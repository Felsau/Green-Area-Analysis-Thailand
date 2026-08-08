"""อุ่นแคชล่วงหน้าก่อนเดโม — กันหน้าจอค้างรอ GEE compute สด 30–60 วิ

ตรวจ Supabase จริง (4 ส.ค. 2569) พบว่า 165/170 แถวของ `ndvi_annual` จะถูกมองว่า
stale โดย `_is_stale()` (ขาด `validation`/`data_quality`/`canopy` หรือ
`cache_version` เก่า) รวมทั้ง 77/77 จังหวัดของปีปัจจุบันด้วย — เปิดจังหวัดไหนก่อน
ก็ตกไป recompute สดตอนนั้น ส่วน LST ไม่มี staleness check (แคชค้างตลอดไปจนกว่าจะ
ลบ) แต่ปี 2025 (ปีล่าสุดที่ข้อมูลครบ) ยังไม่มีแคชเลยสักแถว

สคริปต์นี้ไม่คำนวณเอง — เรียก endpoint จริงผ่าน TestClient ในโพรเซสเดียวกัน
ให้ endpoint ตัดสินใจเองว่า cache ที่มีพอหรือต้อง recompute เพื่อไม่ให้ตรรกะใน
สคริปต์เพี้ยนไปจากของจริงที่ผู้ใช้เจอ — แถวที่ fresh อยู่แล้วจะข้ามแทบไม่เสียเวลา
ซ้ำสคริปต์ได้เรื่อยๆ (idempotent) และถูกฆ่ากลางทางแล้วรันต่อได้โดยไม่เสียงานเดิม

ชั้นข้อมูล (`--layer`):
    ndvi / lst          ระดับจังหวัด — 77 รายการต่อปีต่อชั้น
    urban               urban subset (FR-12) เทียบ WHO ในเขต built-up เท่านั้น
                        จำเป็นต่อการตอบคำถาม WHO ให้ตรงนิยาม — ค่า m²/คน ทั้งจังหวัด
                        เอาป่า/เกษตรนอกเมืองมาหารด้วย จึงไม่มีจังหวัดไหนต่ำกว่าเกณฑ์ 9
                        เลยสักจังหวัด (ต่ำสุดคือ กทม. ~87) ซึ่งขัดกับความเป็นจริง
    district-ndvi /     ระดับอำเภอ — 928 อำเภอทั้งประเทศ ถ้าไม่ใส่ `--only`
    district-lst        `/analysis/cooling/{province}` ต้องมีทั้งสองชั้นของปีเดียวกัน
                        และต้องได้อย่างน้อย 5 อำเภอต่อจังหวัด (MIN_DISTRICTS_FOR_STRENGTH)
                        ถึงจะสรุปความแน่นของความสัมพันธ์ได้ → วอร์มทีละจังหวัดด้วย `--only`

Run:
    cd green-area-backend
    python prefetch_cache.py                                  # ndvi+lst 77 จังหวัด (ปีนี้+ปีก่อน)
    python prefetch_cache.py --layer urban --years 2025       # urban subset ครบ 77 จังหวัด
    python prefetch_cache.py --layer district-ndvi district-lst \
        --only "Bangkok Metropolis" --years 2025              # ทุกอำเภอของ กทม. (50 อำเภอ)
    python prefetch_cache.py --layer ndvi --years 2025        # เฉพาะ NDVI ปี 2025
"""
import argparse
import logging
import os
import sys
import time

os.environ.setdefault("RATE_LIMIT", "100000/minute")  # ปลด slowapi (60/min) —
# มีไว้กันยิง GEE ผ่าน API จริง ไม่เกี่ยวกับสคริปต์วอร์มแคชในเครื่อง

try:
    sys.stdout.reconfigure(encoding='utf-8')
except (AttributeError, OSError):
    pass

logging.basicConfig(level=logging.WARNING)

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402 — import ตอนนี้ถึงจะรัน ee.Initialize() ใน main.py
from dependencies import (CURRENT_YEAR, DISTRICT_GEOMETRIES,  # noqa: E402
                          PROVINCE_GEOMETRIES, require_user)

main.app.dependency_overrides[require_user] = lambda: {
    "id": "prefetch-script", "email": "prefetch@local"}
client = TestClient(main.app)

# ชั้นที่ทำงานทีละจังหวัด (1 รายการ = 1 จังหวัด/ปี)
PROVINCE_LAYERS = {
    "ndvi": "/ndvi/{province}",
    "lst": "/lst/{province}",
    "urban": "/analysis/urban-subset/{province}",
}
# ชั้นที่ทำงานทีละอำเภอ (1 รายการ = 1 อำเภอ/ปี) — ขยายเป็นทุกอำเภอของจังหวัดที่เลือก
DISTRICT_LAYERS = {
    "district-ndvi": "/ndvi/{province}/districts/{district}",
    "district-lst": "/lst/{province}/districts/{district}",
}
ALL_LAYERS = {**PROVINCE_LAYERS, **DISTRICT_LAYERS}


def warm_one(layer: str, province: str, district: str | None,
             year: int) -> tuple[str, float]:
    """เรียก endpoint จริง 1 ครั้ง → คืน (สถานะ, เวลาที่ใช้วิ)

    สถานะ: "cached" (endpoint ตอบจาก cache, ไม่เสีย GEE quota) / "computed"
    (recompute จริง) / "error: ..." (HTTP ไม่ใช่ 200)

    404 ถือเป็น error ตามปกติ — แปลว่าปีนั้นไม่มีภาพดาวเทียมครอบคลุมพื้นที่นั้น
    ซึ่งเป็นข้อมูลที่ควรเห็นในสรุป ไม่ใช่กลืนเงียบ
    """
    path = ALL_LAYERS[layer].format(province=province, district=district)
    started = time.time()
    resp = client.get(path, params={"year": year})
    elapsed = time.time() - started
    if resp.status_code != 200:
        return f"error: HTTP {resp.status_code} {resp.text[:120]}", elapsed
    return ("cached" if resp.json().get("from_cache") else "computed"), elapsed


