"""Land use (การใช้ประโยชน์ที่ดิน) — provider layer + จัดกลุ่ม 5 ประเภทหลักตามนิยาม LDD.

ชั้นข้อมูล "การใช้ที่ดิน" ของระบบ ออกแบบเป็น provider แยกจากชั้นสรุป/แสดงผล:
    provider (แหล่งข้อมูล → ee.Image ค่า 1–5) ─→ summarize / tiles / top-locations tag
ตอนนี้มี provider เดียวคือ Dynamic World (รายปี ครอบคลุมทั้งประเทศ) · เฟสต่อไป
เสียบข้อมูลกรมพัฒนาที่ดิน (LDD 1:25,000 รายจังหวัด) เป็น provider ที่สองได้โดย
ไม่แตะชั้นสรุป — ทุกอย่างหลังจาก ee.Image band 'landuse' ใช้ร่วมกัน

การจำแนก: ยึด 5 ประเภทหลักของกรมพัฒนาที่ดิน (LDD) เป็น schema กลาง
    U ชุมชนและสิ่งปลูกสร้าง · A พื้นที่เกษตรกรรม · F พื้นที่ป่าไม้ ·
    W พื้นที่น้ำ · M พื้นที่เบ็ดเตล็ด
Dynamic World 9 คลาสถูก map เข้า 5 ประเภทนี้ (ดู DW_TO_LDD) → frontend ผูกกับ
schema กลางเท่านั้น ไม่รู้จักคลาส DW → เปลี่ยน/เพิ่ม provider ได้โดย UI ไม่ต้องแก้
"""
import ee

# ── Schema กลาง: 5 ประเภทหลักตาม LDD ────────────────────────────────────────
# value = ค่า pixel ในภาพ (1–5, ต่อเนื่อง — ใช้เป็น vis min/max ของ tile ได้ตรงๆ)
# สีตาม convention แผนที่การใช้ที่ดินไทย: ชุมชน=แดง เกษตร=เหลือง ป่า=เขียว
# น้ำ=ฟ้า เบ็ดเตล็ด=เทา (hex ไม่มี # — ตาม format palette ของ GEE)
LANDUSE_CATEGORIES = [
    {"value": 1, "code": "U", "name_th": "ชุมชนและสิ่งปลูกสร้าง",
     "name_en": "Urban and built-up land", "color": "e5534b"},
    {"value": 2, "code": "A", "name_th": "พื้นที่เกษตรกรรม",
     "name_en": "Agricultural land", "color": "f2c94c"},
    {"value": 3, "code": "F", "name_th": "พื้นที่ป่าไม้",
     "name_en": "Forest land", "color": "1a9850"},
    {"value": 4, "code": "W", "name_th": "พื้นที่น้ำ",
     "name_en": "Water body", "color": "3d85c6"},
    {"value": 5, "code": "M", "name_th": "พื้นที่เบ็ดเตล็ด",
     "name_en": "Miscellaneous land", "color": "9aa0a6"},
]

# palette เรียงตาม value 1→5 — ใช้กับ vis {'min':1,'max':5} แล้วสีตรงประเภทพอดี
LANDUSE_PALETTE = [c["color"] for c in LANDUSE_CATEGORIES]
CATEGORY_BY_VALUE = {c["value"]: c for c in LANDUSE_CATEGORIES}

# แหล่งข้อมูลที่ endpoint การใช้ที่ดินรองรับ (ผลลัพธ์ schema เดียวกัน ต่างแค่ที่มา):
#   dynamic_world = provider นี้ (DW รายปี ทั้งประเทศ) · ldd = provider LDD (ดู ldd.py)
# เก็บชื่อไว้ที่ schema กลางให้ทั้ง summary + tiles endpoint import ที่เดียว
LANDUSE_SOURCES = ("dynamic_world", "ldd")

# ── แนวทางการปลูกต่อประเภทที่ดิน ─────────────────────────────────────────────
# ประเภทที่ดินกำหนด "วิธีปลูก" ไม่ใช่แค่ "ปลูกที่ไหน" — ใช้ติดจุด top-locations
# (scoring.get_top_locations) ให้แต่ละจุดบอกแนวทางที่ทำได้จริงบนที่ดินแบบนั้น ·
# เป็น descriptor additive: ไม่กระทบคะแนน/การเลือกจุด · key = value 1–5 ของ schema
PLANTING_GUIDANCE = {
    1: "ปลูกเป็นไม้ริมถนน/สวนหย่อมชุมชน — เลือกพันธุ์ทนมลพิษ รากไม่ทำลายทางเท้า",
    2: "ปลูกแบบวนเกษตร — แนวกันชนขอบแปลงหรือปลูกแซม เสริมรายได้ด้วยไม้ผล-ไม้เศรษฐกิจ",
    3: "ปลูกเสริมป่าเดิมด้วยพันธุ์พื้นถิ่น — เพิ่มความหลากหลายของชั้นเรือนยอด",
    4: "ปลูกไม้ริมตลิ่ง/ทนน้ำท่วม — กันการกัดเซาะและฟื้นแนวชายน้ำ",
    5: "ที่ว่าง/ทุ่งหญ้า — ปลูกป่าฟื้นฟูเต็มผืน ไม้บุกเบิกโตเร็วผสมพันธุ์พื้นถิ่น",
}

