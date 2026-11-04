"""Fixed A6.3 synthetic bindings; no GEE, SDK, auth, DB or arbitrary paths.

Uses the unchanged offline provider's four artificial pixels and legacy-AST
specification. The scene IDs below explicitly name mocks, never satellite assets.
This is a synthetic-year template, not spatial or temporal scientific evidence.
"""
from datetime import date
from pathlib import Path
import re
from uuid import UUID, uuid4

from gis_worker.gee_adapter import LegacyBindings, LegacyReturn, SafeComputeAdapter
from gis_worker.gee_contracts import LiveRequest, Observation, Statistics, geometry_digest, method_for
from gis_worker.gee_mock_queue import mock_case, report
from gis_worker import processing_provider as offline

GEOMETRY = {'type': 'Polygon', 'coordinates': [[[100, 13], [101, 13], [101, 14], [100, 13]]]}
AS_OF = date(2026, 1, 1)
SPECS = {'ndvi-annual': ('ndvi', 0, 'standard'), 'ndvi-monthly': ('ndvi', 2, 'standard'),
    'lst-annual': ('lst', 0, 'standard'), 'lst-monthly': ('lst', 2, 'standard'),
    'no-data': ('ndvi', 3, 'no_data'), 'all-masked': ('ndvi', 4, 'no_data'),
    'partial': ('ndvi', 5, 'standard'), 'retry-once': ('ndvi', 6, 'standard'),
    'retry-exhausted': ('ndvi', 7, 'standard'), 'long-running': ('ndvi', 8, 'standard')}


def request_for(key, seed, request_id=None):
    if key not in SPECS or not isinstance(seed, str) or not re.fullmatch('[0-9a-f]{12}', seed):
        raise ValueError('GEE_MOCK_FIXTURE_REJECTED')
    product, month, _ = SPECS[key]
    return LiveRequest(request_id=request_id or uuid4(), input_revision=1, product=product,
        boundary={'province': 'Bangkok Metropolis', 'boundary_version': f'a63-{seed}-{key}',
                  'geometry_sha256': geometry_digest(GEOMETRY)},
        period={'year': 2025, 'month': month, 'start': date(2025, month or 1, 1),
                'end_exclusive': date(2026, 1, 1) if month == 0 else date(2025, month + 1, 1)},
        method_version=method_for(product, month).version)


def selected_fixture(request, geometry):
    match = re.fullmatch(r'a63-([0-9a-f]{12})-([a-z-]+)', request.boundary.boundary_version)
    if (not match or match[2] not in SPECS or geometry != GEOMETRY
        or request != request_for(match[2], match[1], request.request_id)):
        raise ValueError('GEE_MOCK_FIXTURE_REJECTED')
    return match[2]


def compute_output(request, geometry, *, legacy_root):
    key = selected_fixture(request, geometry)
    product, month, scenario = SPECS[key]
    method = method_for(product, month)
    provider = offline.OfflineProcessingAdapter(legacy_root=Path(legacy_root))

    def numeric(m):
        start = date(2025, m or 1, 1)
        end = date(2026, 1, 1) if m in (0, 12) else date(2025, m + 1, 1)
        manifest = {'schema_version': 3, 'provider': 'offline_synthetic', 'mode': 'offline_synthetic',
            'provenance': 'gis-processing-offline-v1', 'data_kind': 'raster', 'province': request.boundary.province,
            'district': None, 'metric': product, 'data_year': 2025, 'month': m, 'scenario': scenario,
            'start_date': start.isoformat(), 'end_date': end.isoformat(), 'scale_m': 500,
            'processing_version': offline.BUILD, **offline.source_spec(product, scenario)}
        return provider.compute({'processing_id': str(UUID(int=1)), 'manifest': manifest,
            'input_hash': request.request_hash(), 'input_revision': 1, 'attempt_number': 1})['statistics']

    raw = numeric(month)
    obs = Observation(request_hash=request.request_hash(), geometry_sha256=request.boundary.geometry_sha256,
        product=product, method_version=method.version, period=request.period, collections=method.collections,
        scenes=() if key == 'no-data' else ({'collection': method.collections[0],
            'image_id': method.collections[0] + '/A63_SYNTHETIC_' + key.replace('-', '_'), 'acquired': request.period.start},),
        observations_complete=key != 'partial', valid_pixels=raw['valid_pixels'],
        raw_statistics=Statistics(**{k: raw[k] for k in ('mean', 'min', 'max')}))
    if month:
        payload = [{'month_num': n, 'image_count': 0 if key == 'no-data' else 1,
                    product: numeric(n)['mean']} for n in range(1, 13)]
    elif product == 'ndvi':
        payload = {f'ndvi_{k}': raw[k] or 0 for k in ('mean', 'min', 'max')}
    else:
        payload = tuple(raw[k] or 0 for k in ('mean', 'min', 'max'))
    binding = lambda *_: LegacyReturn(payload, obs)
    adapter = SafeComputeAdapter(LegacyBindings(binding, binding, binding, binding), as_of=AS_OF)
    return adapter.compute(request, geometry, expected_request_hash=request.request_hash())


def case_for(key, seed, *, legacy_root):
    request = request_for(key, seed)
    return mock_case(request, GEOMETRY, compute_output(request, GEOMETRY, legacy_root=legacy_root))


def execute(job, *, legacy_root, sleep):
    allowed = {'request', 'geometry', 'input_hash', 'input_revision', 'semantic_request_sha256', 'attempt_number'}
    if (not isinstance(job, dict) or set(job) != allowed or type(job['attempt_number']) is not int
        or not 1 <= job['attempt_number'] <= 3):
        raise ValueError('GEE_MOCK_PACKET_REJECTED')
    request = LiveRequest.model_validate(job['request'])
    key = selected_fixture(request, job['geometry'])
    # Fixed server fixture behavior only; no delay/command is accepted by API.
    if key == 'retry-exhausted' or (key == 'retry-once' and job['attempt_number'] == 1):
        return report(job, infrastructure_error='NATIVE_PROCESS_FAILED')
    if key == 'long-running':
        sleep(12)
    return report(job, compute_output(request, job['geometry'], legacy_root=legacy_root))
