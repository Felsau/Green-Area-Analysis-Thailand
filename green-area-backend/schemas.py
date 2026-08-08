"""Pydantic response models — เปิด /docs จะเห็น schema ตรงตามนี้
ใช้กับ openapi-typescript สร้าง type frontend ได้ตรงข้าม API boundary"""
from typing import Optional
from pydantic import BaseModel, Field


# NDVI
class MonthlyNDVIPoint(BaseModel):
    month: str
    month_num: int = Field(ge=1, le=12)
    ndvi: Optional[float] = None
    image_count: Optional[int] = 0


class NDVIDataQuality(BaseModel):
    """คุณภาพ/ความไม่แน่นอนของ median composite ที่ใช้คำนวณ NDVI (NFR-07).

    สร้างใน routers/ndvi/compute.py::build_data_quality · เก็บลง cache เป็น jsonb
    เกณฑ์ตัดระดับ = GCOS-245 (FAPAR: 2σ ≤ 5% Goal / ≤ 10% Threshold) ·
    ฤดูกาลตามนิยามกรมอุตุนิยมวิทยา
    """
    image_count: int                      # จำนวนภาพ Sentinel-2 ที่เข้า composite
    cloud_filter_pct: int                 # เกณฑ์เมฆที่ใช้ (20 ปกติ · 80 = fallback)
    clear_obs_mean: float                 # observation ปลอดเมฆเฉลี่ยต่อ pixel
    clear_obs_min: int                    # pixel ที่แย่ที่สุดในพื้นที่
    ndvi_sd_mean: float = 0               # σ ของ NDVI รายภาพตลอดปี (เฉลี่ยทั้งพื้นที่)
    uncertainty: Optional[float] = None   # u (1σ) ของค่ากลางรายปี หน่วย NDVI
    uncertainty_2sigma_pct: Optional[float] = None   # 2σ คิดเป็น % ของค่า NDVI
    first_date: Optional[str] = None      # วันที่ภาพแรก (YYYY-MM-DD)
    last_date: Optional[str] = None
    months_covered: int = 0               # จำนวนเดือนที่มีภาพ
    months_missing: list[int] = []        # เลขเดือนที่ไม่มีภาพเลย
    seasons_covered: list[str] = []       # ฤดู (TMD) ที่มีภาพ
    seasons_missing: list[str] = []
    seasonally_representative: bool = False   # มีภาพครบทั้ง 3 ฤดูหรือไม่
    level: str                            # goal | threshold | below | none
    label: str                            # ป้ายภาษาไทยของ level
    note: str                             # ข้อความอธิบายพร้อมแสดง/ลงรายงาน


class CanopyTrend(BaseModel):
    """แนวโน้มเรือนยอดจาก Dynamic World เทียบปีฐาน — อ่านเฉพาะ *ทิศทาง* ไม่ใช่ระดับ.

    DW ตรวจไม่เจอเรือนยอดในพื้นที่เมือง (pixel ที่ปนอาคารถูกจำแนกเป็นสิ่งปลูกสร้าง)
    ระดับจึงต่ำกว่าค่าหลักของ WorldCover มาก แต่เพราะวัดด้วยวิธีเดียวกันทั้งสองปี
    ผลต่างระหว่างปียังใช้อ่านทิศทางได้ (ดูตารางเทียบใน canopy.py)
    """
    source: str
    year: int
    baseline_year: int
    canopy_pct: float                     # ค่าที่ DW วัดได้ปีนั้น (ต่ำกว่าจริงในเมือง)
    baseline_pct: float
    change_pp: float                      # เปลี่ยนไปกี่จุดเปอร์เซ็นต์เทียบปีฐาน
    direction: str                        # increase | decrease | stable
    coverage_pct: float                   # % พื้นที่ที่ปีนั้นมีภาพ DW
    note: str