# ── Provider: Dynamic World ──────────────────────────────────────────────────
# DW label (คลาสความน่าจะเป็นสูงสุดต่อ pixel) → ประเภทหลัก LDD
# เหตุผลการจัดกลุ่ม: DW เป็น land *cover* — คลาสที่ไม่ใช่เมือง/เกษตร/ป่า/น้ำชัดๆ
# (ทุ่งหญ้า ไม้พุ่ม พื้นที่ลุ่ม ดินโล่ง หิมะ) เข้าประเภทเบ็ดเตล็ด (M) ตามแนว LDD
# ที่จัดทุ่งหญ้าธรรมชาติ/ไม้ละเมาะ/พื้นที่ลุ่ม/เหมือง ไว้ใน M
DW_TO_LDD = {
    0: 4,  # water              → W พื้นที่น้ำ
    1: 3,  # trees              → F พื้นที่ป่าไม้
    2: 5,  # grass              → M เบ็ดเตล็ด (ทุ่งหญ้า)
    3: 5,  # flooded_vegetation → M เบ็ดเตล็ด (พื้นที่ลุ่ม)
    4: 2,  # crops              → A พื้นที่เกษตรกรรม
    5: 5,  # shrub_and_scrub    → M เบ็ดเตล็ด (ไม้พุ่ม/ไม้ละเมาะ)
    6: 1,  # built              → U ชุมชนและสิ่งปลูกสร้าง
    7: 5,  # bare               → M เบ็ดเตล็ด (ดินโล่ง)
    8: 5,  # snow_and_ice       → M เบ็ดเตล็ด (ไม่มีในไทย — กันครบคลาส)
}

_DW_COLLECTION = 'GOOGLE/DYNAMICWORLD/V1'


def _dw_collection(geom: ee.Geometry, year: int) -> ee.ImageCollection:
    """DW label collection ของปีที่ขอ — filter ที่เดียว กัน drift ระหว่าง lazy/checked"""
    return (ee.ImageCollection(_DW_COLLECTION)
            .filterBounds(geom)
            .filterDate(f'{year}-01-01', f'{year + 1}-01-01')  # end exclusive — รวม 31 ธ.ค.
            .select('label'))


def landuse_image(geom: ee.Geometry, year: int) -> ee.Image:
    """ee.Image band 'landuse' ค่า 1–5 (ประเภทหลัก LDD) — lazy, ไม่มี roundtrip.

    mode() ทั้งปี = คลาสที่พบบ่อยสุดต่อ pixel (ทนเมฆ — DW mask เมฆรายภาพแล้ว
    แนวเดียวกับ dynamic_world_built ใน gee_utils) · pixel ที่ไม่มีภาพทั้งปี = masked
    caller ฝั่ง scoring ควร unmask(0) เอง (0 = ไม่ทราบ) เพื่อไม่ให้จุด sample หลุด
    """
    label = _dw_collection(geom, year).mode()
    keys = sorted(DW_TO_LDD)
    return (label.remap(keys, [DW_TO_LDD[k] for k in keys])
            .rename('landuse').clip(geom))


def landuse_image_checked(geom: ee.Geometry, year: int) -> ee.Image | None:
    """เหมือน landuse_image แต่เช็คก่อนว่ามีภาพ DW ปีนั้นจริง — ไม่มี → None.

    ใช้ใน endpoint (summary/tiles) เพื่อตอบ 404 ที่อ่านรู้เรื่อง แทน error คลุมเครือ
    จาก mode() บน collection ว่าง ('input may not be null') · แลกกับ 1 roundtrip
    """
    if _dw_collection(geom, year).size().getInfo() == 0:
        return None
    return landuse_image(geom, year)


def landuse_meta(year: int) -> dict:
    """metadata แหล่งข้อมูล — แนบทุก response ให้ UI/รายงานบอกที่มาได้เสมอ.

    data_year = year ที่ขอตรงๆ เพราะ DW มีรายปี · provider LDD ในอนาคตจะคืนปีชุด
    ข้อมูลจริงของจังหวัดนั้น (อาจ ≠ ปีที่ขอ) — field นี้คือจุดที่ความต่างจะปรากฏ
    """
    return {"source": "dynamic_world",
            "source_label": "Dynamic World 10m (Google/WRI)",
            "data_year": year}


def build_summary(area_m2_by_value: dict[int, float]) -> dict:
    """แปลงผล grouped reduce ({value: พื้นที่ m²}) → classes 5 แถว + total (pure, test ได้).

    ทุกประเภทปรากฏเสมอ (พื้นที่ 0 ถ้าไม่พบ) → frontend วาดครบ 5 แถวโดยไม่ต้องเดา ·
    share_pct คิดจากพื้นที่รวมของ pixel ที่จำแนกได้ (ค่า 1–5) เท่านั้น
    """
    total_m2 = sum(area_m2_by_value.get(c["value"], 0) for c in LANDUSE_CATEGORIES)
    classes = []
    for cat in LANDUSE_CATEGORIES:
        m2 = area_m2_by_value.get(cat["value"], 0)
        classes.append({
            "code": cat["code"], "name_th": cat["name_th"], "name_en": cat["name_en"],
            "color": cat["color"],
            "area_km2": round(m2 / 1e6, 2),
            "share_pct": round(m2 / total_m2 * 100, 1) if total_m2 else 0,
        })
    return {"total_km2": round(total_m2 / 1e6, 2), "classes": classes}
