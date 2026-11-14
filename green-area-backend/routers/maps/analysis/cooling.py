"""NDVI ↔ LST cooling relationship — quantify vegetation's surface-cooling effect.

อ่าน NDVI + LST รายอำเภอจาก cache (ปีเดียว) จับคู่ต่ออำเภอ แล้ว fit เส้นถดถอย
    LST = slope·NDVI + intercept
slope < 0 = ยิ่งเขียวยิ่งเย็น (urban cooling gradient) — เป็นหลักฐานเชิงประจักษ์
ของวิทยานิพนธ์ว่า "เพิ่มพืชพรรณ → ลดอุณหภูมิผิวเมือง"

ไม่ trigger GEE — ใช้ cached district rows เหมือน /analysis/districts จึงตอบไว
และ test ได้โดยไม่แตะ external service
"""
import math

from fastapi import APIRouter

from dependencies import (supa_call, ensure_province, resolve_year,
                          OptionalYearParam, DISTRICT_GEOMETRIES)
from stats_utils import linregress

router = APIRouter()

# เกณฑ์ขั้นต่ำก่อนจะคืนความชัน — ต้องผ่านทั้งสองข้อ
#   1) อย่างน้อย 10 อำเภอ: ต่ำกว่านี้เส้นตรงพลิกทิศได้ด้วยความบังเอิญว่าอำเภอไหนมีข้อมูล
#      (ตรวจจริง 13 ก.ย. 2569: กรุงเทพฯ ปี 2026 มี 5 อำเภอ ได้ +11.3 °C/NDVI ขณะที่
#      ปี 2025 ครบ 50 อำเภอ ได้ −7.47)
#   2) อย่างน้อยครึ่งหนึ่งของอำเภอทั้งจังหวัด: กันกรณีได้แต่อำเภอที่อยู่ติดกันกลุ่มเดียว
#      ซึ่งไม่เป็นตัวแทนของทั้งจังหวัด
# จังหวัดที่มีไม่ถึง 10 อำเภอ (38 จาก 77 จังหวัด) จึงไม่มีความชันเลยไม่ว่าปีไหน —
# เจ้าของโครงการเลือกแบบนี้เอง (14 พ.ย. 2569) แทนการลดเกณฑ์ให้จังหวัดเล็ก
MIN_DISTRICTS_FOR_SLOPE = 10
MIN_DISTRICT_COVERAGE = 0.5


def required_districts(total: int) -> int:
    """จำนวนอำเภอขั้นต่ำที่ต้องมีทั้ง NDVI และ LST ก่อนจะคืนความชัน"""
    return max(MIN_DISTRICTS_FOR_SLOPE, math.ceil(total * MIN_DISTRICT_COVERAGE))


def _province_district_count(province_name: str) -> int:
    return sum(1 for (p, _d) in DISTRICT_GEOMETRIES if p == province_name)


def _points_by_year(ndvi_rows: list[dict], lst_rows: list[dict]) -> dict[int, list[dict]]:
    """จับคู่ NDVI กับ LST ของอำเภอเดียวกันในปีเดียวกัน — อำเภอที่ขาดค่าใดค่าหนึ่งตัดทิ้ง"""
    lst = {(r["year"], r["district"]): r.get("lst_mean") for r in lst_rows}
    by_year: dict[int, dict[str, dict]] = {}
    for r in ndvi_rows:
        ndvi, t = r.get("ndvi_mean"), lst.get((r["year"], r["district"]))
        if ndvi is not None and t is not None:
            # dict ต่ออำเภอ — ถ้า cache มีแถวซ้ำ (เคยเกิดจริง) ให้นับอำเภอละครั้ง
            by_year.setdefault(r["year"], {})[r["district"]] = {
                "district": r["district"], "ndvi": ndvi, "lst": t}
    return {y: sorted(d.values(), key=lambda p: p["ndvi"]) for y, d in by_year.items()}


