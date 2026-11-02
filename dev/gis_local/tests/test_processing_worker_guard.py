"""Only the exact processing daemon plus three read-only legacy sources is allowed."""
import copy
import importlib.util
from pathlib import Path
import sys
import pytest

spec=importlib.util.spec_from_file_location('p3_guard_base',Path(__file__).with_name('test_t3_worker_guard.py'))
base=importlib.util.module_from_spec(spec);sys.modules[spec.name]=base;spec.loader.exec_module(base)
manager=base.manager

@pytest.fixture
def setup():
    item=base.T3WorkerGuardTests(methodName='runTest');item.setUp()
    name='gis-processing-worker-'+item.run_id[:12]
    item.approval[item.cid]={'name':name,'run_id':item.run_id,'processing_legacy':True}
    item.worker.update(name='/'+name,command=['python3','-I','-B','/app/gis_worker/processing_worker.py'],
        labels={'gis.phase3.scope':'processing-worker','gis.phase3.instance':'a'*32,
            'gis.phase3.run':item.run_id,'com.docker.compose.project':manager.guard.PROJECT})
    for target,source in {'gee_utils.py':manager.WORKER_SOURCE.parent/'gee_utils.py',
        'ndvi_compute.py':manager.WORKER_SOURCE.parent/'routers/ndvi/compute.py',
        'lst.py':manager.WORKER_SOURCE.parent/'routers/lst.py'}.items():
        item.worker['mounts'].append({'Type':'bind','Source':str(source),'Destination':'/app/legacy/'+target,
            'RW':False,'Propagation':'rprivate'})
    return item

def test_exact_processing_policy(setup):
    assert set(setup.verify())==set(manager.SERVICES)

def test_default_strict_mode_not_relaxed(setup):
    with pytest.raises(manager.guard.SafetyError): setup.runtime.verify_containers()

@pytest.mark.parametrize('field,value',[('Memory',0),('MemorySwap',-1),('NanoCpus',0),('PidsLimit',0),
    ('Privileged',True),('ReadonlyRootfs',False),('NetworkMode','host'),('CapAdd',['SYS_ADMIN'])])
def test_processing_limits(setup,field,value):
    setup.worker['host'][field]=value
    with pytest.raises(manager.guard.SafetyError):setup.verify()

@pytest.mark.parametrize('field,value',[('Source','/unknown/gee_utils.py'),('Destination','/app/main.py'),
    ('RW',True),('Propagation','rshared')])
def test_legacy_mount_not_arbitrary(setup,field,value):
    setup.worker['mounts'][1][field]=value
    with pytest.raises(manager.guard.SafetyError):setup.verify()

@pytest.mark.parametrize('field,value',[('user','0:0'),('image','python:latest'),
    ('command',['python3','-c','anything'])])
def test_processing_identity(setup,field,value):
    setup.worker[field]=value
    with pytest.raises(manager.guard.SafetyError):setup.verify()

def test_unapproved_flag_rejected(setup):
    setup.approval[setup.cid]['processing_legacy']=False
    with pytest.raises(manager.guard.SafetyError):setup.verify()

def test_extra_source_rejected(setup):
    setup.worker['mounts'].append({'Type':'bind','Source':str(Path.home()),'Destination':'/other','RW':False})
    with pytest.raises(manager.guard.SafetyError):setup.verify()
