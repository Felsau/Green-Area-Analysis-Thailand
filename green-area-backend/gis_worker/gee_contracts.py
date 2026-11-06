"""A6.1 data contracts only. No SDK, environment, storage or client discovery."""
from __future__ import annotations

from datetime import date
import hashlib
import json
import math
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from gis_worker.method_registry import LEGACY_V1, MethodError, definition_for_version

Hash = Annotated[str, StringConstraints(strict=True, pattern=r'^[0-9a-f]{64}$')]
Name = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1,
                                      pattern=r'^[^\x00-\x1f\x7f]{1,120}$')]
Version = Annotated[str, StringConstraints(strict=True, pattern=r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$')]
Count = Annotated[int, Field(strict=True, ge=0, le=10**12)]
Product = Literal['ndvi', 'lst']
METHODS = LEGACY_V1.method_versions


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    ensure_ascii=True, allow_nan=False).encode()).hexdigest()


def geometry_digest(value: dict) -> str:
    """Bounded WGS84 polygon payload; hash equality is not province verification."""
    if not isinstance(value, dict) or set(value) != {'type', 'coordinates'}:
        raise ValueError('GEE_GEOMETRY_INVALID')
    if value['type'] not in ('Polygon', 'MultiPolygon'):
        raise ValueError('GEE_GEOMETRY_INVALID')
    polygons = [value['coordinates']] if value['type'] == 'Polygon' else value['coordinates']
    if not isinstance(polygons, (list, tuple)) or not 1 <= len(polygons) <= 10000:
        raise ValueError('GEE_GEOMETRY_INVALID')
    count = 0
    for polygon in polygons:
        if not isinstance(polygon, (list, tuple)) or not polygon:
            raise ValueError('GEE_GEOMETRY_INVALID')
        for ring in polygon:
            if not isinstance(ring, (list, tuple)) or len(ring) < 4 or ring[0] != ring[-1]:
                raise ValueError('GEE_GEOMETRY_INVALID')
            for point in ring:
                count += 1
                if (count > 200000 or not isinstance(point, (list, tuple)) or len(point) != 2
                    or any(type(v) not in (int, float) or not math.isfinite(v) for v in point)
                    or not -180 <= point[0] <= 180 or not -90 <= point[1] <= 90):
                    raise ValueError('GEE_GEOMETRY_INVALID')
    return digest(value)


class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, allow_inf_nan=False)

    @model_validator(mode='before')
    @classmethod
    def strict_version(cls, value):
        if isinstance(value, dict) and 'schema_version' in value and type(value['schema_version']) is not int:
            raise ValueError('GEE_VERSION_INVALID')
        return value


class Period(Contract):
    year: Annotated[int, Field(strict=True, ge=2013, le=2200)]
    month: Annotated[int, Field(strict=True, ge=0, le=12)]
    start: date
    end_exclusive: date

    @model_validator(mode='after')
    def canonical(self):
        start = date(self.year, self.month or 1, 1)
        end = date(self.year + 1, 1, 1) if self.month in (0, 12) else date(self.year, self.month + 1, 1)
        if self.start != start or self.end_exclusive != end:
            raise ValueError('GEE_PERIOD_MISMATCH')
        return self


class Boundary(Contract):
    scope: Literal['province'] = 'province'
    province: Name
    crs: Literal['EPSG:4326'] = 'EPSG:4326'
    boundary_version: Version
    geometry_sha256: Hash


class Method(Contract):
    version: str
    product: Product
    frequency: Literal['annual', 'monthly']
    collections: tuple[str, ...]
    bands: tuple[str, ...]
    units: Literal['unitless', 'celsius']
    scene_cloud_lt: int
    fallback_cloud_lt: int | None
    clear_score_gte: float | None
    reflectance_divisor: int | None
    qa_mask_bits: tuple[int, ...]
    st_multiplier: float | None
    st_offset_kelvin: float | None
    celsius_subtract: float | None
    composite: str
    mask_negative_ndvi: bool
    reduction_scale_m: int = 500
    best_effort: bool = True
    tile_scale: int | None
    max_pixels: int = 10**10
    legacy_sources: tuple[tuple[str, str], ...]


