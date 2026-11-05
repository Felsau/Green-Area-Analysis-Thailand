"""All delivery signatures, TLS peers and HTTPS bytes here are SYNTHETIC.

Sockets are replaced; a valid Output is not evidence of real Google compute.
Production constructors remain closed, including after all these tests pass.
"""
from dataclasses import replace
from datetime import date
import hashlib
import json
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4, UUID

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from gis_worker.gee_genuine_identity import (CredentialDelivery, ExplicitGoogleCredentials,
    GenuineBoundaryError, PROJECT_ID, PROJECT_NUMBER, PRINCIPAL, PRINCIPAL_ID)
from gis_worker.gee_genuine_runtime import GenuineBinding, require_genuine_runtime
from gis_worker.gee_genuine_transport import GenuineHTTPSWire, GenuinePhysicalHTTP, GenuineSDKAdapter
from gis_worker.gee_live_contracts import Request, canonical, digest
from gis_worker.gee_live_injected import fixture
from gis_worker.gee_sdk_transport import FakeHTTPWire


def packet(product='ndvi', scenario='candidate'):
    req, geom, raw = fixture(uuid4().hex[:12], product=product, month=2, scenario=scenario)
    req = Request.model_validate(req.model_dump(mode='json') | {'execution': 'live', 'project': {
        'project_id': PROJECT_ID, 'project_number': PROJECT_NUMBER,
        'principal': PRINCIPAL, 'readiness': 'verified_sandbox'}})
    token = uuid4()
    binding = GenuineBinding(worker_subject=uuid4(), recorder_subject=uuid4(),
        session_id=uuid4(), job_id=uuid4(), attempt_number=1, project=req.project,
        principal_id=PRINCIPAL_ID, input_revision=1, input_hash='a'*64,
        request_sha256=req.request_hash(), method_sha256=digest(req.method.model_dump(mode='json')),
        geometry_sha256=req.scope.geometry_sha256, lease_sha256=hashlib.sha256(token.bytes).hexdigest(), runtime_id=uuid4())
    job = {'id': str(binding.job_id), 'session_id': str(binding.session_id),
        'worker_id': str(binding.worker_subject), 'attempt_number': 1, 'lease_token': str(token),
        'input_hash': binding.input_hash, 'input_revision': 1, 'job_remaining_seconds': 180,
        'geometry': geom, 'request': req.model_dump(mode='json')}
    return req, geom, raw, binding, job


def delivered(binding, *, wall=None, mono=None, change=None):
    wall, mono = wall or [1000.0], mono or [10.0]
    key = Ed25519PrivateKey.generate()  # ephemeral synthetic broker, not Google
    delivery = CredentialDelivery(b'synthetic-bearer-only', PROJECT_ID, PROJECT_NUMBER,
        PRINCIPAL, PRINCIPAL_ID, 990, 1200, binding.fingerprint(), b'')
    if change:
        delivery = replace(delivery, **change)
    delivery = replace(delivery, signature=key.sign(delivery.signed_message()))
    provider = ExplicitGoogleCredentials(delivery, binding, issuer_key=key.public_key().public_bytes_raw(),
        wall=lambda: wall[0], monotonic=lambda: mono[0])
    return provider, delivery, key, wall, mono


def test_signed_explicit_memory_delivery_without_adc_or_logging():
    _, _, _, binding, _ = packet()
    c, d, _, _, _ = delivered(binding)
    assert c.headers(binding) == {'Authorization': 'Bearer synthetic-bearer-only'}
    assert 'synthetic-bearer' not in repr(c) + repr(d)
    assert c.sdk_credentials(binding).token is None
    with pytest.raises(GenuineBoundaryError, match='REDELIVERY'):
        c.sdk_credentials(binding).refresh(lambda *a: pytest.fail('auth HTTP'))
    c.close()
    with pytest.raises(GenuineBoundaryError): c.headers(binding)


@pytest.mark.parametrize('field,value', [('principal', 'other@green-area-gis-sandbox.iam.gserviceaccount.com'),
    ('project_id', 'innate-beacon-483307-v1'), ('project_number', '122535800048'),
    ('principal_id', '123456789'), ('binding_sha256', 'b'*64),
    ('issued_at', 1001), ('expires_at', 1001), ('expires_at', 4000)])
def test_wrong_or_expired_identity_even_with_signed_envelope(field, value):
    _, _, _, binding, _ = packet()
    with pytest.raises(GenuineBoundaryError): delivered(binding, change={field:value})


def test_signature_token_binding_and_monotonic_expiry():
    _, _, _, binding, _ = packet()
    c, d, key, wall, mono = delivered(binding)
    with pytest.raises(GenuineBoundaryError, match='ATTESTATION'):
        ExplicitGoogleCredentials(replace(d, token=b'synthetic-forged-bearer'), binding,
            issuer_key=key.public_key().public_bytes_raw(), wall=lambda:1000, monotonic=lambda:10)
    wall[0] = 900  # clock rollback cannot extend lifetime
    mono[0] = 211
    with pytest.raises(GenuineBoundaryError, match='EXPIRED'): c.authorize(binding)


def test_explicit_renewal_same_binding_and_new_signature_only():
    _, _, _, b, _ = packet()
    c, d, key, wall, mono = delivered(b)
    wall[0] = 1001
    new = replace(d, token=b'synthetic-replacement-only', issued_at=1001, expires_at=1300, signature=b'')
    new = replace(new, signature=key.sign(new.signed_message()))
    c.replace(new, b)
    assert c.headers(b)['Authorization'].endswith('synthetic-replacement-only')
    with pytest.raises(GenuineBoundaryError): c.replace(d, b)
    with pytest.raises(GenuineBoundaryError): c.authorize(b.model_copy(update={'job_id':uuid4()}))


