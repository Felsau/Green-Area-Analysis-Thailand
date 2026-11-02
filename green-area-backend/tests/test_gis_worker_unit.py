"""No-network tests for daemon target checks and lease/error control flow."""
import base64,json,time
from copy import deepcopy
from types import SimpleNamespace
import pytest
from gis_worker.worker import GisWorker,LocalWorkerClient,WorkerError,LOCAL_URL,ISSUER

SUB='11111111-1111-4111-8111-111111111111'
def bootstrap(**claims):
    c={'sub':SUB,'role':'gis_native_worker','iss':ISSUER,'exp':int(time.time())+3600,**claims}
    part=base64.urlsafe_b64encode(json.dumps(c).encode()).decode().rstrip('=')
    return {'api_url':LOCAL_URL,'subject':SUB,'anon_key':'test-placeholder','access_token':'test.'+part+'.test',
            'refresh_token':'test-placeholder','runtime_instance':'a'*32,'baseline_fingerprint':'b'*64}

@pytest.mark.parametrize('url',['https://example.invalid','http://127.0.0.1:55421','http://gateway:8000','https://prod.invalid','file:///tmp/test'])
def test_unknown_target_rejected_before_network(url):
    b=bootstrap();b['api_url']=url
    with pytest.raises(WorkerError,match='TARGET_REJECTED'):LocalWorkerClient(b)

@pytest.mark.parametrize('claims',[{'role':'service_role'},{'role':'authenticated'},{'sub':'22222222-2222-4222-8222-222222222222'},{'iss':'https://unknown.invalid/auth/v1'},{'exp':True}])
def test_worker_identity_metadata_must_match_expected(claims):
    with pytest.raises(WorkerError,match='IDENTITY_REJECTED'):LocalWorkerClient(bootstrap(**claims))

def test_transport_only_accepts_two_worker_rpcs():
    client=LocalWorkerClient(bootstrap())
    with pytest.raises(WorkerError,match='RPC_REJECTED'):client.call('gis_command',{})

def ready():
    return {'status':'ready','worker_role':'gis_native_worker','subject':SUB,'database_name':'postgres','cluster_name':'green-area-gis-t0',
            'contract_version':'1.3.0-t3-remediation','migration_versions':list(range(27,34)),'runtime_instance':'a'*32,'baseline_fingerprint':'b'*64}

class FakeClient:
    subject=SUB
    expected={'runtime_instance':'a'*32,'baseline_fingerprint':'b'*64}
    def __init__(self,value=None):self.value=ready() if value is None else value;self.calls=[]
    def call(self,name,payload):self.calls.append((name,payload));return self.value if name.endswith('readiness_v2') else {'state':'queued'}

@pytest.mark.parametrize('field,value',[('runtime_instance','c'*32),('baseline_fingerprint','d'*64),('subject','other'),('database_name','unknown'),('cluster_name','unknown'),('worker_role','service_role'),('migration_versions',[27,28,29,30,31,32]),('status','unknown')])
def test_target_readiness_failure_prevents_mutation(field,value):
    r=ready();r[field]=value;c=FakeClient(r)
    with pytest.raises(WorkerError,match='TARGET_REJECTED'):GisWorker(c).call('claim')
    assert [name for name,_ in c.calls]==['gis_worker_readiness_v2']

def job():return {'id':SUB,'lease_token':SUB,'manifest':{'fixture_id':'t3-ldd-valid-v2'},'input_hash':'a'*64,'input_revision':1,'attempt_number':1}

def test_lease_loss_prevents_result_commit(monkeypatch):
    c=FakeClient();w=GisWorker(c)
    def child(_):w._lease_lost.set();return {'valid':True,'error_code':None}
    monkeypatch.setattr(w,'_execute_native',child)
    with pytest.raises(WorkerError,match='GIS_STALE_LEASE'):w.process_job(job())
    assert not c.calls

@pytest.mark.parametrize('code',['NATIVE_TIMEOUT','NATIVE_MEMORY_LIMIT','WORKER_SHUTDOWN','TRANSIENT_SYNTHETIC','NATIVE_OUTPUT_LIMIT'])
def test_infrastructure_failure_is_transient(monkeypatch,code):
    c=FakeClient();w=GisWorker(c);monkeypatch.setattr(w,'_execute_native',lambda _:{'valid':False,'error_code':code})
    w.process_job(job())
    mutation=c.calls[-1][1]
    assert mutation['p_action']=='fail' and mutation['p_payload']['error_code']=='transient'

def test_stopped_worker_does_not_claim():
    c=FakeClient();w=GisWorker(c);w.stop();w.run()
    assert [name for name,_ in c.calls]==['gis_worker_readiness_v2']
