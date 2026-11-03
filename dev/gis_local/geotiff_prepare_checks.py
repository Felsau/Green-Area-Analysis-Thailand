"""A4.1 real Local integration; fresh synthetic rows/files, no migrations/cloud."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib.util
import io
import json
import logging
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import time
from uuid import uuid4
import zipfile
HERE=Path(__file__).resolve().parent;REPO=HERE.parents[1]
def load(name,path):
    s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);sys.modules[name]=m;s.loader.exec_module(m);return m
a4=load('a4_checks_operator',HERE/'geotiff_prepare_local.py');m=a4.m
demo_module=load('a4_checks_demo',REPO/'dev/gis_ui/phase5_demo.py');demo_module.local_target=lambda root:a4.GeoTiffPrepareLocal(root)
def source():
    value=demo_module.source()
    for folder in ('green-area-backend','dev/gis_ui'):
        for p in (REPO/folder).glob('*.py'):
            value['files'][p.relative_to(REPO).as_posix()]=hashlib.sha256(p.read_bytes()).hexdigest()
    for p in (REPO/'dev/gis_ui').glob('a4*'):
        if p.is_file():value['files'][p.relative_to(REPO).as_posix()]=hashlib.sha256(p.read_bytes()).hexdigest()
    value['sha256']=hashlib.sha256(json.dumps(value['files'],sort_keys=True).encode()).hexdigest();return value

def fixtures(local,output,year):
    directory=output/'fixtures';directory.mkdir()
    code="""import sys,importlib.util,hashlib,json;from pathlib import Path
