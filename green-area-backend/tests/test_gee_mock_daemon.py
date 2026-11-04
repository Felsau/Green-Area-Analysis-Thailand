"""Pure mock dispatch and daemon specialization; actual Linux lifecycle is E2E."""
import base64
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from uuid import uuid4

import pytest

from gis_worker.gee_mock_fixtures import SPECS, GEOMETRY, case_for, execute
from gis_worker.gee_mock_worker import MockClient, MockWorker
from gis_worker.worker import GisWorker, LocalWorkerClient, WorkerError


@pytest.fixture
def legacy(tmp_path):
    backend = Path(__file__).resolve().parents[1]
    for target, source in [('gee_utils.py', 'gee_utils.py'), ('ndvi_compute.py', 'routers/ndvi/compute.py'), ('lst.py', 'routers/lst.py')]:
        (tmp_path / target).write_bytes((backend / source).read_bytes())
    return tmp_path


def packet(value, attempt=1):
    return {'request': deepcopy(value['request']), 'geometry': deepcopy(value['geometry']),
            'input_hash': 'b' * 64, 'input_revision': 1,
            'semantic_request_sha256': value['request_sha256'], 'attempt_number': attempt}


@pytest.mark.parametrize('key', list(SPECS))
def test_all_trusted_mock_case_outputs_use_same_adapter_as_worker(legacy, key):
    value = case_for(key, 'a' * 12, legacy_root=legacy)
    waits = []
    output = execute(packet(value, 2), legacy_root=legacy, sleep=waits.append)
    if key == 'retry-exhausted':
        assert output['output'] is None and output['error_code'] == 'NATIVE_PROCESS_FAILED'
    else:
        assert output['output'] == value['output']
        assert output['output']['content']['execution'] == 'mock'
        assert output['output']['content']['publishable'] is False
    assert waits == ([12] if key == 'long-running' else [])


def test_retry_behavior_is_fixed_by_fixture_not_api_delay_or_command(legacy):
    value = case_for('retry-once', 'a' * 12, legacy_root=legacy)
    assert execute(packet(value), legacy_root=legacy, sleep=lambda _: None)['output'] is None
    assert execute(packet(value, 2), legacy_root=legacy, sleep=lambda _: None)['valid'] is True
    for field in ('command', 'delay', 'expected_output', 'path', 'worker_id'):
        with pytest.raises(ValueError):
            execute(packet(value) | {field: 'untrusted'}, legacy_root=legacy, sleep=lambda _: None)


def test_unapproved_scope_and_geometry_are_rejected(legacy):
    value = case_for('ndvi-annual', 'a' * 12, legacy_root=legacy)
    for change in ('scope', 'geometry'):
        data = packet(value)
        if change == 'scope':
            data['request']['boundary']['province'] = 'Other Province'
        else:
            data['geometry']['coordinates'][0][1][0] = 100.5
        with pytest.raises(ValueError): execute(data, legacy_root=legacy, sleep=lambda _: None)


def test_native_daemon_loop_and_credentials_boundary_are_reused():
    assert MockWorker.run is GisWorker.run and MockWorker.process_job is GisWorker.process_job
    assert MockWorker._execute_native is GisWorker._execute_native
    assert LocalWorkerClient.JWT_ROLE == 'gis_native_worker' and MockClient.JWT_ROLE == 'gis_gee_mock_worker'
    assert set(MockClient.RPC_NAMES) == {'gis_gee_mock_worker', 'gis_gee_mock_readiness'}
    worker = MockWorker(None)
    job = {'request': {}, 'geometry': {}, 'input_hash': 'a' * 64, 'input_revision': 1,
           'semantic_request_sha256': 'b' * 64, 'attempt_number': 1,
           'lease_token': 'private', 'worker_id': 'private', 'access_token': 'private'}
    subset = worker.build_native_request(job)
    assert not set(subset) & {'lease_token', 'worker_id', 'access_token'}
    assert worker.failure_report(subset, 'WORKER_SHUTDOWN')['output'] is None
    with pytest.raises(WorkerError): worker.failure_report(subset, 'ARBITRARY')


def test_only_dedicated_role_claims_are_accepted_by_new_transport():
    subject = str(uuid4())
    mock = object.__new__(MockClient)
    mock.subject = subject
    native = object.__new__(LocalWorkerClient)
    native.subject = subject
    def token(role):
        value = json.dumps({'sub': subject, 'role': role, 'iss': 'http://127.0.0.1:55421/auth/v1', 'exp': 2000000000}).encode()
        return 'header.' + base64.urlsafe_b64encode(value).decode().rstrip('=') + '.not-a-signature'
    assert mock._claims(token('gis_gee_mock_worker'))['sub'] == subject
    with pytest.raises(WorkerError): mock._claims(token('gis_native_worker'))
    with pytest.raises(WorkerError): native._claims(token('gis_gee_mock_worker'))


def test_child_guards_deny_udp_process_credential_and_sdk_access():
    root = Path(__file__).resolve().parents[1]
    code = r'''
import sys,socket,subprocess
sys.path.insert(0,sys.argv[1])
from gis_worker.gee_mock_child import install_guards
install_guards()
checks=[lambda:socket.socket(socket.AF_INET,socket.SOCK_DGRAM),
 lambda:socket.getaddrinfo('example.invalid',443),
 lambda:subprocess.Popen([sys.executable,'-c','pass']),
 lambda:open('/tmp/credentials'),lambda:__import__('ee'),lambda:__import__('google.auth')]
for check in checks:
 try: check()
 except RuntimeError as error: assert str(error).startswith('GEE_MOCK_CHILD_')
 else: raise AssertionError('Guard was bypassed')
print('CHILD_GUARDS_PASS')
'''
    result = subprocess.run([sys.executable, '-I', '-B', '-c', code, str(root)], capture_output=True,
                            text=True, timeout=15, env={'SYSTEMROOT': os.environ.get('SYSTEMROOT', r'C:\Windows')})
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == 'CHILD_GUARDS_PASS'
