"""Operator-mediated mint observation contract, never a token issuer.

An access token is opaque: offline parsing cannot prove its Google identity.
The real observation connector remains disabled. Only an independently pinned,
authenticated broker may attest an observed IAM mint exchange in a future run.
No stdin/paste, ADC, token file, environment or command-line fallback exists.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import re
import time

from gis_worker.gee_genuine_identity import (CredentialDelivery, ExplicitGoogleCredentials,
    GenuineBoundaryError, PROJECT_ID, PROJECT_NUMBER, PRINCIPAL, PRINCIPAL_ID)
from gis_worker.gee_live_contracts import canonical

MINT_URL = ('https://iamcredentials.googleapis.com/v1/projects/-/serviceAccounts/'
    + PRINCIPAL + ':generateAccessToken')
# Supported scope from the pinned SDK's ee/oauth.py. Effective read privileges
# remain the Sandbox IAM viewer binding; no invented readonly OAuth scope.
SCOPES = ['https://www.googleapis.com/auth/earthengine']


@dataclass(frozen=True, repr=False)
class MintObservation:
    """Signed by a separately trusted observer, not by Google or the worker.

    Metadata GET and mint response must be observed on authenticated HTTPS by
    that observer. Merely constructing this object is NOT mint-time proof.
    """
    token: bytes = field(repr=False)
    request_url: str
    request_body: dict
    service_account: dict
    response_expire_time: str
    observed_at: int
    nonce: str
    binding_sha256: str
    signature: bytes = field(repr=False)

    def __repr__(self):
        return '<MintObservation redacted>'

    def message(self):
        return canonical({'token_sha256': hashlib.sha256(self.token).hexdigest(),
            'request_url': self.request_url, 'request_body': self.request_body,
            'service_account': self.service_account, 'response_expire_time': self.response_expire_time,
            'observed_at': self.observed_at, 'nonce': self.nonce,
            'binding_sha256': self.binding_sha256}).encode()


class OperatorDelivery:
    """One explicit, challenge-bound handoff to the Recorder process only.

    Keys/challenge/binding come from trusted supervisor configuration, never a
    job. The signing callback is local broker authority, never the worker.
    Real observation/issuer provisioning is deliberately absent.
    """
    def __init__(self, *, binding, observer_key, issuer, challenge, wall=time.time):
        if (type(observer_key) is not bytes or len(observer_key) != 32
            or type(challenge) is not str or len(challenge) != 64
            or any(c not in '0123456789abcdef' for c in challenge)):
            raise GenuineBoundaryError('GEE_OPERATOR_CONFIGURATION_REJECTED')
        self.binding, self.key, self.issuer = binding, observer_key, issuer
        self.challenge, self.wall, self.used = challenge, wall, False

    def deliver(self, observation):
        if self.used:
            raise GenuineBoundaryError('GEE_OPERATOR_DELIVERY_REPLAY')
        # Consume even an invalid exchange. Retrying needs a new supervisor challenge.
        self.used = True
        try:
            if type(observation) is not MintObservation:
                raise ValueError()
            o = observation
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
            Ed25519PublicKey.from_public_bytes(self.key).verify(o.signature, o.message())
            if (o.nonce != self.challenge or o.binding_sha256 != self.binding.fingerprint()
                or o.request_url != MINT_URL
                or o.request_body != {'scope': SCOPES, 'lifetime': '1800s'}
                or o.service_account != {'projectId': PROJECT_ID, 'email': PRINCIPAL,
                    'uniqueId': PRINCIPAL_ID, 'disabled': False}
                or type(o.observed_at) is not int or not 0 <= self.wall() - o.observed_at <= 15
                or type(o.token) is not bytes or not 16 <= len(o.token) <= 8192
                or any(c <= 32 or c >= 127 for c in o.token)):
                raise ValueError()
            # Explicit timezone required, no naive/locale-dependent timestamp.
            if not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?Z',o.response_expire_time):
                raise ValueError()
            expiry = datetime.fromisoformat(o.response_expire_time[:-1] + '+00:00').timestamp()
            # Floor fractional RFC3339 expiry; never round validity upwards.
            expiry=int(expiry)
            if not 5 < expiry - self.wall() <= 1800:
                raise ValueError()
            packet = CredentialDelivery(o.token, PROJECT_ID, PROJECT_NUMBER, PRINCIPAL,
                PRINCIPAL_ID, o.observed_at, int(expiry), o.binding_sha256, b'')
            from dataclasses import replace
            return replace(packet, signature=self.issuer(packet.signed_message()))
        except Exception:
            # Never propagate upstream errors containing the mint response/token.
            raise GenuineBoundaryError('GEE_OPERATOR_OBSERVATION_REJECTED') from None


def observe_real_mint(*args, **kwargs):
    # No IAM call, OAuth, ADC or impersonation implementation is authorized here.
    raise GenuineBoundaryError('GEE_REAL_MINT_OBSERVER_NOT_VERIFIED')
