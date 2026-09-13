"""Validation ของเครื่องมือ "แนะนำจุดปลูก" (FR-20/21/22 + FR-26) — ตรวจว่าจุดที่ระบบ
แนะนำเชื่อถือได้แค่ไหน ด้วยการวัดผลจริงจาก GEE ไม่ใช่การอ่านโค้ด

ตรวจ 5 กลุ่ม (คนละเรื่องกับ NFR-08 ที่ตรวจ "ค่า green_area_pct" — ดู validate_green_area.py)

  A. ข้อจำกัดเชิงพื้นที่ (hard constraint) — จุดแนะนำต้องไม่ตกบนน้ำ/อาคาร/ป่าเดิม/
     พื้นที่ชุ่มน้ำ และความชันต้องไม่เกิน MAX_SLOPE_DEG · ตรวจโดย sample ค่า
     ESA WorldCover + ความชัน SRTM *ที่พิกัดจุดแนะนำจริง* ทั้งที่สเกล 10 m (native
     ของ WorldCover) และ 200 m (สเกลที่ engine ใช้ sample) → เห็นผลของ scale ด้วย
  B. อำนาจจำแนก (discriminant) — จุดที่แนะนำต้อง "ขาดแคลนกว่า" พื้นที่ปลูกได้ทั่วไป
     อย่างมีนัย ไม่ใช่จุดสุ่ม · เทียบคะแนน priority ของจุดแนะนำกับ distribution ของ
     พื้นที่ปลูกได้ทั้งจังหวัด (เปอร์เซ็นไทล์ + สัดส่วนพื้นที่ที่คะแนนสูงกว่าจุดแนะนำ
     ต่ำสุด) และเทียบค่าเฉลี่ยรายปัจจัย
  C. ความสามารถทำซ้ำ (reproducibility) — รันซ้ำต้องได้จุดเดิมทุกพิกัด (seed คงที่)
  D. ความไวต่อค่าถ่วงน้ำหนัก (sensitivity) — ค่าถ่วงน้ำหนักเป็น "การตัดสินใจเชิง
     นโยบาย" ไม่ได้มาจากการ fit ข้อมูล จึงต้องรายงานว่าถ้าเปลี่ยนน้ำหนักแล้วคำตอบ
     เปลี่ยนแค่ไหน (ชุดน้ำหนักสุดขั้ว 4 แบบเทียบ baseline)
  E. ตรวจแบบไม่ใช้ GEE (โครงสร้างข้อมูล) — ความครอบคลุมของตารางพันธุ์ไม้ 77 จังหวัด
     และ traceability ของสัมประสิทธิ์ CO2 ทุกพันธุ์

คำนวณสดจาก GEE ทุกจังหวัด ไม่แตะ Supabase cache — รันซ้ำได้เสมอโดยไม่มีผลข้างเคียง

Run:
    cd green-area-backend
    python validate_recommend.py                     # ชุดจังหวัดมาตรฐาน 12 จังหวัด ปี 2024
    python validate_recommend.py --year 2023
    python validate_recommend.py --provinces Lamphun # เฉพาะบางจังหวัด (ทดสอบเร็ว)
    python validate_recommend.py --skip-sensitivity  # ข้ามกลุ่ม D (ช้าสุด)
"""
import argparse
import csv
import json
import logging
import os
import statistics
import sys
import time

import ee
from dotenv import load_dotenv

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
load_dotenv()
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("validate_recommend")
logger.setLevel(logging.INFO)

from canopy import WORLDCOVER_ASSET  # noqa: E402
from dependencies import PROVINCE_GEOMETRIES  # noqa: E402
from impact import TREE_CO2_PER_YEAR  # noqa: E402
from routers.recommend.scoring import (  # noqa: E402
    ESA_NON_PLANTABLE_CLASSES, MAX_SLOPE_DEG, TOP_MIN_SEPARATION_M,
    W_ACCESS, W_LST, W_NDVI, W_POP, _haversine_m,
    compute_priority, get_top_locations)
from routers.recommend.species import (  # noqa: E402
    PROVINCE_REGION, TREE_SPECIES_BY_REGION)

