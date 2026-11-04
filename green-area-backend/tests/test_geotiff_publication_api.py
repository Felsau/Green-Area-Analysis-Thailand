from unittest.mock import Mock
from contextlib import nullcontext
from types import SimpleNamespace
from uuid import uuid4
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from gis_app import create_app

ID='11111111-1111-4111-8111-111111111111';ACTOR='22222222-2222-4222-8222-222222222222'
def body():return {'edition_id':ID,'expected_dataset_revision':1,'expected_active_edition_id':None,'expected_input_revision':1,'input_hash':'a'*64,
    'validation_result_id':ID,'certificate_id':ID,'source_sha256':'b'*64,'province':'Bangkok Metropolis','data_year':2026,'month':0,'product':'ndvi','profile':'ndvi_ready',
    'method_version':'geotiff-grid-celsius-v1','coverage_mode':'source_footprint_intersection','policy_version':'local-declared-period-footprint-v1',
    'acknowledge_unverified_period':True,'acknowledge_limited_coverage':True,'reason':'Local explicit acceptance'}
class Runtime:
    sandbox_activation_enabled=False
    def __init__(self):self.admin=True;self.calls=[];self.replayed=False
    def require_ready(self):return {'migration_versions':list(range(27,43))}
    def verify_user_token(self,token):
        if token!='mock':raise HTTPException(401)
        return ACTOR
    def rpc(self,name,params):
        self.calls.append((name,params))
        if name=='gis_read':return {'admin':self.admin,'capabilities':[]}
        if name=='gis_geotiff_publication_command':return {'status':200,'body':{'receipt_exists':self.replayed if params['p_probe'] else True}}
        if name in ('gis_geotiff_publication_status','gis_geotiff_prepare_read'):return {'catalog_prepared':True,'identity':{'certificate_id':ID}}
        raise AssertionError(name)
@pytest.fixture
def api():
    rt=Runtime();provider=Mock();provider.store=SimpleNamespace(_lock=nullcontext);provider.fresh_proof.return_value={'private_native_proof':True};provider.bundle.return_value={'snapshot_id':'c'*64,'local_only':True}
    app=create_app(rt,rate_limit='10000/minute');app.state.gis_geotiff_publication=provider
    with TestClient(app) as c:c.headers['Authorization']='Bearer mock';yield c,rt,provider

@pytest.mark.parametrize('operation',['activation','rollback','withdrawal'])
def test_admin_proof_private_actor_cas_and_store_lock(api,operation):
    c,rt,p=api
    b=body()|({'replacement_edition_id':None} if operation=='withdrawal' else {})
    assert c.post('/gis/datasets/'+ID+'/geotiff-publication/'+operation,json=b,headers={'Idempotency-Key':str(uuid4())}).status_code==200
    args=next(a for n,a in reversed(rt.calls) if n=='gis_geotiff_publication_command')
    assert args['p_actor']==ACTOR and args['p_payload']['month']==0
    assert args['p_proof']==(None if operation=='withdrawal' else p.fresh_proof.return_value)

@pytest.mark.parametrize('field,value',[('proof',{}),('actor',ID),('url','https://invalid.test'),('acknowledge_unverified_period',False),('acknowledge_limited_coverage',False),('product','landuse'),('profile','raw_dn')])
def test_closed_policy_and_payload(api,field,value):
    c,_,p=api
    assert c.post('/gis/datasets/'+ID+'/geotiff-publication/activation',json=body()|{field:value},headers={'Idempotency-Key':str(uuid4())}).status_code==422
    p.fresh_proof.assert_not_called()

def test_nonadmin_cannot_mutate(api):
    c,rt,p=api;rt.admin=False
    assert c.post('/gis/datasets/'+ID+'/geotiff-publication/activation',json=body(),headers={'Idempotency-Key':str(uuid4())}).status_code==403
    p.attest.assert_not_called()

def test_receipt_replay_never_reverifies_or_mutates_pointer(api):
    c,rt,p=api;rt.replayed=True
    assert c.post('/gis/datasets/'+ID+'/geotiff-publication/activation',json=body(),headers={'Idempotency-Key':str(uuid4())}).status_code==200
    p.fresh_proof.assert_not_called();assert len([1 for n,a in rt.calls if n=='gis_geotiff_publication_command'])==1

def test_signed_in_normal_reader_explicit_scope(api):
    c,rt,p=api;rt.admin=False
    q={'province':'Bangkok Metropolis','data_year':2026,'month':0,'product':'ndvi','coverage_mode':'source_footprint_intersection'}
    assert c.get('/gis/published-geotiff',params=q).status_code==200
    p.bundle.assert_called_once_with(__import__('unittest').mock.ANY,ACTOR,'Bangkok Metropolis',2026,0,'ndvi')
    assert c.get('/gis/published-geotiff',params=q|{'district':'district'}).status_code==422
    assert c.get('/gis/published-geotiff',params={k:v for k,v in q.items() if k!='coverage_mode'}).status_code==422
    c.headers.pop('Authorization');assert c.get('/gis/published-geotiff',params=q).status_code==401

def test_byte_failure_never_calls_commit(api):
    c,rt,p=api;p.fresh_proof.side_effect=ValueError('bytes')
    assert c.post('/gis/datasets/'+ID+'/geotiff-publication/activation',json=body(),headers={'Idempotency-Key':str(uuid4())}).status_code==409
    assert not any(n=='gis_geotiff_publication_command' and not a['p_probe'] for n,a in rt.calls)

@pytest.mark.parametrize('failure',[RuntimeError('container limit'),TimeoutError('native timeout'),{'valid':False,'error_code':'PUBLICATION_BYTE_VERIFICATION_FAILED'}])
def test_temporary_verifier_failure_never_revokes_active(failure):
    from gis_geotiff_publication import LocalGeoTiffPublication
    p=object.__new__(LocalGeoTiffPublication);p.attest=lambda:None
    p.store=SimpleNamespace(read_files=lambda *a:{'summary':{}})
    def verifier(packet):
        if isinstance(failure,Exception):raise failure
        return failure
    p.verifier=verifier
    service=Mock();service._rpc.return_value={'prepare_request':{},'candidate':{'artifacts':{}}}
    with pytest.raises(HTTPException) as e:p.bundle(service,ACTOR,'Bangkok Metropolis',2026,0,'ndvi')
    assert e.value.status_code==503
    assert [x.args[0] for x in service._rpc.call_args_list]==['gis_geotiff_published_read']

def test_established_artifact_corruption_revokes_and_never_returns_cached_raster():
    from gis_geotiff_publication import LocalGeoTiffPublication
    p=object.__new__(LocalGeoTiffPublication);p.attest=lambda:None
    p.store=Mock();p.store.read_files.side_effect=ValueError('source SHA mismatch')
    service=Mock();service._rpc.return_value={'prepare_request':{},'candidate':{'artifacts':{}},'snapshot_id':'a'*64,'certificate_id':ID}
    with pytest.raises(HTTPException) as e:p.bundle(service,ACTOR,'Bangkok Metropolis',2026,0,'ndvi')
    assert e.value.status_code==409
    assert [x.args[0] for x in service._rpc.call_args_list]==['gis_geotiff_published_read','gis_geotiff_published_unavailable']
