"""Validation ของ "การแนะนำพันธุ์ไม้" (routers/recommend/species.py + impact.py) —
ตอบคำถามว่า *รู้ได้อย่างไรว่าควรปลูกต้นไหน* และหลักฐานคืออะไร

ต่างจาก validate_green_area.py (ตรวจค่า green_area_pct) และ validate_recommend.py
(ตรวจ *จุด* ที่แนะนำ) — ไฟล์นี้ตรวจ *ชนิดพันธุ์* ที่แนะนำ 6 ด้าน

  S1 ความถูกต้องของชื่อวิทยาศาสตร์  — เทียบ GBIF Backbone Taxonomy (ชื่อที่ใช้ต้อง
     เป็นชื่อที่ยอมรับ ไม่ใช่ชื่อพ้องหรือสะกดผิด)
  S2 สถานะพื้นเมืองในประเทศไทย      — เทียบ World Checklist of Vascular Plants
     (WCVP, Royal Botanic Gardens Kew) ผ่าน GBIF · ตรวจด้วยว่าพันธุ์ที่ระบบติดป้าย
     "พันธุ์พื้นถิ่น" ตรงกับ WCVP ไหม (ข้อความในระบบ vs ฐานข้อมูลสากล)
  S3 พบจริงในภาคที่แนะนำหรือไม่      — นับ occurrence ของ GBIF ในประเทศไทย แยกราย
     จังหวัด (GADM level 1) แล้วรวมเป็นภาคตามตารางของระบบ · ปรับอคติความพยายาม
     สำรวจ (observer effort) ด้วยสัดส่วน occurrence ของพืชทั้งหมดในภาคนั้นเป็นฐาน
  S4 พฤติกรรมการจัดอันดับ           — ไล่ทุกเงื่อนไขพื้นที่ (ร้อน × NDVI × ประเภท
     ที่ดิน) ทุกภาค แล้ววัดว่าอันดับเปลี่ยนจริงไหม เปลี่ยนไปในทางที่อ้างไว้ไหม และ
     มีกี่คู่ที่คะแนนเสมอกัน (= ลำดับตัดสินด้วยลำดับในตาราง ไม่ใช่สภาพพื้นที่)
  S5 เกณฑ์ตัดสินใช้ได้จริงไหม        — เอาเกณฑ์ HOT_LST_C / LOW_NDVI / HIGH_NDVI
     ไปเทียบค่า LST/NDVI จริงจาก cache ทั้ง 77 จังหวัด และระดับอำเภอ → เกณฑ์ไหน
     แทบไม่เคยทำงาน
  S6 สัมประสิทธิ์ CO2 รายพันธุ์       — ความครอบคลุม + ความสอดคล้องภายในกับความสูง
     ของพันธุ์ (Spearman) + เทียบช่วงค่ากับค่าอ้างอิง IPCC

S1–S3 ต้องต่ออินเทอร์เน็ต (GBIF API) · S4/S6 เป็น pure function ไม่ต้องต่ออะไร ·
S5 อ่าน cache จาก Supabase อย่างเดียว (ไม่เขียน) · ไม่แตะ GEE เลย

Run:
    cd green-area-backend
    python validate_species.py
    python validate_species.py --offline      # ข้าม S1-S3 (ไม่ต่อเน็ต)
    python validate_species.py --year 2025    # ปีของ cache ที่ใช้ตรวจ S5
"""
import argparse
import csv
import json
import logging
import os
import re
import statistics
import sys
import time

import requests
from dotenv import load_dotenv

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
load_dotenv()
logging.basicConfig(level=logging.WARNING)

from impact import IMPACT_DEFAULTS, TREE_CO2_PER_YEAR  # noqa: E402
from landuse import LANDUSE_CATEGORIES  # noqa: E402
from routers.recommend.species import (  # noqa: E402
    HIGH_NDVI, HOT_LST_C, LANDUSE_KEYWORDS, LOW_NDVI, PROVINCE_REGION,
    TREE_SPECIES_BY_REGION, _BIODIV_KEYWORDS, _HARDY_KEYWORDS,
    _SHADE_KEYWORDS, rank_species_by_site)

REPORTS_DIR = os.path.join(os.path.dirname(__file__), "reports")

