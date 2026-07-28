"""NFR-08 — สคริปต์ validation: เทียบ green_area_pct (NDVI) กับ ESA WorldCover
ทุกจังหวัด แล้วรายงานค่าความคลาดเคลื่อน เทียบเป้าหมาย ±10 จุด% (ดู validation.py
สำหรับนิยาม/เหตุผลของวิธีเทียบ)

รันที่ปี WorldCover epoch (2021) เป็นค่าเริ่มต้น เพื่อตัดตัวแปรการเปลี่ยนแปลง
พื้นที่ระหว่างปีออก — ให้ความต่างที่วัดได้สะท้อน "ความคลาดเคลื่อนของวิธีวัด"
ล้วนๆ ไม่ปนกับ "การเปลี่ยนแปลงจริงของพื้นที่สีเขียว"

คำนวณสดจาก GEE ทุกจังหวัด ไม่แตะ Supabase เลย (ไม่อ่าน ไม่เขียน cache) — รันซ้ำได้
เสมอโดยไม่มีผลข้างเคียง · เหตุผลที่ไม่ใช้ cache อยู่ใน docstring ของ validate_province

Run:
    cd green-area-backend
    python validate_green_area.py                # ปี 2021 (WorldCover epoch), ทุกจังหวัด
    python validate_green_area.py --year 2022     # ปีอื่น (เห็น note เตือน epoch offset)
    python validate_green_area.py --limit 5       # ทดสอบเร็วกับ 5 จังหวัดแรก
"""
import argparse
import csv
import logging
import os
import statistics
import sys

import ee
from dotenv import load_dotenv

# UTF-8 stdout — รองรับ emoji + ไทย บน Windows console (เหมือน main.py)
try:
    sys.stdout.reconfigure(encoding='utf-8')
except (AttributeError, OSError):
    pass

load_dotenv()
logging.basicConfig(level=logging.WARNING)  # เงียบ log INFO ของ dependencies/routers
logger = logging.getLogger("validate_green_area")
logger.setLevel(logging.INFO)

from dependencies import PROVINCE_GEOMETRIES  # noqa: E402
from routers.ndvi.compute import _compute_ndvi_annual  # noqa: E402
from validation import (WORLDCOVER_GREEN_CLASSES,  # noqa: E402
                        WORLDCOVER_NONGREEN_CLASSES, build_breakdown,
                        build_validation, validation_area_sums)

PROVINCE_SCALE_M = 500  # สเกลเดียวกับที่ /ndvi/{province} ใช้จริง (routers/ndvi/endpoints.py)

REPORTS_DIR = os.path.join(os.path.dirname(__file__), "reports")


def validate_province(province: str, year: int) -> dict:
    """คำนวณ NDVI + band validation ทั้งหมดใน reduceRegion ก้อนเดียว.

    ไม่อ่าน cache: การแยกสาเหตุรายคลาสต้องใช้ *ตัว green_mask* ไม่ใช่แค่ตัวเลข
    green_area_pct ที่ cache เก็บไว้ จึงต้องคำนวณ composite ใหม่อยู่ดี — และการ
    คำนวณสดยังตัดความเสี่ยงที่จะไปให้คะแนน cache row เก่าที่ระบบเองจะ recompute
    ก่อนผู้ใช้เห็น (ดู _is_stale)
    """
    geom = ee.Geometry(PROVINCE_GEOMETRIES[province])

    ndvi_result = _compute_ndvi_annual(geom, year, scale=PROVINCE_SCALE_M,
                                       extra_sums_fn=validation_area_sums)
    if ndvi_result is None:
        return {"province": province, "available": False,
                "note": f"ไม่มีภาพ Sentinel-2 พอสำหรับปี {year}"}

    sums = ndvi_result["extra_area_sums"]
    total_area_m2 = ndvi_result["total_area_m2_raw"]
    wc_m2 = sums.get("worldcover_green_area")
    wc_pct = None if wc_m2 is None or not total_area_m2 else wc_m2 / total_area_m2 * 100
    breakdown = build_breakdown(sums, total_area_m2)
    out = build_validation(ndvi_result["green_area_pct"], wc_pct, year,
                           breakdown=breakdown)
    out["province"] = province
    return out


