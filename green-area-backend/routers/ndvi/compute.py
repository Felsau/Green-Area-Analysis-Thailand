"""Pure compute helpers สำหรับ NDVI — แยกจาก endpoints เพื่อ test/reuse ได้ตรง.

`_is_stale` + `compute_who_status` ถูก import ตรงใน tests (test_pure_helpers)
และ re-export ผ่าน routers/ndvi/__init__.py
"""
import math
from datetime import datetime, timezone

import ee

from canopy import build_canopy, canopy_area_bands
from dependencies import CURRENT_CACHE_VERSION, WHO_STANDARD_M2, MONTH_NAMES
from gee_utils import clean_s2_collection


def _is_stale(row: dict) -> bool:
    """Cache row ที่ควร invalidate และคำนวณใหม่.

    เกณฑ์ (เรียงตาม priority):
      1. cache_version < CURRENT_CACHE_VERSION → schema/logic เปลี่ยน, recompute
      2. ขาด field สำคัญ (green_area_pct, total_area_km2)
      3. NDVI Min ต่ำกว่า −0.05 = cache ก่อนยุค water mask (legacy heuristic)

    เกณฑ์ #3 ถูกแทนที่ด้วย cache_version ในอนาคต — เก็บไว้ backward-compat
    กับ row ที่สร้างก่อน migration 002
    """
    # ใช้ .get default = 1 สำหรับ row จาก legacy schema ที่ยังไม่มี column
    if row.get("cache_version", 1) < CURRENT_CACHE_VERSION:
        return True
    if row.get("green_area_pct") is None or row.get("total_area_km2") is None:
        return True
    # row ที่คำนวณก่อน NFR-07 ไม่มีข้อมูลคุณภาพ composite — recompute ให้ทุกค่า NDVI
    # ที่แสดง/ลงรายงานมีตัวเลขความไม่แน่นอนกำกับเสมอ (ไม่ bump CURRENT_CACHE_VERSION
    # เพราะ version นั้นใช้ร่วมกับ cache ของ LST/urban ที่ไม่ได้เปลี่ยน schema)
    if row.get("data_quality") is None:
        return True
    # row ที่คำนวณก่อน FR-17 ไม่มีตัวชี้วัดเรือนยอด — เหตุผลเดียวกับ data_quality
    # (ปีก่อน 2015 ที่ DW ไม่มีข้อมูลก็ยังได้ dict {"available": false} ไม่ใช่ None
    # จึงไม่วนคำนวณซ้ำทุกครั้ง)
    if row.get("canopy") is None:
        return True
    nm = row.get("ndvi_min")
    if nm is not None and nm < -0.05:
        return True
    return False


def compute_who_status(green_area_m2, population):
    """คำนวณ m²/คน + ข้อความ WHO เทียบมาตรฐาน 9 m²/คน

    Return tuple (m2_per_person, status_text) — ทั้งสองเป็น None ถ้าข้อมูลไม่พอ
    """
    if not population or not green_area_m2:
        return None, None
    m2_per_person = round(green_area_m2 / population, 2)
    # แสดงด้วย .2f ให้ตรงกับความละเอียดที่ใช้ตัดสินผ่าน/ไม่ผ่าน — ถ้าใช้ .1f ค่าเช่น 8.96
    # (ไม่ผ่าน) จะถูกปัดแสดงเป็น "9.0 m²/คน" คู่กับคำว่า "ต่ำกว่ามาตรฐาน" ดูย้อนแย้ง
    if m2_per_person >= WHO_STANDARD_M2:
        status = f"ผ่านมาตรฐาน WHO ✅ ({m2_per_person:.2f} m²/คน)"
    else:
        status = f"ต่ำกว่ามาตรฐาน WHO ⚠️ ({m2_per_person:.2f} m²/คน)"
    return m2_per_person, status


