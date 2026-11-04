"""A6.2 internal protocol tests; no database or external transport."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys
from uuid import uuid4

import pytest
from pydantic import ValidationError

from gis_worker.gee_contracts import ComputeOutput, LiveRequest, digest
from gis_worker.gee_mock_queue import MockQueueHooks, canonical, mock_case, report
from tests.test_gee_adapter import compute
from tests.test_gee_contracts import GEOMETRY, request


def job():
    r = request()
    return {'id': str(uuid4()), 'lease_token': str(uuid4()), 'input_hash': 'a' * 64,
        'input_revision': 1, 'semantic_request_sha256': r.request_hash(),
        'request': r.model_dump(mode='json'), 'geometry': deepcopy(GEOMETRY)}


def test_case_is_canonical_and_explicitly_mock_json_not_a_raster():
    r = request()
    c = mock_case(r, GEOMETRY, compute(r))
    assert digest(json.loads(c['request_canonical'])) == c['request_sha256']
    assert digest(json.loads(c['output_canonical'])) == c['output_sha256']
    assert c['request_sha256'] != c['output_sha256']
    assert c['output']['content']['execution'] == 'mock'
    assert c['output']['content']['publishable'] is False
    assert json.loads(canonical(c)) == c


@pytest.mark.parametrize('change', ['geometry', 'request', 'output', 'live'])
def test_case_and_report_reject_mixed_lineage(change):
    r = request()
    geometry = deepcopy(GEOMETRY)
    output = compute(r)
    if change == 'geometry': geometry['coordinates'][0][1][0] = 100.5
    elif change == 'request': r = request(month=1)
    elif change == 'output': output = compute(request('lst'))
    else:
        data = output.model_dump(mode='json')
        data['content']['execution'] = 'live'
        data['output_sha256'] = digest(data['content'])
        with pytest.raises(ValidationError): ComputeOutput.model_validate(data)
        return
    with pytest.raises(ValueError): mock_case(r, geometry, output)


@pytest.mark.parametrize('key,value', [('input_revision', 2), ('semantic_request_sha256', '0' * 64),
    ('request', request('lst').model_dump(mode='json')), ('geometry', {'type': 'Point', 'coordinates': [0, 0]})])
def test_claim_identity_rejected_before_commit(key, value):
    with pytest.raises(ValueError): report(job() | {key: value}, compute(request()))


def test_report_cannot_assert_an_actor_worker_or_publication():
    value = report(job(), compute(request()))
    assert value['valid'] and value['protocol'] == 'gee_contract_mock'
    assert not set(value) & {'worker_id', 'actor', 'publishable', 'path', 'sql', 'project_id'}


@pytest.mark.parametrize('code', ['NATIVE_TIMEOUT', 'NATIVE_MEMORY_LIMIT', 'NATIVE_PROCESS_FAILED', 'WORKER_SHUTDOWN', 'NATIVE_OUTPUT_LIMIT'])
def test_bounded_infrastructure_failure_protocol(code):
    value = report(job(), infrastructure_error=code)
    assert value['valid'] is False and value['output'] is None
    with pytest.raises(ValueError): report(job(), compute(request()), infrastructure_error=code)


def test_unknown_failure_and_missing_report_rejected():
    with pytest.raises(ValueError): report(job(), infrastructure_error='ARBITRARY_COMMAND')
    with pytest.raises(ValueError): report(job())


def test_target_subject_mismatch_and_unknown_actions_fail_before_worker_rpc():
    calls = []
    def wrong(name, payload):
        calls.append(name)
        return {}
    hooks = MockQueueHooks(wrong, subject=str(uuid4()), runtime_instance='b' * 32, baseline_fingerprint='c' * 64)
    with pytest.raises(ValueError, match='GEE_MOCK_TARGET_REJECTED'): hooks.call('claim')
    assert calls == ['gis_gee_mock_readiness']
    with pytest.raises(ValueError, match='GEE_MOCK_ACTION_REJECTED'): hooks.call('activate')
    assert calls == ['gis_gee_mock_readiness']


def test_success_uses_only_readiness_and_protocol_rpc():
    calls = []
    subject = str(uuid4())
    hooks = None
    def rpc(name, payload):
        calls.append((name, payload))
        return hooks.expected if name == 'gis_gee_mock_readiness' else {'state': 'succeeded'}
    hooks = MockQueueHooks(rpc, subject=subject, runtime_instance='b' * 32, baseline_fingerprint='c' * 64)
    assert hooks.complete(job(), compute(request()))['state'] == 'succeeded'
    assert [n for n, _ in calls] == ['gis_gee_mock_readiness', 'gis_gee_mock_worker']
    assert calls[-1][1]['p_action'] == 'complete'


def test_external_processing_api_and_existing_live_stub_stay_closed():
    from gis_schemas import ProcessingCreate
    from gis_worker.processing_provider import LiveGeeAdapter, ProcessingError
    with pytest.raises(ValidationError):
        ProcessingCreate(province='Bangkok Metropolis', metric='ndvi', data_year=2025, mode='live_gee')
    with pytest.raises(ProcessingError, match='GEE_LIVE_NOT_APPROVED'): LiveGeeAdapter().compute()


def test_operator_approval_gate_requires_exact_source_review_and_checksum(tmp_path):
    path = Path(__file__).resolve().parents[2] / 'dev/gis_local/gee_mock_local.py'
    spec = importlib.util.spec_from_file_location('a62_unit_operator', path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    value = json.loads((path.parent / 'gee-mock-review.json').read_text(encoding='utf-8'))
    local = object.__new__(mod.GeeMockLocal)
    for change in ('missing', 'empty', 'extra', 'wrong_source', 'wrong_sql'):
        invalid = deepcopy(value)
        if change == 'missing': invalid.pop('source_files')
        elif change == 'empty': invalid['source_files'] = {}
        elif change == 'extra': invalid['source_files']['outside.py'] = '0' * 64
        elif change == 'wrong_source': invalid['source_files'][str(next(iter(value['source_files'])))] = '0' * 64
        else: invalid['files'][mod.MIGRATION.name] = '0' * 64
        target = tmp_path / (change + '.json')
        target.write_text(json.dumps(invalid), encoding='utf-8')
        with pytest.raises(RuntimeError): local.reviewed(target)
