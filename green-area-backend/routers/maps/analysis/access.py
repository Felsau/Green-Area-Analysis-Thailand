"""Accessibility (FR-18 · เกณฑ์ "300" ของ 3-30-300) — % ประชากรที่อยู่ในระยะเดิน
300 ม. จากพื้นที่สีเขียว (ต้นไม้ตาม ESA WorldCover class 10, ปี 2021 epoch เดียว).

ใช้เทคนิคเดียวกับ `scoring.access_need_image` (fastDistanceTransform บนกริดปักหมุด
คงที่ — ดู docstring ที่นั่นสำหรับเหตุผลที่ต้องปักหมุด scale) แต่ตัดที่ threshold
300 ม. ตรง ๆ (population ในรัศมี / population ทั้งหมด) แทนการ normalize เป็นคะแนน
0–1 อย่าง access_need — คนละคำถามกัน (ที่นี่ตอบ "กี่ % เข้าถึงได้" ไม่ใช่ "ขาดแคลนแค่ไหน")

WorldCover + WorldPop เป็น epoch คงที่ (ไม่ผูกปีภาพดาวเทียมเหมือน NDVI/LST) — `year`
ในพารามิเตอร์/cache key มีไว้เป็น partition ให้เข้าชุดกับตารางอื่นเท่านั้น
"""
import logging

import ee
from fastapi import APIRouter, HTTPException

from canopy import ESA_TREE_COVER_CLASS, WORLDCOVER_ASSET
from dependencies import (supa_call, internal_error, worldpop_unavailable_error,
                          get_province_geom, get_district_geom,
                          CURRENT_YEAR, CURRENT_CACHE_VERSION,
                          WORLDPOP_YEAR, YearParam)
from gee_utils import worldpop_pop_collection
from keyed_lock import COMPUTE_LOCK

# ระยะเดินถึงพื้นที่สีเขียวตามเกณฑ์ "300" ของ 3-30-300 (Konijnendijk 2021 — [R2])
ACCESS_DISTANCE_M = 300.0
# กริดคงที่สำหรับ fastDistanceTransform — เหตุผลเดียวกับ scoring.ACCESS_DT_SCALE_M
# (ปักที่ 100 ม. ให้ pixel ของ transform = เมตรจริงเสมอ ไม่เพี้ยนตาม zoom/scale)
DT_SCALE_M = 100.0
# หน้าต่างค้นหา (pixel ที่ DT_SCALE_M) ต้องคลุมระยะ cap: 300/100 = 3 px · ใช้ 8 px
# (800 ม.) เผื่อเหลือพอสมควรแต่เล็กกว่า scoring.ACCESS_NEIGHBORHOOD_PX (64px/6.4km
# ที่ต้องคลุมถึง 1 กม.) — ที่นี่ cap แค่ 300 ม. จึงใช้หน้าต่างเล็กกว่าได้ เร็วกว่า
DT_NEIGHBORHOOD_PX = 8

router = APIRouter()
logger = logging.getLogger(__name__)


def _compute_access_300m(geom: ee.Geometry) -> dict:
    """คำนวณ population_total / population_within / pct_within ในรัศมี ACCESS_DISTANCE_M"""
    wc = ee.ImageCollection(WORLDCOVER_ASSET).first().clip(geom)
    proj = wc.projection().atScale(DT_SCALE_M)
    tree = wc.eq(ESA_TREE_COVER_CLASS).reproject(proj)  # 1 = ต้นไม้, 0 = ไม่มี
    dist_m = (tree.fastDistanceTransform(DT_NEIGHBORHOOD_PX).sqrt()
              .multiply(DT_SCALE_M))
    # pixel ที่ fastDistanceTransform หาต้นไม้ไม่เจอในหน้าต่างค้นหา (ไกลเกิน
    # DT_NEIGHBORHOOD_PX×DT_SCALE_M) จะถูก mask ไว้ — แปลว่า "ไกลแน่ ๆ" (เกิน 800 ม.
    # จึงเกิน cap 300 ม. แน่นอน) ไม่ใช่ "ไม่มีข้อมูล" → unmask ด้วยค่าเกิน cap เล็กน้อย
    # (ไม่ต้องใช้ระยะจริง เพราะขั้นต่อไปเทียบแค่ lte(ACCESS_DISTANCE_M) เท่านั้น)
    dist_m = dist_m.unmask(ACCESS_DISTANCE_M + 1)
    within = dist_m.lte(ACCESS_DISTANCE_M)  # pixel บนต้นไม้เอง = ระยะ 0 = within อยู่แล้ว

    pop_col = worldpop_pop_collection(WORLDPOP_YEAR)
    if pop_col.size().getInfo() == 0:
        raise worldpop_unavailable_error(WORLDPOP_YEAR)
    pop = ee.Image(pop_col.first()).select('population')

    sums = (pop.rename('total').addBands(pop.updateMask(within).rename('within'))
            .reduceRegion(reducer=ee.Reducer.sum(), geometry=geom, scale=100,
                          maxPixels=1e10, bestEffort=True).getInfo())
    total = sums.get('total') or 0
    within_pop = sums.get('within') or 0
    pct = round(within_pop / total * 100, 1) if total > 0 else None

    return {
        "distance_m": ACCESS_DISTANCE_M,
        "worldpop_year": WORLDPOP_YEAR,
        "population_total": int(round(total)),
        "population_within": int(round(within_pop)),
        "pct_within": pct,
    }


