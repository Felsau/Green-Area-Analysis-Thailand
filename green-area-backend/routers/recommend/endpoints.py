"""Recommendation endpoints — province + district level.

Priority Score = (1−W_PERI)·(w1·NDVI_deficit + w2·LST_heat + w3·pop_need + w4·access_need)
                 + W_PERI·peri_urban_need
- NDVI_deficit : พื้นที่ NDVI ต่ำ = ขาดต้นไม้ → ค่าสูงคือควรปลูก
- LST_heat     : อุณหภูมิผิวพื้นสูง = ร้อนเกินต้องการพืช → ค่าสูงคือควรปลูก
- pop_need     : ประชากรหนาแน่น (WorldPop) = คนเยอะต้องการพื้นที่สีเขียว
- access_need  : ไกลจากพื้นที่สีเขียวเดิม = เข้าถึงยาก (equity) → ค่าสูงคือควรปลูก
- peri_urban   : ขอบเมืองกำลังขยาย (ISA ปานกลาง, Dynamic World) = ปลูกลดร้อนคุ้มสุด
                 (Moukomla et al. 2026) → ปัจจัยคงที่ W_PERI, ไม่แตะ slider ผู้ใช้ 4 ตัว

Province + district ใช้ flow เดียวกันทุกขั้น ต่างแค่ geometry/cache-key →
รวมไว้ใน _run_recommendation() (district_name=None = province-level)
"""
import logging

import ee
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from dependencies import (supa_call, internal_error, RECOMMEND_CACHE_VERSION,
                          PROVINCE_GEOMETRIES, get_province_geom, get_district_geom,
                          CURRENT_YEAR, YEAR_MIN, YEAR_MAX, YearParam, WeightParam,
                          WORLDPOP_YEAR)
from impact import estimate_impact
from polygon_utils import validate_drawn_polygon

from .scoring import (W_NDVI, W_LST, W_POP, W_ACCESS,
                      normalize_weights, assert_imagery_available,
                      compute_priority, get_top_locations,
                      compute_plantable_area_m2, get_heatmap_url)
from .species import get_recommended_species
from .tile_cache import get_cached_tile_url, store_tile_url
from keyed_lock import COMPUTE_LOCK

router = APIRouter()
logger = logging.getLogger(__name__)


def _metric_tables(district_name: str | None) -> tuple[str, str]:
    """คืน (lst_table, ndvi_table) ตามระดับที่ขอ — province vs district.
    แยกเป็น helper เล็กๆ เพื่อ unit-test การ route ตารางได้โดยไม่แตะ DB"""
    if district_name is None:
        return "province_lst_annual", "ndvi_annual"
    return "district_lst_annual", "district_ndvi_annual"


def _site_metrics(province_name: str, district_name: str | None, year: int):
    """NDVI/LST เฉลี่ยจาก cache (ปีที่ขอ) — ใช้จัดอันดับพันธุ์ไม้ตามสภาพพื้นที่.

    district_name=None → ระดับจังหวัด (ndvi_annual / province_lst_annual);
    มีค่า → ระดับอำเภอ (district_ndvi_annual / district_lst_annual) เพื่อให้พันธุ์ไม้
    สะท้อนสภาพอำเภอจริง ไม่ใช่ค่าเฉลี่ยทั้งจังหวัด · คืน (lst_mean, ndvi_mean) ·
    None รายตัวถ้าไม่มีใน cache → species fallback ลำดับภาค"""
    lst_table, ndvi_table = _metric_tables(district_name)

    def _one(table, col):
        def _q(s):
            q = (s.table(table).select(col)
                 .eq("province", province_name).eq("year", year))
            if district_name is not None:
                q = q.eq("district", district_name)
            return q.limit(1).execute()
        try:
            rows = supa_call(_q).data
            return rows[0][col] if rows else None
        except Exception:
            return None

    return _one(lst_table, "lst_mean"), _one(ndvi_table, "ndvi_mean")


def _imagery_unavailable_error(year: int, district_name: str | None) -> HTTPException:
    """HTTPException 422 มาตรฐานเมื่อ GEE คำนวณ priority ไม่สำเร็จ (ภาพถ่ายไม่ครอบคลุม).

    ข้อความเดียวกันทุก path (province / district / custom-area / cache-refresh) กัน
    drift — เดิม cache-refresh ไม่ดัก ee.EEException เลยคืน 500 generic ต่างจาก path
    คำนวณสดที่คืน 422 + คำแนะนำให้เปลี่ยนปี
    """
    scope = "อำเภอนี้" if district_name else "พื้นที่นี้"
    return HTTPException(status_code=422, detail=(
        f"คำนวณ priority สำหรับปี {year} ไม่สำเร็จ — "
        f"ข้อมูลภาพถ่ายดาวเทียมอาจไม่ครอบคลุม{scope} ลองปีก่อนหน้านี้"
    ))


