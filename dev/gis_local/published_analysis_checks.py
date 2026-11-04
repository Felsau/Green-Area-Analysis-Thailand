"""A5 actual Local UI/provider integration; only fresh synthetic test catalogs."""
import argparse
import hashlib
import importlib.util
import io
import json
import logging
import re
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
s=importlib.util.spec_from_file_location('a5_existing_a42',HERE/'geotiff_publication_checks.py')
c=importlib.util.module_from_spec(s);sys.modules[s.name]=c;s.loader.exec_module(c)

def source():
    result=c.source()
    for path in (Path(__file__),REPO/'dev/gis_ui/a5_smoke.cjs'):
        result['files'][path.relative_to(REPO).as_posix()]=hashlib.sha256(path.read_bytes()).hexdigest()
    result['sha256']=hashlib.sha256(json.dumps(result['files'],sort_keys=True).encode()).hexdigest()
    return result

def run(root,node_modules):
    import httpx
    logging.disable(logging.CRITICAL);demo=c.demo_module.Demo(root);local=demo.local
    out=root/'a5-published-analysis'/('integration-'+demo.run);out.mkdir(parents=True)
    initial=source();rows=[];tokens={};faults=[];proc=None
    http=httpx.Client(trust_env=False,follow_redirects=False,timeout=180);literal=c.m.t2.t1.literal
    def check(name,value):
        rows.append({'name':name,'status':'Pass' if value else 'Fail'});print(json.dumps(rows[-1]),flush=True)
        if not value:raise AssertionError(name)
    def sql(q):return local.sql(q,read_only=True)
    def req(method,path,body=None,**kw):
        headers={'Authorization':'Bearer '+tokens['admin'],'Idempotency-Key':str(uuid4()),**kw.pop('headers',{})}
        response=http.request(method,'http://127.0.0.1:55422/gis'+path,json=body,headers=headers,**kw)
        if response.status_code not in (200,201,202):
            raise RuntimeError('HTTP_'+str(response.status_code)+'_'+str(response.json().get('detail',{}).get('code','UNKNOWN')))
        return response.json()
    def wait_job(job):
        end=time.monotonic()+150
        while time.monotonic()<end:
            row=sql('SELECT to_jsonb(j) FROM gis.jobs j WHERE id='+literal(job['id'])+'::uuid')
            if row['state'] in ('succeeded','failed'):return row['state']=='succeeded'
            time.sleep(.3)
        return False
    def stop_workers():
        for worker in list(demo.workers):worker.close();demo.workers.remove(worker)
    def ldd_edition(dataset,tag):
        raw=io.BytesIO((REPO/'green-area-backend/gis_worker/fixtures/ldd_valid.zip').read_bytes())
        with zipfile.ZipFile(raw,'a') as archive:archive.comment=('A5:'+demo.run+':'+tag).encode()
        raw=raw.getvalue();req('POST','/datasets/'+dataset['id']+'/ldd-uploads',content=raw,
            headers={'Content-Type':'application/zip'},params={'expected_revision':dataset['revision'],'crs':'EPSG:32647','encoding':'auto'})
        edition=next(e for e in req('GET','/datasets/'+dataset['id']+'/editions',params={'limit':100})['data'] if e.get('upload',{}).get('sha256')==hashlib.sha256(raw).hexdigest())
        check('real_ldd_validation_'+tag,wait_job(req('POST','/editions/'+edition['id']+'/validation-jobs',{'expected_revision':edition['input_revision']})))
        edition=req('GET','/editions/'+edition['id'])
        job=req('POST','/editions/'+edition['id']+'/prepare-jobs',{'expected_dataset_revision':dataset['revision'],'expected_input_revision':edition['input_revision'],
            'input_hash':edition['input_hash'],'province':dataset['province'],'data_year':dataset['data_year']})
        check('real_ldd_preparation_'+tag,wait_job(job));verified=req('POST','/editions/'+edition['id']+'/prepare-verification',{'job_id':job['id']})
        check('real_ldd_verification_'+tag,verified['ready_for_publication'] and verified['summary']['total_area_m2']==6400)
        return req('GET','/editions/'+edition['id'])
    try:
        check('queue_idle_before',sql("SELECT to_jsonb(count(*)=0) FROM gis.jobs WHERE state IN ('queued','running')"))
        demo.accounts(secrets.token_urlsafe(24));demo.start(launchers=(lambda:c.demo_module.p.p.m.LddContainer(local),lambda:c.a42.a41.a3.a2.PrepareContainer(local)))
        for role,user in demo.users.items():tokens[role]=local.client(demo.anon).auth.sign_in_with_password({'email':user['email'],'password':user['password']}).session.access_token
        year=sql("SELECT to_jsonb(y) FROM generate_series(1980,2027)y WHERE NOT EXISTS(SELECT 1 FROM gis.datasets WHERE province='Bangkok Metropolis' AND data_year=y AND kind='ldd_shapefile') ORDER BY y LIMIT 1")
        ldd=req('POST','/datasets',{'province':'Bangkok Metropolis','data_year':year,'month':0,'kind':'ldd_shapefile','purpose':'landuse','title':'A5 Synthetic LDD '+demo.run})
        a,b=ldd_edition(ldd,'A'),ldd_edition(ldd,'B');stop_workers()
        gy=sql("SELECT to_jsonb(y) FROM generate_series(1980,2027)y WHERE NOT EXISTS(SELECT 1 FROM gis.datasets WHERE province='Bangkok Metropolis' AND data_year=y AND kind='geotiff' AND purpose='ndvi' AND month=0) ORDER BY y DESC LIMIT 1")
        directory,manifest=c.fixtures(local,out,gy)
        geo=req('POST','/datasets',{'province':'Bangkok Metropolis','data_year':gy,'month':0,'kind':'geotiff','purpose':'ndvi','title':'A5 Synthetic GeoTIFF '+demo.run})
        demo.workers=[c.demo_module.p.GeoTiffContainer(local),c.a42.a41.prepare_container(local)]
        for worker in demo.workers:c.m.wait_for(lambda:worker.has('ready') or worker.has('fatal'),30)
        raw=(directory/'D.tif').read_bytes();check('synthetic_geotiff_source_sha',hashlib.sha256(raw).hexdigest()==manifest['D']['sha256'])
        req('POST','/datasets/'+geo['id']+'/geotiff-uploads',content=raw,headers={'Content-Type':'image/tiff'},params={'expected_revision':geo['revision'],'crs':'EPSG:4326','profile':'ndvi_ready'})
        ge=next(e for e in req('GET','/datasets/'+geo['id']+'/editions',params={'limit':100})['data'] if e.get('upload',{}).get('sha256')==manifest['D']['sha256'])
        check('real_geotiff_validation',wait_job(req('POST','/editions/'+ge['id']+'/validation-jobs',{'expected_revision':ge['input_revision']})))
        native=req('GET','/editions/'+ge['id']+'/geotiff-prepared')
        job=req('POST','/editions/'+ge['id']+'/geotiff-prepare-jobs',{'expected_dataset_revision':geo['revision'],'expected_input_revision':ge['input_revision'],
            'input_hash':ge['input_hash'],'province':geo['province'],'data_year':gy,'month':0,'validation_result_id':native['validation_result_id']})
        check('real_geotiff_preparation',wait_job(job));verified=req('POST','/editions/'+ge['id']+'/geotiff-prepare-verification',{'job_id':job['id']})
        check('real_geotiff_verification_no_auto_activate',verified['ready_for_review'] and not verified['ready_for_publication'] and req('GET','/datasets/'+geo['id'])['active_edition_id'] is None)
        stop_workers()
        (out/'targets.json').write_text(json.dumps({'ldd':ldd,'a':a,'b':b,'geo':geo,'ge':ge},indent=2),encoding='utf-8')
        # Credentials stay in a private stdin pipe, never flags/env/files/logs.
        with tempfile.TemporaryFile() as output:
            proc=subprocess.Popen([shutil.which('node'),str(REPO/'dev/gis_ui/a5_smoke.cjs')],cwd=REPO,
                env={**demo.env,'GIS_TEST_NODE_MODULES':str(node_modules)},stdin=subprocess.PIPE,stdout=output,stderr=subprocess.DEVNULL)
            proc.stdin.write((json.dumps({'user':demo.users['normal'],'admin_token':tokens['admin'],'ldd':ldd,'a':a,'b':b,'geo':geo,'ge':ge,'output':str(out)})+'\n').encode());proc.stdin.close()
            end=time.monotonic()+900
            while not (out/'browser-awaiting-fault').exists() and proc.poll() is None and time.monotonic()<end:time.sleep(.3)
            if not (out/'browser-awaiting-fault').exists():raise RuntimeError('BROWSER_BEFORE_FAULT_FAILED')
            info=sql('SELECT gis.ldd_prepare_read('+literal(demo.users['admin']['id'])+'::uuid,'+literal(b['id'])+'::uuid)')
            path=local.prepared_store.objects/(info['candidate']['artifacts']['ldd_geometry']['sha256']+'.json')
            held=path.with_name(path.name+'.held-a5-'+demo.run)
            if held.exists() or path.resolve().parent!=local.prepared_store.objects.resolve():raise RuntimeError('OWNED_FAULT_TARGET_REJECTED')
            path.rename(held);faults.append((path,held));path.write_bytes(b'corrupt-a5-owned');(out/'browser-fault-injected').write_text('ready')
            proc.wait(timeout=300);output.seek(0);print(output.read(65536).decode(),flush=True);demo.smoke_exit=proc.returncode
            check('actual_browser_source_aware_flows',proc.returncode==0)
        check('test_catalogs_retired',all(req('GET','/datasets/'+d['id'])['active_edition_id'] is None for d in (ldd,geo)))
        check('queue_idle_after',sql("SELECT to_jsonb(count(*)=0) FROM gis.jobs WHERE state IN ('queued','running')"))
    except Exception as error:
        rows.append({'name':'execution','status':'Fail','diagnostic':str(error)[:180]});print(json.dumps(rows[-1]),flush=True)
    finally:
        if proc is not None and proc.poll() is None:proc.kill();proc.wait()
        for path,held in reversed(faults):
            if path.exists():path.rename(path.with_name(path.name+'.corrupt-a5-'+demo.run))
            held.rename(path)
        http.close();clean=demo.close();final=source()
        (out/'results.json').write_text(json.dumps({'rows':rows,'source':initial,'source_unchanged':initial==final,'cleanup':clean,'synthetic_only':True,'external_services':False},indent=2),encoding='utf-8')
    return 0 if clean and initial==final and rows and all(row['status']=='Pass' for row in rows) else 1