def test_runtime_remains_disabled_with_provider_or_caller_flags():
    _, _, _, b, _ = packet(); c, *_ = delivered(b)
    with pytest.raises(GenuineBoundaryError, match='RUNTIME_DISABLED'):
        require_genuine_runtime(binding=b, credentials=c, image='sha256:'+'a'*64, egress=True)
    with pytest.raises(GenuineBoundaryError, match='EGRESS'):
        GenuineHTTPSWire(binding=b, credentials=c, egress=True, deadline=180)


class Recorder:
    def __init__(self, budget=32): self.rows={}; self.events=[]; self.budget=budget; self.sealed=None
    def __call__(self, action, value):
        self.events.append(action)
        if action=='reserve':
            if len(self.rows)>=self.budget:return {'granted':False}
            rid=str(uuid4());self.rows[rid]={'state':'reserved','kind':value['kind']}
            return {'request_id':rid,'state':'reserved'}
        if action=='seal': self.sealed=value; return value
        row=self.rows[value['request_id']]
        if action=='attempted': assert row['state']=='reserved';row['state']='attempted'
        elif action=='response':
            assert row['state']=='attempted'
            assert value['response_sha256']==hashlib.sha256(value['response_body'].encode()).hexdigest()
            row.update(value);row['state']='recorded'
        elif action=='uncertain': row['state']='uncertain'
        return {'state':row['state']}


def run_sdk(product='ndvi', scenario='candidate', statuses=(), budget=32):
    req,geom,raw,b,j=packet(product,scenario);creds,*_=delivered(b)
    synthetic_req=req.model_copy(update={'execution':'injected'})
    fake=FakeHTTPWire(raw,responses=statuses); recorder=Recorder(budget)
    class Connection:
        def __init__(self, host, **kwargs):
            self.host=host; self.sock=SimpleNamespace(getpeername=lambda:('8.8.8.8',443),
                version=lambda:'TLSv1.3',getpeercert=lambda **kw:b'synthetic-certificate')
            assert kwargs['context'].check_hostname
            assert kwargs['context'].keylog_filename is None
        def connect(self): pass
        def close(self): pass
        def request(self, method, path, body=None, headers=None):
            assert recorder.events[-1]=='attempted'
            uri='https://'+self.host+path
            category=http.category(uri,method)
            if category=='catalog':assert 'Authorization' not in headers
            else:assert headers['Authorization']=='Bearer synthetic-bearer-only'
            self.status,self.body=fake.send(category,uri,method,body or b'')
        def getresponse(self):
            return SimpleNamespace(status=self.status,getheader=lambda *a:'identity',read=lambda n:self.body)
    with patch('gis_worker.gee_genuine_transport.require_selective_egress',lambda *a:None), \
        patch('gis_worker.gee_genuine_transport.http.client.HTTPSConnection',Connection), patch('time.sleep',lambda *a:None):
        wire=GenuineHTTPSWire(binding=b,credentials=creds,egress=None,deadline=10**20)
        http=GenuinePhysicalHTTP(recorder,j,wire,binding=b)
        result=GenuineSDKAdapter(http,credentials=creds).compute(req,geom,as_of=date(2026,1,1))
    return result,recorder,fake


@pytest.mark.parametrize('product',['ndvi','lst'])
@pytest.mark.parametrize('scenario',['candidate','zero','no_data','all_masked','incomplete'])
def test_real_sdk_with_synthetic_tls_exchange_only(product, scenario):
    output,r,f=run_sdk(product,scenario)
    assert not output.content.synthetic and not output.content.publishable
    assert len(r.rows)==len(f.calls)==5
    assert all('Authorization' not in canonical(row) and 'synthetic-bearer' not in canonical(row) for row in r.rows.values())
    assert output.content.statistics.mean==(0 if scenario=='zero' else .25 if product=='ndvi' else 30) if scenario in ('candidate','zero') else output.content.statistics.mean is None


def test_sdk_retry_still_reserves_each_physical_exchange():
    _,r,f=run_sdk(statuses=[503,200])
    assert len(r.rows)==len(f.calls)==6
    assert sum(x['kind']=='sdk_retry' for x in r.rows.values())==1


def test_budget_denial_does_not_create_unobserved_send():
    with pytest.raises(ValueError,match='BUDGET'):run_sdk(budget=2)


def test_no_implicit_refresh_after_401():
    with pytest.raises(GenuineBoundaryError,match='REDELIVERY'):run_sdk(statuses=[401,200])


def test_failure_report_is_fixed_and_contains_no_raw_credential_errors():
    import threading
    from gis_worker.gee_genuine_worker import GenuineQueueWorker
    req,geom,raw,b,job=packet()
    job |= {'semantic_request_sha256':req.request_hash(),'policy_sha256':'b'*64}
    obj=object.__new__(GenuineQueueWorker)
    obj._stop_event=threading.Event();obj._lease_lost=threading.Event()
    def fail(*a,**k):raise ValueError('synthetic-sensitive-error-do-not-report')
    obj.runtime=SimpleNamespace(compute=fail)
    report=obj._execute_native(job)
    assert report['error_code']=='NATIVE_PROCESS_FAILED' and report['base']['output'] is None
    assert 'sensitive-error' not in canonical(report)


def test_inherited_ssl_env_cannot_enable_key_logging_or_replace_ca(tmp_path):
    import os
    path=tmp_path/'must-not-exist-keylog'
    with patch.dict(os.environ,{'SSLKEYLOGFILE':str(path),'SSL_CERT_FILE':str(tmp_path/'unknown-ca')}):
        run_sdk()
    assert not path.exists()