def _compute_recommendation_payload(geom: ee.Geometry, year: int,
                                    weights: tuple[float, float, float, float],
                                    species: list):
    """Shared compute: assert imagery → priority heatmap URL + top-10 + plantable impact.

    คืน (tile_url, top_locations, impact) · เรียก *ภายใน* try ของ caller เพราะ
    province/district (cache) กับ custom-area แปลง ee.EEException เป็น 422 ด้วยข้อความ
    scope ต่างกัน — helper จึงไม่ดักเอง · รวม flow ที่เดิมเขียนซ้ำสองชุด (เดิมต่างกันแค่
    geometry/response) ให้แก้ที่เดียวเวลา compute logic เปลี่ยน
    """
    assert_imagery_available(geom, year)
    (priority, ndvi_deficit, lst_heat, pop_need, access_need, peri_need,
     plantable) = compute_priority(geom, year, *weights)
    tile_url = get_heatmap_url(priority)
    top = get_top_locations(priority, ndvi_deficit, lst_heat, pop_need, access_need,
                            peri_need, geom, plantable, n=10)
    plantable_m2 = compute_plantable_area_m2(priority, plantable, geom)
    impact = estimate_impact(plantable_m2, species)
    return tile_url, top, impact


def _run_recommendation(province_name: str, district_name: str | None,
                        raw_geom: dict, year: int,
                        w_ndvi: float, w_lst: float, w_pop: float, w_access: float):
    """Province/district recommendation — ล็อกต่อ key เฉพาะ default weights กัน
    cache stampede (request เดียวกันยิง GEE compute หนักซ้ำพร้อมกัน) แล้ว delegate
    ไป _run_recommendation_inner · custom weights ไม่ cache จึงไม่ต้องล็อก ·
    cache lookup ใน inner ทำหน้าที่ re-check หลังได้ lock ในตัว (เจอ row ที่ request
    ก่อนหน้า compute ไว้แล้ว → ไม่ต้องคำนวณซ้ำ)
    """
    nw = normalize_weights(w_ndvi, w_lst, w_pop, w_access)
    if nw == (W_NDVI, W_LST, W_POP, W_ACCESS):
        with COMPUTE_LOCK.hold(("recommend", province_name, district_name, year)):
            return _run_recommendation_inner(province_name, district_name,
                                             raw_geom, year, *nw)
    return _run_recommendation_inner(province_name, district_name,
                                     raw_geom, year, *nw)


