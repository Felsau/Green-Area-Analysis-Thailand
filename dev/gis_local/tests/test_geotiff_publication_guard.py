import importlib.util,json,sys
from pathlib import Path
import pytest
s=importlib.util.spec_from_file_location('a42_guard_base',Path(__file__).with_name('test_geotiff_worker_guard.py'));base=importlib.util.module_from_spec(s);sys.modules[s.name]=base;s.loader.exec_module(base);manager=base.manager
@pytest.fixture
def setup(tmp_path):
    f=base.setup.__wrapped__(tmp_path);root=tmp_path/'geotiff-prepared';objects=root/'objects';objects.mkdir(parents=True)
    marker=json.loads((tmp_path/'geotiff-storage/owner.json').read_text());marker['scope']='gis-geotiff-prepared-v1';(root/'owner.json').write_text(json.dumps(marker))
    name='gis-geotiff-publication-verify-'+f.run_id[:12];f.approval[f.cid].update(name=name,geotiff_objects=manager.canonical_bind_path(str(objects)),publication_only=True)
    f.worker.update(name='/'+name,command=['python3','-I','-B','/app/gis_worker/geotiff_publication_child.py'],labels={'gis.a4.2.scope':'geotiff-publication-verifier','gis.a4.2.instance':'a'*32,'gis.a4.2.run':f.run_id,'com.docker.compose.project':manager.guard.PROJECT})
    f.worker['host']['NetworkMode']='none';f.worker['networks']={'none':{}};f.worker['mounts'].append({'Type':'bind','Source':str(objects),'Destination':'/data/geotiff-artifacts','RW':False,'Propagation':'rprivate'});return f
def test_exact_ro_network_none_policy(setup):setup.verify()
@pytest.mark.parametrize('key,value',[('Memory',0),('MemorySwap',-1),('NanoCpus',0),('PidsLimit',0),('Privileged',True),('ReadonlyRootfs',False),('NetworkMode','host')])
def test_no_relaxed_resource_boundary(setup,key,value):
    setup.worker['host'][key]=value
    with pytest.raises(manager.guard.SafetyError):setup.verify()
def test_objects_cannot_be_rw(setup):
    setup.worker['mounts'][-1]['RW']=True
    with pytest.raises(manager.guard.SafetyError):setup.verify()
def test_unapproved_source_rejected(setup):
    setup.worker['mounts'][-1]['Source']='/unknown'
    with pytest.raises(manager.guard.SafetyError):setup.verify()
