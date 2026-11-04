"""Guarded SQL-RPC adapter. No credentials, app config or legacy admin bypass."""
from __future__ import annotations

import base64
import json
import re
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from starlette.responses import JSONResponse

from gis_schemas import PageCursor


def gis_error(status: int, code: str, message: str, *, fields=None, headers=None):
    return HTTPException(status_code=status,
        detail={"code": code, "message": message, "fields": fields or {}}, headers=headers)


_CONFLICTS = {
    "GIS_GEOTIFF_PUBLISHED_UNAVAILABLE", "GIS_GEOTIFF_PUBLICATION_UNSUPPORTED",
    "GIS_LDD_PUBLISHED_UNAVAILABLE", "GIS_SOURCE_CHANGED", "GIS_PUBLICATION_NOT_READY", "GIS_LDD_PUBLICATION_UNSUPPORTED",
    "GIS_PREPARE_BUSY", "GIS_PREPARE_VALIDATION_REQUIRED", "GIS_PREPARE_CERTIFICATE_REVOKED", "GIS_PREPARE_PROOF_INVALID",
    "GIS_PREPARE_NOT_READY", "GIS_PREPARE_REPORT_INVALID", "GIS_ARTIFACT_INPUT_MISMATCH",
    "GIS_REVISION_CONFLICT", "GIS_IDEMPOTENCY_CONFLICT", "GIS_RETRY_INELIGIBLE",
    "GIS_RETRY_ALREADY_USED", "GIS_EDITION_NOT_DRAFT", "GIS_ACTIVATION_INELIGIBLE",
    "GIS_ROLLBACK_INELIGIBLE", "GIS_WITHDRAWAL_INELIGIBLE", "GIS_REPLACEMENT_FOR_INACTIVE_EDITION",
    "GIS_UPLOADED_EDITION_IMMUTABLE",
    "GIS_PROCESSING_IMMUTABLE", "GIS_PROCESSING_ROUTE_REQUIRED",
    "GIS_PROCESSING_COMMAND_REQUIRED", "GIS_PROCESSING_INPUT_IMMUTABLE",
    "GIS_GEOTIFF_IMMUTABLE", "GIS_GEOTIFF_COMMAND_REQUIRED", "GIS_GEOTIFF_IMMUTABLE_VALIDATION_ONLY",
}
_INVALID = {
    "GIS_INVALID_PAYLOAD", "GIS_INVALID_MANIFEST", "GIS_SYNTHETIC_MANIFEST_NOT_ALLOWLISTED",
    "GIS_INVALID_YEAR", "GIS_REASON_REQUIRED", "GIS_REQUEST_ID_REQUIRED", "GIS_SYNTHETIC_ONLY",
    "GIS_EXPECTED_POINTER_REQUIRED", "GIS_INVALID_CURSOR", "GIS_INVALID_LIMIT", "GIS_INVALID_FILTER",
    "GIS_LDD_DATASET_REQUIRED", "GIS_INVALID_UPLOAD", "GIS_LDD_UPLOAD_REQUIRED",
    "GIS_PROCESSING_INVALID", "GIS_PROCESSING_SCOPE_INVALID", "GIS_PROCESSING_YEAR_INVALID",
    "GIS_PROCESSING_SCOPE_UNSUPPORTED", "GIS_PROCESSING_DATE_UNSUPPORTED",
    "GIS_PROCESSING_SOURCE_UNSUPPORTED", "GIS_INVALID_PROCESSING_MANIFEST",
    "GIS_GEOTIFF_DATASET_REQUIRED", "GIS_INVALID_GEOTIFF_UPLOAD", "GIS_GEOTIFF_UPLOAD_REQUIRED", "GIS_INVALID_GEOTIFF_MANIFEST",
}
_NOT_READY = {"GIS_LOCAL_TARGET_REQUIRED", "GIS_BASELINE_REQUIRED", "GIS_ACTIVATION_DISABLED", "GIS_GEE_LIVE_NOT_APPROVED", "GIS_PROCESSING_NOT_READY", "GIS_GEE_LIVE_DISABLED", "GIS_PROCESSING_CONTRACT_NOT_READY"}
_HIDDEN_KEYS = {
    "lease_token", "lease_until", "worker_id", "created_by", "requested_by", "granted_by", "actor_id", "subject_id",
    "runtime_instance", "baseline_fingerprint", "cluster_name", "database_name",
    "access_token", "refresh_token", "service_key", "password", "secret",
}