GBIF = "https://api.gbif.org/v1"
# World Checklist of Vascular Plants (Kew) — datasetKey บน GBIF · เป็นฐานข้อมูล
# เดียวกับที่ Plants of the World Online (POWO) ใช้เผยแพร่ขอบเขตการกระจายพันธุ์
WCVP_DATASET = "f382f0ce-323a-4091-bb9f-add557f3a9a2"
TDWG_THAILAND = "TDWG:THA"
HTTP_TIMEOUT = 60

# ป้ายในระบบที่ "อ้างความเป็นพื้นถิ่น" — ใช้ตรวจ S2 ว่าคำอ้างตรงกับ WCVP ไหม
# ตรวจทั้ง traits + purpose + reason เพราะคำอ้างกระจายอยู่ทั้งสามช่อง (เช่น สัก
# เขียนว่า "พันธุ์พื้นถิ่นภาคเหนือ" ไว้ใน reason ไม่ใช่ traits)
NATIVE_CLAIM_KEYWORDS = ("พื้นถิ่น", "เฉพาะถิ่น", "พันธุ์เด่นของป่า")

# คำในกลุ่ม shade ที่ "อ่อน" — ชนแล้วไม่ได้แปลว่าให้ร่มเงาจริง (เช่น "ทรงพุ่มเป็น
# ระเบียบ" หมายถึงรูปทรงสวย ไม่ใช่ร่มเงากว้าง) · ใช้รายงาน false positive ของ S4
WEAK_SHADE_KEYWORDS = ("ทรงพุ่ม",)

# ชื่อจังหวัดของ GADM ที่สะกดต่างจากตารางของระบบ (PROVINCE_REGION)
GADM_ALIASES = {
    "bangkok": "Bangkok Metropolis",
    "bangkokmetropolis": "Bangkok Metropolis",
    "phangnga": "Phangnga",
    "nakhonratchasima": "Nakhon Ratchasima",
    "buengkan": "Bueng Kan",
    "lopburi": "Lop Buri",
    "chainat": "Chai Nat",
    "singburi": "Sing Buri",
    "angthong": "Ang Thong",
    "ayutthaya": "Phra Nakhon Si Ayutthaya",
    "phranakhonsiayutthaya": "Phra Nakhon Si Ayutthaya",
    "nongbualamphu": "Nong Bua Lam Phu",
    "sisaket": "Si Sa Ket",
    "buriram": "Buri Ram",
}


def _norm(name):
    """ตัดช่องว่าง/ขีด/จุด แล้วทำเป็นตัวพิมพ์เล็ก — ใช้จับคู่ชื่อจังหวัดข้ามแหล่ง"""
    return re.sub(r"[^a-z]", "", (name or "").lower())


_PROVINCE_BY_NORM = {_norm(p): p for p in PROVINCE_REGION}


def _province_from_gadm(name):
    """ชื่อจังหวัดของ GADM → ชื่อในตารางของระบบ (None ถ้าจับคู่ไม่ได้)"""
    n = _norm(name)
    return _PROVINCE_BY_NORM.get(n) or GADM_ALIASES.get(n)


def _get(path, **params):
    r = requests.get(GBIF + path, params=params, timeout=HTTP_TIMEOUT)
    r.raise_for_status()
    return r.json()


def all_species():
    """คืน {scientific: {name_th, regions:[...], species_dict}} — พันธุ์ไม่ซ้ำทั้งระบบ"""
    out = {}
    for region, lst in TREE_SPECIES_BY_REGION.items():
        for sp in lst:
            key = sp["scientific"]
            entry = out.setdefault(key, {"name_th": sp["name_th"], "regions": [],
                                         "sp": sp})
            entry["regions"].append(region)
    return out