def _write_csv(rows: list[dict], out_path: str) -> None:
    """แผ่ breakdown ออกเป็นคอลัมน์รายคลาส — pivot ต่อใน Excel เพื่อทำตาราง/กราฟ
    ลงรูปเล่มได้เลย โดยไม่ต้องแกะ JSON ซ้อน"""
    class_cols = ([f"fn_{c}" for c in WORLDCOVER_GREEN_CLASSES]
                  + [f"fp_{c}" for c in WORLDCOVER_NONGREEN_CLASSES])
    fieldnames = (["province", "available", "ndvi_green_pct", "worldcover_green_pct",
                   "error_pp", "within_target", "false_negative_pp", "false_positive_pp",
                   "net_pp", "reference_scale_delta_pp", "dominant_class", "dominant_pp"]
                  + class_cols + ["note"])

    flat_rows = []
    for row in rows:
        flat = dict(row)
        breakdown = row.get("breakdown") or {}
        for key in ("false_negative_pp", "false_positive_pp", "net_pp",
                    "reference_scale_delta_pp"):
            flat[key] = breakdown.get(key)
        dominant = breakdown.get("dominant")
        if dominant:
            flat["dominant_class"] = dominant["name"]
            flat["dominant_pp"] = dominant["pp"]
        for entry in breakdown.get("by_class", []):
            prefix = "fn" if entry["kind"] == "false_negative" else "fp"
            flat[f"{prefix}_{entry['code']}"] = entry["pp"]
        flat_rows.append(flat)

    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(flat_rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--year", type=int, default=2021,
                        help="ปีที่เทียบ (default: 2021 = WorldCover epoch)")
    parser.add_argument("--limit", type=int, default=None,
                        help="จำกัดจำนวนจังหวัด (สำหรับทดสอบเร็ว)")
    args = parser.parse_args()

    gee_project = os.getenv("GEE_PROJECT")
    if not gee_project:
        print("❌ GEE_PROJECT ไม่ถูกตั้งใน .env")
        sys.exit(1)
    ee.Initialize(project=gee_project)

    provinces = sorted(PROVINCE_GEOMETRIES.keys())
    if args.limit:
        provinces = provinces[:args.limit]

    rows = []
    for i, province in enumerate(provinces, 1):
        print(f"⏳ [{i}/{len(provinces)}] {province} ...", end=" ", flush=True)
        try:
            out = validate_province(province, args.year)
        except Exception as e:
            print(f"❌ error: {e}")
            rows.append({"province": province, "available": False, "note": str(e)})
            continue
        if not out.get("available"):
            print(f"⚠️  {out.get('note')}")
        else:
            top = (out.get("breakdown") or {}).get("dominant")
            cause = f" · หลัก: {top['name']} {top['pp']:.1f}pp" if top else ""
            print(f"NDVI={out['ndvi_green_pct']:.1f}% WC={out['worldcover_green_pct']:.1f}% "
                 f"error={out['error_pp']:+.1f}pp "
                 f"{'✅' if out['within_target'] else '❌'}{cause}")
        rows.append(out)

    os.makedirs(REPORTS_DIR, exist_ok=True)
    out_path = os.path.join(REPORTS_DIR, f"nfr08_validation_{args.year}.csv")
    _write_csv(rows, out_path)

    available = [r for r in rows if r.get("available")]
    print(f"\n{'='*70}\nสรุปผล NFR-08 — validation ปี {args.year} "
         f"({len(available)}/{len(rows)} จังหวัดมีข้อมูล)\n{'='*70}")
    if available:
        errors = [r["error_pp"] for r in available]
        abs_errors = [abs(e) for e in errors]
        within = sum(1 for r in available if r["within_target"])
        mean_err = statistics.mean(errors)
        mae = statistics.mean(abs_errors)
        rmse = (sum(e ** 2 for e in errors) / len(errors)) ** 0.5
        worst = max(available, key=lambda r: abs(r["error_pp"]))
        print(f"Mean error:        {mean_err:+.2f} จุด%  (bias: {'NDVI สูงกว่า' if mean_err > 0 else 'NDVI ต่ำกว่า'})")
        print(f"MAE:               {mae:.2f} จุด%")
        print(f"RMSE:              {rmse:.2f} จุด%")
        print(f"ผ่านเป้า ±10 จุด%:   {within}/{len(available)} จังหวัด ({100*within/len(available):.0f}%)")
        print(f"คลาดเคลื่อนสูงสุด:   {worst['province']} ({worst['error_pp']:+.1f} จุด%)")

        # แยกสาเหตุระดับประเทศ — เฉลี่ยส่วนร่วมของแต่ละคลาสข้ามจังหวัด
        totals: dict[str, list[float]] = {}
        for row in available:
            for entry in (row.get("breakdown") or {}).get("by_class", []):
                key = f"{entry['name']} [{'WC เขียว/NDVI ไม่เขียว' if entry['kind'] == 'false_negative' else 'NDVI เขียว/WC ไม่เขียว'}]"
                totals.setdefault(key, []).append(entry["pp"])
        if totals:
            print("\nแยกสาเหตุ (เฉลี่ยจุด% ต่อจังหวัดที่พบคลาสนั้น · เรียงจากมากไปน้อย):")
            ranked = sorted(totals.items(),
                            key=lambda kv: statistics.mean(kv[1]), reverse=True)
            for name, values in ranked[:6]:
                print(f"  {statistics.mean(values):5.1f} จุด%  {name}  "
                      f"({len(values)} จังหวัด)")
    print(f"\n✅ บันทึกผลรายจังหวัดที่ {out_path}")


if __name__ == "__main__":
    main()
