"""HTTP contract checks with mock Auth/RPC; not real JWT or database evidence."""
from uuid import uuid4
from fastapi.testclient import TestClient
import pytest
from gis_app import create_app
from gis_service import gis_error

ACTOR = '11111111-1111-4111-8111-111111111111'
JOB = '22222222-2222-4222-8222-222222222222'

class Runtime:
    sandbox_activation_enabled = False
    def __init__(self):
        self.calls = []
    def require_ready(self):
        return {'migration_versions': list(range(27,36))}
    def verify_user_token(self, token):
        if token != 'unit-user-token': raise gis_error(401, 'GIS_UNAUTHENTICATED', 'unit')
        return ACTOR
    def rpc(self, name, payload):
        self.calls.append((name,payload))
        if name == 'gis_processing_command':
            return {'status':202, 'body':{'id':JOB, 'mode':'offline_synthetic','state':'queued'}}
        return {'data':[], 'next_cursor':None, 'has_more':False, 'live_enabled':False}

@pytest.fixture
def api():
    runtime = Runtime()
    with TestClient(create_app(runtime, rate_limit='10000/minute')) as client:
        client.headers.update({'Authorization':'Bearer unit-user-token', 'Idempotency-Key':str(uuid4())})
        yield client,runtime

def body(**change):
    return {'province':'Bangkok Metropolis','district':None,'metric':'ndvi','data_year':2025,
        'month':0,'mode':'offline_synthetic','scenario':'standard','expected_revision':1,**change}

def test_processing_actor_and_rpc_boundary(api):
    client,runtime = api
    assert client.post('/gis/processing-jobs',json=body()).status_code == 202
    name,payload = runtime.calls[-1]
    assert name == 'gis_processing_command' and payload['p_actor'] == ACTOR
    assert payload['p_backend_sandbox'] is False and payload['p_payload'] == body()

@pytest.mark.parametrize('field,value', [('mode','gee_live'),('metric','unknown'),('data_year',2016),
    ('data_year',True),('data_year','2025'),('month',True),('month',13),('expected_revision',True),
    ('expected_revision',2),('scenario','command'),('actor_id',ACTOR),('url','https://example.invalid'),('path','/tmp/x')])
def test_invalid_processing_parameters_rejected_before_rpc(api,field,value):
    client,runtime=api
    assert client.post('/gis/processing-jobs',json=body(**{field:value})).status_code==422
    assert not runtime.calls

def test_missing_auth_and_idempotency_denied(api):
    client,runtime=api
    client.headers.pop('Authorization')
    assert client.post('/gis/processing-jobs',json=body()).status_code==401
    assert not runtime.calls

@pytest.mark.parametrize('suffix,kind', [('', 'job'),('/attempts','attempts'),('/result','result'),('/history','history')])
def test_processing_reads_stay_on_private_rpc(api,suffix,kind):
    client,runtime=api
    assert client.get('/gis/processing-jobs/'+JOB+suffix).status_code==200
    name,payload=runtime.calls[-1]
    assert name=='gis_processing_read' and payload['p_kind']==kind and payload['p_actor']==ACTOR

def test_options_reject_arbitrary_target(api):
    client,runtime=api
    assert client.get('/gis/processing-options?province=Bangkok%20Metropolis').status_code==200
    assert client.get('/gis/processing-options?project=external').status_code==422

def test_retry_frozen_hash_revision_and_reason(api):
    client,runtime=api
    request={'expected_revision':1,'input_hash':'a'*64,'reason':'test retry'}
    assert client.post('/gis/processing-jobs/'+JOB+'/retry',json=request).status_code==202
    assert runtime.calls[-1][1]['p_payload']=={'job_id':JOB,**request}
