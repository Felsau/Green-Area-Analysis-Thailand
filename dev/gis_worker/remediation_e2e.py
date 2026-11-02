"""Real local JWT/API/Linux-process T3 acceptance tests. Synthetic data only."""
from __future__ import annotations
import argparse, copy, importlib.util, json, logging, secrets, sys, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

spec=importlib.util.spec_from_file_location('remediation_local',Path(__file__).with_name('remediation_local.py'))
m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m)
sys.path.insert(0,str(m.REPO/'green-area-backend'))
from gis_worker import provider
from starlette.testclient import TestClient
from gis_app import create_app

class Suite:
    def __init__(self,root):
        self.local=m.Local(root);self.rows=[];self.workers=[];self.events=[];self.datasets={};self.jobs=[]
        self.source=m.fingerprint()
    def record(self,name,passed,**evidence):
        row={'name':name,'status':'Pass' if passed else 'Fail',**evidence};self.rows.append(row)
        print(json.dumps(row),flush=True)
        if not passed:raise AssertionError(name)
    def rpc(self,action,payload=None,identity=None):
        return (identity or self.identity).client.rpc('gis_worker_v2',{'p_action':action,'p_payload':payload or {}}).execute().data
    def denied(self,name,call,expected):
        try:call()
        except Exception as error:
            code=str(getattr(error,'code',''));message=str(getattr(error,'message',''))
            self.record(name,code in expected or message in expected,error_code=code)
            return
        self.record(name,False)
    def setup(self):
        self.local.attest();self.local.check_frozen()
        self.identity=m.identity_module.provision(self.local)
        self.second=m.identity_module.provision(self.local)
        ready=self.identity.client.rpc('gis_worker_readiness_v2',{}).execute().data
        self.record('real_worker_jwt_readiness_matches_local',ready['subject']==self.identity.subject and ready['runtime_instance']==self.local.db.instance and 32 in ready['migration_versions'])
        anon,service=self.local.local_keys();operator=self.local.client(service)
        email='gis-t3-remediation-'+uuid4().hex+'@example.invalid';pw=secrets.token_urlsafe(30)
        created=operator.auth.admin.create_user({'email':email,'password':pw,'email_confirm':True})
        self.local.sql("INSERT INTO gis.officers(user_id) VALUES("+m.t2.t1.literal(str(created.user.id))+"::uuid)")
        c=self.local.client(anon);session=c.auth.sign_in_with_password({'email':email,'password':pw}).session
        self.headers={'Authorization':'Bearer '+session.access_token}
        self.api=TestClient(create_app(self.local.runtime()),base_url='http://127.0.0.1:55422')
        self.record('queue_initially_idle',self.local.sql("SELECT to_jsonb(count(*)) FROM gis.jobs WHERE state IN ('queued','running')",read_only=True)==0)
    def post(self,path,body,status):
        r=self.api.post(path,json=body,headers={**self.headers,'Idempotency-Key':str(uuid4())})
        if r.status_code!=status:
            detail=r.json().get('detail',{})
            code=detail.get('code') if isinstance(detail,dict) else 'INPUT_VALIDATION'
            print(json.dumps({'local_api_status':r.status_code,'expected':status,'api_code':code,'route':path.split('/')[2]}),flush=True)
            raise RuntimeError('LOCAL_API_STATUS_MISMATCH')
        return r.json()
    def create(self,fid):
        if fid.endswith('-v1'):
            fixture=self.local.sql("SELECT to_jsonb(f) FROM gis.synthetic_fixtures f WHERE id="+m.t2.t1.literal(fid),read_only=True)
            manifest=fixture['manifest'];kind,purpose=fixture['kind'],fixture['purpose']
        else:
            entry=provider.load_registry()['entries'][fid];manifest=entry['manifest']
            kind='ldd_shapefile' if manifest['data_kind']=='polygon' else 'geotiff';purpose=entry['purpose']
        key=(kind,purpose)
        if key not in self.datasets:
            month=0 if kind=='ldd_shapefile' else 1
            identity=self.local.sql("SELECT jsonb_build_object('province',p.name_en,'data_year',y,'month',"+str(month)+",'kind',"+m.t2.t1.literal(kind)+",'purpose',"+m.t2.t1.literal(purpose)+") FROM public.provinces p CROSS JOIN generate_series(1980,2026)y WHERE NOT EXISTS(SELECT 1 FROM gis.datasets d WHERE d.province=p.name_en AND d.data_year=y AND d.month="+str(month)+" AND d.kind="+m.t2.t1.literal(kind)+" AND d.purpose="+m.t2.t1.literal(purpose)+") ORDER BY p.name_en,y LIMIT 1",read_only=True)
            self.datasets[key]=self.post('/gis/datasets',{**identity,'title':'T3 synthetic remediation'},201)['id']
        ds=self.datasets[key]
        edition=self.post('/gis/datasets/'+ds+'/editions',{'manifest':manifest},201)
        job=self.post('/gis/editions/'+edition['id']+'/validation-jobs',{'expected_revision':1},202)
        self.jobs.append(job['id'])
        return job['id']
    def state(self,job):
        return self.local.sql("SELECT jsonb_build_object('state',j.state,'worker_id',j.worker_id,'lease_until',j.lease_until,'progress',j.progress,'attempt_count',j.attempt_count,'input_hash',j.input_hash,'input_revision',j.input_revision,'edition_state',e.state,'active',d.active_edition_id,'attempts',(SELECT jsonb_agg(jsonb_build_object('state',a.state,'report',a.validation_report,'progress',a.progress,'error_code',a.error_code) ORDER BY attempt_no) FROM gis.attempts a WHERE a.job_id=j.id)) FROM gis.jobs j JOIN gis.editions e ON e.id=j.edition_id JOIN gis.datasets d ON d.id=e.dataset_id WHERE j.id="+m.t2.t1.literal(job)+"::uuid",read_only=True)
    def start(self,identity=None):
        w=m.ContainerWorker(self.local,identity or self.identity);self.workers.append(w)
        m.wait_for(lambda:w.has('ready') or w.has('fatal'),20)
        self.record('linux_worker_started_'+str(len(self.workers)),w.has('ready') and not w.has('fatal'))
        return w
    def close(self,w):
        w.close();self.events.extend(w.events);self.workers.remove(w)
    def report(self,job):
        return {'schema_version':2,'fixture_id':job['manifest']['fixture_id'],'artifact_sha256':job['manifest']['sha256'],
            'input_hash':job['input_hash'],'input_revision':job['input_revision'],'provider_build':'t3-native-v1','valid':True,
            'checks':['synthetic_fixture_match','metadata_shape','source_hash_match','bounded_input','native_validation','scientific_expected_results'],
            'warnings':[],'statistics':{'feature_count':3,'total_area_m2':6400,'unknown_area_m2':0,'area_U_m2':3200,'area_A_m2':3200,'unknown_code_count':0},'error_code':None}
    def security(self):
        self.denied('worker_backend_admin_rpc_denied',lambda:self.identity.client.rpc('gis_command',{'p_actor':self.identity.subject,'p_request_id':str(uuid4()),'p_operation':'grant_officer','p_payload':{}}).execute(),{'42501'})
        self.denied('worker_backend_read_rpc_denied',lambda:self.identity.client.rpc('gis_read',{'p_actor':self.identity.subject,'p_kind':'me','p_payload':{}}).execute(),{'42501'})
        self.denied('worker_direct_profile_read_denied',lambda:self.identity.client.table('profiles').select('id').limit(1).execute(),{'42501'})
        self.denied('worker_legacy_rpc_denied',lambda:self.identity.client.rpc('gis_worker',{'p_action':'claim','p_payload':{'worker_id':self.identity.subject}}).execute(),{'42501'})
        self.denied('jwt_worker_identity_spoof_rejected',lambda:self.rpc('claim',{'worker_id':str(uuid4())}),{'42501','GIS_WORKER_IDENTITY_MISMATCH'})
        jid=self.create('t3-ldd-valid-v2');job=self.rpc('claim')['job'];lease={'job_id':jid,'lease_token':job['lease_token']}
        self.record('worker_id_derived_from_real_jwt',self.state(jid)['worker_id']==self.identity.subject)
        good=self.report(job)
        for key,value in [('artifact_sha256','0'*64),('input_hash','0'*64),('input_revision',99),('schema_version',1),('checks',[]),('provider_build','untrusted')]:
            bad=copy.deepcopy(good);bad[key]=value
            self.denied('native_report_rejects_'+key,lambda bad=bad:self.rpc('complete',{**lease,'report':bad}),{'GIS_NATIVE_REPORT_INVALID','GIS_NATIVE_REPORT_REQUIRED','GIS_NATIVE_SCIENTIFIC_INVARIANT'})
        bad=copy.deepcopy(good);bad['statistics']['total_area_m2']=1
        self.denied('scientific_report_forged_area_rejected',lambda:self.rpc('complete',{**lease,'report':bad}),{'GIS_NATIVE_SCIENTIFIC_INVARIANT'})
        self.denied('wrong_lease_token_complete_rejected',lambda:self.rpc('complete',{'job_id':jid,'lease_token':str(uuid4()),'report':good}),{'GIS_STALE_LEASE'})
        self.denied('other_worker_identity_complete_rejected',lambda:self.rpc('complete',{**lease,'report':good},self.second),{'GIS_STALE_LEASE'})
        self.record('invalid_reports_leave_attempt_running',self.state(jid)['state']=='running' and self.state(jid)['attempts'][0]['report'] is None)
        legacy=self.local.sql("SELECT public.gis_worker('complete',"+m.t2.t1.literal(json.dumps({**lease,'worker_id':self.identity.subject,'report':{'valid':True,'fixture_id':'t3-ldd-valid-v2','checks':[]}}))+"::jsonb)",role='gis_worker',check=False)
        self.record('legacy_worker_cannot_complete_native_v2',legacy.returncode!=0 and 'GIS_WORKER_PROTOCOL_MISMATCH' in legacy.stderr)
        rid=str(uuid4())
        body=("UPDATE gis.attempts SET state='succeeded',progress=100,finished_at=clock_timestamp() WHERE job_id='"+jid+"'::uuid AND state='running';"
            +"INSERT INTO gis.results(id,job_id,edition_id,input_revision,input_hash,validator_version,attempt_no,lease_token,valid,report) SELECT '"+rid+"'::uuid,id,edition_id,input_revision,input_hash,validator_version,attempt_count,lease_token,true,"+m.t2.t1.literal(json.dumps(good))+"::jsonb FROM gis.jobs WHERE id='"+jid+"'::uuid;"
            +"UPDATE gis.editions SET state='validated',validated_result_id='"+rid+"'::uuid WHERE id='"+job['edition_id']+"'::uuid;"
            +"UPDATE gis.jobs SET state='succeeded',worker_id=NULL,lease_token=NULL,lease_until=NULL,progress=100,finished_at=clock_timestamp() WHERE id='"+jid+"'::uuid")
        bypass=self.local.sql(body,check=False)
        self.record('deferred_invariant_blocks_owner_native_report_bypass',bypass.returncode!=0 and 'GIS_NATIVE_REPORT_REQUIRED' in bypass.stderr and self.state(jid)['state']=='running')
        self.rpc('complete',{**lease,'report':good})
        self.record('native_report_atomic_success_no_activation',self.state(jid)['state']=='succeeded' and self.state(jid)['active'] is None)
        # Two actual JWT requests race for exactly one newly queued job.
        jid=self.create('t3-ldd-valid-v2')
        with ThreadPoolExecutor(max_workers=2) as pool:
            claims=list(pool.map(lambda i:self.rpc('claim',identity=i),(self.identity,self.second)))
        claimed=[(i,r['job']) for i,r in zip((self.identity,self.second),claims) if r.get('job')]
        self.record('concurrent_real_jwt_claim_exactly_once',len(claimed)==1 and claimed[0][1]['id']==jid and self.state(jid)['attempt_count']==1)
        who,job=claimed[0];self.rpc('complete',{'job_id':jid,'lease_token':job['lease_token'],'report':self.report(job)},who)
    def isolation(self):
        v1=self.create('ldd-valid-v1')
        self.record('native_claim_ignores_v1_queue',self.rpc('claim').get('job') is None and self.state(v1)['attempt_count']==0)
        v2=self.create('t3-ldd-valid-v2')
        v1lease=self.local.sql("SELECT public.gis_worker('claim',"+m.t2.t1.literal(json.dumps({'worker_id':str(uuid4())}))+"::jsonb)",role='gis_worker')
        self.record('legacy_claim_selects_v1_only',v1lease['job_id']==v1 and self.state(v2)['state']=='queued')
        self.local.sql("UPDATE gis.jobs SET lease_until=clock_timestamp()-interval '1 second' WHERE id="+m.t2.t1.literal(v1)+"::uuid")
        self.record('native_recovery_does_not_touch_expired_v1',self.rpc('recover')['recovered']==0 and self.state(v1)['state']=='running')
        self.local.sql("SELECT public.gis_worker('recover','{}')",role='gis_worker')
        time.sleep(8)
        lease=self.local.sql("SELECT public.gis_worker('claim',"+m.t2.t1.literal(json.dumps({'worker_id':str(uuid4())}))+"::jsonb)",role='gis_worker')
        self.local.sql("SELECT public.gis_worker('complete',"+m.t2.t1.literal(json.dumps({**{k:lease[k] for k in ('job_id','worker_id','lease_token')},'report':{'valid':True,'fixture_id':'ldd-valid-v1','checks':['synthetic_fixture_match']}}))+"::jsonb)",role='gis_worker')
        self.record('v1_retry_and_response_preserved',self.state(v1)['state']=='succeeded' and self.state(v1)['attempts'][-1]['report'] is None)
        w=self.start();m.wait_for(lambda:self.state(v2)['state']=='succeeded',30);self.close(w)
        self.record('v2_after_v1_isolation_succeeds',self.state(v2)['state']=='succeeded')
    def science(self):
        # One durable Linux daemon handles consecutive API-submitted jobs.
        w=self.start()
        for fid in ('t3-ldd-valid-v2','t3-ldd-cp874-v2','t3-ldd-composite-v2','t3-s2-v2','t3-lst-v2','t3-ndvi-ready-v2','t3-lst-ready-v2','t3-kelvin-v2','t3-unknown-v2','t3-zip-unsafe-v2','t3-zip-symlink-v2','t3-ldd-missing-v2','t3-nodata-v2','t3-transient-v2'):
            jid=self.create(fid);state=m.wait_for(lambda:(s if (s:=self.state(jid))['state'] in ('succeeded','failed') else None),60)
            expected=provider.load_registry()['entries'][fid]['expected'].get('valid',False)
            self.record('linux_api_queue_scientific_'+fid,state['state']==('succeeded' if expected else 'failed') and state['active'] is None and state['attempts'][-1]['report'] is not None)
            if fid=='t3-transient-v2':self.record('transient_retry_then_success',state['attempt_count']==2 and state['attempts'][0]['report']['error_code']=='TRANSIENT_SYNTHETIC')
            r=self.api.get('/gis/jobs/'+jid+'/attempts',headers=self.headers)
            self.record('native_report_api_projection_'+fid,r.status_code==200 and bool(r.json()['data'][-1]['validation_report']))
        self.close(w)
    def lifecycle(self):
        # This job really runs >15s. No lease backdating or availability edits.
        jid=self.create('t3-timeout-v2');first=self.start();m.wait_for(lambda:first.has('claimed',jid),20)
        frozen=self.local.sql("SELECT jsonb_build_object('job_id',id,'lease_token',lease_token,'input_hash',input_hash,'input_revision',input_revision) FROM gis.jobs WHERE id="+m.t2.t1.literal(jid)+"::uuid",read_only=True)
        first.signal('SIGKILL');first.proc.wait(timeout=10)
        self.record('actual_linux_worker_sigkill',first.proc.returncode!=0 and self.state(jid)['state']=='running')
        replacement=self.start(self.second)
        m.wait_for(lambda:self.state(jid)['attempt_count']==2,85)
        self.record('replacement_recovers_real_expired_lease',self.state(jid)['attempts'][0]['state']=='expired' and replacement.has('claimed',jid))
        self.denied('expired_old_worker_complete_fenced',lambda:self.rpc('complete',{'job_id':jid,'lease_token':frozen['lease_token'],'report':{}}),{'GIS_STALE_LEASE'})
        m.wait_for(lambda:replacement.has('heartbeat',jid),15)
        self.record('heartbeat_during_long_running_native_child',self.state(jid)['progress']>0)
        replacement.signal('SIGTERM');replacement.proc.wait(timeout=20)
        state=self.state(jid)
        self.record('sigterm_graceful_shutdown_requeues_job',replacement.has('stopped') and replacement.proc.returncode==0 and state['state']=='queued' and state['attempts'][-1]['report']['error_code']=='WORKER_SHUTDOWN')
        self.close(first);self.close(replacement)
        finisher=self.start();state=m.wait_for(lambda:(s if (s:=self.state(jid))['state']=='failed' else None),75);self.close(finisher)
        self.record('native_timeout_bounded_and_retry_budget_enforced',state['attempt_count']==3 and state['attempts'][-1]['report']['error_code']=='NATIVE_TIMEOUT' and state['edition_state']=='draft')
        jid=self.create('t3-oom-v2');w=self.start();state=m.wait_for(lambda:(s if (s:=self.state(jid))['state']=='failed' else None),70);self.close(w)
        self.record('actual_native_memory_limit_is_transient_not_invalid_gis',state['attempt_count']==3 and all(a['report']['error_code']=='NATIVE_MEMORY_LIMIT' and a['error_code']=='transient' for a in state['attempts']))
        idle=self.start();idle.signal('SIGINT');idle.proc.wait(timeout=20)
        self.record('sigint_idle_worker_stops_cleanly',idle.proc.returncode==0 and idle.has('stopped'))
        self.close(idle)
    def run(self):
        try:
            self.setup();self.security();self.isolation();self.science();self.lifecycle()
        except Exception as error:
            self.rows.append({'name':'suite_execution','status':'Fail','error_type':type(error).__name__})
            print(json.dumps(self.rows[-1]),flush=True)
        finally:
            for w in list(self.workers):
                try:self.close(w)
                except Exception:self.rows.append({'name':'worker_cleanup','status':'Fail'})
            self.local.check_frozen()
            same=self.source==m.fingerprint()
            self.rows.append({'name':'source_fingerprint_unchanged_during_run','status':'Pass' if same else 'Fail'})
            result={'type':'actual_local_linux_worker_remediation_e2e','source':self.source,'results':self.rows,
                    'counts':{s:sum(x['status']==s for x in self.rows) for s in ('Pass','Fail')},'synthetic_only':True,
                    'cloud_access':False,'worker_credentials_persisted':False}
            result['worker_events']=self.events
            self.local.write('e2e-'+uuid4().hex+'.json',result)
            self.local.write('e2e-results.json',result)
            print(json.dumps({'counts':result['counts'],'source_sha256':self.source['sha256']}),flush=True)
        return not any(r['status']=='Fail' for r in self.rows)

if __name__=='__main__':
    logging.disable(logging.CRITICAL)
    p=argparse.ArgumentParser();p.add_argument('--runtime-dir',type=Path,required=True);args=p.parse_args()
    sys.exit(0 if Suite(args.runtime_dir).run() else 1)
