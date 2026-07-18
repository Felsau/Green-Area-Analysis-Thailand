"""Priority scoring engine — NDVI deficit + LST heat + population need.

ใช้คำนวณ priority image (100m) สำหรับ heatmap + top-N pixels + plantable area.
"""
import logging
import math

import ee
from fastapi import HTTPException

from dependencies import WORLDPOP_YEAR, worldpop_unavailable_error
from gee_utils import (clean_s2_collection, get_lst_col, worldpop_pop_collection,
                       dynamic_world_built)
from impact import IMPACT_DEFAULTS
from landuse import CATEGORY_BY_VALUE, landuse_image

logger = logging.getLogger(__name__)

# Weights — ปรับได้ตาม use case · รวมเป็น 1.0 (normalize_weights บังคับอีกชั้น)
W_NDVI = 0.35     # การขาดพืชพรรณสำคัญที่สุด
W_LST = 0.25      # ความร้อนสำคัญรอง
W_POP = 0.25      # ประชากรเป็นปัจจัยร่วม
W_ACCESS = 0.15   # การเข้าถึงพื้นที่สีเขียว (equity) — ไกลจากต้นไม้เดิม = ขาดแคลน

# Heat island = "ร้อนกว่าค่าเฉลี่ยรอบข้าง" ไม่ใช่อุณหภูมิสัมบูรณ์ → ใช้ LST anomaly
# (pixel − ค่าเฉลี่ยพื้นที่) normalize ด้วยช่วงนี้ · +6°C เหนือค่าเฉลี่ย → คะแนนเต็ม
# (urban core ร้อนกว่ารอบนอก ~5–10°C) · เดิมใช้ absolute 25–40°C ทำให้จังหวัดร้อน
# ตามธรรมชาติได้คะแนนสูงทั้งจังหวัด จับ hotspot จริงไม่ได้
LST_ANOMALY_SPREAD = 6.0

# ── Peri-urban cooling opportunity (จากงานวิจัย Moukomla et al. 2026, Earth 7:76) ──
# พื้นผิวทึบน้ำ (ISA) สัมพันธ์บวกกับความร้อนผิว แต่ "อิ่มตัว" ที่ใจกลางเมืองทึบเต็ม
# (stratified Pearson r≈−0.14 ไม่ significant) — marginal cooling จากการปลูกต้นไม้สูงสุด
# ที่ "ขอบเมืองกำลังขยาย" (pervious→mixed) ไม่ใช่ core ที่ทึบอยู่แล้ว หรือชนบทที่ยังเขียว
# ใช้ Dynamic World built prob (annual mean, cloud-resilient) เป็น ISA แล้ว shape เป็น
# trapezoid: ต่ำที่ ISA~0 (ทุ่ง/ป่า — ปัจจัยอื่นดูแลอยู่แล้ว) → สูงสุดช่วง fringe →
# ลดลงที่ core ทึบ · เป็นปัจจัย additive (blend หลัง 4 ปัจจัยผู้ใช้ ไม่ลดมิติ/ไม่ทำให้ heatmap จืด)
W_PERI = 0.15         # น้ำหนักคงที่ · 4 ปัจจัยผู้ใช้ถูก re-normalize ให้กินสัดส่วน (1 − W_PERI)
PERI_RISE_ISA = 0.25  # ISA ที่ไต่ถึงโอกาสเต็ม (จาก 0 ที่ ISA=0)
PERI_FALL_ISA = 0.60  # ISA ที่เริ่มอิ่มตัว (เกินนี้โอกาสลดลง)
PERI_SAT_FLOOR = 0.15 # โอกาสคงเหลือที่ core ทึบเต็ม (ISA=1) — ไม่ 0 สนิท (ยังปลูกได้ ผลน้อย)


