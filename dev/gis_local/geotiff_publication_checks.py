"""A4.2 actual Local API/Auth/SQL/Linux/files/browser; synthetic run-owned data."""
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
import tempfile
import time
from uuid import uuid4
import zipfile
HERE=Path(__file__).resolve().parent;REPO=HERE.parents[1]
def load(name,path):
    s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);sys.modules[name]=m;s.loader.exec_module(m);return m
a42=load('a42_checks_operator',HERE/'geotiff_publication_local.py');m=a42.m
a41checks=load('a42_existing_checks',HERE/'geotiff_prepare_checks.py');demo_module=a41checks.demo_module;demo_module.local_target=lambda root:a42.GeoTiffPublicationLocal(root)
def source():return a41checks.source()

def fixtures(local,out,year):
    directory=out/'fixtures';directory.mkdir()
    code="""import sys,importlib.util,json,hashlib;from pathlib import Path
sys.path.insert(0,'/work');s=importlib.util.spec_from_file_location('fixture','/work/tests/test_geotiff_prepare_native.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
out=Path('/out');rows={}
for name,profile,values,month in [('A','ndvi_ready',[[-1,0],[1,-9999]],0),('B','ndvi_ready',[[0,.25],[.5,-9999]],0),('C','ndvi_ready',[[.25,.5],[.75,-9999]],0),('D','ndvi_ready',[[.5,.75],[1,-9999]],0),('Celsius','lst_celsius_ready',None,0),('Kelvin','lst_kelvin_ready',None,0),('Monthly','ndvi_ready',None,5)]:
 tags={'GIS_PROFILE':profile,'GIS_PROVINCE':'Bangkok Metropolis','GIS_YEAR':'__YEAR__','GIS_MONTH':str(month),'GIS_VARIANT':name}
 packet,root,_=m.fixture(out,profile,values=values,tags=tags,month=month);raw=next(root.iterdir()).read_bytes();(out/(name+'.tif')).write_bytes(raw);rows[name]={'sha256':hashlib.sha256(raw).hexdigest(),'profile':profile,'month':month}
(out/'manifest.json').write_text(json.dumps(rows))
""".replace('__YEAR__',str(year))
    args=['run','--rm','--entrypoint','','--network=none','--memory=1g','--memory-swap=1g','--cpus=1','--pids-limit=64','--read-only','--cap-drop=ALL','--security-opt=no-new-privileges:true','--user=65534:65534','--tmpfs=/tmp:rw,nosuid,noexec,size=32m,mode=1777',
        '--mount','type=bind,src='+str(REPO/'green-area-backend/gis_worker')+',dst=/work/gis_worker,readonly','--mount','type=bind,src='+str(REPO/'green-area-backend/tests')+',dst=/work/tests,readonly',
        '--mount','type=bind,src='+str(directory)+',dst=/out',m.IMAGE,'python3','-I','-B','-c',code]
    local.db.runtime.docker(args,quiet=True,timeout=90);return directory,json.loads((directory/'manifest.json').read_text())