def build_jobs(layers: list[str], provinces: list[str],
               years: list[int]) -> list[tuple[str, str, str | None, int]]:
    """กาง (ชั้น × พื้นที่ × ปี) เป็นรายการงาน — ชั้นระดับอำเภอกางเป็นทุกอำเภอของจังหวัดนั้น

    เรียงตามปี→ชั้น→จังหวัด ให้ผลลัพธ์ของปีหนึ่งครบก่อนขึ้นปีถัดไป (ถ้าถูกฆ่ากลางทาง
    จะได้ข้อมูลปีล่าสุดที่ใช้เดโมได้ครบก่อน)
    """
    jobs: list[tuple[str, str, str | None, int]] = []
    for year in years:
        for layer in layers:
            for province in provinces:
                if layer in DISTRICT_LAYERS:
                    districts = sorted(d for (p, d) in DISTRICT_GEOMETRIES if p == province)
                    jobs.extend((layer, province, d, year) for d in districts)
                else:
                    jobs.append((layer, province, None, year))
    return jobs


def main_cli():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--years", type=int, nargs="+",
                        default=[CURRENT_YEAR - 1, CURRENT_YEAR],
                        help="ปีที่จะวอร์ม (ค่าเริ่มต้น: ปีก่อนหน้า + ปีปัจจุบัน)")
    parser.add_argument("--layer", nargs="+", default=["ndvi", "lst"],
                        choices=list(ALL_LAYERS) + ["both", "all"],
                        help="ชั้นข้อมูลที่จะวอร์ม (ใส่หลายตัวได้) · "
                             "both = ndvi+lst (ค่าเริ่มต้น) · all = ทุกชั้นระดับจังหวัด")
    parser.add_argument("--only", action="append", default=None,
                        help="จำกัดเฉพาะจังหวัดที่ระบุ (ใส่ซ้ำได้)")
    args = parser.parse_args()

    if not os.getenv("GEE_PROJECT"):
        print("❌ GEE_PROJECT ไม่ถูกตั้งใน .env")
        sys.exit(1)

    provinces = sorted(args.only or PROVINCE_GEOMETRIES.keys())
    unknown = [p for p in provinces if p not in PROVINCE_GEOMETRIES]
    if unknown:
        print(f"❌ ไม่รู้จักจังหวัด: {', '.join(unknown)}")
        sys.exit(1)

    # ขยาย alias แล้วตัดซ้ำ โดยคงลำดับที่ผู้ใช้พิมพ์ไว้
    layers: list[str] = []
    for name in args.layer:
        expanded = (["ndvi", "lst"] if name == "both"
                    else list(PROVINCE_LAYERS) if name == "all"
                    else [name])
        layers.extend(x for x in expanded if x not in layers)

    jobs = build_jobs(layers, provinces, args.years)
    district_layers_used = [x for x in layers if x in DISTRICT_LAYERS]
    print(f"วอร์มแคช {len(jobs)} รายการ · จังหวัด {len(provinces)} × ปี {args.years} "
          f"× ชั้นข้อมูล {layers}")
    if district_layers_used and not args.only:
        print(f"⚠️  ชั้นระดับอำเภอ {district_layers_used} ครอบคลุมทั้ง 928 อำเภอ "
              f"(ไม่ได้ใส่ --only) — อาจใช้เวลาหลายชั่วโมง")

    started = time.time()
    counts = {"cached": 0, "computed": 0, "error": 0}
    errors: list[str] = []
    try:
        for i, (layer, province, district, year) in enumerate(jobs, 1):
            elapsed = time.time() - started
            eta_min = (elapsed / max(i - 1, 1)) * (len(jobs) - i + 1) / 60 if i > 1 else 0
            scope = f"{province}/{district}" if district else province
            print(f"⏳ [{i}/{len(jobs)}] {layer} {scope}/{year} ... "
                  f"(เหลือ ~{eta_min:.0f} นาที)", end=" ", flush=True)
            status, took = warm_one(layer, province, district, year)
            bucket = "error" if status.startswith("error") else status
            counts[bucket] += 1
            if bucket == "error":
                errors.append(f"{layer} {scope}/{year} — {status}")
            icon = {"cached": "✅ cache เดิม", "computed": "🛰️  compute ใหม่", "error": "❌"}[bucket]
            print(f"{icon} ({took:.1f}s)" + ("" if bucket != "error" else f" — {status}"))
    except KeyboardInterrupt:
        print("\n⚠️  ถูกยกเลิกกลางทาง — รันซ้ำได้ทันที (แถวที่วอร์มแล้วจะถูกข้าม)")

    total_min = (time.time() - started) / 60
    print(f"\nสรุป: cache เดิม {counts['cached']} · compute ใหม่ {counts['computed']} · "
          f"ล้มเหลว {counts['error']} · ใช้เวลา {total_min:.1f} นาที")
    if errors:
        # รวมรายการที่พังไว้ท้ายสุด — ไม่ต้องไล่หาใน log ยาวๆ ว่าอะไรไม่ผ่านบ้าง
        print(f"\nรายการที่ล้มเหลว ({len(errors)}):")
        for e in errors[:30]:
            print(f"  · {e}")
        if len(errors) > 30:
            print(f"  … และอีก {len(errors) - 30} รายการ")


if __name__ == "__main__":
    main_cli()