# ---------------------------------------------------------------- S1 + S2
def check_taxonomy_and_nativeness(scientific):
    """S1+S2 ของพันธุ์เดียว — ชื่อที่ยอมรับ (GBIF Backbone) + สถานะในไทย (WCVP/Kew)"""
    row = {"scientific": scientific}

    m = _get("/species/match", name=scientific)
    row["gbif_match_type"] = m.get("matchType")
    row["gbif_status"] = m.get("status")
    row["gbif_accepted_name"] = m.get("canonicalName")
    row["gbif_family"] = m.get("family")
    row["gbif_usage_key"] = m.get("usageKey")
    row["name_accepted"] = (m.get("matchType") == "EXACT"
                            and m.get("status") == "ACCEPTED")

    # WCVP — หา taxon ที่ยอมรับในเช็คลิสต์ แล้วอ่านการกระจายพันธุ์ระดับ TDWG
    row["wcvp_key"] = None
    row["in_thailand_wcvp"] = None
    row["establishment_in_thailand"] = None
    try:
        res = _get("/species/search", datasetKey=WCVP_DATASET, q=scientific,
                   rank="SPECIES", limit=20).get("results", [])
        exact = [x for x in res if _norm(x.get("canonicalName")) == _norm(scientific)]
        accepted = next((x for x in exact
                         if x.get("taxonomicStatus") == "ACCEPTED"), None)
        if accepted is None and exact:
            syn = exact[0]
            akey = syn.get("acceptedKey")
            accepted = _get("/species/%d" % akey) if akey else None
        if accepted:
            row["wcvp_key"] = accepted.get("key")
            dists = _get("/species/%d/distributions" % accepted["key"],
                         limit=300).get("results", [])
            tha = [d for d in dists if d.get("locationId") == TDWG_THAILAND]
            row["in_thailand_wcvp"] = bool(tha)
            if tha:
                # WCVP ใส่ INTRODUCED เฉพาะที่นำเข้า — ไม่ใส่ = พื้นเมือง
                means = tha[0].get("establishmentMeans")
                row["establishment_in_thailand"] = means or "NATIVE"
    except Exception as e:  # noqa: BLE001 — รายงานแล้วไปต่อ ไม่ให้ล้มทั้งการตรวจ
        row["wcvp_error"] = str(e)[:200]
    return row


# ---------------------------------------------------------------- S3
def gadm_province_index():
    """{gid: ชื่อจังหวัดในระบบ} ของ GADM level 1 ประเทศไทย"""
    subs = _get("/geocode/gadm/THA/subdivisions")
    idx = {}
    for s in subs:
        if s.get("gadmLevel") != 1:
            continue
        idx[s["id"]] = _province_from_gadm(s.get("name"))
    return idx


def _facet_by_province(gadm_idx, **params):
    """นับ occurrence แยกรายภาคจาก facet gadmGid (เอาเฉพาะ level 1 = THA.N_1)"""
    j = _get("/occurrence/search", country="TH", hasCoordinate="true", limit=0,
             facet="gadmGid", facetLimit=200, **params)
    by_region, unmatched, total = {}, [], 0
    facets = j.get("facets") or []
    counts = facets[0].get("counts", []) if facets else []
    for c in counts:
        gid, n = c["name"], c["count"]
        if gid not in gadm_idx:          # ข้าม THA (ประเทศ) และ level 2/3
            continue
        province = gadm_idx[gid]
        if province is None:
            unmatched.append(gid)
            continue
        region = PROVINCE_REGION.get(province)
        by_region[region] = by_region.get(region, 0) + n
        total += n
    return by_region, total, unmatched


def check_regional_occurrence(scientific, regions, gadm_idx, baseline_share):
    """S3 — พันธุ์นี้ถูกบันทึกพบจริงในภาคที่ระบบแนะนำแค่ไหน (ปรับอคติการสำรวจแล้ว)

    baseline_share: {region: สัดส่วน occurrence ของพืชทั้งหมดในไทยที่อยู่ในภาคนั้น}
    → ratio = สัดส่วนของพันธุ์นี้ในภาค ÷ สัดส่วนพื้นฐาน · >1 = พบมากกว่าที่ควรเป็น
    ตามความพยายามสำรวจ (เป็นการ "ปรับอคติ" อย่างหยาบ ไม่ใช่การสุ่มตัวอย่างเชิงสถิติ)
    """
    by_region, total, unmatched = _facet_by_province(
        gadm_idx, scientificName=scientific)
    row = {"scientific": scientific,
           "recommended_regions": "|".join(sorted(regions)),
           "n_records_th_georef": total,
           "n_unmatched_gid": len(unmatched)}
    in_rec = sum(by_region.get(r, 0) for r in regions)
    row["n_records_in_recommended_regions"] = in_rec
    row["share_in_recommended_regions"] = (round(in_rec / total, 3)
                                           if total else None)
    exp = sum(baseline_share.get(r, 0.0) for r in regions)
    row["expected_share_by_effort"] = round(exp, 3)
    row["effort_adjusted_ratio"] = (round((in_rec / total) / exp, 2)
                                    if total and exp else None)
    for r in sorted(TREE_SPECIES_BY_REGION):
        row["n_" + r] = by_region.get(r, 0)
    return row


