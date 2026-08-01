"""Saved areas — บันทึก polygon ที่ผู้ใช้วาดเอง + ผลวิเคราะห์ ไว้ดูย้อนหลัง.

นี่คือ *ข้อมูลผู้ใช้* (ไม่ใช่ cache) → ไม่อยู่ใน CACHE_TABLES, DELETE /cache ไม่แตะ

Ownership ผูกกับบัญชีผู้ใช้อย่างเดียว (require_user ที่ include_router ใน main.py):
  - POST /saved-areas ตั้ง user_id = ผู้ใช้ที่ล็อกอินเสมอ (ผูกกับบัญชี ไม่ใช่เครื่อง —
    ล็อกอินบัญชีเดิมจากเครื่องไหนก็เห็นพื้นที่เดิม) · ลบบัญชี → พื้นที่ถูกลบตาม
    (ON DELETE CASCADE ใน migration 013)
  - GET /saved-areas (list) คืน *เฉพาะของเจ้าของ* เสมอ (privacy) — polygon ที่ผู้ใช้
    วาด อาจเป็นที่ดิน/บ้านตัวเอง ไม่ควรให้คนอื่นเห็นพิกัด (ไม่มี public gallery —
    frontend ไม่มีฟีเจอร์นี้ด้วย ดู useSavedAreas.js)
  - GET /saved-areas/{id} (แบบเต็ม รวม analysis + recommendation) จำกัดเฉพาะเจ้าของ
    หรือ admin เท่านั้น — id เป็น BIGSERIAL เดาเลขถัดไปได้ง่าย เปิดสาธารณะไม่ได้
  - DELETE ทำได้เฉพาะเจ้าของ หรือ admin (X-Admin-Token ตรง)
  - response ไม่เคย leak user_id ออกไป

เดิมมี X-Owner-Token (UUID ใน localStorage รายเครื่อง จากยุคก่อนมี login) เป็นทางเลือก
ที่สองในการระบุเจ้าของ — ตัดออกใน migration 019 เพราะทั้งแอปบังคับล็อกอินหมดแล้ว
จึงไม่มีแถวที่ไม่มี user_id เกิดขึ้นได้อีก
"""
import logging
import secrets

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

import dependencies  # อ่าน ADMIN_TOKEN แบบ dynamic (รองรับ monkeypatch ใน test)
from dependencies import (supa_call, internal_error, require_user, PROVINCE_GEOMETRIES,
                          CURRENT_YEAR, YEAR_MIN, YEAR_MAX)
from polygon_utils import validate_drawn_polygon

router = APIRouter()
logger = logging.getLogger(__name__)

MAX_LABEL_LEN = 120
_SAVED_AREA_LIST_COLUMNS = "id,label,year,area_km2,province,geometry,user_id,created_at"


class SavedAreaCreate(BaseModel):
    """Body ของ POST /saved-areas"""
    geometry: dict = Field(..., description="GeoJSON Polygon geometry")
    year: int = Field(default=CURRENT_YEAR, ge=YEAR_MIN, le=YEAR_MAX)
    label: str | None = Field(default=None, max_length=MAX_LABEL_LEN)
    province: str | None = None
    analysis: dict | None = None        # response ของ /analysis/custom-area
    recommendation: dict | None = None  # response ของ /recommend/custom-area


def _public(row: dict, user_id: str) -> dict:
    """ตัด user_id ออกจาก response + เติม flag `mine`

    `mine` เป็น True เมื่อเป็นเจ้าของผ่านบัญชี · list คืนเฉพาะของเจ้าของอยู่แล้วจึง
    เป็น True เสมอ แต่คงไว้เพื่อไม่ให้ response shape เปลี่ยน (frontend อ่าน field นี้)"""
    out = {k: v for k, v in row.items() if k != "user_id"}
    out["mine"] = row.get("user_id") == user_id
    return out


def _is_admin(x_admin_token: str | None) -> bool:
    """เทียบ X-Admin-Token แบบ constant-time · ไม่มี ADMIN_TOKEN ตั้งไว้ = ไม่มี admin"""
    admin = dependencies.ADMIN_TOKEN
    return bool(admin and x_admin_token
                and secrets.compare_digest(str(x_admin_token), str(admin)))


