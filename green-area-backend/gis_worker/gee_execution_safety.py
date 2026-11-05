"""Offline execution-policy and one-use accounting boundary. No SDK/auth/network.

Rehearsals never certify Google execution. Actual live authority is unapproved.
Trusted dependency injection is not a sandbox for arbitrary Python callbacks.
"""
from dataclasses import dataclass, field
import time
from typing import Literal
from uuid import UUID, uuid4
from typing import Annotated
from pydantic import Field, model_validator

from gis_worker.gee_contracts import Contract
from gis_worker.gee_live_contracts import Hash, Output, canonical, digest, queue_report

PROTOCOL = 'gee_safety_rehearsal'
MAX_JOBS, MAX_REQUESTS, MAX_ATTEMPTS = 4, 32, 2
REQUEST_TIMEOUT, JOB_TIMEOUT, SESSION_SECONDS = 120, 180, 1200


class SafetyError(ValueError):
    pass


class UnapprovedPolicy(Contract):
    schema_version: Literal[1] = 1
    kind: Literal['unapproved'] = 'unapproved'
    project_id: None = None
    project_number: None = None
    google_principal: None = None
    account_verified: Literal[False] = False
    transport_verified: Literal[False] = False
    live_enabled: Literal[False] = False


class LiveResultBinding(Contract):
    """Non-authoritative future envelope; hashes never attest Google origin.

    Output carries project, province/ROI geometry, exact interval, method,
    collections/scenes/dates, raw values/pixels, units/CRS/scale and all hashes.
    Google principal remains absent/unapproved in policy until a later gate.
    """
    worker_subject: UUID
    job_id: UUID
    attempt_number: Annotated[int, Field(strict=True,ge=1,le=2)]
    result_id: UUID
    lease_token: UUID
    input_revision: Annotated[int, Field(strict=True,ge=1)]
    input_hash: Hash
    method_sha256: Hash
    # Digest of a future transport-attestation document, distinct from the
    # observation digest inside Output. No such attestation is verified here.
    transport_evidence_sha256: Hash
    claimed_output: Output
    transport_verified: Literal[False] = False
    publishable: Literal[False] = False

    @model_validator(mode='after')
    def integrity(self):
        if (self.input_revision!=self.claimed_output.content.request.input_revision or
            self.method_sha256!=digest(self.claimed_output.content.request.method.model_dump(mode='json'))):
            raise ValueError('GEE_METHOD_BINDING_MISMATCH')
        return self


class TrustedLiveEnvelope(Contract):
    """Future discriminant only; parsing is never authority to execute/commit."""
    schema_version: Literal[3] = 3
    protocol: Literal['gee_trusted_live_v3'] = 'gee_trusted_live_v3'
    policy: UnapprovedPolicy
    # Empty diagnostic policy is allowed; neither empty nor filled binding can
    # cross the authority gate or be submitted to the rehearsal SQL protocol.
    binding: LiveResultBinding | None = None

    def require_authority(self):
        raise SafetyError('GEE_TRUSTED_LIVE_NOT_APPROVED')


def require_real_transport():
    # No credentials, environment flag or request payload can open this boundary.
    raise SafetyError('GEE_REAL_TRANSPORT_DISABLED')


@dataclass(frozen=True)
class _Receipt:
    request_id: str
    evidence_sha256: str
    issuer: object = field(repr=False, compare=False)


