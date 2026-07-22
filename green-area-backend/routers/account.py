"""Account — โปรไฟล์ผู้ใช้ที่ล็อกอินผ่าน Supabase Auth (supabase-js ฝั่ง frontend).

Auth token lifecycle (signup/signin/verify/reset) เกิดขึ้นตรงระหว่าง frontend ↔
Supabase Auth (GoTrue) — backend ไม่แตะ ยกเว้น 2 อย่างที่ต้องใช้ service-role key
ซึ่งมีแค่ backend เท่านั้น:
  1) อ่าน/แก้ profiles (display_name) — RLS ไม่เปิด update ให้ client เรียกตรง กัน
     ใครก็ตามที่ยิง Supabase REST เองด้วย anon key แล้วเผลอแก้ column อื่น (เช่น role)
  2) ลบบัญชี (auth.admin.delete_user) — ต้องใช้ service-role key เท่านั้น
"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from dependencies import require_user, supa_call, get_supabase, internal_error

router = APIRouter(prefix="/account", tags=["account"])
logger = logging.getLogger(__name__)

MAX_NAME_LEN = 100


class ProfileOut(BaseModel):
    id: str
    email: str
    display_name: str
    role: str
    created_at: str
    updated_at: str
    accepted_terms_at: str | None = None
    organization: str | None = None


class ProfileUpdate(BaseModel):
    display_name: str = Field(min_length=1, max_length=MAX_NAME_LEN)
    organization: str | None = Field(default=None, max_length=MAX_NAME_LEN)


def _fetch_profile(user: dict) -> ProfileOut:
    result = supa_call(lambda s: s.table("profiles")
                       .select("display_name,role,created_at,updated_at,accepted_terms_at,organization")
                       .eq("id", user["id"]).limit(1).execute())
    if not result.data:
        # แถวควรถูกสร้างอัตโนมัติโดย trigger on_auth_user_created ตอนสมัคร —
        # ถ้าไม่เจอ (เช่น สมัครก่อนรัน migration 010) แสดง error ชัดเจนแทนการ 500 เงียบๆ
        raise HTTPException(status_code=404,
            detail="ไม่พบโปรไฟล์ผู้ใช้ — ติดต่อผู้ดูแลระบบถ้าปัญหานี้เกิดซ้ำ")
    row = result.data[0]
    return ProfileOut(id=user["id"], email=user["email"], **row)


@router.get("/me", response_model=ProfileOut)
def get_me(user: dict = Depends(require_user)):
    return _fetch_profile(user)


@router.patch("/me", response_model=ProfileOut)
def update_me(body: ProfileUpdate, user: dict = Depends(require_user)):
    name = body.display_name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="กรอกชื่อ-นามสกุล")
    org = (body.organization or "").strip() or None
    supa_call(lambda s: s.table("profiles")
              .update({"display_name": name, "organization": org}).eq("id", user["id"]).execute())
    return _fetch_profile(user)


@router.delete("/me")
def delete_me(user: dict = Depends(require_user)):
    """ลบบัญชีถาวร — auth.users ถูกลบ (profiles + saved_areas ที่ผูก user_id
    ตามไปด้วยจาก ON DELETE CASCADE — ดู migrations 010, 013)"""
    try:
        get_supabase().auth.admin.delete_user(user["id"])
    except Exception:
        logger.error("❌ ลบบัญชีผู้ใช้ %s ไม่สำเร็จ", user["id"], exc_info=True)
        raise internal_error("ลบบัญชีไม่สำเร็จ — ลองใหม่อีกครั้ง")
    logger.info("🗑️  ลบบัญชีผู้ใช้ %s แล้ว", user["id"])
    return {"message": "ลบบัญชีแล้ว"}
