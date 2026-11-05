"""Explicit, signed, memory-only credential delivery. Never discovers credentials.

The signature is the approved delivery broker's attestation, NOT a Google
signature. A real broker must verify the identity when minting the short-lived
token. No broker, key, token, ADC or renewal service is installed here.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import math
import time

from gis_worker.gee_live_contracts import canonical

PROJECT_ID = 'green-area-gis-sandbox'
PROJECT_NUMBER = '977478562022'
PRINCIPAL = 'gis-gee-smoke-worker@green-area-gis-sandbox.iam.gserviceaccount.com'
PRINCIPAL_ID = '103297967369976617173'


class GenuineBoundaryError(ValueError):
    pass


def target(project):
    if (project.project_id, project.project_number, project.principal,
        project.readiness) != (PROJECT_ID, PROJECT_NUMBER, PRINCIPAL, 'verified_sandbox'):
        raise GenuineBoundaryError('GEE_GENUINE_IDENTITY_REJECTED')


@dataclass(frozen=True, repr=False)
class CredentialDelivery:
    # Bytes remain in the explicit parent channel; never put this in a job,
    # environment variable, argument, file, exception, RPC or log.
    token: bytes = field(repr=False)
    project_id: str
    project_number: str
    principal: str
    principal_id: str
    issued_at: int
    expires_at: int
    binding_sha256: str
    signature: bytes = field(repr=False)

    def __repr__(self):
        return '<CredentialDelivery redacted>'

    def signed_message(self):
        return canonical({'project_id': self.project_id,
            'project_number': self.project_number, 'principal': self.principal,
            'principal_id': self.principal_id, 'issued_at': self.issued_at,
            'expires_at': self.expires_at, 'binding_sha256': self.binding_sha256,
            'token_sha256': hashlib.sha256(self.token).hexdigest()}).encode()


class ExplicitGoogleCredentials:
    """Consume one broker-attested delivery; no implicit refresh or token issue.

    issuer_key is pinned in trusted runtime configuration, never API/job input.
    Each authorize checks both wall and monotonic clocks. Renewal requires an
    explicitly delivered, freshly signed replacement for the exact same binding.
    """
    def __init__(self, delivery, binding, *, issuer_key, wall=time.time, monotonic=time.monotonic):
        self._wall, self._monotonic = wall, monotonic
        self._binding = binding.fingerprint()
        self._issuer_key = bytes(issuer_key)
        self._token = bytearray()
        self._install(delivery, binding)

    def __repr__(self):
        return '<ExplicitGoogleCredentials redacted>'

    def _install(self, delivery, binding):
        target(binding.project)
        if (type(delivery) is not CredentialDelivery or len(self._issuer_key) != 32
            or type(delivery.token) is not bytes or not 16 <= len(delivery.token) <= 8192
            or any(c <= 32 or c >= 127 for c in delivery.token)
            or (delivery.project_id, delivery.project_number, delivery.principal, delivery.principal_id)
                != (PROJECT_ID, PROJECT_NUMBER, PRINCIPAL, PRINCIPAL_ID)
            or type(delivery.issued_at) is not int or type(delivery.expires_at) is not int
            or not 0 < delivery.expires_at - delivery.issued_at <= 1800
            or binding.fingerprint() != self._binding
            or delivery.binding_sha256 != self._binding):
            raise GenuineBoundaryError('GEE_CREDENTIAL_DELIVERY_REJECTED')
        now = self._wall()
        if not math.isfinite(now) or delivery.issued_at > now or delivery.expires_at <= now + 5:
            raise GenuineBoundaryError('GEE_CREDENTIAL_EXPIRED')
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
            Ed25519PublicKey.from_public_bytes(self._issuer_key).verify(delivery.signature, delivery.signed_message())
        except Exception:
            raise GenuineBoundaryError('GEE_CREDENTIAL_ATTESTATION_REJECTED') from None
        self.close()
        self._token = bytearray(delivery.token)
        self._expiry = delivery.expires_at
        self._deadline = self._monotonic() + delivery.expires_at - now

    def authorize(self, binding):
        target(binding.project)
        if binding.fingerprint() != self._binding or not self._token:
            raise GenuineBoundaryError('GEE_CREDENTIAL_BINDING_REJECTED')
        if self._wall() >= self._expiry - 5 or self._monotonic() >= self._deadline - 5:
            self.close()
            raise GenuineBoundaryError('GEE_CREDENTIAL_EXPIRED')

    def headers(self, binding):
        self.authorize(binding)
        return {'Authorization': 'Bearer ' + bytes(self._token).decode('ascii')}

    def remaining(self, binding):
        self.authorize(binding)
        return min(self._expiry - self._wall(), self._deadline - self._monotonic()) - 5

    def replace(self, delivery, binding):
        self.authorize(binding)
        if delivery.issued_at <= self._wall() - 30 or delivery.expires_at <= self._expiry:
            raise GenuineBoundaryError('GEE_CREDENTIAL_RENEWAL_REJECTED')
        self._install(delivery, binding)

    def sdk_credentials(self, binding):
        # Explicitly non-refreshing credentials. No Google auth discovery calls.
        from google.auth.credentials import Credentials
        parent = self
        class BoundCredentials(Credentials):
            def refresh(self, request):
                raise GenuineBoundaryError('GEE_EXPLICIT_REDELIVERY_REQUIRED')

            def apply(self, headers, token=None):
                headers.update(parent.headers(binding))

            def before_request(self, request, method, url, headers):
                self.apply(headers)

        return BoundCredentials()

    def close(self):
        self._token[:] = b'\x00' * len(self._token)
        self._token.clear()

