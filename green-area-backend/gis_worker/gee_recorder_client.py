"""Dedicated authenticated Recorder SQL client for SQL047 contracts.

Recorder uses this client to record receipts and seal execution on the approved
local SQL gateway while external HTTPS stays restricted by the pinned nft policy.
The destination is a fixed RFC1918 IP literal bound to the same supervisor-owned
``gateway_endpoint`` that the nft rules allow; there is no DNS or hostname.

Worker cannot use this client: its JWT role is gis_gee_https_worker and its seccomp
filter denies all AF_INET socket creation. SQL047 grants the Recorder role EXECUTE
only on ``gis_gee_https_recorder(text,jsonb)``; readiness is its ``readiness`` action.
runtime_instance/baseline_fingerprint are NOT returned by that RPC, so they are only
format-checked bootstrap values here, never claimed as verified against SQL.
"""
from __future__ import annotations
import base64
import ipaddress
import json
import re
import threading
import time
from urllib import request as http, error as http_error
from urllib.parse import urlsplit
from uuid import UUID

from gis_worker.gee_genuine_identity import GenuineBoundaryError
from gis_worker.gee_restricted_network import validate_gateway_endpoint

ISSUER = 'http://127.0.0.1:55421/auth/v1'  # must equal gis_worker.worker.ISSUER
ALLOWED_ACTIONS = ('reserve', 'attempted', 'response', 'uncertain', 'seal')
RPC_PATH = '/rest/v1/rpc/gis_gee_https_recorder'
REFRESH_PATH = '/auth/v1/token?grant_type=refresh_token'
READINESS_KEYS = {'subject', 'mode', 'live_enabled', 'genuine_completion_enabled'}