def peri_urban_need_image(geom: ee.Geometry, year: int) -> ee.Image:
    """peri_need (0–1): โอกาสลดความร้อนจากการปลูก สูงสุดที่ "ขอบเมืองกำลังขยาย".

    Trapezoid บน ISA (Dynamic World built prob เฉลี่ยทั้งปี):
      ไต่ 0→1 ช่วง ISA [0, PERI_RISE_ISA] · คงที่ 1 ช่วง [PERI_RISE_ISA, PERI_FALL_ISA]
      · ลด 1→PERI_SAT_FLOOR ช่วง [PERI_FALL_ISA, 1] (อิ่มตัวที่ core ทึบเต็ม)
    ทำด้วย min(rise, fall) · isa unmask(0) มาแล้ว → ไม่มีรู (สอดคล้อง lst_heat/pop_need)
    """
    isa = dynamic_world_built(geom, year)
    rise = isa.divide(PERI_RISE_ISA).clamp(0, 1)
    fall = ee.Image.constant(1).subtract(
        isa.subtract(PERI_FALL_ISA)
           .divide(1.0 - PERI_FALL_ISA).clamp(0, 1)
           .multiply(1.0 - PERI_SAT_FLOOR))
    return rise.min(fall).clamp(0, 1).unmask(0).rename('peri_need')


def normalize_weights(w_ndvi: float, w_lst: float, w_pop: float,
                      w_access: float = W_ACCESS) -> tuple[float, float, float, float]:
    """Normalize weights ให้รวมเป็น 1.0 — กัน UI ส่ง slider ที่บวกไม่ครบ
    Fallback ไป default ถ้ารวมเป็น 0 หรือติดลบ"""
    total = w_ndvi + w_lst + w_pop + w_access
    if total <= 0:
        return W_NDVI, W_LST, W_POP, W_ACCESS
    return w_ndvi / total, w_lst / total, w_pop / total, w_access / total


# ── Plantability (ESA WorldCover v200, ปี 2021) ──────────────────────────────
# พื้นที่ที่ "ปลูกป่าได้จริง" — เดิม plantable area คิดจาก priority>threshold เฉยๆ
# → ระบบแนะนำปลูกบนน้ำ/อาคาร/ป่าที่มีอยู่แล้วได้ · ใช้ WorldCover (global mosaic
# ปี 2021, single image — ตัวเดียวกับที่ urban.py ใช้) เป็น mask กรองออก
# class ที่ตัดออก (ปลูกไม่ได้/ไม่ควร):
#   10 Tree cover (มีต้นไม้อยู่แล้ว ไม่ใช่พื้นที่ขาด) · 50 Built-up (สิ่งปลูกสร้าง —
#   ปลูก 400 ต้น/ha ไม่ได้จริง) · 70 Snow/ice · 80 Permanent water (ปลูกไม่ได้) ·
#   90 Herbaceous wetland · 95 Mangroves (ระบบนิเวศชุ่มน้ำ/ป่าชายเลน) · 100 Moss/lichen
# คงเป็น plantable: 20 Shrubland, 30 Grassland, 40 Cropland, 60 Bare/sparse
# NOTE: Cropland (40) นับเป็น plantable โดย default (marginal land/agroforestry) —
#       ถ้าต้องการนับเฉพาะที่ว่างจริง เพิ่ม 40 ลงใน tuple นี้
ESA_NON_PLANTABLE_CLASSES = (10, 50, 70, 80, 90, 95, 100)

# ความชันสูงสุดที่ยังปลูกได้ (องศา) — เกินนี้ = ลาดชันมาก ปลูกยาก/ดินสไลด์/กล้าไม่รอด
# 30° ≈ 58% grade · ตัดหน้าผา/ภูเขาชันออก แต่ยังคงเนินเขาทั่วไป · คำนวณจาก SRTM 30m
MAX_SLOPE_DEG = 30