def _run_recommendation_inner(province_name: str, district_name: str | None,
                              raw_geom: dict, year: int,
                              w_ndvi: float, w_lst: float, w_pop: float, w_access: float):
    """Shared province/district recommendation flow.

    district_name=None → province-level (cache row มี district IS NULL).
    Caller รับผิดชอบ validate geometry + return 404 ก่อนเรียก helper นี้.
    """
    w_ndvi, w_lst, w_pop, w_access = normalize_weights(w_ndvi, w_lst, w_pop, w_access)
    is_default = (w_ndvi, w_lst, w_pop, w_access) == (W_NDVI, W_LST, W_POP, W_ACCESS)
    lst_mean, ndvi_mean = _site_metrics(province_name, district_name, year)
    species_info = get_recommended_species(province_name, lst_mean, ndvi_mean)
    label = province_name if district_name is None else f"{province_name}/{district_name}"

    def _base_response(**extra):
        resp = {"province": province_name, "year": year,
                "weights": {"ndvi": w_ndvi, "lst": w_lst, "population": w_pop,
                            "access": w_access},
                # ประชากรมาจาก WorldPop raster ปีคงที่ (ดู scoring.compute_priority) —
                # surface ให้ client รู้ว่า pop_need คิดบนข้อมูลปีไหน (อาจ ≠ year ที่ขอ)
                "worldpop_year": WORLDPOP_YEAR,
                "recommended_species": species_info, **extra}
        if district_name is not None:
            resp["district"] = district_name
        return resp

    # Custom weights → bypass DB cache (top_locations จะต่างไปทุก combination)
    if is_default:
        def _cache_query(s):
            q = (s.table("planting_recommendations").select("*")
                 .eq("province", province_name).eq("year", year))
            q = (q.is_("district", "null") if district_name is None
                 else q.eq("district", district_name))
            return q.execute()
        cached = supa_call(_cache_query)
        row = cached.data[0] if cached.data else None
        # row ที่ cache_version < ปัจจุบัน = คำนวณก่อนยุค plantability mask → stale,
        # ลบทิ้งแล้วตกไปคำนวณใหม่ด้านล่าง (ลบก่อน ไม่งั้น insert รอบใหม่ชน
        # UNIQUE(province,district,year)) — pattern เดียวกับ ndvi/urban cache
        if row and row.get("cache_version", 0) < RECOMMEND_CACHE_VERSION:
            logger.info("♻️ Recommend stale cache: %s/%d — recomputing", label, year)
            supa_call(lambda s: s.table("planting_recommendations")
                      .delete().eq("id", row["id"]).execute())
            row = None
        if row:
            tile_url = get_cached_tile_url(province_name, district_name, year)
            impact = row.get("impact")
            # tile URL หมดอายุพร้อม GEE session / impact อาจยังไม่เคย back-fill
            if tile_url is None or impact is None:
                try:
                    geom = ee.Geometry(raw_geom)
                    priority, _, _, _, _, _, plantable = compute_priority(
                        geom, year, w_ndvi, w_lst, w_pop, w_access)
                    if tile_url is None:
                        tile_url = get_heatmap_url(priority)
                        store_tile_url(province_name, district_name, year, tile_url)
                    if impact is None:
                        plantable_m2 = compute_plantable_area_m2(priority, plantable, geom)
                        impact = estimate_impact(plantable_m2, species_info.get("species", []))
                        # back-fill impact ลง cache row เพื่อรอบหลังไม่ต้อง recompute
                        try:
                            supa_call(lambda s: s.table("planting_recommendations")
                                .update({"impact": impact}).eq("id", row["id"]).execute())
                        except Exception as cache_err:
                            logger.warning("⚠️  Impact back-fill failed (non-fatal): %s", cache_err)
                except ee.EEException as ee_err:
                    # คำนวณสดตอน refresh พลาด (asset edge case / all-masked) — คืน 422
                    # + คำแนะนำเปลี่ยนปี ให้ตรงกับ path คำนวณสด ไม่ใช่ 500 generic
                    logger.warning("⚠️  Recommend tile refresh GEE failed [%s/%d]: %s", label, year, ee_err)
                    raise _imagery_unavailable_error(year, district_name)
                except Exception:
                    logger.error("❌ Recommend tile refresh error [%s/%d]", label, year, exc_info=True)
                    raise internal_error()
            return _base_response(tile_url=tile_url, top_locations=row.get("top_locations") or [],
                                  impact=impact, from_cache=True, cached_at=row.get("created_at"))

    logger.info("⏳ Computing recommendation: %s/%d (w=%.2f/%.2f/%.2f/%.2f%s)",
                label, year, w_ndvi, w_lst, w_pop, w_access, "" if is_default else " custom")
    try:
        geom = ee.Geometry(raw_geom)
        tile_url, top, impact = _compute_recommendation_payload(
            geom, year, (w_ndvi, w_lst, w_pop, w_access), species_info.get("species", []))

        # Cache เฉพาะ default weights (ไม่งั้นจะปนกัน + DB บวมโดยเปล่าประโยชน์)
        if is_default:
            store_tile_url(province_name, district_name, year, tile_url)
            try:
                # ไม่เก็บ tile_url ลง DB — URL ผูก GEE session ที่หมดอายุใน ~ชั่วโมง
                # (ดู get_heatmap_url docstring) · cache-hit อ่านจาก in-process TTL
                # cache แล้ว refresh ใหม่ทุกครั้งที่ serve แทน
                supa_call(lambda s: s.table("planting_recommendations").insert({
                    "province": province_name, "district": district_name, "year": year,
                    "top_locations": top, "impact": impact,
                    "cache_version": RECOMMEND_CACHE_VERSION,
                }).execute())
            except Exception as cache_err:
                logger.warning("⚠️  Cache insert failed (non-fatal): %s", cache_err)

        return _base_response(tile_url=tile_url, top_locations=top,
                              impact=impact, from_cache=False)
    except HTTPException:
        raise
    except ee.EEException as ee_err:
        # GEE คำนวณไม่สำเร็จ (data ขาดบางส่วน, asset edge case) — assert ก่อนหน้า
        # จับได้แค่ collection ว่างทั้งดุ้น แต่ image ที่ all-masked ก็ทำให้ getMapId
        # พังด้วย 'input may not be null' เช่นกัน → 422 + แนะนำให้เปลี่ยนปี
        logger.warning("⚠️  GEE compute failed [%s/%d]: %s", label, year, ee_err)
        raise _imagery_unavailable_error(year, district_name)
    except Exception:
        logger.error("❌ Recommend error [%s/%d]", label, year, exc_info=True)
        raise internal_error()


