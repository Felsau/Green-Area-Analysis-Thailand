import importlib.util,json,sys
from pathlib import Path
import pytest
s=importlib.util.spec_from_file_location('a4_guard_base',Path(__file__).with_name('test_geotiff_worker_guard.py'))
base=importlib.util.module_from_spec(s);sys.modules[s.name]=base;s.loader.exec_module(base);manager=base.manager
@pytest.fixture(params=[False,True])
def setup(tmp_path,request):
    f=base.setup.__wrapped__(tmp_path);verify=request.param;root=tmp_path/'geotiff-prepared';stage=root/'staging';stage.mkdir(parents=True)
    marker=json.loads((tmp_path/'geotiff-storage/owner.json').read_text());marker['scope']='gis-geotiff-prepared-v1';(root/'owner.json').write_text(json.dumps(marker))
    name=('gis-geotiff-verify-' if verify else 'gis-geotiff-prepare-worker-')+f.run_id[:12]
    f.approval[f.cid].update(name=name,geotiff_staging=manager.canonical_bind_path(str(stage)))
    if verify:f.approval[f.cid]['verify_only']=True
    f.worker.update(name='/'+name,command=['python3','-I','-B','/app/gis_worker/'+('geotiff_prepare_child.py' if verify else 'geotiff_prepare_worker.py')]+(['--verify'] if verify else []),labels={'gis.a4.scope':'geotiff-verify' if verify else 'geotiff-prepare','gis.a4.instance':'a'*32,'gis.a4.run':f.run_id,'com.docker.compose.project':manager.guard.PROJECT})
    if verify:f.worker['host']['NetworkMode']='none';f.worker['networks']={'none':{}}
    f.worker['mounts'].append({'Type':'bind','Source':str(stage),'Destination':'/data/prepare','RW':not verify,'Propagation':'rprivate'})
    return f
def test_exact_approved_prepare_or_verifier(setup):setup.verify()
@pytest.mark.parametrize('key,value',[('Memory',0),('MemorySwap',-1),('NanoCpus',0),('PidsLimit',0),('Privileged',True),('ReadonlyRootfs',False),('NetworkMode','host')])
def test_no_resource_relaxation(setup,key,value):
    setup.worker['host'][key]=value
    with pytest.raises(manager.guard.SafetyError):setup.verify()
def test_unknown_staging_rejected(setup):
    setup.worker['mounts'][-1]['Source']='/unknown'
    with pytest.raises(manager.guard.SafetyError):setup.verify()
def test_wrong_write_boundary_rejected(setup):
    setup.worker['mounts'][-1]['RW']=not setup.worker['mounts'][-1]['RW']
    with pytest.raises(manager.guard.SafetyError):setup.verify()
