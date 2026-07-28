"""NFR-08 — เติม `provinces.worldcover_green_pct` (ค่าอ้างอิงของการ validate).

ค่านี้คือ % พื้นที่สีเขียวตาม ESA WorldCover อ่านแบบ fractional ที่ 10 ม. ซึ่ง
**ไม่ขึ้นกับปีและไม่ขึ้นกับ Sentinel-2** (WorldCover เป็น epoch เดียว ปี 2021) จึง
คำนวณครั้งเดียวต่อจังหวัดแล้วใช้ซ้ำได้ทุกปี

ทำไมต้องแยกมาเป็นสคริปต์: ก้อนนี้แพงที่สุดในชุด NFR-08 (~17.5 วิ/จังหวัด) ถ้าคิดสด
ตอน cache miss จะดัน NDVI compute (~50 วิ) ทะลุงบ 60 วิ ของ NFR-01 · ดึงออกมา
backfill ครั้งเดียวแล้ว request path เหลือจ่ายแค่ ~2.8 วิ (disagreement_sums)

รันครั้งเดียวหลัง migration 016 · idempotent — รันซ้ำได้ (UPDATE ทับค่าเดิม)
ใช้เวลาราว 25 นาทีสำหรับ 77 จังหวัด

Run:
    cd green-area-backend
    python backfill_worldcover_reference.py
    python backfill_worldcover_reference.py --only "Bangkok Metropolis"   # เฉพาะบางจังหวัด
    python backfill_worldcover_reference.py --missing-only                # เฉพาะที่ยังว่าง
"""
import argparse
import logging
import os
import sys
import time

import ee
from dotenv import load_dotenv

try:
    sys.stdout.reconfigure(encoding='utf-8')
except (AttributeError, OSError):
    pass

load_dotenv()
logging.basicConfig(level=logging.WARNING)

from dependencies import PROVINCE_GEOMETRIES, supa_call  # noqa: E402
from validation import worldcover_reference_sums  # noqa: E402

# ต้องตรงกับ scale ที่ /ndvi/{province} ใช้ ไม่งั้นค่าอ้างอิงกับ green_area_pct
# ที่เอามาลบกันคิดคนละความละเอียด
PROVINCE_SCALE_M = 500


def compute_reference_pct(province: str) -> float | None:
    geom = ee.Geometry(PROVINCE_GEOMETRIES[province])
    sums = worldcover_reference_sums(geom, PROVINCE_SCALE_M)
    green_m2 = sums.get('worldcover_green_area')
    if green_m2 is None:
        return None
    total_m2 = ee.Image.pixelArea().clip(geom).reduceRegion(
        reducer=ee.Reducer.sum(), geometry=geom, scale=PROVINCE_SCALE_M,
        maxPixels=1e10, bestEffort=True).getInfo().get('area')
    if not total_m2:
        return None
    return round(green_m2 / total_m2 * 100, 2)


def check_column_exists() -> bool:
    """เช็คว่ารัน migration 016 แล้วหรือยัง — ก่อนเผาเวลา GEE ไปเปล่า ๆ.

    ถ้าไม่เช็ค: สคริปต์จะคำนวณจังหวัดแรกจนเสร็จ (~17 วิ) แล้วค่อยพังตอน UPDATE
    ด้วย error ของ PostgREST ที่อ่านไม่ออกว่าต้องไปทำอะไร
    """
    try:
        supa_call(lambda s: s.table("provinces")
                  .select("worldcover_green_pct").limit(1).execute())
        return True
    except Exception as e:
        print("❌ ยังไม่มีคอลัมน์ provinces.worldcover_green_pct\n"
              "   → เอา migrations/016_validation.sql ไปรันใน Supabase SQL Editor ก่อน\n"
              f"   (รายละเอียด: {e})")
        return False


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", action="append", default=None,
                        help="จำกัดเฉพาะจังหวัดที่ระบุ (ใส่ซ้ำได้)")
    parser.add_argument("--missing-only", action="store_true",
                        help="ข้ามจังหวัดที่มีค่าอยู่แล้ว")
    args = parser.parse_args()

    gee_project = os.getenv("GEE_PROJECT")
    if not gee_project:
        print("❌ GEE_PROJECT ไม่ถูกตั้งใน .env")
        sys.exit(1)
    if not check_column_exists():
        sys.exit(1)
    ee.Initialize(project=gee_project)

    provinces = sorted(args.only or PROVINCE_GEOMETRIES.keys())
    unknown = [p for p in provinces if p not in PROVINCE_GEOMETRIES]
    if unknown:
        print(f"❌ ไม่รู้จักจังหวัด: {', '.join(unknown)}")
        sys.exit(1)

    if args.missing_only:
        rows = supa_call(lambda s: s.table("provinces")
                         .select("name_en,worldcover_green_pct").execute()).data
        have = {r["name_en"] for r in rows if r.get("worldcover_green_pct") is not None}
        skipped = len([p for p in provinces if p in have])
        provinces = [p for p in provinces if p not in have]
        print(f"ข้าม {skipped} จังหวัดที่มีค่าแล้ว · เหลือ {len(provinces)}")

    started = time.time()
    ok = failed = 0
    for i, province in enumerate(provinces, 1):
        elapsed = time.time() - started
        eta = (elapsed / max(i - 1, 1)) * (len(provinces) - i + 1) if i > 1 else 0
        print(f"⏳ [{i}/{len(provinces)}] {province} ... "
              f"(เหลือ ~{eta/60:.0f} นาที)", end=" ", flush=True)
        try:
            pct = compute_reference_pct(province)
        except Exception as e:
            print(f"❌ {e}")
            failed += 1
            continue
        if pct is None:
            print("⚠️  ไม่มีข้อมูล WorldCover")
            failed += 1
            continue
        supa_call(lambda s, p=province, v=pct: s.table("provinces")
                  .update({"worldcover_green_pct": v}).eq("name_en", p).execute())
        print(f"{pct:.2f}%")
        ok += 1

    print(f"\n✅ เติมค่าอ้างอิงสำเร็จ {ok} จังหวัด"
          + (f" · ล้มเหลว {failed}" if failed else "")
          + f" · ใช้เวลา {(time.time()-started)/60:.1f} นาที")


if __name__ == "__main__":
    main()
