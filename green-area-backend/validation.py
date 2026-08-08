"""NFR-08 — ตรวจสอบความถูกต้อง (validation) ของ green_area_pct เทียบ ESA WorldCover.

green_area_pct (ดู routers/ndvi/compute.py) มาจาก NDVI > 0.3 ของ composite
Sentinel-2 = "พืชพรรณทุกชนิด" (นาข้าว สนามหญ้า วัชพืช รวมด้วย — คนละนิยามกับ
canopy_pct ของ FR-17 ที่นับเฉพาะเรือนยอดไม้ยืนต้น ดู docstring canopy.py) NFR-08
ต้องการเทียบตัวเลขนี้กับ ESA WorldCover ซึ่งจำแนกด้วยวิธีอื่น (land-cover
classification ไม่ใช่ vegetation-index threshold) แล้วรายงานค่าความคลาดเคลื่อน
เทียบเป้าหมาย ±10 จุด% ที่ระบุใน REQUIREMENTS.md NFR-08

นิยาม "green" ฝั่ง WorldCover ที่เทียบเคียงกับ green_area_pct
green_area_pct นับพืชพรรณทุกชนิด ไม่ใช่แค่ป่า จึงรวมทุกคลาส WorldCover ที่เป็น
พืชพรรณ:
  10 Tree cover · 20 Shrubland · 30 Grassland · 40 Cropland ·
  90 Herbaceous wetland (มีพืชขึ้นปกคลุม) · 95 Mangroves (เรือนยอดหนาแน่น NDVI สูง
  แม้พื้นที่จะเป็นน้ำขึ้นน้ำลง)
ไม่รวม: 50 Built-up · 60 Bare/sparse (นิยามคือ <10% พืชพรรณปกคลุม — ตรงข้ามกับ
"green") · 70 Snow/ice (ไม่มีในไทย) · 80 Permanent water · 100 Moss/lichen
(พืชไม่มีท่อลำเลียง ชีวมวลต่ำ แทบไม่มีในไทย)

ทำไมต้องใช้ fractional area แบบเดียวกับ canopy.py
WorldCover เป็น band แบบคลาส (pyramiding policy = MODE) — ถ้าอ่านผ่าน pyramid
ตรงๆ ที่ scale หยาบ (100/500 ม.) พืชพรรณกระจัดกระจายในเมือง (ต้นไม้ริมถนน แปลง
เกษตรแทรกตัวเมือง) จะหายไปเป็นระบบเหมือนที่ FR-17 เจอกับเรือนยอด — ทำให้ความ
คลาดเคลื่อนที่วัดได้พองเกินจริงจาก artifact ของ scale ไม่ใช่ของข้อมูลจริง จึงต้อง
ใช้ `canopy._fractional_area` เทคนิคเดียวกัน (reduceResolution ที่ native 10 ม.
ก่อนย่อ) — ดู docstring ของฟังก์ชันนั้นสำหรับรายละเอียด
"""
import ee

from canopy import (WORLDCOVER_ASSET, WORLDCOVER_EPOCH_YEAR,
                    WORLDCOVER_NATIVE_SCALE_M, _fractional_area)

WORLDCOVER_GREEN_CLASSES = (10, 20, 30, 40, 90, 95)
WORLDCOVER_NONGREEN_CLASSES = (50, 60, 70, 80, 100)

WORLDCOVER_CLASS_NAMES = {
    10: "ไม้ยืนต้น (Tree cover)",
    20: "ไม้พุ่ม (Shrubland)",
    30: "ทุ่งหญ้า (Grassland)",
    40: "พื้นที่เกษตร (Cropland)",
    50: "สิ่งปลูกสร้าง (Built-up)",
    60: "พื้นที่โล่ง/พืชเบาบาง (Bare/sparse)",
    70: "หิมะ/น้ำแข็ง (Snow and ice)",
    80: "แหล่งน้ำถาวร (Permanent water)",
    90: "พื้นที่ชุ่มน้ำไม้ล้มลุก (Herbaceous wetland)",
    95: "ป่าชายเลน (Mangroves)",
    100: "มอสส์/ไลเคน (Moss and lichen)",
}

