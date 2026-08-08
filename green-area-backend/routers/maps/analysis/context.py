"""National & regional context — ค่าเฉลี่ย + อันดับสำหรับเทียบกับจังหวัดที่เลือก."""
from fastapi import APIRouter

from dependencies import supa_call, ensure_province, CURRENT_YEAR, YearParam

router = APIRouter()


@router.get("/analysis/context/{province_name}")
def get_context(province_name: str, year: YearParam = CURRENT_YEAR):
    """ค่าเฉลี่ยของจังหวัดที่มี cache (ทั้งจังหวัด) + อันดับ m²/คน จาก urban subset

    สองส่วนนี้คนละแหล่งข้อมูลโดยตั้งใจ: ตารางเทียบค่าเฉลี่ยใช้ค่าทั้งจังหวัดเป็นบริบท
    ส่วนอันดับใช้ urban subset ให้ตรงกับ /analysis/ranking ที่ใช้บน Landing/Dashboard
    """
    ensure_province(province_name)

    rows = supa_call(lambda s: s.table("ndvi_annual")
                     .select("province,ndvi_mean,green_area_pct,green_area_km2,green_area_m2_per_person")
                     .eq("year", year).execute()).data

    if not rows:
        return {"year": year, "provinces_in_cache": 0,
                "national": None, "target": None, "ranked_top": []}

    valid_ndvi = [r["ndvi_mean"] for r in rows if r.get("ndvi_mean") is not None]
    valid_pct = [r["green_area_pct"] for r in rows if r.get("green_area_pct") is not None]
    valid_m2 = [r["green_area_m2_per_person"] for r in rows
                if r.get("green_area_m2_per_person") is not None]

    def avg(xs):
        return round(sum(xs) / len(xs), 3) if xs else None

    target = next((r for r in rows if r["province"] == province_name), None)

    # district IS NULL — urban_ndvi_annual เก็บทั้งแถวระดับจังหวัดและอำเภอปนกัน
    urban_rows = supa_call(lambda s: s.table("urban_ndvi_annual")
                           .select("province,m2_per_person_urban")
                           .eq("year", year).is_("district", "null").execute()).data
    # ascending — rank 1 = ต่ำสุด (ให้ตรงกับ convention เดียวกับ /analysis/ranking)
    sorted_by_urban = sorted(
        [r for r in urban_rows if r.get("m2_per_person_urban") is not None],
        key=lambda r: r["m2_per_person_urban"])
    urban_rank = next((i + 1 for i, r in enumerate(sorted_by_urban)
                       if r["province"] == province_name), None)

    # Top 10 ranked provinces — เปิดเผยให้รายงานแสดงรายชื่อจริง อ่านแล้วตรวจอันดับเองได้
    ranked_top = [
        {"rank": i + 1, "province": r["province"],
         "m2_per_person_urban": r["m2_per_person_urban"]}
        for i, r in enumerate(sorted_by_urban[:10])
    ]

    return {
        "year": year,
        "provinces_in_cache": len(rows),
        "national": {
            "ndvi_mean_avg": avg(valid_ndvi),
            "green_area_pct_avg": avg(valid_pct),
            "green_area_m2_per_person_avg": avg(valid_m2),
        },
        "target": {
            "province": province_name,
            "urban_rank": urban_rank,
            "urban_total_ranked": len(sorted_by_urban),
        } if target else None,
        "ranked_top": ranked_top,
    }