def method_for(product: Product, month: int) -> Method:
    if product not in ('ndvi', 'lst') or type(month) is not int or not 0 <= month <= 12:
        raise ValueError('GEE_METHOD_INVALID')
    annual = month == 0
    ndvi = product == 'ndvi'
    version = f'{product}-{"annual" if annual else "monthly"}-legacy-v1'
    try:
        definition_for_version(version)  # only reviewed definitions are ever built
    except MethodError:
        raise ValueError('GEE_METHOD_INVALID') from None
    return Method(version=version,
        product=product, frequency='annual' if annual else 'monthly',
        collections=('COPERNICUS/S2_SR_HARMONIZED', 'GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED') if ndvi else
                    ('LANDSAT/LC08/C02/T1_L2', 'LANDSAT/LC09/C02/T1_L2'),
        bands=('B8', 'B4', 'cs') if ndvi else ('ST_B10', 'QA_PIXEL'),
        units='unitless' if ndvi else 'celsius', scene_cloud_lt=20 if ndvi and annual else 80 if ndvi else 40,
        fallback_cloud_lt=80 if ndvi and annual else None, clear_score_gte=0.6 if ndvi else None,
        reflectance_divisor=10000 if ndvi else None, qa_mask_bits=() if ndvi else (3, 4),
        st_multiplier=None if ndvi else 0.00341802, st_offset_kelvin=None if ndvi else 149.0,
        celsius_subtract=None if ndvi else 273.15,
        composite='median_bands_then_normalized_difference' if ndvi else 'scale_then_median',
        mask_negative_ndvi=ndvi and annual, tile_scale=4 if ndvi and annual else None,
        # v0 (raw-crlf-sha256-v0) identity of the reviewed legacy-v1 text; bound by
        # migration 044. Unchanged values, now sourced from the approved definition.
        legacy_sources=LEGACY_V1.legacy_identity)


class LiveRequest(Contract):
    schema_version: Literal[1] = 1
    mode: Literal['live_gee'] = 'live_gee'
    request_id: UUID
    input_revision: Annotated[int, Field(strict=True, ge=1, le=2147483647)]
    product: Product
    boundary: Boundary
    period: Period
    method_version: Version

    @model_validator(mode='after')
    def consistent_method(self):
        if (self.method_version != method_for(self.product, self.period.month).version
            or (self.product == 'ndvi' and self.period.year < 2017)):
            raise ValueError('GEE_METHOD_MISMATCH')
        return self

    def request_hash(self) -> str:
        # Transport request IDs do not defeat semantic idempotency.
        return digest({'request': self.model_dump(mode='json', exclude={'request_id'}),
                       'method': method_for(self.product, self.period.month).model_dump(mode='json')})


class OfflineReference(Contract):
    """Reference to the unchanged Phase 3 payload, not a new offline protocol."""
    schema_version: Literal[1] = 1
    mode: Literal['offline_synthetic']
    request: dict

    @model_validator(mode='after')
    def existing_validation(self):
        from gis_worker.processing_provider import check_request
        check_request(self.request)
        return self


ProcessingContract = Annotated[LiveRequest | OfflineReference, Field(discriminator='mode')]


class Statistics(Contract):
    mean: Annotated[float, Field(strict=True)] | None = None
    min: Annotated[float, Field(strict=True)] | None = None
    max: Annotated[float, Field(strict=True)] | None = None

    @model_validator(mode='after')
    def ordered(self):
        if ((self.min is not None and self.mean is not None and self.min > self.mean)
            or (self.max is not None and self.mean is not None and self.mean > self.max)
            or (self.min is not None and self.max is not None and self.min > self.max)):
            raise ValueError('GEE_STATISTICS_INVALID')
        return self


class Scene(Contract):
    collection: str
    image_id: Annotated[str, StringConstraints(strict=True, pattern=r'^[A-Za-z0-9_./-]{1,240}$')]
    acquired: date

    @model_validator(mode='after')
    def qualified_id(self):
        if not self.image_id.startswith(self.collection + '/') or '..' in self.image_id:
            raise ValueError('GEE_SCENE_INVALID')
        return self


class Observation(Contract):
    """Trusted injected bridge must capture raw nulls before legacy `or 0` coercion."""
    request_hash: Hash
    geometry_sha256: Hash
    product: Product
    method_version: Version
    period: Period
    collections: tuple[str, ...]
    scenes: Annotated[tuple[Scene, ...], Field(max_length=20000)]
    observations_complete: bool = Field(strict=True)
    valid_pixels: Count | None
    raw_statistics: Statistics

    @model_validator(mode='after')
    def scientific_identity(self):
        method = method_for(self.product, self.period.month)
        if self.method_version != method.version or self.collections != method.collections:
            raise ValueError('GEE_OBSERVATION_METHOD_MISMATCH')
        ids = [s.image_id for s in self.scenes]
        if len(ids) != len(set(ids)):
            raise ValueError('GEE_SCENE_DUPLICATED')
        for scene in self.scenes:
            if (scene.collection not in method.collections or 'CLOUD_SCORE_PLUS' in scene.collection
                or not self.period.start <= scene.acquired < self.period.end_exclusive):
                raise ValueError('GEE_SCENE_SCOPE_MISMATCH')
        raw = self.raw_statistics
        if self.product == 'ndvi':
            values = [v for v in (raw.mean, raw.min, raw.max) if v is not None]
            if any(not -1 <= v <= 1 or (method.mask_negative_ndvi and v < 0) for v in values):
                raise ValueError('GEE_NDVI_DOMAIN_MISMATCH')
        return self


