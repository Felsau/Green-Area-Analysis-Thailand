"""Pure contracts; no application, SDK, credentials, DB or cloud fixtures."""
from copy import deepcopy
from datetime import date
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import TypeAdapter, ValidationError

from gis_worker.gee_contracts import (ComputeOutput, LiveRequest, Period, ProcessingContract,
                                    Statistics, geometry_digest, method_for)

GEOMETRY = {'type': 'Polygon', 'coordinates': [[[100, 13], [101, 13], [101, 14], [100, 13]]]}
ID = UUID('11111111-1111-4111-8111-111111111111')


def request(product='ndvi', month=0, year=2025):
    return LiveRequest(request_id=ID, input_revision=1, product=product,
        boundary={'province': 'Bangkok Metropolis', 'boundary_version': 'gadm-reviewed-test-v1',
                  'geometry_sha256': geometry_digest(GEOMETRY)},
        period={'year': year, 'month': month, 'start': date(year, month or 1, 1),
                'end_exclusive': date(year + 1, 1, 1) if month in (0, 12) else date(year, month + 1, 1)},
        method_version=method_for(product, month).version)


@pytest.mark.parametrize('product', ['ndvi', 'lst'])
@pytest.mark.parametrize('month', range(13))
def test_versioned_live_contract_roundtrip_and_canonical_period(product, month):
    value = request(product, month)
    parsed = TypeAdapter(ProcessingContract).validate_json(value.model_dump_json())
    assert parsed == value
    assert parsed.request_hash() == value.request_hash()
    assert parsed.boundary.scope == 'province'


@pytest.mark.parametrize('changes', [dict(product='unknown'), dict(method_version='lst-annual-legacy-v1'),
    dict(input_revision=True), dict(input_revision=0), dict(mode='offline_synthetic'), dict(schema_version=2), dict(schema_version=True),
    dict(path='/private/key'), dict(url='https://example.invalid'), dict(project_id='production'), dict(sql='SELECT 1')])
def test_live_contract_rejects_mismatches_and_external_authority(changes):
    with pytest.raises(ValidationError):
        LiveRequest.model_validate(request().model_dump(mode='json') | changes)


@pytest.mark.parametrize('changes', [dict(start='2025-02-01'), dict(end_exclusive='2025-12-31'),
    dict(month=13), dict(month=True), dict(year=2012)])
def test_period_rejects_noncanonical(changes):
    with pytest.raises(ValidationError):
        Period.model_validate(request().period.model_dump(mode='json') | changes)


def test_hash_separates_content_from_transport_and_binds_lineage():
    a = request()
    changed_id = LiveRequest.model_validate(a.model_dump(mode='json') | {'request_id': str(UUID(int=2))})
    assert a.request_hash() == changed_id.request_hash()
    for key, value in [('input_revision', 2), ('boundary', a.boundary.model_dump() | {'boundary_version': 'v2'})]:
        assert LiveRequest.model_validate(a.model_dump() | {key: value}).request_hash() != a.request_hash()
    assert request('lst').request_hash() != a.request_hash()
    assert request(month=1).request_hash() != a.request_hash()


@pytest.mark.parametrize('value', [None, {}, {'type': 'Point', 'coordinates': [100, 13]},
    {'type': 'Polygon', 'coordinates': []}, {'type': 'Polygon', 'coordinates': [[[0, 0]]]},
    {'type': 'Polygon', 'coordinates': [[[0, 0], [1, 0], [1, 1], [2, 2]]]},
    {'type': 'Polygon', 'coordinates': [[[0, 0], [181, 0], [1, 1], [0, 0]]]},
    {'type': 'Polygon', 'coordinates': [[[0, 0], [1, float('nan')], [1, 1], [0, 0]]]},
    {'type': 'Polygon', 'coordinates': [[[0, 0], [True, 0], [1, 1], [0, 0]]]},
    GEOMETRY | {'path': '/tmp/input'}])
def test_bounded_geometry_rejects_invalid_payloads(value):
    with pytest.raises(ValueError, match='GEE_GEOMETRY_INVALID'):
        geometry_digest(value)


def test_geometry_hash_is_key_order_stable_and_coordinate_bound():
    assert geometry_digest(GEOMETRY) == geometry_digest(dict(reversed(list(GEOMETRY.items()))))
    altered = deepcopy(GEOMETRY)
    altered['coordinates'][0][1][0] = 100.5
    assert geometry_digest(altered) != geometry_digest(GEOMETRY)
    assert geometry_digest({'type': 'MultiPolygon', 'coordinates': [GEOMETRY['coordinates']]})


@pytest.mark.parametrize('values', [dict(mean=float('nan')), dict(mean=float('inf')),
                                 dict(mean=0.5, min=0.6), dict(mean=0.5, max=0.4), dict(mean=True)])
def test_statistics_are_finite_and_ordered(values):
    with pytest.raises(ValidationError):
        Statistics(**values)


def test_offline_reference_still_uses_original_validator():
    from tests.test_processing_provider import request as offline_request
    original = offline_request()
    parsed = TypeAdapter(ProcessingContract).validate_python(
        {'mode': 'offline_synthetic', 'request': original})
    assert parsed.request == original
    for changes in ({'mode': 'live_gee'}, {'sha256': '0' * 64}, {'scenario': 'arbitrary'}):
        invalid = deepcopy(original)
        invalid['manifest'].update(changes)
        with pytest.raises(ValueError):
            TypeAdapter(ProcessingContract).validate_python({'mode': 'offline_synthetic', 'request': invalid})


def test_methods_bind_current_legacy_source_bytes_without_runtime_file_reads():
    # Same pinned v0 identities as before; verified under the declared schemes so
    # a CRLF (Windows) and an LF (Linux) checkout of the same text both pass.
    from gis_worker.method_registry import definition_for_version
    from gis_worker.source_integrity import legacy_crlf_sha256, source_text_sha256
    root = Path(__file__).resolve().parents[1]
    method = method_for('ndvi', 0)
    approved = dict(definition_for_version(method.version).approved_sources)
    for name, expected in method.legacy_sources:
        raw = (root / name).read_bytes()
        assert source_text_sha256(raw) == approved[name]
        assert legacy_crlf_sha256(raw) == expected


def test_output_hash_cannot_be_replaced():
    from tests.test_gee_adapter import adapter
    output = adapter(request()).compute(request(), GEOMETRY, expected_request_hash=request().request_hash())
    with pytest.raises(ValidationError):
        ComputeOutput.model_validate(output.model_dump(mode='json') | {'output_sha256': '0' * 64})
