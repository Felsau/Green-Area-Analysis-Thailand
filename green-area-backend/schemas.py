"""Pydantic response models — เปิด /docs จะเห็น schema ตรงตามนี้
ใช้กับ openapi-typescript สร้าง type frontend ได้ตรงข้าม API boundary"""
from typing import Optional
from pydantic import BaseModel, Field


# ── NDVI ─────────────────────────────────────────────────────────────────────
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
    from_cache: bool


class NDVIMonthlyResponse(BaseModel):
    province: str
    year: int
    monthly: list[MonthlyNDVIPoint]
    from_cache: bool


# ── LST ──────────────────────────────────────────────────────────────────────
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


# ── Ranking ──────────────────────────────────────────────────────────────────
class RankingRow(BaseModel):
    province: str
    rank: int
    ndvi_mean: Optional[float] = None
    green_area_pct: Optional[float] = None
    green_area_km2: Optional[float] = None
    green_area_m2_per_person: Optional[float] = None
    who_status: Optional[str] = None
    population: Optional[int] = None
    total_area_km2: Optional[float] = None
    deficit_m2_per_person: Optional[float] = None
    deficit_km2: Optional[float] = None


class RankingResponse(BaseModel):
    year: int
    total_cached: int
    who_pass_count: int
    who_fail_count: int
    data: list[RankingRow]


# ── Custom area (user-drawn polygon) ─────────────────────────────────────────
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


# ── Timelapse ────────────────────────────────────────────────────────────────
class TimelapseResponse(BaseModel):
    """ค่า annual (NDVI หรือ LST) ของทุกจังหวัด ใน range ที่กำหนด — เล่นเป็น
    animation บนแผนที่ · data['Bangkok']['2020'] = 0.42 (อาจ missing บางปีถ้ายัง
    ไม่ compute) · main.py skip row ที่ value เป็น None แล้ว — float เสมอ"""
    start_year: int
    end_year: int
    years: list[int]
    province_count: int
    data: dict[str, dict[str, float]]