REPORTS_DIR = os.path.join(os.path.dirname(__file__), "reports")
SAMPLE_SCALE_M = 200      # สเกลเดียวกับที่ get_top_locations ใช้ sample จริง
TOP_N = 10                # จำนวนจุดแนะนำต่อพื้นที่ (เท่ากับที่ endpoint ใช้จริง)

# ชุดจังหวัดมาตรฐาน — ครบ 6 ภาค ภาคละ 2 จังหวัด คละขนาด/ความเป็นเมือง
DEFAULT_PROVINCES = [
    "Bangkok Metropolis", "Nakhon Sawan",        # กลาง (เมืองใหญ่สุด / เมืองรอง)
    "Chiang Mai", "Lamphun",                     # เหนือ (ใหญ่ / เล็ก)
    "Khon Kaen", "Nakhon Ratchasima",            # อีสาน
    "Chon Buri", "Rayong",                       # ตะวันออก (อุตสาหกรรม)
    "Kanchanaburi", "Phetchaburi",               # ตะวันตก
    "Songkhla", "Phuket",                        # ใต้ (ใหญ่ / เกาะ)
]

# กลุ่ม D — ชุดน้ำหนักที่ใช้ทดสอบความไว (w_ndvi, w_lst, w_pop, w_access)
WEIGHT_SETS = {
    "baseline":   (W_NDVI, W_LST, W_POP, W_ACCESS),
    "equal":      (0.25, 0.25, 0.25, 0.25),
    "ndvi_heavy": (0.70, 0.10, 0.10, 0.10),
    "lst_heavy":  (0.10, 0.70, 0.10, 0.10),
    "pop_heavy":  (0.10, 0.10, 0.70, 0.10),
}
# ระยะที่ถือว่า "จุดเดียวกัน/ย่านเดียวกัน" เวลาเทียบผลระหว่างชุดน้ำหนัก
SAME_SPOT_M = TOP_MIN_SEPARATION_M   # 750 m — ระยะขั้นต่ำระหว่างจุดแนะนำ
SAME_AREA_M = 2000.0                 # 2 km — ระดับ "ย่านเดียวกัน"

FACTOR_KEYS = ["ndvi_deficit", "lst_heat", "pop_need", "access_need",
               "peri_urban", "feasibility"]
# ชื่อ band ที่ scoring ตั้งไว้ (peri_urban/feasibility ใน factors ↔ band peri_need/feasibility)
FACTOR_BANDS = {"ndvi_deficit": "ndvi_deficit", "lst_heat": "lst_heat",
                "pop_need": "pop_need", "access_need": "access_need",
                "peri_urban": "peri_need", "feasibility": "feasibility"}


# ---------------------------------------------------------------- helpers
def _min_pairwise_separation_m(points):
    """ระยะห่างที่น้อยที่สุดระหว่างจุดแนะนำคู่ใดคู่หนึ่ง — ใช้ตรวจข้อ A3"""
    if len(points) < 2:
        return float("inf")
    return min(_haversine_m(a["lat"], a["lng"], b["lat"], b["lng"])
               for i, a in enumerate(points) for b in points[i + 1:])


def _nearest_distance_m(point, others):
    """ระยะถึงจุดที่ใกล้ที่สุดใน others — ใช้ทั้ง A3 และ D (เทียบชุดน้ำหนัก)"""
    if not others:
        return float("inf")
    return min(_haversine_m(point["lat"], point["lng"], o["lat"], o["lng"])
               for o in others)


def _sample_landcover_slope(points, scale):
    """sample ค่า ESA WorldCover + ความชัน SRTM ที่พิกัดจุดแนะนำ (1 roundtrip).

    ใช้ตรวจข้อ A แบบ "ตรวจผลลัพธ์" ไม่ใช่ "ตรวจว่าโค้ดเรียก mask ไหม" — ถ้า
    plantable_mask ทำงานจริง จุดที่คืนมาต้องไม่มีคลาสห้ามปลูกและความชันไม่เกินเกณฑ์

    scale: 10 = native ของ WorldCover (เข้มที่สุด) · 200 = สเกลที่ engine sample จริง
    คืน list เรียงตาม idx เดิม (sampleRegions ไม่รับประกันลำดับ จึง map กลับด้วย idx)
    """
    fc = ee.FeatureCollection([
        ee.Feature(ee.Geometry.Point([p["lng"], p["lat"]]), {"idx": i})
        for i, p in enumerate(points)])
    wc = ee.ImageCollection(WORLDCOVER_ASSET).first().rename("wc")
    slope = ee.Terrain.slope(ee.Image("USGS/SRTMGL1_003")).rename("slope")
    info = (wc.addBands(slope)
            .sampleRegions(collection=fc, scale=scale, geometries=False)
            .getInfo())
    out = [None] * len(points)
    for feat in info.get("features", []):
        p = feat["properties"]
        out[int(p["idx"])] = {"wc": p.get("wc"), "slope": p.get("slope")}
    return [o or {"wc": None, "slope": None} for o in out]