# ---------------------------------------------------------------- S4
def _species_text(sp):
    """ข้อความทั้งหมดของพันธุ์ — ตัวเดียวกับที่ _site_fit ใน species.py ใช้ match"""
    return (" ".join(sp.get("traits", [])) + " " + sp.get("purpose", "")
            + " " + sp.get("reason", ""))


def _matched_keywords(sp):
    """คืนว่าข้อความของพันธุ์นี้ไปชนคำค้นกลุ่มไหนบ้าง — ทำให้ตรวจสอบย้อนกลับได้"""
    text = _species_text(sp)
    hit = {
        "shade": [k for k in _SHADE_KEYWORDS if k in text],
        "hardy": [k for k in _HARDY_KEYWORDS if k in text],
        "biodiv": [k for k in _BIODIV_KEYWORDS if k in text],
    }
    for code, (keywords, _why) in LANDUSE_KEYWORDS.items():
        hit["landuse_" + code] = [k for k in keywords if k in text]
    return hit


def ranking_behaviour():
    """S4 — ไล่ทุกเงื่อนไขพื้นที่ทุกภาค วัดว่าอันดับเปลี่ยนจริงไหม/เสมอกันกี่กรณี"""
    landuse_codes = [None] + [c["code"] for c in LANDUSE_CATEGORIES]
    ndvi_cases = {"degraded": LOW_NDVI - 0.05, "mid": (LOW_NDVI + HIGH_NDVI) / 2,
                  "green": HIGH_NDVI + 0.05}
    lst_cases = {"hot": HOT_LST_C + 2.0, "not_hot": HOT_LST_C - 2.0}

    rows = []
    for region, species in sorted(TREE_SPECIES_BY_REGION.items()):
        default_order = [s["scientific"] for s in species]
        for lst_name, lst_val in lst_cases.items():
            for ndvi_name, ndvi_val in ndvi_cases.items():
                for code in landuse_codes:
                    ranked = rank_species_by_site(species, lst_val, ndvi_val, code)
                    order = [s["scientific"] for s in ranked]
                    top = ranked[0]
                    rows.append({
                        "region": region, "lst_case": lst_name,
                        "ndvi_case": ndvi_name, "landuse": code or "-",
                        "changed_from_default": order != default_order,
                        "top_species": top["scientific"],
                        "top_name_th": top["name_th"],
                        "top_has_site_fit": bool(top.get("site_fit")),
                        "top_site_fit": top.get("site_fit") or "",
                        "n_with_site_fit": sum(1 for s in ranked if s.get("site_fit")),
                    })
    return rows


def source_worksheet(tax_rows, occ_rows):
    """ใบงานติดตามแหล่งอ้างอิงรายพันธุ์ — ช่องที่ตรวจได้อัตโนมัติเติมให้แล้ว
    ช่องที่ต้องใส่เอกสารอ้างอิงด้วยมือปล่อยว่างไว้

    เหตุผลที่ต้องมี: บัญชีพันธุ์ไม้ใน TREE_SPECIES_BY_REGION ถูกเขียนลงโค้ดโดยตรง
    ไม่มีการบันทึกแหล่งที่มารายชนิดไว้ที่ใดในรีโปหรือในเล่ม · การตรวจกับ GBIF/WCVP
    ยืนยันได้แค่ว่า "พันธุ์นี้มีจริง ชื่อถูก และพบในภาคนั้น" ไม่ได้ยืนยันว่า
    "คุณสมบัติที่เราเขียน (ทนแล้ง/ทนน้ำท่วม/ความสูง) ถูกต้อง" หรือ "ควรเลือกพันธุ์นี้"
    """
    occ_by = {r["scientific"]: r for r in occ_rows}
    sp_all = all_species()
    rows = []
    for r in sorted(tax_rows, key=lambda x: x["scientific"]):
        sci = r["scientific"]
        sp = sp_all[sci]["sp"]
        o = occ_by.get(sci, {})
        rows.append({
            "name_th": r.get("name_th", ""),
            "scientific": sci,
            "regions": r.get("regions", ""),
            # --- ตรวจแล้วอัตโนมัติ (อ้างอิงได้ทันที) ---
            "gbif_taxon_url": ("https://www.gbif.org/species/%s" % r["gbif_usage_key"]
                               if r.get("gbif_usage_key") else ""),
            "gbif_family": r.get("gbif_family", ""),
            "wcvp_status_thailand": r.get("establishment_in_thailand") or "ไม่มีบันทึกในไทย",
            "gbif_records_in_recommended_regions":
                o.get("n_records_in_recommended_regions", ""),
            # --- คำกล่าวอ้างในระบบที่ยังไม่มีแหล่งอ้างอิง ---
            "claimed_height_m": sp.get("height_m", ""),
            "claimed_traits": " · ".join(sp.get("traits", [])),
            "claimed_purpose": sp.get("purpose", ""),
            "claimed_kg_co2_per_year": TREE_CO2_PER_YEAR.get(sci, ""),
            # --- ช่องที่ต้องกรอกเอง ---
            "source_for_traits": "",
            "source_for_height": "",
            "source_for_co2": "",
            "note": "",
        })
    return rows


