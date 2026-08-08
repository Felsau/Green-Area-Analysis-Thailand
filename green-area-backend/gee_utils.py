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


def _mask_landsat_clouds(image):
    qa = image.select('QA_PIXEL')
    mask = (qa.bitwiseAnd(1 << 4).eq(0)
              .And(qa.bitwiseAnd(1 << 3).eq(0)))
    return image.updateMask(mask)


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
    return (round(stats.get('LST_mean') or 0, 2),
            round(stats.get('LST_min')  or 0, 2),
            round(stats.get('LST_max')  or 0, 2))
