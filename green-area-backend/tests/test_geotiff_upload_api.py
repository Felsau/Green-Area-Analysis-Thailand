"""Auth/RPC unit contracts and real private filesystem; not native/SQL E2E."""
import asyncio
import hashlib
import json
import importlib.util
from pathlib import Path
import struct
import sys

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest

from gis_app import create_app
from gis_geotiff_storage import LocalGeoTiffStore
from gis_service import gis_error
spec=importlib.util.spec_from_file_location('geotiff_api_base',Path(__file__).with_name('test_ldd_upload_api.py'))
base=importlib.util.module_from_spec(spec);sys.modules[spec.name]=base;spec.loader.exec_module(base)
BaseRuntime,ACTOR,DATASET,KEY,chunks=base.FakeRuntime,base.ACTOR,base.DATASET,base.KEY,base.chunks


class Runtime(BaseRuntime):
    def __init__(self):
        super().__init__()
        self.kind, self.purpose, self.month = 'geotiff', 'ndvi', 0

    def require_ready(self):
        return {'migration_versions': list(range(27,37))}

    def rpc(self, name, payload):
        if name == 'gis_geotiff_command':
            self.calls.append((name,payload))
            if not self.allowed:
                raise gis_error(403,'GIS_FORBIDDEN','unit denied')
            return {'status':200 if payload['p_operation']=='preflight' else 201,'body':payload['p_payload']}
        return super().rpc(name,payload)


@pytest.fixture
def setup(tmp_path):
    runtime=Runtime()
    (tmp_path/'owner.json').write_text(json.dumps({'scope':'gis-foundation-t0','project':runtime.settings.cluster,
        'instance':runtime.settings.runtime_instance}))
    store=LocalGeoTiffStore(runtime,tmp_path)
    return runtime,store,TestClient(create_app(runtime,geotiff_store=store))


def raw_tiff():
    # Sufficient only for HTTP signature preflight; native tests use real TIFFs.
    return b'II*\x00'+struct.pack('<I',8)+b'\x00\x00\x00\x00\x00\x00'


def send(client,raw=None,**options):
    return client.post('/gis/datasets/'+DATASET+'/geotiff-uploads',
        params={'expected_revision':3,'crs':'EPSG:32647','profile':'ndvi_ready',**options.pop('params',{})},
        headers={'Authorization':'Bearer mock-user-token','Idempotency-Key':KEY,'Content-Type':'image/tiff',**options.pop('headers',{})},
        content=raw if raw is not None else raw_tiff(),**options)


def test_upload_stream_saved_by_content_hash_and_scientific_metadata(setup):
    runtime,store,api=setup
    response=send(api)
    assert response.status_code==201
    data=response.json()
    assert data['sha256']==hashlib.sha256(raw_tiff()).hexdigest()
    assert data['profile']=='ndvi_ready' and data['crs']=='EPSG:32647'
    assert (store.objects/(data['sha256']+'.tif')).read_bytes()==raw_tiff()
    assert [c[1]['p_operation'] for c in runtime.calls if c[0]=='gis_geotiff_command']==['preflight','upload']


def test_retry_storage_is_immutable_and_no_extra_object(setup):
    _,store,api=setup
    first=send(api).json(); second=send(api).json()
    assert first['upload_id']==second['upload_id']
    assert len(list(store.objects.iterdir()))==1
    assert not list(store.staging.iterdir())


@pytest.mark.parametrize('raw',[b'',b'not TIFF',b'II+\0'+b'\0'*20,b'MM\0*'+b'\xff'*12,b'II*\0'+struct.pack('<I',1000)+b'\0'*8])
def test_invalid_signature_and_bigtiff_rejected_before_publishing(setup,raw):
    _,store,api=setup
    assert send(api,raw).status_code==(413 if not raw else 422)
    assert not list(store.objects.iterdir())


@pytest.mark.parametrize('params',[{'crs':'EPSG:3857'},{'profile':'raw_dn'},{'path':'../../file'},{'url':'https://invalid.example/x'},{'expected_revision':2},{'profile':'lst_kelvin_ready'}])
def test_metadata_and_revision_guards_before_reading(setup,params):
    _,store,api=setup
    assert send(api,params=params).status_code in (409,422)
    assert not list(store.objects.iterdir())


def test_unauthorized_upload_never_creates_object(setup):
    runtime,store,api=setup
    assert send(api,headers={'Authorization':'Bearer invalid'}).status_code==401
    runtime.allowed=False
    assert send(api).status_code==403
    assert not list(store.objects.iterdir())


def test_wrong_mime_does_not_bypass_content_check(setup):
    _,store,api=setup
    assert send(api,headers={'Content-Type':'application/json'}).status_code==415
    assert not list(store.objects.iterdir())


def test_stream_size_and_shared_quota_are_enforced(setup,monkeypatch):
    import gis_ldd_storage as common
    _,store,api=setup
    monkeypatch.setattr(common,'MAX_UPLOAD',12)
    assert send(api).status_code==413
    monkeypatch.setattr(common,'MAX_UPLOAD',20*1024**2)
    monkeypatch.setattr(common,'DISK_QUOTA',4)
    assert send(api).status_code==507
    assert not list(store.objects.iterdir())


def test_existing_content_tampering_fails_closed(setup):
    _,store,api=setup
    data=send(api).json();path=store.objects/(data['sha256']+'.tif')
    path.chmod(0o600);path.write_bytes(b'X'*len(raw_tiff()))
    response=send(api)
    assert response.status_code==503 and response.json()['detail']['code']=='GIS_GEOTIFF_INTEGRITY'


def test_owner_marker_wrong_target_is_rejected(setup):
    _,store,_=setup
    (store.root/'owner.json').write_text('{}')
    with pytest.raises(HTTPException):
        asyncio.run(store.receive(chunks(raw_tiff())))


def test_schema_035_cannot_enable_geo_storage(setup):
    runtime,store,_=setup
    runtime.require_ready=lambda:{'migration_versions':list(range(27,36))}
    with pytest.raises(HTTPException):store.attest()
