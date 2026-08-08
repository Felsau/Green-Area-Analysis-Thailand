"""Urban subset (Phase B-3) — พืชพรรณต่อประชากรเฉพาะภายในเขต Built-up.

จำกัดขอบเขตให้ตรงกับที่คนอยู่จริง แต่ยังนับพืชพรรณทุกชนิดที่ NDVI > 0.3 ไม่ใช่
พื้นที่สาธารณะตามนิยาม WHO จึงเทียบเกณฑ์ตรง ๆ ไม่ได้ (กรุงเทพฯ ในเขต built-up
วัดได้ 31.5 m²/คน) ถ้อยคำที่ใช้กับผู้ใช้อยู่ใน frontend utils/greenMetric.js
"""
import logging

import ee
from fastapi import APIRouter, HTTPException

from dependencies import (supa_call, internal_error, worldpop_unavailable_error,
                          get_province_geom, get_district_geom,
                          CURRENT_YEAR, CURRENT_CACHE_VERSION,
                          WORLDPOP_YEAR, YearParam)
from gee_utils import clean_s2_collection, worldpop_pop_collection
from keyed_lock import COMPUTE_LOCK

# ESA WorldCover v200 class code (Built-up = สิ่งปลูกสร้าง/พื้นที่ urban)
ESA_BUILTUP_CLASS = 50

router = APIRouter()
logger = logging.getLogger(__name__)


def _compute_urban_subset(geom: ee.Geometry, province_name: str,
                          district_name: str | None, year: int, scope: str) -> dict:
    """คำนวณ urban subset สด (GEE) + insert cache (best-effort) → คืน response dict.

    แยกจาก endpoint เพื่อให้ COMPUTE_LOCK ครอบเฉพาะช่วง compute หนักได้สะอาด ·
    raise HTTPException (404/503) เมื่อภาพ/WorldPop ไม่ครอบคลุม — caller ปล่อยผ่าน
    """
    # ESA WorldCover v200 = single image, ปี 2021 — ใช้เป็น proxy ของ urban extent
    wc = ee.ImageCollection("ESA/WorldCover/v200").first().clip(geom)
    built_up = wc.eq(ESA_BUILTUP_CLASS)

    # Sentinel-2 NDVI ของปีที่ขอ
    s2 = clean_s2_collection(
        ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
        .filterBounds(geom)
        .filterDate(f'{year}-01-01', f'{year + 1}-01-01')  # end exclusive — รวม 31 ธ.ค.
        .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 80)))
    if s2.size().getInfo() == 0:
        raise HTTPException(status_code=404,
            detail=f"ไม่พบภาพ Sentinel-2 สำหรับ {scope} ปี {year}")
    ndvi = s2.median().normalizedDifference(['B8', 'B4']).rename('NDVI')
    green_mask = ndvi.gt(0.3)

    # Reductions: split sum/mean ออก 2 รอบเพื่อความชัด — แต่ละรอบ getInfo() ครั้งเดียว
    pixel_area = ee.Image.pixelArea().clip(geom)
    scale = 30  # ความละเอียดที่ balance ระหว่างความเร็วและความแม่น (WorldCover = 10m)

    # 1) sum: total/urban/green-in-urban areas
    area_stack = (pixel_area.rename('total_area')
                  .addBands(pixel_area.updateMask(built_up).rename('urban_area'))
                  .addBands(pixel_area.updateMask(built_up.And(green_mask))
                            .rename('green_urban_area')))
    area_sums = area_stack.reduceRegion(
        reducer=ee.Reducer.sum(),
        geometry=geom, scale=scale, maxPixels=1e10, bestEffort=True, tileScale=4,
    ).getInfo()
    total_m2 = area_sums.get('total_area') or 0
    urban_m2 = area_sums.get('urban_area') or 0
    green_in_urban_m2 = area_sums.get('green_urban_area') or 0

    # 2) mean NDVI within built-up
    ndvi_urban_mean = (ndvi.updateMask(built_up)
                       .reduceRegion(reducer=ee.Reducer.mean(),
                                     geometry=geom, scale=scale,
                                     maxPixels=1e10, bestEffort=True, tileScale=4)
                       .get('NDVI').getInfo())

    # Population ภายใน built-up (WorldPop 100m, ปี WORLDPOP_YEAR)
    # ถ้าไม่มี image สำหรับ THA+ปีนี้ .first() = null → ee.Image(null) พังด้วย
    # error คลุมเครือ ('input may not be null') แล้วกลายเป็น 500 · เช็ค size
    # ก่อนเพื่อตอบ 503 ที่บอกวิธีแก้ (ตั้ง WORLDPOP_YEAR) เหมือนใน /recommend
    pop_col = worldpop_pop_collection(WORLDPOP_YEAR)
    if pop_col.size().getInfo() == 0:
        raise worldpop_unavailable_error(WORLDPOP_YEAR)
    pop_urban = (ee.Image(pop_col.first()).select('population')
                 .updateMask(built_up)
                 .reduceRegion(reducer=ee.Reducer.sum(), geometry=geom,
                               scale=100, maxPixels=1e10, bestEffort=True)
                 .get('population').getInfo()) or 0

    urban_km2 = round(urban_m2 / 1_000_000, 2)
    green_in_urban_km2 = round(green_in_urban_m2 / 1_000_000, 2)
    urban_share = round((urban_m2 / total_m2) * 100, 2) if total_m2 else 0
    green_share_in_urban = round((green_in_urban_m2 / urban_m2) * 100, 1) if urban_m2 else 0
    pop_urban_int = int(round(pop_urban))
    m2_per_person_urban = (round(green_in_urban_m2 / pop_urban_int, 2)
                           if pop_urban_int > 0 else None)

    result = {
        "province": province_name, "district": district_name, "year": year,
        "worldcover_year": 2021, "worldpop_year": WORLDPOP_YEAR,
        "total_area_km2": round(total_m2 / 1_000_000, 2),
        "urban_area_km2": urban_km2,
        "urban_share_pct": urban_share,
        "ndvi_mean_urban": round(ndvi_urban_mean, 4) if ndvi_urban_mean is not None else None,
        "green_in_urban_km2": green_in_urban_km2,
        "green_share_in_urban_pct": green_share_in_urban,
        "population_urban": pop_urban_int,
        "m2_per_person_urban": m2_per_person_urban,
    }

    # Cache (best-effort — แค่ insert ถ้า table มีอยู่)
    try:
        supa_call(lambda s: s.table("urban_ndvi_annual").insert(
            {**result, "cache_version": CURRENT_CACHE_VERSION}).execute())
    except Exception as e:
        logger.warning("⚠️ Urban cache insert failed (non-fatal — table อาจยังไม่ถูกสร้าง): %s", e)

    return {**result, "from_cache": False}


