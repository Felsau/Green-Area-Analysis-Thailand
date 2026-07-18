"""Land use composition — สัดส่วนการใช้ที่ดิน 5 ประเภทหลัก (นิยาม LDD) ต่อจังหวัด/อำเภอ.

ชั้นสรุปของ landuse.py (provider) — grouped area reduce ครั้งเดียวต่อ scope/ปี
แล้ว cache ใน in-process TTL (ผลไม่เปลี่ยนสำหรับ (scope, year) เดิม จนกว่า
provider เปลี่ยน) · COMPUTE_LOCK กันหลาย request คำนวณ scope เดียวกันพร้อมกัน
"""
import logging

import ee
from fastapi import APIRouter, HTTPException

from dependencies import (get_province_geom, get_district_geom,
                          CURRENT_YEAR, YearParam, internal_error)
from keyed_lock import COMPUTE_LOCK
from landuse import landuse_image_checked, landuse_meta, build_summary
from ttl_cache import TTLCache

router = APIRouter()
logger = logging.getLogger(__name__)

# ผลสรุปต่อ (scope, year) คงที่ — TTL ยาว (6 ชม.) แค่กัน process memory โตไม่หยุด
# ต่างจาก tile cache (30 นาที) เพราะไม่มี GEE session URL ที่หมดอายุมาเกี่ยว
_SUMMARY_TTL = 6 * 3600
_summary_cache = TTLCache(_SUMMARY_TTL, 300)

# scale 100m พอสำหรับสัดส่วนระดับจังหวัด/อำเภอ (DW native 10m — ลด pixel ลง 100
# เท่าให้ reduce เร็วขึ้นมาก ความคลาดเคลื่อนสัดส่วนระดับ <1%) · tileScale 4 กัน
# memory limit บนจังหวัดใหญ่ (pattern เดียวกับ urban.py)
_REDUCE_SCALE_M = 100


def _compute_summary(geom: ee.Geometry, province_name: str,
                     district_name: str | None, year: int, scope: str) -> dict:
    """คำนวณสัดส่วนสด (GEE) → response dict · raise 404 เมื่อไม่มีภาพ DW ปีนั้น"""
    lu = landuse_image_checked(geom, year)
    if lu is None:
        raise HTTPException(status_code=404,
            detail=f"ไม่พบข้อมูล Dynamic World สำหรับ {scope} ปี {year}")

    # พื้นที่ (m²) รวมต่อประเภท — group ด้วยค่า band 'landuse' → roundtrip เดียว
    grouped = (ee.Image.pixelArea().addBands(lu)
               .reduceRegion(
                   reducer=ee.Reducer.sum().group(groupField=1, groupName='landuse'),
                   geometry=geom, scale=_REDUCE_SCALE_M,
                   maxPixels=1e10, bestEffort=True, tileScale=4)
               .get('groups').getInfo())
    area_by_value = {int(g['landuse']): float(g['sum']) for g in grouped}

    return {"province": province_name, "district": district_name, "year": year,
            **landuse_meta(year), **build_summary(area_by_value)}


@router.get("/analysis/landuse/{province_name}")
def get_landuse_summary(province_name: str, year: YearParam = CURRENT_YEAR,
                        district_name: str | None = None):
    """สัดส่วนการใช้ที่ดิน 5 ประเภทหลัก (ตามนิยามกรมพัฒนาที่ดิน) ของจังหวัด/อำเภอ.

    แหล่งข้อมูล: Dynamic World 10m composite รายปี (mode) จัดกลุ่มเข้า schema
    LDD — response แนบ source/data_year ให้ผู้ใช้รู้ที่มาเสมอ (เฟส B จะเพิ่ม
    provider ข้อมูล LDD 1:25,000 โดย response shape เดิม)
    """
    if district_name:
        raw_geom = get_district_geom(province_name, district_name)
        scope = f"{province_name}/{district_name}"
    else:
        raw_geom = get_province_geom(province_name)
        scope = province_name

    key = ("landuse", province_name, district_name, year)
    cached = _summary_cache.get(key)
    if cached is not None:
        return cached

    # cache miss — ล็อกต่อ key กัน request ซ้ำยิง GEE compute พร้อมกัน แล้ว re-check
    with COMPUTE_LOCK.hold(key):
        cached = _summary_cache.get(key)
        if cached is not None:
            return cached
        logger.info("⏳ Computing land use summary: %s/%d", scope, year)
        try:
            result = _compute_summary(ee.Geometry(raw_geom), province_name,
                                      district_name, year, scope)
            _summary_cache.set(key, result)
            return result
        except HTTPException:
            raise
        except ee.EEException as ee_err:
            # ภาพมีแต่ compute พัง (all-masked/edge case) → 422 + แนะนำเปลี่ยนปี
            # แนวเดียวกับ tiles/recommend แทน 500 generic
            logger.warning("⚠️  Land use GEE compute failed [%s/%d]: %s",
                           scope, year, ee_err)
            raise HTTPException(status_code=422, detail=(
                f"คำนวณสัดส่วนการใช้ที่ดินปี {year} ไม่สำเร็จ — "
                "ข้อมูลดาวเทียมอาจไม่ครอบคลุมพื้นที่/ช่วงเวลานี้ ลองเลือกปีก่อนหน้า"
            ))
        except Exception:
            logger.error("❌ Land use summary error [%s/%d]", scope, year,
                         exc_info=True)
            raise internal_error()
