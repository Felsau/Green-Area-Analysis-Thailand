"""สร้าง/อัปเดต data/tree_species.json — บัญชีพันธุ์ไม้ที่ผูกกับฐานข้อมูลพฤกษศาสตร์จริง

เดิมบัญชีพันธุ์ไม้ถูกเขียนเป็นตัวแปรคงที่ในโค้ด (TREE_SPECIES_BY_REGION) โดยไม่มี
การบันทึกแหล่งที่มารายชนิด — ตอบไม่ได้ว่า "ข้อมูลต้นไม้มาจากไหน" · สคริปต์นี้ย้าย
บัญชีออกมาเป็นไฟล์ข้อมูล และแนบผลการตรวจสอบจากฐานข้อมูลอิสระ 3 แหล่งให้ทุกชนิด

  BGCI GlobalTreeSearch  ยืนยันว่า "เป็นไม้ยืนต้นจริง" + ถิ่นกำเนิดระดับประเทศ
                         (บัญชีไม้ยืนต้นมาตรฐานที่ IUCN ใช้อ้างอิง)
  Kew WCVP (ผ่าน GBIF)   สถานะพื้นเมือง/นำเข้า ในประเทศไทย
  GBIF Occurrence        จำนวนบันทึกการพบจริงในไทย และในภาคที่ระบบแนะนำ
  GBIF Backbone          ชื่อวิทยาศาสตร์ที่ยอมรับ + วงศ์

ฟิลด์ที่เป็น "ข้อมูลของโครงงาน" (name_th/traits/purpose/reason/height_m) สคริปต์
ไม่แตะ — คัดลอกต่อจากไฟล์เดิม · เขียนทับเฉพาะบล็อก verification

ครั้งแรกที่ยังไม่มีไฟล์ json จะอ่านบัญชีตั้งต้นจาก LEGACY_SPECIES ใน species.py
(bootstrap) · หลังจากนั้นอ่านจาก json เสมอ

Run:
    cd green-area-backend
    python refresh_species_verification.py
    python refresh_species_verification.py --check   # ตรวจอย่างเดียว ไม่เขียนไฟล์
"""
import argparse
import datetime
import json
import os
import re
import sys

import requests

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "data", "tree_species.json")

GBIF = "https://api.gbif.org/v1"
BGCI_COUNTRY = "https://data.bgci.org/treesearch/country/Thailand"
BGCI_GENUS = "https://data.bgci.org/treesearch/genus/%s"
# World Checklist of Vascular Plants (Kew) บน GBIF — แหล่งเดียวกับที่ POWO เผยแพร่
WCVP_DATASET = "f382f0ce-323a-4091-bb9f-add557f3a9a2"
TDWG_THAILAND = "TDWG:THA"
PLANTAE_KEY = 6
HTTP_TIMEOUT = 90
UA = {"User-Agent": "GreenLens/1.0 (thesis research; contact via repository)"}

SOURCE_CITATIONS = {
    "bgci": "BGCI GlobalTreeSearch — Botanic Gardens Conservation International, "
            "https://tools.bgci.org/global_tree_search.php",
    "wcvp": "World Checklist of Vascular Plants (WCVP), Royal Botanic Gardens Kew, "
            "เข้าถึงผ่าน GBIF dataset " + WCVP_DATASET,
    "gbif_backbone": "GBIF Backbone Taxonomy, https://doi.org/10.15468/39omei",
    "gbif_occurrence": "GBIF Occurrence Search API, https://www.gbif.org/",
}

GADM_ALIASES = {
    "bangkok": "Bangkok Metropolis",
    "ayutthaya": "Phra Nakhon Si Ayutthaya",
}


def _norm(name):
    return re.sub(r"[^a-z]", "", (name or "").lower())


def _get(url, **params):
    r = requests.get(url, params=params or None, headers=UA, timeout=HTTP_TIMEOUT)
    r.raise_for_status()
    return r.json()


