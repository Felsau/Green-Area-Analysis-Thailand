import importlib.util
import json
from pathlib import Path
import sys
import pytest

spec=importlib.util.spec_from_file_location('a2_guard_base',Path(__file__).with_name('test_ldd_worker_guard.py'))
old=importlib.util.module_from_spec(spec);sys.modules[spec.name]=old;spec.loader.exec_module(old)
manager=old.manager


@pytest.fixture(params=[False,True],ids=['prepare','verify'])
def setup(tmp_path,request):
    fixture=old.setup.__wrapped__(tmp_path);verify=request.param
    prepared=tmp_path/'ldd-prepared';stage=prepared/'staging';stage.mkdir(parents=True)
    marker=json.loads((tmp_path/'ldd-storage/owner.json').read_text());marker['scope']='gis-ldd-prepared-v1'
    (prepared/'owner.json').write_text(json.dumps(marker))
    name=('gis-ldd-verify-' if verify else 'gis-ldd-prepare-worker-')+fixture.run_id[:12]
    policy=fixture.approval[fixture.cid];policy.update(name=name,prepare_staging=manager.canonical_bind_path(str(stage)))
    if verify:policy['verify_only']=True
    fixture.worker.update(name='/'+name,command=['python3','-I','-B','/app/gis_worker/'+('ldd_prepare_child.py' if verify else 'ldd_prepare_worker.py')]+(['--verify'] if verify else []),
        labels={'gis.a2.scope':'ldd-verify' if verify else 'ldd-prepare','gis.a2.instance':'a'*32,
            'gis.a2.run':fixture.run_id,'com.docker.compose.project':manager.guard.PROJECT})
    fixture.worker['mounts'].append({'Type':'bind','Source':str(stage),'Destination':'/data/prepare','RW':not verify,'Propagation':'rprivate'})
    if verify:
        fixture.worker['host']['NetworkMode']='none';fixture.worker['networks']={'none':{}}
    return fixture,verify


def test_exact_container_policy_only(setup):
    fixture,_=setup
    fixture.verify()
    with pytest.raises(manager.guard.SafetyError):fixture.runtime.verify_containers()


@pytest.mark.parametrize('field,value',[('Memory',0),('MemorySwap',-1),('NanoCpus',0),('PidsLimit',0),
    ('Privileged',True),('ReadonlyRootfs',False),('CapDrop',[]),('CapAdd',['SYS_ADMIN']),('NetworkMode','host')])
def test_limits_never_relaxed(setup,field,value):
    fixture,_=setup;fixture.worker['host'][field]=value
    with pytest.raises(manager.guard.SafetyError):fixture.verify()


def test_input_source_cannot_be_writable(setup):
    fixture,_=setup;fixture.worker['mounts'][-2]['RW']=True
    with pytest.raises(manager.guard.SafetyError):fixture.verify()


def test_staging_only_expected_access(setup):
    fixture,verify=setup;fixture.worker['mounts'][-1]['RW']=verify
    with pytest.raises(manager.guard.SafetyError):fixture.verify()


def test_unknown_storage_or_command_rejected(setup):
    fixture,_=setup;fixture.approval[fixture.cid]['prepare_staging']='/unknown/source'
    with pytest.raises(manager.guard.SafetyError):fixture.verify()


def test_verifier_cannot_use_internal_network(setup):
    fixture,verify=setup
    if verify:
        fixture.worker['host']['NetworkMode']='green-area-gis-t0-internal'
        with pytest.raises(manager.guard.SafetyError):fixture.verify()
