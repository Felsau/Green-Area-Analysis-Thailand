"""Actual Local A2 HTTP/Auth/Queue/Linux/files/Browser checks, no migrations.

Fresh synthetic users/rows are retained; fault injection only renames newly owned
artifact files (original bytes retained). Only containers/processes owned by this
run are stopped. Credentials stay in memory/private stdin, never in evidence.
"""
from __future__ import annotations
import argparse
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

HERE=Path(__file__).resolve().parent
REPO=HERE.parents[1]
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    mod=importlib.util.module_from_spec(spec);sys.modules[name]=mod;spec.loader.exec_module(mod);return mod
a2=load('a2_checks_operator',HERE/'ldd_prepare_local.py')
demo_module=load('a2_checks_demo',REPO/'dev/gis_ui/phase5_demo.py')
demo_module.local_target=lambda root:a2.LddPrepareLocal(root)


def run(root,node_modules,large_fixture,*,only_lifecycle=False):
    import httpx
    logging.disable(logging.CRITICAL)
    demo=demo_module.Demo(root)
    local=demo.local;literal=a2.m.t2.t1.literal
    output=local.output/('integration-'+demo.run);output.mkdir()
    rows=[];worker=None
    def check(name,ok):
        rows.append({'name':name,'status':'Pass' if ok else 'Fail'})
        print(json.dumps(rows[-1]),flush=True)
        if not ok:raise AssertionError(name)
    def sql(query):return local.sql(query,read_only=True)
    def job_state(jid):return sql('SELECT to_jsonb(j) FROM gis.jobs j WHERE id='+literal(jid)+'::uuid')
    def wait_job(jid,seconds=120):
        end=time.monotonic()+seconds
        while time.monotonic()<end:
            value=job_state(jid)
            if value['state'] in ('succeeded','failed'):return value
            time.sleep(1)
        raise RuntimeError('JOB_WAIT_TIMEOUT')
    http=httpx.Client(trust_env=False,follow_redirects=False,timeout=90)
    sessions={}
    def request(method,path,body=None,role='officer',key=None,raw=None,params=None):
        headers={'Authorization':'Bearer '+sessions[role]}
        if method!='GET':headers['Idempotency-Key']=key or str(uuid4())
        if raw is not None:headers['Content-Type']='application/zip'
        return http.request(method,'http://127.0.0.1:55422/gis'+path,headers=headers,
            json=body,content=raw,params=params)
    def ok(method,path,body=None,**kwargs):
        response=request(method,path,body,**kwargs)
        if response.status_code not in (200,201,202):
            raise RuntimeError('HTTP_UNEXPECTED_'+str(response.status_code)+'_'+path.split('/')[-1])
        return response.json()
    def inputs(edition):
        dataset=ok('GET','/datasets/'+edition['dataset_id'])
        return {'expected_dataset_revision':dataset['revision'],'expected_input_revision':edition['input_revision'],
            'input_hash':edition['input_hash'],'province':dataset['province'],'data_year':dataset['data_year']}
    def new_edition(dataset,raw):
        latest=ok('GET','/datasets/'+dataset['id'])
        value=ok('POST','/datasets/'+dataset['id']+'/ldd-uploads',raw=raw,
            params={'expected_revision':latest['revision'],'crs':'EPSG:32647','encoding':'auto'})
        # Existing upload command returns upload/edition references, not an
        # Edition resource. Re-read through the original public API contract.
        edition=next(e for e in ok('GET','/datasets/'+dataset['id']+'/editions',params={'limit':100})['data']
            if e.get('upload',{}).get('sha256')==hashlib.sha256(raw).hexdigest())
        job=ok('POST','/editions/'+edition['id']+'/validation-jobs',{'expected_revision':edition['input_revision']})
        check('original_upload_native_validation_'+edition['id'][:8],wait_job(job['id'])['state']=='succeeded')
        return ok('GET','/editions/'+edition['id'])
    def unique_zip(raw,variant):
        data=io.BytesIO(raw)
        with zipfile.ZipFile(data,'a') as archive:archive.comment=('a2:'+demo.run+':'+variant).encode()
        return data.getvalue()
    try:
        check('queue_idle_before_owned_workers',sql("SELECT to_jsonb(count(*)=0) FROM gis.jobs WHERE state IN ('queued','running')"))
        demo.accounts(secrets.token_urlsafe(24))
        # A2 needs LDD validation + prepare only. Preserve the existing maximum
        # of four approved containers, including the one-shot RO verifier.
        demo.start(launchers=(lambda:demo_module.p.p.m.LddContainer(local),))
        demo.grant_officer()
        for role,user in demo.users.items():
            sessions[role]=local.client(demo.anon).auth.sign_in_with_password({'email':user['email'],'password':user['password']}).session.access_token
        worker=a2.PrepareContainer(local);demo.workers.append(worker)
        a2.m.wait_for(lambda:worker.has('ready') or worker.has('fatal'),30)
        check('prepare_linux_daemon_ready',worker.has('ready'))
        check('officer_capability_enabled',ok('GET','/me')['ldd_prepare_enabled'])
        year=sql("SELECT to_jsonb(y) FROM generate_series(1980,2026)y WHERE NOT EXISTS(SELECT 1 FROM gis.datasets WHERE province='Bangkok Metropolis' AND data_year=y AND kind='ldd_shapefile') ORDER BY y LIMIT 1")
        dataset=ok('POST','/datasets',{'province':'Bangkok Metropolis','data_year':year,'month':0,
            'kind':'ldd_shapefile','purpose':'landuse','title':'A2 Synthetic '+demo.run})
        raw=(REPO/'green-area-backend/gis_worker/fixtures/ldd_valid.zip').read_bytes()
        if not only_lifecycle:
            first=new_edition(dataset,unique_zip(raw,'corrupt'))
            base='/editions/'+first['id'];payload=inputs(first)
            check('normal_user_prepare_denied',request('POST',base+'/prepare-jobs',payload,role='normal').status_code==403)
            check('normal_user_preview_denied',request('GET',base+'/prepared',role='normal').status_code==403)
            check('anonymous_preview_denied',http.get('http://127.0.0.1:55422/gis'+base+'/prepared').status_code==401)
            for field,value in [('province','Chiang Mai'),('data_year',year+1),('expected_input_revision',first['input_revision']+1),
                ('input_hash','0'*64),('expected_dataset_revision',payload['expected_dataset_revision']+1)]:
                check('conflict_'+field,request('POST',base+'/prepare-jobs',{**payload,field:value}).status_code==409)
            for field in ('actor','path','ready','proof'):
                check('payload_authority_'+field+'_rejected',request('POST',base+'/prepare-jobs',{**payload,field:'untrusted'}).status_code==422)
            competing=a2.PrepareContainer(local);demo.workers.append(competing)
            a2.m.wait_for(lambda:competing.has('ready') or competing.has('fatal'),30)
            check('two_prepare_daemons_ready',competing.has('ready'))
            key=str(uuid4());queued=ok('POST',base+'/prepare-jobs',payload,key=key)
            replay=ok('POST',base+'/prepare-jobs',payload,key=key)
            check('idempotency_same_job',replay['id']==queued['id'])
            done=wait_job(queued['id']);check('actual_prepare_succeeded',done['state']=='succeeded')
            check('concurrent_daemons_one_claim',sql('SELECT to_jsonb(count(*)=1) FROM gis.attempts WHERE job_id='+literal(queued['id'])+'::uuid')
                and sum(w.has('claimed',queued['id']) for w in (worker,competing))==1)
            competing.close();demo.workers.remove(competing)
            check('semantic_dedup_same_job',ok('POST',base+'/prepare-jobs',payload)['id']==queued['id'])
            preview=ok('GET',base+'/prepared')
            check('candidate_is_not_ready',preview['prepared'] and not preview['ready_for_publication'])
            check('client_cannot_supply_verifier_proof',request('POST',base+'/prepare-verification',{'job_id':queued['id'],'ready':True}).status_code==422)
            verified=ok('POST',base+'/prepare-verification',{'job_id':queued['id']})
            check('trusted_verifier_actual_files_ready',verified['ready_for_publication'] and len(verified['geometry']['features'])==3)
            check('known_area_6400_m2',verified['summary']['total_area_m2']==6400 and verified['summary']['feature_count']==3)
            check('not_complete_province_inventory',verified['summary']['metadata']['complete_province_inventory'] is False)
            internal=sql('SELECT gis.ldd_prepare_read('+literal(demo.users['officer']['id'])+'::uuid,'+literal(first['id'])+'::uuid)')
            descriptor=internal['candidate']['artifacts']['ldd_geometry']
            artifact=local.prepared_store.objects/(descriptor['sha256']+'.json')
            check('physical_sha_and_size',hashlib.sha256(artifact.read_bytes()).hexdigest()==descriptor['sha256'] and artifact.stat().st_size==descriptor['byte_size'])
            # Only fresh run-owned output; preserve original under a new, checked name.
            held=artifact.with_name(artifact.name+'.held-'+demo.run)
            if held.exists() or artifact.resolve().parent!=local.prepared_store.objects.resolve():raise RuntimeError('FAULT_TARGET_REJECTED')
            artifact.rename(held)
            with artifact.open('xb') as stream:stream.write(b'{"corrupt":true}')
            broken=ok('GET',base+'/prepared')
            check('corrupt_object_revokes_no_geometry',not broken['ready_for_publication'] and 'geometry' not in broken and broken['status']=='verification_revoked')
            check('revocation_is_durable',not ok('GET',base+'/prepared')['ready_for_publication'])
            # A separate fixture proves missing source also fails closed on every read.
            missing=new_edition(dataset,unique_zip(raw,'missing'))
            mbase='/editions/'+missing['id'];mj=ok('POST',mbase+'/prepare-jobs',inputs(missing))
            check('second_prepare_succeeded',wait_job(mj['id'])['state']=='succeeded')
            check('second_verified',ok('POST',mbase+'/prepare-verification',{'job_id':mj['id']})['ready_for_publication'])
            source=local.store.objects/(missing['upload']['sha256']+'.zip')
            saved=source.with_name(source.name+'.held-'+demo.run)
            if saved.exists() or source.resolve().parent!=local.store.objects.resolve():raise RuntimeError('FAULT_SOURCE_REJECTED')
            source.rename(saved)
            unavailable=ok('GET',mbase+'/prepared')
            check('missing_source_revokes_no_summary',not unavailable['ready_for_publication'] and 'summary' not in unavailable)
            # Restore immutable original without overwriting any path; certificate stays revoked.
            if source.exists():raise RuntimeError('SOURCE_RESTORE_CONFLICT')
            saved.rename(source)
        # 1500 duplicate synthetic polygons deliberately lengthen the native child.
        large=new_edition(dataset,Path(large_fixture).read_bytes())
        lj=ok('POST','/editions/'+large['id']+'/prepare-jobs',inputs(large))
        a2.m.wait_for(lambda:worker.has('claimed',lj['id']),30)
        # Freeze this exact owned container promptly after its claim event so a
        # fast native child cannot finish during the slower identity/SQL probes.
        local.db.runtime.verify_worker(worker.cid,worker.policy)
        local.db.runtime.docker(['pause',worker.cid])
        try:
            prior=job_state(lj['id']);check('kill_target_running',prior['state']=='running')
        finally:
            local.db.runtime.docker(['unpause',worker.cid])
        worker.signal('SIGKILL')
        replacement=a2.PrepareContainer(local);demo.workers.append(replacement)
        a2.m.wait_for(lambda:replacement.has('ready') or replacement.has('fatal'),30)
        check('replacement_worker_ready',replacement.has('ready'))
        # Natural lease expiry; no updates to job clocks or token state.
        recovered=wait_job(lj['id'],180)
        check('sigkill_replacement_recovery',recovered['state']=='succeeded' and recovered['attempt_count']==2)
        attempts=sql('SELECT jsonb_agg(state ORDER BY attempt_no) FROM gis.attempts WHERE job_id='+literal(lj['id'])+'::uuid')
        check('expired_then_succeeded_attempts',attempts==['expired','succeeded'])
        check('one_durable_result',sql('SELECT to_jsonb(count(*)=1) FROM gis.results WHERE job_id='+literal(lj['id'])+'::uuid'))
        identity=worker.identity
        headers={'apikey':identity.anon_key,'Authorization':'Bearer '+identity.access_token}
        rest='http://127.0.0.1:55421/rest/v1'
        stale=http.post(rest+'/rpc/gis_ldd_prepare_worker',headers=headers,json={'p_action':'complete','p_payload':{
            'job_id':lj['id'],'lease_token':prior['lease_token'],'report':{}}})
        check('stale_completion_fenced',stale.status_code>=400 and 'GIS_STALE_LEASE' in stale.text)
        worker.close();demo.workers.remove(worker)
        denied=http.post(rest+'/rpc/gis_ldd_verify_complete',headers=headers,json={'p_actor':demo.users['admin']['id'],
            'p_request_id':str(uuid4()),'p_job':lj['id'],'p_proof':{}})
        check('worker_cannot_certify',denied.status_code in (401,403,404))
        check('worker_direct_table_denied',sql("SELECT to_jsonb(NOT has_table_privilege('gis_native_worker','gis.ldd_prepare_certificates','INSERT,UPDATE,DELETE,SELECT'))"))
        check('browser_cannot_call_service_rpc',http.post(rest+'/rpc/gis_ldd_verify_complete',headers={
            'apikey':demo.anon,'Authorization':'Bearer '+sessions['admin']},json={'p_actor':demo.users['admin']['id'],
            'p_request_id':str(uuid4()),'p_job':lj['id'],'p_proof':{}}).status_code in (401,403,404))
        check('retry_succeeded_job_denied',request('POST','/editions/'+large['id']+'/prepare-retry',
            {**inputs(large),'job_id':lj['id'],'reason':'Synthetic already succeeded'}).status_code==409)
        # Exercise allowed retry with real least-privilege RPC calls. This is a
        # deterministic infrastructure-error injection, not a claimed OS timeout.
        retry_edition=new_edition(dataset,unique_zip(raw,'retry'))
        replacement.close();demo.workers.remove(replacement)
        retry_base='/editions/'+retry_edition['id']
        retry_payload=inputs(retry_edition)
        parent=ok('POST',retry_base+'/prepare-jobs',retry_payload)
        injected=a2.m.identity_module.provision(local)
        def injected_call(action,value):
            response=http.post(rest+'/rpc/gis_ldd_prepare_worker',headers={
                'apikey':injected.anon_key,'Authorization':'Bearer '+injected.access_token},json={'p_action':action,'p_payload':value})
            if response.status_code!=200:raise RuntimeError('INJECTED_WORKER_RPC_REJECTED')
            return response.json()
        from gis_worker.ldd_prepare_provider import failure
        for attempt in range(3):
            if attempt:time.sleep(5.2)
            claimed=injected_call('claim',{})['job']
            check('transient_claim_'+str(attempt+1),claimed['id']==parent['id'])
            failed=injected_call('fail',{'job_id':claimed['id'],'lease_token':claimed['lease_token'],
                'error_code':'transient','report':failure(claimed['prepare_request'],'NATIVE_TIMEOUT')})
            check('transient_budget_'+str(attempt+1),failed['state']==('failed' if attempt==2 else 'queued'))
        retry_body={**retry_payload,'job_id':parent['id'],'reason':'A2 controlled transient test, retry once'}
        retry_key=str(uuid4());child=ok('POST',retry_base+'/prepare-retry',retry_body,key=retry_key)
        check('explicit_retry_parent_history',child['parent_job_id']==parent['id'] and child['id']!=parent['id'])
        check('retry_idempotent',ok('POST',retry_base+'/prepare-retry',retry_body,key=retry_key)['id']==child['id'])
        check('second_explicit_retry_denied',request('POST',retry_base+'/prepare-retry',retry_body).status_code==409)
        retry_worker=a2.PrepareContainer(local);demo.workers.append(retry_worker)
        a2.m.wait_for(lambda:retry_worker.has('ready') or retry_worker.has('fatal'),30)
        check('explicit_retry_actual_native_succeeded',wait_job(child['id'])['state']=='succeeded')
        check('parent_failed_history_kept',job_state(parent['id'])['state']=='failed')
        # Browser uses a new validated small edition; the user triggers real prepare+verify.
        browser_edition=new_edition(dataset,unique_zip(raw,'browser'))
        payload={'users':demo.users,'dataset':dataset,'edition':browser_edition,'output':str(output)}
        env={**demo.env,'GIS_TEST_NODE_MODULES':str(node_modules)}
        proc=subprocess.Popen([shutil.which('node'),str(REPO/'dev/gis_ui/a2_smoke.cjs')],cwd=REPO,env=env,
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,encoding='utf-8')
        stdout,_=proc.communicate(json.dumps(payload)+'\n',timeout=300)
        check('browser_actual_preview_flow',proc.returncode==0)
        check('gate_closed',sql('SELECT to_jsonb(NOT activation_enabled) FROM gis.environment'))
        check('new_dataset_not_activated',ok('GET','/datasets/'+dataset['id'])['active_edition_id'] is None)
        demo.smoke_exit=0
    finally:
        http.close()
        clean=demo.close()
        (output/'integration-results.json').write_text(json.dumps({'rows':rows,'cleanup_ok':clean,
            'mocked_api':False,'local_only':True,'migration_run':False,'source':demo.initial_source,
            'fixture_sha256':hashlib.sha256(Path(large_fixture).read_bytes()).hexdigest()},indent=2),encoding='utf-8')
    return all(r['status']=='Pass' for r in rows) and clean


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime-dir',type=Path,required=True)
    parser.add_argument('--node-modules',type=Path,required=True)
    parser.add_argument('--large-fixture',type=Path,required=True)
    parser.add_argument('--only-lifecycle',action='store_true',help='Run only remaining recovery/retry/browser checks; retain earlier evidence')
    args=parser.parse_args()
    try:raise SystemExit(0 if run(args.runtime_dir,args.node_modules,args.large_fixture,only_lifecycle=args.only_lifecycle) else 1)
    except Exception as error:
        # No HTTP/client repr, body, session or credential in failures.
        import traceback
        traceback.print_tb(error.__traceback__)
        code=str(error) if isinstance(error,(AssertionError,RuntimeError,a2.m.t2.t1.SafetyError)) else type(error).__name__
        print(json.dumps({'failure':code[:160]}),flush=True);raise SystemExit(1)