# ── Accessibility / equity (ระยะถึงพื้นที่สีเขียวเดิม) ────────────────────────
# คนที่อยู่ไกลจากต้นไม้/พื้นที่สีเขียว = เข้าถึงพื้นที่สีเขียวยาก → ควรได้รับความสำคัญ
# ก่อน (ตรงกับภารกิจ m²/คน ตามมาตรฐาน WHO ของทั้งระบบ) · ใช้ ESA WorldCover class 10
# (Tree cover) เป็น "พื้นที่สีเขียวเดิม" แล้ววัดระยะถึง pixel ต้นไม้ใกล้สุด
ESA_TREE_COVER_CLASS = 10
# Scale คงที่ที่ใช้คำนวณ distance transform (เมตร/pixel) — ดู docstring ว่าทำไมต้องปักหมุด
ACCESS_DT_SCALE_M = 100.0
# ไกลจากต้นไม้เกินระยะนี้ = ขาดแคลนพื้นที่สีเขียวเต็มที่ (access_need = 1) · 1 กม. ≈
# ระยะเดินเข้าถึงสวน/ร่มไม้ที่เหมาะสมในเขตเมือง
ACCESS_MAX_DIST_M = 1000.0
# หน้าต่างค้นหา fastDistanceTransform (pixel ที่ ACCESS_DT_SCALE_M) — ต้องคลุมระยะ cap:
# ACCESS_MAX_DIST_M / ACCESS_DT_SCALE_M = 10 px · 64 px × 100 m = 6.4 km >> 1 km เผื่อเหลือ
ACCESS_NEIGHBORHOOD_PX = 64


def access_need_image(geom: ee.Geometry) -> ee.Image:
    """access_need (0–1): ระยะถึงพื้นที่สีเขียวเดิม normalize แล้ว — ไกล = ค่าสูง = ขาดแคลน.

    ESA WorldCover class 10 (Tree cover) = พื้นที่สีเขียวเดิม · fastDistanceTransform
    คืน *squared* distance (หน่วย pixel) ถึง non-zero (= ต้นไม้) ใกล้สุด → sqrt = pixel.

    สำคัญ: fastDistanceTransform คิดระยะเป็น "pixel" ของ projection ที่ EE เลือกตอน
    compute (แปรตาม zoom ของ tile / scale ของ sample เช่น 200 m) — ไม่ใช่ 10 m native
    ของ WorldCover · ถ้าไม่ปักหมุด การคูณ scale คงที่จะผิดและ access_need เพี้ยนตาม scale
    (ที่ sample 200 m จะ ~0 แทบทั้งภาพ) · จึง reproject mask ไปกริดคงที่ ACCESS_DT_SCALE_M
    ก่อน → pixel = 100 m เสมอ → คูณ 100 ได้เมตรจริง · pixel บนต้นไม้ = ระยะ 0 = need 0
    """
    wc = ee.ImageCollection("ESA/WorldCover/v200").first().clip(geom)
    # ปักหมุดกริดที่ ACCESS_DT_SCALE_M ให้ fastDistanceTransform คิดเป็น pixel 100 m คงที่
    # (deterministic ทุก zoom/scale) · NOTE: reproject sample แบบ nearest อาจพลาดต้นไม้
    # หย่อมเล็ก < 100 m → ประเมิน "ไกลจากสีเขียว" สูงไปเล็กน้อย (conservative)
    proj = wc.projection().atScale(ACCESS_DT_SCALE_M)
    tree = wc.eq(ESA_TREE_COVER_CLASS).reproject(proj)  # 1 = ต้นไม้, 0 = ไม่มี
    dist_m = (tree.fastDistanceTransform(ACCESS_NEIGHBORHOOD_PX).sqrt()
              .multiply(ACCESS_DT_SCALE_M))
    return (dist_m.divide(ACCESS_MAX_DIST_M).clamp(0, 1)
            .unmask(0).rename('access_need'))


