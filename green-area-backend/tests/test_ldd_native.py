"""Phase 2 local-file/native validation; no database, service or network."""
from __future__ import annotations

from copy import deepcopy
import hashlib
from io import BytesIO
import json
from pathlib import Path
import re
import stat
import zipfile

import pytest

from gis_worker import ldd_provider as ldd
from gis_worker.ldd_worker import LddWorker, LddClient
from gis_worker.worker import WorkerError

FIXTURES = Path(__file__).resolve().parents[1] / 'gis_worker/fixtures'
ID = '11111111-1111-4111-8111-111111111111'


def request(raw=None, **values):
    raw = raw or (FIXTURES / 'ldd_valid.zip').read_bytes()
    return {'upload_id': ID, 'manifest': {'schema_version': 1, 'provider': 'real',
        'sha256': hashlib.sha256(raw).hexdigest(), 'byte_size': len(raw),
        'provenance': 'local-ldd-upload-v1', 'crs': 'EPSG:32647', 'data_kind': 'polygon',
        'attributes': list(ldd.REQUIRED_FIELDS)}, 'input_hash': 'a' * 64,
        'input_revision': 1, 'attempt_number': 1, 'province': 'Bangkok Metropolis',
        'data_year': 2026, 'encoding': 'auto', **values}


def store(tmp_path, raw, req=None):
    req = req or request(raw)
    (tmp_path / (req['manifest']['sha256'] + '.zip')).write_bytes(raw)
    return req


def archive(members, **kwargs):
    output = BytesIO()
    with zipfile.ZipFile(output, 'w', **kwargs) as z:
        for name, value in members:
            z.writestr(name, value)
    return output.getvalue()


def test_catalog_is_frozen_existing_96_codes_and_boundaries():
    legend = ldd._asset('ldd_codes.json', ldd.LEGEND_SHA256)
    assert len(legend['codes']) == 96
    assert ldd._main_code('U201/A401', 'U', legend['codes']) == 'U'
    assert ldd._main_code('A300/A400', 'A', legend['codes']) == 'A'
    assert ldd._main_code('A101/A401', 'A', legend['codes']) == 'A'
    assert ldd._main_code('U101/UNKNOWN', 'U', legend['codes']) is None
    assert ldd._main_code('U101', '', legend['codes']) is None
    assert ldd._main_code('U101', True, legend['codes']) is None
    assert len(ldd._asset('province_boundaries.json', ldd.BOUNDARY_SHA256)['features']) == 77


@pytest.mark.parametrize('change', [
    {'path': '/tmp/x'}, {'province': None}, {'encoding': 'latin-1'}, {'attempt_number': 4},
    {'input_revision': True}, {'input_hash': '../path'}, {'upload_id': '../../x'},
])
def test_arbitrary_paths_and_invalid_metadata_rejected(change):
    req = request()
    req.update(change)
    with pytest.raises(ldd.LddError, match='LDD_REQUEST_INVALID'):
        ldd.check_request(req)


@pytest.mark.parametrize('name', ['../x.shp', '/x.shp', 'C:/x.shp', 'a\\x.shp', 'a/./x.shp', 'a//x.shp'])
def test_zip_traversal_denied(name):
    raw = archive([(name, b'a')])
    if '\\' in name:
        # ZipInfo on Windows normalizes writes; patch both same-length header
        # names to represent an archive actually received from another OS.
        raw = archive([(name.replace('\\', '/'), b'a')]).replace(name.replace('\\', '/').encode(), name.encode())
    with pytest.raises(ldd.LddError, match='ZIP_PATH_UNSAFE'):
        ldd.guarded_zip(raw)


def test_symlink_zip_member_denied():
    member = zipfile.ZipInfo('x.shp')
    member.create_system = 3
    member.external_attr = (stat.S_IFLNK | 0o777) << 16
    with pytest.raises(ldd.LddError, match='ZIP_SYMLINK'):
        ldd.guarded_zip(archive([(member, b'/etc/passwd')]))


def test_duplicate_case_and_bomb_and_unsupported_members():
    with pytest.raises(ldd.LddError, match='ZIP_DUPLICATE_NAME'):
        ldd.guarded_zip(archive([('x.shp', b'a'), ('X.SHP', b'b')]))
    with pytest.raises(ldd.LddError, match='ZIP_COMPRESSION_RATIO'):
        ldd.guarded_zip(archive([('x.shp', b'0' * 200000)], compression=zipfile.ZIP_DEFLATED))
    with pytest.raises(ldd.LddError, match='UNSUPPORTED_ZIP_MEMBER'):
        ldd.guarded_zip(archive([('x.vrt', b'<VRT/>')]))


