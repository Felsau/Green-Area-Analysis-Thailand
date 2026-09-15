import ee

# Sentinel-2 cloud masking — Cloud Score+
# เลิกใช้ QA60 (bitmask เมฆ) เพราะ ESA หยุดเติมข้อมูล band นี้ช่วง ม.ค.2022–ก.พ.2024
# ใน S2_SR_HARMONIZED → mask กลายเป็น no-op (เมฆปนเข้า NDVI median ทำให้ค่าต่ำ/เพี้ยน)
# Cloud Score+ เป็น dataset แยกที่ Google คำนวณให้ทั้ง S2 archive (เชื่อถือได้ทุกปี)
# band 'cs' = คะแนนความใส 0–1 · cs >= threshold = pixel ใส (Google แนะนำ 0.5–0.65)
_CS_PLUS_ID = 'GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED'
_CS_BAND = 'cs'
_CS_CLEAR_THRESHOLD = 0.6


def _mask_s2_csplus(image):
    """Mask เมฆ 1 ภาพด้วย band Cloud Score+ ที่ link มาแล้ว + scale reflectance 0–1"""
    cs = image.select(_CS_BAND)
    return (image.updateMask(cs.gte(_CS_CLEAR_THRESHOLD))
                 .divide(10000)
                 .copyProperties(image, ['system:time_start']))


def clean_s2_collection(s2_col):
    """รับ S2_SR_HARMONIZED collection (filter พื้นที่/วันที่/cloud% แล้ว) → link
    Cloud Score+, mask เมฆรายภาพ, แล้ว scale เป็น reflectance 0–1.

    ใช้แทน `.map(mask_s2_clouds)` เดิม (QA60) — เรียกครอบ collection ที่ build เสร็จ:
        col = clean_s2_collection(ee.ImageCollection(...).filterBounds(geom)...)
    """
    return (s2_col.linkCollection(ee.ImageCollection(_CS_PLUS_ID), [_CS_BAND])
                  .map(_mask_s2_csplus))


# Landsat Collection 2 Level-2 QA_PIXEL — bit ที่หมายถึง "pixel นี้ไม่ใส"
#   1 Dilated Cloud (ขอบเมฆที่ขยายออกจากก้อนหลัก) · 2 Cirrus (เมฆชั้นสูงบาง)
#   3 Cloud · 4 Cloud Shadow
# เดิม mask แค่ bit 3/4 — ขอบเมฆกับเมฆบางจึงรั่วเข้า median ของ LST ทำให้ค่าเอนต่ำ
# (เมฆเย็นกว่าผิวดิน) · ฝั่ง Sentinel-2 ยกระดับไป Cloud Score+ แล้ว (ดู _mask_s2_csplus)
# ฝั่ง Landsat ยังไม่มี dataset เทียบเท่า จึงใช้ QA bit ให้ครบชุดแทน
_LANDSAT_CLOUD_BITS = (1, 2, 3, 4)
_LANDSAT_CLOUD_BITMASK = sum(1 << b for b in _LANDSAT_CLOUD_BITS)


# เกณฑ์เมฆระดับ "ทั้งภาพ" ของ Sentinel-2 — ใช้ร่วมกันทั้งระบบ
# Cloud Score+ mask เมฆ *รายพิกเซล* ให้อยู่แล้ว (_mask_s2_csplus) เกณฑ์นี้เป็นตัวกรอง
# อีกชั้นระดับภาพ: ภาพที่เมฆคลุมเกือบทั้งภาพเหลือพิกเซลใสน้อยจนไม่คุ้มดึงเข้า median
#
# เดิมค่านี้ต่างกันตามจุดที่เรียก — 20% เฉพาะ NDVI รายปี แต่ 80% ที่ทุกที่อื่น
# (ndvi_deficit ของคะแนนความสำคัญ, urban subset, tiles, thumbs, กราฟรายเดือน) →
# ค่า NDVI ที่หน้าเว็บแสดง กับค่าที่ระบบใช้ตัดสินว่า "ขาดต้นไม้" มาจาก composite
# คนละชุด · รวมมาไว้ที่เดียวเพื่อไม่ให้ drift อีก (ดู s2_clean_collection)
S2_CLOUD_FILTER_PCT = 20           # เกณฑ์หลัก — รับเฉพาะภาพที่เมฆทั้งภาพ < 20%
S2_CLOUD_FILTER_FALLBACK_PCT = 80  # เกณฑ์สำรอง เมื่อช่วงนั้นไม่มีภาพผ่านเกณฑ์หลักเลย