class AccountedTransport:
    """One injected evaluation per lease-bound attempted reservation.

    RPC retries may replay reserve, never mark-attempted/evaluate. An ambiguous
    RPC/evaluation outcome consumes its reservation permanently. No refund path.
    """
    def __init__(self, call, job, *, clock=time.monotonic):
        self.call, self.job, self.clock = call, dict(job), clock
        self.started = clock()
        self.job_seconds = min(JOB_TIMEOUT, max(0, float(job.get('job_remaining_seconds', JOB_TIMEOUT))))
        self._issuer = object()

    def _lease(self):
        return {'job_id':self.job['id'], 'lease_token':self.job['lease_token']}

    def _uncertain(self, request_id):
        try:
            self.call('uncertain', self._lease() | {'request_id':request_id})
        except Exception:
            # DB recovery conservatively fences/marks outstanding requests. Never
            # evaluate again or claim completion after failed accounting.
            pass

    def execute(self, evaluate, *, kind='compute', request_key=None):
        if kind not in ('compute','sdk_retry','reference','discovery'):
            raise SafetyError('GEE_REQUEST_KIND_REJECTED')
        if self.clock()-self.started >= self.job_seconds:
            raise SafetyError('GEE_JOB_TIMEOUT')
        # No arbitrary job-provided transport. Only an explicitly injected port.
        if getattr(evaluate, 'OFFLINE_INJECTED', None) is not True:
            require_real_transport()
        key = str(UUID(request_key)) if request_key else str(uuid4())
        reservation = self.call('reserve', self._lease() | {'request_key':key, 'kind':kind})
        if reservation.get('granted') is False:
            raise SafetyError('GEE_REQUEST_BUDGET_EXHAUSTED')
        request_id = str(UUID(reservation['request_id']))
        start = self.clock()
        try:
            attempted = self.call('attempted', self._lease() | {'request_id':request_id})
            if attempted.get('state') != 'attempted':
                raise SafetyError('GEE_ACCOUNTING_REQUIRED')
            remaining = min(REQUEST_TIMEOUT, self.job_seconds-(self.clock()-self.started))
            if remaining <= 0:
                raise SafetyError('GEE_JOB_TIMEOUT')
            output = Output.model_validate(evaluate.evaluate(timeout_seconds=remaining).model_dump(mode='json'))
            if output.content.execution != 'injected':
                raise SafetyError('GEE_TRUSTED_LIVE_NOT_APPROVED')
            elapsed = self.clock()-start
            if elapsed >= REQUEST_TIMEOUT or self.clock()-self.started >= self.job_seconds:
                raise SafetyError('GEE_REQUEST_TIMEOUT' if elapsed >= REQUEST_TIMEOUT else 'GEE_JOB_TIMEOUT')
            # Hash comes from the validated observation, never a caller receipt.
            sha = output.content.evidence_sha256
            finished = self.call('finished', self._lease() | {'request_id':request_id, 'evidence_sha256':sha})
            if finished.get('state') != 'completed':
                raise SafetyError('GEE_ACCOUNTING_UNCERTAIN')
            return output, _Receipt(request_id, sha, self._issuer)
        except Exception:
            self._uncertain(request_id)
            raise

    def report(self, output, receipts):
        if (not isinstance(receipts, (list,tuple)) or not receipts or len(receipts)>MAX_REQUESTS
            or any(not isinstance(r,_Receipt) or r.issuer is not self._issuer for r in receipts)):
            raise SafetyError('GEE_TRUSTED_TRANSPORT_RECEIPT_REQUIRED')
        output = Output.model_validate(output.model_dump(mode='json'))
        if any(r.evidence_sha256 != output.content.evidence_sha256 for r in receipts):
            raise SafetyError('GEE_OBSERVATION_RECEIPT_MISMATCH')
        return report(self.job, queue_report(self.job,output), [r.request_id for r in receipts])


def report(job, base, receipts=(), failure_kind=None):
    if failure_kind not in (None,'request_timeout','job_timeout','lease_expired','budget_exhausted','session_stopped','accounting_uncertain','transient'):
        raise SafetyError('GEE_FAILURE_KIND_REJECTED')
    value = {'schema_version':3,'protocol':PROTOCOL,'execution':'rehearsal',
        'live_enabled':False,'session_id':job['session_id'],'policy_sha256':job['policy_sha256'],
        'valid':base['valid'],'error_code':base['error_code'],'base':base,'receipts':list(receipts),'failure_kind':failure_kind}
    if len(canonical(value).encode())>16384:
        raise SafetyError('GEE_SAFETY_REPORT_LIMIT')
    return value
