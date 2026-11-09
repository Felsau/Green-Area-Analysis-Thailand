"""A3 HTTP trust-boundary tests; actual SQL/files exercised by Local checks."""
from contextlib import nullcontext
from unittest.mock import Mock
from uuid import uuid4
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from gis_app import create_app
from gis_ldd_publication import LocalLddPublication

ID='11111111-1111-4111-8111-111111111111';ACTOR='22222222-2222-4222-8222-222222222222'
CERT='33333333-3333-4333-8333-333333333333'
def body():return {'edition_id':ID,'expected_dataset_revision':1,'expected_active_edition_id':None,'expected_input_revision':1,
 'input_hash':'a'*64,'validation_result_id':ID,'source_sha256':'b'*64,'province':'Bangkok Metropolis','data_year':2026,
 'method_version':'ldd-source-area-v1','coverage_mode':'validated_source_footprint','reason':'A3 Local test'}

class Runtime:
    sandbox_activation_enabled=False;ldd_publication_enabled=True
    def __init__(self):self.admin=True;self.replay=False;self.calls=[];self.prepared={'candidate':{'valid':True}}
    def require_ready(self):return {'migration_versions':list(range(27,40))}
    def verify_user_token(self,token):
        if token!='mock':raise HTTPException(401)
        return ACTOR
    def rpc(self,name,params):
        self.calls.append((name,params))
        if name=='gis_read':return {'admin':self.admin,'capabilities':['read_catalog']}
        if name=='gis_ldd_prepare_read':return self.prepared
        if name=='gis_ldd_publication_command':return {'status':200,'body':{'receipt_exists':self.replay or not params['p_probe'],'replayed':self.replay}}
        raise AssertionError(name)

@pytest.fixture
def api():
    runtime=Runtime();provider=Mock();provider.store._lock=Mock(side_effect=lambda:nullcontext())
    provider.fresh_proof.return_value={'certificate_id':CERT,'report':{'valid':True}}
    provider.bundle.return_value={'snapshot_id':'c'*64,'geometry':{},'summary':{}}
    app=create_app(runtime,rate_limit='10000/minute');app.state.gis_ldd_publication=provider
    with TestClient(app) as client:
        client.headers['Authorization']='Bearer mock';yield client,runtime,provider

@pytest.mark.parametrize('operation',['activation','rollback','withdrawal'])
def test_admin_only_before_native_access(api,operation):
    client,runtime,provider=api;runtime.admin=False
    value={**body(),**({'replacement_edition_id':None} if operation=='withdrawal' else {})}
    assert client.post(f'/gis/datasets/{ID}/ldd-publication/{operation}',json=value,headers={'Idempotency-Key':str(uuid4())}).status_code==403
    provider.attest.assert_not_called();provider.fresh_proof.assert_not_called()

@pytest.mark.parametrize('extra',[{'proof':{}},{'ready':True},{'actor':ACTOR},{'path':'/tmp/file'},{'backend_local':True}])
def test_client_cannot_supply_authority(api,extra):
    client,_,provider=api
    assert client.post(f'/gis/datasets/{ID}/ldd-publication/activation',json={**body(),**extra},headers={'Idempotency-Key':str(uuid4())}).status_code==422
    provider.fresh_proof.assert_not_called()

def test_activation_requires_fresh_private_proof(api):
    client,runtime,provider=api
    response=client.post(f'/gis/datasets/{ID}/ldd-publication/activation',json=body(),headers={'Idempotency-Key':str(uuid4())})
    assert response.status_code==200 and response.headers['cache-control']=='no-store'
    calls=[p for n,p in runtime.calls if n=='gis_ldd_publication_command']
    assert calls[0]['p_probe'] is True and calls[0]['p_proof'] is None
    assert calls[1]['p_probe'] is False and calls[1]['p_proof']==provider.fresh_proof.return_value
    assert calls[1]['p_actor']==ACTOR and calls[1]['p_backend_local'] is True

def test_failed_verification_does_not_commit_pointer(api):
    client,runtime,provider=api;provider.fresh_proof.side_effect=ValueError('corrupt bytes')
    assert client.post(f'/gis/datasets/{ID}/ldd-publication/activation',json=body(),headers={'Idempotency-Key':str(uuid4())}).status_code==409
    assert all(p['p_probe'] for n,p in runtime.calls if n=='gis_ldd_publication_command')

