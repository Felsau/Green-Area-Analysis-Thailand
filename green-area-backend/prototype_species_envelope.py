"""ต้นแบบ (ยังไม่ใช่ระบบจริง) — จับคู่พันธุ์ไม้กับ "สภาพของจุดนั้นจริง ๆ"

คำถามที่ต้นแบบนี้ตอบ: ถ้าเลิกผูกพันธุ์ไม้กับ "ภาค" แล้วหันมาจับคู่ด้วยสภาพภูมิอากาศ
ที่วัดได้ของแต่ละจุด คำตอบจะเปลี่ยนจริงไหม และเปลี่ยนไปในทางที่สมเหตุสมผลไหม
ถ้าไม่เปลี่ยน = ไม่ต้องเสียเวลาทำของจริง

วิธี (environmental envelope / niche matching — ไม่ใช่ AI ไม่มีการเดา)
  1. ดึงพิกัดที่ "พบพันธุ์นั้นจริง" จาก GBIF ในไทยและประเทศเพื่อนบ้าน
  2. เอาพิกัดเหล่านั้นไป sample ชั้นข้อมูลภูมิอากาศบน GEE (WorldClim BIO + SRTM)
     → ได้ช่วงสภาพที่พันธุ์นี้ขึ้นได้จริง เป็นตัวเลข ไม่ใช่คำว่า "ทนแล้ง"
  3. sample ชั้นเดียวกันที่จุดที่ระบบแนะนำจริง แล้วให้คะแนนความเข้ากัน
  4. เทียบอันดับใหม่กับอันดับที่ระบบให้อยู่ตอนนี้

ขอบเขตต้นแบบ: ภาคเหนือ · จุดทดสอบคือจุดที่ระบบแนะนำจริง (เชียงใหม่ + ลำพูน ปี 2024)
อ่านจาก reports/recommend_points_2024.csv

ข้อจำกัดที่ต้องรู้: envelope บอกว่า "ขึ้นได้ไหม" ไม่ได้บอกว่า "เหมาะกับทางเท้าไหม"
(รากดันทางเท้า ผลหล่น มีพิษ) — เรื่องพวกนั้นยังต้องมาจากคู่มือของหน่วยงาน

Run:
    cd green-area-backend
    python prototype_species_envelope.py
    python prototype_species_envelope.py --region ใต้     # ลองภาคอื่น
"""
import argparse
import csv
import io
import json
import logging
import os
import statistics
import sys
import time

import ee
import requests
from dotenv import load_dotenv

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
load_dotenv()
logging.basicConfig(level=logging.WARNING)

from routers.recommend.species import (TREE_SPECIES_BY_REGION,  # noqa: E402
                                       rank_species_by_site)

REPORTS_DIR = os.path.join(os.path.dirname(__file__), "reports")
POINTS_CSV = os.path.join(REPORTS_DIR, "recommend_points_2024.csv")

# ประเทศที่ใช้เก็บพิกัดการพบ — จำกัดไว้ในภูมิภาคเดียวกัน เพื่อไม่ให้ต้นที่ถูกนำไปปลูก
# ทั่วโลก (เช่น สัก) ลาก envelope ไปกินสภาพที่ไม่เกี่ยวกับไทย
REGION_COUNTRIES = ["TH", "LA", "MM", "KH", "VN", "MY"]
MAX_OCCURRENCES = 200          # ต่อชนิด — พอสำหรับหาเปอร์เซ็นไทล์ ไม่หนักเกินไป
ENVELOPE_LOW, ENVELOPE_HIGH = 10, 90   # ตัดหางสองข้างกันจุดผิดพลาด/ต้นที่ปลูกนอกถิ่น

# ตัวแปรสภาพแวดล้อม — WorldClim V1 BIO เป็นชุดมาตรฐานของงาน niche modelling
# bio01/bio05 เก็บเป็น °C ×10 · เลือก 4 ตัวที่ตรงกับสิ่งที่คำบรรยายพันธุ์ไม้อ้าง
VARIABLES = [
    ("bio01", "อุณหภูมิเฉลี่ยทั้งปี (°C)", 0.1),
    ("bio05", "อุณหภูมิสูงสุดเดือนร้อนสุด (°C)", 0.1),
    ("bio12", "ปริมาณฝนทั้งปี (มม.)", 1.0),
    ("bio14", "ฝนเดือนที่แล้งสุด (มม.)", 1.0),   # ← ตัวที่แทน "ทนแล้ง" ได้ตรงที่สุด
    ("elev", "ความสูงจากระดับน้ำทะเล (ม.)", 1.0),
]


