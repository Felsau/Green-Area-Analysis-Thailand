"""Provider LDD — การใช้ประโยชน์ที่ดินกรมพัฒนาที่ดิน (LDD 1:25,000) เป็น provider ที่สอง.

เป็น provider ตัวที่สองต่อจาก Dynamic World (ดู landuse.py) ที่ป้อน ee.Image band
'landuse' ค่า 1–5 (ประเภทหลัก LDD) เข้าชั้นสรุป/tiles ชุดเดิม — schema กลางตัวเดียวกัน
(U/A/F/W/M = value 1–5) จึงไม่ต้องแตะชั้นแสดงผลใดๆ ต่างกันแค่ "แหล่งข้อมูล":

    Dynamic World : ดาวเทียม land *cover* รายปี ครอบคลุมทั้งประเทศ (จำแนกอัตโนมัติ)
    LDD           : ข้อมูลราชการ land *use* สำรวจภาคสนาม รายจังหวัด (แม่นแต่คงที่ราย edition)

ที่มา: shapefile LU_BKK_2566 (กรุงเทพฯ ปี 2566) อัปโหลดเป็น GEE FeatureCollection asset
แล้วชี้ผ่าน env LDD_LANDUSE_ASSET (ดู data/ldd/README.md) · asset ยังไม่ตั้งค่า →
ldd_available() = False → endpoint ตอบ 404 ที่อ่านรู้เรื่องแทนล่ม

ต่างจาก DW ตรงที่สรุปพื้นที่คิดจาก **Shape_Area ของ polygon จริง** (พื้นที่ทางการ
ระดับ 1:25,000) ไม่ใช่ประมาณจาก pixel — แม่นกว่าและได้ตัวเลขไร่/ตร.กม.ตรงกับเอกสาร LDD
ส่วน tiles ยัง rasterize polygon → ee.Image เพื่อวาดทับ basemap แบบ pixel เหมือน DW
"""
import os

import ee

from landuse import CATEGORY_BY_VALUE
from ldd_codes import LDD_LU_CODES

# ── การตั้งค่า asset ──────────────────────────────────────────────────────────
# GEE FeatureCollection asset id (เช่น 'projects/xxx/assets/LU_BKK_2566') ที่ได้จาก
# earthengine upload table ของ shapefile LDD · ไม่ตั้ง = provider ปิด (ดู README)
LDD_ASSET_ID = os.getenv("LDD_LANDUSE_ASSET")

# จังหวัดที่ asset ปัจจุบันครอบคลุม — ใช้บอกผู้ใช้/gate UI (edition นี้ = กทม.เท่านั้น)
# เพิ่มจังหวัดในอนาคต: อัปโหลด asset รวม แล้วเติมชื่อ (EN, ตรงกับ get_province_geom)
LDD_COVERAGE_PROVINCES = ("Bangkok Metropolis",)

# edition ของข้อมูล (คงที่ ไม่ผูกปีที่ผู้ใช้เลือก ต่างจาก DW ที่มีรายปี)
_DATA_YEAR_BE = 2566
_DATA_YEAR_CE = 2023

# ── mapping ประเภทหลัก / รหัสละเอียด → เลข (สำหรับ rasterize + grouped reduce) ──
# ตัวอักษร LUL1_CODE บน asset → value 1–5 ของ schema กลาง (ทำเป็น ee.Dictionary
# ตอน runtime — ไม่สร้าง ee object ระดับ module กัน import ก่อน ee.Initialize)
_L1_TO_VALUE = {"U": 1, "A": 2, "F": 3, "W": 4, "M": 5}

# LU_CODE (string) ↔ id เลข — reduceColumns group ต้องใช้ group field เป็นตัวเลข
# id เรียงตามลำดับ code (คงที่) → group ผลลัพธ์ map กลับเป็น code ได้
_CODE_TO_ID = {code: i for i, code in enumerate(sorted(LDD_LU_CODES), start=1)}
_ID_TO_CODE = {i: code for code, i in _CODE_TO_ID.items()}


def ldd_available() -> bool:
    """ตั้งค่า asset แล้วหรือยัง — endpoint เช็คก่อนเรียก provider นี้"""
    return bool(LDD_ASSET_ID)


def ldd_covers(province_name: str) -> bool:
    """asset ปัจจุบันครอบคลุมจังหวัดนี้ไหม (edition กทม.) — ใช้ตอบ error ที่ชัด"""
    return province_name in LDD_COVERAGE_PROVINCES


def _feature_collection() -> ee.FeatureCollection:
    return ee.FeatureCollection(LDD_ASSET_ID)


def _with_value(fc: ee.FeatureCollection) -> ee.FeatureCollection:
    """เติม property 'lu_value' (1–5) ต่อ feature จาก LUL1_CODE — ใช้ rasterize"""
    lut = ee.Dictionary(_L1_TO_VALUE)
    return fc.map(lambda f: f.set("lu_value", lut.get(f.get("LUL1_CODE"))))


