"""A6.3 API authorization/closed-contract checks with mock Auth/RPC only."""
from types import SimpleNamespace
from uuid import uuid4

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest

from gis_app import create_app
from gis_runtime import LOCAL_URL

ACTOR = '11111111-1111-4111-8111-111111111111'
CASE = '22222222-2222-4222-8222-222222222222'
JOB = '33333333-3333-4333-8333-333333333333'
EDITION = '44444444-4444-4444-8444-444444444444'


class Runtime:
    sandbox_activation_enabled = False

    def __init__(self):
        self.settings = SimpleNamespace(enabled=True, api_url=LOCAL_URL, database='postgres',
                                        cluster='green-area-gis-t0', mode='local_synthetic')
        self.officer, self.admin, self.database_gate = True, False, False
        self.calls = []
        self.case_id = CASE

    def require_ready(self):
        return {'migration_versions': list(range(27, 44))}

    def verify_user_token(self, value):
        if value != 'mock-user':
            raise HTTPException(401)
        return ACTOR

    def rpc(self, name, payload):
        self.calls.append((name, payload))
        if name == 'gis_read' and payload['p_kind'] == 'me':
            return {'officer': self.officer, 'admin': self.admin, 'activation_enabled': self.database_gate}
        if name == 'gis_read' and payload['p_kind'] == 'history':
            return {'data': [{'operation': 'gee_mock.create', 'worker_id': 'private'}]}
        if name == 'gis_gee_mock_command':
            return {'status': 202, 'body': {'job_id': JOB, 'execution': 'mock', 'live_enabled': False, 'publishable': False}}
        if name == 'gis_gee_mock_read':
            return {'job': {'id': JOB, 'state': 'running', 'lease_token': 'private', 'worker_id': 'private'},
                    'request': {'case_id': self.case_id, 'edition_id': EDITION},
                    'attempts': [{'attempt_no': 1, 'lease_token': 'private', 'validation_report': None}], 'candidate': None}
        raise AssertionError(name)


@pytest.fixture
def api():
    runtime = Runtime()
    with TestClient(create_app(runtime, rate_limit='10000/minute', gee_mock_catalog={'ndvi-annual': CASE})) as client:
        client.headers['Authorization'] = 'Bearer mock-user'
        yield client, runtime


def post(client, **changes):
    return client.post('/gis/mock-gee/jobs', json={'mode': 'gee_contract_mock', 'case_key': 'ndvi-annual'} | changes,
                       headers={'Idempotency-Key': str(uuid4())})


def test_only_explicit_catalog_options_are_exposed(api):
    client, _ = api
    value = client.get('/gis/mock-gee/options').json()
    assert value == {'protocol': 'gee_contract_mock', 'execution': 'mock', 'synthetic': True,
                     'live_enabled': False, 'publishable': False, 'case_keys': ['ndvi-annual']}


def test_create_forwards_only_trusted_actor_case_and_idempotency(api):
    client, runtime = api
    response = post(client)
    assert response.status_code == 202
    _, payload = runtime.calls[-1]
    assert payload['p_actor'] == ACTOR and payload['p_payload'] == {'case_id': CASE}
    assert payload['p_backend_mock'] is True and response.json()['publishable'] is False


@pytest.mark.parametrize('extra', [{'mode': 'live_gee'}, {'mode': 'offline_synthetic'}, {'case_key': 'unknown'},
    {'case_id': CASE}, {'worker_id': ACTOR}, {'actor': ACTOR}, {'output': {'valid': True}},
    {'expected_output': {}}, {'geometry': {}}, {'project': 'production'}, {'path': '/private'},
    {'url': 'https://example.invalid'}, {'command': 'anything'}, {'sql': 'SELECT 1'}, {'publishable': True}])
def test_user_cannot_supply_protocol_or_oracle_authority(api, extra):
    client, runtime = api
    assert post(client, **extra).status_code == 422
    assert not any(name == 'gis_gee_mock_command' for name, _ in runtime.calls)


@pytest.mark.parametrize('gate', ['database', 'backend', 'target'])
def test_gate_or_target_mismatch_precedes_job_creation(api, gate):
    client, runtime = api
    if gate == 'database':
        runtime.database_gate = True
    elif gate == 'backend':
        runtime.sandbox_activation_enabled = True
    else:
        runtime.settings.api_url = 'https://example.invalid'
    assert post(client).status_code == 503
    assert not any(name == 'gis_gee_mock_command' for name, _ in runtime.calls)


def test_normal_user_and_worker_tokens_cannot_use_officer_api(api):
    client, runtime = api
    runtime.officer = False
    assert post(client).status_code == 403
    client.headers['Authorization'] = 'Bearer mock-worker'
    assert post(client).status_code == 401


def test_disabled_by_default_and_missing_key(api):
    client, runtime = api
    with TestClient(create_app(runtime, rate_limit='10000/minute')) as disabled:
        disabled.headers['Authorization'] = 'Bearer mock-user'
        assert post(disabled).status_code == 503
    assert client.post('/gis/mock-gee/jobs', json={'mode': 'gee_contract_mock', 'case_key': 'ndvi-annual'}).status_code == 422


def test_status_history_strip_worker_authority_and_only_read_current_catalog(api):
    client, runtime = api
    value = client.get(f'/gis/mock-gee/jobs/{JOB}').json()
    assert value['execution'] == 'mock' and value['live_enabled'] is False
    assert 'lease_token' not in str(value) and 'worker_id' not in str(value)
    history = client.get(f'/gis/mock-gee/jobs/{JOB}/history')
    assert history.status_code == 200 and 'worker_id' not in history.text
    runtime.case_id = str(uuid4())
    assert client.get(f'/gis/mock-gee/jobs/{JOB}').status_code == 404
