"""Actual local Auth/API/SQL/Linux offline-processing acceptance checks.

Synthetic scenes and test identities only. No GEE/Cloud/dotenv, migration,
backdated leases, cache deletion or synthetic result presented as live data.
"""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
import importlib.util
import json
import logging
from pathlib import Path
import secrets
import sys
from uuid import uuid4

spec=importlib.util.spec_from_file_location('p3_operator',Path(__file__).with_name('phase3_local.py'))
p=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=p
spec.loader.exec_module(p)
m=p.m.m
REPO=p.REPO

def fingerprint():
    value=m.fingerprint()
    for name in ('phase3_local.py','phase3_checks.py','phase2_local.py'):
        path=Path(__file__).with_name(name)
        value['files'][path.relative_to(REPO).as_posix()]=hashlib.sha256(path.read_bytes()).hexdigest()
    for name in ('gis_ldd_storage.py','gee_utils.py','routers/ndvi/compute.py','routers/ndvi/endpoints.py','routers/lst.py','dependencies.py'):
        path=REPO/'green-area-backend'/name
        value['files'][path.relative_to(REPO).as_posix()]=hashlib.sha256(path.read_bytes()).hexdigest()
    value['sha256']=hashlib.sha256(json.dumps(value['files'],sort_keys=True).encode()).hexdigest()
    return value

