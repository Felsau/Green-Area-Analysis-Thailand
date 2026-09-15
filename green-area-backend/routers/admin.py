"""Admin — จัดการผู้ใช้งานและสิทธิ์ผ่านหน้าเว็บ (ไม่ต้องรัน SQL เอง)

เดิมการเลื่อน/ลดสิทธิ์ต้องเปิด Supabase แล้วรัน SQL ตรง ๆ ตามที่ migration 010
เขียนไว้ ทำให้หน่วยงานที่รับระบบไปใช้ต้องพึ่งผู้พัฒนาทุกครั้งที่มีเจ้าหน้าที่เข้า/ออก
router นี้ย้ายงานนั้นมาไว้บนหน้าเว็บให้ผู้ดูแลระบบกดเองได้

บทบาทในระบบมี 2 ค่า ตรงกับ CHECK constraint ของ profiles (migration 010):
    'user'   → เจ้าหน้าที่ GIS   (ผู้ใช้งานหลัก)
    'admin'  → ผู้ดูแลระบบ       (สืบทอดทุกอย่างของเจ้าหน้าที่ GIS + งานดูแลระบบ)

กันล็อกตัวเองออกจากระบบไว้ 2 ชั้น เพราะถ้าไม่เหลือแอดมินเลยจะกลับมาแก้ทางหน้าเว็บ
ไม่ได้อีก ต้องไปรัน SQL ซึ่งเป็นปัญหาที่ router นี้ตั้งใจกำจัด:
  1) แอดมินลดสิทธิ์ตัวเองไม่ได้
  2) ลดสิทธิ์แอดมินคนสุดท้ายไม่ได้
"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from dependencies import (current_admin, get_supabase, internal_error,
                          require_admin_or_user, supa_call)

router = APIRouter(prefix="/admin", tags=["admin"])
logger = logging.getLogger(__name__)

# ตรงกับ CHECK constraint ใน migration 010 — เพิ่มค่าใหม่ต้องแก้ migration ด้วย
ROLES = ("user", "admin")
ROLE_LABELS = {"user": "เจ้าหน้าที่ GIS", "admin": "ผู้ดูแลระบบ"}

_PROFILE_COLUMNS = "id,display_name,organization,role,created_at"


class AdminUser(BaseModel):
    id: str
    email: str | None = None          # None เมื่ออ่านอีเมลจาก auth ไม่สำเร็จ
    display_name: str
    organization: str | None = None
    role: str
    role_label: str
    created_at: str
    is_me: bool = False               # แถวของแอดมินที่กำลังใช้งานอยู่


class RoleUpdate(BaseModel):
    role: str = Field(..., description="'user' (เจ้าหน้าที่ GIS) หรือ 'admin'")


def _emails_by_id() -> dict[str, str]:
    """map user_id → email จาก auth.users (service-role key เท่านั้นที่อ่านได้)

    อีเมลไม่ได้อยู่ใน profiles จึงต้องถามฝั่ง auth · ถ้าเรียกไม่สำเร็จให้คืน dict ว่าง
    แล้วปล่อยให้ตารางแสดงผลต่อโดยไม่มีอีเมล ดีกว่าทำให้ทั้งหน้าพัง
    """
    try:
        res = get_supabase().auth.admin.list_users()
    except Exception:
        logger.warning("อ่านรายชื่ออีเมลจาก auth ไม่สำเร็จ — ตารางจะไม่แสดงอีเมล",
                       exc_info=True)
        return {}
    users = getattr(res, "users", res)      # supabase-py คืน list ตรง ๆ หรือ object
    out = {}
    for u in users or []:
        uid, email = getattr(u, "id", None), getattr(u, "email", None)
        if uid:
            out[str(uid)] = email
    return out


@router.get("/users", response_model=list[AdminUser])
def list_users(admin: dict | None = Depends(current_admin)):
    """รายชื่อผู้ใช้งานทั้งหมดพร้อมบทบาท — เรียงคนใหม่สุดขึ้นก่อน"""
    try:
        rows = supa_call(lambda s: s.table("profiles").select(_PROFILE_COLUMNS)
                         .order("created_at", desc=True).limit(500).execute()).data
    except Exception:
        logger.error("❌ อ่านรายชื่อผู้ใช้ไม่สำเร็จ", exc_info=True)
        raise internal_error()
    emails = _emails_by_id()
    me = admin["id"] if admin else None
    return [AdminUser(**r, email=emails.get(r["id"]),
                      role_label=ROLE_LABELS.get(r["role"], r["role"]),
                      is_me=(r["id"] == me)) for r in rows]


@router.patch("/users/{user_id}/role", response_model=AdminUser)
def set_user_role(user_id: str, body: RoleUpdate,
                  admin: dict | None = Depends(current_admin)):
    """เปลี่ยนบทบาทของผู้ใช้ — งานที่เดิมต้องรัน SQL ใน Supabase"""
    if body.role not in ROLES:
        raise HTTPException(status_code=400,
                            detail="บทบาทต้องเป็น %s เท่านั้น" % " หรือ ".join(ROLES))

    res = supa_call(lambda s: s.table("profiles").select(_PROFILE_COLUMNS)
                    .eq("id", user_id).limit(1).execute())
    if not res.data:
        raise HTTPException(status_code=404, detail="ไม่พบผู้ใช้งานรายนี้")
    row = res.data[0]
    if row["role"] == body.role:
        return AdminUser(**row, email=_emails_by_id().get(user_id),
                         role_label=ROLE_LABELS.get(row["role"], row["role"]),
                         is_me=bool(admin and admin["id"] == user_id))

    # ชั้นที่ 1 — แอดมินลดสิทธิ์ตัวเองไม่ได้
    if admin and admin["id"] == user_id and body.role != "admin":
        raise HTTPException(status_code=400,
                            detail="ลดสิทธิ์ของตัวเองไม่ได้ — ให้ผู้ดูแลระบบคนอื่นเป็นผู้ดำเนินการ")

    # ชั้นที่ 2 — ต้องเหลือผู้ดูแลระบบอย่างน้อย 1 คนเสมอ
    if row["role"] == "admin" and body.role != "admin":
        admins = supa_call(lambda s: s.table("profiles").select("id")
                           .eq("role", "admin").execute()).data
        if len(admins) <= 1:
            raise HTTPException(status_code=400,
                                detail="ต้องเหลือผู้ดูแลระบบอย่างน้อย 1 คน — "
                                       "ตั้งผู้ดูแลระบบคนใหม่ก่อนจึงจะลดสิทธิ์คนนี้ได้")

    try:
        supa_call(lambda s: s.table("profiles").update({"role": body.role})
                  .eq("id", user_id).execute())
    except Exception:
        logger.error("❌ เปลี่ยนบทบาทผู้ใช้ %s ไม่สำเร็จ", user_id, exc_info=True)
        raise internal_error("เปลี่ยนบทบาทไม่สำเร็จ — ลองใหม่อีกครั้ง")

    logger.warning("👤 ADMIN เปลี่ยนบทบาท %s: %s → %s (โดย %s)",
                   user_id, row["role"], body.role,
                   admin["email"] if admin else "X-Admin-Token")
    row["role"] = body.role
    return AdminUser(**row, email=_emails_by_id().get(user_id),
                     role_label=ROLE_LABELS.get(body.role, body.role),
                     is_me=bool(admin and admin["id"] == user_id))


@router.get("/saved-areas", dependencies=[Depends(require_admin_or_user)])
def list_all_saved_areas(province: str | None = None):
    """พื้นที่ที่ผู้ใช้ทุกคนบันทึกไว้ — สำหรับผู้ดูแลระบบตรวจสอบและลบของที่ไม่เหมาะสม

    ต่างจาก GET /saved-areas ที่คืนเฉพาะของเจ้าของ · ไม่คืน geometry/analysis เพราะ
    หน้าจัดการต้องการแค่รายการ ส่วนการดูรายละเอียดใช้ GET /saved-areas/{id} เดิม
    (รับ X-Admin-Token อยู่แล้ว) · คืน user_id ด้วยเพราะแอดมินต้องรู้ว่าเป็นของใคร
    """
    def _query(s):
        q = (s.table("saved_areas").select("id,label,year,area_km2,province,user_id,created_at")
             .order("created_at", desc=True).limit(500))
        return (q.eq("province", province) if province else q).execute()

    try:
        return {"data": supa_call(_query).data}
    except Exception:
        logger.error("❌ อ่านรายการพื้นที่ทั้งหมดไม่สำเร็จ", exc_info=True)
        raise internal_error()