class CanopyCover(BaseModel):
    """เรือนยอดไม้ปกคลุมเทียบเกณฑ์ 30% ของกฎ 3-30-300 (FR-17).

    สร้างใน canopy.py::build_canopy · เก็บลง cache เป็น jsonb (migration 015)
    ต่างจาก green_area_pct ซึ่งเป็น "พืชพรรณทุกชนิด" จาก NDVI — ตัวนี้นับเฉพาะ
    คลาสต้นไม้จากการจำแนก land cover จึงตอบเกณฑ์ 30% ได้ตรงกว่า

    ค่าหลักมาจาก ESA WorldCover ที่มี epoch เดียว (2021) — *ไม่ขยับตามปีที่เลือก*
    ต้องแสดง epoch_year คู่กับตัวเลขเสมอ ส่วนการเปลี่ยนแปลงรายปีอยู่ใน trend
    """
    available: bool
    canopy_pct: Optional[float] = None
    canopy_km2: Optional[float] = None
    target_pct: float                     # 30.0 ตาม [R2]
    meets_target: Optional[bool] = None
    gap_pct: Optional[float] = None       # ขาดอีกกี่จุด% ถึงเกณฑ์ (0 เมื่อผ่านแล้ว)
    source: str
    epoch_year: int                       # ปีของข้อมูล WorldCover (2021)
    epoch_offset_years: int               # ปีที่เลือก ห่างจากปีข้อมูลเท่าไร
    trend: Optional[CanopyTrend] = None
    label: str
    note: str


class ValidationClassContribution(BaseModel):
    """ส่วนร่วมของคลาส WorldCover หนึ่งคลาสต่อความต่างรวม (NFR-08)."""
    code: int                             # รหัสคลาส ESA WorldCover (10, 40, 50, ...)
    name: str
    kind: str                             # false_negative | false_positive
    pp: float                             # กี่จุด% ของพื้นที่ทั้งหมด


class ValidationBreakdown(BaseModel):
    """แยกความต่างออกตามคลาสที่เป็นต้นเหตุ — กระทบยอดกับ error_pp ได้ครบ.

        error_pp = net_pp + reference_scale_delta_pp
    """
    false_negative_pp: float              # WorldCover ว่าเขียว แต่ NDVI ว่าไม่เขียว
    false_positive_pp: float              # NDVI ว่าเขียว แต่ WorldCover ว่าไม่เขียว
    net_pp: float                         # false_positive − false_negative
    reference_scale_delta_pp: Optional[float] = None   # ผลของ pyramid MODE
    by_class: list[ValidationClassContribution] = []
    dominant: Optional[ValidationClassContribution] = None


class GreenAreaValidation(BaseModel):
    """ผลตรวจสอบความถูกต้องของ green_area_pct เทียบ ESA WorldCover (NFR-08).

    สร้างใน validation.py::build_validation · เก็บลง cache เป็น jsonb (migration 016)
    ระดับจังหวัดเท่านั้น · ค่าอ้างอิงมาจาก provinces.worldcover_green_pct ที่ backfill ไว้

    ความต่างที่พบเป็นเรื่องของ *นิยาม* ไม่ใช่ความผิดพลาดของการวัด — NDVI วัดพืชพรรณ
    ที่เขียวจริงในช่วงเวลานั้น ส่วน WorldCover วัดประเภทการใช้ที่ดิน (ดู §5.1 ของ
    REQUIREMENTS.md สำหรับผลวัดจริงทั้ง 77 จังหวัด)
    """
    available: bool
    ndvi_green_pct: Optional[float] = None
    worldcover_green_pct: Optional[float] = None
    error_pp: Optional[float] = None      # NDVI − WorldCover (จุด%)
    target_pp: float                      # 10.0 ตาม NFR-08
    within_target: Optional[bool] = None
    year: int
    worldcover_epoch_year: int            # 2021 — ค่าอ้างอิงไม่ขยับตามปีที่เลือก
    breakdown: Optional[ValidationBreakdown] = None
    note: str