def _s2_scenes(geom, year: int, cloud_pct: int, month=None):
    """S2_SR_HARMONIZED ที่ filter พื้นที่/ช่วงเวลา/เกณฑ์เมฆแล้ว (ยังไม่ mask เมฆ).

    month=None → ทั้งปี · month เป็นเลขเดือนหรือ ee.Number ได้ (ใช้ใน server-side map
    ของกราฟรายเดือน) จึง filter ด้วย calendarRange แทน filterDate ในเคสนั้น
    """
    col = (ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
           .filterBounds(geom)
           .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', cloud_pct)))
    if month is None:
        # end exclusive — รวม 31 ธ.ค.
        return col.filterDate(f'{year}-01-01', f'{year + 1}-01-01')
    return (col.filter(ee.Filter.calendarRange(year, year, 'year'))
               .filter(ee.Filter.calendarRange(month, month, 'month')))


def s2_clean_collection(geom, year: int, month=None):
    """S2 ที่ mask เมฆแล้ว ด้วยเกณฑ์เมฆมาตรฐานของระบบ — คืน (collection, cloud_pct ที่ใช้จริง).

    ถอยไปเกณฑ์สำรองอัตโนมัติเมื่อเกณฑ์หลักไม่เหลือภาพเลยในช่วงนั้น · ตัดสินฝั่ง
    server ด้วย ee.Algorithms.If จึง **ไม่เพิ่ม round-trip** (เดิมฝั่ง NDVI รายปีต้อง
    getInfo รอบแรกเพื่อดูว่าว่างไหม แล้วค่อยยิงรอบสองด้วยเกณฑ์ผ่อน)

    cloud_pct ที่คืนเป็น ee.Number — ผู้เรียกที่ต้องรายงานค่านี้ (data_quality ของ
    NFR-07) ค่อยดึงรวมไปกับ getInfo ก้อนอื่นที่ต้องยิงอยู่แล้ว
    """
    strict = _s2_scenes(geom, year, S2_CLOUD_FILTER_PCT, month)
    use_strict = strict.size().gt(0)
    col = ee.ImageCollection(ee.Algorithms.If(
        use_strict, strict,
        _s2_scenes(geom, year, S2_CLOUD_FILTER_FALLBACK_PCT, month)))
    used_pct = ee.Number(ee.Algorithms.If(
        use_strict, S2_CLOUD_FILTER_PCT, S2_CLOUD_FILTER_FALLBACK_PCT))
    return clean_s2_collection(col), used_pct


def s2_scene_count(geom, year: int):
    """จำนวนภาพ S2 ที่ผ่านเกณฑ์ *สำรอง* — ใช้ตอบว่า "ปีนี้มีภาพให้ใช้ไหม" ในชั้น guard.

    ต้องนับที่เกณฑ์ผ่อน เพราะ s2_clean_collection ถอยมาใช้เกณฑ์นี้เองอยู่แล้ว —
    ถ้า guard นับที่เกณฑ์เข้มจะปฏิเสธปีที่ compute จริงยังทำงานได้ (guard คลาดกับ compute)
    """
    return _s2_scenes(geom, year, S2_CLOUD_FILTER_FALLBACK_PCT).size()


def _mask_landsat_clouds(image):
    qa = image.select('QA_PIXEL')
    return image.updateMask(qa.bitwiseAnd(_LANDSAT_CLOUD_BITMASK).eq(0))


def scale_lst(image):
    masked = _mask_landsat_clouds(image)
    lst = (masked.select('ST_B10')
                 .multiply(0.00341802)
                 .add(149.0)
                 .subtract(273.15)
                 .rename('LST'))
    return masked.addBands(lst)


def get_lst_col(geom, year: int, month: int = None):
    filters = [
        ee.Filter.lt('CLOUD_COVER', 40),
        ee.Filter.calendarRange(year, year, 'year'),
    ]
    if month:
        filters.append(ee.Filter.calendarRange(month, month, 'month'))

    def build(cid):
        return (ee.ImageCollection(cid)
                .filterBounds(geom)
                .filter(ee.Filter.And(*filters))
                .map(scale_lst)
                .select('LST'))

    return build('LANDSAT/LC08/C02/T1_L2').merge(
           build('LANDSAT/LC09/C02/T1_L2'))


def worldpop_pop_collection(year: int):
    """WorldPop GP/100m/pop ของไทย (THA) ปีที่ระบุ — สร้าง filter country/year ที่เดียว.

    ใช้ร่วม /recommend (scoring), /analysis/urban-subset, /analysis/custom-area
    เพื่อกัน drift ของ filter · caller เช็ค .size() เองก่อน .first() เพราะถ้าไม่มี
    ภาพสำหรับปีนี้ .first() = null → ee.Image(null) พังด้วย 'input may not be null'
    (ดู worldpop_unavailable_error ใน dependencies สำหรับข้อความ 503 มาตรฐาน)
    """
    return (ee.ImageCollection('WorldPop/GP/100m/pop')
            .filter(ee.Filter.eq('country', 'THA'))
            .filter(ee.Filter.eq('year', year)))


def dynamic_world_built(geom, year: int):
    """Dynamic World 'built' probability เฉลี่ยทั้งปี (0–1) = สัดส่วนพื้นผิวทึบน้ำ (ISA proxy).

    GOOGLE/DYNAMICWORLD/V1 เป็น land cover 10 m near-real-time (deep learning) ที่ mask
    เมฆรายภาพให้แล้ว → mean() ทั้งปีเป็น composite ที่ทนเมฆ (แนวเดียวกับงานวิจัย Moukomla
    et al. 2026, Earth 7:76 ที่ใช้ built prob เป็น reference ของ impervious surface).
    unmask(0): pixel ที่ไม่มีภาพทั้งปี (เมฆตลอด/นอกครอบคลุม) ถือว่า "ไม่ทึบ" ให้สอดคล้อง
    กับ lst_heat/pop_need ที่ unmask แล้ว — ไม่เปิดรูใน priority · คืน band 'isa_frac'.
    """
    return (ee.ImageCollection('GOOGLE/DYNAMICWORLD/V1')
            .filterBounds(geom)
            .filterDate(f'{year}-01-01', f'{year + 1}-01-01')  # end exclusive
            .select('built')
            .mean().unmask(0).rename('isa_frac'))


def reduce_lst(col, geom, scale):
    stats = (col.median()
               .reduceRegion(
                   reducer=ee.Reducer.mean()
                           .combine(ee.Reducer.min(), '', True)
                           .combine(ee.Reducer.max(), '', True),
                   geometry=geom,
                   scale=scale,
                   maxPixels=1e10,
                   bestEffort=True)
               .getInfo())
    # None = ไม่มี pixel ที่ใช้ได้ในพื้นที่นี้ ต้องคืน None ไม่ใช่ 0 — เดิม `or 0`
    # เปลี่ยน "ไม่มีข้อมูล" ให้กลายเป็น 0.0 °C ซึ่งหน้าเว็บแสดงเป็นค่าที่วัดได้จริง
    # (schemas.LSTResponse ประกาศ Optional[float] ไว้แล้ว และ custom.py ก็คืน None
    # ในเคสไม่มีภาพอยู่ก่อน — ตรงกับหลักการ "ค่า ไม่ใช่คำตัดสิน" ของระบบ)
    def _c(key):
        v = stats.get(key)
        return round(v, 2) if v is not None else None

    return _c('LST_mean'), _c('LST_min'), _c('LST_max')