# Optional cache table (สร้างเองใน Supabase ก่อนใช้ ถ้าต้องการ cache — migration
# 022_access_300m.sql) · ถ้าไม่สร้าง endpoint ยังทำงานได้ปกติ แค่คำนวณใหม่ทุกครั้ง
# (pattern เดียวกับ urban.py ตอนตาราง urban_ndvi_annual ยังไม่มี):
#   CREATE TABLE access_300m (
#     id BIGSERIAL PRIMARY KEY,
#     province TEXT NOT NULL, district TEXT, year INT NOT NULL,
#     distance_m NUMERIC, worldpop_year INT,
#     population_total INT, population_within INT, pct_within NUMERIC,
#     cache_version INT NOT NULL DEFAULT 1,
#     created_at TIMESTAMPTZ DEFAULT NOW()
#   );
@router.get("/analysis/access-300m/{province_name}")
def get_access_300m(province_name: str, year: YearParam = CURRENT_YEAR,
                    district_name: str | None = None):
    """FR-18 — % ประชากรที่อยู่ในระยะเดิน 300 ม. จากพื้นที่สีเขียว (เกณฑ์ 3-30-300)."""
    if district_name:
        raw_geom = get_district_geom(province_name, district_name)
        scope = f"{province_name}/{district_name}"
    else:
        raw_geom = get_province_geom(province_name)
        scope = province_name

    def _read_cache():
        """อ่าน cache → คืน response dict ถ้า hit (version ปัจจุบัน) · ลบ row ที่ stale
        แล้วคืน None · best-effort: table อาจยังไม่ถูกสร้าง → skip เงียบๆ"""
        try:
            def _cache_q(s):
                q = (s.table("access_300m").select("*")
                     .eq("province", province_name).eq("year", year))
                q = (q.eq("district", district_name) if district_name
                     else q.is_("district", "null"))
                return q.execute()
            cached = supa_call(_cache_q)
            if cached.data:
                row = cached.data[0]
                if row.get("cache_version", 1) >= CURRENT_CACHE_VERSION:
                    logger.info("✅ Access-300m cache hit: %s", scope)
                    public = {k: v for k, v in row.items()
                              if k not in ("id", "cache_version", "created_at")}
                    return {**public, "from_cache": True}
                logger.info("♻️ Access-300m stale cache: %s — recomputing", scope)
                supa_call(lambda s: s.table("access_300m")
                          .delete().eq("id", row["id"]).execute())
        except Exception as e:
            logger.warning("⚠️ Access-300m cache lookup skipped (non-fatal): %s", e)
        return None

    hit = _read_cache()
    if hit is not None:
        return hit

    # cache miss — ล็อกต่อ key กัน request เดียวกันยิง GEE compute ซ้ำซ้อนพร้อมกัน
    with COMPUTE_LOCK.hold(("access300", province_name, district_name, year)):
        hit = _read_cache()
        if hit is not None:
            return hit
        logger.info("⏳ Computing access-300m: %s", scope)
        try:
            geom = ee.Geometry(raw_geom)
            result = _compute_access_300m(geom)
        except HTTPException:
            raise
        except Exception:
            logger.error("❌ Access-300m error [%s]", scope, exc_info=True)
            raise internal_error()

        try:
            supa_call(lambda s: s.table("access_300m").insert({
                "province": province_name, "district": district_name, "year": year,
                **result, "cache_version": CURRENT_CACHE_VERSION,
            }).execute())
        except Exception as e:
            logger.warning("⚠️ Access-300m cache insert failed (non-fatal): %s", e)

        return {"province": province_name, "district": district_name, "year": year,
                **result, "from_cache": False}
