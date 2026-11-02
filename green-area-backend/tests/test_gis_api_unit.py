"""Mock HTTP contracts only; this suite is not Supabase/JWT E2E evidence."""
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest

from gis_app import create_app
from gis_schemas import SourceManifest
from gis_service import decode_cursor, encode_cursor, map_rpc_error


ACTOR = str(uuid4())


class FakeRuntime:
    sandbox_activation_enabled = False

    def __init__(self):
        self.calls = []
        self.reply = None
        self.failure = None
        self.ready_calls = 0

    def require_ready(self):
        self.ready_calls += 1

    def verify_user_token(self, value):
        if value != "mock-user-token":
            raise HTTPException(401, detail={"code": "GIS_UNAUTHENTICATED"})
        return ACTOR

    def rpc(self, name, parameters):
        self.calls.append((name, parameters))
        if self.failure:
            raise self.failure
        if self.reply is not None:
            return self.reply
        if name == "gis_command":
            return {"status": 202 if parameters['p_operation'] == 'enqueue' else 201,
                "body": {"id": str(uuid4()), "state": "queued"}}
        return {"data": [], "next_cursor": None, "has_more": False}


@pytest.fixture
def api():
    runtime = FakeRuntime()
    with TestClient(create_app(runtime, rate_limit="10000/minute")) as client:
        client.headers['Authorization'] = 'Bearer mock-user-token'
        yield client, runtime


def dataset():
    return {"province": "Bangkok Metropolis", "data_year": 2025, "month": 0,
        "kind": "geotiff", "purpose": "ndvi", "title": "ข้อมูลจำลอง"}


def key():
    return {"Idempotency-Key": str(uuid4())}


def test_actor_is_bound_from_verified_dependency(api):
    client, runtime = api
    response = client.post('/gis/datasets', json=dataset(), headers=key())
    assert response.status_code == 201
    name, params = runtime.calls[-1]
    assert name == 'gis_command' and params['p_actor'] == ACTOR
    assert params['p_backend_sandbox'] is False


@pytest.mark.parametrize('field,value', [('actor_id', str(uuid4())), ('role', 'admin'), ('permission', 'admin')])
def test_body_authority_and_unknown_fields_rejected(api, field, value):
    client, runtime = api
    response = client.post('/gis/datasets', json={**dataset(), field: value}, headers=key())
    assert response.status_code == 422 and runtime.calls == []
    assert 'input' not in str(response.json())


@pytest.mark.parametrize('headers', [{}, {'Idempotency-Key': 'wrong'}, [('Idempotency-Key',str(uuid4())),('Idempotency-Key',str(uuid4()))]])
def test_mutation_requires_single_uuid_idempotency_header(api, headers):
    client, runtime = api
    response = client.post('/gis/datasets', json=dataset(), headers=headers)
    assert response.status_code == 422 and runtime.calls == []


@pytest.mark.parametrize('field,value', [('month',True),('month',13),('data_year','2025'),('data_year',2199),('title','   '),('kind','unknown')])
def test_strict_identity_validation(api, field, value):
    client, runtime = api
    response = client.post('/gis/datasets', json={**dataset(),field:value}, headers=key())
    assert response.status_code == 422 and runtime.calls == []


def test_ldd_must_be_annual(api):
    client, runtime = api
    response = client.post('/gis/datasets', json={**dataset(),'kind':'ldd_shapefile','purpose':'landuse','month':1}, headers=key())
    assert response.status_code == 422 and runtime.calls == []


def test_nullable_pointer_must_be_explicit(api):
    client, runtime = api
    response = client.post(f'/gis/datasets/{uuid4()}/activation',
        json={'edition_id':str(uuid4()),'expected_revision':1,'reason':'sandbox'},headers=key())
    assert response.status_code == 422 and runtime.calls == []


def test_enqueue_is_queued_record_not_fake_success(api):
    client, runtime = api
    response = client.post(f'/gis/editions/{uuid4()}/validation-jobs',json={'expected_revision':1},headers=key())
    assert response.status_code == 202 and response.json()['state']=='queued'
    assert runtime.calls[-1][1]['p_operation']=='enqueue'


def test_sql_receipt_status_is_preserved(api):
    client, runtime = api
    runtime.reply={'status':200,'body':{'state':'failed'}}
    response=client.post(f'/gis/editions/{uuid4()}/validation-jobs',json={'expected_revision':1},headers=key())
    assert response.status_code==200 and response.json()['state']=='failed'


def test_private_tokens_and_actor_fields_never_leave_service(api):
    client, runtime=api
    runtime.reply={'status':201,'body':{'id':'safe','worker_id':'private','lease_token':'private','lease_until':'private','created_by':'private',
        'nested':{'requested_by':'private','access_token':'private','value':'safe'}}}
    response=client.post('/gis/datasets',json=dataset(),headers=key())
    assert response.status_code==201
    assert response.json()=={'id':'safe','nested':{'value':'safe'}}


@pytest.mark.parametrize('path', ['/gis/datasets?limit=0','/gis/datasets?limit=101','/gis/datasets?actor_id=forged',
    '/gis/jobs?state=complete','/gis/datasets?cursor=bad!'])
def test_query_contracts_are_bounded_and_strict(api,path):
    client,runtime=api
    response=client.get(path)
    assert response.status_code==422 and runtime.calls==[]