def safe_output(value: Any):
    if isinstance(value, dict):
        return {key: safe_output(item) for key, item in value.items() if key not in _HIDDEN_KEYS}
    if isinstance(value, list):
        return [safe_output(item) for item in value]
    return value


def map_rpc_error(error: Exception) -> HTTPException:
    """Map allowlisted database diagnostics, never return SQL text/details/hints."""
    code = str(getattr(error, "code", ""))
    raw = getattr(error, "message", "")
    message = raw if isinstance(raw, str) and re.fullmatch(r"GIS_[A-Z0-9_]+", raw) else ""
    if message == "GIS_FORBIDDEN" or code == "42501":
        return gis_error(403, "GIS_FORBIDDEN", "ไม่มีสิทธิ์ดำเนินการนี้")
    if message in {"GIS_NOT_FOUND", "GIS_LDD_NOT_PUBLISHED", "GIS_GEOTIFF_NOT_PUBLISHED"}:
        return gis_error(404, message, "ไม่พบข้อมูล GIS ที่ระบุ")
    if message in _CONFLICTS:
        return gis_error(409, message, "ข้อมูลหรือสถานะเปลี่ยนแล้ว กรุณาอ่านข้อมูลล่าสุดก่อนลองใหม่")
    if message in _INVALID:
        return gis_error(422, message, "ข้อมูลคำขอ GIS ไม่ถูกต้องหรือไม่รองรับ")
    if code == "23505":
        return gis_error(409, "GIS_IDENTITY_CONFLICT", "มีข้อมูลที่ใช้ Identity นี้อยู่แล้ว")
    if code in {"23503", "23514", "23502", "22P02", "22003", "22007", "22008", "22023"}:
        return gis_error(422, "GIS_INVALID_INPUT", "ข้อมูลคำขอหรือข้อมูลอ้างอิงไม่ถูกต้อง")
    if code == "429":
        return gis_error(429, "GIS_RATE_LIMITED", "คำขอมากเกินไป กรุณาลองใหม่ภายหลัง", headers={"Retry-After": "1"})
    if message in _NOT_READY or message in {'GIS_LDD_PUBLICATION_DISABLED','GIS_GEOTIFF_PUBLICATION_DISABLED'}:
        return gis_error(503, message, "ระบบ GIS หรือ Sandbox Gate ยังไม่พร้อมใช้งาน")
    return gis_error(503, "GIS_UNAVAILABLE", "บริการ GIS ยังไม่พร้อมใช้งาน กรุณาลองใหม่ภายหลัง")


def decode_cursor(value: str | None) -> dict | None:
    if value is None:
        return None
    try:
        if not value or len(value) > 512 or not re.fullmatch(r"[A-Za-z0-9_-]+={0,2}", value):
            raise ValueError("invalid cursor")
        decoded = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
        # json.load normally accepts duplicate names; reject ambiguous cursor fields.
        def pairs(items):
            data = {}
            for key, item in items:
                if key in data:
                    raise ValueError("duplicate cursor field")
                data[key] = item
            return data
        parsed = PageCursor.model_validate(json.loads(decoded, object_pairs_hook=pairs))
        return parsed.model_dump(mode="json")
    except (ValueError, TypeError, UnicodeError):
        raise gis_error(422, "GIS_INVALID_CURSOR", "Cursor ไม่ถูกต้อง") from None