def _area_stats(priority, factors, plantable, geom, min_top_score):
    """สถิติของ "พื้นที่ปลูกได้ทั้งจังหวัด" สำหรับเทียบกับจุดแนะนำ (กลุ่ม B) — 1 roundtrip.

    - pct: เปอร์เซ็นไทล์ 50/90/99 ของ priority บนพื้นที่ปลูกได้
    - frac_ge_min: สัดส่วนพื้นที่ปลูกได้ที่คะแนน >= คะแนนต่ำสุดของจุดแนะนำ
      (mean ของภาพ 0/1 บน mask = สัดส่วนพิกเซล) → "จุดแนะนำอยู่ท็อปกี่ %"
    - means: ค่าเฉลี่ยรายปัจจัยบนพื้นที่ปลูกได้ (baseline ไว้เทียบกับจุดแนะนำ)
    """
    pp = priority.updateMask(plantable)
    stack = pp.rename("priority")
    for key in FACTOR_KEYS:
        stack = stack.addBands(factors[key].updateMask(plantable))
    common = dict(geometry=geom, scale=SAMPLE_SCALE_M, maxPixels=int(1e10),
                  bestEffort=True)
    payload = ee.Dictionary({
        "pct": pp.reduceRegion(reducer=ee.Reducer.percentile([50, 90, 99]), **common),
        "frac_ge_min": pp.gte(min_top_score).reduceRegion(
            reducer=ee.Reducer.mean(), **common),
        "means": stack.reduceRegion(reducer=ee.Reducer.mean(), **common),
    })
    return payload.getInfo()


def _top_for_weights(geom, year, weights):
    """คำนวณจุดแนะนำ TOP_N จุดด้วยชุดน้ำหนักที่กำหนด (ใช้ทั้งกลุ่ม C และ D)"""
    (priority, nd, lh, pn, an, pen, fn, plantable, landuse) = compute_priority(
        geom, year, *weights)
    return get_top_locations(priority, nd, lh, pn, an, pen, fn, geom, plantable,
                             n=TOP_N, landuse=landuse)