def ldd_landuse_image(geom: ee.Geometry, year: int | None = None) -> ee.Image:
    """ee.Image band 'landuse' ค่า 1–5 จาก polygon LDD — lazy (สำหรับ tiles).

    year รับไว้ให้ signature ตรงกับ provider DW แต่ไม่ใช้ (LDD เป็น snapshot เดียว) ·
    reduceToImage(first) วาดค่า lu_value ของ polygon ลง raster → pixel นอก polygon
    ถูก mask (ตรงกับที่ต้องการสำหรับ overlay) · กรอง LUL1_CODE ให้เหลือเฉพาะ U/A/F/W/M
    ก่อน map กัน value null (จากรหัสแปลกปลอม) ทำ reduceToImage ทั้งภาพพัง
    """
    known = _feature_collection().filterBounds(geom).filter(
        ee.Filter.inList("LUL1_CODE", list(_L1_TO_VALUE)))
    fc = _with_value(known)
    return (fc.reduceToImage(["lu_value"], ee.Reducer.first())
              .rename("landuse").clip(geom))


def ldd_landuse_image_checked(geom: ee.Geometry,
                              year: int | None = None) -> ee.Image | None:
    """เหมือน ldd_landuse_image แต่คืน None เมื่อ asset ปิด/ไม่มี polygon ในพื้นที่.

    ให้ endpoint ตอบ 404 ที่อ่านรู้เรื่อง (แนวเดียวกับ landuse_image_checked ของ DW)
    """
    if not ldd_available():
        return None
    if _feature_collection().filterBounds(geom).size().getInfo() == 0:
        return None
    return ldd_landuse_image(geom)


def ldd_summary_areas(geom: ee.Geometry) -> tuple[dict[int, float], dict[str, float]]:
    """(area_by_value m², area_by_code m²) จากพื้นที่ polygon จริง — grouped reduce เดียว.

    รวม Shape_Area (m², เพราะ prj เป็น UTM) จัดกลุ่มตาม LU_CODE ครั้งเดียว → ได้
    breakdown รหัสละเอียด แล้ว roll up เป็น 5 ประเภทหลักฝั่ง Python (code→ประเภทหลัก
    รู้จาก legend อยู่แล้ว ไม่ต้องยิง GEE ซ้ำ) · filterBounds: ระดับจังหวัด = polygon
    อยู่ในเขตครบ → พื้นที่ทางการเป๊ะ; ระดับอำเภอ polygon คร่อมขอบถูกนับเต็ม (คลาดเล็กน้อย)
    """
    id_lut = ee.Dictionary(_CODE_TO_ID)
    fc = (_feature_collection().filterBounds(geom)
          .map(lambda f: f.set("code_id", id_lut.get(f.get("LU_CODE"))))
          .filter(ee.Filter.notNull(["code_id"])))
    grouped = (fc.reduceColumns(
                   ee.Reducer.sum().group(groupField=1, groupName="code"),
                   ["Shape_Area", "code_id"])
                 .get("groups").getInfo())

    area_by_code: dict[str, float] = {}
    for g in grouped:
        cid = g.get("code")
        code = _ID_TO_CODE.get(int(cid)) if cid is not None else None
        if code:
            area_by_code[code] = float(g["sum"])
    return _rollup_by_value(area_by_code), area_by_code


def _rollup_by_value(area_by_code: dict[str, float]) -> dict[int, float]:
    """รวมพื้นที่ตาม LU_CODE → 5 ประเภทหลัก (value 1–5) — pure, test ได้"""
    by_value: dict[int, float] = {}
    for code, m2 in area_by_code.items():
        value = LDD_LU_CODES[code][0]
        by_value[value] = by_value.get(value, 0.0) + m2
    return by_value


def build_detail(area_by_code: dict[str, float], top: int = 12) -> list[dict]:
    """รหัสละเอียด LDD ที่พื้นที่มากสุด → แถวพร้อมแสดง (pure, test ได้) — additive.

    เสริมชั้นสรุป 5 ประเภทของ DW ด้วยรายละเอียดที่ DW ให้ไม่ได้ (นาข้าว/โรงงาน/
    ป่าชายเลน ฯลฯ) · share_pct คิดจากพื้นที่รวมของ polygon ที่จำแนกได้ · color ยึด
    สีประเภทหลักของ code นั้น (tint ตามกลุ่ม) — ตัดเอา top อันดับแรก
    """
    total_m2 = sum(area_by_code.values())
    ordered = sorted(area_by_code.items(), key=lambda kv: kv[1], reverse=True)
    rows = []
    for code, m2 in ordered[:top]:
        l1_value, name_th, name_en = LDD_LU_CODES[code]
        rows.append({
            "code": code, "l1_value": l1_value,
            "name_th": name_th, "name_en": name_en,
            "color": CATEGORY_BY_VALUE[l1_value]["color"],
            "area_km2": round(m2 / 1e6, 2),
            "share_pct": round(m2 / total_m2 * 100, 1) if total_m2 else 0,
        })
    return rows


def ldd_meta() -> dict:
    """metadata แหล่งข้อมูล LDD — แนบทุก response ให้ UI/รายงานบอกที่มาได้เสมอ.

    data_year = ปี พ.ศ. ของ edition (คงที่ ไม่ใช่ปีที่ผู้ใช้เลือก) · data_year_ce
    ให้ ค.ศ. คู่กัน · coverage บอกขอบเขตที่ asset ครอบคลุม
    """
    return {"source": "ldd",
            "source_label": "กรมพัฒนาที่ดิน (LDD) 1:25,000",
            "data_year": _DATA_YEAR_BE,
            "data_year_ce": _DATA_YEAR_CE,
            "coverage": "กรุงเทพมหานคร"}
