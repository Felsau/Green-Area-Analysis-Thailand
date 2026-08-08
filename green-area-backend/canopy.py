"""FR-17 — ตัวชี้วัด "30% tree canopy cover" ต่อจังหวัด/อำเภอ (กฎ 3-30-300 · [R2])

Konijnendijk (2023) เสนอเกณฑ์ 3-30-300 เป็น benchmark ระดับย่าน โดยตัวเลข 30
คือ "ทุกย่านควรมีเรือนยอดไม้ปกคลุมอย่างน้อย 30% ของพื้นที่" — เป็นเกณฑ์แบบผ่าน/ไม่ผ่าน
ไม่มีระดับกลาง จึงรายงานเป็น meets_target + ระยะห่างจากเกณฑ์ (gap) ไม่ตั้งระดับเพิ่มเอง

canopy ≠ green_area_pct ที่มีอยู่เดิม — คนละนิยามและคนละวิธีวัด เก็บแยกกันโดยตั้งใจ:
  green_area_pct  NDVI > 0.3 ของ composite Sentinel-2 = "พืชพรรณทุกชนิด" (รวมนาข้าว
                  สนามหญ้า วัชพืช) ใช้คิดค่า m²/คน ที่เทียบค่าอ้างอิง WHO
  canopy_pct      คลาส "ต้นไม้" จากการจำแนก land cover = เฉพาะ *เรือนยอดไม้ยืนต้น*
                  ตอบเกณฑ์ 30% ของ 3-30-300
ค่าที่ได้จึงต่างกันมากเป็นเรื่องปกติ (อำเภอเกษตรกรรม: green สูง canopy ต่ำ) และการมี
ทั้งสองค่าคู่กันคือสิ่งที่ทำให้อ่านสถานการณ์ออก — ไม่ควรยุบเหลือค่าเดียว

ทำไมตัวเลขหลักเป็น WorldCover ไม่ใช่ Dynamic World
เดิมตั้งใจใช้ DW เป็นตัวเลขหลักเพราะเป็นข้อมูล *รายปี* ขยับตามตัวเลือกปีของทั้งระบบ
แต่วัดจริงเทียบกันแล้ว (2026-07-27, ปี 2024, scale 100 m) พบว่าสองชุดข้อมูลตรงกันใน
พื้นที่ป่า แต่ต่างกันมหาศาลในเมือง:

    พื้นที่              DW (label mode)   WorldCover   ต่างเชิงสัมพัทธ์
    ปทุมวัน                    1.7%          14.6%          88%
    หนองจอก                    9.4%          26.0%          64%
    เมืองเชียงใหม่              4.1%          29.1%          86%
    เขาใหญ่ (ป่า)             98.3%          97.4%           1%

สาเหตุคือ DW band 'label' เป็น argmax ต่อ pixel 10 m — pixel เมืองที่ปนต้นไม้กับอาคาร
ถูกตัดสินเป็น 'built' เสมอ ต้นไม้ริมถนน/สวนหย่อมจึงหายทั้งหมด (ลอง band 'trees'
probability แล้วยังได้ 4.7%/12.1% — ไม่ใช่ปัญหาวิธีรวมพื้นที่ แต่เป็นตัวข้อมูลเอง)
ใช้ DW เป็นตัวเลขหลักจะทำให้ทุกเมืองในไทยรายงาน canopy ~2–5% ซึ่งต่ำจนใช้อ้างอิงไม่ได้
และเป็นกลุ่มพื้นที่ที่เกณฑ์ 30% สนใจที่สุดพอดี

จึงแบ่งบทบาทเป็น:
  หลัก   ESA WorldCover v200 `[R13]` — ระดับ canopy ที่เอาไปเทียบเกณฑ์ 30% · มี epoch
         เดียว (2021) จึงเป็นค่าคงที่ข้ามปี ต้องกำกับปีข้อมูลให้ผู้ใช้เห็นเสมอ
  trend  Dynamic World V1 `[R36]` — วัด *การเปลี่ยนแปลง* เทียบปีฐาน 2021 ด้วยวิธีและ
         เซนเซอร์เดียวกันทั้งสองปี อคติที่ต่ำเกินจริงจึงหักลบกันไปมาก ใช้อ่านทิศทางได้
         แม้ระดับสัมบูรณ์จะเชื่อไม่ได้ · ความต่างระหว่าง 2 ชุดข้อมูลนี้เองคือสิ่งที่
         NFR-08 (validation ±10%) ต้องรายงาน
"""
import ee