def env_image():
    """ภาพรวมตัวแปรสภาพแวดล้อมทั้งหมดในภาพเดียว (sample ทีเดียวได้ครบ)"""
    bio = ee.Image("WORLDCLIM/V1/BIO").select(
        ["bio01", "bio05", "bio12", "bio14"])
    elev = ee.Image("USGS/SRTMGL1_003").rename("elev")
    return bio.addBands(elev)


def fetch_occurrences(scientific, limit=MAX_OCCURRENCES):
    """พิกัดที่พบพันธุ์นั้นจริงจาก GBIF (เฉพาะที่มีพิกัดและอยู่ในภูมิภาค)"""
    out, offset = [], 0
    while len(out) < limit:
        j = requests.get(
            "https://api.gbif.org/v1/occurrence/search",
            params={"scientificName": scientific, "hasCoordinate": "true",
                    "country": REGION_COUNTRIES, "limit": 300, "offset": offset},
            timeout=90).json()
        for rec in j.get("results", []):
            lat, lng = rec.get("decimalLatitude"), rec.get("decimalLongitude")
            if lat is not None and lng is not None:
                out.append((lat, lng))
                if len(out) >= limit:
                    break
        if j.get("endOfRecords") or not j.get("results"):
            break
        offset += 300
    return out


def sample_points(points, tag_key="idx"):
    """sample ตัวแปรสภาพแวดล้อมที่ชุดพิกัด — 1 roundtrip

    points: list ของ (lat, lng, tag) · คืน {tag: [ค่าต่อ VARIABLES]}
    """
    feats = [ee.Feature(ee.Geometry.Point([lng, lat]), {tag_key: tag})
             for lat, lng, tag in points]
    info = (env_image().sampleRegions(
        collection=ee.FeatureCollection(feats), scale=1000, geometries=False)
        .getInfo())
    out = {}
    for f in info.get("features", []):
        p = f["properties"]
        vals = []
        for band, _label, scale in VARIABLES:
            v = p.get(band)
            vals.append(None if v is None else v * scale)
        if all(v is not None for v in vals):
            out.setdefault(p[tag_key], []).append(vals)
    return out


def build_envelope(samples):
    """ช่วงสภาพที่พันธุ์นี้ขึ้นจริง — เปอร์เซ็นไทล์ 10–90 ของแต่ละตัวแปร"""
    env = []
    for i, (_band, label, _s) in enumerate(VARIABLES):
        col = sorted(row[i] for row in samples)
        if not col:
            env.append(None)
            continue
        lo = col[max(0, int(len(col) * ENVELOPE_LOW / 100) - 1)]
        hi = col[min(len(col) - 1, int(len(col) * ENVELOPE_HIGH / 100))]
        env.append({"label": label, "lo": lo, "hi": hi,
                    "median": statistics.median(col), "n": len(col)})
    return env


def match_score(env, point_vals):
    """คะแนนความเข้ากัน 0–1 — อยู่ในช่วง = 1, ออกนอกช่วงลดลงตามระยะที่เกิน

    ใช้ความกว้างของช่วงเป็นหน่วยวัดระยะ เพื่อให้ตัวแปรที่ช่วงกว้าง (ฝน) กับแคบ
    (อุณหภูมิ) เทียบกันได้ · คืน (คะแนนรวม, [คะแนนรายตัวแปร])
    """
    per_var = []
    for e, x in zip(env, point_vals):
        if e is None or x is None:
            per_var.append(None)
            continue
        width = max(e["hi"] - e["lo"], 1e-6)
        if e["lo"] <= x <= e["hi"]:
            per_var.append(1.0)
        else:
            dist = (e["lo"] - x) if x < e["lo"] else (x - e["hi"])
            per_var.append(max(0.0, 1.0 - dist / width))
    valid = [s for s in per_var if s is not None]
    return (sum(valid) / len(valid) if valid else 0.0), per_var


def load_test_points(provinces):
    """จุดที่ระบบแนะนำจริง จากผลการ validate ล่าสุด"""
    with io.open(POINTS_CSV, encoding="utf-8-sig") as f:
        rows = [r for r in csv.DictReader(f) if r["province"] in provinces]
    return [{"province": r["province"], "rank": int(r["rank"]),
             "lat": float(r["lat"]), "lng": float(r["lng"]),
             "landuse": r["landuse_code"], "score": float(r["score"])}
            for r in rows]


def all_species_with_home():
    """พันธุ์ทั้งหมดไม่ซ้ำ + จำว่าเดิมอยู่ภาคไหน (ชนิดเดียวอยู่ได้หลายภาค)"""
    out, home = [], {}
    for region, lst in TREE_SPECIES_BY_REGION.items():
        for sp in lst:
            sci = sp["scientific"]
            if sci in home:
                home[sci] += "+" + region
            else:
                out.append(sp)
                home[sci] = region
    return out, home


