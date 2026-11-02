"""Offline T3 scientific readiness only; NOT a queue worker or DB test.

Reuse original PoC sources/fixtures read-only. No credential/env/GEE import.
Only a newly owned network-none container is created; existing volumes untouched.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

IMAGE = "sha256:fca4560d8a0d0198c0eb75fbf6598314cd8ed4a5e8bafa00e1d7298126aa04c9"
SCOPE = "gis-t3-science-readiness"
SOURCES = {
    "poc_gis.py": "91c8604115b8c5c08d362127ed5fd2ded8c8259d82f088ed259dba87cce81480",
    "test_poc_gis.py": "a3aa47a9f20a7e9d0bbee89c294c1f12e6833e02f145b5d42f187e39fb6a67a4",
    "manifest.json": "72a406b0291f3dcc553346def336c39f2a6f7e776c89e637c7e7372b3f86fcdf",
    "run_tests.py": "a1caa284f2203e610be5d12807324d460ae0d9c8b5e91ad0b0f06dcfc7afec9e",
}
CODE = r'''
import hashlib,json,os,sys
from pathlib import Path
sys.path.insert(0,'/poc')
os.chdir('/poc')
import test_poc_gis
before=hashlib.sha256(json.dumps({k:v for k,v in test_poc_gis.MANIFEST.items() if k!='files'},sort_keys=True).encode()).hexdigest()
test_poc_gis.MANIFEST['files']={k.replace(chr(92),'/'):v for k,v in test_poc_gis.MANIFEST['files'].items()}
after=hashlib.sha256(json.dumps({k:v for k,v in test_poc_gis.MANIFEST.items() if k!='files'},sort_keys=True).encode()).hexdigest()
assert before==after
import run_tests
code=run_tests.main()
result=json.loads(Path('/poc/test-results.json').read_text())
result['expected_values_sha_before']=before
result['expected_values_sha_after']=after
result['source_expected_results_unchanged']=before==after
result['test_type']='offline_scientific_readiness_not_worker_e2e'
print('T3_SCIENCE_JSON:'+json.dumps(result,separators=(',',':')))
raise SystemExit(code)
'''


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace-root',type=Path,required=True)
    args=parser.parse_args()
    workspace=args.workspace_root.resolve()
    source=workspace/'gis-local-poc-20261026'
    runtime=workspace/'t0-local-supabase-20261027-v2'
    owner=json.loads((runtime/'owner.json').read_text(encoding='utf-8'))
    if owner.get('scope')!='gis-foundation-t0' or owner.get('project')!='green-area-gis-t0':
        raise RuntimeError('EXPLICIT_LOCAL_RUNTIME_REQUIRED')
    for name,expected in SOURCES.items():
        if digest(source/name)!=expected:raise RuntimeError('POC_SOURCE_DRIFT')
    manifest=json.loads((source/'manifest.json').read_text(encoding='utf-8'))
    originals={name:digest(source/name) for name in SOURCES}
    for name,item in manifest['files'].items():
        path=(source/'fixtures'/name.replace(chr(92),'/')).resolve()
        if not path.is_relative_to((source/'fixtures').resolve()) or path.stat().st_size!=item['bytes'] or digest(path)!=item['sha256']:
            raise RuntimeError('FIXTURE_DRIFT')
    allowed={'PATH','SYSTEMROOT','SYSTEMDRIVE','COMSPEC','TEMP','TMP','WINDIR','PATHEXT','LANG','LC_ALL'}
    environment={k:v for k,v in os.environ.items() if k.upper() in allowed}
    base=['docker','--config',str(runtime/'docker-config'),'--host','npipe:////./pipe/dockerDesktopLinuxEngine']
    def docker(arguments,check=True,timeout=120):
        result=subprocess.run(base+arguments,env=environment,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=timeout)
        if check and result.returncode:raise RuntimeError('OFFLINE_DOCKER_OPERATION_FAILED')
        return result
    image=json.loads(docker(['image','inspect',IMAGE,'--format','{"id":{{json .Id}},"os":{{json .Os}},"arch":{{json .Architecture}}}']).stdout)
    if image!={'id':IMAGE,'os':'linux','arch':'amd64'}:raise RuntimeError('IMAGE_REJECTED')
    run=uuid.uuid4().hex
    name='gis-t3-science-'+run[:12]
    arguments=['create','--pull=never','--name',name,'--label','gis.t3.scope='+SCOPE,'--label','gis.t3.run='+run,
        '--network=none','--memory=1g','--memory-swap=1g','--cpus=1','--pids-limit=64',
        '--read-only','--cap-drop=ALL','--security-opt=no-new-privileges:true','--user=65534:65534',
        '--tmpfs=/poc:rw,nosuid,noexec,size=64m,mode=1777','--tmpfs=/tmp:rw,nosuid,noexec,size=64m,mode=1777',
        '--workdir=/poc','--env=PYTEST_DISABLE_PLUGIN_AUTOLOAD=1','--env=PROJ_NETWORK=OFF',
        '--env=OPENBLAS_NUM_THREADS=1','--env=OMP_NUM_THREADS=1']
    for item in ('poc_gis.py','test_poc_gis.py','run_tests.py','manifest.json','fixtures'):
        arguments+=['--mount',f'type=bind,src={source/item},dst=/poc/{item},readonly']
    arguments+=['--entrypoint=python',IMAGE,'-I','-B','-c',CODE]
    cid=None;state=None
    report={'scope':SCOPE,'run':run,'image':image,'database_contacted':False,'worker_e2e':False}
    try:
        cid=docker(arguments).stdout.strip()
        state=json.loads(docker(['inspect','--format','{"id":{{json .Id}},"labels":{{json .Config.Labels}},"network":{{json .HostConfig.NetworkMode}},"memory":{{json .HostConfig.Memory}},"swap":{{json .HostConfig.MemorySwap}},"cpus":{{json .HostConfig.NanoCpus}},"pids":{{json .HostConfig.PidsLimit}},"readonly":{{json .HostConfig.ReadonlyRootfs}},"mounts":{{json .Mounts}}}',cid]).stdout)
        if (state['labels'].get('gis.t3.scope')!=SCOPE or state['labels'].get('gis.t3.run')!=run
                or state['network']!='none' or state['memory']!=1073741824 or state['swap']!=1073741824
                or state['cpus']!=1000000000 or state['pids']!=64 or not state['readonly']
                or any(m['Type']=='bind' and m['RW'] for m in state['mounts'])):
            raise RuntimeError('OFFLINE_CONTAINER_GUARD_REJECTED')
        output=docker(['start','--attach',cid],check=False,timeout=120)
        marker=next((line for line in output.stdout.splitlines() if line.startswith('T3_SCIENCE_JSON:')),None)
        if marker is None:raise RuntimeError('SCIENCE_REPORT_MISSING')
        report['science']=json.loads(marker.split(':',1)[1])
        report['limits']={key:state[key] for key in ('network','memory','swap','cpus','pids','readonly')}
        report['sources_unchanged']=all(digest(source/name)==expected for name,expected in originals.items())
        if output.returncode or report['science']['exit_code'] or not report['sources_unchanged']:
            raise RuntimeError('SCIENTIFIC_READINESS_FAILED')
    finally:
        if cid:
            labels=json.loads(docker(['inspect','--format','{{json .Config.Labels}}',cid]).stdout)
            if labels.get('gis.t3.scope')==SCOPE and labels.get('gis.t3.run')==run:
                docker(['stop','--time','5',cid],check=False)
                docker(['rm',cid]);report['owned_container_removed']=True
        output_dir=runtime/'t3';output_dir.mkdir(exist_ok=True)
        (output_dir/'science-readiness.json').write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps({'science':report['science']['summary'],'sources_unchanged':report['sources_unchanged'],
        'worker_e2e':False,'owned_container_removed':report.get('owned_container_removed',False)}))


if __name__=='__main__':
    try:main()
    except Exception as error:
        print(json.dumps({'ok':False,'error_type':type(error).__name__}));sys.exit(1)
