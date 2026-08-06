"""อุ่นแคช NDVI/LST annual ระดับจังหวัดล่วงหน้า — กันเดโมค้าง 50–60 วิ/จังหวัด

ตรวจ Supabase จริง (4 ส.ค. 2569) พบว่า 165/170 แถวของ `ndvi_annual` จะถูกมองว่า
stale โดย `_is_stale()` (ขาด `validation`/`data_quality`/`canopy` หรือ
`cache_version` เก่า) รวมทั้ง 77/77 จังหวัดของปีปัจจุบันด้วย — เปิดจังหวัดไหนก่อน
ก็ตกไป recompute สดตอนนั้น ส่วน LST ไม่มี staleness check (แคชค้างตลอดไปจนกว่าจะ
ลบ) แต่ปี 2025 (ปีล่าสุดที่ข้อมูลครบ) ยังไม่มีแคชเลยสักแถว

สคริปต์นี้**ไม่คำนวณเอง** — เรียก endpoint จริง (`GET /ndvi/{province}`,
`GET /lst/{province}`) ผ่าน TestClient ในโพรเซสเดียวกัน ให้ endpoint ตัดสินใจ
เองว่า cache ที่มีพอหรือต้อง recompute (`_is_stale`) เพื่อไม่ให้ตรรกะใน
สคริปต์เพี้ยนไปจากของจริงที่ผู้ใช้เจอ — แถวที่ fresh อยู่แล้วจะข้ามแทบไม่เสียเวลา
ซ้ำสคริปต์ได้เรื่อยๆ (idempotent)

Run:
    cd green-area-backend
    python prefetch_cache.py                              # ปีปัจจุบัน + ปีก่อนหน้า, ndvi+lst, 77 จังหวัด
    python prefetch_cache.py --years 2025                 # เฉพาะปี 2025
    python prefetch_cache.py --layer ndvi                 # เฉพาะ NDVI
    python prefetch_cache.py --only "Bangkok Metropolis" --only Tak
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
from dependencies import CURRENT_YEAR, PROVINCE_GEOMETRIES, require_user  # noqa: E402

main.app.dependency_overrides[require_user] = lambda: {
    "id": "prefetch-script", "email": "prefetch@local"}
client = TestClient(main.app)

LAYERS = {
    "ndvi": "/ndvi/{province}",
    "lst": "/lst/{province}",
}


def warm_one(layer: str, province: str, year: int) -> tuple[str, float]:
    """เรียก endpoint จริง 1 ครั้ง → คืน (สถานะ, เวลาที่ใช้วิ)

    สถานะ: "cached" (endpoint ตอบจาก cache, ไม่เสีย GEE quota) / "computed"
    (recompute จริง) / "error: ..." (HTTP ไม่ใช่ 200)
    """
    path = LAYERS[layer].format(province=province)
    started = time.time()
    resp = client.get(path, params={"year": year})
    elapsed = time.time() - started
    if resp.status_code != 200:
        return f"error: HTTP {resp.status_code} {resp.text[:120]}", elapsed
    return ("cached" if resp.json().get("from_cache") else "computed"), elapsed


def main_cli():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--years", type=int, nargs="+",
                        default=[CURRENT_YEAR - 1, CURRENT_YEAR],
                        help="ปีที่จะวอร์ม (ค่าเริ่มต้น: ปีก่อนหน้า + ปีปัจจุบัน)")
    parser.add_argument("--layer", choices=["ndvi", "lst", "both"], default="both")
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

    layers = ["ndvi", "lst"] if args.layer == "both" else [args.layer]
    jobs = [(layer, province, year)
            for year in args.years for layer in layers for province in provinces]

    print(f"วอร์มแคช {len(jobs)} รายการ · จังหวัด {len(provinces)} × ปี {args.years} × ชั้นข้อมูล {layers}")

    started = time.time()
    counts = {"cached": 0, "computed": 0, "error": 0}
    try:
        for i, (layer, province, year) in enumerate(jobs, 1):
            elapsed = time.time() - started
            eta_min = (elapsed / max(i - 1, 1)) * (len(jobs) - i + 1) / 60 if i > 1 else 0
            print(f"⏳ [{i}/{len(jobs)}] {layer} {province}/{year} ... "
                  f"(เหลือ ~{eta_min:.0f} นาที)", end=" ", flush=True)
            status, took = warm_one(layer, province, year)
            bucket = "error" if status.startswith("error") else status
            counts[bucket] += 1
            icon = {"cached": "✅ cache เดิม", "computed": "🛰️  compute ใหม่", "error": "❌"}[bucket]
            print(f"{icon} ({took:.1f}s)" + ("" if bucket != "error" else f" — {status}"))
    except KeyboardInterrupt:
        print("\n⚠️  ถูกยกเลิกกลางทาง — รันซ้ำได้ทันที (แถวที่วอร์มแล้วจะถูกข้าม)")

    total_min = (time.time() - started) / 60
    print(f"\nสรุป: cache เดิม {counts['cached']} · compute ใหม่ {counts['computed']} · "
          f"ล้มเหลว {counts['error']} · ใช้เวลา {total_min:.1f} นาที")


if __name__ == "__main__":
    main_cli()