def plantable_mask(geom: ee.Geometry) -> ee.Image:
    """คืน mask (1 = ปลูกได้, ที่เหลือถูก mask) จาก ESA WorldCover v200 + ความชัน SRTM.

    ใช้กรอง top-locations + plantable-area ไม่ให้แนะนำปลูกบนน้ำ อาคาร ป่าเดิม พื้นที่
    ชุ่มน้ำ หรือพื้นที่ลาดชันเกิน · ไม่ใช้ mask นี้กับ priority heatmap (heatmap ยังโชว์
    "ความต้องการ" ทั่วพื้นที่) · WorldCover/SRTM เป็น global ครอบคลุมทั้งไทย
    """
    wc = ee.ImageCollection("ESA/WorldCover/v200").first().clip(geom)
    non_plantable = ee.Image.constant(0)
    for code in ESA_NON_PLANTABLE_CLASSES:
        non_plantable = non_plantable.Or(wc.eq(code))
    landcover_ok = non_plantable.Not()
    # ความชัน — ตัดพื้นที่ลาดชันเกิน MAX_SLOPE_DEG (ปลูกยาก/ดินสไลด์)
    slope_ok = ee.Terrain.slope(ee.Image('USGS/SRTMGL1_003')).lte(MAX_SLOPE_DEG)
    # selfMask() → 0 (ปลูกไม่ได้) ถูก mask, เหลือเฉพาะ pixel ค่า 1 ที่ปลูกได้
    return landcover_ok.And(slope_ok).selfMask().rename('plantable')


def assert_imagery_available(geom: ee.Geometry, year: int) -> None:
    """ตรวจว่ามีภาพ S2 + Landsat ที่ผ่าน cloud filter พอจะ compute priority ไหม.

    Guard ปีปัจจุบัน — ต้นปีอาจมี S2/Landsat น้อยจน median() คืน empty image
    แล้วลูกโซ่ select ภายในล้มเหลวด้วย error คลุมเครือ ('input may not be null')
    เช็คครั้งเดียวด้วย ee.Dictionary().getInfo() → roundtrip เดียว ~300-500ms

    ตรง threshold ที่ใช้ filter ต้องตรงกับใน compute_priority + get_lst_col
    ไม่งั้น guard จะคลาดกับ compute จริง"""
    s2_size = (ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
               .filterBounds(geom)
               .filterDate(f'{year}-01-01', f'{year + 1}-01-01')  # end exclusive — รวม 31 ธ.ค.
               .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 80))
               .size())
    lst_size = get_lst_col(geom, year).size()
    # WorldPop: .first() คืน null ถ้าไม่เจอ THA+WORLDPOP_YEAR — pop_need กลายเป็น null
    # → ทั้ง priority image พัง getMapId ตอน 'Image.select: input may not be null'
    # ตรวจ size แทน .first() เพื่อจับ case นี้ก่อน compute
    pop_size = worldpop_pop_collection(WORLDPOP_YEAR).size()
    counts = ee.Dictionary({'s2': s2_size, 'lst': lst_size, 'pop': pop_size}).getInfo()
    missing = []
    if counts['s2'] == 0:
        missing.append(f"Sentinel-2 NDVI ปี {year}")
    if counts['lst'] == 0:
        missing.append(f"Landsat LST ปี {year}")
    if counts['pop'] == 0:
        # WorldPop ขาด = config issue ฝั่ง server ไม่ใช่เรื่องของปี → ข้อความต่างจาก S2/LST
        raise worldpop_unavailable_error(WORLDPOP_YEAR)
    if missing:
        raise HTTPException(status_code=422, detail=(
            f"ยังไม่มีข้อมูล {' + '.join(missing)} เพียงพอ — ลองเลือกปีก่อนหน้านี้"
        ))


