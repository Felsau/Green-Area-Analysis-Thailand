"""Explicit offline packaging/probe operator; never a Live launcher.

All generated context, image locks and logs stay outside Repository. Uses
installed requirements and existing Linux wheels only; never pip/pull/network.
No database/auth/credential discovery. No existing container/volume changes.
"""
import argparse
import hashlib
from importlib import metadata
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

from packaging.requirements import Requirement

REPO=Path(__file__).resolve().parents[2]
BASE='sha256:7557955c9e2c8611ea1396ddef6d8629c2ee1e7f193e85f0c65bcf5db9566674'
BASE_TAG='gis-gee-mock:20261104-a63'
DOCKER=Path('C:/Users/chaya/AppData/Local/Programs/DockerDesktop/resources/bin/docker.exe')
ROOT=Path('C:/Users/chaya/.codex/visualizations/2026/10/04/01a107d9-ff44-7731-8bc3-91814ffd8d51')
OUTPUT=ROOT/'a6-boundary'
NATIVE=ROOT/'a6-sdk-http/linux-native'


def docker(args, *, timeout=90):
    result=subprocess.run([str(DOCKER),'--host','npipe:////./pipe/dockerDesktopLinuxEngine',
        '--config',str(ROOT/'t0-local-supabase-20261027-v2/docker-config'),*args],
        capture_output=True,text=True,timeout=timeout)
    if result.returncode:
        # Docker inputs contain paths/hashes only; no secrets/environment dump.
        raise RuntimeError('OFFLINE_DOCKER_FAILED: '+result.stderr[-2000:])
    return result.stdout


def sources():
    paths=list((REPO/'green-area-backend/gis_worker').glob('*.py'))
    paths += [REPO/'green-area-backend/tests'/f for f in
        ('test_gee_credential_boundary.py','test_gee_genuine_foundation.py','test_gee_sdk_transport.py')]
    paths += [Path(__file__),Path(__file__).with_name('gee_boundary.Dockerfile'),
        Path(__file__).with_name('gee_boundary_entry.py')]
    return {p.relative_to(REPO).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def build():
    base=json.loads(docker(['image','inspect',BASE]))[0]
    if json.loads(docker(['image','inspect',BASE_TAG]))[0]['Id']!=BASE:
        raise RuntimeError('BOUNDARY_BASE_DRIFT')
    if base['Os']!='linux' or base['Architecture']!='amd64':raise RuntimeError('BOUNDARY_PLATFORM')
    OUTPUT.mkdir(exist_ok=True)
    manifest=sources();tree=hashlib.sha256(json.dumps(manifest,sort_keys=True).encode()).hexdigest()
    context=OUTPUT/('context-'+tree[:12])
    # Never overwrite existing sandbox output. Inspect/reuse by hash only.
    if context.exists():raise RuntimeError('BOUNDARY_CONTEXT_EXISTS_USE_EXISTING_LOCK_OR_NEW_SANDBOX')
    context.mkdir();(context/'sdk').mkdir()
    for name in ('gis_worker','tests'):
        (context/name).mkdir()
    for p in manifest:
        if '/gis_worker/' in p: shutil.copyfile(REPO/p,context/'gis_worker'/Path(p).name)
        elif '/tests/' in p: shutil.copyfile(REPO/p,context/'tests'/Path(p).name)
    shutil.copyfile(Path(__file__).with_name('gee_boundary.Dockerfile'),context/'Dockerfile')
    shutil.copyfile(Path(__file__).with_name('gee_boundary_entry.py'),context/'boundary_entry.py')
    (context/'source-manifest.json').write_text(json.dumps(manifest,indent=2))
    # Recursively copy the already-installed SDK's required distributions. Skip
    # Windows binaries/entry-point scripts; Linux native files are copied below.
    pending=['earthengine-api','cryptography'];seen={};site=Path(sys.executable).parents[1]/'Lib/site-packages'
    while pending:
        name=pending.pop();dist=metadata.distribution(name);key=dist.metadata['Name'].lower()
        if key in seen:continue
        seen[key]=dist.version
        for raw in dist.requires or ():
            req=Requirement(raw)
            if req.marker is None or req.marker.evaluate({'extra':''}):pending.append(req.name)
        for item in dist.files or ():
            src=Path(dist.locate_file(item)).resolve()
            if not src.is_relative_to(site.resolve()) or not src.is_file():continue
            rel=src.relative_to(site.resolve())
            if src.suffix.lower() in ('.pyd','.pyc','.exe','.dll','.pth') or '__pycache__' in rel.parts:continue
            dest=context/'sdk'/rel;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src,dest)
    # Existing previously authorized Linux wheels, already expanded offline.
    for src in NATIVE.rglob('*'):
        if src.is_file() and '__pycache__' not in src.parts:
            dest=context/'sdk'/src.relative_to(NATIVE);dest.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(src,dest)
    if seen.get('earthengine-api')!='1.7.30' or seen.get('cryptography')!='49.0.0':
        raise RuntimeError('BOUNDARY_DEPENDENCY_DRIFT')
    dependencies={p.relative_to(context/'sdk').as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (context/'sdk').rglob('*') if p.is_file()}
    tag='gis-gee-boundary:offline-'+tree[:12]
    docker(['build','--pull=false','--network=none','--build-arg','SOURCE_TREE_SHA256='+tree,
        '-t',tag,str(context)],timeout=120)
    image=json.loads(docker(['image','inspect',tag]))[0]
    if (image['RootFS']['Layers'][:len(base['RootFS']['Layers'])]!=base['RootFS']['Layers']
        or image['Config']['User']!='65534:65534'
        or image['Config']['Labels'].get('gis.a6.boundary.source')!=tree):
        raise RuntimeError('BOUNDARY_IMAGE_DRIFT')
    lock={'mode':'offline-boundary-only','live_enabled':False,'image_id':image['Id'],
        'source':manifest,'source_tree_sha256':tree,'base_image':BASE,'dependencies':seen,
        'packaged_dependency_hashes':dependencies}
    (OUTPUT/'image-lock.json').write_text(json.dumps(lock,indent=2))
    return {'image_id':image['Id'],'source_tree_sha256':tree,'dependencies':seen,'live_enabled':False}