EXAMPLE_REGION = "กลาง"
EXAMPLE_LANDUSE = "U"


def ranking_example():
    """ตัวอย่างการจัดอันดับ 1 กรณี (ลำดับตั้งต้น vs ลำดับหลังพิจารณาสภาพพื้นที่).

    เขียนลงไฟล์เพื่อให้สคริปต์สร้างเอกสารหลักฐานอ่านได้โดยไม่ต้อง import โมดูลของระบบ
    (ตัวสร้างเอกสารรันด้วย Python ระบบซึ่งไม่มี dependency ของ backend)
    """
    species = TREE_SPECIES_BY_REGION[EXAMPLE_REGION]
    ranked = rank_species_by_site(species, HOT_LST_C + 2.0, LOW_NDVI - 0.05,
                                  EXAMPLE_LANDUSE)
    return [{"region": EXAMPLE_REGION, "rank": i + 1,
             "lst_used": HOT_LST_C + 2.0, "ndvi_used": round(LOW_NDVI - 0.05, 3),
             "landuse_used": EXAMPLE_LANDUSE,
             "default_name_th": species[i]["name_th"],
             "ranked_name_th": sp["name_th"],
             "site_fit": sp.get("site_fit") or "-"}
            for i, sp in enumerate(ranked)]


def keyword_audit():
    """ตารางตรวจสอบย้อนกลับ: พันธุ์ไหนชนคำไหน (ใช้ดู false positive ของ keyword)"""
    rows = []
    for scientific, info in sorted(all_species().items()):
        hit = _matched_keywords(info["sp"])
        row = {"scientific": scientific, "name_th": info["name_th"],
               "regions": "|".join(sorted(info["regions"]))}
        for group, words in hit.items():
            row[group] = "|".join(words)
        # ชนกลุ่ม shade ด้วยคำอ่อนอย่างเดียว = การจับคู่ที่ตีความเกินข้อความจริง
        row["weak_shade_only"] = bool(
            hit["shade"] and all(w in WEAK_SHADE_KEYWORDS for w in hit["shade"]))
        row["no_keyword_at_all"] = not (hit["shade"] or hit["hardy"] or hit["biodiv"])
        rows.append(row)
    return rows