# ---------------------------------------------------------------- แหล่งข้อมูล
def bgci_thailand_trees():
    """{ชื่อวิทยาศาสตร์: แถวของ BGCI} ของไม้ยืนต้นที่ BGCI บันทึกว่าพบในไทย"""
    return {r["taxon"]: r for r in _get(BGCI_COUNTRY).get("results", [])}


def bgci_native_range(scientific):
    """ถิ่นกำเนิดระดับประเทศจาก BGCI (ใช้กับชนิดที่ไม่ได้อยู่ในบัญชีของไทย)"""
    genus = scientific.split()[0]
    for row in _get(BGCI_GENUS % genus).get("results", []):
        if row.get("taxon") == scientific:
            seen, out = set(), []
            for g in row.get("TSGeolinks", []):
                c = g.get("country")
                if c and c not in seen:
                    seen.add(c)
                    out.append(c)
            return out, True
    return [], False


def gbif_backbone(scientific):
    m = _get(GBIF + "/species/match", name=scientific)
    return {
        "usage_key": m.get("usageKey"),
        "accepted_name": m.get("canonicalName"),
        "family": m.get("family"),
        "match_type": m.get("matchType"),
        "name_status": m.get("status"),
    }


def wcvp_thailand_status(scientific):
    """สถานะในไทยตาม WCVP — 'NATIVE' / 'INTRODUCED' / None (ไม่มีบันทึกในไทย)"""
    res = _get(GBIF + "/species/search", datasetKey=WCVP_DATASET, q=scientific,
               rank="SPECIES", limit=20).get("results", [])
    exact = [x for x in res if _norm(x.get("canonicalName")) == _norm(scientific)]
    accepted = next((x for x in exact if x.get("taxonomicStatus") == "ACCEPTED"), None)
    if accepted is None and exact:
        akey = exact[0].get("acceptedKey")
        accepted = _get(GBIF + "/species/%d" % akey) if akey else None
    if not accepted:
        return None
    for d in _get(GBIF + "/species/%d/distributions" % accepted["key"],
                  limit=300).get("results", []):
        if d.get("locationId") == TDWG_THAILAND:
            # WCVP ใส่ INTRODUCED เฉพาะที่นำเข้า — ไม่ใส่ = พื้นเมือง
            return d.get("establishmentMeans") or "NATIVE"
    return None


def gadm_province_index():
    """{gid ระดับ 1: ชื่อจังหวัดแบบที่ระบบใช้}"""
    idx = {}
    for s in _get(GBIF + "/geocode/gadm/THA/subdivisions"):
        if s.get("gadmLevel") != 1:
            continue
        n = _norm(s.get("name"))
        idx[s["id"]] = GADM_ALIASES.get(n) or s.get("name")
    return idx


def gbif_records_by_region(scientific, gadm_idx, province_region):
    """(จำนวนบันทึกในไทย, {ภาค: จำนวน}) — facet รายจังหวัดแล้วรวมเป็นภาค"""
    j = _get(GBIF + "/occurrence/search", scientificName=scientific, country="TH",
             hasCoordinate="true", limit=0, facet="gadmGid", facetLimit=200,
             kingdomKey=PLANTAE_KEY)
    facets = j.get("facets") or []
    counts = facets[0].get("counts", []) if facets else []
    by_region, total = {}, 0
    for c in counts:
        province = gadm_idx.get(c["name"])
        if province is None:
            continue                      # ข้าม THA (ประเทศ) และระดับอำเภอ/ตำบล
        region = province_region.get(province)
        if region is None:
            continue
        by_region[region] = by_region.get(region, 0) + c["count"]
        total += c["count"]
    return total, by_region


# ---------------------------------------------------------------- บัญชีตั้งต้น
def load_curated():
    """คืน {ภาค: [พันธุ์...]} จากไฟล์ json ถ้ามี · ครั้งแรกอ่านจากบัญชีตั้งต้นในโค้ด"""
    if os.path.exists(DATA_PATH):
        with open(DATA_PATH, encoding="utf-8") as f:
            return json.load(f)["regions"]
    # bootstrap ครั้งแรก (ตอนไฟล์ยังไม่ถูกสร้าง) — หลังจากนี้ species.py อ่านจาก json
    from routers.recommend.species import TREE_SPECIES_BY_REGION
    print("   (ยังไม่มี %s — สร้างใหม่จากบัญชีตั้งต้น)" % os.path.basename(DATA_PATH))
    return TREE_SPECIES_BY_REGION