# ── NFR-07: คุณภาพ/ความไม่แน่นอนของ NDVI composite ──────────────────────────
# ค่า NDVI ทุกค่าในระบบมาจาก *median composite* ของภาพทั้งปี — ถ้าปีนั้นในพื้นที่นั้น
# มีภาพปลอดเมฆน้อย (ภาคใต้/ฤดูฝน — ข้อจำกัดที่ REQUIREMENTS §5 ระบุไว้เอง) median
# ถูกคำนวณจากตัวอย่างไม่กี่ค่า ความไม่แน่นอนจึงสูง แต่หน้าจอแสดงทศนิยม 4 ตำแหน่ง
# เท่ากันหมดโดยไม่บอกว่าอิงภาพกี่ภาพ → เก็บ metadata นี้คู่กับค่าทุกครั้ง
#
# รายงาน 2 ตัวชี้วัดที่แยกจากกัน (ไม่เอามาถัวเฉลี่ยเป็นคะแนนเดียว):
#   1. ความไม่แน่นอนเชิงปริมาณของค่ากลางรายปี → เทียบเกณฑ์ GCOS-245
#   2. ความเป็นตัวแทนของฤดูกาล → เทียบนิยามฤดูของกรมอุตุนิยมวิทยา
S2_CLOUD_FILTER_PCT = 20           # เกณฑ์หลัก — รับเฉพาะภาพที่เมฆทั้งภาพ < 20%
S2_CLOUD_FILTER_FALLBACK_PCT = 80  # เกณฑ์สำรอง เมื่อทั้งปีไม่มีภาพผ่านเกณฑ์หลัก

# การจัดระดับใช้ "เกณฑ์ที่อ้างอิงได้" ไม่ใช่ตัวเลขที่ตั้งเอง (ดูรายละเอียดแต่ละค่า
# ด้านล่าง) · หลักการมาจาก QA4EO (CEOS/GEO): ผลิตภัณฑ์ EO ทุกชิ้นต้องแนบ Quality
# Indicator ที่ "ประเมินเชิงปริมาณและสาวกลับไปหามาตรฐานที่ตกลงร่วมกันได้"

# ── (1) ความไม่แน่นอนของค่ากลางรายปี ────────────────────────────────────────
# u = 1.2533 · σ / √n  — standard error ของ *median* (ค่า asymptotic √(π/2) เทียบกับ
# ของ mean) · σ = ส่วนเบี่ยงเบนมาตรฐานของ NDVI รายภาพในปีนั้นต่อ pixel (จึงรวมทั้ง
# noise ของเซนเซอร์และการแปรผันตามฤดูกาลจริง — ตีความว่า "เรารู้ค่ากลางรายปีแม่นแค่ไหน
# จากตัวอย่างที่มี" ไม่ใช่ error เทียบ ground truth)
MEDIAN_SE_FACTOR = 1.2533

# พื้น σ ขั้นต่ำต่อภาพ — กันเคส n น้อยมากแล้ว σ ที่วัดได้เล็กผิดจริง (n=1 → σ=0 →
# ความไม่แน่นอน 0 ทั้งที่แย่ที่สุด) · ใช้ RMSE ของ Sentinel-2 NDVI เทียบเซนเซอร์
# ภาคพื้นดิน จาก Lee et al. 2024 (Sensors 24(6):1892 — [R24] ในบรรณานุกรม) ซึ่ง
# รายงาน RMSE รายจุด 0.057–0.081 · เลือกขอบล่าง 0.06 = ประมาณค่าอย่างไม่พองตัวเลข
SENSOR_NDVI_SD = 0.06

# เกณฑ์ตัดระดับ = GCOS-245 "The 2022 GCOS ECVs Requirements" สำหรับ FAPAR ซึ่งเป็น
# ECV ด้านพืชพรรณที่ใกล้ NDVI ที่สุด (NDVI ถูกใช้เป็น proxy ของ FAPAR อย่างแพร่หลาย)
# — required measurement uncertainty (2σ): Goal 5% ของค่า · Threshold 10%
# GCOS นิยาม Goal = "ระดับที่ดีจนไม่ต้องพัฒนาต่อ" · Threshold = "ขั้นต่ำที่ข้อมูลยัง
# มีประโยชน์" · หมายเหตุสำคัญ: NDVI ไม่ได้เป็น ECV ในตัวเอง จึงเป็นการ *เทียบเคียง*
# เกณฑ์ climate-record ซึ่งเข้มกว่าที่งานจัดอันดับพื้นที่สีเขียวต้องการ
GCOS_GOAL_PCT = 5.0
GCOS_THRESHOLD_PCT = 10.0

QUALITY_LABELS = {
    "goal": "ผ่านเกณฑ์ Goal (GCOS)",
    "threshold": "ผ่านเกณฑ์ Threshold (GCOS)",
    "below": "ต่ำกว่าเกณฑ์ GCOS",
    "none": "ไม่มีภาพ",
}