# ── Province-level recommendation ────────────────────────────────────────────
@router.get("/recommend/{province_name}")
def recommend_province(province_name: str, year: YearParam = CURRENT_YEAR,
                       w_ndvi: WeightParam = W_NDVI, w_lst: WeightParam = W_LST,
                       w_pop: WeightParam = W_POP, w_access: WeightParam = W_ACCESS):
    raw_geom = get_province_geom(province_name)
    return _run_recommendation(province_name, None, raw_geom, year,
                               w_ndvi, w_lst, w_pop, w_access)


# ── District-level recommendation ────────────────────────────────────────────
@router.get("/recommend/{province_name}/districts/{district_name}")
def recommend_district(province_name: str, district_name: str,
                       year: YearParam = CURRENT_YEAR,
                       w_ndvi: WeightParam = W_NDVI, w_lst: WeightParam = W_LST,
                       w_pop: WeightParam = W_POP, w_access: WeightParam = W_ACCESS):
    raw_geom = get_district_geom(province_name, district_name)
    return _run_recommendation(province_name, district_name, raw_geom, year,
                               w_ndvi, w_lst, w_pop, w_access)


# ── Custom-area recommendation (user-drawn polygon) ──────────────────────────
class CustomAreaRecommendRequest(BaseModel):
    """Body ของ POST /recommend/custom-area"""
    geometry: dict = Field(..., description="GeoJSON Polygon geometry")
    year: int = Field(default=CURRENT_YEAR, ge=YEAR_MIN, le=YEAR_MAX,
                      description=f"ปี ค.ศ. ระหว่าง {YEAR_MIN}–{YEAR_MAX}")
    # ใบ้จังหวัด (centroid ตกในจังหวัดไหน) — ใช้เลือกพันธุ์ไม้ตามภาคเท่านั้น
    province: str | None = Field(default=None, description="ชื่อจังหวัด (อังกฤษ) สำหรับเลือกพันธุ์ไม้")
    w_ndvi: float = Field(default=W_NDVI, ge=0, le=1)
    w_lst: float = Field(default=W_LST, ge=0, le=1)
    w_pop: float = Field(default=W_POP, ge=0, le=1)
    w_access: float = Field(default=W_ACCESS, ge=0, le=1)


@router.post("/recommend/custom-area")
def recommend_custom_area(req: CustomAreaRecommendRequest):
    """AI Recommend (priority heatmap + top-10 + impact + พันธุ์ไม้) บน polygon ที่ผู้ใช้
    วาดเอง — คำนวณสดทุกครั้ง (ไม่ cache เพราะ geometry ไม่ซ้ำ) · พันธุ์ไม้เลือกตามภาค
    ของจังหวัดที่ centroid ตกอยู่ (ส่งมาใน req.province) — ถ้าไม่รู้ก็คืน species ว่าง"""
    try:
        area_km2 = validate_drawn_polygon(req.geometry)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    w_ndvi, w_lst, w_pop, w_access = normalize_weights(
        req.w_ndvi, req.w_lst, req.w_pop, req.w_access)
    # province ใช้แค่เลือกพันธุ์ไม้ — ถ้าไม่อยู่ใน whitelist ก็ข้าม (คืน species ว่าง)
    province = req.province if req.province in PROVINCE_GEOMETRIES else None
    lst_mean, ndvi_mean = _site_metrics(province, None, req.year) if province else (None, None)
    species_info = (get_recommended_species(province, lst_mean, ndvi_mean) if province
                    else {"region": None, "species": []})

    logger.info("⏳ Custom-area recommend: %.1f km² · ปี %d (w=%.2f/%.2f/%.2f/%.2f)",
                area_km2, req.year, w_ndvi, w_lst, w_pop, w_access)
    try:
        geom = ee.Geometry(req.geometry)
        tile_url, top, impact = _compute_recommendation_payload(
            geom, req.year, (w_ndvi, w_lst, w_pop, w_access), species_info.get("species", []))
        return {
            "year": req.year,
            "area_km2": round(area_km2, 2),
            "province": province,
            "weights": {"ndvi": w_ndvi, "lst": w_lst, "population": w_pop,
                        "access": w_access},
            "worldpop_year": WORLDPOP_YEAR,
            "tile_url": tile_url,
            "top_locations": top,
            "recommended_species": species_info,
            "impact": impact,
        }
    except HTTPException:
        raise
    except ee.EEException as ee_err:
        logger.warning("⚠️ Custom-area recommend GEE failed (ปี %d): %s", req.year, ee_err)
        # custom-area = polygon เดี่ยว ไม่มี district → scope "พื้นที่นี้"
        raise _imagery_unavailable_error(req.year, None)
    except Exception:
        logger.error("❌ Custom-area recommend error (ปี %d)", req.year, exc_info=True)
        raise internal_error()