# เกณฑ์ 3-30-300
# "30" = เรือนยอดปกคลุม ≥ 30% ของพื้นที่ย่าน · เกณฑ์นี้มาจาก [R2] ตรง ๆ ไม่ได้ตั้งเอง
CANOPY_TARGET_PCT = 30.0

# ชุดข้อมูลหลัก: ESA WorldCover
WORLDCOVER_ASSET = 'ESA/WorldCover/v200'
WORLDCOVER_EPOCH_YEAR = 2021   # v200 = ปี 2021 (v100 = 2020) — ไม่ใช่ข้อมูลรายปี
ESA_TREE_COVER_CLASS = 10      # class 10 = Tree cover
WORLDCOVER_NATIVE_SCALE_M = 10

# ชุดข้อมูล trend: Dynamic World
DW_COLLECTION = 'GOOGLE/DYNAMICWORLD/V1'
DW_TREES_BAND = 'trees'   # ความน่าจะเป็นคลาสต้นไม้ 0–1 (ไม่ใช่ 'label' ที่เป็น argmax)
DW_FIRST_YEAR = 2015      # DW เริ่ม 27 มิ.ย. 2015 → ปี 2015 ครอบคลุมแค่ครึ่งหลัง

# DW ต้องมีข้อมูลครอบคลุมพื้นที่อย่างน้อยเท่านี้ (% ของพื้นที่) จึงรายงาน trend
# ต่ำกว่านี้ = ปีนั้นแทบไม่มีภาพ ค่าที่ได้เป็นตัวแทนพื้นที่ทั้งหมดไม่ได้
DW_MIN_COVERAGE_PCT = 50.0

# ต่ำกว่านี้ถือว่า "ทรงตัว" — เป็นเกณฑ์เพื่อการ *แสดงผล* ไม่ใช่นัยสำคัญทางสถิติ
# (ตั้งไว้กันไม่ให้ noise ระดับ 0.1 จุด% ถูกอ่านเป็นแนวโน้มเพิ่ม/ลด)
TREND_STABLE_PP = 0.5

# เพดาน pixel ละเอียดต่อ 1 cell ผลลัพธ์ของ reduceResolution — ดู _fractional_area
FRACTION_MAX_PIXELS = 4096


