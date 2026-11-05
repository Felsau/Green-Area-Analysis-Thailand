"""Offline credential-delivery contract. Never Google auth, ADC or token IO.

Fake leases are trusted test capabilities, not a sandbox against hostile Python.
The real credential channel and the real project allowlist remain closed.
"""
from dataclasses import dataclass, field
import hashlib
import time
from typing import Annotated
from uuid import UUID, uuid4

from pydantic import Field

from gis_worker.gee_contracts import Contract, Hash
from gis_worker.gee_live_contracts import Project, Request, digest, geometry_digest


class CredentialBoundaryError(ValueError):
    pass


class RuntimeBinding(Contract):
    worker_subject: UUID
    session_id: UUID
    job_id: UUID
    attempt_number: Annotated[int, Field(strict=True, ge=1, le=2)]
    project: Project
    input_revision: Annotated[int, Field(strict=True, ge=1)]
    input_hash: Hash
    request_sha256: Hash
    method_sha256: Hash
    geometry_sha256: Hash
    lease_sha256: Hash
    policy_sha256: Hash

    @classmethod
    def from_claim(cls, job, trusted_subject):
        """Subject comes from the verified parent client, never job authority."""
        subject = UUID(str(trusted_subject))
        request = Request.model_validate(job['request'])
        if (request.execution != 'injected'
            or job.get('manifest', {}).get('schema_version') != 8
            or job.get('manifest', {}).get('provider') != 'gee_safety_rehearsal'
            or str(subject) != job.get('worker_id')
            or request.input_revision != job.get('input_revision')
            or request.request_hash() != job.get('semantic_request_sha256')
            or request.scope.geometry_sha256 != geometry_digest(job['geometry'])
            or job.get('session_id') != job.get('manifest', {}).get('session_id')
            or job.get('policy_sha256') != job.get('manifest', {}).get('policy_sha256')):
            raise CredentialBoundaryError('GEE_RUNTIME_CONTEXT_REJECTED')
        return cls(worker_subject=subject, session_id=job['session_id'], job_id=job['id'],
            attempt_number=job['attempt_number'], project=request.project,
            input_revision=job['input_revision'], input_hash=job['input_hash'],
            request_sha256=request.request_hash(),
            method_sha256=digest(request.method.model_dump(mode='json')),
            geometry_sha256=request.scope.geometry_sha256,
            lease_sha256=hashlib.sha256(UUID(job['lease_token']).bytes).hexdigest(),
            policy_sha256=job['policy_sha256'])

    def fingerprint(self):
        return digest(self.model_dump(mode='json'))


class DisabledGoogleCredentials:
    """Future interface only. No real credentials can be issued or discovered."""
    APPROVED_PROJECTS = ()
    APPROVED_PRINCIPAL = None

    def issue(self, *args, **kwargs):
        raise CredentialBoundaryError('GEE_GOOGLE_CREDENTIAL_DELIVERY_DISABLED')

    renew = issue
    revoke = issue
    authorize = issue


@dataclass(frozen=True, repr=False)
class FakeGoogleLease:
    """Opaque in-memory fake token. Never serialize into jobs or reports."""
    lease_id: UUID = field(repr=False)
    expires_at: float = field(repr=False)
    binding_sha256: str = field(repr=False)
    _issuer: object = field(repr=False, compare=False)

    def __repr__(self):
        return '<FakeGoogleLease injected-only redacted>'


class InjectedCredentials:
    """One explicitly bound synthetic project/principal; no live authority.

    The SQL session remains the authoritative expiry/budget boundary. Local fake
    token expiry does not substitute for that check or authorize a Google call.
    """
    def __init__(self, binding, *, clock=time.monotonic, lifetime_seconds=180):
        if type(lifetime_seconds) not in (int, float) or not 0 < lifetime_seconds <= 180:
            raise CredentialBoundaryError('GEE_FAKE_CREDENTIAL_LIFETIME_REJECTED')
        self.binding = RuntimeBinding.model_validate(binding.model_dump(mode='json'))
        self._clock = clock
        self._deadline = clock() + lifetime_seconds
        self._issuer = object()
        self._issued = {}
        self._revoked = set()
        self.allowed_project = (self.binding.project.project_id, self.binding.project.project_number)
        self.allowed_principal = self.binding.project.principal

    def issue(self, binding, *, ttl_seconds=30):
        self._check_binding(binding)
        if type(ttl_seconds) not in (int, float) or not 0 < ttl_seconds <= 30:
            raise CredentialBoundaryError('GEE_FAKE_CREDENTIAL_TTL_REJECTED')
        now = self._clock()
        if now >= self._deadline:
            raise CredentialBoundaryError('GEE_FAKE_CREDENTIAL_EXPIRED')
        lease = FakeGoogleLease(uuid4(), min(now + ttl_seconds, self._deadline),
            binding.fingerprint(), self._issuer)
        self._issued[lease.lease_id] = lease
        return lease

    def _check_binding(self, binding):
        if (not isinstance(binding, RuntimeBinding)
            or binding.fingerprint() != self.binding.fingerprint()
            or (binding.project.project_id, binding.project.project_number) != self.allowed_project
            or binding.project.principal != self.allowed_principal):
            raise CredentialBoundaryError('GEE_FAKE_CREDENTIAL_BINDING_REJECTED')

    def authorize(self, lease, binding):
        self._check_binding(binding)
        if (not isinstance(lease, FakeGoogleLease) or lease._issuer is not self._issuer
            or self._issued.get(lease.lease_id) is not lease
            or lease.binding_sha256 != binding.fingerprint()):
            raise CredentialBoundaryError('GEE_FAKE_CREDENTIAL_ISSUER_REJECTED')
        if lease.lease_id in self._revoked:
            raise CredentialBoundaryError('GEE_FAKE_CREDENTIAL_REVOKED')
        if self._clock() >= min(lease.expires_at, self._deadline):
            raise CredentialBoundaryError('GEE_FAKE_CREDENTIAL_EXPIRED')

    def revoke(self, lease):
        if (not isinstance(lease, FakeGoogleLease) or lease._issuer is not self._issuer
            or self._issued.get(lease.lease_id) is not lease):
            raise CredentialBoundaryError('GEE_FAKE_CREDENTIAL_ISSUER_REJECTED')
        self._revoked.add(lease.lease_id)

    def renew(self, lease, binding, *, ttl_seconds=30):
        self.authorize(lease, binding)
        replacement = self.issue(binding, ttl_seconds=ttl_seconds)
        self.revoke(lease)
        return replacement
