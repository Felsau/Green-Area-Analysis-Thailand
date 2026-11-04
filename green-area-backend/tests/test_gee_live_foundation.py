"""A6.4b synthetic response/SDK graph tests; no actual Google calls."""
from copy import deepcopy
from datetime import date
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from gis_worker.gee_live_contracts import Content, Output, Request, registered_input, queue_report, digest, canonical
from gis_worker.gee_live_bridge import BridgeError, InjectedBridge, build_graph
from gis_worker.gee_live_injected import InjectedSDK, InjectedTransport, fixture
from gis_worker.gee_live_worker import LiveClient, LiveWorker, require_live_runtime
from gis_worker.worker import GisWorker, LocalWorkerClient, WorkerError


def compute(request, geometry, response):
    sdk, transport = InjectedSDK(), InjectedTransport(response)
    output = InjectedBridge(sdk=sdk, transport=transport, authorization=lambda: request.project,
                           as_of=date(2026, 1, 1)).compute(request, geometry)
    return output, sdk, transport


@pytest.mark.parametrize('product', ['ndvi', 'lst'])
@pytest.mark.parametrize('month', [0, 2, 12])
@pytest.mark.parametrize('scenario,status', [('candidate', 'candidate'), ('zero', 'candidate'),
    ('no_data', 'no_data'), ('all_masked', 'no_data'), ('incomplete', 'incomplete')])
def test_science_and_missing_are_distinct(product, month, scenario, status):
    request, geometry, response = fixture('a' * 12, product=product, month=month, scenario=scenario)
    output, sdk, transport = compute(request, geometry, response)
    assert output.content.status == status and output.content.synthetic is True
    assert output.content.publishable is False and output.content.execution == 'injected'
    assert output.content.request.scope.kind == 'sandbox_roi'
    assert transport.calls == 1
    if status != 'candidate':
        assert output.content.statistics.mean is None
    elif scenario == 'zero':
        assert output.content.statistics.mean == 0
    if month:
        assert output.content.statistics.min is None and output.content.statistics.max is None
    calls = sdk.calls
    assert all('Initialize' not in name for name, _, _ in calls)
    assert any(name.endswith('reduceRegion') and kwargs.get('scale') == 500 and kwargs.get('bestEffort') is True for name, _, kwargs in calls)
    if product == 'ndvi':
        assert any(name.endswith('normalizedDifference') and args == (['B8', 'B4'],) for name, args, _ in calls)
        assert any(name.endswith('divide') and args == (10000,) for name, args, _ in calls)
        assert any(name.endswith('gte') and args == (0.6,) for name, args, _ in calls)
        assert any(name.endswith('gte') and args == (0,) for name, args, _ in calls) == (month == 0)
    else:
        for suffix, value in [('multiply', 0.00341802), ('add', 149.0), ('subtract', 273.15), ('bitwiseAnd', 8), ('bitwiseAnd', 16)]:
            assert any(name.endswith(suffix) and args == (value,) for name, args, _ in calls)


def test_live_rejected_before_auth_sdk_or_transport_and_runtime_cannot_be_enabled_by_payload():
    request, geometry, raw = fixture('b' * 12)
    live = Request.model_validate(request.model_dump(mode='json') | {'execution': 'live'})
    bridge = InjectedBridge(sdk=object(), transport=object(), authorization=lambda: pytest.fail('auth called'), as_of=date(2026, 1, 1))
    with pytest.raises(BridgeError, match='NOT_APPROVED'): bridge.compute(live, geometry)
    with pytest.raises(BridgeError, match='NOT_APPROVED'): build_graph(object(), live, geometry)
    with pytest.raises(ValueError): registered_input(live, geometry)
    with pytest.raises(WorkerError, match='DISABLED'):
        require_live_runtime(image='anything', command=('anything',), restricted_egress=True, credential_channel=True)


@pytest.mark.parametrize('field', ['project', 'geometry', 'period', 'method', 'output', 'evidence', 'status', 'scope'])
def test_forged_output_or_identity_rejected(field):
    request, geometry, response = fixture('c' * 12)
    output, _, _ = compute(request, geometry, response)
    value = output.model_dump(mode='json')
    content = value['content']
    if field == 'project': content['evidence']['project']['project_id'] = 'other-project'
    elif field == 'geometry': content['geometry_sha256'] = '0' * 64
    elif field == 'period': content['evidence']['period']['year'] = 2024
    elif field == 'method': content['evidence']['method']['st_multiplier'] = 0.01
    elif field == 'output': content['statistics']['mean'] = 0.8
    elif field == 'evidence': content['evidence_sha256'] = '0' * 64
    elif field == 'status': content['status'] = 'no_data'
    elif field == 'scope': content['request']['scope']['kind'] = 'province'
    value['output_sha256'] = digest(content)
    with pytest.raises(ValueError): Output.model_validate(value)


