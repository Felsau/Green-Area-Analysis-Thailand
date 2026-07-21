"""Auth dependency tests — require_user / require_admin_or_user (dependencies.py)

Mock ทุกอย่างที่แตะ Supabase จริง (SUPABASE_URL=None ปิด local JWKS path,
get_supabase()/supa_call ปลอมด้วย SimpleNamespace) — ไม่มี test ไหนยิง network จริง
รัน: cd green-area-backend && pytest tests/test_auth_dependencies.py -v
"""
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import dependencies
from dependencies import require_admin_or_user, require_user


def _fake_user_response(user_id="uid-1", email="user@example.com"):
    return SimpleNamespace(user=SimpleNamespace(id=user_id, email=email))


class TestRequireUser:
    def test_no_authorization_header_raises_401(self, monkeypatch):
        monkeypatch.setattr(dependencies, "SUPABASE_URL", None)
        with pytest.raises(HTTPException) as exc:
            require_user(None)
        assert exc.value.status_code == 401

    def test_non_bearer_header_raises_401(self, monkeypatch):
        monkeypatch.setattr(dependencies, "SUPABASE_URL", None)
        with pytest.raises(HTTPException) as exc:
            require_user("Basic abc123")
        assert exc.value.status_code == 401

    def test_empty_bearer_token_raises_401(self, monkeypatch):
        monkeypatch.setattr(dependencies, "SUPABASE_URL", None)
        with pytest.raises(HTTPException) as exc:
            require_user("Bearer ")
        assert exc.value.status_code == 401

    def test_valid_token_via_network_fallback_returns_user(self, monkeypatch):
        # SUPABASE_URL=None → ข้าม local JWKS path ตรงไป network fallback
        # (โปรเจกต์จริงมี SUPABASE_URL ตั้งไว้ใน .env — ปิดที่นี่กันเทสต์ยิง JWKS จริง)
        monkeypatch.setattr(dependencies, "SUPABASE_URL", None)
        fake_client = SimpleNamespace(auth=SimpleNamespace(
            get_user=lambda token: _fake_user_response("uid-42", "a@b.com")))
        monkeypatch.setattr(dependencies, "get_supabase", lambda: fake_client)

        user = require_user("Bearer sometoken")
        assert user == {"id": "uid-42", "email": "a@b.com"}

    def test_network_call_raising_returns_401(self, monkeypatch):
        monkeypatch.setattr(dependencies, "SUPABASE_URL", None)

        def _boom():
            raise RuntimeError("network down")
        monkeypatch.setattr(dependencies, "get_supabase", _boom)

        with pytest.raises(HTTPException) as exc:
            require_user("Bearer sometoken")
        assert exc.value.status_code == 401

    def test_network_no_user_returns_401(self, monkeypatch):
        monkeypatch.setattr(dependencies, "SUPABASE_URL", None)
        fake_client = SimpleNamespace(auth=SimpleNamespace(
            get_user=lambda token: SimpleNamespace(user=None)))
        monkeypatch.setattr(dependencies, "get_supabase", lambda: fake_client)

        with pytest.raises(HTTPException) as exc:
            require_user("Bearer sometoken")
        assert exc.value.status_code == 401


class TestRequireAdminOrUser:
    def test_valid_admin_token_passes(self, monkeypatch):
        monkeypatch.setattr(dependencies, "ADMIN_TOKEN", "secret-token")
        require_admin_or_user(x_admin_token="secret-token", authorization=None)  # ไม่ raise = ผ่าน

    def test_wrong_admin_token_and_no_auth_raises_401(self, monkeypatch):
        monkeypatch.setattr(dependencies, "ADMIN_TOKEN", "secret-token")
        with pytest.raises(HTTPException) as exc:
            require_admin_or_user(x_admin_token="wrong", authorization=None)
        assert exc.value.status_code == 401

    def test_authenticated_admin_role_passes(self, monkeypatch):
        monkeypatch.setattr(dependencies, "ADMIN_TOKEN", "secret-token")
        monkeypatch.setattr(dependencies, "SUPABASE_URL", None)
        fake_client = SimpleNamespace(auth=SimpleNamespace(
            get_user=lambda token: _fake_user_response("admin-uid")))
        monkeypatch.setattr(dependencies, "get_supabase", lambda: fake_client)
        monkeypatch.setattr(dependencies, "supa_call",
            lambda fn, **kw: SimpleNamespace(data=[{"role": "admin"}]))

        require_admin_or_user(x_admin_token=None, authorization="Bearer sometoken")  # ไม่ raise = ผ่าน

    def test_authenticated_non_admin_raises_401(self, monkeypatch):
        monkeypatch.setattr(dependencies, "ADMIN_TOKEN", "secret-token")
        monkeypatch.setattr(dependencies, "SUPABASE_URL", None)
        fake_client = SimpleNamespace(auth=SimpleNamespace(
            get_user=lambda token: _fake_user_response("user-uid")))
        monkeypatch.setattr(dependencies, "get_supabase", lambda: fake_client)
        monkeypatch.setattr(dependencies, "supa_call",
            lambda fn, **kw: SimpleNamespace(data=[{"role": "user"}]))

        with pytest.raises(HTTPException) as exc:
            require_admin_or_user(x_admin_token=None, authorization="Bearer sometoken")
        assert exc.value.status_code == 401

    def test_nothing_provided_raises_401(self, monkeypatch):
        monkeypatch.setattr(dependencies, "ADMIN_TOKEN", "secret-token")
        with pytest.raises(HTTPException) as exc:
            require_admin_or_user(x_admin_token=None, authorization=None)
        assert exc.value.status_code == 401