def _fractional_area(mask: ee.Image, native_scale_m: int, name: str) -> ee.Image:
    """แปลง mask 0/1 ความละเอียดสูง → พื้นที่จริง (m²/pixel) ที่ *ไม่เพี้ยนตาม scale ที่ reduce*.

    ทำไมต้องมีขั้นนี้: WorldCover เป็นข้อมูล 10 m แต่ reduceRegion ของ NDVI เรียกที่
    scale 100 m (อำเภอ) / 500 m (จังหวัด) — EE จะดึงข้อมูลผ่าน image pyramid ซึ่ง band
    แบบ *คลาส* ใช้ pyramiding policy = MODE · ผลคือแต่ละ pixel 100 m กลายเป็น "คลาสที่
    พบบ่อยสุดใน 10×10 pixel" → เรือนยอดที่กระจัดกระจาย (ไม้ริมถนน สวนหย่อม แนวรั้ว
    ต้นไม้) ที่ไม่ถึงครึ่งของ cell จะหายไปทั้งหมด ทำให้ canopy ของพื้นที่เมืองต่ำกว่า
    จริงอย่างเป็นระบบ — ซึ่งเป็นพื้นที่ที่เกณฑ์ 30% สนใจที่สุด (วัดจริงที่ปทุมวัน:
    14.6% แบบ fractional vs 12.6% แบบอ่านผ่าน pyramid)

    reduceResolution(mean) รวมแบบ "สัดส่วนพื้นที่" จาก pixel ละเอียดขึ้นมาเป็น cell
    หยาบก่อน → ได้ค่า 0–1 = สัดส่วนเรือนยอดจริงใน cell แล้วคูณ pixelArea เป็น m²
    ต้อง reproject ปักกริดที่ native scale ก่อน เพราะ reduceResolution ต้องรู้
    projection ต้นทางที่แน่นอน (ไม่งั้นมันอ่านผ่าน pyramid เหมือนเดิม)

    maxPixels=4096 (64×64) รองรับอัตราส่วนหยาบสุดที่ระบบใช้ 500/10 = 50×50 = 2,500
    ถ้าเกิน (พื้นที่ใหญ่มาก) bestEffort จะถอยไปใช้ข้อมูลหยาบลงแทนที่จะ error —
    ค่าเพี้ยนขึ้นบ้างแต่ระบบไม่ล้ม

    หมายเหตุ: band ของ DW ที่ใช้เป็น *ความน่าจะเป็น* (pyramid policy = MEAN) อ่านที่
    scale หยาบได้ค่าเฉลี่ยที่ถูกต้องอยู่แล้ว จึงไม่ต้องผ่านฟังก์ชันนี้
    """
    frac = (mask.reproject(ee.Projection('EPSG:4326').atScale(native_scale_m))
            .reduceResolution(reducer=ee.Reducer.mean(), bestEffort=True,
                              maxPixels=FRACTION_MAX_PIXELS))
    return frac.multiply(ee.Image.pixelArea()).rename(name)


def _dw_trees_prob(geom: ee.Geometry, year: int) -> ee.Image:
    """ความน่าจะเป็นคลาสต้นไม้เฉลี่ยทั้งปี (0–1) — ยังไม่ unmask (ผู้เรียกใช้ mask ต่อ).

    ใช้ band 'trees' (probability) ไม่ใช่ 'label' (argmax) แนวเดียวกับที่
    `gee_utils.dynamic_world_built` ใช้ band 'built' เป็น ISA proxy — ค่าต่อเนื่องจับ
    การเปลี่ยนแปลงระหว่างปีได้ไวกว่าการนับ pixel ที่ชนะ argmax

    placeholder band: ปีก่อน DW_FIRST_YEAR หรือปีอนาคตที่ยังไม่มีภาพ → collection ว่าง
    → mean() คืน image *ไม่มี band* แล้ว operation ถัดไปพังทั้ง reduceRegion ซึ่งจะลาก
    NDVI ที่คำนวณอยู่ก้อนเดียวกันล้มไปด้วย · เติม band ค่าคงที่ที่ selfMask() ไว้ (=
    masked ทุก pixel) เมื่อยังไม่มี → รอดถึง reduceRegion โดยมี coverage = 0
    (pattern เดียวกับ _compute_ndvi_monthly)
    """
    return (ee.ImageCollection(DW_COLLECTION)
            .filterBounds(geom)
            .filterDate(f'{year}-01-01', f'{year + 1}-01-01')  # end exclusive — รวม 31 ธ.ค.
            .select(DW_TREES_BAND)
            .mean()
            .addBands(ee.Image.constant(0).rename(DW_TREES_BAND).selfMask(),
                      overwrite=False)
            .select(DW_TREES_BAND))