# ── (2) ความเป็นตัวแทนของฤดูกาล ─────────────────────────────────────────────
# composite รายปีที่มีภาพเฉพาะฤดูแล้งให้ NDVI ต่ำกว่าค่าจริงของทั้งปี · แบ่งฤดูตาม
# นิยามกรมอุตุนิยมวิทยา (ฤดูร้อน กลาง ก.พ.–กลาง พ.ค. · ฤดูฝน กลาง พ.ค.–กลาง ต.ค. ·
# ฤดูหนาว กลาง ต.ค.–กลาง ก.พ.) แทนการนับเดือนแบบตั้งเกณฑ์เอง · TMD ประกาศวันเริ่ม
# ฤดูจริงเป็นรายปี ที่นี่ใช้ "กลางเดือน = วันที่ 16" เป็นค่าประมาณคงที่
TMD_SEASONS = (
    ("ฤดูร้อน", (2, 16), (5, 15)),
    ("ฤดูฝน", (5, 16), (10, 15)),
    ("ฤดูหนาว", (10, 16), (2, 15)),   # คร่อมปีใหม่
)


def season_of(month: int, day: int) -> str:
    """ฤดูตามนิยาม TMD ของวันที่ (เดือน, วัน) — ฤดูหนาวคร่อมปีใหม่จึงเป็น else"""
    for name, (m1, d1), (m2, d2) in TMD_SEASONS[:2]:
        if (month, day) >= (m1, d1) and (month, day) <= (m2, d2):
            return name
    return TMD_SEASONS[2][0]


def summarize_acquisitions(times_ms: list) -> dict:
    """สรุปช่วงเวลาที่ภาพเข้า composite จาก `system:time_start` (epoch ms).

    คืนวันแรก/วันสุดท้าย + เดือนที่มี/ขาด + ฤดู (TMD) ที่มี/ขาด — ตอบข้อ "ช่วงฤดูที่ใช้
    composite" ของ NFR-07 · ใช้ UTC ตรงกับที่ GEE เก็บ — เวลาถ่ายจริงของ Sentinel-2
    เหนือไทยราว 10:30 น. ตามเวลาท้องถิ่น (~03:30 UTC วันเดียวกัน) วันที่จึงไม่เลื่อน
    """
    all_seasons = [s[0] for s in TMD_SEASONS]
    if not times_ms:
        return {"first_date": None, "last_date": None,
                "months_covered": 0, "months_missing": list(range(1, 13)),
                "seasons_covered": [], "seasons_missing": all_seasons,
                "seasonally_representative": False}
    dates = sorted(datetime.fromtimestamp(t / 1000, tz=timezone.utc) for t in times_ms)
    months = {d.month for d in dates}
    seasons = {season_of(d.month, d.day) for d in dates}
    return {
        "first_date": dates[0].strftime("%Y-%m-%d"),
        "last_date": dates[-1].strftime("%Y-%m-%d"),
        "months_covered": len(months),
        "months_missing": [m for m in range(1, 13) if m not in months],
        "seasons_covered": [s for s in all_seasons if s in seasons],
        "seasons_missing": [s for s in all_seasons if s not in seasons],
        "seasonally_representative": len(seasons) == len(all_seasons),
    }


def composite_uncertainty(ndvi_sd, clear_obs) -> float:
    """u (1σ) ของค่า NDVI กลางรายปี = MEDIAN_SE_FACTOR · max(σ, พื้นเซนเซอร์) / √n."""
    sd = max(ndvi_sd or 0.0, SENSOR_NDVI_SD)
    n = max(clear_obs or 0, 1)
    return MEDIAN_SE_FACTOR * sd / math.sqrt(n)


