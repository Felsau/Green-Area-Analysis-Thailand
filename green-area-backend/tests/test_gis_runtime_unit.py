"""Mock-only JWT/target boundary tests. Real signature/Auth E2E is separate."""
from dataclasses import replace
import time
from types import SimpleNamespace
from uuid import uuid4

import httpx
import jwt
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from gis_app import create_app
from gis_runtime import GISRuntime, LocalGISSettings, LOCAL_ISSUER, read_proof_scope

ACTOR = str(uuid4())
DUMMY_KEY = "dummy-unit-signing-material-only-never-a-real-key"
SETTINGS = LocalGISSettings(enabled=True, runtime_instance="a"*32, baseline_fingerprint="b"*64)


def proof():
    return {"database":"postgres", "cluster":"green-area-gis-t0", "instance":"a"*32,
        "baseline_fingerprint":"b"*64, "containers_healthy":True}


class FakeClient:
    def __init__(self):
        self.calls = []
        self.auth = SimpleNamespace(get_user=self.user)
        self.user_calls = 0
        self.user_id = ACTOR
        self.failure = None
        self.readiness = {"runtime_instance":"a"*32,"baseline_fingerprint":"b"*64,
            "database_name":"postgres","cluster_name":"green-area-gis-t0","mode":"local_synthetic",
            "migration_versions":[27,28,29,30],"contract_version":"1.1.0-t2"}

    def user(self, token):
        self.user_calls += 1
        if self.failure:
            raise self.failure
        return SimpleNamespace(user=SimpleNamespace(id=self.user_id))

    def rpc(self, name, params):
        self.calls.append(name)
        return SimpleNamespace(execute=lambda:SimpleNamespace(data=self.readiness if name=='gis_readiness' else {"ok":True}))


def runtime():
    auth, service = FakeClient(), FakeClient()
    instance = GISRuntime(SETTINGS, attest=proof, clients=lambda url:(auth,service))
    return instance, auth, service


def token(**overrides):
    now=int(time.time())
    claims={"iss":LOCAL_ISSUER,"aud":"authenticated","sub":ACTOR,"role":"authenticated","iat":now-1,"exp":now+60}
    claims.update(overrides)
    return jwt.encode(claims,DUMMY_KEY,algorithm="HS256")


def test_valid_claims_still_require_trusted_auth_response():
    instance, auth, _ = runtime()
    assert instance.verify_user_token(token()) == ACTOR
    assert auth.user_calls == 1


@pytest.mark.parametrize('change',[
    {"iss":"https://unknown.invalid/auth/v1"},{"aud":"service_role"},{"role":"admin"},
    {"exp":1},{"iat":int(time.time())+300},{"nbf":int(time.time())+300},
    {"sub":"not-a-uuid"},{"is_anonymous":True},{"exp":True},{"exp":str(int(time.time())+60)}])
def test_invalid_claims_rejected_before_auth(change):
    instance, auth, _ = runtime()
    with pytest.raises(HTTPException) as error:
        instance.verify_user_token(token(**change))
    assert error.value.status_code == 401 and auth.user_calls == 0


def test_matching_subject_is_required_after_auth():
    instance, auth, _ = runtime();auth.user_id=str(uuid4())
    with pytest.raises(HTTPException) as error:
        instance.verify_user_token(token())
    assert error.value.status_code == 401


def test_auth_unavailable_is_not_misreported_as_invalid_login():
    instance, auth, _ = runtime();auth.failure=httpx.ConnectError('dummy local failure')
    with pytest.raises(HTTPException) as error:
        instance.verify_user_token(token())
    assert error.value.status_code == 503


def test_auth_signature_rejection_maps_401():
    class Rejected(Exception):
        status=401
    instance, auth, _ = runtime();auth.failure=Rejected()
    with pytest.raises(HTTPException) as error:
        instance.verify_user_token(token())
    assert error.value.status_code == 401


@pytest.mark.parametrize('url',['https://production.supabase.co','http://localhost:55421','http://127.0.0.1:55421@unknown.invalid','http://127.0.0.1:55421/path'])
def test_unknown_targets_rejected_before_client_or_network(url):
    calls=[]
    with pytest.raises(HTTPException) as error:
        GISRuntime(replace(SETTINGS,api_url=url),attest=lambda:calls.append('attest'),clients=lambda u:calls.append('client'))
    assert error.value.status_code==503 and calls==[]