def test_history_replay_never_republishes(api):
    client,runtime,provider=api;runtime.replay=True
    assert client.post(f'/gis/datasets/{ID}/ldd-publication/activation',json=body(),headers={'Idempotency-Key':str(uuid4())}).json()['replayed']
    provider.fresh_proof.assert_not_called();provider.store._lock.assert_not_called()

def test_null_withdrawal_works_without_current_files(api):
    client,runtime,provider=api
    assert client.post(f'/gis/datasets/{ID}/ldd-publication/withdrawal',json={**body(),'replacement_edition_id':None},headers={'Idempotency-Key':str(uuid4())}).status_code==200
    provider.fresh_proof.assert_not_called()
    assert [p for n,p in runtime.calls if n=='gis_ldd_publication_command'][-1]['p_proof'] is None

def test_normal_signed_in_can_read_without_catalog_admin(api):
    client,runtime,provider=api;runtime.admin=False
    result=client.get('/gis/published-ldd',params={'province':'Bangkok Metropolis','data_year':2026})
    assert result.status_code==200 and result.headers['cache-control']=='no-store'
    assert runtime.calls==[]
    provider.bundle.assert_called_once()

@pytest.mark.parametrize('query',[{'province':'Bangkok Metropolis','data_year':2026,'district':'test'},
 {'province':'Bangkok Metropolis','data_year':2026,'edition_id':ID},{'province':'Bangkok Metropolis','data_year':1979}])
def test_read_scope_closed(api,query):
    client,_,provider=api
    assert client.get('/gis/published-ldd',params=query).status_code==422
    provider.bundle.assert_not_called()

@pytest.mark.parametrize('sent',['ldd-source-area-v1','ldd-geometry-area-v2'])
def test_the_method_sent_to_sql_is_the_editions_own(api,sent):
    client,runtime,_=api
    runtime.prepared={'candidate':{'valid':True},'prepare_request':{'method_version':'ldd-geometry-area-v2'}}
    assert client.post(f'/gis/datasets/{ID}/ldd-publication/activation',json={**body(),'method_version':sent},
        headers={'Idempotency-Key':str(uuid4())}).status_code==200
    sent_to_sql={p['p_payload']['method_version'] for n,p in runtime.calls if n=='gis_ldd_publication_command'}
    assert sent_to_sql=={'ldd-geometry-area-v2'}

def test_without_a_preparation_the_clients_method_is_kept_and_sql_decides(api):
    client,runtime,_=api
    client.post(f'/gis/datasets/{ID}/ldd-publication/activation',json=body(),headers={'Idempotency-Key':str(uuid4())})
    assert {p['p_payload']['method_version'] for n,p in runtime.calls if n=='gis_ldd_publication_command'}=={'ldd-source-area-v1'}

def test_unknown_method_is_refused_before_native_access(api):
    client,_,provider=api
    assert client.post(f'/gis/datasets/{ID}/ldd-publication/activation',json={**body(),'method_version':'ldd-other-v9'},
        headers={'Idempotency-Key':str(uuid4())}).status_code==422
    provider.fresh_proof.assert_not_called()

def test_geometry_is_read_per_snapshot_and_sent_compressed(api):
    client,runtime,provider=api;runtime.admin=False
    provider.geometry.return_value=({'type':'FeatureCollection','features':[{'type':'Feature','properties':{'LU_CODE':'U101'},'geometry':None}]},'d'*64)
    query={'province':'Bangkok Metropolis','data_year':2026,'snapshot_id':'c'*64}
    result=client.get('/gis/published-ldd/geometry',params=query,headers={'Accept-Encoding':'gzip'})
    assert result.status_code==200 and result.headers['content-encoding']=='gzip' and result.headers['cache-control']=='no-store'
    assert result.headers['x-artifact-sha256']=='d'*64 and result.json()['features'][0]['properties']['LU_CODE']=='U101'
    provider.geometry.assert_called_once()
    assert provider.geometry.call_args.args[2:]==('Bangkok Metropolis',2026,'c'*64)
    plain=client.get('/gis/published-ldd/geometry',params=query,headers={'Accept-Encoding':'identity'})
    assert plain.status_code==200 and 'content-encoding' not in plain.headers

@pytest.mark.parametrize('query',[{'province':'Bangkok Metropolis','data_year':2026},
 {'province':'Bangkok Metropolis','data_year':2026,'snapshot_id':'C'*64},{'province':'Bangkok Metropolis','data_year':2026,'snapshot_id':'c'*63},
 {'province':'Bangkok Metropolis','data_year':2026,'snapshot_id':'c'*64,'edition_id':ID}])