def grade_uncertainty(uncertainty: float, ndvi_mean: float) -> tuple[str, float | None]:
    """เทียบ 2σ กับเกณฑ์ GCOS → (level, ความไม่แน่นอนสัมพัทธ์ 2σ เป็น % ของค่า).

    GCOS ระบุ requirement เป็นสัดส่วนของค่าที่วัดได้ (5%/10% ที่ 2σ) — พื้นที่เมือง
    ที่ NDVI ต่ำจึงผ่านยากกว่าโดยธรรมชาติ เพราะ error เท่ากันคิดเป็น % ได้มากกว่า

    ndvi_mean ≤ 0 (พื้นที่เป็นน้ำ/ไม่มีพืชเลย) คิดสัดส่วนไม่ได้ → คืน rel = None
    (ห้ามคืน inf — json.dumps เขียน `Infinity` ซึ่งไม่ใช่ JSON ที่ถูกต้อง jsonb ปฏิเสธ)
    """
    if not ndvi_mean or ndvi_mean <= 0:
        return "below", None
    rel_pct = 200.0 * uncertainty / ndvi_mean       # 200 = 2σ แล้วคูณ 100 เป็น %
    if rel_pct <= GCOS_GOAL_PCT:
        return "goal", rel_pct
    if rel_pct <= GCOS_THRESHOLD_PCT:
        return "threshold", rel_pct
    return "below", rel_pct


def build_data_quality(times_ms: list, clear_obs_mean, clear_obs_min, ndvi_sd_mean,
                       ndvi_mean: float, cloud_filter_pct: int) -> dict:
    """รวมตัวชี้วัดคุณภาพเป็น dict เดียว — เก็บลง cache (jsonb) และส่งกลับ client ตรง."""
    span = summarize_acquisitions(times_ms)
    obs_mean = round(clear_obs_mean or 0, 1)
    sd_mean = round(ndvi_sd_mean or 0, 4)
    image_count = len(times_ms)

    if image_count <= 0:
        return {"image_count": 0, "cloud_filter_pct": cloud_filter_pct,
                "clear_obs_mean": 0, "clear_obs_min": 0, "ndvi_sd_mean": 0,
                "uncertainty": None, "uncertainty_2sigma_pct": None,
                **span, "level": "none", "label": QUALITY_LABELS["none"],
                "note": "ไม่มีภาพ Sentinel-2 ที่ใช้ได้ในปีนี้"}

    u = composite_uncertainty(sd_mean, obs_mean)
    level, rel_pct = grade_uncertainty(u, ndvi_mean)

    # พื้นที่ที่ NDVI ≤ 0 (น้ำทั้งผืน) เทียบสัดส่วนแบบ GCOS ไม่ได้ — บอกค่าสัมบูรณ์แทน
    rel_text = (f"{rel_pct:.0f}% ของค่า — GCOS Goal ≤ {GCOS_GOAL_PCT:.0f}% · "
                f"Threshold ≤ {GCOS_THRESHOLD_PCT:.0f}%") if rel_pct is not None else \
               "พื้นที่นี้ไม่มีค่า NDVI เป็นบวก จึงเทียบสัดส่วนตามเกณฑ์ GCOS ไม่ได้"
    parts = [
        f"median composite จากภาพ Sentinel-2 {image_count:,} ภาพ "
        f"(เมฆทั้งภาพ < {cloud_filter_pct}%)",
        f"เฉลี่ย {obs_mean:.1f} ภาพปลอดเมฆต่อ pixel",
        f"ความไม่แน่นอนของค่ากลางรายปี ±{2 * u:.3f} NDVI ที่ 2σ ({rel_text})",
    ]
    if span["seasons_missing"]:
        parts.append("ไม่มีภาพในฤดู: " + ", ".join(span["seasons_missing"]) +
                     " (ค่ารายปีจึงเอนไปทางฤดูที่มีภาพ)")
    else:
        parts.append("มีภาพครบทั้ง 3 ฤดูตามนิยามกรมอุตุนิยมวิทยา")
    if cloud_filter_pct != S2_CLOUD_FILTER_PCT:
        parts.append(f"ปีนี้ไม่มีภาพผ่านเกณฑ์เมฆ < {S2_CLOUD_FILTER_PCT}% "
                     f"จึงผ่อนเกณฑ์เป็น < {cloud_filter_pct}%")

    return {
        "image_count": image_count,
        "cloud_filter_pct": cloud_filter_pct,
        "clear_obs_mean": obs_mean,
        "clear_obs_min": int(clear_obs_min or 0),
        "ndvi_sd_mean": sd_mean,
        "uncertainty": round(u, 4),
        "uncertainty_2sigma_pct": round(rel_pct, 1) if rel_pct is not None else None,
        **span,
        "level": level, "label": QUALITY_LABELS[level],
        "note": " · ".join(parts),
    }


