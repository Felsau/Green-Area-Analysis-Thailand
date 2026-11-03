"""A4.1 HTTP authority boundary; SQL/native integration uses actual Local tests."""
from copy import deepcopy
from unittest.mock import Mock
from uuid import uuid4
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from gis_app import create_app

ID='11111111-1111-4111-8111-111111111111'
ACTOR='22222222-2222-4222-8222-222222222222'
def body():return {'expected_dataset_revision':1,'expected_input_revision':1,'input_hash':'a'*64,'province':'Bangkok Metropolis','data_year':2026,'month':0,'validation_result_id':ID}
class Runtime:
    sandbox_activation_enabled=False
    def __init__(self):
        self.officer=True;self.calls=[]
        self.info={'status':'succeeded','job':{'id':ID,'progress':100},'attempts':[{}],'candidate':{'valid':True,'artifacts':{}},'certificate':{'id':ID},'ready_for_review':True,'validation_result_id':ID,'prepare_request':{}}
    def require_ready(self):return {'migration_versions':list(range(27,42))}
    def verify_user_token(self,token):
        if token!='mock':raise HTTPException(401)
        return ACTOR
    def rpc(self,name,params):
        self.calls.append((name,params))
        if name=='gis_read':return {'admin':False,'capabilities':['enqueue_validation'] if self.officer else []}
        if name=='gis_geotiff_prepare_read':return deepcopy(self.info)
        if name=='gis_geotiff_prepare_command':return {'status':202,'body':{'id':ID}}
        if name in ('gis_geotiff_verify_complete','gis_geotiff_verify_revoke'):return {'certificate_id':ID}
        raise AssertionError(name)
@pytest.fixture
def api():
    runtime=Runtime();store=Mock();store._usage.return_value=0
    store.certify_files.return_value={'valid':True,'verifier_version':'geotiff-trusted-bytes-v1'}
    store.read_files.return_value={'summary':{'metadata':{'period_verified':False},'statistics':{'mean':0}}}
    app=create_app(runtime,rate_limit='10000/minute');app.state.gis_geotiff_prepared_store=store
    with TestClient(app) as client:
        client.headers['Authorization']='Bearer mock';yield client,runtime,store

@pytest.mark.parametrize('route,method,payload',[('geotiff-prepare-jobs','post',body()),('geotiff-prepare-retry','post',{**body(),'job_id':ID,'reason':'retry'}),('geotiff-prepare-verification','post',{'job_id':ID}),('geotiff-prepared','get',None)])
def test_normal_cannot_prepare_verify_or_preview(api,route,method,payload):
    client,runtime,store=api;runtime.officer=False
    r=client.request(method,'/gis/editions/'+ID+'/'+route,json=payload,headers={'Idempotency-Key':str(uuid4())})
    assert r.status_code==403;store.attest.assert_not_called()
def test_anonymous_denied(api):
    client,_,store=api;client.headers.pop('Authorization')
    assert client.get('/gis/editions/'+ID+'/geotiff-prepared').status_code==401
    store.attest.assert_not_called()
@pytest.mark.parametrize('field',['actor','path','proof','ready_for_review','command','url'])
def test_http_payload_cannot_supply_authority(api,field):
    client,_,store=api
    assert client.post('/gis/editions/'+ID+'/geotiff-prepare-jobs',json={**body(),field:'untrusted'},headers={'Idempotency-Key':str(uuid4())}).status_code==422
    store.certify_files.assert_not_called()
def test_officer_enqueue_has_server_actor_and_full_cas(api):
    client,runtime,_=api
    assert client.post('/gis/editions/'+ID+'/geotiff-prepare-jobs',json=body(),headers={'Idempotency-Key':str(uuid4())}).status_code==202
    args=next(p for n,p in runtime.calls if n=='gis_geotiff_prepare_command')
    assert args['p_actor']==ACTOR and args['p_payload']['validation_result_id']==ID and args['p_payload']['month']==0
def test_actual_certification_is_private_not_client_proof(api):
    client,runtime,store=api
    r=client.post('/gis/editions/'+ID+'/geotiff-prepare-verification',json={'job_id':ID},headers={'Idempotency-Key':str(uuid4())})
    assert r.status_code==200 and r.json()['ready_for_review'] and r.json()['ready_for_publication'] is False
    args=next(p for n,p in runtime.calls if n=='gis_geotiff_verify_complete')
    assert args['p_proof']==store.certify_files.return_value and args['p_actor']==ACTOR
@pytest.mark.parametrize('problem',[ValueError('hash'),FileNotFoundError()])
def test_corrupt_or_missing_objects_revoked_and_no_stale_preview(api,problem):
    client,runtime,store=api;store.read_files.side_effect=problem
    r=client.get('/gis/editions/'+ID+'/geotiff-prepared')
    assert r.status_code==200 and r.json()['ready_for_review'] is False and 'summary' not in r.json()
    assert r.json()['status']=='verification_revoked' and any(n=='gis_geotiff_verify_revoke' for n,_ in runtime.calls)
def test_failed_native_verification_never_certifies(api):
    client,runtime,store=api;store.certify_files.side_effect=ValueError('bad bytes')
    assert client.post('/gis/editions/'+ID+'/geotiff-prepare-verification',json={'job_id':ID},headers={'Idempotency-Key':str(uuid4())}).status_code==409
    assert not any(n=='gis_geotiff_verify_complete' for n,_ in runtime.calls)
