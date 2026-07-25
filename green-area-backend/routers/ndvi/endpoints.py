from fastapi import APIRouter, HTTPException
import logging
import ee

from dependencies import (get_population, supa_call, internal_error, ensure_province,
                          get_province_geom, get_district_geom,
                          CURRENT_YEAR, YearParam, YEAR_MIN, YEAR_MAX,
                          CURRENT_CACHE_VERSION)
from schemas import NDVIResponse, NDVIMonthlyResponse
from .compute import (_is_stale, compute_who_status,
                      _compute_ndvi_annual, _compute_ndvi_monthly)

router = APIRouter()
logger = logging.getLogger(__name__)


# ── District NDVI monthly ────────────────────────────────── (before catch-all)
@router.get("/ndvi/{province_name}/districts/{district_name}/monthly")
def get_district_ndvi_monthly(province_name: str, district_name: str, year: YearParam = CURRENT_YEAR):
    raw_geom = get_district_geom(province_name, district_name)

    cached = supa_call(lambda s: s.table("district_ndvi_monthly")
                       .select("*")
                       .eq("province", province_name)
                       .eq("district", district_name)
                       .eq("year", year)
                       .execute())
    if cached.data:
        logger.info("✅ Supabase hit: %s/%s/%d/monthly", province_name, district_name, year)
        return {
            "province": province_name, "district": district_name, "year": year,
            "monthly": cached.data[0]["monthly_data"],
            "from_cache": True, "cached_at": cached.data[0]["created_at"],
        }

    logger.info("⏳ Computing district monthly: %s/%s/%d", province_name, district_name, year)
    try:
        results = _compute_ndvi_monthly(ee.Geometry(raw_geom), year, scale=100)
        supa_call(lambda s: s.table("district_ndvi_monthly").insert({
            "province": province_name, "district": district_name,
            "year": year, "monthly_data": results,
            "cache_version": CURRENT_CACHE_VERSION,
        }).execute())
        return {"province": province_name, "district": district_name,
                "year": year, "monthly": results, "from_cache": False}
    except Exception:
        logger.error("❌ Error district monthly [%s/%s/%d]", province_name, district_name, year, exc_info=True)
        raise internal_error()


# ── District NDVI annual ─────────────────────────────────── (before catch-all)
@router.get("/ndvi/{province_name}/districts/{district_name}")
def get_district_ndvi(province_name: str, district_name: str, year: YearParam = CURRENT_YEAR):
    raw_geom = get_district_geom(province_name, district_name)

    cached = supa_call(lambda s: s.table("district_ndvi_annual")
                       .select("*")
                       .eq("province", province_name)
                       .eq("district", district_name)
                       .eq("year", year)
                       .execute())
    if cached.data:
        row = cached.data[0]
        if not _is_stale(row):
            logger.info("✅ Supabase hit: %s/%s/%d", province_name, district_name, year)
            return {
                "province": province_name, "district": district_name, "year": year,
                "ndvi_mean": row["ndvi_mean"], "ndvi_min": row["ndvi_min"],
                "ndvi_max": row["ndvi_max"],
                "green_area_pct": row["green_area_pct"],
                "green_area_km2": row.get("green_area_km2"),
                "total_area_km2": row.get("total_area_km2"),
                "data_quality": row.get("data_quality"),
                "from_cache": True, "cached_at": row["created_at"],
            }
        logger.info("♻️ Stale cache (district): %s/%s/%d — recomputing", province_name, district_name, year)
        supa_call(lambda s: s.table("district_ndvi_annual").delete().eq("id", row["id"]).execute())

    logger.info("⏳ Computing district annual: %s/%s/%d", province_name, district_name, year)
    try:
        result = _compute_ndvi_annual(ee.Geometry(raw_geom), year, scale=100)
        if result is None:
            raise HTTPException(status_code=404,
                detail=f"ไม่พบข้อมูลภาพดาวเทียมสำหรับ {district_name} ในปี {year}")
        result.pop('green_area_m2_raw', None)

        supa_call(lambda s: s.table("district_ndvi_annual").insert({
            "province": province_name, "district": district_name, "year": year,
            **result,
            "cache_version": CURRENT_CACHE_VERSION,
        }).execute())

        return {
            "province": province_name, "district": district_name, "year": year,
            **result, "from_cache": False,
        }
    except HTTPException:
        raise
    except Exception:
        logger.error("❌ Error district [%s/%s/%d]", province_name, district_name, year, exc_info=True)
        raise internal_error()