# ---------------------------------------------------------------- per province
def validate_province(province, year, sensitivity, reproducibility):
    """ตรวจ 1 จังหวัด — คืน (summary, point_rows, sensitivity_rows)"""
    geom = ee.Geometry(PROVINCE_GEOMETRIES[province])
    t0 = time.time()

    (priority, nd, lh, pn, an, pen, fn, plantable, landuse) = compute_priority(
        geom, year, *WEIGHT_SETS["baseline"])
    factors = {"ndvi_deficit": nd, "lst_heat": lh, "pop_need": pn,
               "access_need": an, "peri_urban": pen, "feasibility": fn}
    top = get_top_locations(priority, nd, lh, pn, an, pen, fn, geom, plantable,
                            n=TOP_N, landuse=landuse)
    if not top:
        return ({"province": province, "year": year, "ok": False,
                 "note": "ไม่มีจุดแนะนำคืนมา"}, [], [])

    scores = [p["score"] for p in top]
    min_score = min(scores)

    # --- A: ข้อจำกัดเชิงพื้นที่
    at10 = _sample_landcover_slope(top, 10)
    at200 = _sample_landcover_slope(top, SAMPLE_SCALE_M)

    # --- B: เทียบกับพื้นที่ปลูกได้ทั้งจังหวัด
    stats = _area_stats(priority, factors, plantable, geom, min_score)
    pct = stats["pct"]
    means = stats["means"]
    frac = stats["frac_ge_min"].get("priority")

    point_rows = []
    n_bad_class10 = n_bad_class200 = n_bad_slope = 0
    for i, p in enumerate(top):
        wc10, slope10 = at10[i]["wc"], at10[i]["slope"]
        wc200 = at200[i]["wc"]
        bad10 = wc10 in ESA_NON_PLANTABLE_CLASSES
        bad200 = wc200 in ESA_NON_PLANTABLE_CLASSES
        bad_slope = slope10 is not None and slope10 > MAX_SLOPE_DEG
        n_bad_class10 += bad10
        n_bad_class200 += bad200
        n_bad_slope += bad_slope
        row = {
            "province": province, "year": year, "rank": i + 1,
            "lat": p["lat"], "lng": p["lng"], "score": p["score"],
            "worldcover_class_10m": wc10, "worldcover_class_200m": wc200,
            "slope_deg": round(slope10, 2) if slope10 is not None else None,
            "plantable_ok_10m": not (bad10 or bad_slope),
            "plantable_ok_200m": not (bad200 or bad_slope),
            "nearest_other_point_m": round(_nearest_distance_m(
                p, [q for j, q in enumerate(top) if j != i])),
            "landuse_code": (p.get("landuse") or {}).get("code"),
        }
        row.update({"f_" + k: p["factors"][k] for k in FACTOR_KEYS})
        point_rows.append(row)

    top_factor_means = {k: statistics.mean(p["factors"][k] for p in top)
                        for k in FACTOR_KEYS}
    area_factor_means = {k: means.get(FACTOR_BANDS[k]) for k in FACTOR_KEYS}

    min_sep = _min_pairwise_separation_m(top)
    summary = {
        "province": province, "year": year, "ok": True, "n_points": len(top),
        # A
        "n_violate_class_10m": n_bad_class10,
        "n_violate_class_200m": n_bad_class200,
        "n_violate_slope": n_bad_slope,
        "min_separation_m": round(min_sep),
        "separation_ok": min_sep >= TOP_MIN_SEPARATION_M,
        # B
        "score_min": round(min_score, 3),
        "score_median": round(statistics.median(scores), 3),
        "score_max": round(max(scores), 3),
        "area_p50": round(pct.get("priority_p50") or 0, 3),
        "area_p90": round(pct.get("priority_p90") or 0, 3),
        "area_p99": round(pct.get("priority_p99") or 0, 3),
        "frac_area_ge_score_min": round(frac, 6) if frac is not None else None,
        "top_percentile": round(100 * frac, 3) if frac is not None else None,
    }
    for k in FACTOR_KEYS:
        summary["top_" + k] = round(top_factor_means[k], 3)
        av = area_factor_means[k]
        summary["area_" + k] = round(av, 3) if av is not None else None
        summary["delta_" + k] = (round(top_factor_means[k] - av, 3)
                                 if av is not None else None)

    # --- C: ทำซ้ำได้ไหม
    if reproducibility:
        top2 = _top_for_weights(geom, year, WEIGHT_SETS["baseline"])
        summary["reproducible"] = (len(top2) == len(top) and all(
            a["lat"] == b["lat"] and a["lng"] == b["lng"] and a["score"] == b["score"]
            for a, b in zip(top, top2)))
    else:
        summary["reproducible"] = None

    # --- D: ความไวต่อค่าถ่วงน้ำหนัก
    sens_rows = []
    if sensitivity:
        for name, weights in WEIGHT_SETS.items():
            if name == "baseline":
                continue
            alt = _top_for_weights(geom, year, weights)
            d = [_nearest_distance_m(p, top) for p in alt]
            sens_rows.append({
                "province": province, "year": year, "weight_set": name,
                "w_ndvi": weights[0], "w_lst": weights[1],
                "w_pop": weights[2], "w_access": weights[3],
                "n_points": len(alt),
                "n_within_750m": sum(1 for x in d if x <= SAME_SPOT_M),
                "n_within_2km": sum(1 for x in d if x <= SAME_AREA_M),
                "median_dist_to_baseline_m": round(statistics.median(d)) if d else None,
                "max_dist_to_baseline_m": round(max(d)) if d else None,
                "score_mean": (round(statistics.mean(p["score"] for p in alt), 3)
                               if alt else None),
            })

    summary["elapsed_s"] = round(time.time() - t0, 1)
    return summary, point_rows, sens_rows