def canopy_area_bands(geom: ee.Geometry, year: int) -> ee.Image:
    """band พื้นที่ (m²/pixel) ไว้ addBands เข้า reduceRegion เดิมของ NDVI — ไม่เพิ่ม round-trip.

    'canopy_area'    เรือนยอดจาก ESA WorldCover v200 (2021) → ตัวเลขหลักของ FR-17
    'dw_area'        DW trees prob ปี `year`                → ตัวตั้งของ trend
    'dw_valid_area'  พื้นที่ที่ DW มีภาพในปีนั้น            → กันรายงาน trend จากภาพไม่กี่ภาพ
    'dw_base_area'   DW trees prob ปีฐาน WORLDCOVER_EPOCH_YEAR → ตัวหักลบของ trend

    ปีที่ขอ = ปีฐานพอดี ไม่ต้องคำนวณซ้ำ (change = 0 อยู่แล้ว) — ประหยัด composite ทั้งก้อน
    """
    wc_trees = (ee.ImageCollection(WORLDCOVER_ASSET).first()
                .eq(ESA_TREE_COVER_CLASS).unmask(0))
    pixel_area = ee.Image.pixelArea()

    dw = _dw_trees_prob(geom, year)
    # unmask(0): pixel ที่ปีนั้นไม่มีภาพต้องนับเป็น "ไม่มีต้นไม้" ไม่ใช่หลุดออกจากผลรวม
    # (ไม่งั้นสัดส่วนพองขึ้นตามพื้นที่ที่หายไป) — แล้วชดเชยด้วย dw_valid_area ที่บอกว่า
    # ปีนั้นมีภาพครอบคลุมแค่ไหน จึงแยก "0% จริง" ออกจาก "ไม่มีข้อมูล" ได้
    bands = (_fractional_area(wc_trees, WORLDCOVER_NATIVE_SCALE_M, 'canopy_area')
             .addBands(dw.unmask(0).multiply(pixel_area).rename('dw_area'))
             .addBands(dw.mask().multiply(pixel_area).rename('dw_valid_area')))

    base = (dw if year == WORLDCOVER_EPOCH_YEAR
            else _dw_trees_prob(geom, WORLDCOVER_EPOCH_YEAR))
    return bands.addBands(base.unmask(0).multiply(pixel_area).rename('dw_base_area')).clip(geom)


def _build_trend(dw_m2, dw_valid_m2, dw_base_m2, total_area_m2: float, year: int) -> dict | None:
    """แนวโน้มเรือนยอดจาก DW เทียบปีฐาน — None เมื่อปีนั้นไม่มีข้อมูลพอ.

    รายงานเป็น "เปลี่ยนไปกี่จุด%" เท่านั้น ไม่เอาไปบวกกับค่าหลักของ WorldCover เพราะ
    สองชุดข้อมูลวัดคนละนิยาม การบวกข้ามชุดจะสร้างตัวเลขที่ไม่มีแหล่งอ้างอิงรองรับ
    """
    if dw_m2 is None or dw_base_m2 is None or not total_area_m2:
        return None
    coverage_pct = round(((dw_valid_m2 or 0) / total_area_m2) * 100, 1)
    if coverage_pct < DW_MIN_COVERAGE_PCT:
        return None

    pct = round((dw_m2 / total_area_m2) * 100, 1)
    base_pct = round((dw_base_m2 / total_area_m2) * 100, 1)
    change_pp = round(pct - base_pct, 1)
    direction = ("stable" if abs(change_pp) < TREND_STABLE_PP
                 else "increase" if change_pp > 0 else "decrease")
    word = {"stable": "ทรงตัว", "increase": "เพิ่มขึ้น", "decrease": "ลดลง"}[direction]

    note = (f"Dynamic World วัดเรือนยอดปี {year} ได้ {pct:.1f}% เทียบปีฐาน "
            f"{WORLDCOVER_EPOCH_YEAR} ที่ {base_pct:.1f}% → {word}")
    if direction != "stable":
        note += f" {abs(change_pp):.1f} จุด%"
    if coverage_pct < 99:
        note += f" · ปีนั้นมีภาพครอบคลุม {coverage_pct:.0f}% ของพื้นที่"
    note += (" · ตัวเลขของ DW ต่ำกว่าความจริงในพื้นที่เมือง (pixel ที่ปนอาคารถูกจำแนก"
             "เป็นสิ่งปลูกสร้าง) จึงใช้อ่านเฉพาะ *ทิศทางการเปลี่ยนแปลง* ไม่ใช่ระดับ")

    return {
        "source": "Dynamic World V1",
        "year": year,
        "baseline_year": WORLDCOVER_EPOCH_YEAR,
        "canopy_pct": pct,
        "baseline_pct": base_pct,
        "change_pp": change_pp,
        "direction": direction,
        "coverage_pct": coverage_pct,
        "note": note,
    }