@router.post("/saved-areas")
def create_saved_area(req: SavedAreaCreate, user: dict = Depends(require_user)):
    """บันทึกพื้นที่ที่วาด + ผลวิเคราะห์ · ผูกกับบัญชีที่ล็อกอิน (user_id)"""
    try:
        area_km2 = validate_drawn_polygon(req.geometry)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    province = req.province if req.province in PROVINCE_GEOMETRIES else None
    label = (req.label or "").strip()[:MAX_LABEL_LEN] or None
    row = {
        "label": label, "geometry": req.geometry, "year": req.year,
        "area_km2": round(area_km2, 2), "province": province,
        "analysis": req.analysis, "recommendation": req.recommendation,
        "user_id": user["id"],
    }
    try:
        res = supa_call(lambda s: s.table("saved_areas").insert(row).execute())
        saved = res.data[0] if res.data else row
        logger.info("💾 Saved area #%s (%.1f km²)", saved.get("id", "?"), area_km2)
        return _public(saved, user["id"])
    except Exception:
        logger.error("❌ Save area error", exc_info=True)
        raise internal_error()


@router.get("/saved-areas")
def list_saved_areas(province: str | None = None, user: dict = Depends(require_user)):
    """รายการพื้นที่ที่บันทึก (ใหม่สุดก่อน) — คืน geometry ด้วยเพื่อโหลดกลับบนแผนที่
    แต่ไม่คืน analysis/recommendation ที่หนัก (ดึงเต็มที่ GET /saved-areas/{id}).

    Privacy: คืนเฉพาะพื้นที่ของบัญชีนี้ (user_id) เสมอ"""
    def _by_user(s):
        q = (s.table("saved_areas").select(_SAVED_AREA_LIST_COLUMNS)
             .eq("user_id", user["id"]).order("created_at", desc=True).limit(200))
        if province:
            q = q.eq("province", province)
        return q.execute()

    try:
        rows = supa_call(_by_user).data
        return {"data": [_public(r, user["id"]) for r in rows]}
    except Exception:
        logger.error("❌ List saved areas error", exc_info=True)
        raise internal_error()


@router.get("/saved-areas/{area_id}")
def get_saved_area(area_id: int, x_admin_token: str | None = Header(default=None),
                   user: dict = Depends(require_user)):
    """ดึงพื้นที่ที่บันทึกแบบเต็ม (รวม analysis + recommendation) — เฉพาะเจ้าของ
    หรือ admin เท่านั้น

    id เป็น BIGSERIAL เรียงลำดับ เดาเลขถัดไปได้ง่าย — ถ้าเปิดให้ผู้ใช้ที่ล็อกอินคนไหน
    ก็ดึงได้ (ตามที่ตั้งใจไว้เดิมว่าจะใช้เป็นลิงก์แชร์) จะเห็น polygon/พิกัดของคนอื่น
    ได้ทั้งหมด ขัดกับ privacy stance ของ list (ดู docstring บนสุดของไฟล์) · frontend
    ก็ไม่มีฟีเจอร์แชร์ด้วยลิงก์อยู่จริง (useSavedAreas.getOne เรียกเฉพาะรายการของ
    ตัวเอง) — ถ้าต้องการแชร์ในอนาคตควรใช้ share token สุ่มแยกต่างหาก ไม่ใช่ id ตรงๆ
    """
    res = supa_call(lambda s: s.table("saved_areas").select("*")
                    .eq("id", area_id).execute())
    if not res.data:
        raise HTTPException(status_code=404, detail="ไม่พบพื้นที่ที่บันทึกไว้")
    row = res.data[0]
    is_owner = row.get("user_id") == user["id"]
    if not (is_owner or _is_admin(x_admin_token)):
        raise HTTPException(status_code=403, detail="ดูได้เฉพาะพื้นที่ที่คุณบันทึกเอง")
    return _public(row, user["id"])


@router.delete("/saved-areas/{area_id}")
def delete_saved_area(area_id: int, x_admin_token: str | None = Header(default=None),
                      user: dict = Depends(require_user)):
    """ลบได้เฉพาะเจ้าของ หรือ admin (admin token ตรง)"""
    res = supa_call(lambda s: s.table("saved_areas").select("id,user_id")
                    .eq("id", area_id).execute())
    if not res.data:
        raise HTTPException(status_code=404, detail="ไม่พบพื้นที่ที่บันทึกไว้")
    row = res.data[0]
    is_owner = row.get("user_id") == user["id"]
    if not (is_owner or _is_admin(x_admin_token)):
        raise HTTPException(status_code=403, detail="ลบได้เฉพาะพื้นที่ที่คุณบันทึกเอง")
    supa_call(lambda s: s.table("saved_areas").delete().eq("id", area_id).execute())
    logger.info("🗑️  Deleted saved area #%d (%s)", area_id, "owner" if is_owner else "admin")
    return {"message": "ลบแล้ว", "id": area_id}