def run_country(root,node_modules,resume):
    """Targeted country-back regression; reuse only this A5 synthetic catalog."""
    if not re.fullmatch('[a-f0-9]{10}',resume):raise RuntimeError('COUNTRY_RESUME_SCOPE_REJECTED')
    logging.disable(logging.CRITICAL);demo=c.demo_module.Demo(root);out=root/'a5-published-analysis'/('country-'+demo.run);out.mkdir()
    targets=json.loads((root/'a5-published-analysis'/('integration-'+resume)/'targets.json').read_text(encoding='utf-8'))
    if targets['ldd']['title']!='A5 Synthetic LDD '+resume:raise RuntimeError('COUNTRY_DATASET_OWNERSHIP_REJECTED')
    initial=source();rows=[];proc=None
    try:
        demo.accounts(secrets.token_urlsafe(24));demo.start(launchers=())
        user=demo.users['admin'];token=demo.local.client(demo.anon).auth.sign_in_with_password({'email':user['email'],'password':user['password']}).session.access_token
        with tempfile.TemporaryFile() as output:
            proc=subprocess.Popen([shutil.which('node'),str(REPO/'dev/gis_ui/a5_smoke.cjs')],cwd=REPO,
                env={**demo.env,'GIS_TEST_NODE_MODULES':str(node_modules)},stdin=subprocess.PIPE,stdout=output,stderr=subprocess.DEVNULL)
            proc.stdin.write((json.dumps({'user':demo.users['normal'],'admin_token':token,'ldd':targets['ldd'],'a':targets['a'],'country_only':True,'output':str(out)})+'\n').encode());proc.stdin.close()
            proc.wait(timeout=600);output.seek(0);print(output.read(65536).decode(),flush=True);demo.smoke_exit=proc.returncode
            rows.append({'name':'actual_country_back_source_isolation','status':'Pass' if proc.returncode==0 else 'Fail'})
    except Exception as error:
        rows.append({'name':'execution','status':'Fail','diagnostic':str(error)[:160]})
    finally:
        if proc is not None and proc.poll() is None:proc.kill();proc.wait()
        clean=demo.close();final=source();(out/'results.json').write_text(json.dumps({'rows':rows,'source':initial,'source_unchanged':initial==final,'cleanup':clean,'synthetic_only':True},indent=2),encoding='utf-8')
    return 0 if clean and initial==final and all(row['status']=='Pass' for row in rows) else 1

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--runtime-dir',type=Path,required=True);p.add_argument('--node-modules',type=Path,required=True);p.add_argument('--resume-country')
    args=p.parse_args();raise SystemExit(run_country(args.runtime_dir,args.node_modules,args.resume_country) if args.resume_country else run(args.runtime_dir,args.node_modules))