def encode_cursor(value: dict) -> str:
    cursor = PageCursor.model_validate(value).model_dump(mode="json")
    raw = json.dumps(cursor, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


class GisService:
    def __init__(self, runtime):
        self.runtime = runtime

    def _rpc(self, name: str, parameters: dict):
        try:
            return self.runtime.rpc(name, parameters)
        except HTTPException:
            raise
        except Exception as error:
            raise map_rpc_error(error) from None

    def read(self, actor: str, kind: str, payload: dict | None = None):
        result = self._rpc("gis_read", {"p_actor": str(UUID(actor)), "p_kind": kind,
            "p_payload": jsonable_encoder(payload or {})})
        if not isinstance(result, dict):
            raise gis_error(503, "GIS_INVALID_RESPONSE", "บริการ GIS ส่งข้อมูลไม่สมบูรณ์")
        result = safe_output(result)
        if kind == "me":
            database_gate = result.get("activation_enabled") is True
            backend_gate = self.runtime.sandbox_activation_enabled is True
            result["database_activation_enabled"] = database_gate
            result["backend_activation_enabled"] = backend_gate
            result["activation_enabled"] = database_gate and backend_gate
        if result.get("next_cursor") is not None:
            try:
                result["next_cursor"] = encode_cursor(result["next_cursor"])
            except (ValueError, TypeError):
                raise gis_error(503, "GIS_INVALID_RESPONSE", "บริการ GIS ส่งข้อมูลไม่สมบูรณ์") from None
        return result

    def command(self, actor: str, key: UUID, operation: str, payload: dict):
        return self._command("gis_command", actor, key, operation, payload)

    def ldd_command(self, actor: str, key: UUID, operation: str, payload: dict):
        return self._command("gis_ldd_command", actor, key, operation, payload)

    def ldd_read(self, actor: str, upload_id: UUID):
        return safe_output(self._rpc("gis_ldd_read", {"p_actor": str(UUID(actor)), "p_upload_id": str(upload_id)}))

    def geotiff_command(self, actor: str, key: UUID, operation: str, payload: dict):
        return self._command('gis_geotiff_command', actor, key, operation, payload)

    def geotiff_read(self, actor: str, upload_id: UUID):
        return safe_output(self._rpc('gis_geotiff_read', {'p_actor': str(UUID(actor)), 'p_upload_id': str(upload_id)}))

    def processing_command(self, actor: str, key: UUID, operation: str, payload: dict):
        return self._command('gis_processing_command', actor, key, operation, payload)

    def processing_read(self, actor: str, kind: str, payload: dict | None = None):
        result = self._rpc('gis_processing_read', {'p_actor': str(UUID(actor)), 'p_kind': kind,
            'p_payload': jsonable_encoder(payload or {})})
        if not isinstance(result, dict):
            raise gis_error(503, 'GIS_INVALID_RESPONSE', 'บริการประมวลผลส่งข้อมูลไม่สมบูรณ์')
        result = safe_output(result)
        if result.get('next_cursor') is not None:
            result['next_cursor'] = encode_cursor(result['next_cursor'])
        return result

    def _command(self, rpc: str, actor: str, key: UUID, operation: str, payload: dict):
        result = self._rpc(rpc, {"p_actor": str(UUID(actor)), "p_request_id": str(key),
            "p_operation": operation, "p_payload": jsonable_encoder(payload),
            "p_backend_sandbox": self.runtime.sandbox_activation_enabled is True})
        if (not isinstance(result, dict) or type(result.get("status")) is not int
                or result["status"] not in {200, 201, 202} or not isinstance(result.get("body"), dict)):
            raise gis_error(503, "GIS_INVALID_RESPONSE", "บริการ GIS ส่งข้อมูลไม่สมบูรณ์")
        return JSONResponse(status_code=result["status"], content=safe_output(result["body"]))