# เป้าหมายความคลาดเคลื่อนของ NFR-08 (REQUIREMENTS.md §4.2) — ±10 จุด%
VALIDATION_TARGET_PP = 10.0

# แยกสาเหตุความคลาดเคลื่อนรายคลาส
# ตัวเลขรวม ("ต่างกัน 15 จุด%") ตอบไม่ได้ว่าต่างเพราะอะไร — ซึ่งเป็นคำถามแรกที่
# ตามมาเสมอ จึงแยกความไม่ตรงกันออกเป็นสองทิศทาง แล้วระบุว่าแต่ละคลาสของ
# WorldCover มีส่วนเท่าไร:
#
#   false negative (fn)  WorldCover ว่า "เขียว" แต่ NDVI ว่า "ไม่เขียว"
#                        คาดว่าเด่นที่ Cropland — WorldCover จำแนกนาข้าวเป็นพื้นที่
#                        เกษตรตลอดทั้งปี ส่วน NDVI median รายปีของนาที่มีช่วงพักดิน/
#                        น้ำท่วมขังจะตกต่ำกว่า 0.3
#   false positive (fp)  WorldCover ว่า "ไม่เขียว" แต่ NDVI ว่า "เขียว"
#                        คาดว่าเด่นที่ Built-up — NDVI จับหญ้า/ต้นไม้แทรกตัวเมืองได้
#                        ส่วน WorldCover ตัดสินทั้ง pixel เป็นสิ่งปลูกสร้าง
#
# นิยามนี้ทำให้ผลรวมกระทบยอดกับค่าความคลาดเคลื่อนรวมพอดี:
#     error_pp = (Σ fp − Σ fn) / total_area × 100
# จึงไม่ใช่การประมาณคนละชุด แต่เป็นการ *กระจาย* ตัวเลขเดิมออกตามที่มาจริง
BREAKDOWN_MIN_PP = 0.1   # ต่ำกว่านี้ไม่ต้องลงรายการ (noise ระดับปัดเศษ)


# ข้อจำกัดสำคัญ: reproject 10 ม. ใช้กับ mask ที่พึ่ง S2 ไม่ได้
# `_fractional_area` ต้อง `reproject` ไปกริด 10 ม. ก่อน — ทำได้กับ mask ที่มาจาก
# WorldCover ล้วน (canopy.py ใช้แบบนั้น) แต่ ใช้กับ mask ที่พึ่ง green_mask ไม่ได้
# เพราะ green_mask มาจาก median composite ของ Sentinel-2 การ reproject จึงบังคับให้
# GEE คำนวณ composite ทั้งจังหวัดที่ 10 ม. ในคราวเดียว → 'User memory limit exceeded'
# ทุกจังหวัด แม้ band เดียวและ tileScale=16 (วัดจริง 2026-07-28 ที่อำนาจเจริญ)
#
# จึงแบ่งการวัดเป็นสองโดเมนที่ *แต่ละโดเมนสอดคล้องกันภายในตัวเอง*:
#   fractional (10 ม.)  ใช้กับฝั่ง WorldCover ล้วน = ค่าอ้างอิงที่แม่นที่สุด →
#                       เป็นตัวตั้งของ error_pp ที่เอาไปเทียบเกณฑ์ ±10 จุด%
#   plain (scale วิเคราะห์) ใช้กับพจน์ที่ตัดกับ green_mask (fn/fp รายคลาส) →
#                       วัดด้วยวิธีเดียวกับที่ระบบคิด green_area_pct พอดี จึง
#                       กระทบยอดกันเป๊ะ ในโดเมนนี้ (วัดจริง: net −14.9 = error −14.9)
# ส่วนต่างระหว่างสองโดเมน (`reference_scale_delta_pp`) รายงานไว้ให้ตรวจสอบย้อนได้:
#     error_pp = net_pp + reference_scale_delta_pp
VALIDATION_TILE_SCALE = 8


