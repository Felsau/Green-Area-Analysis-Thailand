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
import secrets
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


HELLO_KEYS = {'version', 'action', 'binding', 'nonce', 'sent_at'}
CREDENTIAL_KEYS = {'version', 'action', 'nonce', 'token', 'project_id', 'project_number',
    'principal', 'principal_id', 'issued_at', 'expires_at', 'binding_sha256', 'signature'}
HELLO_TOLERANCE = 30
_SEEN_HELLOS: dict = {}


def _hex(value, length):
    return (type(value) is str and len(value) == length
        and all(c in '0123456789abcdef' for c in value))


def _consume_hello(nonce, now):
    # Replay ledger for the supervisor process: a hello nonce is single-use.
    for old in [k for k, expiry in _SEEN_HELLOS.items() if expiry <= now]:
        del _SEEN_HELLOS[old]
    if nonce in _SEEN_HELLOS or len(_SEEN_HELLOS) >= 256:
        raise ValueError()
    _SEEN_HELLOS[nonce] = now + 2 * HELLO_TOLERANCE


def deliver_credential(endpoint, delivery, *, binding, recorder_pid: int, recorder_uid: int,
    timeout: float = 30, wall=time.time):
    """Supervisor side. The token is sent only after the Recorder proved itself.

    A socketpair has no meaningful SO_PEERCRED for the remote end, so identity is
    established by a Recorder-initiated hello whose kernel SCM_CREDENTIALS must equal
    the pinned non-root (recorder_pid, recorder_uid). The hello is bound to this
    binding, fresh (+-30 s) and single-use; its nonce is echoed inside the credential
    packet. Any failure sends nothing and closes the endpoint; errors never carry
    token material and are raised outside the handler, so no exception context or
    frame chain is attached. Memory-only; the endpoint is always closed.
    """
    delivered = False
    try:
        if (type(delivery) is not CredentialDelivery or type(delivery.token) is not bytes
            or not 16 <= len(delivery.token) <= 8192 or any(c <= 32 or c >= 127 for c in delivery.token)
            or type(recorder_pid) is not int or recorder_pid <= 0
            or type(recorder_uid) is not int or recorder_uid <= 0
            or delivery.binding_sha256 != binding.fingerprint()):
            raise ValueError()
        from gis_worker.gee_recorder_channel import receive, send
        hello = receive(endpoint, pid=recorder_pid, uid=recorder_uid, timeout=timeout)
        now = wall()
        if (set(hello) != HELLO_KEYS or hello['version'] != 1
            or hello['action'] != 'credential_hello'
            or hello['binding'] != binding.fingerprint() or not _hex(hello['nonce'], 64)
            or type(hello['sent_at']) is not int
            or abs(now - hello['sent_at']) > HELLO_TOLERANCE):
            raise ValueError()
        _consume_hello(hello['nonce'], now)
        send(endpoint, {
            'version': 1,
            'action': 'deliver_credential',
            'nonce': hello['nonce'],
            'token': delivery.token.decode('ascii'),
            'project_id': delivery.project_id,
            'project_number': delivery.project_number,
            'principal': delivery.principal,
            'principal_id': delivery.principal_id,
            'issued_at': delivery.issued_at,
            'expires_at': delivery.expires_at,
            'binding_sha256': delivery.binding_sha256,
            'signature': delivery.signature.hex(),
        })
        delivered = True
    except Exception:
        delivered = False
    finally:
        endpoint.close()
    if not delivered:
        raise GenuineBoundaryError('GEE_CREDENTIAL_DELIVERY_REJECTED')


def receive_credential(endpoint, *, supervisor_pid: int, supervisor_uid: int, binding,
    issuer_key: bytes, timeout: float = 30, wall=time.time):
    """Recorder side. Sends a fresh hello, then accepts exactly one matching packet.

    The only path that may accept a root peer (the supervisor), and only when the
    kernel-reported (pid, uid) equals the pinned supervisor identity. The packet must
    have exactly the CREDENTIAL_KEYS, echo this hello's nonce and match the binding
    and pinned sandbox identity; the broker signature is then verified by
    ExplicitGoogleCredentials. The endpoint is closed on every outcome, and a
    rejection carries no exception context or token-bearing locals.
    """
    from gis_worker.gee_recorder_channel import receive, send
    from gis_worker.gee_genuine_identity import ExplicitGoogleCredentials
    credentials = value = delivery = None
    try:
        if type(supervisor_uid) is not int or supervisor_uid < 0:
            raise ValueError()
        nonce = secrets.token_hex(32)
        send(endpoint, {'version': 1, 'action': 'credential_hello', 'binding': binding.fingerprint(),
            'nonce': nonce, 'sent_at': int(wall())})
        value = receive(endpoint, pid=supervisor_pid, uid=supervisor_uid, timeout=timeout,
            allow_root=True)
        now = wall()
        if (set(value) != CREDENTIAL_KEYS or value['version'] != 1
            or value['action'] != 'deliver_credential' or value['nonce'] != nonce
            or value['project_id'] != binding.project.project_id
            or value['project_id'] != PROJECT_ID
            or value['project_number'] != PROJECT_NUMBER
            or value['principal'] != binding.project.principal
            or value['principal'] != PRINCIPAL
            or value['principal_id'] != binding.principal_id
            or value['principal_id'] != PRINCIPAL_ID
            or value['binding_sha256'] != binding.fingerprint()
            or type(value['token']) is not str or not 16 <= len(value['token']) <= 8192
            or any(not 33 <= ord(c) <= 126 for c in value['token'])
            or type(value['issued_at']) is not int or value['issued_at'] > now
            or type(value['expires_at']) is not int or value['expires_at'] <= now
            or not 0 <= now - value['issued_at'] <= 300
            or not _hex(value['signature'], 128)):
            raise ValueError()
        delivery = CredentialDelivery(
            value['token'].encode('ascii'),
            value['project_id'],
            value['project_number'],
            value['principal'],
            value['principal_id'],
            value['issued_at'],
            value['expires_at'],
            value['binding_sha256'],
            bytes.fromhex(value['signature'])
        )
        credentials = ExplicitGoogleCredentials(delivery, binding, issuer_key=issuer_key, wall=wall)
    except Exception:
        credentials = None
    finally:
        value = delivery = None  # drop token-bearing locals before any raise
        endpoint.close()
    if credentials is None:
        raise GenuineBoundaryError('GEE_CREDENTIAL_DELIVERY_REJECTED')
    return credentials