def compute_priority(geom: ee.Geometry, year: int,
                     w_ndvi: float = W_NDVI, w_lst: float = W_LST,
                     w_pop: float = W_POP, w_access: float = W_ACCESS):
    """คำนวณ Priority Score image (100m resolution) สำหรับ geometry ที่ระบุ"""

    # ── 1. NDVI ────────────────────────────────────────────────
    s2 = clean_s2_collection(
        ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
        .filterBounds(geom)
        .filterDate(f'{year}-01-01', f'{year + 1}-01-01')  # end exclusive — รวม 31 ธ.ค.
        .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 80)))
    ndvi = s2.median().normalizedDifference(['B8', 'B4']).rename('NDVI')

    # NDVI deficit: NDVI < 0.3 = ขาดต้นไม้ (clamp 0-1)
    # unmask(0): pixel ที่ S2 median ใส masked (เมฆเยอะตลอดปี) → ถือว่า "ไม่ขาดต้นไม้"
    # ให้สอดคล้องกับ lst_heat/pop_need ที่ unmask แล้ว — ไม่งั้น priority ทั้ง pixel กลาย
    # เป็น masked (รู) ทำให้ heatmap มีช่องโหว่ และ top-locations หล่นจุดเหล่านั้นทิ้ง
    ndvi_deficit = (ee.Image.constant(0.3).subtract(ndvi)
                    .divide(0.3).clamp(0, 1).unmask(0).rename('ndvi_deficit'))

    # ── 2. LST (relative heat anomaly) ──────────────────────────
    lst_col = get_lst_col(geom, year)
    lst = lst_col.median().select('LST').rename('LST')
    # anomaly = LST − ค่าเฉลี่ยพื้นที่ → normalize ด้วย LST_ANOMALY_SPREAD
    # pixel ร้อนกว่าเฉลี่ย +spread → 1, เย็นกว่าเฉลี่ย/เท่าเฉลี่ย → 0
    # mean เป็น ee.Number lazy (ไม่ getInfo เพิ่ม — รวมใน image math)
    lst_mean_region = ee.Number(lst.reduceRegion(
        reducer=ee.Reducer.mean(), geometry=geom, scale=200,
        maxPixels=1e10, bestEffort=True).get('LST'))
    lst_heat = (lst.subtract(lst_mean_region).divide(LST_ANOMALY_SPREAD)
                .clamp(0, 1).unmask(0).rename('lst_heat'))

    # ── 3. Population (WorldPop) ────────────────────────────────
    pop = worldpop_pop_collection(WORLDPOP_YEAR).first()
    pop_img = ee.Image(pop).select('population').unmask(0)
    # Normalize ด้วย log base 1000 — สูตรคือ ln(pop+1) / ln(1000)
    # ผลลัพธ์: pop=1 → 0, pop=1000 → 1, ตัดที่ [0,1]
    # เลือก log แทน linear เพราะ population ทั่วไทยเหลื่อมหลาย order of magnitude
    pop_need = (pop_img.add(1).log().divide(ee.Number(1000).log())
                .clamp(0, 1).rename('pop_need'))

    # ── 4. Accessibility / equity (ระยะถึงพื้นที่สีเขียวเดิม) ────
    # ไกลจากต้นไม้เดิม = เข้าถึงพื้นที่สีเขียวยาก → ควรปลูกก่อน (equity)
    access_need = access_need_image(geom)

    # ── 5. Peri-urban cooling opportunity (Moukomla et al. 2026) ─
    # โอกาสลดความร้อนสูงสุดที่ขอบเมืองกำลังขยาย (ISA ปานกลาง) — ดู W_PERI ด้านบน
    peri_need = peri_urban_need_image(geom, year)

    # ── 6. Weighted Priority Score ──────────────────────────────
    # 4 ปัจจัยผู้ใช้ (w_* normalize รวม 1.0) กินสัดส่วน (1 − W_PERI) · peri_need เป็นปัจจัย
    # คงที่จากงานวิจัย · additive — ไม่ลดมิติ/ความคมของปัจจัยเดิม แค่เพิ่ม slice ใหม่ W_PERI
    base4 = (ndvi_deficit.multiply(w_ndvi)
             .add(lst_heat.multiply(w_lst))
             .add(pop_need.multiply(w_pop))
             .add(access_need.multiply(w_access)))
    priority = (base4.multiply(1.0 - W_PERI)
                .add(peri_need.multiply(W_PERI))
                .rename('priority')
                .clip(geom))

    # ── 7. Plantability mask ────────────────────────────────────
    # ส่ง mask แยกออกมา (ไม่ mask ตัว priority) ให้ top-locations + plantable-area
    # กรองจุดที่ปลูกได้จริง · lazy ee.Image — ไม่ถูก evaluate จนกว่าจะถูกใช้
    plantable = plantable_mask(geom)

    # ── 8. Land use tag (ไม่ใช่ปัจจัยคะแนน) ─────────────────────
    # ประเภทการใช้ที่ดิน 1–5 (นิยาม LDD จาก Dynamic World — ดู landuse.py) sample
    # ที่จุด top-locations เพื่ออธิบายว่าจุดแนะนำอยู่บนพื้นที่แบบไหน · unmask(0)
    # (0 = ไม่ทราบ) กัน pixel ที่ DW ขาดทำจุด sample หลุดทั้งแถวจาก dropNulls
    landuse = landuse_image(geom, year).unmask(0)

    return (priority, ndvi_deficit, lst_heat, pop_need, access_need, peri_need,
            plantable, landuse)