def test_size_limit_corruption_missing_components_and_sidecars():
    with pytest.raises(ldd.LddError, match='ZIP_SIZE_LIMIT'):
        ldd.guarded_zip(b'a' * (ldd.MAX_ZIP_BYTES + 1))
    with pytest.raises(ldd.LddError, match='ZIP_CORRUPT'):
        ldd.guarded_zip(b'PK\x03\x04invalid')
    with pytest.raises(ldd.LddError, match='MISSING_COMPONENT_SHX'):
        ldd._components({'a.shp': b'a'})
    files = ldd.guarded_zip(archive([(f'a.{ext}', b'x') for ext in ('shp', 'shx', 'dbf', 'prj', 'sbn', 'sbx', 'qix')]))
    assert len(ldd._components(files)[1]) == 7


@pytest.mark.parametrize('fixture,outcome,accepted,review', [
    ('ldd_valid.zip', 'accepted', 3, 0), ('ldd_unknown.zip', 'review_required', None, None), ('ldd_missing_dbf.zip', 'rejected', 0, 0),
])
def test_report_audit_matches_the_rules_in_migration_050(tmp_path, fixture, outcome, accepted, review):
    pytest.importorskip('fiona')
    pytest.importorskip('rasterio')
    result = ldd.validate(store(tmp_path, (FIXTURES / fixture).read_bytes()), storage_root=tmp_path)
    audit = result['audit']
    assert set(audit) == {'policy_version', 'outcome', 'field_profile', 'field_mapping', 'declared_area_units', 'feature_outcomes',
                          'boundary', 'unknown_samples', 'repairs', 'repairs_total'}
    assert audit['outcome'] == outcome and audit['policy_version'] == 'ldd-policy-v2'
    assert set(audit['feature_outcomes']) == {'accepted', 'accepted_with_warnings', 'review_required', 'rejected'}
    assert set(audit['boundary']) == {'minor', 'review', 'fatal', 'outside_area_m2'}
    total = sum(audit['feature_outcomes'].values())
    if result['valid']:
        assert total == result['statistics']['feature_count'] and audit['field_mapping'] == {
            'main_code': 'LUL1_CODE', 'lu_code': 'LU_CODE', 'declared_area': 'Shape_Area'}
    else:
        assert total <= result['statistics']['feature_count']
    if accepted is not None:
        assert audit['feature_outcomes']['accepted'] == accepted and audit['feature_outcomes']['review_required'] == review
    if outcome == 'review_required':
        assert audit['feature_outcomes']['review_required'] > 0 and 0 < len(audit['unknown_samples']) <= 10
        assert {e['code'] for e in result['errors']} == {'UNKNOWN_CODE_REVIEW_REQUIRED'}
        sample = audit['unknown_samples'][0]
        assert set(sample) == {'value', 'main', 'reason', 'count', 'area_m2'} and re.fullmatch('[A-Z][A-Z0-9_]{0,59}', sample['reason'])
    assert len(json.dumps(result, allow_nan=False).encode()) <= 16384


def test_audit_is_dropped_rather_than_failing_when_the_report_would_be_too_large(tmp_path, monkeypatch):
    pytest.importorskip('fiona')
    pytest.importorskip('rasterio')
    monkeypatch.setattr(ldd, 'audit_summary', lambda details, total: {'padding': 'x' * 20000})
    result = ldd.validate(store(tmp_path, (FIXTURES / 'ldd_valid.zip').read_bytes()), storage_root=tmp_path)
    assert result['valid'] is True and 'audit' not in result


def test_resource_failures_carry_no_audit(tmp_path, monkeypatch):
    req = request((FIXTURES / 'ldd_valid.zip').read_bytes())
    failure = ldd.report_failure(req, 'NATIVE_MEMORY_LIMIT')
    monkeypatch.setattr(ldd, 'assess', lambda request, storage_root: (failure, {}))
    assert 'audit' not in ldd.validate(req, storage_root=tmp_path)


def test_native_hash_mismatch_and_missing_file_fail_safely(tmp_path):
    raw = (FIXTURES / 'ldd_valid.zip').read_bytes()
    req = request(raw)
    result = ldd.validate(req, storage_root=tmp_path)
    assert result['valid'] is False and result['error_code'] == 'LDD_FILE_UNAVAILABLE'
    store(tmp_path, bytes([raw[0] ^ 1]) + raw[1:], req)
    result = ldd.validate(req, storage_root=tmp_path)
    assert result['error_code'] == 'LDD_SHA256_MISMATCH' and result['observed_sha256'] != result['artifact_sha256']
    assert str(tmp_path) not in json.dumps(result)