# ── Shared compute helpers ───────────────────────────────────────────────────
def _compute_ndvi_annual(geom: ee.Geometry, year: int, scale: int):
    """คำนวณ NDVI + พื้นที่สีเขียว ประจำปี — คืน None ถ้าไม่มีภาพ.

    คืน dict ที่ใส่ insert ลง cache + ส่งกลับ client ได้เลย ยกเว้น
    `green_area_m2_raw` ซึ่งเป็นค่าดิบไว้ให้ caller ใช้คำนวณ m²/คน แล้ว pop ทิ้ง.
    """
    def s2_col(cloud_pct):
        return clean_s2_collection(
            ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
            .filterBounds(geom)
            .filterDate(f'{year}-01-01', f'{year + 1}-01-01')  # end exclusive — รวม 31 ธ.ค.
            .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', cloud_pct)))

    # ดึง system:time_start ของทุกภาพในคราวเดียว — ได้ทั้งจำนวนภาพ (แทน size()
    # ที่เดิมเรียก ไม่เพิ่ม round-trip) และช่วงวัน/เดือนที่ composite ครอบคลุม (NFR-07)
    cloud_filter_pct = S2_CLOUD_FILTER_PCT
    col = s2_col(cloud_filter_pct)
    times_ms = col.aggregate_array('system:time_start').getInfo()
    if not times_ms:
        cloud_filter_pct = S2_CLOUD_FILTER_FALLBACK_PCT
        col = s2_col(cloud_filter_pct)
        times_ms = col.aggregate_array('system:time_start').getInfo()
        if not times_ms:
            return None

    median = col.median().clip(geom)
    ndvi_raw = median.normalizedDifference(['B8', 'B4']).rename('NDVI')

    # Mask water + cloud-shadow pixels: NDVI < 0 บนบกแทบเป็นไปไม่ได้ที่ไม่ใช่ artifact
    # tileScale=4 ลด downsampling artifacts ที่ทำให้ mask ไม่ apply ครบทุก pixel
    water_mask = ndvi_raw.gte(0.0)
    ndvi_land = ndvi_raw.updateMask(water_mask)

    # ── วัตถุดิบของตัวชี้วัดความไม่แน่นอน (NFR-07) ───────────────────────────
    # NDVI รายภาพ (ต่างจาก ndvi_raw ที่เป็น NDVI ของ median composite) ใช้หา
    #   n  = จำนวน observation ที่ *รอดจาก mask เมฆ* ต่อ pixel — จริงกว่าจำนวนภาพทั้งปี
    #        (ภาพผ่านเกณฑ์เมฆ 20% ทั้งภาพ แต่ก้อนเมฆอาจทับอำเภอนี้ทุกครั้ง)
    #   σ  = การกระจายของ NDVI ตลอดปีต่อ pixel → เข้าสูตร standard error ของ median
    # unmask(0) ที่ n → pixel ที่ไม่มีภาพใดรอดเลยนับเป็น 0 ไม่ใช่หลุดออกจาก reduce
    # ทั้งสอง band รวมใน reduceRegion เดิม (sharedInputs=True) → ไม่เพิ่ม round-trip
    ndvi_col = col.map(lambda img: img.normalizedDifference(['B8', 'B4']).rename('NDVI'))
    clear_obs = ndvi_col.reduce(ee.Reducer.count()).unmask(0).rename('clear_obs').clip(geom)
    ndvi_sd = ndvi_col.reduce(ee.Reducer.stdDev()).rename('ndvi_sd').clip(geom)

    stats = ndvi_land.addBands(clear_obs).addBands(ndvi_sd).reduceRegion(
        reducer=ee.Reducer.mean()
                .combine(ee.Reducer.min(), '', True)
                .combine(ee.Reducer.max(), '', True),
        geometry=geom, scale=scale, maxPixels=1e10,
        bestEffort=True, tileScale=4).getInfo()

    ndvi_mean = round(stats.get('NDVI_mean') or 0, 4)
    ndvi_min  = round(stats.get('NDVI_min')  or 0, 4)
    ndvi_max  = round(stats.get('NDVI_max')  or 0, 4)

    data_quality = build_data_quality(
        times_ms, stats.get('clear_obs_mean'), stats.get('clear_obs_min'),
        stats.get('ndvi_sd_mean'), ndvi_mean, cloud_filter_pct)

    # Two thresholds: 0.3 (vegetation incl. crops) and 0.5 (dense forest)
    green_mask = ndvi_raw.gt(0.3)
    dense_mask = ndvi_raw.gt(0.5)

    # total/green/dense area + band เรือนยอดของ FR-17 รวมเป็นก้อนเดียวแล้ว reduceRegion
    # รอบเดียว — ลด GEE round-trip เหลือ 1 (pattern เดียวกับ urban.py) · canopy จึงแทบ
    # ไม่มีต้นทุนเพิ่มเพราะเกาะ reduce ก้อนที่ต้องยิงอยู่แล้ว
    pixel_area = ee.Image.pixelArea().clip(geom)
    area_stack = (pixel_area.rename('total_area')
                  .addBands(pixel_area.updateMask(green_mask).rename('green_area'))
                  .addBands(pixel_area.updateMask(dense_mask).rename('dense_area'))
                  .addBands(canopy_area_bands(geom, year)))
    area_sums = area_stack.reduceRegion(
        reducer=ee.Reducer.sum(), geometry=geom,
        scale=scale, maxPixels=1e10, bestEffort=True, tileScale=4).getInfo()
    total_area_m2 = area_sums.get('total_area')
    green_area_m2 = area_sums.get('green_area')
    dense_area_m2 = area_sums.get('dense_area')

    total_area_km2 = round((total_area_m2 or 0) / 1_000_000, 2)
    green_area_km2 = round((green_area_m2 or 0) / 1_000_000, 2)
    dense_area_km2 = round((dense_area_m2 or 0) / 1_000_000, 2)
    green_area_pct = round(((green_area_m2 or 0) / total_area_m2) * 100, 1) if total_area_m2 else 0
    dense_area_pct = round(((dense_area_m2 or 0) / total_area_m2) * 100, 1) if total_area_m2 else 0

    # FR-17: เรือนยอด (คลาสต้นไม้) เทียบเกณฑ์ 30% ของ 3-30-300 — คนละนิยามกับ
    # green_area_pct ข้างบนที่เป็น "พืชพรรณทุกชนิด" จาก NDVI (ดู canopy.py)
    canopy = build_canopy(area_sums.get('canopy_area'), area_sums.get('dw_area'),
                          area_sums.get('dw_valid_area'), area_sums.get('dw_base_area'),
                          total_area_m2, year)

    return {
        "ndvi_mean": ndvi_mean, "ndvi_min": ndvi_min, "ndvi_max": ndvi_max,
        "green_area_pct": green_area_pct, "green_area_km2": green_area_km2,
        "dense_area_pct": dense_area_pct, "dense_area_km2": dense_area_km2,
        "total_area_km2": total_area_km2,
        "data_quality": data_quality,
        "canopy": canopy,
        "green_area_m2_raw": green_area_m2,
    }


def _compute_ndvi_monthly(geom: ee.Geometry, year: int, scale: int):
    """NDVI 12 เดือน รวมใน 1 round-trip ด้วย ee.List.sequence(server-side map)."""
    def by_month(m):
        m_int = ee.Number(m).toInt()
        col = clean_s2_collection(
            ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
            .filterBounds(geom)
            .filter(ee.Filter.calendarRange(m_int, m_int, 'month'))
            .filter(ee.Filter.calendarRange(year, year, 'year'))
            .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 80)))
        # เติม B8/B4 placeholder กัน normalizedDifference พังตอน col ว่าง
        median = col.median().addBands(
            ee.Image.constant([0, 0]).rename(['B8', 'B4']).selfMask(),
            overwrite=False)
        ndvi = (median.normalizedDifference(['B8', 'B4'])
                .rename('NDVI')
                .reduceRegion(reducer=ee.Reducer.mean(), geometry=geom,
                              scale=scale, maxPixels=1e10, bestEffort=True)
                .get('NDVI'))
        return ee.Feature(None, {'month_num': m_int, 'count': col.size(), 'ndvi': ndvi})

    fc = ee.FeatureCollection(ee.List.sequence(1, 12).map(by_month))
    feats = fc.getInfo()['features']

    results = []
    for f in feats:
        props = f['properties']
        m = int(props['month_num'])
        count = int(props.get('count') or 0)
        ndvi_raw = props.get('ndvi')
        ndvi_val = round(ndvi_raw, 4) if ndvi_raw is not None else None
        results.append({"month": MONTH_NAMES[m - 1], "month_num": m,
                        "ndvi": ndvi_val, "image_count": count})
    return results