class NDVIResponse(BaseModel):
    province: str
    year: int
    ndvi_mean: Optional[float] = None
    ndvi_min: Optional[float] = None
    ndvi_max: Optional[float] = None
    green_area_pct: Optional[float] = None
    green_area_km2: Optional[float] = None
    dense_area_pct: Optional[float] = None
    dense_area_km2: Optional[float] = None
    total_area_km2: Optional[float] = None
    green_area_m2_per_person: Optional[float] = None
    population: Optional[int] = None
    population_year: Optional[int] = None   # ปีของข้อมูลประชากร — อาจต่างจาก year ถ้า fallback
    who_status: Optional[str] = None
    data_quality: Optional[NDVIDataQuality] = None
    canopy: Optional[CanopyCover] = None
    validation: Optional[GreenAreaValidation] = None
    from_cache: bool


class NDVIMonthlyResponse(BaseModel):
    province: str
    year: int
    monthly: list[MonthlyNDVIPoint]
    from_cache: bool


# LST
class MonthlyLSTPoint(BaseModel):
    month: str
    month_num: int = Field(ge=1, le=12)
    lst: Optional[float] = None
    image_count: Optional[int] = 0


class LSTResponse(BaseModel):
    province: str
    year: int
    lst_mean: Optional[float] = None
    lst_min: Optional[float] = None
    lst_max: Optional[float] = None
    from_cache: bool


class LSTMonthlyResponse(BaseModel):
    province: str
    year: int
    monthly: list[MonthlyLSTPoint]
    from_cache: bool


# Ranking
# ค่าจาก urban_ndvi_annual (เขต built-up) ไม่ใช่ ndvi_annual ทั้งจังหวัด — ดูเหตุผลใน
# main.py::get_ranking
class RankingRow(BaseModel):
    province: str
    rank: int
    ndvi_mean_urban: Optional[float] = None
    green_share_in_urban_pct: Optional[float] = None
    green_in_urban_km2: Optional[float] = None
    urban_area_km2: Optional[float] = None
    population_urban: Optional[int] = None
    m2_per_person_urban: Optional[float] = None


class RankingResponse(BaseModel):
    year: int
    total_cached: int
    # จำนวนจังหวัดที่อยู่เหนือ/ใต้ค่าอ้างอิง WHO — ชื่อฟิลด์เลี่ยงคำว่า pass/fail ตั้งใจ
    above_who_reference_count: int
    below_who_reference_count: int
    data: list[RankingRow]


# Custom area (user-drawn polygon)
class CustomAreaResponse(BaseModel):
    """ผลวิเคราะห์ polygon ที่ผู้ใช้วาดเอง — NDVI/พื้นที่สีเขียว/ประชากร/LST.
    ประชากรมาจาก WorldPop sum ภายในพื้นที่จริง (ไม่ใช่ค่าทั้งจังหวัด)"""
    year: int
    area_km2: float
    ndvi_mean: Optional[float] = None
    ndvi_min: Optional[float] = None
    ndvi_max: Optional[float] = None
    green_area_pct: Optional[float] = None
    green_area_km2: Optional[float] = None
    dense_area_pct: Optional[float] = None
    dense_area_km2: Optional[float] = None
    total_area_km2: Optional[float] = None
    population: Optional[int] = None
    green_area_m2_per_person: Optional[float] = None
    who_status: Optional[str] = None
    lst_mean: Optional[float] = None
    lst_min: Optional[float] = None
    lst_max: Optional[float] = None
    data_quality: Optional[NDVIDataQuality] = None
    worldpop_year: int


# Timelapse
class TimelapseResponse(BaseModel):
    """ค่า annual (NDVI หรือ LST) ของทุกจังหวัด ใน range ที่กำหนด — เล่นเป็น
    animation บนแผนที่ · data['Bangkok']['2020'] = 0.42 (อาจ missing บางปีถ้ายัง
    ไม่ compute) · main.py skip row ที่ value เป็น None แล้ว — float เสมอ"""
    start_year: int
    end_year: int
    years: list[int]
    province_count: int
    data: dict[str, dict[str, float]]
