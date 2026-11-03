import importlib.util,json,sys
from pathlib import Path
import pytest
spec=importlib.util.spec_from_file_location('a3_guard_base',Path(__file__).with_name('test_ldd_worker_guard.py'))
old=importlib.util.module_from_spec(spec);sys.modules[spec.name]=old;spec.loader.exec_module(old)
manager=old.manager

@pytest.fixture
def setup(tmp_path):
    f=old.setup.__wrapped__(tmp_path);root=tmp_path/'ldd-prepared';objects=root/'objects';objects.mkdir(parents=True)
    marker=json.loads((tmp_path/'ldd-storage/owner.json').read_text());marker['scope']='gis-ldd-prepared-v1'
    (root/'owner.json').write_text(json.dumps(marker))
    name='gis-ldd-publication-verify-'+f.run_id[:12]
    f.approval[f.cid].update(name=name,prepare_objects=manager.canonical_bind_path(str(objects)),publication_only=True)
    f.worker.update(name='/'+name,command=['python3','-I','-B','/app/gis_worker/ldd_publication_child.py'],
        labels={'gis.a3.scope':'ldd-publication-verifier','gis.a3.instance':'a'*32,'gis.a3.run':f.run_id,'com.docker.compose.project':manager.guard.PROJECT})
    f.worker['host']['NetworkMode']='none';f.worker['networks']={'none':{}}
    f.worker['mounts'].append({'Type':'bind','Source':str(objects),'Destination':'/data/ldd-artifacts','RW':False,'Propagation':'rprivate'})
    return f

def test_exact_publication_container(setup):setup.verify()

@pytest.mark.parametrize('key,value',[('Memory',0),('MemorySwap',-1),('NanoCpus',0),('PidsLimit',0),('Privileged',True),('ReadonlyRootfs',False),('NetworkMode','host')])
def test_limits_never_relaxed(setup,key,value):
    setup.worker['host'][key]=value
    with pytest.raises(manager.guard.SafetyError):setup.verify()

def test_objects_cannot_be_writable(setup):
    setup.worker['mounts'][-1]['RW']=True
    with pytest.raises(manager.guard.SafetyError):setup.verify()

def test_unknown_object_root_rejected(setup):
    setup.approval[setup.cid]['prepare_objects']='/unapproved'
    with pytest.raises(manager.guard.SafetyError):setup.verify()