# ── Top-locations sampling ───────────────────────────────────────────────────
# "Top N จุด" ต้องเป็น pixel priority สูงสุด *จริง* ของพื้นที่ ไม่ใช่ของ sample สุ่ม
# เดิม: sample(numPixels=2000) สุ่มทั่ว geom แล้วค่อย sort → จังหวัดใหญ่ (หลายแสน
# pixel ที่ 200 m) สุ่มไม่โดน hotspot จริง + ไม่มี seed = ผลต่างกันทุกครั้ง
# แก้: หา threshold ที่เปอร์เซ็นไทล์สูง (เฉพาะ plantable) ก่อน → mask เหลือเฉพาะโซน
# priority สูงสุด แล้วทุ่ม sample ลงตรงนั้น → จับ pixel สูงสุดจริงได้แม่นขึ้นมาก ·
# พื้นที่เล็ก (numPixels > จำนวน pixel) จะ sample ได้เกือบครบ = เกือบ exhaustive ·
# ใส่ seed คงที่ → top_locations ซ้ำได้ (deterministic)
TOP_SAMPLE_PERCENTILE = 85    # คัดเฉพาะ priority เปอร์เซ็นไทล์ ≥ นี้ (top 15% ของ plantable)
TOP_SAMPLE_NUM_PIXELS = 5000  # งบ sample หลัง mask โซน hotspot (เดิม 2000 ทั่วทั้ง geom)
TOP_SAMPLE_SEED = 42          # คงที่ → ผลซ้ำได้ทุกครั้ง

# Top-N ต้อง "กระจายตัว" ไม่กระจุกซ้อนกันใน hotspot เดียว — เดิม sort priority แล้ว
# limit(n) ตรง ๆ ทำให้ได้ pixel คะแนนสูงสุดที่มักติดกัน → หมุดทับกันบนแผนที่ + แนะนำ
# ปลูกย่านเดิมซ้ำ ๆ · แก้: ดึง candidate pool (เรียง priority) มามากกว่า n แล้วเลือก
# แบบ greedy ให้แต่ละจุดห่างกัน ≥ TOP_MIN_SEPARATION_M (เลือกตามลำดับคะแนน → ยังได้
# จุดคะแนนสูงก่อน แค่ข้ามจุดที่ใกล้จุดที่เลือกไปแล้ว) · ไม่แตะสูตรคะแนน/ปัจจัยเลย
TOP_MIN_SEPARATION_M = 750    # ระยะห่างขั้นต่ำระหว่างจุดแนะนำ (เมตร) — ~ระดับย่าน/ตำบลเมือง
TOP_CANDIDATE_POOL = 300      # จำนวน pixel คะแนนสูงสุดที่ดึงมาคัดระยะห่าง (>> n)


def _haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """ระยะทางโดยประมาณ (เมตร) ระหว่างสองพิกัด lat/lng (องศา) — great-circle.
    ใช้คัดจุดแนะนำไม่ให้กระจุกกัน · แม่นพอสำหรับระยะ < ไม่กี่สิบกิโลเมตรในไทย"""
    r = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lng2 - lng1)
    a = (math.sin(dphi / 2) ** 2
         + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2)
    return 2 * r * math.asin(math.sqrt(a))