# ---------------------------------------------------------------- S5
def threshold_reality(year):
    """S5 — เกณฑ์ HOT_LST_C / LOW_NDVI / HIGH_NDVI เทียบค่าจริงจาก cache"""
    from dependencies import supa_call

    def _fetch(table, col):
        try:
            rows = supa_call(lambda s: s.table(table).select(col)
                             .eq("year", year).limit(5000).execute()).data
            return [r[col] for r in rows if r.get(col) is not None]
        except Exception as e:  # noqa: BLE001
            print("   (อ่าน %s ไม่ได้: %s)" % (table, str(e)[:120]))
            return []

    out = {"year": year, "hot_lst_c": HOT_LST_C, "low_ndvi": LOW_NDVI,
           "high_ndvi": HIGH_NDVI}
    for level, lst_t, ndvi_t in (("province", "province_lst_annual", "ndvi_annual"),
                                 ("district", "district_lst_annual",
                                  "district_ndvi_annual")):
        lv = _fetch(lst_t, "lst_mean")
        nv = _fetch(ndvi_t, "ndvi_mean")
        out[level] = {
            "n_lst": len(lv),
            "lst_min": round(min(lv), 2) if lv else None,
            "lst_median": round(statistics.median(lv), 2) if lv else None,
            "lst_max": round(max(lv), 2) if lv else None,
            "pct_hot": round(100 * sum(1 for x in lv if x >= HOT_LST_C) / len(lv), 1)
                       if lv else None,
            "n_ndvi": len(nv),
            "ndvi_min": round(min(nv), 3) if nv else None,
            "ndvi_median": round(statistics.median(nv), 3) if nv else None,
            "ndvi_max": round(max(nv), 3) if nv else None,
            "pct_degraded": round(100 * sum(1 for x in nv if x < LOW_NDVI) / len(nv), 1)
                            if nv else None,
            "pct_green": round(100 * sum(1 for x in nv if x >= HIGH_NDVI) / len(nv), 1)
                         if nv else None,
        }
    return out


# ---------------------------------------------------------------- S6
def _height_mid(sp):
    """กลางช่วงความสูง (เมตร) จากสตริงแบบ "15–25" """
    nums = [float(x) for x in re.findall(r"\d+", sp.get("height_m", ""))]
    return sum(nums) / len(nums) if nums else None


def _spearman(xs, ys):
    """สหสัมพันธ์อันดับ Spearman แบบมือ (ไม่มี scipy ใน env นี้) — จัดการค่าเสมอด้วยอันดับเฉลี่ย"""
    def ranks(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            avg = (i + j) / 2 + 1
            for k in range(i, j + 1):
                r[order[k]] = avg
            i = j + 1
        return r
    rx, ry = ranks(xs), ranks(ys)
    mx, my = statistics.mean(rx), statistics.mean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = (sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry)) ** 0.5
    return num / den if den else None


def co2_coefficients():
    """S6 — ความครอบคลุม + ความสอดคล้องภายในของสัมประสิทธิ์ CO2 รายพันธุ์"""
    sp_all = all_species()
    rows, xs, ys = [], [], []
    for scientific, info in sorted(sp_all.items()):
        kg = TREE_CO2_PER_YEAR.get(scientific)
        h = _height_mid(info["sp"])
        rows.append({"scientific": scientific, "name_th": info["name_th"],
                     "height_m": info["sp"].get("height_m"),
                     "height_mid_m": h, "kg_co2_per_year": kg,
                     "has_coefficient": kg is not None})
        if kg is not None and h is not None:
            xs.append(h)
            ys.append(kg)
    vals = [r["kg_co2_per_year"] for r in rows if r["kg_co2_per_year"] is not None]
    summary = {
        "n_species": len(rows),
        "n_with_coefficient": sum(1 for r in rows if r["has_coefficient"]),
        "kg_min": min(vals) if vals else None,
        "kg_median": statistics.median(vals) if vals else None,
        "kg_max": max(vals) if vals else None,
        "ipcc_default_kg": IMPACT_DEFAULTS["default_kg_co2"],
        "spearman_height_vs_co2": (round(_spearman(xs, ys), 3)
                                   if len(xs) > 2 else None),
        "n_pairs": len(xs),
    }
    return rows, summary