@pytest.mark.parametrize('change', ['overflow', 'truncated', 'duplicate', 'foreign', 'future', 'wrong_type', 'secret', 'infinite'])
def test_scene_evidence_is_bounded_not_truncated(change):
    request, geometry, raw = fixture('d' * 12)
    if change == 'overflow': raw['scene_ids'] *= 33; raw['acquired_ms'] *= 33; raw['scene_count'] = 33
    elif change == 'truncated': raw['scene_count'] = 2
    elif change == 'duplicate': raw['scene_ids'] *= 2; raw['acquired_ms'] *= 2; raw['scene_count'] = 2
    elif change == 'foreign': raw['scene_ids'] = ['UNAPPROVED/INJECTED']
    elif change == 'future': raw['acquired_ms'] = [2000000000000]
    elif change == 'wrong_type': raw['scene_count'] = True
    elif change == 'secret': raw['access_token'] = 'synthetic-must-not-accept'
    elif change == 'infinite': raw['mean'] = float('inf')
    with pytest.raises(ValueError): compute(request, geometry, raw)


def test_unknown_pixels_and_open_period_are_incomplete():
    request, geometry, raw = fixture('e' * 12)
    raw['valid_pixels'] = None
    output, _, _ = compute(request, geometry, raw)
    assert output.content.status == 'incomplete'
    raw['valid_pixels'] = 2
    output = InjectedBridge(sdk=InjectedSDK(), transport=InjectedTransport(raw), authorization=lambda: request.project,
        as_of=date(2025, 6, 1)).compute(request, geometry)
    assert output.content.status == 'incomplete'


@pytest.mark.parametrize('case', ['missing_mean', 'contradictory_nodata', 'wrong_project', 'real_sdk', 'real_transport'])
def test_missing_or_unapproved_evidence_never_becomes_a_candidate(case):
    request, geometry, raw = fixture('e' * 12)
    if case == 'missing_mean':
        raw.update(mean=None, min=None, max=None)
        output, _, _ = compute(request, geometry, raw)
        assert output.content.status == 'incomplete'
        return
    if case == 'contradictory_nodata': raw['valid_pixels'] = 0
    project = request.project if case != 'wrong_project' else None
    sdk = object() if case == 'real_sdk' else InjectedSDK()
    transport = object() if case == 'real_transport' else InjectedTransport(raw)
    with pytest.raises(ValueError):
        InjectedBridge(sdk=sdk, transport=transport, authorization=lambda: project,
                       as_of=date(2026, 1, 1)).compute(request, geometry)


def test_v2_canonical_identity_is_not_json_whitespace_or_numeric_spelling():
    assert canonical({'z': -0.0, 'a': [100.0, 0.000001, 'ไทย']}) == '{"a":[100,0.000001,"ไทย"],"z":0}'
    assert digest({'x':100.0}) == digest({'x':100})
    with pytest.raises(ValueError): canonical({'x':float('inf')})


def test_report_hashes_and_role_loop_reuse():
    request, geometry, raw = fixture('f' * 12)
    output, _, _ = compute(request, geometry, raw)
    registered = registered_input(request, geometry)
    assert 'output' not in registered and 'expected_output' not in registered
    job = {'input_hash': 'b' * 64, 'input_revision': 1, 'semantic_request_sha256': request.request_hash()}
    report = queue_report(job, output)
    assert report['protocol'] == 'gee_live_v2' and report['valid'] is True
    assert json.loads(report['evidence_canonical']) == output.content.evidence.model_dump(mode='json')
    assert LiveWorker.run is GisWorker.run and LiveWorker.process_job is GisWorker.process_job
    assert LiveClient.JWT_ROLE != LocalWorkerClient.JWT_ROLE
    assert set(LiveClient.RPC_NAMES) == {'gis_gee_live_worker', 'gis_gee_live_readiness'}
    assert not {'access_token','lease_token','worker_id'} & LiveWorker(None).build_native_request(job | {'request':{},'geometry':{},'worker_id':'private','lease_token':'private'}).keys()


def test_import_and_cli_never_discover_credentials_or_network():
    root = Path(__file__).resolve().parents[1]
    code = r'''
import sys,os
sys.path.insert(0,sys.argv[1])
def audit(event,args):
 if event.startswith('socket.') or event.startswith('urllib.'): raise AssertionError('network')
 if event=='open' and isinstance(args[0],(str,bytes)):
  name=os.path.basename(os.fsdecode(args[0])).lower()
  if name.startswith('.env') or name in ('credentials','credentials.json'): raise AssertionError('credentials')
sys.addaudithook(audit)
import gis_worker.gee_live_contracts, gis_worker.gee_live_bridge, gis_worker.gee_live_worker
assert not any(x in sys.modules for x in ('ee','google.auth','dotenv','main','dependencies'))
from gis_worker.gee_live_worker import require_live_runtime
try: require_live_runtime()
except Exception as error: assert str(error)=='GEE_LIVE_RUNTIME_DISABLED'
else: raise AssertionError('gate')
'''
    result = subprocess.run([sys.executable, '-I', '-B', '-c', code, str(root)], env={'SYSTEMROOT':os.environ.get('SYSTEMROOT',r'C:\Windows')}, capture_output=True, timeout=15)
    assert result.returncode == 0