def test_geometry_scope_closed(api,query):
    client,_,provider=api
    assert client.get('/gis/published-ldd/geometry',params=query).status_code==422
    provider.geometry.assert_not_called()

def packet():
    identity={'namespace':'published','scope':'province','product':'landuse','province':'Bangkok Metropolis',
        'data_year':2026,'month':0,'method_version':'ldd-source-area-v1','dataset_id':ID,'edition_id':ID,
        'validation_result_id':ID,'input_hash':'a'*64,'source_sha256':'b'*64}
    metadata={k:v for k,v in identity.items() if k not in ('namespace','scope','product')}
    metadata.update(input_revision=1,complete_province_inventory=False)
    info={'source_identity':identity,'snapshot_id':'c'*64,'dataset':{'revision':1},'certificate_id':CERT,
        'prepare_request':{},'candidate':{'artifacts':{'ldd_geometry':{'sha256':'d'*64},'ldd_summary':{'sha256':'e'*64}}}}
    files={'ldd_geometry':{'type':'FeatureCollection','metadata':metadata,'features':[]},'ldd_summary':{'metadata':metadata,'feature_count':0,'area_by_code_m2':{},'total_area_m2':0}}
    return info,files

def provider_fixture():
    runtime=Mock();runtime.ldd_publication_enabled=True;runtime.sandbox_activation_enabled=False
    runtime.require_ready.return_value={'migration_versions':[39]}
    store=Mock();store.runtime=runtime;info,files=packet();store.read_files.return_value=files
    service=Mock();service._rpc.return_value=info
    return LocalLddPublication(runtime,store,Mock()),store,service,info,files

def test_cached_summary_still_rechecks_bytes_and_current_snapshot():
    provider,store,service,info,_=provider_fixture()
    for _ in range(2):assert provider.bundle(service,ACTOR,'Bangkok Metropolis',2026)['snapshot_id']==info['snapshot_id']
    assert store.read_files.call_count==2
    assert len([call for call in service._rpc.call_args_list if call.args[1].get('p_expected')==info['snapshot_id']])==2

def test_pointer_change_during_read_returns_no_mixed_bundle():
    provider,_,service,info,_=provider_fixture();service._rpc.side_effect=[info,HTTPException(409)]
    with pytest.raises(HTTPException):provider.bundle(service,ACTOR,'Bangkok Metropolis',2026)

def test_polled_bundle_carries_a_geometry_descriptor_not_the_geometry():
    provider,_,service,info,_=provider_fixture()
    bundle=provider.bundle(service,ACTOR,'Bangkok Metropolis',2026)
    assert 'geometry' not in bundle and bundle['geometry_artifact']['sha256']=='d'*64

def test_geometry_is_only_served_for_the_current_snapshot():
    provider,store,service,info,files=provider_fixture()
    geometry,sha=provider.geometry(service,ACTOR,'Bangkok Metropolis',2026,info['snapshot_id'])
    assert geometry==files['ldd_geometry'] and sha=='d'*64 and store.read_files.call_count==1
    assert service._rpc.call_args.args[1]['p_expected']==info['snapshot_id']      # still current after the read
    with pytest.raises(HTTPException) as error:provider.geometry(service,ACTOR,'Bangkok Metropolis',2026,'f'*64)
    assert error.value.status_code==409

def test_geometry_that_does_not_match_the_parcel_count_is_not_admitted():
    _,_,_,_,files=provider_fixture()
    with pytest.raises(HTTPException) as error:
        LocalLddPublication.display_geometry({**files,'ldd_summary':{**files['ldd_summary'],'feature_count':1}})
    assert error.value.status_code==413

@pytest.mark.parametrize('failure',[FileNotFoundError(),ValueError('hash')])
def test_unavailable_files_fail_closed_even_after_cached_read(failure):
    provider,store,service,_,_=provider_fixture();provider.bundle(service,ACTOR,'Bangkok Metropolis',2026)
    store.read_files.side_effect=failure
    with pytest.raises(HTTPException) as error:provider.bundle(service,ACTOR,'Bangkok Metropolis',2026)
    assert error.value.status_code==409
    assert service._rpc.call_args[0][0]=='gis_ldd_published_unavailable'