def test_disabled_runtime_never_initializes_clients():
    calls=[]
    instance=GISRuntime(clients=lambda url:calls.append(url))
    with pytest.raises(HTTPException) as error:
        instance.rpc('gis_command',{})
    assert error.value.status_code==503 and calls==[]


@pytest.mark.parametrize('field,value',[('instance','c'*32),('cluster','unknown'),('database','production'),('containers_healthy',False)])
def test_changed_transport_rejected_before_mutation(field,value):
    instance, _, service=runtime()
    instance._attest=lambda:{**proof(),field:value}
    with pytest.raises(HTTPException) as error:
        instance.rpc('gis_command',{})
    assert error.value.status_code==503 and 'gis_command' not in service.calls


@pytest.mark.parametrize('field,value',[('runtime_instance','c'*32),('mode','production'),('migration_versions',[27,28,29]),('contract_version','unknown')])
def test_changed_rpc_identity_rejected_before_mutation(field,value):
    instance, _, service=runtime();service.readiness[field]=value
    with pytest.raises(HTTPException) as error:
        instance.rpc('gis_command',{})
    assert error.value.status_code==503 and 'gis_command' not in service.calls


def test_private_and_worker_rpc_names_are_not_backend_endpoints():
    instance, _, service=runtime()
    with pytest.raises(HTTPException):instance.rpc('gis_worker',{})
    assert service.calls==[]


# One target proof per GIS read request (docs/gis/w5-ldd-publication-design.md 6.4).
def counting_runtime(**change):
    instance, auth, service = runtime()
    proofs = []
    def attest():
        proofs.append(1)
        return {**proof(), **change}
    instance._attest = attest
    return instance, service, proofs


def test_a_read_scope_proves_the_target_once_and_a_new_scope_proves_again():
    instance, service, proofs = counting_runtime()
    with read_proof_scope(True):
        first = instance.require_ready()
        assert instance.rpc('gis_read', {}) == {'ok': True} and instance.rpc('gis_read', {}) == {'ok': True}
        again = instance.require_ready()
    assert len(proofs) == 1 and service.calls.count('gis_readiness') == 1
    assert again == first and again is not first   # callers get their own copy
    with read_proof_scope(True):
        instance.require_ready()
    assert len(proofs) == 2


@pytest.mark.parametrize('scope', ['mutation', 'outside a request'])
def test_mutations_and_code_outside_requests_prove_before_every_call(scope):
    instance, _, proofs = counting_runtime()
    def work():
        instance.require_ready(); instance.rpc('gis_command', {}); instance.require_ready()
    if scope == 'mutation':
        with read_proof_scope(False):
            work()
    else:
        work()
    assert len(proofs) == 3


def test_a_failed_proof_is_not_remembered():
    instance, service, proofs = counting_runtime(containers_healthy=False)
    with read_proof_scope(True):
        for _ in range(2):
            with pytest.raises(HTTPException) as error:
                instance.rpc('gis_read', {})
            assert error.value.status_code == 503
    assert len(proofs) == 2 and 'gis_read' not in service.calls


def test_a_transport_error_proves_the_target_again_before_the_retry():
    instance, service, proofs = counting_runtime()
    plain, failures = service.rpc, [httpx.ConnectError('dummy local failure')]
    def flaky(name, params):
        if name == 'gis_read' and failures:
            raise failures.pop()
        return plain(name, params)
    service.rpc = flaky
    with read_proof_scope(True):
        instance.require_ready()
        assert instance.rpc('gis_read', {}) == {'ok': True}
    assert len(proofs) == 2


def test_gis_app_proves_once_per_get_and_before_every_call_otherwise():
    instance, service, proofs = counting_runtime()
    headers = {'Authorization': 'Bearer ' + token()}
    with TestClient(create_app(instance, rate_limit='10000/minute')) as client:
        # /gis/me: Auth, one SQL read and a readiness check, in different threads.
        assert client.get('/gis/me', headers=headers).status_code == 200
        assert len(proofs) == 1
        assert client.get('/gis/me', headers=headers).status_code == 200
        assert len(proofs) == 2
        before = len(proofs)
        client.post('/gis/officers', headers={**headers, 'Idempotency-Key': str(uuid4())},
            json={'user_id': str(uuid4()), 'reason': 'unit test only'})
        assert 'gis_command' in service.calls and len(proofs) - before >= 2   # Auth and the SQL command each prove