def _worldcover_green_mask(wc: ee.Image) -> ee.Image:
    green = ee.Image.constant(0)
    for code in WORLDCOVER_GREEN_CLASSES:
        green = green.Or(wc.eq(code))
    return green


def worldcover_reference_sums(geom: ee.Geometry, scale: int) -> dict:
    """โดเมน 1 — พื้นที่สีเขียวตาม WorldCover แบบ fractional (m²) = ค่าอ้างอิงที่แม่นที่สุด.

    ไม่ขึ้นกับปีและไม่ขึ้นกับ Sentinel-2 (WorldCover เป็น epoch เดียว) → คำนวณ
    ครั้งเดียวต่อจังหวัดแล้วเก็บลง `provinces.worldcover_green_pct` ใช้ซ้ำได้ทุกปี ·
    เป็นก้อนที่แพงที่สุด (วัดจริง ~17.5 วิ/จังหวัด) การดึงออกจาก request path จึงสำคัญ
    ต่อ NFR-01 (cache miss ≤ 60 วิ) — ดู `backfill_worldcover_reference.py`
    """
    wc = ee.ImageCollection(WORLDCOVER_ASSET).first()
    return _fractional_area(_worldcover_green_mask(wc), WORLDCOVER_NATIVE_SCALE_M,
                            'worldcover_green_area').reduceRegion(
        reducer=ee.Reducer.sum(), geometry=geom, scale=scale,
        maxPixels=1e10, bestEffort=True, tileScale=VALIDATION_TILE_SCALE).getInfo()


def disagreement_sums(green_mask: ee.Image, geom: ee.Geometry, scale: int) -> dict:
    """โดเมน 2 — พจน์ที่ตัดกับ green_mask (m²): fn/fp รายคลาส + WorldCover แบบ plain.

    เสียบเป็น `extra_sums_fn` ของ `_compute_ndvi_annual` เพื่อใช้ green_mask ตัวเดียว
    กับที่ระบบใช้จริง · ถูกพอจะคิดสดทุก cache miss (วัดจริง ~2.8 วิ/จังหวัด)

    green_mask อาจ masked ในพื้นที่ที่ไม่มีภาพ S2 → unmask(0) ให้เป็น "ไม่เขียว"
    ตรงกับวิธีที่ green_area คิด (updateMask ตัด pixel นั้นออกจากผลรวม = ไม่ถูกนับ
    เป็นสีเขียว) ไม่งั้นพื้นที่ไร้ภาพจะหายจากทั้งสองฝั่งแล้วยอดไม่กระทบกัน
    """
    wc = ee.ImageCollection(WORLDCOVER_ASSET).first()
    green = green_mask.unmask(0)
    pixel_area = ee.Image.pixelArea()

    stack = pixel_area.updateMask(_worldcover_green_mask(wc)).rename(
        'worldcover_green_area_plain')
    for code in WORLDCOVER_GREEN_CLASSES:
        # WorldCover ว่าเขียว แต่ NDVI ว่าไม่เขียว
        stack = stack.addBands(
            pixel_area.updateMask(wc.eq(code).And(green.Not())).rename(f'fn_{code}'))
    for code in WORLDCOVER_NONGREEN_CLASSES:
        # WorldCover ว่าไม่เขียว แต่ NDVI ว่าเขียว
        stack = stack.addBands(
            pixel_area.updateMask(wc.eq(code).And(green)).rename(f'fp_{code}'))
    return stack.reduceRegion(
        reducer=ee.Reducer.sum(), geometry=geom, scale=scale,
        maxPixels=1e10, bestEffort=True, tileScale=VALIDATION_TILE_SCALE).getInfo()


