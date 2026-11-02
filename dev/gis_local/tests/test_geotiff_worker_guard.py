"""Exact GeoTIFF container/storage approval keeps the strict default topology."""
import importlib.util
import json
from pathlib import Path
import sys
import pytest

spec=importlib.util.spec_from_file_location('geo_guard_base',Path(__file__).with_name('test_ldd_worker_guard.py'))
old=importlib.util.module_from_spec(spec);sys.modules[spec.name]=old;spec.loader.exec_module(old)
manager=old.manager


@pytest.fixture
def setup(tmp_path):
    fixture=old.setup.__wrapped__(tmp_path)
    storage=tmp_path/'geotiff-storage';objects=storage/'objects';objects.mkdir(parents=True)
    (storage/'owner.json').write_text(json.dumps({'scope':'gis-geotiff-storage-v1','runtime_instance':'a'*32,
        'baseline_fingerprint':'e'*64,'database':'postgres','cluster':'green-area-gis-t0'}))
    name='gis-geotiff-worker-'+fixture.run_id[:12]
    fixture.approval[fixture.cid]={'name':name,'run_id':fixture.run_id,'geotiff_storage':manager.canonical_bind_path(str(objects))}
    fixture.worker.update(name='/'+name,command=['python3','-I','-B','/app/gis_worker/geotiff_worker.py'],
        labels={'gis.phase4.scope':'geotiff-worker','gis.phase4.instance':'a'*32,'gis.phase4.run':fixture.run_id,
        'com.docker.compose.project':manager.guard.PROJECT})
    fixture.worker['mounts'][-1].update(Source=str(objects),Destination='/data/geotiff/objects')
    return fixture


def test_exact_geo_worker_allowed_but_default_stays_strict(setup):
    assert set(setup.verify())==set(manager.SERVICES)
    with pytest.raises(manager.guard.SafetyError):setup.runtime.verify_containers()


@pytest.mark.parametrize('field,value',[('command',['sh']),('user','0:0'),('image','python:latest'),
    ('networks',{'green-area-gis-t0-internal':{},'external':{}})])
def test_geo_identity_negative(setup,field,value):
    setup.worker[field]=value
    with pytest.raises(manager.guard.SafetyError):setup.verify()


@pytest.mark.parametrize('field,value',[('Memory',0),('PidsLimit',0),('NanoCpus',0),('Privileged',True),('ReadonlyRootfs',False)])
def test_geo_unbounded_or_privileged_rejected(setup,field,value):
    setup.worker['host'][field]=value
    with pytest.raises(manager.guard.SafetyError):setup.verify()


@pytest.mark.parametrize('field,value',[('RW',True),('Source','/elsewhere'),('Destination','/data/ldd')])
def test_geo_storage_exact_readonly_mount(setup,field,value):
    setup.worker['mounts'][-1][field]=value
    with pytest.raises(manager.guard.SafetyError):setup.verify()


def test_foreign_peer_is_rejected(setup):
    setup.foreign_members['d'*64]={}
    with pytest.raises(manager.guard.SafetyError):setup.verify()
