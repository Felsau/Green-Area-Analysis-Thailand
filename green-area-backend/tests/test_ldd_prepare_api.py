"""Mock Auth/RPC tests; byte integrity tested separately and in Local E2E."""
from copy import deepcopy
from uuid import uuid4
from unittest.mock import Mock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from gis_app import create_app

ID='11111111-1111-4111-8111-111111111111'
ACTOR='22222222-2222-4222-8222-222222222222'
JOB='33333333-3333-4333-8333-333333333333'
CERT='44444444-4444-4444-8444-444444444444'


class Runtime:
    sandbox_activation_enabled=False
    def __init__(self):
        self.calls=[];self.allowed=True
        self.info={'status':'succeeded','job':{'id':JOB,'state':'succeeded','progress':100},'attempts':[],
            'candidate':{'valid':True,'artifacts':{}},'prepare_request':{},'certificate':{'id':CERT},'ready_for_publication':True,
            'preview_only':True,'complete_province_inventory':False}
    def require_ready(self):return {'migration_versions':list(range(27,39))}
    def verify_user_token(self, token):
        if token!='mock':raise HTTPException(401)
        return ACTOR
    def rpc(self,name,params):
        self.calls.append((name,params))
        if name=='gis_read':return {'capabilities':['enqueue_validation'] if self.allowed else []}
        if name=='gis_ldd_prepare_read':return deepcopy(self.info)
        if name=='gis_ldd_prepare_command':return {'status':202,'body':{'id':JOB,'state':'queued'}}
        if name=='gis_ldd_verify_complete':return {'certificate_id':CERT,'ready_for_publication':True}
        if name=='gis_ldd_verify_revoke':return None
        raise AssertionError(name)


@pytest.fixture
def api():
    runtime=Runtime();store=Mock();store._usage.return_value=0
    store.certify_files.return_value={'valid':True,'verifier_version':'ldd-trusted-bytes-v1'}
    store.read_files.return_value={'ldd_geometry':{'type':'FeatureCollection','features':[]},
        'ldd_summary':{'feature_count':3,'total_area_m2':6400,'area_by_code_m2':{'U101':6400},'metadata':{}}}
    with TestClient(create_app(runtime,prepared_store=store,rate_limit='10000/minute')) as client:
        client.headers['Authorization']='Bearer mock'
        yield client,runtime,store


def body():return {'expected_dataset_revision':1,'expected_input_revision':1,'input_hash':'a'*64,'province':'Bangkok Metropolis','data_year':2026}
def key():return {'Idempotency-Key':str(uuid4())}


def test_actor_from_auth_and_no_backend_activation(api):
    client,runtime,_=api
    reply=client.post(f'/gis/editions/{ID}/prepare-jobs',json=body(),headers=key())
    assert reply.status_code==202
    name,params=runtime.calls[-1]
    assert name=='gis_ldd_prepare_command' and params['p_actor']==ACTOR
    assert params['p_payload']['edition_id']==ID and 'ready' not in params['p_payload']


@pytest.mark.parametrize('extra',[{'actor':ACTOR},{'path':'/tmp/x'},{'url':'https://example.invalid'},
    {'ready':True},{'method_version':'arbitrary'},{'proof':{'valid':True}}])
def test_enqueue_rejects_authority_and_arbitrary_paths(api,extra):
    client,_,store=api
    reply=client.post(f'/gis/editions/{ID}/prepare-jobs',json={**body(),**extra},headers=key())
    assert reply.status_code==422 and store.certify_files.call_count==0


@pytest.mark.parametrize('extra',[{'ready':True},{'proof':{}},{'path':'/tmp/x'},{'certificate_id':CERT}])
def test_verify_accepts_job_id_only_never_a_client_proof(api,extra):
    client,_,store=api
    assert client.post(f'/gis/editions/{ID}/prepare-verification',json={'job_id':JOB,**extra},headers=key()).status_code==422
    store.certify_files.assert_not_called()


def test_all_mutations_need_idempotency_header(api):
    client,_,store=api
    assert client.post(f'/gis/editions/{ID}/prepare-jobs',json=body()).status_code==422
    assert client.post(f'/gis/editions/{ID}/prepare-verification',json={'job_id':JOB}).status_code==422
    store.certify_files.assert_not_called()


def test_normal_user_denied_before_file_access(api):
    client,runtime,store=api;runtime.allowed=False
    assert client.get(f'/gis/editions/{ID}/prepared').status_code==403
    assert client.post(f'/gis/editions/{ID}/prepare-jobs',json=body(),headers=key()).status_code==403
    store.attest.assert_not_called();store.read_files.assert_not_called()


def test_preview_reopens_actual_files_each_request(api):
    client,_,store=api
    for _ in range(2):
        data=client.get(f'/gis/editions/{ID}/prepared').json()
        assert data['ready_for_publication'] and data['preview_only']
        assert data['summary']['total_area_m2']==6400 and 'prepare_request' not in data
    assert store.read_files.call_count==2


@pytest.mark.parametrize('failure',[FileNotFoundError(),ValueError('corrupt')])
def test_missing_corrupt_object_revokes_and_never_returns_geometry(api,failure):
    client,runtime,store=api;store.read_files.side_effect=failure
    data=client.get(f'/gis/editions/{ID}/prepared').json()
    assert data['ready_for_publication'] is False and 'geometry' not in data and 'summary' not in data
    assert runtime.calls[-1]==('gis_ldd_verify_revoke',{'p_actor':ACTOR,'p_certificate':CERT,'p_reason':'artifact_corrupt'})


def test_only_private_trusted_verifier_constructs_certificate_proof(api):
    client,runtime,store=api
    reply=client.post(f'/gis/editions/{ID}/prepare-verification',json={'job_id':JOB},headers=key())
    assert reply.status_code==200 and store.certify_files.call_count==1
    cert=[params for name,params in runtime.calls if name=='gis_ldd_verify_complete'][0]
    assert cert['p_actor']==ACTOR and cert['p_proof']==store.certify_files.return_value


def test_worker_candidate_alone_is_not_ready(api):
    client,runtime,store=api;runtime.info['certificate']=None;runtime.info['ready_for_publication']=False
    value=client.get(f'/gis/editions/{ID}/prepared').json()
    assert value['prepared'] and value['ready_for_publication'] is False
    store.read_files.assert_not_called()


def test_enqueue_over_soft_quota_fails_before_queue_mutation(api):
    client,runtime,store=api;store._usage.return_value=256*1024**2
    response=client.post(f'/gis/editions/{ID}/prepare-jobs',json=body(),headers=key())
    assert response.status_code==507
    assert not any(name=='gis_ldd_prepare_command' for name,_ in runtime.calls)


def test_certification_capacity_failure_cannot_create_certificate(api):
    client,runtime,store=api
    store.certify_files.side_effect=HTTPException(507,detail={'code':'GIS_PREPARE_STORAGE_LIMIT'})
    response=client.post(f'/gis/editions/{ID}/prepare-verification',json={'job_id':JOB},headers=key())
    assert response.status_code==507
    assert not any(name=='gis_ldd_verify_complete' for name,_ in runtime.calls)
