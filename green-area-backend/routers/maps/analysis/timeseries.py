"""Time-series (Phase B-2) — multi-year NDVI+LST trend จาก cached annual rows."""
from fastapi import APIRouter, HTTPException

from dependencies import (supa_call, gather, ensure_province, ensure_district,
                          resolve_year, OptionalYearParam)
from stats_utils import forecast_linear, mann_kendall

router = APIRouter()


@router.get("/analysis/timeseries/{province_name}")
def get_timeseries(province_name: str,
                   start_year: OptionalYearParam = None,
                   end_year: OptionalYearParam = None,
                   district_name: str | None = None):
    """ดึง NDVI + LST รายปี (annual) ย้อนหลังจาก cache เพื่อแสดงแนวโน้ม.

    เฉพาะปีที่มี cached row เท่านั้น — ไม่ trigger GEE compute ใหม่ เพื่อให้ response ไว.
    ถ้า district_name ระบุ → ดึง district_*_annual แทน

    start_year/end_year ไม่ระบุ = ปีปัจจุบัน−4 / ปีปัจจุบัน (คำนวณสดตอนเรียก ไม่ใช่ค่า
    ที่ตรึงไว้ตอน import — ดู resolve_year) ทั้งสองอิสระต่อกัน ไม่ได้ผูกกับอีกฝั่ง
    """
    now_year = resolve_year(None)
    if start_year is None:
        start_year = now_year - 4
    if end_year is None:
        end_year = now_year
    if district_name:
        ensure_district(province_name, district_name)
        ndvi_table, lst_table = "district_ndvi_annual", "district_lst_annual"
    else:
        ensure_province(province_name)
        ndvi_table, lst_table = "ndvi_annual", "province_lst_annual"

    if start_year > end_year:
        start_year, end_year = end_year, start_year
    year_range = list(range(start_year, end_year + 1))
    if not year_range:
        raise HTTPException(status_code=400, detail="ช่วงปีไม่ถูกต้อง")

    def _q(table, fields):
        def go(s):
            q = (s.table(table).select(fields)
                 .eq("province", province_name)
                 .in_("year", year_range))
            if district_name:
                q = q.eq("district", district_name)
            return q.execute()
        return supa_call(go).data

    # NDVI + LST เป็น query คนละตารางที่ไม่พึ่งกัน → ยิงขนาน ลด latency
    ndvi_rows, lst_rows = gather(
        lambda: _q(ndvi_table,
                   "year,ndvi_mean,ndvi_min,ndvi_max,green_area_pct,green_area_km2,green_area_m2_per_person"),
        lambda: _q(lst_table, "year,lst_mean,lst_min,lst_max"),
    )

    n_by_y = {r["year"]: r for r in ndvi_rows}
    l_by_y = {r["year"]: r for r in lst_rows}

    series = []
    for y in year_range:
        nrow, lrow = n_by_y.get(y), l_by_y.get(y)
        if not nrow and not lrow:
            continue
        series.append({
            "year": y,
            "ndvi_mean": nrow.get("ndvi_mean") if nrow else None,
            "ndvi_min": nrow.get("ndvi_min") if nrow else None,
            "ndvi_max": nrow.get("ndvi_max") if nrow else None,
            "green_area_pct": nrow.get("green_area_pct") if nrow else None,
            "green_area_km2": nrow.get("green_area_km2") if nrow else None,
            "green_area_m2_per_person": nrow.get("green_area_m2_per_person") if nrow else None,
            "lst_mean": lrow.get("lst_mean") if lrow else None,
            "lst_min": lrow.get("lst_min") if lrow else None,
            "lst_max": lrow.get("lst_max") if lrow else None,
        })

    # คำนวณ delta สรุป (จุดแรก → จุดสุดท้าย) ถ้ามีข้อมูลครบทั้งสองข้าง
    summary = {}
    valid_ndvi = [s for s in series if s.get("ndvi_mean") is not None]
    valid_lst = [s for s in series if s.get("lst_mean") is not None]
    if len(valid_ndvi) >= 2:
        first, last = valid_ndvi[0], valid_ndvi[-1]
        summary["ndvi_delta"] = round(last["ndvi_mean"] - first["ndvi_mean"], 4)
        summary["ndvi_first_year"] = first["year"]
        summary["ndvi_last_year"] = last["year"]
    if len(valid_lst) >= 2:
        first, last = valid_lst[0], valid_lst[-1]
        summary["lst_delta"] = round(last["lst_mean"] - first["lst_mean"], 2)
        summary["lst_first_year"] = first["year"]
        summary["lst_last_year"] = last["year"]

    # Mann-Kendall — ทดสอบว่าแนวโน้มมีนัยสำคัญทางสถิติไหม (ต้องมี >= 3 ปี)
    # เลี่ยงการ "เคลม" แนวโน้มจาก delta จุดแรก-จุดสุดท้ายเพียงอย่างเดียว
    mk_ndvi = mann_kendall([s["ndvi_mean"] for s in valid_ndvi])
    if mk_ndvi:
        summary["ndvi_trend"] = mk_ndvi
    mk_lst = mann_kendall([s["lst_mean"] for s in valid_lst])
    if mk_lst:
        summary["lst_trend"] = mk_lst

    # Forecast — OLS projection 3 ปีข้างหน้า + 95% prediction interval ต่อ metric
    # ใช้เฉพาะปีที่มีค่าจริง · ต้อง ≥ 3 จุด (ดูเงื่อนไขใน forecast_linear)
    valid_pct = [s for s in series if s.get("green_area_pct") is not None]
    forecast = {}
    for key, rows, clamp in (
        ("ndvi_mean", valid_ndvi, (-1.0, 1.0)),
        ("green_area_pct", valid_pct, (0.0, 100.0)),
        ("lst_mean", valid_lst, None),
    ):
        fc = forecast_linear([r["year"] for r in rows], [r[key] for r in rows],
                             horizon=3, clamp=clamp)
        if fc:
            forecast[key] = fc

    return {
        "province": province_name,
        "district": district_name,
        "start_year": start_year, "end_year": end_year,
        "years_with_data": len(series),
        "years_in_range": len(year_range),
        "data": series,
        "summary": summary,
        "forecast": forecast,
    }
