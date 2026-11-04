"""Version two future-live contracts. No SDK/auth/environment or IO imports.

Injected evidence is explicitly synthetic. These hashes bind documents, never
certify that a satellite or Google produced them. SQL owns worker authority.
"""
from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StringConstraints, model_validator

from gis_worker.gee_contracts import (Contract, Count, Hash, Method, Name, Period,
    Scene, Statistics, Version, geometry_digest as check_geometry, method_for)

PROTOCOL = 'gee_live_v2'
MAX_SCENES = 32  # Fail closed, never silently truncate to fit the native report.


class Project(Contract):
    project_id: Annotated[str, StringConstraints(strict=True, pattern=r'^[a-z][a-z0-9-]{4,28}[a-z0-9]$')]
    project_number: Annotated[str, StringConstraints(strict=True, pattern=r'^[0-9]{6,30}$')]
    principal: Annotated[str, StringConstraints(strict=True, pattern=r'^[a-z0-9-]+@[a-z][a-z0-9-]+\.iam\.gserviceaccount\.com$')]
    readiness: Literal['not_verified'] = 'not_verified'

    @model_validator(mode='after')
    def principal_project(self):
        if not self.principal.endswith('@' + self.project_id + '.iam.gserviceaccount.com'):
            raise ValueError('GEE_LIVE_PROJECT_MISMATCH')
        return self


class Scope(Contract):
    kind: Literal['province', 'sandbox_roi']
    province: Name
    boundary_version: Version
    province_geometry_sha256: Hash
    geometry_sha256: Hash
    geometry_crs: Literal['EPSG:4326'] = 'EPSG:4326'

    @model_validator(mode='after')
    def honest_scope(self):
        if self.kind == 'province' and self.geometry_sha256 != self.province_geometry_sha256:
            raise ValueError('GEE_LIVE_PROVINCE_SCOPE_MISMATCH')
        return self


class Request(Contract):
    schema_version: Literal[2] = 2
    protocol: Literal['gee_live_v2'] = PROTOCOL
    request_id: UUID
    input_revision: Annotated[int, Field(strict=True, ge=1, le=2147483647)]
    execution: Literal['injected', 'live']
    product: Literal['ndvi', 'lst']
    period: Period
    scope: Scope
    project: Project
    method_version: Version

    @model_validator(mode='after')
    def method_identity(self):
        if (self.method_version != self.method.version or
            self.product == 'ndvi' and self.period.year < 2017):
            raise ValueError('GEE_LIVE_METHOD_MISMATCH')
        return self

    @property
    def method(self) -> Method:
        return method_for(self.product, self.period.month)

    def semantic(self):
        return {'request': self.model_dump(mode='json', exclude={'request_id'}),
                'method': self.method.model_dump(mode='json')}

    def request_hash(self):
        return digest(self.semantic())


class Evidence(Contract):
    request_sha256: Hash
    geometry_sha256: Hash
    project: Project
    method: Method
    period: Period
    scenes: Annotated[tuple[Scene, ...], Field(max_length=MAX_SCENES)]
    scene_count: Annotated[int, Field(strict=True, ge=0, le=MAX_SCENES)]
    complete: bool = Field(strict=True)
    valid_pixels: Count | None
    raw_statistics: Statistics
    units: Literal['unitless', 'celsius']
    geometry_crs: Literal['EPSG:4326'] = 'EPSG:4326'
    reduction_crs: Annotated[str, StringConstraints(strict=True, max_length=80)] | None = None
    nominal_scale_m: Literal[500] = 500
    effective_scale_m: Annotated[float, Field(gt=0)] | None = None
    nodata: Literal['null'] = 'null'

    @model_validator(mode='after')
    def provenance(self):
        if (self.scene_count != len(self.scenes) or len({s.image_id for s in self.scenes}) != self.scene_count
            or self.method != method_for(self.method.product, self.period.month)
            or self.units != self.method.units):
            raise ValueError('GEE_LIVE_EVIDENCE_MISMATCH')
        for scene in self.scenes:
            if (scene.collection not in self.method.collections or 'CLOUD_SCORE_PLUS' in scene.collection
                or not self.period.start <= scene.acquired < self.period.end_exclusive):
                raise ValueError('GEE_LIVE_SCENE_MISMATCH')
        if ((not self.scenes and self.valid_pixels not in (None, 0))
            or (not self.scenes or self.valid_pixels == 0) and self.raw_statistics != Statistics()):
            raise ValueError('GEE_LIVE_NODATA_CONTRADICTION')
        values = [v for v in self.raw_statistics.model_dump().values() if v is not None]
        if self.method.product == 'ndvi' and any(not -1 <= v <= 1 or self.method.mask_negative_ndvi and v < 0 for v in values):
            raise ValueError('GEE_LIVE_NDVI_DOMAIN')
        return self

    def status(self, as_of):
        if not self.complete or self.period.end_exclusive > as_of or self.valid_pixels is None:
            return 'incomplete'
        if not self.scenes or self.valid_pixels == 0:
            return 'no_data'
        if self.raw_statistics.mean is None:
            return 'incomplete'
        if self.method.frequency == 'annual' and (self.raw_statistics.min is None or self.raw_statistics.max is None):
            return 'incomplete'
        return 'candidate'