# ── Province NDVI monthly ────────────────────────────────────────────────────
@router.get("/ndvi/{province_name}/monthly", response_model=NDVIMonthlyResponse)
def get_ndvi_monthly(province_name: str, year: YearParam = CURRENT_YEAR):
    raw_geom = get_province_geom(province_name)

    cached = supa_call(lambda s: s.table("ndvi_monthly")
                       .select("*").eq("province", province_name).eq("year", year).execute())
    if cached.data:
        logger.info("✅ Supabase hit: %s/%d/monthly", province_name, year)
        return {
            "province": province_name, "year": year,
            "monthly": cached.data[0]["monthly_data"],
            "from_cache": True, "cached_at": cached.data[0]["created_at"],
        }

    logger.info("⏳ Computing: %s/%d/monthly", province_name, year)
    try:
        results = _compute_ndvi_monthly(ee.Geometry(raw_geom), year, scale=500)
        supa_call(lambda s: s.table("ndvi_monthly").insert({
            "province": province_name, "year": year, "monthly_data": results,
            "cache_version": CURRENT_CACHE_VERSION,
        }).execute())
        return {"province": province_name, "year": year,
                "monthly": results, "from_cache": False}
    except Exception:
        logger.error("❌ Error monthly [%s/%d]", province_name, year, exc_info=True)
        raise internal_error()


# ── Province NDVI compare ────────────────────────────────────────────────────
@router.get("/ndvi/{province_name}/compare")
def get_ndvi_compare(province_name: str,
                     years: str = ",".join(str(y) for y in range(CURRENT_YEAR - 3, CURRENT_YEAR + 1))):
    ensure_province(province_name)
    if len(years) > 2000:  # bound parse cost — กัน query string ยักษ์
        raise HTTPException(status_code=400, detail="พารามิเตอร์ years ยาวเกินไป")
    year_list = sorted(set(int(y.strip()) for y in years.split(",") if y.strip().isdigit()))
    if not year_list:
        raise HTTPException(status_code=400, detail="years ต้องเป็นตัวเลขคั่นด้วย comma")
    out_of_range = [y for y in year_list if y < YEAR_MIN or y > YEAR_MAX]
    if out_of_range:
        raise HTTPException(status_code=400,
            detail=f"years ต้องอยู่ใน {YEAR_MIN}–{YEAR_MAX} · นอกช่วง: {out_of_range}")

    result = supa_call(lambda s: s.table("ndvi_annual")
                       .select("year,ndvi_mean,ndvi_min,ndvi_max,green_area_pct,green_area_km2,green_area_m2_per_person,who_status")
                       .eq("province", province_name)
                       .in_("year", year_list)
                       .order("year")
                       .execute())
    found = {row["year"]: row for row in result.data}
    data = [
        {"year": y, "available": True, **found[y]} if y in found
        else {"year": y, "available": False}
        for y in year_list
    ]
    return {"province": province_name, "data": data}


# ── Province NDVI annual ─────────────────────────────────────────────────────
@router.get("/ndvi/{province_name}", response_model=NDVIResponse)
def get_ndvi(province_name: str, year: YearParam = CURRENT_YEAR):
    raw_geom = get_province_geom(province_name)

    cached = supa_call(lambda s: s.table("ndvi_annual")
                       .select("*").eq("province", province_name).eq("year", year).execute())
    if cached.data:
        row = cached.data[0]
        if _is_stale(row):
            logger.info("♻️ Stale cache: %s/%d — recomputing", province_name, year)
            supa_call(lambda s: s.table("ndvi_annual").delete().eq("id", row["id"]).execute())
        else:
            logger.info("✅ Supabase hit: %s/%d", province_name, year)
            return {
                "province": province_name, "year": year,
                "ndvi_mean": row["ndvi_mean"], "ndvi_min": row["ndvi_min"],
                "ndvi_max": row["ndvi_max"],
                "green_area_pct": row["green_area_pct"],
                "green_area_km2": row.get("green_area_km2"),
                "total_area_km2": row.get("total_area_km2"),
                "green_area_m2_per_person": row.get("green_area_m2_per_person"),
                "population": row.get("population"),
                "population_year": row.get("population_year"),
                "who_status": row.get("who_status"),
                "data_quality": row.get("data_quality"),
                "from_cache": True, "cached_at": row["created_at"],
            }

    logger.info("⏳ Computing: %s/%d", province_name, year)
    try:
        result = _compute_ndvi_annual(ee.Geometry(raw_geom), year, scale=500)
        if result is None:
            raise HTTPException(status_code=404,
                detail=f"ไม่พบข้อมูลภาพดาวเทียมสำหรับ {province_name} ในปี {year}")

        green_area_m2 = result.pop('green_area_m2_raw', None)
        population, population_year = get_population(province_name, year)
        m2_per_person, who_status = compute_who_status(green_area_m2, population)

        full = {**result,
                "green_area_m2_per_person": m2_per_person,
                "population": population, "population_year": population_year,
                "who_status": who_status}

        supa_call(lambda s: s.table("ndvi_annual").insert({
            "province": province_name, "year": year, **full,
            "cache_version": CURRENT_CACHE_VERSION,
        }).execute())

        return {"province": province_name, "year": year, **full, "from_cache": False}
    except HTTPException:
        raise
    except Exception:
        logger.error("❌ Error [%s/%d]", province_name, year, exc_info=True)
        raise internal_error()
