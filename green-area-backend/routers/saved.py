"""Saved areas — บันทึก polygon ที่ผู้ใช้วาดเอง + ผลวิเคราะห์ ไว้ดูย้อนหลัง/แชร์.

นี่คือ *ข้อมูลผู้ใช้* (ไม่ใช่ cache) → ไม่อยู่ใน CACHE_TABLES, DELETE /cache ไม่แตะ

Ownership ผูกกับบัญชีผู้ใช้ (require_user ที่ include_router ใน main.py):
  - POST /saved-areas ตั้ง user_id = ผู้ใช้ที่ล็อกอินเสมอ (ผูกกับบัญชี ไม่ใช่เครื่อง —
    ล็อกอินบัญชีเดิมจากเครื่องไหนก็เห็นพื้นที่เดิม) · ลบบัญชี → พื้นที่ถูกลบตาม
    (ON DELETE CASCADE ใน migration 012)
  - X-Owner-Token (localStorage รายเครื่อง จากยุคก่อนมี login) ยังรับไว้เป็น fallback
    เพื่อให้แถวเก่าที่ยังไม่มี user_id (บันทึกไว้ก่อน migration 012) เข้าถึง/ลบได้ต่อ
  - GET /saved-areas (list) default คืน *เฉพาะของเจ้าของ* (privacy) — polygon ที่ผู้ใช้
    วาด อาจเป็นที่ดิน/บ้านตัวเอง ไม่ควรให้คนอื่นเห็นพิกัดโดย default
  - ?shared=true → คืนรวมของทุกคน (public gallery) พร้อม flag `mine` ที่ตัดสินฝั่ง server
  - GET /saved-areas/{id} ยังเปิดให้ดึงรายตัวได้ → ใช้เป็นช่องทาง "แชร์ด้วยลิงก์/ไอดี"
  - DELETE ทำได้เฉพาะเจ้าของ (user_id หรือ owner token ตรง) หรือ admin (X-Admin-Token ตรง)
  - response ไม่เคย leak owner_token/user_id ออกไป
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
_SAVED_AREA_LIST_COLUMNS = "id,label,year,area_km2,province,geometry,owner_token,user_id,created_at"


class SavedAreaCreate(BaseModel):
    """Body ของ POST /saved-areas"""
    geometry: dict = Field(..., description="GeoJSON Polygon geometry")
    year: int = Field(default=CURRENT_YEAR, ge=YEAR_MIN, le=YEAR_MAX)
    label: str | None = Field(default=None, max_length=MAX_LABEL_LEN)
    province: str | None = None
    analysis: dict | None = None        # response ของ /analysis/custom-area
    recommendation: dict | None = None  # response ของ /recommend/custom-area


def _public(row: dict, token: str | None, user_id: str) -> dict:
    """ตัด owner_token/user_id ออกจาก response + เติม flag `mine`

    `mine` จริงถ้าเป็นเจ้าของผ่านบัญชี (user_id ตรง) หรือผ่าน legacy owner token
    (แถวเก่าก่อน migration 012 ที่ยังไม่มี user_id)"""
    out = {k: v for k, v in row.items() if k not in ("owner_token", "user_id")}
    owner = row.get("owner_token")
    mine_by_account = row.get("user_id") == user_id
    mine_by_token = bool(token and owner
                         and secrets.compare_digest(str(owner), str(token)))
    out["mine"] = mine_by_account or mine_by_token
    return out


@router.post("/saved-areas")
def create_saved_area(req: SavedAreaCreate,
                      x_owner_token: str | None = Header(default=None),
                      user: dict = Depends(require_user)):
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
        "owner_token": x_owner_token or None,
        "user_id": user["id"],
    }
    try:
        res = supa_call(lambda s: s.table("saved_areas").insert(row).execute())
        saved = res.data[0] if res.data else row
        logger.info("💾 Saved area #%s (%.1f km²)", saved.get("id", "?"), area_km2)
        return _public(saved, x_owner_token, user["id"])
    except Exception:
        logger.error("❌ Save area error", exc_info=True)
        raise internal_error()


@router.get("/saved-areas")
def list_saved_areas(province: str | None = None,
                     shared: bool = False,
                     x_owner_token: str | None = Header(default=None),
                     user: dict = Depends(require_user)):
    """รายการพื้นที่ที่บันทึก (ใหม่สุดก่อน) — คืน geometry ด้วยเพื่อโหลดกลับบนแผนที่
    แต่ไม่คืน analysis/recommendation ที่หนัก (ดึงเต็มที่ GET /saved-areas/{id}).

    Privacy: default คืนเฉพาะพื้นที่ของบัญชีนี้ (user_id) · ถ้ามี X-Owner-Token
    ด้วย จะรวม legacy row เก่า (ก่อน migration 012, user_id ยังว่าง) ที่ตรง token
    เข้ามาด้วย กันของเก่าหายไปตอนอัปเกรด · ?shared=true → คืนรวมทุกคน"""
    def _by_user(s):
        q = (s.table("saved_areas").select(_SAVED_AREA_LIST_COLUMNS)
             .eq("user_id", user["id"]).order("created_at", desc=True).limit(200))
        if province:
            q = q.eq("province", province)
        return q.execute()

    def _shared(s):
        q = (s.table("saved_areas").select(_SAVED_AREA_LIST_COLUMNS)
             .order("created_at", desc=True).limit(200))
        if province:
            q = q.eq("province", province)
        return q.execute()

    def _legacy_by_token(s):
        # ไม่ interpolate x_owner_token เข้า filter DSL ตรงๆ (เลี่ยง filter
        # injection จาก header ที่ผู้ใช้คุมได้) — ใช้ .eq()/.is_() ธรรมดาแทน
        return (s.table("saved_areas").select(_SAVED_AREA_LIST_COLUMNS)
                .is_("user_id", "null").eq("owner_token", x_owner_token)
                .order("created_at", desc=True).limit(200).execute())

    try:
        if shared:
            rows = supa_call(_shared).data
        else:
            rows = supa_call(_by_user).data
            if x_owner_token:
                legacy = supa_call(_legacy_by_token).data
                seen = {r["id"] for r in rows}
                rows += [r for r in legacy if r["id"] not in seen]
                rows.sort(key=lambda r: r.get("created_at") or "", reverse=True)
        return {"data": [_public(r, x_owner_token, user["id"]) for r in rows]}
    except Exception:
        logger.error("❌ List saved areas error", exc_info=True)
        raise internal_error()


@router.get("/saved-areas/{area_id}")
def get_saved_area(area_id: int, x_owner_token: str | None = Header(default=None),
                   user: dict = Depends(require_user)):
    """ดึงพื้นที่ที่บันทึกแบบเต็ม (รวม analysis + recommendation)"""
    res = supa_call(lambda s: s.table("saved_areas").select("*")
                    .eq("id", area_id).execute())
    if not res.data:
        raise HTTPException(status_code=404, detail="ไม่พบพื้นที่ที่บันทึกไว้")
    return _public(res.data[0], x_owner_token, user["id"])


@router.delete("/saved-areas/{area_id}")
def delete_saved_area(area_id: int,
                      x_owner_token: str | None = Header(default=None),
                      x_admin_token: str | None = Header(default=None),
                      user: dict = Depends(require_user)):
    """ลบได้เฉพาะเจ้าของ (user_id หรือ legacy owner token ตรง) หรือ admin (admin token ตรง)"""
    res = supa_call(lambda s: s.table("saved_areas").select("id,owner_token,user_id")
                    .eq("id", area_id).execute())
    if not res.data:
        raise HTTPException(status_code=404, detail="ไม่พบพื้นที่ที่บันทึกไว้")
    row = res.data[0]
    owner = row.get("owner_token")
    is_owner = bool(row.get("user_id") == user["id"]
                    or (x_owner_token and owner
                        and secrets.compare_digest(str(owner), str(x_owner_token))))
    admin = dependencies.ADMIN_TOKEN
    is_admin = bool(admin and x_admin_token
                    and secrets.compare_digest(str(x_admin_token), str(admin)))
    if not (is_owner or is_admin):
        raise HTTPException(status_code=403, detail="ลบได้เฉพาะพื้นที่ที่คุณบันทึกเอง")
    supa_call(lambda s: s.table("saved_areas").delete().eq("id", area_id).execute())
    logger.info("🗑️  Deleted saved area #%d (%s)", area_id, "owner" if is_owner else "admin")
    return {"message": "ลบแล้ว", "id": area_id}
