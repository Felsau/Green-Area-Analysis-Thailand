"""Genuine runtime contract. No approved network deployment exists yet.

Application URL filtering is not selective egress. The existing network=none
Mock/Native containers and allowlists are deliberately untouched. No env flag,
caller boolean, image tag, certificate hash or injected result opens this gate.
"""
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field

from gis_worker.gee_contracts import Contract, Hash
from gis_worker.gee_live_contracts import Project, digest, geometry_digest
from gis_worker.gee_genuine_identity import GenuineBoundaryError, target

APPROVED_LIVE_IMAGE = None
APPROVED_EGRESS_POLICY = None


class GenuineBinding(Contract):
    worker_subject: UUID
    recorder_subject: UUID
    session_id: UUID
    job_id: UUID
    attempt_number: Annotated[int, Field(strict=True, ge=1, le=2)]
    project: Project
    principal_id: Literal['103297967369976617173']
    input_revision: Annotated[int, Field(strict=True, ge=1)]
    input_hash: Hash
    request_sha256: Hash
    method_sha256: Hash
    geometry_sha256: Hash
    lease_sha256: Hash
    runtime_id: UUID

    def fingerprint(self):
        return digest(self.model_dump(mode='json'))

    def check(self, request, geometry):
        target(self.project)
        if (self.worker_subject == self.recorder_subject or request.execution != 'live'
            or request.project != self.project or request.input_revision != self.input_revision
            or request.request_hash() != self.request_sha256
            or digest(request.method.model_dump(mode='json')) != self.method_sha256
            or geometry_digest(geometry) != self.geometry_sha256
            or request.scope.geometry_sha256 != self.geometry_sha256
            or request.scope.kind != 'sandbox_roi' or request.period.month == 0):
            raise GenuineBoundaryError('GEE_GENUINE_BINDING_REJECTED')
        # Small closed ring in Thailand; full province/annual runs are not smoke.
        ring = geometry['coordinates'][0]
        xs, ys = [p[0] for p in ring], [p[1] for p in ring]
        if (not 97 <= min(xs) <= max(xs) <= 106 or not 5 <= min(ys) <= max(ys) <= 21
            or max(xs) - min(xs) > .05 or max(ys) - min(ys) > .05):
            raise GenuineBoundaryError('GEE_SMOKE_ROI_REJECTED')


def require_selective_egress(*args, **kwargs):
    # Deliberately no approval issuer until real network-layer policy is proven.
    raise GenuineBoundaryError('GEE_SELECTIVE_EGRESS_NOT_VERIFIED')


def require_genuine_runtime(*, binding, credentials, image=None, egress=None):
    target(binding.project)
    if (APPROVED_LIVE_IMAGE is None or APPROVED_EGRESS_POLICY is None
        or image != APPROVED_LIVE_IMAGE):
        raise GenuineBoundaryError('GEE_GENUINE_RUNTIME_DISABLED')
    credentials.authorize(binding)
    require_selective_egress(egress, binding)


class GenuineWorkerRuntime:
    """Separate parent dependency, never a callable/provider from an API job."""
    def __init__(self, *, binding, credentials, transport, image, egress):
        require_genuine_runtime(binding=binding, credentials=credentials, image=image, egress=egress)
        from gis_worker.gee_genuine_transport import GenuinePhysicalHTTP
        if type(transport) is not GenuinePhysicalHTTP:
            raise GenuineBoundaryError('GEE_GENUINE_TRANSPORT_REQUIRED')
        self.binding, self.credentials, self.transport = binding, credentials, transport

    def compute(self, request, geometry, *, as_of):
        from gis_worker.gee_genuine_transport import GenuineSDKAdapter
        self.binding.check(request, geometry)
        output = GenuineSDKAdapter(self.transport, credentials=self.credentials).compute(request, geometry, as_of=as_of)
        report = self.transport.sealed_report
        if (not isinstance(report, dict) or report.get('protocol') != 'gee_genuine_https'
            or report.get('base', {}).get('output', {}).get('output_sha256') != output.output_sha256):
            raise GenuineBoundaryError('GEE_GENUINE_RECORDER_REPORT_REQUIRED')
        return report

