from fastapi import APIRouter, HTTPException
import logging
import ee

from dependencies import (supa_call, internal_error,
                          get_province_geom, get_district_geom,
                          CURRENT_YEAR, MONTH_NAMES, YearParam,
                          CURRENT_CACHE_VERSION)
from gee_utils import get_lst_col, reduce_lst, scale_lst
from keyed_lock import COMPUTE_LOCK
from schemas import LSTResponse, LSTMonthlyResponse

router = APIRouter()
logger = logging.getLogger(__name__)


# Shared compute helper
def _compute_lst_monthly(geom: ee.Geometry, year: int, scale: int):
    """LST 12 เดือน รวมใน 1 round-trip ด้วย ee.List.sequence."""
    def build_col(m_int):
        flt = ee.Filter.And(
            ee.Filter.lt('CLOUD_COVER', 40),
            ee.Filter.calendarRange(year, year, 'year'),
            ee.Filter.calendarRange(m_int, m_int, 'month'),
        )

        def per_sat(cid):
            return (ee.ImageCollection(cid)
                    .filterBounds(geom)
                    .filter(flt)
                    .map(scale_lst)
                    .select('LST'))

        return per_sat('LANDSAT/LC08/C02/T1_L2').merge(
               per_sat('LANDSAT/LC09/C02/T1_L2'))

    def by_month(m):
        m_int = ee.Number(m).toInt()
        col = build_col(m_int)
        # เติม LST band ที่ถูก mask ไว้ กัน reduceRegion ไม่มี key ตอน col ว่าง
        img = col.median().addBands(
            ee.Image.constant(0).rename('LST').selfMask(),
            overwrite=False)
        lst = (img.reduceRegion(reducer=ee.Reducer.mean(), geometry=geom,
                                scale=scale, maxPixels=1e10, bestEffort=True)
               .get('LST'))
        return ee.Feature(None, {'month_num': m_int, 'count': col.size(), 'lst': lst})

    fc = ee.FeatureCollection(ee.List.sequence(1, 12).map(by_month))
    feats = fc.getInfo()['features']

    results = []
    for f in feats:
        props = f['properties']
        m = int(props['month_num'])
        count = int(props.get('count') or 0)
        lst_raw = props.get('lst')
        lst_val = round(lst_raw, 2) if lst_raw is not None else None
        results.append({"month": MONTH_NAMES[m - 1], "month_num": m,
                        "lst": lst_val, "image_count": count})
    return results


# District LST monthly (before catch-all)
@router.get("/lst/{province_name}/districts/{district_name}/monthly")
def get_district_lst_monthly(province_name: str, district_name: str, year: YearParam = CURRENT_YEAR):
    raw_geom = get_district_geom(province_name, district_name)

    def _read_cache():
        cached = supa_call(lambda s: s.table("district_lst_monthly")
                           .select("*").eq("province", province_name)
                           .eq("district", district_name).eq("year", year).execute())
        if cached.data:
            return {"province": province_name, "district": district_name, "year": year,
                    "monthly": cached.data[0]["monthly_data"], "from_cache": True}
        return None

    hit = _read_cache()
    if hit is not None:
        return hit

    # cache miss — ล็อกต่อ key กัน request ซ้ำยิง GEE compute พร้อมกัน (ไม่งั้นชน
    # UNIQUE(province,district,year) ตอน insert พร้อมกัน → 500) แล้ว re-check
    with COMPUTE_LOCK.hold(("lst-district-monthly", province_name, district_name, year)):
        hit = _read_cache()
        if hit is not None:
            return hit
        logger.info("⏳ Computing district LST monthly: %s/%s/%d", province_name, district_name, year)
        try:
            results = _compute_lst_monthly(ee.Geometry(raw_geom), year, scale=100)
            supa_call(lambda s: s.table("district_lst_monthly").insert({
                "province": province_name, "district": district_name,
                "year": year, "monthly_data": results,
                "cache_version": CURRENT_CACHE_VERSION}).execute())
            return {"province": province_name, "district": district_name,
                    "year": year, "monthly": results, "from_cache": False}
        except Exception:
            logger.error("❌ District LST monthly error", exc_info=True)
            raise internal_error()