sys.path.insert(0,'/work');s=importlib.util.spec_from_file_location('fixture','/work/tests/test_geotiff_prepare_native.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
out=Path('/out');rows={}
for profile in ('ndvi_ready','lst_celsius_ready','lst_kelvin_ready'):
 tags={'GIS_PROFILE':profile,'GIS_PROVINCE':'Bangkok Metropolis','GIS_YEAR':'YEAR','GIS_MONTH':'0'}
 packet,root,_=m.fixture(out,profile,tags=tags);raw=next(root.iterdir()).read_bytes();name=profile+'.tif';(out/name).write_bytes(raw);rows[profile]={'filename':name,'sha256':hashlib.sha256(raw).hexdigest(),'expected_mean':0 if profile=='ndvi_ready' else20}
packet,root,_=m.fixture(out,values=m.np.full((1000,1000),.5),tags={'GIS_PROFILE':'ndvi_ready','GIS_PROVINCE':'Bangkok Metropolis','GIS_YEAR':'YEAR','GIS_MONTH':'0'});raw=next(root.iterdir()).read_bytes();(out/'large.tif').write_bytes(raw);rows['large']={'filename':'large.tif','sha256':hashlib.sha256(raw).hexdigest(),'expected_mean':.5}
(out/'manifest.json').write_text(json.dumps(rows))
""".replace('YEAR',str(year)).replace('else20','else 20')
    args=['run','--rm','--entrypoint','','--network=none','--memory=1g','--memory-swap=1g','--cpus=1','--pids-limit=64','--read-only','--cap-drop=ALL','--security-opt=no-new-privileges:true','--user=65534:65534','--tmpfs=/tmp:rw,nosuid,noexec,size=32m,mode=1777',
        '--mount','type=bind,src='+str(REPO/'green-area-backend/gis_worker')+',dst=/work/gis_worker,readonly','--mount','type=bind,src='+str(REPO/'green-area-backend/tests')+',dst=/work/tests,readonly','--mount','type=bind,src='+str(directory)+',dst=/out',m.IMAGE,'python3','-I','-B','-c',code]
    local.db.runtime.docker(args,quiet=True,timeout=90)
    values=json.loads((directory/'manifest.json').read_text())
    for v in values.values():
        if hashlib.sha256((directory/v['filename']).read_bytes()).hexdigest()!=v['sha256']:raise RuntimeError('FIXTURE_DRIFT')
    return directory,values

def run(root,node_modules):
    import httpx
    logging.disable(logging.CRITICAL);demo=demo_module.Demo(root);local=demo.local;out=local.output/('integration-'+demo.run);out.mkdir();initial=source();rows=[];tokens={};literal=m.t2.t1.literal
    http=httpx.Client(trust_env=False,follow_redirects=False,timeout=120)
    def check(name,value):
        rows.append({'name':name,'status':'Pass' if value else 'Fail'});print(json.dumps(rows[-1]),flush=True)
        if not value:raise AssertionError(name)
    def sql(body):return local.sql(body,read_only=True)
    def job(jid):return sql('SELECT to_jsonb(j) FROM gis.jobs j WHERE id='+literal(jid)+'::uuid')
    def wait(jid,seconds=150):
        end=time.monotonic()+seconds
        while time.monotonic()<end:
            r=job(jid)
            if r['state'] in ('succeeded','failed'):return r
            time.sleep(.4)
        raise RuntimeError('JOB_TIMEOUT')
    def req(method,path,body=None,role='officer',raw=None,params=None,key=None):
        h={'Authorization':'Bearer '+tokens[role]}
        if method!='GET':h['Idempotency-Key']=key or str(uuid4())
        if raw is not None:h['Content-Type']='image/tiff'
        return http.request(method,'http://127.0.0.1:55422/gis'+path,headers=h,json=body,content=raw,params=params)
    def ok(method,path,body=None,**kw):
        r=req(method,path,body,**kw)
        if r.status_code not in (200,201,202):raise RuntimeError('HTTP_'+str(r.status_code)+'_'+str(r.json().get('detail',{}).get('code','unknown'))+'_'+path.split('/')[-1])
        return r.json()
    def dataset(metric):return ok('POST','/datasets',{'province':'Bangkok Metropolis','data_year':year,'month':0,'kind':'geotiff','purpose':metric,'title':'A4 Synthetic '+metric+' '+demo.run})
    def upload(d,profile,fixture_name=None):
        f=manifest[fixture_name or profile];raw=(directory/f['filename']).read_bytes()
        ok('POST','/datasets/'+d['id']+'/geotiff-uploads',raw=raw,params={'expected_revision':d['revision'],'crs':'EPSG:4326','profile':profile})
        e=next(x for x in ok('GET','/datasets/'+d['id']+'/editions',params={'limit':100})['data'] if x.get('upload',{}).get('sha256')==f['sha256'])
        j=ok('POST','/editions/'+e['id']+'/validation-jobs',{'expected_revision':e['input_revision']})
        check('original_native_validation_'+(fixture_name or profile),wait(j['id'])['state']=='succeeded')
        return ok('GET','/editions/'+e['id'])
    def payload(d,e):
        info=ok('GET','/editions/'+e['id']+'/geotiff-prepared')
        return {'expected_dataset_revision':d['revision'],'expected_input_revision':e['input_revision'],'input_hash':e['input_hash'],'province':d['province'],'data_year':d['data_year'],'month':d['month'],'validation_result_id':info['validation_result_id']}
    def internal(e):return sql('SELECT gis.geotiff_prepare_read('+literal(demo.users['admin']['id'])+'::uuid,'+literal(e['id'])+'::uuid)')
    try:
        check('queue_idle',sql("SELECT to_jsonb(count(*)=0) FROM gis.jobs WHERE state IN ('queued','running')"))
        year=sql("SELECT to_jsonb(y) FROM generate_series(1980,2027)y WHERE NOT EXISTS(SELECT 1 FROM gis.datasets WHERE province='Bangkok Metropolis' AND data_year=y AND month=0) ORDER BY y DESC LIMIT1".replace('LIMIT1','LIMIT 1'))
        directory,manifest=fixtures(local,out,year)
        demo.accounts(secrets.token_urlsafe(24));demo.start(launchers=(lambda:demo_module.p.GeoTiffContainer(local),lambda:a4.prepare_container(local)))
        demo.grant_officer()
        for role,u in demo.users.items():tokens[role]=local.client(demo.anon).auth.sign_in_with_password({'email':u['email'],'password':u['password']}).session.access_token
        check('officer_prepare_enabled',ok('GET','/me')['geotiff_prepare_enabled'])
        ndvi,lst=dataset('ndvi'),dataset('lst');n=upload(ndvi,'ndvi_ready');c=upload(lst,'lst_celsius_ready');k=upload(lst,'lst_kelvin_ready')
        base='/editions/'+c['id'];body=payload(lst,c)
        check('normal_enqueue_denied',req('POST',base+'/geotiff-prepare-jobs',body,role='normal').status_code==403)
        check('normal_preview_denied',req('GET',base+'/geotiff-prepared',role='normal').status_code==403)
        check('anonymous_preview_denied',http.get('http://127.0.0.1:55422/gis'+base+'/geotiff-prepared').status_code==401)
        for field,value in [('expected_dataset_revision',99),('expected_input_revision',99),('input_hash','0'*64),('validation_result_id',str(uuid4())),('province','Chiang Mai'),('data_year',year-1),('month',1)]:
            check('stale_'+field,req('POST',base+'/geotiff-prepare-jobs',{**body,field:value}).status_code==409)
        for field in ('path','url','actor','proof'):
            check('payload_'+field+'_rejected',req('POST',base+'/geotiff-prepare-jobs',{**body,field:'untrusted'}).status_code==422)
        key=str(uuid4());j=ok('POST',base+'/geotiff-prepare-jobs',body,key=key)
        check('idempotent_same_job',ok('POST',base+'/geotiff-prepare-jobs',body,key=key)['id']==j['id'])
        check('actual_celsius_prepare_worker',wait(j['id'])['state']=='succeeded')
        info=ok('GET',base+'/geotiff-prepared');check('worker_cannot_self_certify',info['prepared'] and not info['ready_for_review'])
        check('client_proof_rejected',req('POST',base+'/geotiff-prepare-verification',{'job_id':j['id'],'proof':{}}).status_code==422)
        verified=ok('POST',base+'/geotiff-prepare-verification',{'job_id':j['id']})
        check('trusted_celsius_immutable_artifacts',verified['ready_for_review'] and verified['summary']['statistics']['mean']==20 and verified['ready_for_publication'] is False)
        check('admin_can_inspect',ok('GET',base+'/geotiff-prepared',role='admin')['ready_for_review'])
        kb='/editions/'+k['id'];kj=ok('POST',kb+'/geotiff-prepare-jobs',payload(lst,k));check('actual_kelvin_prepare_worker',wait(kj['id'])['state']=='succeeded')
        kv=ok('POST',kb+'/geotiff-prepare-verification',{'job_id':kj['id']});meta=kv['summary']['metadata'];stats=kv['summary']['statistics']
        check('kelvin_converted_once_zero_C_valid',kv['ready_for_review'] and meta['kelvin_to_celsius_count']==1 and abs(stats['min'])<1e-12 and abs(stats['mean']-20)<1e-12 and meta['nodata']==-9999 and stats['valid_pixels']==3)
        check('coverage_period_limitations',not meta['period_verified'] and not meta['complete_province_inventory'] and meta['boundary_approximate'] and meta['intersection_fraction_of_footprint']>0)
        # Browser enqueues and verifies NDVI through actual confirmation/API/queue.
        env={**demo.env,'GIS_TEST_NODE_MODULES':str(node_modules)};payload_browser={'users':demo.users,'output':str(out),'dataset':ndvi,'edition':n}
        p=subprocess.Popen([shutil.which('node'),str(REPO/'dev/gis_ui/a4_smoke.cjs')],cwd=REPO,env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,encoding='utf-8')
        stdout,_=p.communicate(json.dumps(payload_browser)+'\n',timeout=600);demo.smoke_exit=p.returncode;print(stdout,flush=True);check('browser_prepare_verify_preview',p.returncode==0)
        # Fault only a new run-owned immutable prepared object, keeping originals.
        state=internal(k);kind='lst_raster';path=local.geotiff_prepared_store.object_path(kind,state['candidate']['artifacts'][kind]);held=path.with_name(path.name+'.held-'+demo.run)
        if held.exists():raise RuntimeError('FAULT_TARGET_REJECTED')
        path.rename(held)
        with path.open('xb') as f:f.write(b'corrupt')
        bad=ok('GET',kb+'/geotiff-prepared');check('corrupt_object_revokes_preview',not bad['ready_for_review'] and 'summary' not in bad)
        path.rename(path.with_name(path.name+'.corrupt-'+demo.run));held.rename(path)
        check('revocation_durable_after_restore',not ok('GET',kb+'/geotiff-prepared')['ready_for_review'])
        original=local.geotiff_store.objects/(c['upload']['sha256']+'.tif');saved=original.with_name(original.name+'.held-'+demo.run);original.rename(saved)
        check('missing_source_revokes_preview',not ok('GET',base+'/geotiff-prepared')['ready_for_review']);saved.rename(original)
        check('all_geotiff_editions_draft_ineligible_no_active',sql('SELECT to_jsonb(bool_and(e.state=\'draft\' AND e.validated_result_id IS NULL AND NOT gis.eligible(e.id,d.id) AND NOT gis.publication_ready(e.id,d.id) AND d.active_edition_id IS NULL)) FROM gis.editions e JOIN gis.datasets d ON d.id=e.dataset_id WHERE d.id IN ('+literal(ndvi['id'])+'::uuid,'+literal(lst['id'])+'::uuid)'))
        check('no_geo_publication_or_broad_gate',sql('SELECT to_jsonb(NOT activation_enabled) FROM gis.environment'))
        # Record run-owned fixtures for targeted lifecycle checks without storing Auth.
        (out/'targets.json').write_text(json.dumps({'ndvi':ndvi,'lst':lst,'editions':{'ndvi':n,'celsius':c,'kelvin':k},'year':year,'manifest':manifest},indent=2),encoding='utf-8')
    except Exception as error:
        rows.append({'name':'execution','status':'Fail','diagnostic':str(error)[:240]});print(json.dumps(rows[-1]),flush=True)
    finally:
        http.close();clean=demo.close();final=source()
        (out/'results.json').write_text(json.dumps({'rows':rows,'source':initial,'source_unchanged':initial==final,'cleanup':clean,'synthetic_only':True},indent=2),encoding='utf-8')
    return 0 if clean and initial==final and rows and all(x['status']=='Pass' for x in rows) else 1
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--runtime-dir',type=Path,required=True);p.add_argument('--node-modules',type=Path,required=True)
    args=p.parse_args();raise SystemExit(run(args.runtime_dir,args.node_modules))