def _space_out(candidates: list[dict], n: int, min_sep_m: float) -> list[dict]:
    """เลือกสูงสุด n จุดจาก candidates (ต้องเรียง priority มาก→น้อยมาแล้ว) โดยให้แต่ละ
    จุดห่างจุดที่เลือกไปแล้วทุกจุด ≥ min_sep_m → หมุดไม่กระจุกซ้อนกัน.

    Greedy ตามลำดับคะแนน: จุดคะแนนสูงถูกเลือกก่อน, ข้ามจุดที่ใกล้จุดที่เลือกแล้ว ·
    ถ้ากระจายแล้วได้ไม่ครบ n (พื้นที่เล็ก/hotspot กระจุกมาก) เติมจุดคะแนนสูงสุดที่
    เหลือจนครบ — รับประกันได้ n จุดเสมอ (ไม่ด้อยกว่าพฤติกรรมเดิม) แต่ให้การกระจายก่อน"""
    selected: list[dict] = []
    for c in candidates:
        if all(_haversine_m(c['lat'], c['lng'], s['lat'], s['lng']) >= min_sep_m
               for s in selected):
            selected.append(c)
            if len(selected) >= n:
                return selected
    # เติมจุดที่เหลือ (คะแนนสูงสุดก่อน) ถ้าระยะห่างทำให้ได้ไม่ครบ n
    if len(selected) < n:
        picked = {id(s) for s in selected}
        for c in candidates:
            if id(c) not in picked:
                selected.append(c)
                if len(selected) >= n:
                    break
    return selected[:n]


def get_top_locations(priority: ee.Image, ndvi_deficit: ee.Image,
                      lst_heat: ee.Image, pop_need: ee.Image, access_need: ee.Image,
                      peri_need: ee.Image,
                      geom: ee.Geometry, plantable: ee.Image, n: int = 10,
                      landuse: ee.Image | None = None):
    """หา top-n pixels ที่มี priority สูงสุด — เฉพาะบนพื้นที่ที่ปลูกได้จริง.

    sample แบบ multi-band (priority + 5 องค์ประกอบ) ที่จุดเดียวกัน → คืน `factors`
    ของแต่ละจุด (ขาดต้นไม้/ร้อน/คนหนาแน่น/เข้าถึงสีเขียวยาก/ขอบเมืองลดร้อนคุ้ม) เพื่ออธิบายว่า "ทำไม" จุดนี้
    คะแนนสูง · updateMask(plantable) ก่อน sample → ไม่คืนจุดบนน้ำ/อาคาร/ป่าเดิม/ที่ชัน

    landuse (optional): band ประเภทการใช้ที่ดิน 1–5 (unmask(0) มาแล้ว — ดู
    compute_priority ขั้น 8) sample ที่จุดเดียวกัน → ติดป้าย `landuse` ต่อจุด
    (code + ชื่อไทย) · เป็น descriptor ล้วน ไม่กระทบคะแนน/การเลือกจุด

    คัด priority เปอร์เซ็นไทล์สูง (TOP_SAMPLE_PERCENTILE) เฉพาะ plantable ก่อน sample
    เพื่อทุ่ม budget ลงโซน hotspot จริง — เดิมสุ่มทั่ว geom ทำให้จังหวัดใหญ่พลาด pixel
    สูงสุด (ดู comment บล็อกด้านบน)

    จากนั้นดึง candidate pool (เรียง priority) แล้ว _space_out ให้ n จุดสุดท้ายห่างกัน
    ≥ TOP_MIN_SEPARATION_M → หมุดไม่กระจุกซ้อนกัน
    """
    # priority เฉพาะ pixel ที่ปลูกได้ — reduceRegion ข้าม pixel ที่ถูก mask อยู่แล้ว
    # → percentile คิดบน distribution ของ "ที่ปลูกได้" เท่านั้น (ไม่ปนน้ำ/อาคาร/ป่าเดิม)
    plantable_priority = priority.updateMask(plantable)
    # threshold เป็น ee.Number lazy — fuse เข้า getInfo ก้อนเดียว ไม่เพิ่ม roundtrip ·
    # null (ไม่มี pixel plantable เลย) → fallback 0 = ไม่ threshold (priority ≥ 0 เสมอ)
    p_thresh = plantable_priority.reduceRegion(
        reducer=ee.Reducer.percentile([TOP_SAMPLE_PERCENTILE]),
        geometry=geom, scale=200, maxPixels=1e10, bestEffort=True).get('priority')
    p_thresh = ee.Number(ee.Algorithms.If(p_thresh, p_thresh, 0))

    stack = priority.addBands([ndvi_deficit, lst_heat, pop_need, access_need, peri_need])
    if landuse is not None:
        stack = stack.addBands(landuse)
    # gte() สืบ mask ของ plantable_priority มาด้วย → updateMask ตัดทั้ง non-plantable
    # และ pixel ที่ต่ำกว่า threshold ในคราวเดียว เหลือเฉพาะโซน hotspot ที่ปลูกได้
    hotspots = stack.updateMask(plantable_priority.gte(p_thresh))
    # ดึง candidate pool (เรียง priority มาก→น้อย) มามากกว่า n เพื่อมีตัวเลือกพอให้คัด
    # ระยะห่าง — limit เดิมที่ n ทำให้ได้แต่ pixel สูงสุดที่ติดกัน (หมุดกระจุก)
    samples = (hotspots
               .sample(region=geom, scale=200, numPixels=TOP_SAMPLE_NUM_PIXELS,
                       seed=TOP_SAMPLE_SEED, geometries=True, dropNulls=True)
               .sort('priority', False)
               .limit(TOP_CANDIDATE_POOL))
    info = samples.getInfo()
    candidates = []
    for feat in info.get('features', []):
        coords = feat['geometry']['coordinates']
        p = feat['properties']
        entry = {
            'lng': round(coords[0], 5),
            'lat': round(coords[1], 5),
            'score': round(float(p.get('priority', 0)), 3),
            'factors': {
                'ndvi_deficit': round(float(p.get('ndvi_deficit', 0)), 2),
                'lst_heat': round(float(p.get('lst_heat', 0)), 2),
                'pop_need': round(float(p.get('pop_need', 0)), 2),
                'access_need': round(float(p.get('access_need', 0)), 2),
                'peri_urban': round(float(p.get('peri_need', 0)), 2),
            },
        }
        # ประเภทการใช้ที่ดินที่จุดนี้ — 0 (ไม่ทราบ/DW ขาด) ไม่ใส่ป้าย
        cat = CATEGORY_BY_VALUE.get(int(p.get('landuse') or 0))
        if cat is not None:
            entry['landuse'] = {'code': cat['code'], 'name_th': cat['name_th']}
        candidates.append(entry)
    # candidates เรียงตาม priority มาแล้ว → คัดให้กระจาย ≥ TOP_MIN_SEPARATION_M
    return _space_out(candidates, n, TOP_MIN_SEPARATION_M)