def run(root,node_modules,resume_run=None,skip_browser=False):
    import httpx
    logging.disable(logging.CRITICAL);demo=demo_module.Demo(root);local=demo.local;out=local.output/('integration-'+demo.run);out.mkdir();initial=source();rows=[];tokens={};faults=[]
    literal=m.t2.t1.literal;http=httpx.Client(trust_env=False,follow_redirects=False,timeout=180)
    def check(name,value):
        rows.append({'name':name,'status':'Pass' if value else 'Fail'});print(json.dumps(rows[-1]),flush=True)
        if not value:raise AssertionError(name)
    def sql(body):return local.sql(body,read_only=True)
    def state(jid):return sql('SELECT to_jsonb(j) FROM gis.jobs j WHERE id='+literal(jid)+'::uuid')
    def wait(jid):
        end=time.monotonic()+150
        while time.monotonic()<end:
            j=state(jid)
            if j['state'] in ('succeeded','failed'):return j
            time.sleep(.3)
        raise RuntimeError('JOB_TIMEOUT')
    def req(method,path,body=None,role='admin',key=None,**kw):
        h={'Authorization':'Bearer '+tokens[role],'Idempotency-Key':key or str(uuid4()),**kw.pop('headers',{})}
        return http.request(method,'http://127.0.0.1:55422/gis'+path,headers=h,json=body,**kw)
    def ok(method,path,body=None,**kw):
        r=req(method,path,body,**kw)
        if r.status_code not in (200,201,202):raise RuntimeError('HTTP_'+str(r.status_code)+'_'+str(r.json().get('detail',{}).get('code','UNKNOWN'))+'_'+path.split('/')[-1])
        return r.json()
    def dataset(d):return ok('GET','/datasets/'+d['id'])
    def pubquery(d):return {'province':d['province'],'data_year':d['data_year'],'month':d['month'],'product':d['purpose'],'coverage_mode':'source_footprint_intersection'}
    def read(d,**kw):return req('GET','/published-geotiff',params=pubquery(d),role='normal',**kw)
    def payload(d,e):
        latest=dataset(d);status=ok('GET','/editions/'+e['id']+'/geotiff-publication')
        return {'edition_id':e['id'],'expected_dataset_revision':latest['revision'],'expected_active_edition_id':latest['active_edition_id'],
            'expected_input_revision':e['input_revision'],'input_hash':e['input_hash'],'validation_result_id':status['validation_result_id'],'certificate_id':status['certificate_id'],
            'source_sha256':e['upload']['sha256'],'province':d['province'],'data_year':d['data_year'],'month':d['month'],'product':d['purpose'],'profile':e['manifest']['profile'],
            'method_version':'geotiff-grid-celsius-v1','coverage_mode':'source_footprint_intersection','policy_version':'local-declared-period-footprint-v1',
            'acknowledge_unverified_period':True,'acknowledge_limited_coverage':True,'reason':'A4.2 synthetic Local acceptance '+demo.run}
    def command(d,e,op,**kw):return ok('POST','/datasets/'+d['id']+'/geotiff-publication/'+op,payload(d,e)|kw.pop('extra',{}),**kw)
    def make(d,name):
        f=manifest[name];raw=(directory/(name+'.tif')).read_bytes();check('fixture_sha_'+name,hashlib.sha256(raw).hexdigest()==f['sha256'])
        ok('POST','/datasets/'+d['id']+'/geotiff-uploads',content=raw,headers={'Content-Type':'image/tiff'},params={'expected_revision':dataset(d)['revision'],'crs':'EPSG:4326','profile':f['profile']})
        e=next(e for e in ok('GET','/datasets/'+d['id']+'/editions',params={'limit':100})['data'] if e.get('upload',{}).get('sha256')==f['sha256'])
        j=ok('POST','/editions/'+e['id']+'/validation-jobs',{'expected_revision':e['input_revision']});check('native_validation_'+name,wait(j['id'])['state']=='succeeded')
        e=ok('GET','/editions/'+e['id']);p=payload(d,e)
        # Current native result exists before a preparation certificate.
        native=ok('GET','/editions/'+e['id']+'/geotiff-prepared')
        prep={k:p[k] for k in ('expected_dataset_revision','expected_input_revision','input_hash','province','data_year','month')};prep['validation_result_id']=native['validation_result_id']
        j=ok('POST','/editions/'+e['id']+'/geotiff-prepare-jobs',prep);check('real_prepare_'+name,wait(j['id'])['state']=='succeeded')
        verified=ok('POST','/editions/'+e['id']+'/geotiff-prepare-verification',{'job_id':j['id']});check('a41_preview_contract_'+name,verified['ready_for_review'] and verified['ready_for_publication'] is False)
        return e
    def fault(path,kind):
        held=path.with_name(path.name+'.held-a42-'+demo.run)
        if held.exists():raise RuntimeError('FAULT_SCOPE_REJECTED')
        path.rename(held);faults.append((path,held))
        if kind=='corrupt':
            with path.open('xb') as f:f.write(b'corrupt-a42')
    def restore():
        for path,held in reversed(faults):
            if path.exists():path.rename(path.with_name(path.name+'.corrupt-a42-'+demo.run))
            held.rename(path)
        faults.clear()
    def raster_path(e):
        info=sql('SELECT gis.geotiff_prepare_read('+literal(demo.users['admin']['id'])+'::uuid,'+literal(e['id'])+'::uuid)')
        return local.geotiff_prepared_store.object_path('ndvi_raster',info['candidate']['artifacts']['ndvi_raster'])
    try:
        check('queue_idle',sql("SELECT to_jsonb(count(*)=0) FROM gis.jobs WHERE state IN ('queued','running')"))
        if resume_run is not None:
            import re
            if not re.fullmatch('[a-f0-9]{10}',resume_run):raise RuntimeError('RESUME_SCOPE_REJECTED')
            prior=sql('SELECT jsonb_agg(to_jsonb(d)) FROM gis.datasets d WHERE title LIKE '+literal('A4.2 Synthetic % '+resume_run))
            if len(prior or [])!=3:raise RuntimeError('RESUME_REQUIRES_THREE_OWNED_DATASETS')
            year=prior[0]['data_year']
        else:year=sql("SELECT to_jsonb(y) FROM generate_series(1980,2027)y WHERE NOT EXISTS(SELECT 1 FROM gis.datasets WHERE province='Bangkok Metropolis' AND data_year=y AND kind='geotiff' AND month=0) ORDER BY y DESC LIMIT 1")
        directory,manifest=fixtures(local,out,year);demo.accounts(secrets.token_urlsafe(24))
        demo.start(launchers=(lambda:demo_module.p.GeoTiffContainer(local),lambda:a42.a41.prepare_container(local)));demo.grant_officer()
        for role,u in demo.users.items():tokens[role]=local.client(demo.anon).auth.sign_in_with_password({'email':u['email'],'password':u['password']}).session.access_token
        check('private_geo_gate_broad_closed',ok('GET','/me')['geotiff_publication_enabled'] and not ok('GET','/me')['activation_enabled'])
        def create(metric,month=0):return ok('POST','/datasets',{'province':'Bangkok Metropolis','data_year':year,'month':month,'kind':'geotiff','purpose':metric,'title':'A4.2 Synthetic '+metric+str(month)+' '+demo.run})
        if resume_run is None:
            ndvi,lst,monthly=create('ndvi'),create('lst'),create('ndvi',5)
            editions={name:make(ndvi if name in ('A','B','C','D') else monthly if name=='Monthly' else lst,name) for name in manifest}
        else:
            ndvi=next(d for d in prior if d['purpose']=='ndvi' and d['month']==0);lst=next(d for d in prior if d['purpose']=='lst');monthly=next(d for d in prior if d['month']==5)
            oldmanifest=json.loads((local.output/('integration-'+resume_run)/'fixtures/manifest.json').read_text());editions={}
            for name in ('A','B','C','D','Celsius','Kelvin'):
                d=ndvi if name in ('A','B','C','D') else lst
                e=next(e for e in ok('GET','/datasets/'+d['id']+'/editions',params={'limit':100})['data'] if e.get('upload',{}).get('sha256')==oldmanifest[name]['sha256'])
                v=ok('GET','/editions/'+e['id']+'/geotiff-prepared')
                check('reuse_verified_or_expected_revoked_'+name,(v['ready_for_review'] or (skip_browser and name=='D')) and v['ready_for_publication'] is False)
                editions[name]=e
            editions['Monthly']=make(monthly,'Monthly')
            (out/'tested-fixture-manifest.json').write_text(json.dumps({'reused_source_run':resume_run,'annual':{k:oldmanifest[k] for k in editions if k!='Monthly'},'monthly':manifest['Monthly']},indent=2),encoding='utf-8')
        expected_pointers={d['id']:d['active_edition_id'] for d in (ndvi,lst,monthly)}
        check('no_auto_activation',all(dataset(d)['active_edition_id']==expected_pointers[d['id']] for d in (ndvi,lst,monthly)))
        body=payload(ndvi,editions['A']);route='/datasets/'+ndvi['id']+'/geotiff-publication/activation'
        for role in ('normal','officer'):check(role+'_activation_denied',req('POST',route,body,role=role).status_code==403)
        check('anonymous_reader_denied',http.get('http://127.0.0.1:55422/gis/published-geotiff',params=pubquery(ndvi)).status_code==401)
        check('officer_can_inspect',ok('GET','/editions/'+editions['A']['id']+'/geotiff-publication',role='officer')['catalog_prepared'])
        for field in ('acknowledge_unverified_period','acknowledge_limited_coverage'):check('explicit_'+field,req('POST',route,body|{field:False}).status_code==422)
        for field,value in [('expected_dataset_revision',99),('expected_active_edition_id',str(uuid4())),('input_hash','0'*64),('month',1),('product','lst'),('profile','lst_kelvin_ready')]:
            check('reject_'+field,req('POST',route,body|{field:value}).status_code==409)
        check('failed_cas_preserves_pointer',dataset(ndvi)['active_edition_id']==expected_pointers[ndvi['id']])
        if dataset(lst)['active_edition_id']!=editions['Celsius']['id']:command(lst,editions['Celsius'],'activation')
        c=read(lst).json();check('celsius_active_actual_statistics',c['summary']['statistics']['mean']==20 and c['summary']['metadata']['kelvin_to_celsius_count']==0)
        if dataset(lst)['active_edition_id']!=editions['Kelvin']['id']:command(lst,editions['Kelvin'],'activation')
        k=read(lst).json();check('kelvin_active_correct_celsius_once',k['summary']['statistics']['mean']==20 and k['summary']['statistics']['min']==0 and k['summary']['metadata']['kelvin_to_celsius_count']==1 and k['legend']['units']=='celsius')
        if not skip_browser:
            if dataset(ndvi)['active_edition_id']==editions['D']['id']:command(ndvi,editions['A'],'activation')
            # Browser explicitly activates D and loads NDVI/LST from real API bytes.
            with tempfile.TemporaryFile() as output:
                env={**demo.env,'GIS_TEST_NODE_MODULES':str(node_modules)}
                proc=subprocess.Popen([shutil.which('node'),str(REPO/'dev/gis_ui/a42_smoke.cjs')],cwd=REPO,env=env,stdin=subprocess.PIPE,stdout=output,stderr=subprocess.DEVNULL)
                proc.stdin.write((json.dumps({'users':demo.users,'dataset':ndvi,'edition':editions['D'],'kelvin':editions['Kelvin'],'output':str(out)})+'\n').encode());proc.stdin.close()
                end=time.monotonic()+600
                while not (out/'browser-awaiting-fault').exists() and proc.poll() is None and time.monotonic()<end:time.sleep(.3)
                if not (out/'browser-awaiting-fault').exists():
                    if proc.poll() is None:proc.kill()
                    proc.wait();raise RuntimeError('BROWSER_BEFORE_FAULT_FAILED')
                fault(raster_path(editions['D']),'corrupt');(out/'browser-fault-injected').write_text('ready')
                proc.wait(timeout=180);output.seek(0);raw=output.read(65536);print(raw.decode(),flush=True);demo.smoke_exit=proc.returncode
                check('real_browser_activation_dashboard_corruption',proc.returncode==0)
            restore();check('browser_revocation_durable',not ok('GET','/editions/'+editions['D']['id']+'/geotiff-publication')['catalog_prepared'])
        else:
            status=ok('GET','/editions/'+editions['D']['id']+'/geotiff-publication')
            if status['catalog_prepared']:
                fault(raster_path(editions['D']),'corrupt');check('core_corrupt_active_unservable',read(ndvi).status_code==409);restore()
            check('core_active_revocation_durable',not ok('GET','/editions/'+editions['D']['id']+'/geotiff-publication')['catalog_prepared'])
        command(ndvi,editions['D'],'withdrawal',extra={'replacement_edition_id':None});check('withdraw_revoked_active_to_null',dataset(ndvi)['active_edition_id'] is None)
        key=str(uuid4());pa=payload(ndvi,editions['A']);ok('POST',route,pa,key=key);a=read(ndvi).json();check('ndvi_A_actual_raster_summary',a['summary']['statistics']['mean']==0 and a['source_identity']['edition_id']==editions['A']['id'])
        command(ndvi,editions['B'],'activation');b=read(ndvi).json();check('replace_A_with_B_without_withdrawing_A',b['summary']['statistics']['mean']==.25 and ok('GET','/editions/'+editions['A']['id'])['state']=='draft')
        replay=ok('POST',route,pa,key=key);check('historical_idempotency_replay_no_pointer_rewrite',replay['replayed'] and dataset(ndvi)['active_edition_id']==editions['B']['id'])
        command(ndvi,editions['A'],'rollback');check('rollback_A_fresh_verified',read(ndvi).json()['source_identity']['edition_id']==editions['A']['id'])
        pb,pc=payload(ndvi,editions['B']),payload(ndvi,editions['C']);rev=dataset(ndvi)['revision']
        with ThreadPoolExecutor(max_workers=2) as pool:responses=list(pool.map(lambda p:req('POST',route,p),(pb,pc)))
        outcomes=[{'status':r.status_code,'code':r.json().get('detail',{}).get('code')} for r in responses]
        rows.append({'name':'concurrent_response_diagnostics','status':'Pass','outcomes':outcomes});print(json.dumps(rows[-1]),flush=True)
        check('concurrent_activation_exactly_one_commit',sum(r.status_code==200 for r in responses)==1 and all(r.status_code in (200,409,429,503) for r in responses) and dataset(ndvi)['revision']==rev+1)
        for p,r in zip((pb,pc),responses):
            if r.status_code in (429,503):check('transient_concurrent_retry_rejects_stale_revision',req('POST',route,p).status_code==409)

        active=dataset(ndvi)['active_edition_id'];winner=next(e for e in (editions['B'],editions['C']) if e['id']==active);loser=next(e for e in (editions['B'],editions['C']) if e['id']!=active)
        command(ndvi,editions['A'],'withdrawal',extra={'replacement_edition_id':None});check('inactive_withdrawal_preserves_other_active',dataset(ndvi)['active_edition_id']==active)
        check('withdrawn_terminal_rollback_rejected',req('POST','/datasets/'+ndvi['id']+'/geotiff-publication/rollback',payload(ndvi,editions['A'])).status_code==409)
        fault(raster_path(loser),'corrupt');check('corrupt_before_activation_rejected',req('POST',route,payload(ndvi,loser)).status_code==409 and dataset(ndvi)['active_edition_id']==active);restore()
        warm=read(ndvi).json();fault(raster_path(winner),'corrupt');bad=read(ndvi);check('cache_hit_never_serves_corrupt_active',bad.status_code==409 and 'raster' not in bad.json());restore()
        command(ndvi,winner,'withdrawal',extra={'replacement_edition_id':loser['id']});check('revoked_active_withdrawal_to_fresh_replacement',dataset(ndvi)['active_edition_id']==loser['id'] and read(ndvi).json()['source_identity']['edition_id']==loser['id'])
        src=local.geotiff_store.objects/(loser['upload']['sha256']+'.tif');fault(src,'missing');check('missing_original_after_active_no_stale_cache',read(ndvi).status_code==409);restore()
        command(ndvi,loser,'withdrawal',extra={'replacement_edition_id':None});check('withdraw_missing_source_to_null_no_fallback',dataset(ndvi)['active_edition_id'] is None and read(ndvi).status_code==404)
        command(monthly,editions['Monthly'],'activation');month_result=read(monthly).json();check('matching_month_explicit_and_unverified',month_result['source_identity']['month']==5 and month_result['period_verified'] is False)
        for extra in ({'month':1},{'data_year':year-1},{'province':'Chiang Mai'},{'product':'lst'}):check('no_scope_fallback_'+next(iter(extra)),req('GET','/published-geotiff',params=pubquery(monthly)|extra,role='normal').status_code==404)
        for extra in ({'district':'BangRak'},{'bbox':'1,2,3,4'},{'coverage_mode':'whole_province'}):check('unsupported_partial_request_'+next(iter(extra)),req('GET','/published-geotiff',params=pubquery(monthly)|extra,role='normal').status_code==422)
        # Preserve old Generic GIS gate even after new GeoTIFF acceptance exists.
        gate=req('POST','/datasets/'+monthly['id']+'/activation',{'edition_id':editions['Monthly']['id'],'expected_revision':dataset(monthly)['revision']})
        check('generic_activation_gate_not_opened',gate.status_code in (403,409,422,503) and sql('SELECT to_jsonb(NOT activation_enabled) FROM gis.environment'))
        for w in list(demo.workers):w.close();demo.workers.remove(w)
        # Actual LDD A1–A3 regression on one new run-owned catalog.
        ld=ok('POST','/datasets',{'province':'Bangkok Metropolis','data_year':sql("SELECT to_jsonb(y) FROM generate_series(1980,2027)y WHERE NOT EXISTS(SELECT 1 FROM gis.datasets WHERE province='Bangkok Metropolis' AND data_year=y AND kind='ldd_shapefile') ORDER BY y LIMIT 1"),'month':0,'kind':'ldd_shapefile','purpose':'landuse','title':'A42 LDD regression '+demo.run})
        demo.workers=[demo_module.p.p.m.LddContainer(local),a42.a41.a3.a2.PrepareContainer(local)]
        for w in demo.workers:m.wait_for(lambda:w.has('ready') or w.has('fatal'),30)
        raw=io.BytesIO((REPO/'green-area-backend/gis_worker/fixtures/ldd_valid.zip').read_bytes())
        with zipfile.ZipFile(raw,'a') as z:z.comment=('A42 '+demo.run).encode()
        ok('POST','/datasets/'+ld['id']+'/ldd-uploads',content=raw.getvalue(),headers={'Content-Type':'application/zip'},params={'expected_revision':1,'crs':'EPSG:32647','encoding':'auto'})
        le=ok('GET','/datasets/'+ld['id']+'/editions',params={'limit':100})['data'][0];j=ok('POST','/editions/'+le['id']+'/validation-jobs',{'expected_revision':1});check('ldd_native_regression',wait(j['id'])['state']=='succeeded');le=ok('GET','/editions/'+le['id'])
        j=ok('POST','/editions/'+le['id']+'/prepare-jobs',{'expected_dataset_revision':1,'expected_input_revision':1,'input_hash':le['input_hash'],'province':ld['province'],'data_year':ld['data_year']});check('ldd_prepare_regression',wait(j['id'])['state']=='succeeded')
        check('ldd_verify_regression',ok('POST','/editions/'+le['id']+'/prepare-verification',{'job_id':j['id']})['ready_for_publication'])
        lp={'edition_id':le['id'],'expected_dataset_revision':1,'expected_active_edition_id':None,'expected_input_revision':1,'input_hash':le['input_hash'],'validation_result_id':le['validated_result_id'],'source_sha256':le['upload']['sha256'],'province':ld['province'],'data_year':ld['data_year'],'method_version':'ldd-source-area-v1','coverage_mode':'validated_source_footprint','reason':'A42 LDD preservation regression'}
        ok('POST','/datasets/'+ld['id']+'/ldd-publication/activation',lp);check('ldd_activation_reader_preserved',ok('GET','/published-ldd',params={'province':ld['province'],'data_year':ld['data_year']},role='normal')['summary']['total_area_m2']==6400)
        ok('POST','/datasets/'+ld['id']+'/ldd-publication/withdrawal',lp|{'expected_dataset_revision':2,'expected_active_edition_id':le['id'],'replacement_edition_id':None});check('ldd_withdrawal_preserved',dataset(ld)['active_edition_id'] is None)
        command(monthly,editions['Monthly'],'withdrawal',extra={'replacement_edition_id':None});command(lst,editions['Kelvin'],'withdrawal',extra={'replacement_edition_id':None})
        check('queue_idle_after_tests',sql("SELECT to_jsonb(count(*)=0) FROM gis.jobs WHERE state IN ('queued','running')"))
        (out/'targets.json').write_text(json.dumps({'ndvi':ndvi,'lst':lst,'monthly':monthly,'editions':editions,'year':year},indent=2),encoding='utf-8')
    except Exception as error:
        rows.append({'name':'execution','status':'Fail','diagnostic':str(error)[:220]});print(json.dumps(rows[-1]),flush=True)
    finally:
        restore();http.close();clean=demo.close();final=source()
        (out/'results.json').write_text(json.dumps({'rows':rows,'source':initial,'source_unchanged':initial==final,'cleanup':clean,'synthetic_only':True,'browser_included':not skip_browser},indent=2),encoding='utf-8')
    return 0 if clean and initial==final and rows and all(r['status']=='Pass' for r in rows) else 1

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--runtime-dir',type=Path,required=True);p.add_argument('--node-modules',type=Path,required=True);p.add_argument('--resume-run');p.add_argument('--skip-browser',action='store_true')
    args=p.parse_args();raise SystemExit(run(args.runtime_dir,args.node_modules,args.resume_run,args.skip_browser))