def run_pool_test(args):
    """ทดสอบที่สอง — ถ้าปล่อยให้เลือกจากพันธุ์ทั้งประเทศ envelope แยกแยะได้ไหม

    วัดสองอย่าง: พันธุ์ของภาคนั้นถูกดันขึ้นมาแค่ไหน (เทียบกับการสุ่ม) และพันธุ์ของ
    ภาคที่ไกลที่สุด (ใต้) ถูกผลักลงไปแค่ไหน
    """
    allsp, home = all_species_with_home()
    print("=" * 78)
    print("ทดสอบที่ 2 — จัดอันดับจากพันธุ์ทั้งประเทศ %d ชนิด ที่จุดของภาค%s"
          % (len(allsp), args.region))
    print("=" * 78)
    occ = []
    for i, sp in enumerate(allsp):
        pts = fetch_occurrences(sp["scientific"])
        occ += [(la, ln, str(i)) for la, ln in pts]
        print("    %-12s %4d จุด" % (sp["name_th"][:12], len(pts)), flush=True)
    by = sample_points(occ)
    env = {i: build_envelope(by.get(str(i), [])) for i in range(len(allsp))}

    test = load_test_points(args.provinces)
    sampled = sample_points([(p["lat"], p["lng"], str(k))
                             for k, p in enumerate(test)])
    in_region = {s["name_th"] for s in TREE_SPECIES_BY_REGION[args.region]}
    far_region = {s["name_th"] for s in TREE_SPECIES_BY_REGION["ใต้"]}

    top5_hits, ranks_in, ranks_far = [], [], []
    print()
    print("    %-9s %-4s %-44s %s"
          % ("จังหวัด", "จุด", "5 อันดับแรก", "เป็นพันธุ์ของภาคนี้"))
    for k, p in enumerate(test):
        vals = sampled.get(str(k), [[None] * len(VARIABLES)])[0]
        sc = sorted(((match_score(env[i], vals)[0], allsp[i]["name_th"])
                     for i in range(len(allsp))), key=lambda t: -t[0])
        n_hit = sum(1 for _s, n in sc[:5] if n in in_region)
        top5_hits.append(n_hit)
        for pos, (_s, n) in enumerate(sc, 1):
            if n in in_region:
                ranks_in.append(pos)
            if n in far_region:
                ranks_far.append(pos)
        print("    %-9s %-4d %-44s %d/5"
              % (p["province"][:9], p["rank"],
                 ", ".join("%s(%.2f)" % (n[:9], s) for s, n in sc[:5])[:44], n_hit))

    random_rank = (len(allsp) + 1) / 2
    print()
    print("    ใน 5 อันดับแรกเป็นพันธุ์ของภาคนี้เฉลี่ย %.1f/5"
          % statistics.mean(top5_hits))
    print("    อันดับเฉลี่ยของพันธุ์ภาคนี้      %.1f  (สุ่มจะได้ %.1f)"
          % (statistics.mean(ranks_in), random_rank))
    print("    อันดับเฉลี่ยของพันธุ์ภาคใต้     %.1f  (ยิ่งมากยิ่งแปลว่าถูกปฏิเสธ)"
          % statistics.mean(ranks_far))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--region", default="เหนือ")
    ap.add_argument("--provinces", nargs="*", default=["Chiang Mai", "Lamphun"])
    ap.add_argument("--pool", action="store_true",
                    help="เทียบกับพันธุ์ทั้ง 21 ชนิดทั้งประเทศ แทนที่จะเทียบแค่ในภาค")
    args = ap.parse_args()

    ee.Initialize(project=os.getenv("GEE_PROJECT"))
    if args.pool:
        run_pool_test(args)
        return

    species = TREE_SPECIES_BY_REGION[args.region]
    t0 = time.time()

    print("=" * 78)
    print("ต้นแบบจับคู่พันธุ์ไม้กับสภาพจุด — ภาค%s (%d ชนิด)"
          % (args.region, len(species)))
    print("=" * 78)

    # --- 1. พิกัดที่พบจริง
    print("\n[1] ดึงพิกัดที่พบจริงจาก GBIF (%s)" % ", ".join(REGION_COUNTRIES))
    occ_points = []
    for i, sp in enumerate(species):
        pts = fetch_occurrences(sp["scientific"])
        occ_points += [(lat, lng, str(i)) for lat, lng in pts]
        print("    %-12s %-26s %4d จุด" % (sp["name_th"][:12], sp["scientific"],
                                            len(pts)))

    # --- 2. สร้าง envelope
    print("\n[2] sample ชั้นภูมิอากาศที่พิกัดเหล่านั้น (%d จุด)" % len(occ_points))
    by_species = sample_points(occ_points)
    envelopes = {}
    for i, sp in enumerate(species):
        envelopes[i] = build_envelope(by_species.get(str(i), []))

    print("\n[3] ช่วงสภาพที่แต่ละพันธุ์ขึ้นได้จริง (เปอร์เซ็นไทล์ %d–%d)"
          % (ENVELOPE_LOW, ENVELOPE_HIGH))
    header = "    %-12s" % "ชนิด" + "".join("%-22s" % v[1][:21] for v in VARIABLES)
    print(header)
    for i, sp in enumerate(species):
        cells = ""
        for e in envelopes[i]:
            cells += "%-22s" % ("%.0f–%.0f" % (e["lo"], e["hi"]) if e else "-")
        print("    %-12s%s" % (sp["name_th"][:12], cells))

    # --- 4. จุดทดสอบ
    test = load_test_points(args.provinces)
    print("\n[4] จุดที่ระบบแนะนำจริง %d จุด (%s)"
          % (len(test), ", ".join(args.provinces)))
    tp = [(p["lat"], p["lng"], str(k)) for k, p in enumerate(test)]
    sampled = sample_points(tp)

    # อันดับที่ระบบให้ตอนนี้ — ผูกกับภาค ไม่ได้ดูจุด (ใช้ค่าจังหวัดเหมือน endpoint จริง)
    current = [s["name_th"] for s in rank_species_by_site(species, None, None, None)]

    print("\n[5] เทียบอันดับ 1: ระบบปัจจุบัน vs จับคู่ตามสภาพจุด")
    print("    ระบบปัจจุบันให้อันดับ 1 เป็น '%s' เหมือนกันทุกจุด (ผูกกับภาค)"
          % current[0])
    print()
    print("    %-9s %-5s %-7s %-6s %-13s %-6s %s"
          % ("จังหวัด", "จุด", "สูง(ม.)", "ฝน", "อันดับ 1 ใหม่", "คะแนน", "เปลี่ยนไหม"))
    rows_out, n_changed = [], 0
    for k, p in enumerate(test):
        vals = sampled.get(str(k), [[None] * len(VARIABLES)])[0]
        scored = []
        for i, sp in enumerate(species):
            s, per_var = match_score(envelopes[i], vals)
            scored.append((s, sp["name_th"], per_var))
        scored.sort(key=lambda t: -t[0])
        top = scored[0]
        changed = top[1] != current[0]
        n_changed += changed
        print("    %-9s %-5d %-7s %-6s %-13s %-6.2f %s"
              % (p["province"][:9], p["rank"],
                 "%.0f" % vals[4] if vals[4] is not None else "-",
                 "%.0f" % vals[2] if vals[2] is not None else "-",
                 top[1][:13], top[0], "เปลี่ยน" if changed else "เหมือนเดิม"))
        rows_out.append({
            "province": p["province"], "point_rank": p["rank"],
            "lat": p["lat"], "lng": p["lng"], "landuse": p["landuse"],
            **{VARIABLES[i][0]: vals[i] for i in range(len(VARIABLES))},
            "current_top1": current[0], "envelope_top1": top[1],
            "envelope_top1_score": round(top[0], 3),
            "changed": changed,
            "envelope_ranking": " > ".join("%s(%.2f)" % (n, s)
                                           for s, n, _ in scored),
        })

    print("\n" + "=" * 78)
    print("สรุป: อันดับ 1 เปลี่ยนไป %d จาก %d จุด (%.0f%%)"
          % (n_changed, len(test), 100 * n_changed / len(test)))
    distinct = {r["envelope_top1"] for r in rows_out}
    print("      วิธีใหม่ให้อันดับ 1 ต่างกัน %d ชนิด · วิธีเดิมให้ชนิดเดียวทุกจุด"
          % len(distinct))
    print("=" * 78)

    out_path = os.path.join(REPORTS_DIR, "prototype_envelope_%s.csv" % args.region)
    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows_out[0].keys()))
        w.writeheader()
        w.writerows(rows_out)
    env_path = os.path.join(REPORTS_DIR, "prototype_envelope_%s.json" % args.region)
    with open(env_path, "w", encoding="utf-8") as f:
        json.dump({sp["name_th"]: envelopes[i] for i, sp in enumerate(species)},
                  f, ensure_ascii=False, indent=2)
    print("ใช้เวลา %.0f วินาที · บันทึกที่\n   %s\n   %s"
          % (time.time() - t0, out_path, env_path))


if __name__ == "__main__":
    main()