def compute_plantable_area_m2(priority: ee.Image, plantable: ee.Image,
                              geom: ee.Geometry) -> float:
    """รวม pixel area ที่ priority > threshold *และ* ปลูกได้จริง (plantable) =
    "ที่ควรปลูกจริง" สำหรับ impact projection — ตัดน้ำ/อาคาร/ป่าเดิมออกแล้ว.
    ใช้ scale 100m balance ระหว่างความเร็วและความแม่น (priority ก็คำนวณที่ ~100m เช่นกัน)"""
    high_priority = priority.gt(IMPACT_DEFAULTS["priority_threshold"]).And(plantable)
    area_m2 = (ee.Image.pixelArea().updateMask(high_priority)
               .reduceRegion(reducer=ee.Reducer.sum(), geometry=geom,
                             scale=100, maxPixels=1e10, bestEffort=True)
               .get('area').getInfo())
    return float(area_m2 or 0)


def get_heatmap_url(priority: ee.Image) -> str:
    """ขอ XYZ tile URL จาก GEE สำหรับแสดงเป็น heatmap layer.

    หมายเหตุ: URL ผูกกับ session token ของ GEE และจะหมดอายุภายในไม่กี่ชั่วโมง/วัน
    จึงต้องเรียก getMapId ใหม่ทุกครั้งที่ส่งคำตอบให้ client (ห้าม cache URL ลง DB)
    """
    vis = {
        'min': 0.2, 'max': 0.85,
        'palette': ['1a9850', 'a6d96a', 'ffffbf', 'fdae61', 'd73027'],
    }
    map_id = priority.getMapId(vis)
    return map_id['tile_fetcher'].url_format