def validation_area_sums(green_mask: ee.Image, geom: ee.Geometry, scale: int) -> dict:
    """ทั้งสองโดเมนรวมกัน — ใช้โดย `validate_green_area.py` ที่คิดสดทุกอย่าง
    (ไม่พึ่งค่าที่ backfill ไว้ จึงเป็นการตรวจแบบ end-to-end ที่เป็นอิสระ)"""
    return {**worldcover_reference_sums(geom, scale),
            **disagreement_sums(green_mask, geom, scale)}


def build_breakdown(extra_area_sums: dict, total_area_m2: float,
                    worldcover_green_pct: float | None = None) -> dict | None:
    """กระจายความคลาดเคลื่อนรวมออกตามคลาส WorldCover ที่เป็นต้นเหตุ.

    Pure function — รับผลรวมดิบ (m²) จาก reduceRegion ที่ใส่ band ของ
    validation_area_bands ไว้ · คืน None ถ้าข้อมูลไม่พอ
    """
    if not extra_area_sums or not total_area_m2:
        return None

    def pp(key):
        """m² → จุด% ของพื้นที่ทั้งหมด"""
        return (extra_area_sums.get(key) or 0) / total_area_m2 * 100

    by_class = []
    fn_total = fp_total = 0.0
    for code in WORLDCOVER_GREEN_CLASSES:
        value = pp(f'fn_{code}')
        fn_total += value
        if value >= BREAKDOWN_MIN_PP:
            by_class.append({"code": code, "name": WORLDCOVER_CLASS_NAMES[code],
                             "kind": "false_negative", "pp": round(value, 1)})
    for code in WORLDCOVER_NONGREEN_CLASSES:
        value = pp(f'fp_{code}')
        fp_total += value
        if value >= BREAKDOWN_MIN_PP:
            by_class.append({"code": code, "name": WORLDCOVER_CLASS_NAMES[code],
                             "kind": "false_positive", "pp": round(value, 1)})

    by_class.sort(key=lambda c: c["pp"], reverse=True)

    # ส่วนต่างของค่าอ้างอิง WorldCover ระหว่างสองโดเมน (ดูบล็อกอธิบายด้านบน) —
    # ทำให้ error_pp กระทบยอดกับ net_pp ได้ครบ ตรวจย้อนได้ทุกตัวเลข
    # ค่า fractional มาได้ 2 ทาง: คิดสดในก้อนเดียวกัน (สคริปต์ validation) หรือส่ง
    # เป็น pct ที่ backfill ไว้แล้ว (request path — ดู worldcover_reference_sums)
    wc_frac_m2 = extra_area_sums.get('worldcover_green_area')
    wc_frac_pct = (worldcover_green_pct if wc_frac_m2 is None
                   else wc_frac_m2 / total_area_m2 * 100)
    wc_plain = extra_area_sums.get('worldcover_green_area_plain')
    delta_pp = (None if wc_frac_pct is None or wc_plain is None
                else round(wc_plain / total_area_m2 * 100 - wc_frac_pct, 1))

    return {
        "false_negative_pp": round(fn_total, 1),
        "false_positive_pp": round(fp_total, 1),
        "net_pp": round(fp_total - fn_total, 1),
        "reference_scale_delta_pp": delta_pp,
        "by_class": by_class,
        "dominant": by_class[0] if by_class else None,
    }


def worldcover_green_area_band(geom: ee.Geometry) -> ee.Image:
    """band พื้นที่ (m²/pixel) ของ "WorldCover-green" — ไว้ addBands เข้า reduceRegion.

    รวม mask ของทุกคลาสใน WORLDCOVER_GREEN_CLASSES ด้วย Or() แล้วแปลงเป็นพื้นที่
    จริงผ่าน fractional-area (กัน bias ของ pyramid MODE ที่ scale หยาบ — ดู
    docstring บนสุดของไฟล์นี้)
    """
    wc = ee.ImageCollection(WORLDCOVER_ASSET).first().clip(geom)
    green = ee.Image.constant(0)
    for code in WORLDCOVER_GREEN_CLASSES:
        green = green.Or(wc.eq(code))
    return _fractional_area(green, WORLDCOVER_NATIVE_SCALE_M, 'worldcover_green_area')


