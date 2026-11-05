"""New probe policy cannot grant Live startup or relax the legacy runtime."""
from copy import deepcopy
import importlib.util
from pathlib import Path
import sys

import pytest

spec=importlib.util.spec_from_file_location('a64d2_guard_test',Path(__file__).resolve().parents[1]/'gee_runtime_policy.py')
p=importlib.util.module_from_spec(spec);sys.modules[spec.name]=p;spec.loader.exec_module(p)


def fixture():
    instance,run,cid='a'*32,'b'*32,'c'*64;image='sha256:'+'d'*64;tree='e'*64
    labels={'gis.a6.4d2.scope':'offline-runtime-probe','gis.a6.4d2.source':tree,'gis.a6.4d2.egress':p.POLICY}
    env=['PATH=/usr/local/bin:/usr/bin:/bin']
    lock={'schema_version':1,'mode':'offline-probe-only','base_image':p.BASE_IMAGE,'image_id':image,
        'network_policy':p.POLICY,'live_enabled':False,'image_labels':labels,'source_tree_sha256':tree,
        'environment_sha256':p.fingerprint(env)}
    info={'Id':cid,'Name':'/gis-a64d2-probe-'+run[:12],'Image':image,'Mounts':[],
        'Config':{'Image':image,'Entrypoint':p.ENTRYPOINT.copy(),'Cmd':p.COMMAND.copy(),'User':'65534:65534',
            'WorkingDir':'/app/gis_worker','Labels':labels|{'gis.a6.4d2.instance':instance,'gis.a6.4d2.run':run},
            'Env':env,'OpenStdin':False,'Tty':False,'Volumes':None},
        'NetworkSettings':{'Networks':{'none':{}}},
        'HostConfig':{'Memory':1073741824,'MemorySwap':1073741824,'NanoCpus':1000000000,
            'PidsLimit':64,'ReadonlyRootfs':True,'Privileged':False,'Init':True,'NetworkMode':'none',
            'CapDrop':['ALL'],'SecurityOpt':['no-new-privileges:true'],'Tmpfs':deepcopy(p.TMPFS),
            'PidMode':'','IpcMode':'private','PublishAllPorts':False,
            'LogConfig':{'Type':'none'},
            'Ulimits':[{'Name':n,'Soft':v[0],'Hard':v[1]} for n,v in p.ULIMITS.items()]}}
    return info,lock,{'instance':instance,'run_id':run,'container_id':cid}


def test_exact_policy_only_approves_offline_probe():
    info,lock,context=fixture();value=p.verify_probe(info,lock,**context)
    assert value['verified'] and not value['live_enabled']
    with pytest.raises(p.RuntimePolicyError,match='NOT_APPROVED'):p.require_live_runtime(image=lock['image_id'],verified=True)


@pytest.mark.parametrize('key,value',[('Memory',0),('Memory',2147483648),('MemorySwap',-1),
    ('NanoCpus',0),('NanoCpus',2000000000),('PidsLimit',0),('PidsLimit',-1),
    ('ReadonlyRootfs',False),('Privileged',True),('Init',False),('NetworkMode','host'),
    ('NetworkMode','green-area-gis-t0-internal'),('CapDrop',[]),('CapAdd',['NET_ADMIN']),
    ('SecurityOpt',[]),('Tmpfs',{}),('PidMode','host'),('IpcMode','host'),
    ('PublishAllPorts',True),('Binds',['/home:/home']),('Devices',[{}]),
    ('Dns',['192.0.2.53']),('ExtraHosts',['unapproved.invalid:192.0.2.1']),
    ('PortBindings',{'8000/tcp':[{'HostPort':'8000'}]}),('Ulimits',[]),('LogConfig',{'Type':'json-file'})])
def test_resource_namespace_network_and_mount_mutations_rejected(key,value):
    info,lock,context=fixture();info['HostConfig'][key]=value
    with pytest.raises(p.RuntimePolicyError):p.verify_probe(info,lock,**context)


@pytest.mark.parametrize('key,value',[('Image','sha256:'+'0'*64),('User','0:0'),
    ('Entrypoint',['python3','-c']),('Cmd',['--live']),('WorkingDir','/home'),
    ('Env',['GOOGLE_APPLICATION_CREDENTIALS=/not-mounted/fake.json']),('OpenStdin',True),
    ('Tty',True),('Volumes',{'/home':{}}),('Labels',{})])
def test_unknown_image_command_env_or_user_is_rejected(key,value):
    info,lock,context=fixture();info['Config'][key]=value
    with pytest.raises(p.RuntimePolicyError):p.verify_probe(info,lock,**context)


def test_extra_network_mounts_and_unknown_policy_are_rejected():
    info,lock,context=fixture();info['NetworkSettings']['Networks']['external']={}
    with pytest.raises(p.RuntimePolicyError):p.verify_probe(info,lock,**context)
    info,lock,context=fixture();info['Mounts']=[{'Type':'bind','Source':'/home','Destination':'/home','RW':False}]
    with pytest.raises(p.RuntimePolicyError):p.verify_probe(info,lock,**context)
    info,lock,context=fixture();lock['network_policy']='allow-google-from-payload'
    with pytest.raises(p.RuntimePolicyError):p.verify_probe(info,lock,**context)
    info,lock,context=fixture();context['container_id']='f'*64
    with pytest.raises(p.RuntimePolicyError):p.verify_probe(info,lock,**context)