def test_cursor_roundtrip_and_payload_filters(api):
    client,runtime=api
    cursor={'created_at':datetime.now(timezone.utc).isoformat(),'id':str(uuid4())}
    encoded=encode_cursor(cursor)
    response=client.get('/gis/datasets',params={'limit':5,'province':'Bangkok Metropolis','data_year':2025,'cursor':encoded})
    assert response.status_code==200
    payload=runtime.calls[-1][1]['p_payload']
    assert payload['limit']==5 and payload['province']=='Bangkok Metropolis' and payload['data_year']==2025
    assert decode_cursor(encoded)==payload['cursor']


def test_output_cursor_is_opaque(api):
    client,runtime=api
    runtime.reply={'data':[],'has_more':True,'next_cursor':{'created_at':datetime.now(timezone.utc).isoformat(),'id':str(uuid4())}}
    response=client.get('/gis/datasets')
    assert response.status_code==200 and isinstance(response.json()['next_cursor'],str)


def test_result_route_and_attempt_history(api):
    client,runtime=api
    job=str(uuid4())
    assert client.get(f'/gis/jobs/{job}/result').status_code==200
    assert runtime.calls[-1][1]['p_kind']=='result' and runtime.calls[-1][1]['p_payload']=={'id':job}
    assert client.get(f'/gis/jobs/{job}/attempts').status_code==200
    assert runtime.calls[-1][1]['p_payload']['job_id']==job


@pytest.mark.parametrize('field,value', [('resolution',float('nan')),('nodata',float('inf')),('byte_size',True),('schema_version',True)])
def test_nonfinite_manifest_is_rejected(field,value):
    data={'schema_version':1,'provider':'synthetic','fixture_id':'ndvi-valid-v1','sha256':'a'*64,'byte_size':4,
        'provenance':'fixture','crs':'EPSG:4326','data_kind':'raster','bands':['ndvi'],'units':'unitless','nodata':-9999,'resolution':30}
    data[field]=value
    with pytest.raises(ValueError):
        SourceManifest.model_validate(data)


def test_raw_nonfinite_http_input_returns_safe_422(api):
    client,runtime=api
    response=client.post('/gis/datasets',headers={**key(),'Content-Type':'application/json'},
        content='{"province":"Bangkok Metropolis","data_year":NaN,"month":0,"kind":"geotiff","purpose":"ndvi","title":"x"}')
    assert response.status_code==422 and runtime.calls==[]
    assert 'NaN' not in response.text


def test_default_disabled_does_not_make_any_request():
    with TestClient(create_app()) as client:
        response=client.get('/gis/me')
    assert response.status_code==503


def test_no_admin_header_authentication_bypass(api):
    client,runtime=api
    client.headers.pop('Authorization')
    response=client.post('/gis/datasets',json=dataset(),headers={**key(),'X-Admin-Token':'not-used'})
    assert response.status_code==401 and runtime.calls==[]


def test_duplicate_authorization_is_rejected(api):
    client,runtime=api
    client.headers.pop('Authorization')
    response=client.get('/gis/me',headers=[('Authorization','Bearer mock-user-token'),('Authorization','Bearer other')])
    assert response.status_code==401 and runtime.calls==[]


def test_capabilities_report_both_sandbox_gates(api):
    client,runtime=api
    runtime.reply={'activation_enabled':True,'admin':True,'capabilities':['sandbox_activate']}
    result=client.get('/gis/me').json()
    assert result['database_activation_enabled'] is True
    assert result['backend_activation_enabled'] is False and result['activation_enabled'] is False
    runtime.sandbox_activation_enabled=True
    assert client.get('/gis/me').json()['activation_enabled'] is True


@pytest.mark.parametrize('code,message,status', [
    ('42501','GIS_FORBIDDEN',403),('P0001','GIS_NOT_FOUND',404),('P0001','GIS_REVISION_CONFLICT',409),
    ('P0001','GIS_IDEMPOTENCY_CONFLICT',409),('P0001','GIS_ACTIVATION_DISABLED',503),
    ('P0001','GIS_SYNTHETIC_ONLY',422),('23505','private row details',409),('23503','private row details',422),
    ('429','raw gateway response',429),('PGRST202','secret query token=not-real',503)])
def test_rpc_errors_are_safe_and_status_mapped(code,message,status):
    class Failure(Exception):
        pass
    error=Failure();error.code=code;error.message=message
    result=map_rpc_error(error)
    assert result.status_code==status
    assert 'private' not in str(result.detail) and 'not-real' not in str(result.detail)


def test_process_rate_limit_is_exercised_with_fake_backend():
    with TestClient(create_app(FakeRuntime(),rate_limit='1/minute')) as client:
        headers={'Authorization':'Bearer mock-user-token'}
        assert client.get('/gis/me',headers=headers).status_code==200
        response=client.get('/gis/me',headers=headers)
        assert response.status_code==429
        assert response.json()['detail']['code']=='GIS_RATE_LIMITED'
        assert response.headers['Retry-After']=='60'


def test_oversized_body_is_bounded_and_cors_readable(api):
    client,runtime=api
    response=client.post('/gis/datasets',content=b'x'*65537,
        headers={'Origin':'http://localhost:3000','Content-Type':'application/json',**key()})
    assert response.status_code==422 and runtime.calls==[]
    assert response.json()['detail']['code']=='GIS_INVALID_PAYLOAD'
    assert response.headers['access-control-allow-origin']=='http://localhost:3000'
