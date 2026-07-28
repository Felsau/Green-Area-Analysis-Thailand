from fastapi import APIRouter, HTTPException
import logging
import ee

from dependencies import (get_population, supa_call, internal_error, ensure_province,
                          get_province_geom, get_district_geom,
                          CURRENT_YEAR, YearParam, YEAR_MIN, YEAR_MAX,
                          CURRENT_CACHE_VERSION)
from keyed_lock import COMPUTE_LOCK
from schemas import NDVIResponse, NDVIMonthlyResponse
from validation import build_breakdown, build_validation, disagreement_sums
from .compute import (_is_stale, compute_who_status,
                      _compute_ndvi_annual, _compute_ndvi_monthly)

router = APIRouter()
logger = logging.getLogger(__name__)


# ── District NDVI monthly ────────────────────────────────── (before catch-all)
@router.get("/ndvi/{province_name}/districts/{district_name}/monthly")
def get_district_ndvi_monthly(province_name: str, district_name: str, year: YearParam = CURRENT_YEAR):
    raw_geom = get_district_geom(province_name, district_name)

    def _read_cache():
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
        return None

    hit = _read_cache()
    if hit is not None:
        return hit

    # cache miss — ล็อกต่อ key กัน request ซ้ำยิง GEE compute พร้อมกัน (ไม่งั้นชน
    # UNIQUE(province,district,year) ตอน insert พร้อมกัน → 500) แล้ว re-check
    with COMPUTE_LOCK.hold(("ndvi-district-monthly", province_name, district_name, year)):
        hit = _read_cache()
        if hit is not None:
            return hit
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

    def _read_cache():
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
                    "canopy": row.get("canopy"),
                    "from_cache": True, "cached_at": row["created_at"],
                }
            logger.info("♻️ Stale cache (district): %s/%s/%d — recomputing", province_name, district_name, year)
            # ลบก่อนตกไปคำนวณใหม่ ไม่งั้น insert รอบใหม่ชน UNIQUE(province,district,year)
            supa_call(lambda s: s.table("district_ndvi_annual").delete().eq("id", row["id"]).execute())
        return None

    hit = _read_cache()
    if hit is not None:
        return hit

    # cache miss — ล็อกต่อ key กัน request ซ้ำยิง GEE compute พร้อมกัน แล้ว re-check
    with COMPUTE_LOCK.hold(("ndvi-district-annual", province_name, district_name, year)):
        hit = _read_cache()
        if hit is not None:
            return hit
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

    def _read_cache():
        cached = supa_call(lambda s: s.table("ndvi_monthly")
                           .select("*").eq("province", province_name).eq("year", year).execute())
        if cached.data:
            logger.info("✅ Supabase hit: %s/%d/monthly", province_name, year)
            return {
                "province": province_name, "year": year,
                "monthly": cached.data[0]["monthly_data"],
                "from_cache": True, "cached_at": cached.data[0]["created_at"],
            }
        return None

    hit = _read_cache()
    if hit is not None:
        return hit

    with COMPUTE_LOCK.hold(("ndvi-monthly", province_name, year)):
        hit = _read_cache()
        if hit is not None:
            return hit
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


# ── NFR-08 validation (ระดับจังหวัด) ─────────────────────────────────────────
def _worldcover_reference_pct(province_name: str) -> float | None:
    """% พื้นที่สีเขียวตาม WorldCover ที่ backfill ไว้ — None ถ้ายังไม่ได้เติม.

    None = ข้ามการ validate ไปเงียบ ๆ (ไม่ใช่ error) เพื่อให้ระบบยังใช้งานได้ปกติ
    ก่อนรัน backfill_worldcover_reference.py · ดู migration 016
    """
    try:
        result = supa_call(lambda s: s.table("provinces")
                           .select("worldcover_green_pct")
                           .eq("name_en", province_name).limit(1).execute())
    except Exception:
        logger.warning("อ่านค่าอ้างอิง WorldCover ไม่สำเร็จ (%s) — ข้าม NFR-08",
                       province_name, exc_info=True)
        return None
    return result.data[0].get("worldcover_green_pct") if result.data else None


def _build_validation(result: dict, wc_ref_pct: float | None, year: int) -> dict | None:
    """สร้าง payload NFR-08 แล้ว **ถอน field ดิบออกจาก result** ก่อนถูก insert ลง DB.

    `extra_area_sums` / `total_area_m2_raw` เป็นค่ากลางของการคำนวณ ไม่มีคอลัมน์รองรับ
    ใน ndvi_annual — ถ้าหลุดติดไปกับ insert จะ error ทั้ง request
    """
    sums = result.pop("extra_area_sums", None)
    total_area_m2 = result.pop("total_area_m2_raw", None)
    if wc_ref_pct is None or sums is None or not total_area_m2:
        return None
    breakdown = build_breakdown(sums, total_area_m2, worldcover_green_pct=wc_ref_pct)
    return build_validation(result.get("green_area_pct"), wc_ref_pct, year,
                            breakdown=breakdown)


# ── Province NDVI annual ─────────────────────────────────────────────────────
@router.get("/ndvi/{province_name}", response_model=NDVIResponse)
def get_ndvi(province_name: str, year: YearParam = CURRENT_YEAR):
    raw_geom = get_province_geom(province_name)

    def _read_cache():
        cached = supa_call(lambda s: s.table("ndvi_annual")
                           .select("*").eq("province", province_name).eq("year", year).execute())
        if cached.data:
            row = cached.data[0]
            # require_validation=True เฉพาะระดับจังหวัด — NFR-08 ไม่ได้ทำระดับอำเภอ
            if _is_stale(row, require_validation=True):
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
                    "canopy": row.get("canopy"),
                    "validation": row.get("validation"),
                    "from_cache": True, "cached_at": row["created_at"],
                }
        return None

    hit = _read_cache()
    if hit is not None:
        return hit

    with COMPUTE_LOCK.hold(("ndvi-annual", province_name, year)):
        hit = _read_cache()
        if hit is not None:
            return hit
        logger.info("⏳ Computing: %s/%d", province_name, year)
        try:
            # NFR-08 — ค่าอ้างอิง WorldCover คงที่ต่อจังหวัด อ่านจากที่ backfill ไว้
            # (ไม่คิดสด — ~17.5 วิ จะดัน compute ทะลุงบ 60 วิ ของ NFR-01)
            wc_ref_pct = _worldcover_reference_pct(province_name)
            result = _compute_ndvi_annual(
                ee.Geometry(raw_geom), year, scale=500,
                extra_sums_fn=disagreement_sums if wc_ref_pct is not None else None)
            if result is None:
                raise HTTPException(status_code=404,
                    detail=f"ไม่พบข้อมูลภาพดาวเทียมสำหรับ {province_name} ในปี {year}")

            green_area_m2 = result.pop('green_area_m2_raw', None)
            population, population_year = get_population(province_name, year)
            m2_per_person, who_status = compute_who_status(green_area_m2, population)
            validation = _build_validation(result, wc_ref_pct, year)

            full = {**result,
                    "green_area_m2_per_person": m2_per_person,
                    "population": population, "population_year": population_year,
                    "who_status": who_status,
                    "validation": validation}

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