class Suite:
    def __init__(self,root):
        self.local=p.Phase3Local(root).prepare()
        self.source=fingerprint()
        self.before=self.local.baseline()
        self.rows=[]
        self.workers=[]
        self.events=[]
        self.jobs=[]
        self.run_id=uuid4().hex[:12]

    def record(self,name,passed,**evidence):
        row={'name':name,'status':'Pass' if passed else 'Fail',**evidence}
        self.rows.append(row)
        print(json.dumps(row),flush=True)
        if not passed:
            raise AssertionError(name)

    def request(self,method,path,body=None,*,status=200,headers=None,key=None,**kwargs):
        h=dict(headers if headers is not None else self.headers)
        if method in ('POST','PATCH'):
            h['Idempotency-Key']=key or str(uuid4())
        response=self.api.request(method,path,json=body,headers=h,**kwargs)
        if response.status_code != status:
            detail=response.json().get('detail',{})
            code=detail.get('code','INPUT_VALIDATION') if isinstance(detail,dict) else 'INPUT_VALIDATION'
            print(json.dumps({'local_status':response.status_code,'expected':status,'code':code}),flush=True)
            raise RuntimeError('LOCAL_API_STATUS_MISMATCH')
        return response.json()

    def denied(self,name,call,codes):
        try:
            call()
        except Exception as error:
            code=str(getattr(error,'code',''))
            message=str(getattr(error,'message',''))
            self.record(name,code in codes or message in codes)
            return
        self.record(name,False)

    def setup(self):
        self.local.attest()
        self.record('initial_queue_idle',self.local.sql("SELECT to_jsonb(count(*)) FROM gis.jobs WHERE state IN ('queued','running')",read_only=True)==0)
        anon,service=self.local.local_keys()
        self.operator=self.local.client(service)
        self.users={}
        for role in ('admin','officer','normal'):
            email='gis-p3-'+role+'-'+self.run_id+'@example.invalid'
            password=secrets.token_urlsafe(30)
            user=self.operator.auth.admin.create_user({'email':email,'password':password,'email_confirm':True}).user
            client=self.local.client(anon)
            session=client.auth.sign_in_with_password({'email':email,'password':password}).session
            self.users[role]={'id':str(user.id),'headers':{'Authorization':'Bearer '+session.access_token}}
        self.local.sql("UPDATE public.profiles SET role='admin' WHERE id="+m.t2.t1.literal(self.users['admin']['id'])+'::uuid',role='postgres')
        self.api=self.local.api()
        self.headers=self.users['admin']['headers']
        self.request('POST','/gis/officers',{'user_id':self.users['officer']['id'],'reason':'Phase3 synthetic local test'})
        self.headers=self.users['officer']['headers']
        self.identity=m.identity_module.provision(self.local)
        self.second=m.identity_module.provision(self.local)
        ready=self.identity.client.rpc('gis_processing_readiness',{}).execute().data
        self.record('least_privilege_real_jwt_processing_readiness',ready['subject']==self.identity.subject and ready['contract_version']=='1.0.0-processing-offline')
        # Prefer the year of the existing T1 legacy cache sentinel, without
        # changing it; later reruns choose a new source year for content dedup.
        self.year=self.local.sql("SELECT to_jsonb(y) FROM generate_series(2017,2026)y WHERE NOT EXISTS(SELECT 1 FROM gis.processing_requests WHERE province='Bangkok Metropolis' AND data_year=y) ORDER BY abs(y-2025),y LIMIT 1",read_only=True)
        if self.year is None:
            raise RuntimeError('UNUSED_SYNTHETIC_SOURCE_YEAR_REQUIRED')
        self.cache_before=self.cache()
        if self.cache_before['ndvi_annual_rows']>0 and self.cache_before['lst_annual_rows']>0:
            self.record('legacy_cache_sentinels_exist_before_processing',True)
        else:
            # Do not fabricate satellite-looking rows in the legacy cache solely
            # to turn this assertion green. ACL + empty-table hash preservation
            # are still checked; retention of nonempty caches remains explicit.
            self.rows.append({'name':'nonempty_existing_cache_retention','status':'Not Tested',
                'reason':'Current local postgres legacy NDVI/LST annual caches do not both contain rows',
                'ndvi_rows':self.cache_before['ndvi_annual_rows'],'lst_rows':self.cache_before['lst_annual_rows']})

    def cache(self):
        return self.local.sql("SELECT jsonb_build_object('ndvi_annual_rows',(SELECT count(*) FROM public.ndvi_annual),'lst_annual_rows',(SELECT count(*) FROM public.province_lst_annual),'ndvi_hash',(SELECT md5(COALESCE(string_agg(to_jsonb(t)::text,'|' ORDER BY to_jsonb(t)::text),'')) FROM public.ndvi_annual t),'lst_hash',(SELECT md5(COALESCE(string_agg(to_jsonb(t)::text,'|' ORDER BY to_jsonb(t)::text),'')) FROM public.province_lst_annual t))",role='postgres',read_only=True)

    def body(self,**changes):
        return {'province':'Bangkok Metropolis','district':None,'metric':'ndvi','data_year':self.year,'month':0,
            'mode':'offline_synthetic','scenario':'standard','expected_revision':1,**changes}

    def create(self,**changes):
        value=self.request('POST','/gis/processing-jobs',self.body(**changes),status=202)
        self.jobs.append(value['id'])
        return value

    def rpc(self,action,payload=None,identity=None,name='gis_processing_worker'):
        return (identity or self.identity).client.rpc(name,{'p_action':action,'p_payload':payload or {}}).execute().data

    def state(self,job):
        return self.local.sql("SELECT jsonb_build_object('state',j.state,'attempt_count',j.attempt_count,'worker_id',j.worker_id,'input_hash',j.input_hash,'input_revision',j.input_revision,'edition_state',e.state,'validated_result',e.validated_result_id,'active',d.active_edition_id,'eligible',gis.eligible(e.id,d.id),'result_count',(SELECT count(*) FROM gis.results WHERE job_id=j.id),'result',(SELECT jsonb_build_object('provider',provider,'report',report) FROM gis.results WHERE job_id=j.id),'attempts',(SELECT jsonb_agg(jsonb_build_object('state',state,'report',validation_report,'error_code',error_code) ORDER BY attempt_no) FROM gis.attempts WHERE job_id=j.id)) FROM gis.jobs j JOIN gis.editions e ON e.id=j.edition_id JOIN gis.datasets d ON d.id=e.dataset_id WHERE j.id="+m.t2.t1.literal(job)+'::uuid',read_only=True)

    def terminal(self,job,timeout=90):
        return m.wait_for(lambda:(s if (s:=self.state(job))['state'] in ('succeeded','failed') else None),timeout)

    def start(self,identity=None,kind='processing'):
        worker=(p.ProcessingContainer(self.local,identity or self.identity) if kind=='processing' else
            p.m.LddContainer(self.local,identity or self.identity) if kind=='ldd' else
            m.ContainerWorker(self.local,identity or self.identity))
        self.workers.append(worker)
        m.wait_for(lambda:worker.has('ready') or worker.has('fatal'),30)
        self.record(kind+'_linux_worker_ready_'+str(len(self.rows)),worker.has('ready') and not worker.has('fatal'))
        return worker

    def close(self,worker):
        worker.close()
        self.events.extend(worker.events)
        self.workers.remove(worker)

    @staticmethod
    def native_request(claim):
        return {k:claim[k] for k in ('processing_id','manifest','input_hash','input_revision','attempt_number')}

    def contracts_security(self):
        options=self.request('GET','/gis/processing-options',params={'province':'Bangkok Metropolis'})
        self.record('canonical_province_district_options_offline_only',options['mode']=='offline_synthetic' and options['live_enabled'] is False and any(x['name_en']=='BangKapi' for x in options['districts']))
        self.request('POST','/gis/processing-jobs',self.body(),status=403,headers=self.users['normal']['headers'])
        self.request('POST','/gis/processing-jobs',self.body(),status=401,headers={})
        for changes in ({'mode':'gee_live'},{'data_year':2010},{'month':13},{'expected_revision':True},{'district':'NotADistrict'}):
            self.request('POST','/gis/processing-jobs',self.body(**changes),status=422)
        self.record('api_auth_scope_date_live_revision_negative_cases',True)
        self.denied('sql_live_mode_closed_before_compute',lambda:self.operator.rpc('gis_processing_command',{
            'p_actor':self.users['officer']['id'],'p_request_id':str(uuid4()),'p_operation':'create',
            'p_payload':self.body(mode='gee_live'),'p_backend_sandbox':False}).execute(),{'GIS_GEE_LIVE_DISABLED'})
        for name,rpc,args in (
            ('worker_backend_admin_rpc_denied','gis_command',{'p_actor':self.identity.subject,'p_request_id':str(uuid4()),'p_operation':'grant_officer','p_payload':{}}),
            ('worker_processing_enqueue_rpc_denied','gis_processing_command',{'p_actor':self.identity.subject,'p_request_id':str(uuid4()),'p_operation':'create','p_payload':self.body()}),
            ('worker_processing_read_rpc_denied','gis_processing_read',{'p_actor':self.identity.subject,'p_kind':'options','p_payload':{}})):
            self.denied(name,lambda rpc=rpc,args=args:self.identity.client.rpc(rpc,args).execute(),{'42501'})
        self.denied('worker_direct_legacy_read_denied',lambda:self.identity.client.table('profiles').select('id').limit(1).execute(),{'42501'})
        self.denied('worker_legacy_cache_update_denied',lambda:self.identity.client.table('ndvi_annual').update({'ndvi_mean':0.01}).eq('province','P3_UNMATCHABLE_FIXTURE').execute(),{'42501'})
        self.denied('worker_jwt_subject_spoof_denied',lambda:self.rpc('claim',{'worker_id':str(uuid4())}),{'GIS_WORKER_IDENTITY_MISMATCH','42501'})
        key=str(uuid4())
        value=self.request('POST','/gis/processing-jobs',self.body(),status=202,key=key)
        self.jobs.append(value['id'])
        replay=self.request('POST','/gis/processing-jobs',self.body(),status=202,key=key)
        duplicate=self.request('POST','/gis/processing-jobs',self.body(),status=202)
        self.record('idempotency_replay_content_dedup_exact_job',value==replay and duplicate['id']==value['id'])
        self.request('POST','/gis/processing-jobs',self.body(month=1),status=409,key=key)
        self.record('idempotency_conflict_rejected',True)
        self.record('ldd_and_v2_cannot_claim_processing',self.rpc('claim',name='gis_ldd_worker').get('job') is None and self.rpc('claim',name='gis_worker_v2').get('job') is None)
        with ThreadPoolExecutor(max_workers=2) as pool:
            claims=list(pool.map(lambda i:self.rpc('claim',identity=i),(self.identity,self.second)))
        owners=[(i,c['job']) for i,c in zip((self.identity,self.second),claims) if c.get('job')]
        self.record('concurrent_claim_exactly_once',len(owners)==1 and owners[0][1]['id']==value['id'] and self.state(value['id'])['attempt_count']==1)
        identity,job=owners[0]
        from gis_worker.processing_provider import report_failure
        report=report_failure(self.native_request(job),'NATIVE_TIMEOUT')
        lease={'job_id':job['id'],'lease_token':job['lease_token']}
        for name,bad,code in (
            ('empty_report',{},'GIS_PROCESSING_REPORT_INVALID'),
            ('artifact_hash',{**report,'artifact_sha256':'0'*64},'GIS_PROCESSING_REPORT_INVALID'),
            ('revision',{**report,'input_revision':2},'GIS_PROCESSING_REPORT_INVALID'),
            ('live_label',{**report,'mode':'gee_live'},'GIS_PROCESSING_REPORT_INVALID'),
            ('forged_statistics',{**report,'valid':True,'error_code':None,'statistics':{'valid_pixels':4,'mean':1,'min':0,'max':1}},'GIS_PROCESSING_SCIENTIFIC_INVARIANT')):
            self.denied('report_bypass_'+name,lambda bad=bad:self.rpc('complete',{**lease,'report':bad},identity),{code})
        self.denied('wrong_token_completion_rejected',lambda:self.rpc('complete',{**lease,'lease_token':str(uuid4()),'report':report},identity),{'GIS_STALE_LEASE'})
        self.rpc('fail',{**lease,'error_code':'transient','report':report},identity)
        worker=self.start()
        state=self.terminal(job['id'])
        self.record('api_queue_linux_numeric_candidate_not_active',state['state']=='succeeded' and state['result_count']==1 and state['attempt_count']==2 and state['edition_state']=='draft' and state['validated_result'] is None and not state['eligible'] and state['active'] is None)
        self.verify_candidate(job['id'],'ndvi',0,None)
        self.close(worker)

    def verify_candidate(self,job,metric,month,district):
        value=self.request('GET','/gis/processing-jobs/'+job)
        result=self.request('GET','/gis/processing-jobs/'+job+'/result')
        attempts=self.request('GET','/gis/processing-jobs/'+job+'/attempts')
        history=self.request('GET','/gis/processing-jobs/'+job+'/history')
        report=result['result']['report']
        expected=({'valid_pixels':2,'mean':.4921,'min':.4286,'max':.5556} if month==0 else
            {'valid_pixels':3,'mean':.1614,'min':-.5,'max':.5556}) if metric=='ndvi' else {
                'valid_pixels':2,'mean':29.66,'min':22.82,'max':36.5}
        self.record('scientific_candidate_'+metric+'_'+str(month)+'_'+str(district),value['mode']=='offline_synthetic' and
            value['candidate_status']=='pending_review' and result['result']['provider']=='offline_processing' and report['synthetic'] is True and
            report['valid'] is True and report['statistics']==expected and report['metadata']==value['metadata'] and
            attempts['data'][-1]['validation_report']==report and bool(history['data']))

    def science(self):
        worker=self.start()
        for metric,month,district in (('ndvi',2,'BangKapi'),('lst',0,None),('lst',2,'BangKapi')):
            job=self.create(metric=metric,month=month,district=district)
            state=self.terminal(job['id'])
            self.record('native_processing_success_'+metric+'_'+str(month),state['state']=='succeeded' and state['result_count']==1 and state['edition_state']=='draft' and state['active'] is None)
            self.verify_candidate(job['id'],metric,month,district)
        missing=self.create(month=3,scenario='no_data')
        state=self.terminal(missing['id'])
        attempts=self.request('GET','/gis/processing-jobs/'+missing['id']+'/attempts')
        result=self.request('GET','/gis/processing-jobs/'+missing['id']+'/result')
        self.record('no_data_failed_without_zero_success_or_cache_loss',state['state']=='failed' and state['result_count']==0 and
            state['edition_state']=='draft' and result['result'] is None and attempts['data'][-1]['validation_report']['error_code']=='PROCESSING_NO_VALID_PIXELS' and self.cache()==self.cache_before)
        transient=self.create(metric='lst',month=3,district='BangKapi',scenario='transient_once')
        state=self.terminal(transient['id'],100)
        self.record('synthetic_outage_auto_retry_then_real_numeric_candidate',state['state']=='succeeded' and state['attempt_count']==2 and state['attempts'][0]['report']['error_code']=='TRANSIENT_SYNTHETIC' and state['result_count']==1)
        self.verify_candidate(transient['id'],'lst',3,'BangKapi')
        self.close(worker)

    def isolation(self):
        # New foreign-protocol fixtures only; no existing job is touched.
        year=self.local.sql("SELECT to_jsonb(y) FROM generate_series(1980,2026)y WHERE NOT EXISTS(SELECT 1 FROM gis.datasets WHERE province='Bangkok Metropolis' AND data_year=y AND kind='ldd_shapefile') ORDER BY y LIMIT 1",read_only=True)
        ds=self.request('POST','/gis/datasets',{'province':'Bangkok Metropolis','data_year':year,'month':0,
            'kind':'ldd_shapefile','purpose':'landuse','title':'P3 SYNTHETIC protocol isolation'},status=201)
        raw=(REPO/'green-area-backend/gis_worker/fixtures/ldd_valid.zip').read_bytes()
        uploaded=self.api.post('/gis/datasets/'+ds['id']+'/ldd-uploads',params={'expected_revision':1},content=raw,
            headers={**self.headers,'Idempotency-Key':str(uuid4()),'Content-Type':'application/zip'})
        self.record('new_ldd_protocol_fixture_uploaded',uploaded.status_code==201)
        upload=uploaded.json()
        ldd=self.request('POST','/gis/editions/'+upload['edition_id']+'/validation-jobs',{'expected_revision':1},status=202)
        from gis_worker.provider import fixture_manifest
        edition=self.request('POST','/gis/datasets/'+ds['id']+'/editions',{'manifest':fixture_manifest('t3-ldd-valid-v2')},status=201)
        v2=self.request('POST','/gis/editions/'+edition['id']+'/validation-jobs',{'expected_revision':1},status=202)
        self.jobs.extend([ldd['id'],v2['id']])
        self.record('processing_claim_ignores_ldd_and_native_v2',self.rpc('claim').get('job') is None and self.state(ldd['id'])['attempt_count']==0 and self.state(v2['id'])['attempt_count']==0)
        worker=self.start(kind='ldd')
        self.record('ldd_pipeline_preserved_after_035',self.terminal(ldd['id'])['state']=='succeeded')
        self.close(worker)
        worker=self.start(kind='v2')
        self.record('v2_pipeline_preserved_after_035',self.terminal(v2['id'])['state']=='succeeded')
        self.close(worker)

    def manual_retry(self):
        # Explicit RPC-level synthetic fault injection, not a claim of a real
        # OS timeout. Backoff and the retry budget are exercised without edits.
        value=self.create(month=4)
        from gis_worker.processing_provider import report_failure
        for attempt in range(1,4):
            claim=m.wait_for(lambda:self.rpc('claim').get('job'),45)
            self.record('fault_injection_claim_attempt_'+str(attempt),claim['id']==value['id'] and claim['attempt_number']==attempt)
            report=report_failure(self.native_request(claim),'NATIVE_TIMEOUT')
            result=self.rpc('fail',{'job_id':claim['id'],'lease_token':claim['lease_token'],'error_code':'transient','report':report})
            self.record('bounded_fault_retry_transition_'+str(attempt),result['state']==('failed' if attempt==3 else 'queued'))
        state=self.state(value['id'])
        duplicate=self.request('POST','/gis/processing-jobs',self.body(month=4),status=200)
        self.record('new_key_does_not_reset_exhausted_budget',duplicate['id']==value['id'] and state['state']=='failed' and state['attempt_count']==3)
        body={'expected_revision':1,'input_hash':value['input_hash'],'reason':'Synthetic timeout budget test complete'}
        self.request('POST','/gis/processing-jobs/'+value['id']+'/retry',{**body,'input_hash':'0'*64},status=409)
        retry=self.request('POST','/gis/processing-jobs/'+value['id']+'/retry',body,status=202)
        self.jobs.append(retry['id'])
        self.record('explicit_retry_child_new_job_same_frozen_inputs',retry['id']!=value['id'] and retry['parent_job_id']==value['id'] and retry['input_hash']==value['input_hash'])
        self.request('POST','/gis/processing-jobs/'+value['id']+'/retry',body,status=409)
        worker=self.start()
        result=self.terminal(retry['id'])
        self.record('manual_retry_actual_child_computes_no_duplicate',result['state']=='succeeded' and result['attempt_count']==1 and result['result_count']==1 and self.state(value['id'])['state']=='failed')
        self.close(worker)

    def recovery(self):
        value=self.create(metric='lst',month=5,scenario='transient_once')
        worker=self.start()
        m.wait_for(lambda:worker.has('claimed',value['id']),25)
        m.wait_for(lambda:worker.has('heartbeat',value['id']),15)
        worker.signal('SIGKILL')
        worker.proc.wait(timeout=10)
        frozen=self.local.sql("SELECT jsonb_build_object('lease_token',lease_token,'worker_id',worker_id) FROM gis.jobs WHERE id="+m.t2.t1.literal(value['id'])+'::uuid',read_only=True)
        self.record('actual_processing_heartbeat_then_sigkill',worker.has('heartbeat',value['id']) and worker.proc.returncode!=0 and self.state(value['id'])['state']=='running')
        self.close(worker)
        replacement=self.start(self.second)
        state=m.wait_for(lambda:(s if (s:=self.state(value['id']))['attempt_count']>=2 else None),105)
        self.record('natural_expired_lease_replacement_recovery',state['attempts'][0]['state']=='expired' and replacement.has('claimed',value['id']))
        self.denied('old_token_completion_fenced_after_recovery',lambda:self.rpc('complete',{'job_id':value['id'],'lease_token':frozen['lease_token'],'report':{}}),{'GIS_STALE_LEASE'})
        state=self.terminal(value['id'])
        self.record('replacement_real_numeric_success_one_candidate',state['state']=='succeeded' and state['attempt_count']==2 and state['result_count']==1 and state['edition_state']=='draft' and state['active'] is None)
        self.close(replacement)

    def finish(self):
        for worker in list(self.workers):
            try:
                self.close(worker)
            except Exception:
                self.rows.append({'name':'owned_worker_cleanup','status':'Fail'})
        after=self.local.baseline()
        for db,before in self.before.items():
            current=after[db]
            self.rows.append({'name':'legacy_and_ledger_preservation_'+db,'status':'Pass' if before['ledger']==current['ledger'] and
                all(current['profiles'].get(k)==v for k,v in before['profiles'].items()) and
                all(current['tables'].get(k)==v for k,v in before['tables'].items() if k!='profiles') else 'Fail'})
        self.local.check_frozen()
        self.rows.append({'name':'legacy_cache_existing_values_unchanged','status':'Pass' if self.cache_before==self.cache() else 'Fail'})
        self.rows.append({'name':'source_unchanged_during_execution','status':'Pass' if self.source==fingerprint() else 'Fail'})
        self.rows.append({'name':'owned_workers_removed','status':'Pass' if not self.local.approved else 'Fail'})
        pending=self.local.sql("SELECT to_jsonb(count(*)) FROM gis.jobs WHERE state IN ('queued','running')",read_only=True)
        self.rows.append({'name':'queue_idle_after_tests','status':'Pass' if pending==0 else 'Fail'})
        equivalence={}
        old_path=self.local.directory/'integration-d2811f282f3c.json'
        if old_path.exists():
            previous=json.loads(old_path.read_text(encoding='utf-8'))['source']['files']
            relocated={f:'green-area-backend/gis_worker/processing_fixtures/'+Path(f).name for f in previous
                if f.startswith('green-area-backend/gis_worker/fixtures/processing_')}
            equivalence['six_fixture_contents_identical_after_move']=len(relocated)==6 and all(
                self.source['files'].get(new)==previous[old] for old,new in relocated.items())
            changed_allowed={'dev/gis_ui/phase3_checks.py','green-area-backend/gis_worker/processing_provider.py',
                'green-area-backend/tests/test_processing_provider.py',*relocated}
            equivalence['other_prior_sources_unchanged']=all(self.source['files'].get(f)==h for f,h in previous.items() if f not in changed_allowed)
            provider=REPO/'green-area-backend/gis_worker/processing_provider.py'
            raw=provider.read_bytes().replace(b"FIXTURE_ROOT = ROOT / 'processing_fixtures'\r\n",b'').replace(
                b"FIXTURE_ROOT = ROOT / 'processing_fixtures'\n",b'').replace(b'fixture_root=FIXTURE_ROOT',b"fixture_root=ROOT / 'fixtures'")
            equivalence['provider_only_default_path_change']=hashlib.sha256(raw).hexdigest()==previous.get(provider.relative_to(REPO).as_posix())
            unit=REPO/'green-area-backend/tests/test_processing_provider.py'
            old_unit=unit.read_bytes().replace(b"p.FIXTURE_ROOT/f'processing_",b"p.ROOT/'fixtures'/f'processing_")
            equivalence['provider_tests_only_fixture_path_change']=hashlib.sha256(old_unit).hexdigest()==previous.get(unit.relative_to(REPO).as_posix())
        result={'type':'actual_local_auth_api_queue_linux_offline_processing','synthetic_only':True,'run_id':self.run_id,'sections':self.sections,
            'source':self.source,'results':self.rows,'worker_events':self.events,
            'source_equivalence_to_prior_40_pass_run':equivalence,
            'counts':{s:sum(r['status']==s for r in self.rows) for s in ('Pass','Fail','Not Tested')},
            'cloud_access':False,'live_gee_tested':False,'credentials_persisted':False,
            'fault_injection':'Manual retry case uses authorized worker RPC transient failures; not real OS timeout',
            'cleanup':'Owned workers removed; new synthetic accounts/rows retained; no cache/data/volume deletion'}
        self.local.write('integration-'+self.run_id+'.json',result)
        self.local.write('integration-latest.json',result)
        print(json.dumps({'counts':result['counts'],'source_sha256':self.source['sha256']}),flush=True)

    def run(self,remaining_only=False):
        self.sections='remaining_after_fixture_directory_fix' if remaining_only else 'full'
        try:
            self.setup()
            if not remaining_only:
                self.contracts_security()
                self.science()
            self.isolation()
            self.manual_retry()
            self.recovery()
        except Exception as error:
            self.rows.append({'name':'suite_execution','status':'Fail','error_type':type(error).__name__})
            print(json.dumps(self.rows[-1]),flush=True)
        finally:
            self.finish()
        return not any(x['status']=='Fail' for x in self.rows)

if __name__=='__main__':
    logging.disable(logging.CRITICAL)
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime-dir',type=Path,required=True)
    parser.add_argument('--remaining-only',action='store_true')
    args=parser.parse_args()
    try:
        sys.exit(0 if Suite(args.runtime_dir).run(args.remaining_only) else 1)
    except Exception as error:
        print(json.dumps({'ok':False,'error_type':type(error).__name__,'code':'PHASE3_INTEGRATION_FAILED'}))
        sys.exit(1)