CURATED_KEYS = ("name_th", "scientific", "purpose", "height_m", "traits", "reason")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true",
                    help="ตรวจอย่างเดียว ไม่เขียนไฟล์")
    args = ap.parse_args()

    regions = load_curated()
    from routers.recommend.species import PROVINCE_REGION

    print("ดึงบัญชีไม้ยืนต้นของไทยจาก BGCI GlobalTreeSearch ...", end=" ", flush=True)
    th_trees = bgci_thailand_trees()
    print("%d ชนิด" % len(th_trees))
    gadm_idx = gadm_province_index()

    # พันธุ์เดียวกันอยู่ได้หลายภาค — ตรวจครั้งเดียวแล้วใช้ซ้ำ
    cache, n_species = {}, 0
    out_regions = {}
    for region in sorted(regions):
        out_list = []
        for sp in regions[region]:
            sci = sp["scientific"]
            if sci not in cache:
                bb = gbif_backbone(sci)
                wcvp = wcvp_thailand_status(sci)
                total, by_region = gbif_records_by_region(sci, gadm_idx,
                                                          PROVINCE_REGION)
                native_th = sci in th_trees
                native_range, in_bgci = ([], True) if native_th else bgci_native_range(sci)
                cache[sci] = {
                    "gbif_usage_key": bb["usage_key"],
                    "gbif_url": ("https://www.gbif.org/species/%s" % bb["usage_key"]
                                 if bb["usage_key"] else None),
                    "gbif_accepted_name": bb["accepted_name"],
                    "gbif_family": bb["family"],
                    "gbif_name_status": bb["name_status"],
                    "gbif_match_type": bb["match_type"],
                    "bgci_is_tree": bool(native_th or in_bgci),
                    "bgci_native_to_thailand": native_th,
                    "bgci_native_range": native_range,
                    "wcvp_thailand": wcvp,
                    "gbif_records_thailand": total,
                    "gbif_records_by_region": by_region,
                }
                n_species += 1
                v = cache[sci]
                print("   %-28s %-9s %-11s ไทย=%-5s พบในไทย %d"
                      % (sci, v["gbif_name_status"],
                         v["wcvp_thailand"] or "ไม่มีบันทึก",
                         v["bgci_native_to_thailand"], v["gbif_records_thailand"]))
            v = dict(cache[sci])
            v["gbif_records_in_this_region"] = v["gbif_records_by_region"].get(region, 0)
            entry = {k: sp[k] for k in CURATED_KEYS if k in sp}
            entry["verification"] = v
            out_list.append(entry)
        out_regions[region] = out_list

    payload = {
        "_comment": "บัญชีพันธุ์ไม้ที่ระบบแนะนำ — ฟิลด์ curated เป็นข้อมูลของโครงงาน "
                    "ส่วน verification สร้างอัตโนมัติด้วย refresh_species_verification.py "
                    "จากฐานข้อมูลภายนอก ห้ามแก้ด้วยมือ",
        "generated_at": datetime.date.today().isoformat(),
        "sources": SOURCE_CITATIONS,
        "regions": out_regions,
    }

    n_native = sum(1 for v in cache.values() if v["bgci_native_to_thailand"])
    n_tree = sum(1 for v in cache.values() if v["bgci_is_tree"])
    print("\nสรุป: %d ชนิด · BGCI ยืนยันเป็นไม้ยืนต้น %d · เป็นไม้ยืนต้นของไทย %d · "
          "นำเข้า/ปลูกเลี้ยง %d" % (n_species, n_tree, n_native, n_species - n_native))

    if args.check:
        print("(--check: ไม่เขียนไฟล์)")
        return
    os.makedirs(os.path.dirname(DATA_PATH), exist_ok=True)
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print("บันทึกที่ %s" % DATA_PATH)


if __name__ == "__main__":
    main()
