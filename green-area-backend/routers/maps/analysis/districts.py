"""District summary (Phase B-1) — per-district NDVI+LST breakdown จาก cache."""
from fastapi import APIRouter

from dependencies import (supa_call, gather, ensure_province, DISTRICT_GEOMETRIES,
                          CURRENT_YEAR, YearParam)

router = APIRouter()


@router.get("/analysis/districts/{province_name}")
def get_district_summary(province_name: str, year: YearParam = CURRENT_YEAR):
    """รวบรวมข้อมูลรายอำเภอ (NDVI + LST) จาก cache สำหรับใส่ในรายงานระดับจังหวัด.

    คืนเฉพาะอำเภอที่มี cached ปีนั้น — ไม่ trigger compute ใหม่เพื่อกันเวลา response.
    """
    ensure_province(province_name)

    # NDVI + LST รายอำเภอเป็น query คนละตารางที่ไม่พึ่งกัน → ยิงขนาน ลด latency
    ndvi_rows, lst_rows = gather(
        lambda: supa_call(lambda s: s.table("district_ndvi_annual")
            .select("district,ndvi_mean,green_area_pct,green_area_km2,total_area_km2,canopy")
            .eq("province", province_name).eq("year", year).execute()).data,
        lambda: supa_call(lambda s: s.table("district_lst_annual")
            .select("district,lst_mean,lst_min,lst_max")
            .eq("province", province_name).eq("year", year).execute()).data,
    )

    lst_by_dist = {r["district"]: r for r in lst_rows}
    merged = []
    for n in ndvi_rows:
        d = n["district"]
        lst = lst_by_dist.get(d, {})
        # canopy เก็บเป็น jsonb ก้อนใหญ่ (FR-17) — ตารางรายอำเภอต้องการแค่ 2 ค่าที่
        # เอาไปเรียง/นับได้ ส่ง flat มาให้เลยแทนที่จะให้ frontend เจาะ nested เอง
        canopy = n.get("canopy") or {}
        merged.append({
            "district": d,
            "ndvi_mean": n.get("ndvi_mean"),
            "green_area_pct": n.get("green_area_pct"),
            "green_area_km2": n.get("green_area_km2"),
            "total_area_km2": n.get("total_area_km2"),
            "canopy_pct": canopy.get("canopy_pct"),
            "canopy_meets_target": canopy.get("meets_target"),
            "lst_mean": lst.get("lst_mean"),
            "lst_min": lst.get("lst_min"),
            "lst_max": lst.get("lst_max"),
        })
    # อำเภอที่มีแค่ LST ไม่มี NDVI ก็ใส่ด้วย
    ndvi_dists = {n["district"] for n in ndvi_rows}
    for r in lst_rows:
        if r["district"] not in ndvi_dists:
            merged.append({
                "district": r["district"],
                "ndvi_mean": None, "green_area_pct": None,
                "green_area_km2": None, "total_area_km2": None,
                "canopy_pct": None, "canopy_meets_target": None,
                "lst_mean": r.get("lst_mean"),
                "lst_min": r.get("lst_min"),
                "lst_max": r.get("lst_max"),
            })

    merged.sort(key=lambda r: r.get("ndvi_mean") or -1, reverse=True)
    total_known = sum(1 for (_p, d) in DISTRICT_GEOMETRIES.keys() if _p == province_name)
    # สรุปเกณฑ์ 30% ระดับจังหวัด — นับเฉพาะอำเภอที่มีค่า canopy จริง (อำเภอที่ยังไม่
    # เคยเปิดจะไม่มีใน cache · ตัวหารจึงเป็น with_canopy ไม่ใช่ districts_total)
    with_canopy = [r for r in merged if r.get("canopy_pct") is not None]
    meeting = [r for r in with_canopy if r.get("canopy_meets_target")]
    return {
        "province": province_name, "year": year,
        "districts_in_cache": len(merged),
        "districts_total": total_known,
        "canopy_summary": {
            "districts_with_canopy": len(with_canopy),
            "districts_meeting_target": len(meeting),
            "canopy_pct_avg": round(sum(r["canopy_pct"] for r in with_canopy)
                                    / len(with_canopy), 1) if with_canopy else None,
        },
        "data": merged,
    }