# ---------------------------------------------------------------- io
def _write_csv(rows, path):
    if not rows:
        return
    fields = []
    for r in rows:
        for k in r:
            if k not in fields:
                fields.append(k)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--offline", action="store_true",
                    help="ข้าม S1-S3 (ที่ต้องเรียก GBIF)")
    ap.add_argument("--year", type=int, default=2025,
                    help="ปีของ cache ที่ใช้ตรวจเกณฑ์ใน S5 (default 2025)")
    args = ap.parse_args()

    os.makedirs(REPORTS_DIR, exist_ok=True)
    sp_all = all_species()
    t0 = time.time()
    print("=" * 74)
    print("Validation การแนะนำพันธุ์ไม้ — %d ชนิด, %d ภาค"
          % (len(sp_all), len(TREE_SPECIES_BY_REGION)))
    print("=" * 74)

    tax_rows, occ_rows = [], []
    if not args.offline:
        print("\nS1/S2 ตรวจชื่อวิทยาศาสตร์ + สถานะพื้นเมือง (GBIF + WCVP/Kew)")
        for scientific in sorted(sp_all):
            row = check_taxonomy_and_nativeness(scientific)
            row["name_th"] = sp_all[scientific]["name_th"]
            row["regions"] = "|".join(sorted(sp_all[scientific]["regions"]))
            text = _species_text(sp_all[scientific]["sp"])
            claim = any(k in text for k in NATIVE_CLAIM_KEYWORDS)
            row["system_claims_native"] = claim
            # ขัดแย้ง = ระบบเขียนว่าพื้นถิ่น แต่ WCVP บอกว่านำเข้า หรือไม่มีบันทึกในไทยเลย
            row["claim_conflict"] = bool(
                claim and row.get("establishment_in_thailand") != "NATIVE")
            tax_rows.append(row)
            print("   %-28s %-9s %-9s ไทย=%-5s %s"
                  % (scientific, row["gbif_match_type"], row["gbif_status"],
                     row["in_thailand_wcvp"],
                     row.get("establishment_in_thailand") or "-"))

        print("\nS3 นับ occurrence จริงในไทยรายภาค (GBIF, georeferenced)")
        gadm_idx = gadm_province_index()
        base_by_region, base_total, base_unmatched = _facet_by_province(
            gadm_idx, kingdomKey=6)     # 6 = Plantae ใน GBIF backbone
        baseline_share = {r: (n / base_total if base_total else 0)
                          for r, n in base_by_region.items()}
        print("   ฐานความพยายามสำรวจ (พืชทุกชนิดในไทย %s รายการ): %s"
              % (f"{base_total:,}",
                 ", ".join("%s %.0f%%" % (r, 100 * s)
                           for r, s in sorted(baseline_share.items(),
                                              key=lambda kv: -kv[1]))))
        if base_unmatched:
            print("   (จับคู่ GADM ไม่ได้ %d รหัส)" % len(base_unmatched))
        for scientific, info in sorted(sp_all.items()):
            row = check_regional_occurrence(scientific, info["regions"],
                                            gadm_idx, baseline_share)
            row["name_th"] = info["name_th"]
            occ_rows.append(row)
            print("   %-28s พบในไทย %5d รายการ · อยู่ในภาคที่แนะนำ %s%% · "
                  "ปรับอคติแล้ว %s เท่า"
                  % (scientific, row["n_records_th_georef"],
                     "%.0f" % (100 * row["share_in_recommended_regions"])
                     if row["share_in_recommended_regions"] is not None else "-",
                     row["effort_adjusted_ratio"]))

    print("\nS4 พฤติกรรมการจัดอันดับ (ไล่ทุกเงื่อนไขพื้นที่)")
    beh = ranking_behaviour()
    kw = keyword_audit()
    n_changed = sum(1 for r in beh if r["changed_from_default"])
    print("   กรณีทดสอบทั้งหมด           %d (6 ภาค × ร้อน/ไม่ร้อน × NDVI 3 ระดับ "
          "× ที่ดิน 6 แบบ)" % len(beh))
    print("   อันดับเปลี่ยนจากค่าตั้งต้น   %d (%.0f%%)"
          % (n_changed, 100 * n_changed / len(beh)))
    print("   อันดับ 1 มีเหตุผลกำกับ      %d (%.0f%%)"
          % (sum(1 for r in beh if r["top_has_site_fit"]),
             100 * sum(1 for r in beh if r["top_has_site_fit"]) / len(beh)))
    print("   พันธุ์ที่ได้เหตุผลเฉลี่ยต่อกรณี %.1f จาก 5"
          % statistics.mean(r["n_with_site_fit"] for r in beh))
    # ขอบเขตของการ "เลือกให้เหมาะพื้นที่" — ชุดพันธุ์ผูกกับภาคล้วน สภาพพื้นที่เปลี่ยน
    # ได้แค่ "ลำดับ" ในชุดเดิม จึงต้องรายงานว่าเลือกได้กว้างแค่ไหนจริง
    reachable_top = {r["top_species"] for r in beh}
    print("   ชุดพันธุ์ที่เป็นไปได้ทั้งประเทศ %d ชุด (สำหรับ %d จังหวัด) — ผูกกับภาคล้วน"
          % (len(TREE_SPECIES_BY_REGION), len(PROVINCE_REGION)))
    print("   พันธุ์ที่ขึ้นอันดับ 1 ได้จริง  %d จาก %d ชนิด"
          % (len(reachable_top), len(sp_all)))
    weak = [r["name_th"] for r in kw if r["weak_shade_only"]]
    none_kw = [r["name_th"] for r in kw if r["no_keyword_at_all"]]
    print("   จับคู่ 'ร่มเงา' ด้วยคำอ่อนอย่างเดียว %s"
          % (", ".join(weak) if weak else "ไม่มี"))
    print("   ไม่ชนคำค้นใดเลย (ไม่เคยได้แต้มสภาพพื้นที่) %s"
          % (", ".join(none_kw) if none_kw else "ไม่มี"))

    print("\nS5 เกณฑ์ตัดสินเทียบข้อมูลจริง ปี %d" % args.year)
    thr = threshold_reality(args.year)
    for level in ("province", "district"):
        d = thr[level]
        if d["n_lst"]:
            print("   %-9s LST  n=%-5d มัธยฐาน %.1f C  → เข้าเกณฑ์ร้อน (>=%.0f) %.1f%%"
                  % (level, d["n_lst"], d["lst_median"], HOT_LST_C, d["pct_hot"]))
        if d["n_ndvi"]:
            print("   %-9s NDVI n=%-5d มัธยฐาน %.2f    → เสื่อมโทรม (<%.2f) %.1f%% · "
                  "เขียว (>=%.2f) %.1f%%"
                  % (level, d["n_ndvi"], d["ndvi_median"], LOW_NDVI,
                     d["pct_degraded"], HIGH_NDVI, d["pct_green"]))

    print("\nS6 สัมประสิทธิ์ CO2 รายพันธุ์")
    co2_rows, co2_sum = co2_coefficients()
    print("   มีค่าสัมประสิทธิ์          %d/%d ชนิด"
          % (co2_sum["n_with_coefficient"], co2_sum["n_species"]))
    print("   ช่วงค่า                  %.0f-%.0f kg CO2/ต้น/ปี (มัธยฐาน %.0f · "
          "ค่าตั้งต้น IPCC %.0f)"
          % (co2_sum["kg_min"], co2_sum["kg_max"], co2_sum["kg_median"],
             co2_sum["ipcc_default_kg"]))
    print("   สอดคล้องกับความสูงพันธุ์   Spearman rho = %s (n=%d คู่)"
          % (co2_sum["spearman_height_vs_co2"], co2_sum["n_pairs"]))

    paths = []
    if tax_rows:
        p = os.path.join(REPORTS_DIR, "species_taxonomy.csv")
        _write_csv(tax_rows, p)
        paths.append(p)
    if occ_rows:
        p = os.path.join(REPORTS_DIR, "species_regional_occurrence.csv")
        _write_csv(occ_rows, p)
        paths.append(p)
    if tax_rows:
        p = os.path.join(REPORTS_DIR, "species_source_worksheet.csv")
        _write_csv(source_worksheet(tax_rows, occ_rows), p)
        paths.append(p)
    for rows, name in ((beh, "species_ranking_behaviour.csv"),
                       (kw, "species_keyword_audit.csv"),
                       (ranking_example(), "species_ranking_example.csv"),
                       (co2_rows, "species_co2_coefficients.csv")):
        p = os.path.join(REPORTS_DIR, name)
        _write_csv(rows, p)
        paths.append(p)
    p = os.path.join(REPORTS_DIR, "species_thresholds_%d.json" % args.year)
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"thresholds": thr, "co2_summary": co2_sum,
                   "ranking_summary": {
                       "n_cases": len(beh), "n_changed": n_changed,
                       "n_top_with_reason": sum(1 for r in beh
                                                if r["top_has_site_fit"]),
                       "n_reachable_top": len(reachable_top),
                       "n_regions": len(TREE_SPECIES_BY_REGION),
                       "n_provinces": len(PROVINCE_REGION),
                       "n_species": len(sp_all),
                       "pct_changed": round(100 * n_changed / len(beh), 1)}},
                  f, ensure_ascii=False, indent=2)
    paths.append(p)

    print("\nรวม %.0f วินาที" % (time.time() - t0))
    print("บันทึกผลที่")
    for p in paths:
        print("   " + p)


if __name__ == "__main__":
    main()
