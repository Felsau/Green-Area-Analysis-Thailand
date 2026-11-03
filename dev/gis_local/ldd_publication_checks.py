"""Actual A3 Local HTTP/Auth/SQL/Linux/files/Browser acceptance checks.

All rows/users are fresh synthetic fixtures retained after testing. Faults rename
only run-owned files; original bytes remain under checked backup paths. No cloud,
dotenv, deletion of prior data, migration application or credential output.
"""
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
    spec=importlib.util.spec_from_file_location(name,path);mod=importlib.util.module_from_spec(spec)
    sys.modules[name]=mod;spec.loader.exec_module(mod);return mod
a3=load('a3_checks_operator',HERE/'ldd_publication_local.py')
demo_module=load('a3_checks_demo',REPO/'dev/gis_ui/phase5_demo.py')
demo_module.local_target=lambda root:a3.LddPublicationLocal(root)

def run(root,node_modules,resume_run=None):
    import httpx
    logging.disable(logging.CRITICAL);demo=demo_module.Demo(root);local=demo.local
    output=local.output/('integration-'+demo.run);output.mkdir();rows=[];tokens={};seeded=None
    literal=a3.m.t2.t1.literal
    http=httpx.Client(trust_env=False,follow_redirects=False,timeout=120)
    def check(name,value):
        rows.append({'name':name,'status':'Pass' if value else 'Fail'});print(json.dumps(rows[-1]),flush=True)
        if not value:raise AssertionError(name)
    def sql(query,write=False):return local.sql(query,read_only=not write)
    def req(method,path,body=None,role='admin',key=None,raw=None,params=None):
        headers={'Authorization':'Bearer '+tokens[role]}
        if method!='GET':headers['Idempotency-Key']=key or str(uuid4())
        if raw is not None:headers['Content-Type']='application/zip'
        return http.request(method,'http://127.0.0.1:55422/gis'+path,headers=headers,json=body,content=raw,params=params)
    def ok(method,path,body=None,**kw):
        r=req(method,path,body,**kw)
        if r.status_code not in (200,201,202):
            code=r.json().get('detail',{}).get('code','UNKNOWN')
            raise RuntimeError('HTTP_'+str(r.status_code)+'_'+str(code)+'_'+path.split('/')[-1])
        return r.json()
    def wait_job(jid):
        end=time.monotonic()+150
        while time.monotonic()<end:
            value=sql('SELECT to_jsonb(j) FROM gis.jobs j WHERE id='+literal(jid)+'::uuid')
            if value['state'] in ('succeeded','failed'):return value
            time.sleep(.5)
        raise RuntimeError('OWNED_JOB_TIMEOUT')
    def dataset():return ok('GET','/datasets/'+d['id'])
    def edition(e):return ok('GET','/editions/'+e['id'])
    def prepared(e):return sql('SELECT gis.ldd_prepare_read('+literal(demo.users['admin']['id'])+'::uuid,'+literal(e['id'])+'::uuid)')
    def prepare_input(e):
        return {'expected_dataset_revision':dataset()['revision'],'expected_input_revision':e['input_revision'],
            'input_hash':e['input_hash'],'province':d['province'],'data_year':d['data_year']}
    def payload(e):
        e=edition(e);latest=dataset()
        return {'edition_id':e['id'],'expected_dataset_revision':latest['revision'],'expected_active_edition_id':latest['active_edition_id'],
            'expected_input_revision':e['input_revision'],'input_hash':e['input_hash'],'validation_result_id':e['validated_result_id'],
            'source_sha256':e['upload']['sha256'],'province':d['province'],'data_year':d['data_year'],
            'method_version':'ldd-source-area-v1','coverage_mode':'validated_source_footprint','reason':'A3 Synthetic acceptance '+demo.run}
    def command(op,e,**kw):return ok('POST','/datasets/'+d['id']+'/ldd-publication/'+op,payload(e),**kw)
    def read():return req('GET','/published-ldd',role='normal',params={'province':d['province'],'data_year':d['data_year']})
    def make(tag):
        raw=io.BytesIO((REPO/'green-area-backend/gis_worker/fixtures/ldd_valid.zip').read_bytes())
        with zipfile.ZipFile(raw,'a') as archive:archive.comment=('a3:'+demo.run+':'+tag).encode()
        raw=raw.getvalue();ok('POST','/datasets/'+d['id']+'/ldd-uploads',raw=raw,
            params={'expected_revision':dataset()['revision'],'crs':'EPSG:32647','encoding':'auto'})
        e=next(e for e in ok('GET','/datasets/'+d['id']+'/editions',params={'limit':100})['data'] if e.get('upload',{}).get('sha256')==hashlib.sha256(raw).hexdigest())
        job=ok('POST','/editions/'+e['id']+'/validation-jobs',{'expected_revision':e['input_revision']})
        check('upload_native_validation_'+tag,wait_job(job['id'])['state']=='succeeded');e=edition(e)
        job=ok('POST','/editions/'+e['id']+'/prepare-jobs',prepare_input(e))
        check('prepare_job_'+tag,wait_job(job['id'])['state']=='succeeded')
        result=ok('POST','/editions/'+e['id']+'/prepare-verification',{'job_id':job['id']})
        check('trusted_bytes_'+tag,result['ready_for_publication'] and result['summary']['total_area_m2']==6400 and len(result['geometry']['features'])==3)
        return edition(e)
    def cache_snapshot():
        names=local.sql("SELECT jsonb_agg(table_name ORDER BY table_name) FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE' AND table_name<>'profiles'",role='postgres',read_only=True)
        pairs=[literal(n)+',(SELECT jsonb_build_object(\'count\',count(*),\'hash\',md5(COALESCE(string_agg(to_jsonb(t)::text,\'\' ORDER BY to_jsonb(t)::text),\'\'))) FROM public."'+n+'" t)' for n in names]
        return local.sql('SELECT jsonb_build_object('+','.join(pairs)+')',role='postgres',read_only=True)
    try:
        check('queue_idle',sql("SELECT to_jsonb(count(*)=0) FROM gis.jobs WHERE state IN ('queued','running')"))
        demo.accounts(secrets.token_urlsafe(24));demo.start(launchers=(lambda:demo_module.p.p.m.LddContainer(local),lambda:a3.a2.PrepareContainer(local)))
        demo.grant_officer()
        for role,u in demo.users.items():tokens[role]=local.client(demo.anon).auth.sign_in_with_password({'email':u['email'],'password':u['password']}).session.access_token
        year=sql("SELECT to_jsonb(y) FROM generate_series(1980,2027)y WHERE NOT EXISTS(SELECT 1 FROM gis.datasets WHERE province='Bangkok Metropolis' AND data_year=y AND kind='ldd_shapefile') ORDER BY y LIMIT 1")
        if resume_run is None:
            d=ok('POST','/datasets',{'province':'Bangkok Metropolis','data_year':year,'month':0,'kind':'ldd_shapefile','purpose':'landuse','title':'A3 Synthetic '+demo.run})
        else:
            import re
            if not re.fullmatch('[a-f0-9]{10}',resume_run):raise RuntimeError('RESUME_SCOPE_REJECTED')
            d=sql('SELECT to_jsonb(d) FROM gis.datasets d WHERE title='+literal('A3 Synthetic '+resume_run))
            if not d or d['active_edition_id'] is not None:raise RuntimeError('RESUME_REQUIRES_UNPUBLISHED_A3_FIXTURES')
        # Populate real legacy cache rows, never upsert/overwrite existing rows.
        cy=local.sql("SELECT to_jsonb(y) FROM generate_series(1980,2027)y WHERE NOT EXISTS(SELECT 1 FROM public.ndvi_annual WHERE province='Bangkok Metropolis' AND year=y) AND NOT EXISTS(SELECT 1 FROM public.province_lst_annual WHERE province='Bangkok Metropolis' AND year=y) ORDER BY y LIMIT 1",role='postgres',read_only=True)
        local.sql("INSERT INTO public.ndvi_annual(province,year,ndvi_mean,total_area_km2,green_area_pct) VALUES('Bangkok Metropolis',"+str(cy)+",0.314159,1,25);INSERT INTO public.province_lst_annual(province,year,lst_mean) VALUES('Bangkok Metropolis',"+str(cy)+",30.125)",role='postgres')
        local.sql("INSERT INTO public.saved_areas(label,geometry,year,province,analysis,user_id) VALUES("+literal('A3 synthetic saved '+demo.run)+",'{\"type\":\"Polygon\",\"coordinates\":[[[100.5,13.7],[100.51,13.7],[100.51,13.71],[100.5,13.7]]]}'::jsonb,"+str(cy)+",'Bangkok Metropolis','{\"synthetic\":true}'::jsonb,"+literal(demo.users['normal']['id'])+'::uuid)',role='postgres')
        landuse_module=sys.modules['routers.maps.analysis.landuse']
        sentinel_key=('a3-preservation',demo.run)
        landuse_module._summary_cache.set(sentinel_key,'synthetic-legacy-sentinel')
        seeded=cache_snapshot();check('legacy_cache_prepopulated',seeded['ndvi_annual']['count']>0 and seeded['province_lst_annual']['count']>0)
        # Known test inserts are retained. Preserve the independent pre-A3
        # before.json, but compare demo lifecycle against this seeded baseline.
        demo.before['postgres']['tables']=local.baseline()['postgres']['tables']
        if resume_run is None:a,b,c=[make(tag) for tag in ('A','B','C')]
        else:
            existing=ok('GET','/datasets/'+d['id']+'/editions',params={'limit':100})['data']
            a,b,c=sorted(existing,key=lambda e:e['created_at'])
            check('reuse_prior_owned_synthetic_A_B_C',all(e['state']=='validated' and prepared(e)['ready_for_publication'] for e in (a,b,c)))
        check('prepare_never_activates',dataset()['active_edition_id'] is None)
        key=str(uuid4());pa=payload(a)
        check('officer_publication_denied',req('POST','/datasets/'+d['id']+'/ldd-publication/activation',pa,role='officer').status_code==403)
        check('normal_publication_denied',req('POST','/datasets/'+d['id']+'/ldd-publication/activation',pa,role='normal').status_code==403)
        check('anonymous_published_denied',http.get('http://127.0.0.1:55422/gis/published-ldd',params={'province':d['province'],'data_year':year}).status_code==401)
        first=ok('POST','/datasets/'+d['id']+'/ldd-publication/activation',pa,key=key)
        check('activate_A',first['dataset']['active_edition_id']==a['id'])
        bundle=read();snap=bundle.json()
        check('normal_user_actual_published_geometry_summary',bundle.status_code==200 and snap['source_identity']['edition_id']==a['id'] and snap['summary']['total_area_m2']==6400 and len(snap['geometry']['features'])==3)
        check('consistent_snapshot_lineage',snap['geometry']['metadata']==snap['summary']['metadata'] and snap['summary']['metadata']['edition_id']==a['id'] and bundle.headers['cache-control']=='no-store')
        rb=payload(b);rb['dataset_id']=d['id'];rp=local.publication.fresh_proof(prepared(b));rid=str(uuid4())
        call='gis.ldd_publication_command('+literal(demo.users['admin']['id'])+'::uuid,'+literal(rid)+"::uuid,'activate',"+literal(json.dumps(rb))+'::jsonb,'+literal(json.dumps(rp))+'::jsonb,true,false)'
        # Force failure AFTER actual pointer/audit/receipt and deferred checks.
        # The subtransaction must roll back all effects; the outer read verifies.
        atomic=sql("DO $test$ BEGIN BEGIN PERFORM "+call+";SET CONSTRAINTS ALL IMMEDIATE;RAISE EXCEPTION 'A3_FORCED_AFTER_COMMAND';EXCEPTION WHEN raise_exception THEN IF SQLERRM<>'A3_FORCED_AFTER_COMMAND' THEN RAISE;END IF;END;END $test$;SELECT to_jsonb(NOT EXISTS(SELECT 1 FROM gis.receipts WHERE request_id="+literal(rid)+'::uuid) AND EXISTS(SELECT 1 FROM gis.datasets WHERE id='+literal(d['id'])+'::uuid AND active_edition_id='+literal(a['id'])+'::uuid AND revision='+str(rb['expected_dataset_revision'])+'))',True)
        check('forced_post_command_failure_atomic_rollback',atomic is True)
        command('activation',b);check('replace_B_keeps_A_validated',dataset()['active_edition_id']==b['id'] and edition(a)['state']=='validated')
        replay=ok('POST','/datasets/'+d['id']+'/ldd-publication/activation',pa,key=key)
        check('history_replay_does_not_republish_A',replay['replayed'] and dataset()['active_edition_id']==b['id'])
        command('rollback',a);check('rollback_A_fresh_bytes',dataset()['active_edition_id']==a['id'])
        # CAS/lineage negatives through actual service RPC avoid rerunning native
        # recomputation for deliberately invalid SQL inputs. Proof is server-only.
        from gis_service import GisService
        service=GisService(local.gis_runtime);actor=demo.users['admin']['id'];proof=local.publication.fresh_proof(prepared(b))
        base=payload(b);base['dataset_id']=d['id']
        def rpc(body,operation='activate',rid=None):
            try:return service._rpc('gis_ldd_publication_command',{'p_actor':actor,'p_request_id':rid or str(uuid4()),'p_operation':operation,'p_payload':body,'p_proof':proof,'p_backend_local':True,'p_probe':False})
            except Exception as error:return {'error':getattr(error,'status_code',None)}
        for field,value in [('expected_dataset_revision',base['expected_dataset_revision']+1),('expected_active_edition_id',c['id']),('input_hash','0'*64),('source_sha256','0'*64),('validation_result_id',str(uuid4())),('province','Chiang Mai'),('data_year',year+1),('expected_input_revision',99)]:
            check('sql_reject_'+field,rpc({**base,field:value}).get('error')==409 and dataset()['active_edition_id']==a['id'])
        with ThreadPoolExecutor(max_workers=2) as pool:race=list(pool.map(lambda _:rpc(base),range(2)))
        check('concurrent_CAS_one_commit',sum('status' in x for x in race)==1 and sum(x.get('error')==409 for x in race)==1 and dataset()['active_edition_id']==b['id'])
        command('rollback',a)
        # Explicit inactive withdrawal preserves another active pointer.
        pb=payload(b);pb['replacement_edition_id']=None
        ok('POST','/datasets/'+d['id']+'/ldd-publication/withdrawal',pb)
        check('withdraw_B_terminal_preserves_A',edition(b)['state']=='withdrawn' and dataset()['active_edition_id']==a['id'])
        check('withdrawn_B_cannot_rollback',req('POST','/datasets/'+d['id']+'/ldd-publication/rollback',payload(b)).status_code==409)
        # Newly prepared C only; original bytes preserved in a unique backup.
        pc=prepared(c);desc=pc['candidate']['artifacts']['ldd_geometry'];path=local.prepared_store.objects/(desc['sha256']+'.json')
        held=path.with_name(path.name+'.held-'+demo.run)
        if held.exists() or path.resolve().parent!=local.prepared_store.objects.resolve():raise RuntimeError('FAULT_TARGET_REJECTED')
        path.rename(held)
        check('missing_C_cannot_activate',req('POST','/datasets/'+d['id']+'/ldd-publication/activation',payload(c)).status_code==409 and dataset()['active_edition_id']==a['id'])
        with path.open('xb') as f:f.write(b'{"corrupt":true}')
        check('corrupt_C_cannot_activate',req('POST','/datasets/'+d['id']+'/ldd-publication/activation',payload(c)).status_code==409 and dataset()['active_edition_id']==a['id'])
        bad=path.with_name(path.name+'.corrupt-'+demo.run);path.rename(bad);held.rename(path)
        command('activation',c)
        check('fresh_C_activates_after_bytes_restored',dataset()['active_edition_id']==c['id'])
        check('published_C_live_cache_identity',read().json()['source_identity']['edition_id']==c['id'])
        # Browser tests current real C and normal role (no GIS catalog access).
        payload_browser={'users':demo.users,'output':str(output),'dataset':d,'edition':c}
        env={**demo.env,'GIS_TEST_NODE_MODULES':str(node_modules)}
        proc=subprocess.Popen([shutil.which('node'),str(REPO/'dev/gis_ui/a3_smoke.cjs')],cwd=REPO,env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,encoding='utf-8')
        stdout,_=proc.communicate(json.dumps(payload_browser)+'\n',timeout=600);demo.smoke_exit=proc.returncode
        print(stdout,flush=True);check('browser_published_map_summary',proc.returncode==0)
        # Cached reader must fail closed and revoke after active bytes disappear.
        path.rename(held)
        failed=read();check('active_missing_no_stale_geometry',failed.status_code==409 and 'geometry' not in failed.json())
        check('active_certificate_revoked',not prepared(c)['ready_for_publication'])
        held.rename(path)
        check('revoked_C_never_reactivates',req('POST','/datasets/'+d['id']+'/ldd-publication/activation',payload(c)).status_code==409)
        withdrawal=payload(c);withdrawal['replacement_edition_id']=a['id']
        ok('POST','/datasets/'+d['id']+'/ldd-publication/withdrawal',withdrawal)
        check('withdraw_active_revoked_C_replace_A',edition(c)['state']=='withdrawn' and dataset()['active_edition_id']==a['id'])
        pa=payload(a);pa['replacement_edition_id']=None;ok('POST','/datasets/'+d['id']+'/ldd-publication/withdrawal',pa)
        check('withdraw_A_to_null_terminal',dataset()['active_edition_id'] is None and edition(a)['state']=='withdrawn' and read().status_code==404)
        check('broad_gate_closed',sql('SELECT to_jsonb(NOT activation_enabled) FROM gis.environment') and local.gis_runtime.sandbox_activation_enabled is False)
        check('prepopulated_cache_all_legacy_tables_preserved',cache_snapshot()==seeded)
        check('legacy_inprocess_landuse_cache_preserved',landuse_module._summary_cache.get(sentinel_key)=='synthetic-legacy-sentinel')
        check('A_B_C_source_objects_retained',all((local.store.objects/(e['upload']['sha256']+'.zip')).exists() for e in (a,b,c)))
        check('publication_audits_receipts_atomic',sql('SELECT to_jsonb(count(*)=9) FROM gis.audit WHERE dataset_id='+literal(d['id'])+"::uuid AND operation IN ('ldd.activate','ldd.rollback','ldd.withdraw')"))
    except Exception as error:
        rows.append({'name':'execution','status':'Fail','diagnostic':str(error)[:240]});print(json.dumps(rows[-1]),flush=True)
    finally:
        http.close();clean=demo.close()
        (output/'results.json').write_text(json.dumps({'rows':rows,'source':demo_module.source(),'cleanup':clean,'synthetic_only':True,'cache_seed_retained':seeded is not None},indent=2),encoding='utf-8')
    return 0 if clean and rows and all(r['status']=='Pass' for r in rows) else 1

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--runtime-dir',type=Path,required=True);p.add_argument('--node-modules',type=Path,required=True);p.add_argument('--resume-run')
    args=p.parse_args();raise SystemExit(run(args.runtime_dir,args.node_modules,args.resume_run))