# District LST annual (before catch-all)
@router.get("/lst/{province_name}/districts/{district_name}")
def get_district_lst(province_name: str, district_name: str, year: YearParam = CURRENT_YEAR):
    raw_geom = get_district_geom(province_name, district_name)

    def _read_cache():
        cached = supa_call(lambda s: s.table("district_lst_annual")
                           .select("*").eq("province", province_name)
                           .eq("district", district_name).eq("year", year).execute())
        if cached.data:
            row = cached.data[0]
            return {"province": province_name, "district": district_name, "year": year,
                    "lst_mean": row["lst_mean"], "lst_min": row["lst_min"],
                    "lst_max": row["lst_max"], "from_cache": True}
        return None

    hit = _read_cache()
    if hit is not None:
        return hit

    with COMPUTE_LOCK.hold(("lst-district-annual", province_name, district_name, year)):
        hit = _read_cache()
        if hit is not None:
            return hit
        logger.info("⏳ Computing district LST: %s/%s/%d", province_name, district_name, year)
        try:
            geom = ee.Geometry(raw_geom)
            col = get_lst_col(geom, year)
            if col.size().getInfo() == 0:
                raise HTTPException(status_code=404,
                    detail=f"ไม่พบข้อมูล Landsat สำหรับ {district_name} ปี {year}")
            lst_mean, lst_min, lst_max = reduce_lst(col, geom, scale=100)

            supa_call(lambda s: s.table("district_lst_annual").insert({
                "province": province_name, "district": district_name, "year": year,
                "lst_mean": lst_mean, "lst_min": lst_min, "lst_max": lst_max,
                "cache_version": CURRENT_CACHE_VERSION}).execute())
            return {"province": province_name, "district": district_name, "year": year,
                    "lst_mean": lst_mean, "lst_min": lst_min, "lst_max": lst_max,
                    "from_cache": False}
        except HTTPException:
            raise
        except Exception:
            logger.error("❌ District LST error", exc_info=True)
            raise internal_error()


# Province LST monthly
@router.get("/lst/{province_name}/monthly", response_model=LSTMonthlyResponse)
def get_lst_monthly(province_name: str, year: YearParam = CURRENT_YEAR):
    raw_geom = get_province_geom(province_name)

    def _read_cache():
        cached = supa_call(lambda s: s.table("province_lst_monthly")
                           .select("*").eq("province", province_name).eq("year", year).execute())
        if cached.data:
            logger.info("✅ LST cache hit: %s/%d/monthly", province_name, year)
            return {"province": province_name, "year": year,
                    "monthly": cached.data[0]["monthly_data"], "from_cache": True}
        return None

    hit = _read_cache()
    if hit is not None:
        return hit

    with COMPUTE_LOCK.hold(("lst-monthly", province_name, year)):
        hit = _read_cache()
        if hit is not None:
            return hit
        logger.info("⏳ Computing LST monthly: %s/%d", province_name, year)
        try:
            results = _compute_lst_monthly(ee.Geometry(raw_geom), year, scale=500)
            supa_call(lambda s: s.table("province_lst_monthly").insert(
                {"province": province_name, "year": year, "monthly_data": results,
                 "cache_version": CURRENT_CACHE_VERSION}).execute())
            return {"province": province_name, "year": year,
                    "monthly": results, "from_cache": False}
        except Exception:
            logger.error("❌ LST monthly error", exc_info=True)
            raise internal_error()


# Province LST annual
@router.get("/lst/{province_name}", response_model=LSTResponse)
def get_lst(province_name: str, year: YearParam = CURRENT_YEAR):
    raw_geom = get_province_geom(province_name)

    def _read_cache():
        cached = supa_call(lambda s: s.table("province_lst_annual")
                           .select("*").eq("province", province_name).eq("year", year).execute())
        if cached.data:
            row = cached.data[0]
            logger.info("✅ LST cache hit: %s/%d", province_name, year)
            return {"province": province_name, "year": year,
                    "lst_mean": row["lst_mean"], "lst_min": row["lst_min"],
                    "lst_max": row["lst_max"], "from_cache": True}
        return None

    hit = _read_cache()
    if hit is not None:
        return hit

    with COMPUTE_LOCK.hold(("lst-annual", province_name, year)):
        hit = _read_cache()
        if hit is not None:
            return hit
        logger.info("⏳ Computing LST annual: %s/%d", province_name, year)
        try:
            geom = ee.Geometry(raw_geom)
            col = get_lst_col(geom, year)
            if col.size().getInfo() == 0:
                raise HTTPException(status_code=404,
                    detail=f"ไม่พบข้อมูล Landsat สำหรับ {province_name} ปี {year}")
            lst_mean, lst_min, lst_max = reduce_lst(col, geom, scale=500)

            supa_call(lambda s: s.table("province_lst_annual").insert(
                {"province": province_name, "year": year,
                 "lst_mean": lst_mean, "lst_min": lst_min, "lst_max": lst_max,
                 "cache_version": CURRENT_CACHE_VERSION}).execute())
            return {"province": province_name, "year": year,
                    "lst_mean": lst_mean, "lst_min": lst_min, "lst_max": lst_max,
                    "from_cache": False}
        except HTTPException:
            raise
        except Exception:
            logger.error("❌ LST error [%s/%d]", province_name, year, exc_info=True)
            raise internal_error()