def observation_status(obs: Observation, as_of: date) -> tuple[str, str | None]:
    """One classification for bridge and transport; unknown counts stay unknown."""
    raw = obs.raw_statistics
    empty = raw == Statistics()
    incomplete = ('incomplete', 'INCOMPLETE_OBSERVATIONS')
    if not obs.observations_complete or obs.period.end_exclusive > as_of:
        return incomplete
    if empty and not obs.scenes and obs.valid_pixels in (None, 0):
        return 'no_data', 'NO_OBSERVATIONS'
    if empty and obs.scenes and obs.valid_pixels == 0:
        return 'no_data', 'NO_VALID_PIXELS'
    if (not obs.scenes or obs.valid_pixels == 0 or raw.mean is None
        or (obs.period.month == 0 and (raw.min is None or raw.max is None))):
        return incomplete
    return 'candidate', None


class OutputContent(Contract):
    schema_version: Literal[1] = 1
    mode: Literal['live_gee'] = 'live_gee'
    execution: Literal['mock'] = 'mock'
    synthetic: Literal[True] = True
    publishable: Literal[False] = False
    endpoint_parity: Literal['summary_only'] = 'summary_only'
    request_hash: Hash
    input_revision: Annotated[int, Field(strict=True, ge=1)]
    boundary: Boundary
    period: Period
    as_of: date
    method: Method
    status: Literal['candidate', 'no_data', 'incomplete', 'failed']
    error_code: Literal['NO_OBSERVATIONS', 'NO_VALID_PIXELS', 'INCOMPLETE_OBSERVATIONS',
                        'GEE_TRANSIENT', 'GEE_REJECTED', 'COMPUTE_FAILED'] | None
    statistics: Statistics
    observation: Observation | None

    @model_validator(mode='after')
    def consistent_result(self):
        if self.method != method_for(self.method.product, self.period.month):
            raise ValueError('GEE_OUTPUT_METHOD_MISMATCH')
        identity = LiveRequest(request_id=UUID(int=0), input_revision=self.input_revision, product=self.method.product,
                               boundary=self.boundary, period=self.period, method_version=self.method.version)
        if self.request_hash != identity.request_hash():
            raise ValueError('GEE_OUTPUT_REQUEST_HASH_MISMATCH')
        obs = self.observation
        if obs is not None and (obs.request_hash != self.request_hash or obs.period != self.period
            or obs.geometry_sha256 != self.boundary.geometry_sha256 or obs.product != self.method.product
            or obs.method_version != self.method.version or obs.collections != self.method.collections):
            raise ValueError('GEE_OUTPUT_LINEAGE_MISMATCH')
        if self.status != 'failed' and (obs is None or observation_status(obs, self.as_of) != (self.status, self.error_code)):
            raise ValueError('GEE_OUTPUT_STATUS_MISMATCH')
        if self.status == 'candidate':
            if (self.error_code is not None or obs is None or not obs.observations_complete
                or not obs.scenes or obs.valid_pixels == 0 or obs.raw_statistics.mean is None):
                raise ValueError('GEE_OUTPUT_CANDIDATE_INVALID')
            raw = obs.raw_statistics
            digits = 4 if self.method.product == 'ndvi' else 2
            if self.method.frequency == 'annual':
                if raw.min is None or raw.max is None:
                    raise ValueError('GEE_OUTPUT_CANDIDATE_INVALID')
                expected = Statistics(mean=round(raw.mean, digits), min=round(raw.min, digits), max=round(raw.max, digits))
            else:
                expected = Statistics(mean=round(raw.mean, digits))
            if self.statistics != expected:
                raise ValueError('GEE_OUTPUT_STATISTICS_MISMATCH')
        elif self.statistics != Statistics():
            raise ValueError('GEE_OUTPUT_FAILURE_HAS_STATISTICS')
        elif self.status == 'failed':
            if self.error_code not in ('GEE_TRANSIENT', 'GEE_REJECTED', 'COMPUTE_FAILED') or obs is not None:
                raise ValueError('GEE_OUTPUT_FAILURE_INVALID')
        elif self.status == 'incomplete':
            if self.error_code != 'INCOMPLETE_OBSERVATIONS':
                raise ValueError('GEE_OUTPUT_INCOMPLETE_INVALID')
        return self


class ComputeOutput(Contract):
    content: OutputContent
    output_sha256: Hash

    @model_validator(mode='after')
    def content_address(self):
        if self.output_sha256 != digest(self.content.model_dump(mode='json')):
            raise ValueError('GEE_OUTPUT_HASH_MISMATCH')
        return self

    @property
    def candidate_identity(self) -> str | None:
        return 'gee-candidate-v1:' + self.output_sha256 if self.content.status == 'candidate' else None