def build_canopy(canopy_wc_m2, dw_m2, dw_valid_m2, dw_base_m2,
                 total_area_m2, year: int) -> dict:
    """รวมตัวชี้วัดเรือนยอดเป็น dict เดียว — เก็บลง cache (jsonb) และส่งกลับ client ตรง.

    รับพื้นที่เป็น m² ดิบจาก reduceRegion (None ได้ = ไม่มีข้อมูล) ไม่แตะ GEE เอง
    จึงเป็น pure function ที่ test ได้ตรงเหมือน build_data_quality ของ NFR-07
    """
    if canopy_wc_m2 is None or not total_area_m2:
        return {"available": False, "canopy_pct": None, "canopy_km2": None,
                "target_pct": CANOPY_TARGET_PCT, "meets_target": None, "gap_pct": None,
                "source": "ESA WorldCover v200", "epoch_year": WORLDCOVER_EPOCH_YEAR,
                "epoch_offset_years": abs(year - WORLDCOVER_EPOCH_YEAR),
                "trend": None, "label": "ไม่มีข้อมูลเรือนยอด",
                "note": "ไม่มีข้อมูล ESA WorldCover ครอบคลุมพื้นที่นี้"}

    canopy_pct = round((canopy_wc_m2 / total_area_m2) * 100, 1)
    meets = canopy_pct >= CANOPY_TARGET_PCT
    # gap = ยังขาดอีกกี่จุด% ถึงเกณฑ์ (0 เมื่อผ่านแล้ว — ไม่รายงานค่าติดลบให้สับสนกับ
    # "เกินเกณฑ์เท่าไหร่" ซึ่งไม่ใช่สิ่งที่เกณฑ์ผ่าน/ไม่ผ่านต้องการ)
    gap_pct = 0.0 if meets else round(CANOPY_TARGET_PCT - canopy_pct, 1)
    trend = _build_trend(dw_m2, dw_valid_m2, dw_base_m2, total_area_m2, year)

    label = (f"ผ่านเกณฑ์ 30% ✅ ({canopy_pct:.1f}%)" if meets
             else f"ต่ำกว่าเกณฑ์ 30% ⚠️ ({canopy_pct:.1f}% — ขาดอีก {gap_pct:.1f} จุด%)")

    parts = [f"เรือนยอดไม้ปกคลุม {canopy_pct:.1f}% ของพื้นที่ "
             f"(ESA WorldCover v200 ข้อมูลปี {WORLDCOVER_EPOCH_YEAR})"]
    # ผู้ใช้เลือกปีจากตัวเลือกเดียวกับ NDVI/LST — ต้องบอกให้ชัดว่าค่านี้ไม่ได้ขยับตามปี
    if year != WORLDCOVER_EPOCH_YEAR:
        parts.append(f"เป็นข้อมูล epoch เดียว ไม่ใช่รายปี — ปีที่เลือก ({year}) "
                     f"ห่างจากปีข้อมูล {abs(year - WORLDCOVER_EPOCH_YEAR)} ปี")
    if trend:
        parts.append(trend["note"])
    parts.append("เกณฑ์ 30% ตามกฎ 3-30-300 (Konijnendijk 2023)")

    return {
        "available": True,
        "canopy_pct": canopy_pct,
        "canopy_km2": round(canopy_wc_m2 / 1_000_000, 2),
        "target_pct": CANOPY_TARGET_PCT,
        "meets_target": meets,
        "gap_pct": gap_pct,
        "source": "ESA WorldCover v200",
        "epoch_year": WORLDCOVER_EPOCH_YEAR,
        "epoch_offset_years": abs(year - WORLDCOVER_EPOCH_YEAR),
        "trend": trend,
        "label": label,
        "note": " · ".join(parts),
    }