# ---------------------------------------------------------------- group E (no GEE)
def structural_checks():
    """ตรวจโครงสร้างข้อมูลที่ไม่ต้องใช้ GEE — ความครอบคลุมพันธุ์ไม้ + traceability CO2"""
    provinces = sorted(PROVINCE_GEOMETRIES.keys())
    missing_region = [p for p in provinces if p not in PROVINCE_REGION]
    regions_without_species = [r for r in set(PROVINCE_REGION.values())
                               if not TREE_SPECIES_BY_REGION.get(r)]
    all_species = {sp["scientific"]: sp["name_th"]
                   for lst in TREE_SPECIES_BY_REGION.values() for sp in lst}
    species_without_co2 = sorted(s for s in all_species
                                 if s not in TREE_CO2_PER_YEAR)
    return {
        "n_provinces": len(provinces),
        "n_provinces_without_region": len(missing_region),
        "provinces_without_region": missing_region,
        "n_regions": len(TREE_SPECIES_BY_REGION),
        "species_per_region": {r: len(lst)
                               for r, lst in TREE_SPECIES_BY_REGION.items()},
        "n_unique_species": len(all_species),
        "n_species_without_co2_coefficient": len(species_without_co2),
        "species_without_co2_coefficient": species_without_co2,
        "regions_without_species": regions_without_species,
    }


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
    ap.add_argument("--year", type=int, default=2024)
    ap.add_argument("--provinces", nargs="*", default=None,
                    help="ระบุจังหวัดเอง (default: ชุดมาตรฐาน 12 จังหวัด 6 ภาค)")
    ap.add_argument("--skip-sensitivity", action="store_true",
                    help="ข้ามกลุ่ม D (ช้าสุด — 4 การคำนวณเพิ่มต่อจังหวัด)")
    ap.add_argument("--sensitivity-limit", type=int, default=4,
                    help="ทำกลุ่ม D เฉพาะ N จังหวัดแรก (default 4)")
    ap.add_argument("--repro-limit", type=int, default=3,
                    help="ทำกลุ่ม C เฉพาะ N จังหวัดแรก (default 3)")
    args = ap.parse_args()

    gee_project = os.getenv("GEE_PROJECT")
    if not gee_project:
        print("GEE_PROJECT ไม่ถูกตั้งใน .env")
        sys.exit(1)
    ee.Initialize(project=gee_project)

    provinces = args.provinces or DEFAULT_PROVINCES
    unknown = [p for p in provinces if p not in PROVINCE_GEOMETRIES]
    if unknown:
        print("ไม่รู้จักจังหวัด: %s" % unknown)
        sys.exit(1)

    summaries, points, sens = [], [], []
    t_start = time.time()
    for i, province in enumerate(provinces, 1):
        print("[%d/%d] %s ..." % (i, len(provinces), province), end=" ", flush=True)
        try:
            s, prow, srow = validate_province(
                province, args.year,
                sensitivity=(not args.skip_sensitivity) and i <= args.sensitivity_limit,
                reproducibility=i <= args.repro_limit)
        except Exception as e:
            print("ERROR: %s" % e)
            summaries.append({"province": province, "year": args.year,
                              "ok": False, "note": str(e)})
            continue
        summaries.append(s)
        points.extend(prow)
        sens.extend(srow)
        if s.get("ok"):
            print("top=%.3f-%.3f (บนสุด %.2f%% ของพื้นที่ปลูกได้) · ผิดข้อจำกัด %d/%d · "
                  "ห่างต่ำสุด %d m · %.0fs"
                  % (s["score_min"], s["score_max"], s["top_percentile"],
                     s["n_violate_class_10m"], s["n_points"],
                     s["min_separation_m"], s["elapsed_s"]))

    os.makedirs(REPORTS_DIR, exist_ok=True)
    suffix = str(args.year)
    p_sum = os.path.join(REPORTS_DIR, "recommend_validation_%s.csv" % suffix)
    p_pts = os.path.join(REPORTS_DIR, "recommend_points_%s.csv" % suffix)
    p_sen = os.path.join(REPORTS_DIR, "recommend_sensitivity_%s.csv" % suffix)
    _write_csv(summaries, p_sum)
    _write_csv(points, p_pts)
    _write_csv(sens, p_sen)

    struct = structural_checks()
    p_struct = os.path.join(REPORTS_DIR, "recommend_structural_%s.json" % suffix)
    with open(p_struct, "w", encoding="utf-8") as f:
        json.dump(struct, f, ensure_ascii=False, indent=2)

    ok = [s for s in summaries if s.get("ok")]
    print("\n" + "=" * 74)
    print("สรุปผล validation เครื่องมือแนะนำจุดปลูก ปี %d (%d/%d จังหวัดคำนวณสำเร็จ)"
          % (args.year, len(ok), len(summaries)))
    print("=" * 74)
    if ok:
        n_pts = sum(s["n_points"] for s in ok)
        print("A. ข้อจำกัดเชิงพื้นที่")
        print("   จุดแนะนำทั้งหมด             %d จุด" % n_pts)
        print("   ตกบนคลาสห้ามปลูก (10 m)    %d จุด"
              % sum(s["n_violate_class_10m"] for s in ok))
        print("   ตกบนคลาสห้ามปลูก (200 m)   %d จุด"
              % sum(s["n_violate_class_200m"] for s in ok))
        print("   ความชันเกิน %d องศา          %d จุด"
              % (MAX_SLOPE_DEG, sum(s["n_violate_slope"] for s in ok)))
        print("   ระยะห่างขั้นต่ำผ่านเกณฑ์      %d/%d จังหวัด (ต่ำสุด %d m)"
              % (sum(1 for s in ok if s["separation_ok"]), len(ok),
                 min(s["min_separation_m"] for s in ok)))
        tp = [s["top_percentile"] for s in ok if s["top_percentile"] is not None]
        print("\nB. อำนาจจำแนก")
        if tp:
            print("   จุดแนะนำอยู่ในกลุ่มบนสุด     %.2f%% ของพื้นที่ปลูกได้ (แย่สุด %.2f%%)"
                  % (statistics.mean(tp), max(tp)))
        for k in FACTOR_KEYS:
            d = [s["delta_" + k] for s in ok if s.get("delta_" + k) is not None]
            if d:
                print("   delta %-14s %+.3f (จุดแนะนำ - ค่าเฉลี่ยพื้นที่ปลูกได้)"
                      % (k, statistics.mean(d)))
        repro = [s for s in ok if s.get("reproducible") is not None]
        if repro:
            print("\nC. ทำซ้ำได้      %d/%d จังหวัด ได้พิกัดเดิมครบทุกจุด"
                  % (sum(1 for s in repro if s["reproducible"]), len(repro)))
        if sens:
            print("\nD. ความไวต่อค่าถ่วงน้ำหนัก (เทียบ baseline)")
            for name in WEIGHT_SETS:
                rs = [r for r in sens if r["weight_set"] == name]
                if not rs:
                    continue
                tot = sum(r["n_points"] for r in rs)
                print("   %-11s ตรงจุดเดิม <=750 m %d/%d · <=2 km %d/%d · "
                      "มัธยฐานระยะเบี่ยง %.0f m"
                      % (name, sum(r["n_within_750m"] for r in rs), tot,
                         sum(r["n_within_2km"] for r in rs), tot,
                         statistics.median([r["median_dist_to_baseline_m"] for r in rs])))
    print("\nE. โครงสร้างข้อมูล (ไม่ใช้ GEE)")
    print("   จังหวัดที่จับคู่ภาคไม่ได้       %d/%d"
          % (struct["n_provinces_without_region"], struct["n_provinces"]))
    print("   พันธุ์ไม้ที่ไม่มีสัมประสิทธิ์ CO2  %d/%d"
          % (struct["n_species_without_co2_coefficient"], struct["n_unique_species"]))
    print("\nรวม %.0f วินาที" % (time.time() - t_start))
    print("บันทึกผลที่\n   %s\n   %s\n   %s\n   %s"
          % (p_sum, p_pts, p_sen, p_struct))


if __name__ == "__main__":
    main()