@pytest.mark.parametrize('fixture,valid,code', [
    ('ldd_valid.zip', True, None), ('ldd_cp874.zip', True, None),
    ('ldd_composite_a.zip', True, None), ('ldd_unknown.zip', False, 'UNKNOWN_CODE_REVIEW_REQUIRED'),
    ('ldd_missing_dbf.zip', False, 'MISSING_COMPONENT_DBF'),
])
def test_actual_zip_validation_expected_results(tmp_path, fixture, valid, code):
    pytest.importorskip('fiona')
    pytest.importorskip('rasterio')
    raw = (FIXTURES / fixture).read_bytes()
    req = store(tmp_path, raw)
    result = ldd.validate(req, storage_root=tmp_path)
    assert result['valid'] is valid
    assert result['error_code'] == code
    assert len(json.dumps(result).encode()) <= 16384
    if valid:
        assert result['statistics']['feature_count'] == 3
        assert result['statistics']['total_area_m2'] == pytest.approx(6400)
        assert sum(result['statistics']['area_by_main_m2'].values()) == pytest.approx(6400)
        assert set(result['checks']) == set(ldd.CHECKS)
        assert result['observed_sha256'] == result['artifact_sha256']
    if fixture == 'ldd_cp874.zip':
        assert result['encoding'] == 'cp874'
    if fixture == 'ldd_composite_a.zip':
        assert result['statistics']['composite_feature_count'] >= 1
    if fixture == 'ldd_unknown.zip':
        assert result['statistics']['unknown_code_count'] > 0
        assert result['statistics']['unknown_area_m2'] > 0


def test_actual_crs_province_encoding_mismatch(tmp_path):
    pytest.importorskip('fiona')
    pytest.importorskip('rasterio')
    raw = (FIXTURES / 'ldd_valid.zip').read_bytes()
    req = store(tmp_path, raw)
    wrong_crs = deepcopy(req)
    wrong_crs['manifest']['crs'] = 'EPSG:32648'
    assert ldd.validate(wrong_crs, storage_root=tmp_path)['error_code'] == 'CRS_MISMATCH'
    wrong_province = {**req, 'province': 'Chiang Mai'}
    assert ldd.validate(wrong_province, storage_root=tmp_path)['error_code'] == 'OUTSIDE_PROVINCE'
    wrong_encoding = {**req, 'encoding': 'cp874'}
    assert ldd.validate(wrong_encoding, storage_root=tmp_path)['error_code'] == 'ENCODING_MISMATCH'


def ready():
    return {'status': 'ready', 'worker_role': 'gis_native_worker', 'subject': ID,
        'database_name': 'postgres', 'cluster_name': 'green-area-gis-t0', 'mode': 'local_synthetic',
        'contract_version': '1.0.0-ldd-local', 'migration_versions': list(range(27, 35)),
        'runtime_instance': 'a' * 32, 'baseline_fingerprint': 'b' * 64}


class Client:
    subject = ID
    expected = {'runtime_instance': 'a' * 32, 'baseline_fingerprint': 'b' * 64}

    def __init__(self, result=None):
        self.result = result or ready()
        self.calls = []

    def call(self, name, payload):
        self.calls.append((name, payload))
        return self.result if name == 'gis_ldd_readiness' else {'state': 'succeeded'}


def test_ldd_worker_separate_rpc_and_reused_fencing():
    client = Client()
    worker = LddWorker(client)
    worker.call('claim')
    assert [name for name, _ in client.calls] == ['gis_ldd_readiness', 'gis_ldd_worker']
    assert LddClient.RPC_NAMES == ('gis_ldd_worker', 'gis_ldd_readiness')
    assert worker.CHILD_SCRIPT == 'ldd_child.py'


@pytest.mark.parametrize('field,value', [('contract_version', 'other'), ('migration_versions', list(range(27, 34))), ('subject', 'other'), ('mode', 'production')])
def test_ldd_worker_target_guard_blocks_mutation(field, value):
    response = ready()
    response[field] = value
    client = Client(response)
    with pytest.raises(WorkerError, match='WORKER_TARGET_REJECTED'):
        LddWorker(client).call('claim')
    assert len(client.calls) == 1


def test_ldd_native_request_no_paths_or_extra_keys():
    req = request()
    job = {**req, 'id': ID, 'lease_token': ID}
    assert LddWorker(Client()).build_native_request(job) == req
    failure = LddWorker(Client()).failure_report(req, 'NATIVE_TIMEOUT')
    assert failure['valid'] is False and failure['error_code'] == 'NATIVE_TIMEOUT'
    assert not {'access_token', 'path', 'url'} & failure.keys()
