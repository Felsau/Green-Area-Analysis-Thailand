"""Admin user-management tests — routers/admin.py

เน้นกฎที่กันแอดมินล็อกตัวเองออกจากระบบ เพราะถ้าพลาดแล้วจะกลับมาแก้ทางหน้าเว็บไม่ได้
ต้องไปรัน SQL ซึ่งเป็นปัญหาที่ router นี้ตั้งใจกำจัด

Mock Supabase ทั้งหมด — ไม่มี test ไหนยิง network จริง
รัน: cd green-area-backend && pytest tests/test_admin_users.py -v
"""
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from routers import admin
from routers.admin import RoleUpdate, list_users, set_user_role

ADMIN = {"id": "admin-1", "email": "admin@example.com"}
OTHER_ADMIN = {"id": "admin-2", "email": "admin2@example.com"}


def _profile(uid, role="user", name="ผู้ใช้ทดสอบ"):
    return {"id": uid, "display_name": name, "organization": None,
            "role": role, "created_at": "2026-01-01T00:00:00Z"}


class _Supa:
    """ปลอม supa_call — เก็บ update ที่ถูกเรียกไว้ตรวจ และตอบ select ตามตารางที่ขอ"""

    def __init__(self, profiles):
        self.profiles = {p["id"]: dict(p) for p in profiles}
        self.updates = []

    def __call__(self, fn, **kw):
        return fn(self)

    # --- pseudo query builder ---
    def table(self, name):
        self._table, self._filters, self._payload = name, {}, None
        return self

    def select(self, *_a, **_kw):
        self._op = "select"
        return self

    def update(self, payload):
        self._op, self._payload = "update", payload
        return self

    def eq(self, col, val):
        self._filters[col] = val
        return self

    def order(self, *_a, **_kw):
        return self

    def limit(self, *_a, **_kw):
        return self

    def execute(self):
        rows = list(self.profiles.values())
        for col, val in self._filters.items():
            rows = [r for r in rows if r.get(col) == val]
        if self._op == "update":
            for r in rows:
                r.update(self._payload)
                self.updates.append((r["id"], dict(self._payload)))
        return SimpleNamespace(data=rows)


@pytest.fixture
def supa(monkeypatch):
    def _make(profiles):
        fake = _Supa(profiles)
        monkeypatch.setattr(admin, "supa_call", fake)
        monkeypatch.setattr(admin, "_emails_by_id", lambda: {})
        return fake
    return _make


class TestListUsers:
    def test_marks_the_calling_admin_row(self, supa):
        supa([_profile("admin-1", "admin"), _profile("u-2")])
        rows = list_users(admin=ADMIN)
        by_id = {r.id: r for r in rows}
        assert by_id["admin-1"].is_me is True
        assert by_id["u-2"].is_me is False

    def test_adds_thai_role_label(self, supa):
        supa([_profile("u-2")])
        assert list_users(admin=ADMIN)[0].role_label == "เจ้าหน้าที่ GIS"

    def test_no_row_is_me_when_called_with_admin_token(self, supa):
        # current_admin คืน None เมื่อผ่านด้วย X-Admin-Token (สคริปต์ ไม่มีตัวตนผู้ใช้)
        supa([_profile("admin-1", "admin")])
        assert list_users(admin=None)[0].is_me is False


class TestSetUserRole:
    def test_promotes_user_to_admin(self, supa):
        fake = supa([_profile("admin-1", "admin"), _profile("u-2")])
        out = set_user_role("u-2", RoleUpdate(role="admin"), admin=ADMIN)
        assert out.role == "admin"
        assert fake.updates == [("u-2", {"role": "admin"})]

    def test_rejects_unknown_role(self, supa):
        supa([_profile("u-2")])
        with pytest.raises(HTTPException) as exc:
            set_user_role("u-2", RoleUpdate(role="superuser"), admin=ADMIN)
        assert exc.value.status_code == 400

    def test_unknown_user_returns_404(self, supa):
        supa([_profile("admin-1", "admin")])
        with pytest.raises(HTTPException) as exc:
            set_user_role("ghost", RoleUpdate(role="admin"), admin=ADMIN)
        assert exc.value.status_code == 404

    def test_same_role_is_a_no_op(self, supa):
        fake = supa([_profile("u-2")])
        out = set_user_role("u-2", RoleUpdate(role="user"), admin=ADMIN)
        assert out.role == "user"
        assert fake.updates == []          # ไม่เขียนซ้ำโดยไม่จำเป็น

    def test_admin_cannot_demote_self(self, supa):
        fake = supa([_profile("admin-1", "admin"), _profile("admin-2", "admin")])
        with pytest.raises(HTTPException) as exc:
            set_user_role("admin-1", RoleUpdate(role="user"), admin=ADMIN)
        assert exc.value.status_code == 400
        assert "ตัวเอง" in exc.value.detail
        assert fake.updates == []

    def test_cannot_demote_the_last_admin(self, supa):
        fake = supa([_profile("admin-1", "admin")])
        # ผ่านด้วย X-Admin-Token (admin=None) จึงข้ามด่าน "ลดสิทธิ์ตัวเอง" มาชนด่านนี้
        with pytest.raises(HTTPException) as exc:
            set_user_role("admin-1", RoleUpdate(role="user"), admin=None)
        assert exc.value.status_code == 400
        assert "อย่างน้อย 1 คน" in exc.value.detail
        assert fake.updates == []

    def test_can_demote_an_admin_when_another_remains(self, supa):
        fake = supa([_profile("admin-1", "admin"), _profile("admin-2", "admin")])
        out = set_user_role("admin-2", RoleUpdate(role="user"), admin=ADMIN)
        assert out.role == "user"
        assert fake.updates == [("admin-2", {"role": "user"})]


class TestEmailLookup:
    def test_missing_email_does_not_break_listing(self, monkeypatch):
        fake = _Supa([_profile("u-2")])
        monkeypatch.setattr(admin, "supa_call", fake)

        def _boom():
            raise RuntimeError("auth down")
        monkeypatch.setattr(admin, "get_supabase", _boom)

        rows = list_users(admin=ADMIN)      # ต้องไม่ raise
        assert rows[0].email is None