def _interpret(fit: dict | None, *, year: int, n: int, total: int, required: int,
               latest_sufficient_year: int | None) -> str:
    if total < MIN_DISTRICTS_FOR_SLOPE:
        return (f"จังหวัดนี้มี {total} อำเภอ น้อยกว่า {MIN_DISTRICTS_FOR_SLOPE} อำเภอที่ต้องใช้"
                "ในการหาความสัมพันธ์ระหว่างความเขียวกับอุณหภูมิผิวระดับอำเภอ "
                "ระบบจึงไม่คำนวณความชัน จุดบนกราฟคือค่าจริงของแต่ละอำเภอ")
    if fit is None:
        msg = (f"ปี {year} มีอำเภอที่มีข้อมูลครบทั้ง NDVI และ LST {n} จาก {total} อำเภอ "
               f"ต้องมีอย่างน้อย {required} อำเภอจึงจะคำนวณความชันได้ "
               "ถ้าคำนวณจากอำเภอที่มีอยู่ ผลอาจกลับทิศได้ด้วยความบังเอิญ")
        if latest_sufficient_year is not None and latest_sufficient_year != year:
            msg += f" ส่วนปี {latest_sufficient_year} มีข้อมูลพอ ลองเลือกปีนั้นแทน"
        return msg
    slope, r2 = fit["slope"], fit["r2"]
    if slope < 0:
        strength = "ชัดเจน" if r2 >= 0.5 else "ปานกลาง" if r2 >= 0.25 else "อ่อน"
        # slope = °C ต่อ NDVI 1 หน่วย → ต่อ NDVI 0.1 = slope·0.1
        return (f"พบความสัมพันธ์เชิงลบ ({strength}, R²={r2:.2f}, n={n} อำเภอ) — "
                f"NDVI ที่สูงขึ้น 0.1 สัมพันธ์กับอุณหภูมิผิวที่ต่ำลง "
                f"~{abs(slope) * 0.1:.1f}°C โดยเฉลี่ยระหว่างอำเภอ")
    return (f"ความชันเป็นบวก (R²={r2:.2f}, n={n} อำเภอ) — ไม่พบ cooling effect ตามที่คาด "
            "อาจเพราะพื้นที่เป็นเขตเมืองเกือบทั้งหมด หรือมีปัจจัยอื่นที่มีผลต่ออุณหภูมิมากกว่า")


@router.get("/analysis/cooling/{province_name}")
def get_cooling_analysis(province_name: str, year: OptionalYearParam = None):
    """Regression ของ LST ต่อ NDVI ระดับอำเภอ — วัด cooling effect ของพืชพรรณ.

    คืน scatter points (ndvi, lst ต่ออำเภอ) + regression (slope/r/r²) + คำอธิบายไทย
    `regression` เป็น null เมื่อจำนวนอำเภอไม่ถึง `required_districts` — จุดยังคืนครบ
    ไม่ระบุ year = ปีล่าสุดที่ข้อมูลพอ (`latest_sufficient_year`) ถ้าไม่มีเลยใช้ปีปัจจุบัน
    """
    ensure_province(province_name)

    # ดึงทุกปีของจังหวัดเดียวในครั้งเดียว (≤ 50 อำเภอ × ไม่กี่ปี) เพื่อหาปีล่าสุดที่ข้อมูลพอ
    ndvi_rows = supa_call(lambda s: s.table("district_ndvi_annual")
        .select("district,year,ndvi_mean")
        .eq("province", province_name).execute()).data
    lst_rows = supa_call(lambda s: s.table("district_lst_annual")
        .select("district,year,lst_mean")
        .eq("province", province_name).execute()).data

    by_year = _points_by_year(ndvi_rows, lst_rows)
    total = _province_district_count(province_name)
    required = required_districts(total)
    sufficient_years = [y for y, pts in by_year.items() if len(pts) >= required]
    latest_sufficient_year = max(sufficient_years) if sufficient_years else None

    if year is None:
        year = latest_sufficient_year if latest_sufficient_year is not None else resolve_year(None)
    points = by_year.get(year, [])
    sufficient = total >= MIN_DISTRICTS_FOR_SLOPE and len(points) >= required
    fit = (linregress([p["ndvi"] for p in points], [p["lst"] for p in points])
           if sufficient else None)

    return {
        "province": province_name,
        "year": year,
        "n_districts": len(points),
        "total_districts": total,
        "required_districts": required,
        "sufficient": fit is not None,
        "latest_sufficient_year": latest_sufficient_year,
        "points": points,
        "regression": fit,
        "interpretation": _interpret(
            fit, year=year, n=len(points), total=total, required=required,
            latest_sufficient_year=latest_sufficient_year),
    }