# Optional cache table (สร้างเองใน Supabase ก่อนใช้ ถ้าต้องการ cache):
#   CREATE TABLE urban_ndvi_annual (
#     id BIGSERIAL PRIMARY KEY,
#     province TEXT NOT NULL, district TEXT, year INT NOT NULL,
#     worldcover_year INT, worldpop_year INT,
#     total_area_km2 NUMERIC, urban_area_km2 NUMERIC, urban_share_pct NUMERIC,
#     ndvi_mean_urban NUMERIC,
#     green_in_urban_km2 NUMERIC, green_share_in_urban_pct NUMERIC,
#     population_urban INT, m2_per_person_urban NUMERIC,
#     created_at TIMESTAMPTZ DEFAULT NOW()
#   );
# ถ้าไม่สร้าง endpoint ยังทำงานได้ปกติ — แค่คำนวณใหม่ทุกครั้ง (ใช้เวลา 30-60s ต่อครั้ง)
@router.get("/analysis/urban-subset/{province_name}")
def get_urban_subset(province_name: str, year: YearParam = CURRENT_YEAR,
                     district_name: str | None = None):
    """NDVI + green area + ประชากร เฉพาะภายในเขต Built-up (ESA WorldCover v200, ปี 2021).

    scope = "พื้นที่ที่คนอยู่" ไม่ใช่ป่า/เกษตรนอกเมือง จึงสะท้อนสภาพในเมืองได้ดีกว่า
    ค่ารวมระดับจังหวัด · WorldCover ใช้ปี 2021 เป็น proxy ของขอบเขตเมืองในทุกปี
    (built-up เปลี่ยนแปลงน้อยใน timescale ปี)
    """
    if district_name:
        raw_geom = get_district_geom(province_name, district_name)
        scope = f"{province_name}/{district_name}"
    else:
        raw_geom = get_province_geom(province_name)
        scope = province_name

    key = ("urban", province_name, district_name, year)

    def _read_cache():
        """อ่าน cache → คืน response dict ถ้า hit (version ปัจจุบัน) · ลบ row ที่ stale
        แล้วคืน None · best-effort: table อาจยังไม่ถูกสร้าง → skip เงียบๆ"""
        try:
            def _cache_q(s):
                q = (s.table("urban_ndvi_annual").select("*")
                     .eq("province", province_name).eq("year", year))
                if district_name:
                    q = q.eq("district", district_name)
                else:
                    q = q.is_("district", "null")
                return q.execute()
            cached = supa_call(_cache_q)
            if cached.data:
                row = cached.data[0]
                if row.get("cache_version", 1) >= CURRENT_CACHE_VERSION:
                    logger.info("✅ Urban cache hit: %s/%d", scope, year)
                    # ตัด DB internals ให้ response shape ตรงกับ path คำนวณสด (cache miss)
                    public = {k: v for k, v in row.items()
                              if k not in ("id", "cache_version", "created_at")}
                    return {**public, "from_cache": True}
                # row เก่ากว่า compute version ปัจจุบัน → ลบทิ้งแล้วคำนวณใหม่
                # (ลบก่อน ไม่งั้น insert รอบใหม่ชน UNIQUE(province,district,year))
                logger.info("♻️ Urban stale cache: %s/%d — recomputing", scope, year)
                supa_call(lambda s: s.table("urban_ndvi_annual")
                          .delete().eq("id", row["id"]).execute())
        except Exception as e:
            logger.warning("⚠️ Urban cache lookup skipped (non-fatal): %s", e)
        return None

    hit = _read_cache()
    if hit is not None:
        return hit

    # cache miss — ล็อกต่อ key กัน request เดียวกันยิง GEE compute (30-60s) ซ้ำซ้อนพร้อมกัน
    with COMPUTE_LOCK.hold(key):
        hit = _read_cache()   # อีก request อาจ compute เสร็จระหว่างที่เรารอคิว
        if hit is not None:
            return hit
        logger.info("⏳ Computing urban subset: %s/%d", scope, year)
        try:
            return _compute_urban_subset(ee.Geometry(raw_geom), province_name,
                                         district_name, year, scope)
        except HTTPException:
            raise
        except Exception:
            logger.error("❌ Urban subset error [%s/%d]", scope, year, exc_info=True)
            raise internal_error()