def probe():
    lock=json.loads((OUTPUT/'image-lock.json').read_text())
    if lock['source']!=sources() or lock['mode']!='offline-boundary-only' or lock['live_enabled'] is not False:
        raise RuntimeError('BOUNDARY_SOURCE_LOCK_DRIFT')
    # Root exists ONLY in this isolated probe to drop child UIDs. No NET_ADMIN,
    # SYS_ADMIN, host namespaces, mounts, credentials, published ports or logs.
    name='gis-a6-boundary-'+lock['source_tree_sha256'][:12]
    args=['create','--name',name,'--network','none','--read-only','--memory=1g',
        '--memory-swap=1g','--cpus=1','--pids-limit=64','--cap-drop=ALL',
        '--cap-add=SETUID','--cap-add=SETGID','--security-opt=no-new-privileges:true',
        '--user=0:0','--log-driver=none','--ulimit','core=0:0',
        '--tmpfs=/tmp:rw,nosuid,noexec,size=128m,mode=1777',lock['image_id'],'--offline-probe']
    cid=docker(args).strip()
    try:
        info=json.loads(docker(['inspect',cid]))[0];host=info['HostConfig'];config=info['Config']
        exact={'NetworkMode':'none','ReadonlyRootfs':True,'Privileged':False,'Memory':1073741824,
            'MemorySwap':1073741824,'NanoCpus':1000000000,'PidsLimit':64,'CapDrop':['ALL'],
            'CapAdd':['CAP_SETGID','CAP_SETUID'],'SecurityOpt':['no-new-privileges:true']}
        if (info['Id']!=cid or info['Image']!=lock['image_id'] or info['Mounts']
            or config['User']!='0:0' or config['Cmd']!=['--offline-probe']
            or config['Entrypoint']!=['/usr/local/bin/python3','-I','-B','/app/boundary_entry.py']
            or host['LogConfig']['Type']!='none' or any(host.get(k)!=v for k,v in exact.items())
            or host.get('PortBindings') or host.get('Devices') or host.get('PidMode')
            or host.get('Tmpfs')!={'/tmp':'rw,nosuid,noexec,size=128m,mode=1777'}):
            raise RuntimeError('BOUNDARY_CONTAINER_REJECTED')
        output=docker(['start','--attach',cid],timeout=120)
        state=json.loads(docker(['inspect',cid,'--format','{{json .State}}']))
        (OUTPUT/'probe.log').write_text(output)
        result={'exit':state['ExitCode'],'oom':state['OOMKilled'],'image_id':lock['image_id'],
            'source':sources(),'network':'none','live_enabled':False,'container_identity_checked':True}
        (OUTPUT/'probe.json').write_text(json.dumps(result,indent=2))
        return result|{'summary':output[-3500:]}
    finally:
        # Remove only this operator-created stopped ephemeral container; no volumes.
        state=json.loads(docker(['inspect',cid,'--format','{{json .State}}']))
        if state['Running']:docker(['stop','--time','5',cid])
        docker(['rm',cid])


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=['build','probe'])
    args=parser.parse_args();print(json.dumps(build() if args.action=='build' else probe(),indent=2))