def build_validation(ndvi_green_pct: float | None, worldcover_green_pct: float | None,
                     year: int, breakdown: dict | None = None) -> dict:
    """เทียบ green_area_pct (NDVI) กับ WorldCover-green — คืน dict สรุปผลเดียว.

    Pure function (ไม่แตะ GEE) — test ได้ตรงเหมือน build_canopy/build_data_quality
    รับเป็น % ทั้งสองฝั่ง (None ได้ = ไม่มีข้อมูล)

    error_pp > 0  → NDVI ประเมินสูงกว่า WorldCover · วัดจริงทั้ง 77 จังหวัดพบว่า
                    เครื่องหมายบอกกลไกได้ตรง ๆ (ดู REQUIREMENTS.md §5.1):
                      บวก = เขตเมือง NDVI จับพืชแทรกอาคารที่ WorldCover ตัดสินทั้ง
                            pixel เป็นสิ่งปลูกสร้าง
                      ลบ  = เขตนาข้าว WorldCover นับ Cropland ตลอดปี แต่ median NDVI
                            รายปีตกต่ำกว่า 0.3 ช่วงพักดิน/น้ำท่วมขัง
                    ทั้งสองเป็นความต่างเชิง *นิยาม* ไม่ใช่ความผิดพลาดของการวัด
    """
    if ndvi_green_pct is None or worldcover_green_pct is None:
        return {"available": False, "ndvi_green_pct": None, "worldcover_green_pct": None,
                "error_pp": None, "target_pp": VALIDATION_TARGET_PP,
                "within_target": None, "year": year,
                "worldcover_epoch_year": WORLDCOVER_EPOCH_YEAR, "breakdown": None,
                "note": "ข้อมูลไม่พอสำหรับเปรียบเทียบ (ขาด green_area_pct หรือ WorldCover)"}

    wc_pct = round(worldcover_green_pct, 1)
    error_pp = round(ndvi_green_pct - wc_pct, 1)
    within_target = abs(error_pp) <= VALIDATION_TARGET_PP
    direction = "สูงกว่า" if error_pp > 0 else "ต่ำกว่า" if error_pp < 0 else "เท่ากับ"

    note = (f"NDVI (green_area_pct {ndvi_green_pct:.1f}%) {direction} "
            f"ESA WorldCover ({wc_pct:.1f}%) อยู่ {abs(error_pp):.1f} จุด% "
            f"— เป้าหมาย NFR-08 คือ ±{VALIDATION_TARGET_PP:.0f} จุด% "
            f"({'ผ่าน' if within_target else 'ไม่ผ่าน'})")
    if year != WORLDCOVER_EPOCH_YEAR:
        note += (f" · WorldCover เป็นข้อมูล epoch เดียว (ปี {WORLDCOVER_EPOCH_YEAR}) "
                 f"ส่วน NDVI คำนวณปี {year} — ส่วนต่างบางส่วนอาจมาจากการเปลี่ยนแปลง"
                 "พื้นที่ระหว่างปี ไม่ใช่ความคลาดเคลื่อนของวิธีวัดล้วนๆ")
    if breakdown and breakdown.get("dominant"):
        top = breakdown["dominant"]
        side = ("WorldCover นับเป็นสีเขียวแต่ NDVI ไม่นับ"
                if top["kind"] == "false_negative"
                else "NDVI นับเป็นสีเขียวแต่ WorldCover ไม่นับ")
        note += (f" · ต้นเหตุหลักคือคลาส {top['name']} {top['pp']:.1f} จุด% "
                 f"({side})")

    return {
        "available": True,
        "ndvi_green_pct": ndvi_green_pct,
        "worldcover_green_pct": wc_pct,
        "error_pp": error_pp,
        "target_pp": VALIDATION_TARGET_PP,
        "within_target": within_target,
        "year": year,
        "worldcover_epoch_year": WORLDCOVER_EPOCH_YEAR,
        "breakdown": breakdown,
        "note": note,
    }