class Content(Contract):
    schema_version: Literal[2] = 2
    protocol: Literal['gee_live_v2'] = PROTOCOL
    request: Request
    request_sha256: Hash
    geometry_sha256: Hash
    execution: Literal['injected', 'live']
    synthetic: bool = Field(strict=True)
    publishable: Literal[False] = False
    endpoint_parity: Literal['summary_only'] = 'summary_only'
    as_of: date
    status: Literal['candidate', 'no_data', 'incomplete']
    evidence: Evidence
    evidence_sha256: Hash
    statistics: Statistics

    @model_validator(mode='after')
    def integrity(self):
        r, e = self.request, self.evidence
        if (self.execution != r.execution or self.synthetic != (self.execution == 'injected')
            or self.request_sha256 != r.request_hash() or self.geometry_sha256 != r.scope.geometry_sha256
            or e.request_sha256 != self.request_sha256 or e.geometry_sha256 != self.geometry_sha256
            or e.project != r.project or e.method != r.method or e.period != r.period
            or self.evidence_sha256 != digest(e.model_dump(mode='json')) or self.status != e.status(self.as_of)):
            raise ValueError('GEE_LIVE_RESULT_IDENTITY_MISMATCH')
        expected = Statistics()
        if self.status == 'candidate':
            raw = e.raw_statistics
            digits = 4 if r.product == 'ndvi' else 2
            expected = Statistics(mean=round(raw.mean, digits),
                min=round(raw.min, digits) if not r.period.month else None,
                max=round(raw.max, digits) if not r.period.month else None)
        if self.statistics != expected:
            raise ValueError('GEE_LIVE_STATISTICS_MISMATCH')
        return self


class Output(Contract):
    content: Content
    output_sha256: Hash

    @model_validator(mode='after')
    def content_hash(self):
        if self.output_sha256 != digest(self.content.model_dump(mode='json')):
            raise ValueError('GEE_LIVE_OUTPUT_HASH_MISMATCH')
        return self


def canonical(value):
    # V2 cross-language canonical form: sorted UTF-8 keys; decimal plain numbers
    # without insignificant zeros/exponents. SQL independently reconstructs it.
    import json
    from decimal import Decimal
    if isinstance(value, dict):
        return '{' + ','.join(json.dumps(k, ensure_ascii=False) + ':' + canonical(value[k]) for k in sorted(value)) + '}'
    if isinstance(value, (list, tuple)):
        return '[' + ','.join(canonical(v) for v in value) + ']'
    if type(value) in (int, float):
        n = Decimal(str(value))
        if not n.is_finite():
            raise ValueError('GEE_LIVE_NONFINITE')
        text = format(n, 'f')
        if '.' in text:
            text = text.rstrip('0').rstrip('.')
        return '0' if n == 0 else text
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':'))


def digest(value):
    import hashlib
    return hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()


def geometry_digest(value):
    check_geometry(value)
    return digest(value)


def registered_input(request, geometry):
    """Trusted local operator only. Deliberately has no expected output/oracle."""
    request = Request.model_validate(request.model_dump(mode='json'))
    if request.execution != 'injected' or geometry_digest(geometry) != request.scope.geometry_sha256:
        raise ValueError('GEE_LIVE_DISABLED_OR_GEOMETRY_MISMATCH')
    value = {'request': request.model_dump(mode='json'), 'method': request.method.model_dump(mode='json'),
        'geometry': geometry, 'request_canonical': canonical(request.semantic()),
        'geometry_canonical': canonical(geometry), 'request_sha256': request.request_hash(),
        'geometry_sha256': request.scope.geometry_sha256}
    if len(canonical(value).encode()) > 16384:
        raise ValueError('GEE_LIVE_INPUT_LIMIT')
    return value


def queue_report(job, output=None, infrastructure_error=None):
    allowed = {'NATIVE_TIMEOUT', 'NATIVE_MEMORY_LIMIT', 'NATIVE_PROCESS_FAILED', 'WORKER_SHUTDOWN', 'NATIVE_OUTPUT_LIMIT'}
    if infrastructure_error is not None and infrastructure_error not in allowed:
        raise ValueError('GEE_LIVE_FAILURE_REJECTED')
    if output is not None:
        output = Output.model_validate(output.model_dump(mode='json'))
        if output.content.execution != 'injected' or output.content.request_sha256 != job['semantic_request_sha256']:
            raise ValueError('GEE_LIVE_DISABLED_OR_INPUT_MISMATCH')
    valid = output is not None and output.content.status == 'candidate'
    value = {'schema_version': 2, 'protocol': PROTOCOL, 'input_hash': job['input_hash'],
        'input_revision': job['input_revision'], 'semantic_request_sha256': job['semantic_request_sha256'],
        'valid': valid, 'error_code': infrastructure_error or (None if valid else 'invalid_data'),
        'output': output.model_dump(mode='json') if output else None,
        'output_canonical': canonical(output.content.model_dump(mode='json')) if output else None,
        'evidence_canonical': canonical(output.content.evidence.model_dump(mode='json')) if output else None}
    if len(canonical(value).encode()) > 16384:
        raise ValueError('GEE_LIVE_REPORT_LIMIT')
    return value
