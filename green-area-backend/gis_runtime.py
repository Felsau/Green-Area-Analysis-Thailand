"""GIS-only trust boundary; no legacy dependencies/dotenv/GEE imports.

The only supported T2 target is the explicitly attested T0 local sandbox. No
environment or credential files are loaded. Supabase Auth verifies the signature;
strict issuer/audience/time/sub checks are additionally enforced here.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
import time
from typing import Callable
from uuid import UUID

from fastapi import Header, HTTPException, Request
import httpx
import jwt

LOCAL_URL = "http://127.0.0.1:55421"
LOCAL_ISSUER = LOCAL_URL + "/auth/v1"
REQUIRED_VERSIONS = {27, 28, 29, 30}


def unavailable() -> HTTPException:
    return HTTPException(503, detail={"code": "GIS_NOT_READY", "message": "GIS local sandbox is not ready", "fields": []})


def unauthenticated() -> HTTPException:
    return HTTPException(401, detail={"code": "GIS_UNAUTHENTICATED", "message": "A valid user session is required", "fields": []}, headers={"WWW-Authenticate": "Bearer"})


@dataclass(frozen=True)
class LocalGISSettings:
    enabled: bool = False
    api_url: str = LOCAL_URL
    database: str = "postgres"
    cluster: str = "green-area-gis-t0"
    mode: str = "local_synthetic"
    runtime_instance: str = ""
    baseline_fingerprint: str = ""
    sandbox_activation_enabled: bool = False
    ldd_publication_enabled: bool = False

    def validate(self):
        if (type(self.enabled) is not bool or type(self.sandbox_activation_enabled) is not bool
                or type(self.ldd_publication_enabled) is not bool
                or (self.ldd_publication_enabled and self.sandbox_activation_enabled)
                or self.api_url != LOCAL_URL or self.database != "postgres"
                or self.cluster != "green-area-gis-t0" or self.mode != "local_synthetic"
                or not re.fullmatch(r"[a-f0-9]{32}", self.runtime_instance)
                or not re.fullmatch(r"[a-f0-9]{64}", self.baseline_fingerprint)):
            raise unavailable()


class GISRuntime:
    def __init__(self, settings: LocalGISSettings | None = None, *, attest: Callable | None = None,
                 clients: Callable | None = None):
        self.settings = settings or LocalGISSettings()
        self.sandbox_activation_enabled = self.settings.sandbox_activation_enabled
        self.ldd_publication_enabled = self.settings.ldd_publication_enabled
        self._attest = attest
        self._auth = self._service = None
        if self.settings.enabled:
            self.settings.validate()
            self._verify_transport()
            if clients is None:
                raise unavailable()
            # Credentials are only obtained after the fixed target is attested.
            self._auth, self._service = clients(self.settings.api_url)

    def _verify_transport(self):
        self.settings.validate()
        if not self.settings.enabled or self._attest is None:
            raise unavailable()
        try:
            proof = self._attest()
            if (proof.get("database") != self.settings.database or proof.get("cluster") != self.settings.cluster
                    or proof.get("instance") != self.settings.runtime_instance
                    or proof.get("baseline_fingerprint") != self.settings.baseline_fingerprint
                    or proof.get("containers_healthy") is not True):
                raise unavailable()
        except HTTPException:
            raise
        except Exception:
            raise unavailable() from None

    def require_ready(self):
        self._verify_transport()
        if self._service is None:
            raise unavailable()
        try:
            value = self._service.rpc("gis_readiness", {}).execute().data
            if (not isinstance(value, dict) or value.get("runtime_instance") != self.settings.runtime_instance
                    or value.get("database_name") != self.settings.database
                    or value.get("cluster_name") != self.settings.cluster
                    or value.get("mode") != self.settings.mode
                    or value.get("baseline_fingerprint") != self.settings.baseline_fingerprint
                    or not REQUIRED_VERSIONS <= set(value.get("migration_versions", []))
                    or value.get("contract_version") != "1.1.0-t2"):
                raise unavailable()
            return value
        except HTTPException:
            raise
        except Exception:
            raise unavailable() from None

    def verify_user_token(self, token: str) -> str:
        self.require_ready()
        if not isinstance(token, str) or not 20 <= len(token) <= 8192:
            raise unauthenticated()
        try:
            header = jwt.get_unverified_header(token)
            if header.get("alg") not in {"HS256", "RS256", "ES256"}:
                raise ValueError()
            # These unverified claims are NOT identity proof. The trusted Auth
            # endpoint below verifies the signature and must return the same ID.
            claims = jwt.decode(token, options={"verify_signature": False,
                "verify_exp": True, "verify_nbf": True, "verify_iat": True,
                "verify_aud": True, "verify_iss": True,
                "require": ["iss", "aud", "exp", "iat", "sub", "role"]},
                audience="authenticated", issuer=LOCAL_ISSUER)
            actor = str(UUID(claims["sub"]))
            if (claims["sub"] != actor or claims.get("role") != "authenticated"
                    or claims.get("aud") not in ("authenticated", ["authenticated"])
                    or claims.get("is_anonymous", False) is not False
                    or type(claims["exp"]) is not int or type(claims["iat"]) is not int
                    or claims["exp"] <= claims["iat"]
                    or ("nbf" in claims and type(claims["nbf"]) is not int)):
                raise ValueError()
        except (jwt.InvalidTokenError, ValueError, TypeError, KeyError, RecursionError, OverflowError):
            raise unauthenticated() from None
        try:
            response = self._auth.auth.get_user(token)
        except httpx.HTTPError:
            raise unavailable() from None
        except Exception as error:
            # Do not stringify SDK exceptions or return upstream response bodies.
            status = getattr(error, "status", None) or getattr(error, "status_code", None)
            if str(status) in {"400", "401", "403", "404", "422"}:
                raise unauthenticated() from None
            raise unavailable() from None
        user = getattr(response, "user", None)
        if user is None or str(getattr(user, "id", "")) != actor:
            raise unauthenticated()
        return actor

    def rpc(self, name: str, params: dict):
        if name not in {"gis_command", "gis_read", "gis_ldd_command", "gis_ldd_read", "gis_processing_command", "gis_processing_read", "gis_geotiff_command", "gis_geotiff_read",
                "gis_gee_mock_command", "gis_gee_mock_read",
                "gis_ldd_prepare_command", "gis_ldd_prepare_read", "gis_ldd_verify_complete", "gis_ldd_verify_revoke",
                "gis_ldd_publication_command", "gis_ldd_published_read", "gis_ldd_published_unavailable",
                "gis_geotiff_prepare_command", "gis_geotiff_prepare_read", "gis_geotiff_verify_complete", "gis_geotiff_verify_revoke",
                "gis_geotiff_publication_command", "gis_geotiff_publication_status", "gis_geotiff_published_read", "gis_geotiff_published_unavailable"}:
            raise unavailable()
        for attempt in range(2):
            self.require_ready()  # Repeat target check before a possible retry too.
            try:
                return self._service.rpc(name, params).execute().data
            except (httpx.TransportError, httpx.TimeoutException):
                if attempt:
                    raise unavailable() from None
        raise unavailable()


def require_gis_user(request: Request, authorization: str | None = Header(default=None)) -> str:
    service = getattr(request.app.state, "gis_service", None)
    if service is None:
        raise unavailable()
    if (len(request.headers.getlist("authorization")) != 1 or not authorization
            or not authorization.lower().startswith("bearer ")):
        service.runtime.require_ready()
        raise unauthenticated()
    # verify_user_token proves the target before Auth, and rpc proves it again
    # before the SQL operation. Do not duplicate the first proof here.
    return service.runtime.verify_user_token(authorization.split(" ", 1)[1].strip())
