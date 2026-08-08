"""Custom-area analysis — วิเคราะห์ NDVI/พื้นที่สีเขียว/LST บน polygon ที่ผู้ใช้วาดเอง.

ต่างจาก /ndvi/{province} ตรงที่ไม่ผูกกับขอบเขต admin ที่ load ไว้ล่วงหน้า — รับ
GeoJSON Polygon ดิบจาก client แล้ว compute สดทุกครั้ง (ไม่ cache เพราะ geometry
ไม่ซ้ำ) · ประชากรใช้ WorldPop sum *ภายในพื้นที่จริง* ทำให้ค่า m²/คน ตรงกับขอบเขต
ที่วาดมากกว่าการ map กับประชากรทั้งจังหวัด (ค่านี้เทียบ WHO เป็น "ค่าอ้างอิง" เท่านั้น
ไม่ใช่เกณฑ์ตัดสิน — ดู routers/ndvi/compute.py::compute_who_status)

Validation/area helpers อยู่ใน polygon_utils.py (pure, test ได้โดยไม่ต้องแตะ GEE)
— ดู tests/test_pure_helpers.py
"""
import logging

import ee
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from dependencies import (internal_error, worldpop_unavailable_error, CURRENT_YEAR,
                          YEAR_MIN, YEAR_MAX, WORLDPOP_YEAR)
from gee_utils import get_lst_col, reduce_lst, worldpop_pop_collection
from polygon_utils import validate_drawn_polygon
from routers.ndvi.compute import _compute_ndvi_annual, compute_who_status
from schemas import CustomAreaResponse

router = APIRouter()
logger = logging.getLogger(__name__)


class CustomAreaRequest(BaseModel):
    """Body ของ POST /analysis/custom-area"""
    geometry: dict = Field(..., description="GeoJSON Polygon geometry")
    year: int = Field(default=CURRENT_YEAR, ge=YEAR_MIN, le=YEAR_MAX,
                      description=f"ปี ค.ศ. ระหว่าง {YEAR_MIN}–{YEAR_MAX}")


def _population_in_geom(geom: ee.Geometry) -> int:
    """รวมประชากร (WorldPop 100m, ปี WORLDPOP_YEAR) ภายใน geometry.

    เช็ค size ก่อนเหมือน urban.py — ถ้า WorldPop ไม่มีปีนี้ .first() = null →
    error คลุมเครือ ('input may not be null') · ตอบ 503 บอกวิธีแก้แทน
    """
    pop_col = worldpop_pop_collection(WORLDPOP_YEAR)
    if pop_col.size().getInfo() == 0:
        raise worldpop_unavailable_error(WORLDPOP_YEAR)
    pop = (ee.Image(pop_col.first()).select('population')
           .reduceRegion(reducer=ee.Reducer.sum(), geometry=geom,
                         scale=100, maxPixels=1e10, bestEffort=True)
           .get('population').getInfo()) or 0
    return int(round(pop))


def _lst_in_geom(geom: ee.Geometry, year: int):
    """LST mean/min/max (°C) ภายใน geometry — คืน (None, None, None) ถ้าไม่มี Landsat
    (LST เป็นข้อมูลเสริม ไม่ควรทำทั้ง request พังถ้าปีนั้นไม่มีภาพ Landsat)"""
    col = get_lst_col(geom, year)
    if col.size().getInfo() == 0:
        return None, None, None
    return reduce_lst(col, geom, scale=100)


@router.post("/analysis/custom-area", response_model=CustomAreaResponse)
def analyze_custom_area(req: CustomAreaRequest):
    """วิเคราะห์ NDVI + พื้นที่สีเขียว + ประชากร + LST บน polygon ที่ผู้ใช้วาดเอง.

    คำนวณสดทุกครั้ง (ไม่ cache) เพราะแต่ละ polygon ไม่ซ้ำกัน · มี guard พื้นที่/จำนวนจุด
    กัน compute หนักเกินจำเป็น
    """
    try:
        area_km2 = validate_drawn_polygon(req.geometry)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    year = req.year
    logger.info("⏳ Custom-area analyze: %.1f km² · ปี %d", area_km2, year)
    try:
        geom = ee.Geometry(req.geometry)
        ndvi = _compute_ndvi_annual(geom, year, scale=100)
        if ndvi is None:
            raise HTTPException(status_code=404,
                detail=f"ไม่พบภาพ Sentinel-2 ในพื้นที่นี้สำหรับปี {year} — ลองปีก่อนหน้า")
        green_area_m2 = ndvi.pop("green_area_m2_raw", None)

        population = _population_in_geom(geom)
        m2_per_person, who_status = compute_who_status(green_area_m2, population)
        lst_mean, lst_min, lst_max = _lst_in_geom(geom, year)

        return {
            "year": year,
            "area_km2": round(area_km2, 2),
            **ndvi,
            "population": population,
            "green_area_m2_per_person": m2_per_person,
            "who_status": who_status,
            "lst_mean": lst_mean, "lst_min": lst_min, "lst_max": lst_max,
            "worldpop_year": WORLDPOP_YEAR,
        }
    except HTTPException:
        raise
    except ee.EEException as ee_err:
        logger.warning("⚠️ Custom-area GEE compute failed (ปี %d): %s", year, ee_err)
        raise HTTPException(status_code=422, detail=(
            f"คำนวณพื้นที่สำหรับปี {year} ไม่สำเร็จ — "
            "ข้อมูลภาพถ่ายดาวเทียมอาจไม่ครอบคลุมพื้นที่นี้ ลองปีก่อนหน้า"
        ))
    except Exception:
        logger.error("❌ Custom-area error (ปี %d)", year, exc_info=True)
        raise internal_error()