class _NoRedirect(http.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise GenuineBoundaryError('GEE_RECORDER_REDIRECT_REJECTED')


class RecorderSQLClient:
    JWT_ROLE = 'gis_gee_https_recorder'

    def __init__(self, bootstrap: dict, *, gateway_endpoint: tuple, opener=None):
        keys = {'api_url', 'subject', 'anon_key', 'access_token', 'refresh_token',
                'runtime_instance', 'baseline_fingerprint'}
        if not isinstance(bootstrap, dict) or set(bootstrap) != keys:
            raise GenuineBoundaryError('GEE_RECORDER_BOOTSTRAP_REJECTED')
        host, port = validate_gateway_endpoint(gateway_endpoint)
        api_url = bootstrap['api_url']
        # Exact textual form: http://<ip>:8000 and nothing else (no userinfo, path,
        # query, fragment, hostname, alternate IP spelling or scheme).
        if api_url != f'http://{host}:{port}':
            raise GenuineBoundaryError('GEE_RECORDER_TARGET_REJECTED')
        parts = urlsplit(api_url)
        if (parts.scheme != 'http' or parts.hostname != host or parts.port != port
            or parts.username is not None or parts.password is not None
            or parts.path or parts.query or parts.fragment
            or ipaddress.IPv4Address(parts.hostname) != ipaddress.IPv4Address(host)):
            raise GenuineBoundaryError('GEE_RECORDER_TARGET_REJECTED')
        self.api_url = api_url
        try:
            self.subject = str(UUID(bootstrap['subject']))
        except Exception:
            raise GenuineBoundaryError('GEE_RECORDER_TARGET_REJECTED') from None
        if (not re.fullmatch('[a-f0-9]{32}', str(bootstrap['runtime_instance']))
            or not re.fullmatch('[a-f0-9]{64}', str(bootstrap['baseline_fingerprint']))):
            raise GenuineBoundaryError('GEE_RECORDER_TARGET_REJECTED')
        if any(type(bootstrap[k]) is not str or not bootstrap[k]
            for k in ('anon_key', 'access_token', 'refresh_token')):
            raise GenuineBoundaryError('GEE_RECORDER_BOOTSTRAP_REJECTED')
        self._anon = bootstrap['anon_key']
        self._access = bootstrap['access_token']
        self._refresh = bootstrap['refresh_token']
        self._lock = threading.RLock()
        self._opener = opener or http.build_opener(http.ProxyHandler({}), _NoRedirect())
        self._claims(self._access)

    def __repr__(self):
        return '<RecorderSQLClient redacted>'

    def _claims(self, token: str) -> dict:
        # Routing sanity only; PostgREST verifies the signature and SQL047 re-checks role.
        try:
            part = token.split('.')[1]
            c = json.loads(base64.urlsafe_b64decode(part + '=' * (-len(part) % 4)))
            if (c.get('sub') != self.subject
                or c.get('role') != self.JWT_ROLE
                or c.get('iss') != ISSUER
                or type(c.get('exp')) is not int):
                raise ValueError()
            return c
        except Exception:
            raise GenuineBoundaryError('GEE_RECORDER_IDENTITY_REJECTED') from None

    def _request(self, path: str, payload: dict, access: str) -> dict:
        if path not in (RPC_PATH, REFRESH_PATH):
            raise GenuineBoundaryError('GEE_RECORDER_RPC_REJECTED')
        raw = json.dumps(payload, allow_nan=False, separators=(',', ':')).encode()
        if len(raw) > 65536:
            raise GenuineBoundaryError('GEE_RECORDER_REQUEST_LIMIT')
        req = http.Request(
            self.api_url + path,
            data=raw,
            method='POST',
            headers={
                'apikey': self._anon,
                'Authorization': 'Bearer ' + access,
                'Content-Type': 'application/json'
            }
        )
        try:
            with self._opener.open(req, timeout=5) as r:
                value = r.read(65537)
            if len(value) > 65536:
                raise GenuineBoundaryError('GEE_RECORDER_RESPONSE_LIMIT')
            return json.loads(value)
        except GenuineBoundaryError:
            raise
        except http_error.HTTPError as e:
            try:
                code = json.loads(e.read(2048)).get('message', '')
            except Exception:
                code = ''
            raise GenuineBoundaryError(
                code if re.fullmatch('GIS_[A-Z0-9_]+', code) else 'GEE_RECORDER_HTTP_DENIED'
            ) from None
        except Exception:
            raise GenuineBoundaryError('GEE_RECORDER_TRANSPORT_FAILED') from None

    def readiness(self) -> dict:
        """SQL047 ``https_record('readiness')``: payload must be exactly ``{}``."""
        with self._lock:
            access = self._fresh_access()
        value = self._request(RPC_PATH, {'p_action': 'readiness', 'p_payload': {}}, access)
        if (not isinstance(value, dict) or set(value) != READINESS_KEYS
            or value['subject'] != self.subject or value['mode'] != 'google_https'
            or value['live_enabled'] is not False
            or value['genuine_completion_enabled'] is not False):
            raise GenuineBoundaryError('GEE_RECORDER_TARGET_REJECTED')
        return value

    def _fresh_access(self) -> str:
        if self._claims(self._access)['exp'] - time.time() < 60:
            r = self._request(REFRESH_PATH, {'refresh_token': self._refresh}, self._access)
            try:
                access, refresh = r['access_token'], r['refresh_token']
                if (type(access) is not str or type(refresh) is not str
                    or self._claims(access)['exp'] - time.time() < 60):
                    raise ValueError()
            except GenuineBoundaryError:
                raise
            except Exception:
                raise GenuineBoundaryError('GEE_RECORDER_IDENTITY_REJECTED') from None
            self._access, self._refresh = access, refresh
        return self._access

    def record(self, action: str, payload: dict | None = None) -> dict:
        if action not in ALLOWED_ACTIONS:
            raise GenuineBoundaryError('GEE_RECORDER_ACTION_REJECTED')
        payload = payload or {}
        if not isinstance(payload, dict):
            raise GenuineBoundaryError('GEE_RECORDER_PAYLOAD_REJECTED')
        with self._lock:
            access = self._fresh_access()
        return self._request(RPC_PATH, {'p_action': action, 'p_payload': payload}, access)

    def __call__(self, action: str, payload: dict | None = None) -> dict:
        """Enables direct use as the `recorder` callable in GenuinePhysicalHTTP."""
        return self.record(action, payload)
