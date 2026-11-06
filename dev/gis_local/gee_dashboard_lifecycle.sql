-- 048 rolled-back lifecycle (caller: BEGIN; migration; ledger; this; ROLLBACK).
-- Settings t.actor (officer), t.worker (another profile), t.province come from the caller.
SET LOCAL ROLE gis_owner;
DO $t$ DECLARE a uuid:=current_setting('t.actor')::uuid; w uuid:=current_setting('t.worker')::uuid; p text:=current_setting('t.province');
 r jsonb; r2 jsonb; c jsonb; job jsonb; rep jsonb; m jsonb; prev jsonb; bad jsonb; ok boolean;
BEGIN
 -- options advertise both modes, A6 live gate still false
 r:=gis.processing_read(a,'options','{}');
 IF r->'modes'<>'["offline_synthetic","gee_dashboard"]'::jsonb OR r->'live_enabled'<>'false'::jsonb OR r->>'mode'<>'offline_synthetic' THEN RAISE EXCEPTION 'T_OPTIONS %',r; END IF;
 -- offline manifest byte-identical to the reviewed 035 body
 m:=gis.processing_manifest(jsonb_build_object('province',p,'district',null,'metric','ndvi','data_year',2024,'month',0,'mode','offline_synthetic','scenario','standard','expected_revision',1));
 prev:=gis.dashboard_previous_processing_manifest(jsonb_build_object('province',p,'district',null,'metric','ndvi','data_year',2024,'month',0,'mode','offline_synthetic','scenario','standard','expected_revision',1));
 IF m IS DISTINCT FROM prev OR m->'schema_version'<>'3'::jsonb THEN RAISE EXCEPTION 'T_OFFLINE_MANIFEST_CHANGED'; END IF;
 -- a client cannot inject requested_on or a non-standard GEE scenario
 BEGIN PERFORM gis.processing_command(a,gen_random_uuid(),'create',jsonb_build_object('province',p,'district',null,'metric','ndvi','data_year',2024,'month',0,'mode','gee_dashboard','scenario','standard','expected_revision',1,'requested_on','2020-01-01'));
   RAISE EXCEPTION 'T_REQUESTED_ON_ACCEPTED'; EXCEPTION WHEN raise_exception THEN IF SQLERRM<>'GIS_INVALID_PAYLOAD' THEN RAISE; END IF; END;
 BEGIN PERFORM gis.processing_command(a,gen_random_uuid(),'create',jsonb_build_object('province',p,'district',null,'metric','ndvi','data_year',2024,'month',0,'mode','gee_dashboard','scenario','no_data','expected_revision',1));
   RAISE EXCEPTION 'T_SCENARIO_ACCEPTED'; EXCEPTION WHEN raise_exception THEN IF SQLERRM<>'GIS_INVALID_PAYLOAD' THEN RAISE; END IF; END;
 BEGIN PERFORM gis.processing_command(a,gen_random_uuid(),'create',jsonb_build_object('province',p,'district',null,'metric','ndvi','data_year',2024,'month',0,'mode','gee_live','scenario','standard','expected_revision',1));
   RAISE EXCEPTION 'T_UNKNOWN_MODE_ACCEPTED'; EXCEPTION WHEN raise_exception THEN IF SQLERRM<>'GIS_GEE_LIVE_DISABLED' THEN RAISE; END IF; END;
 -- create GEE annual NDVI job
 c:=gis.processing_command(a,'aaaaaaaa-0000-4000-8000-000000000001','create',jsonb_build_object('province',p,'district',null,'metric','ndvi','data_year',2024,'month',0,'mode','gee_dashboard','scenario','standard','expected_revision',1));
 IF c->'status'<>'202'::jsonb OR c->'body'->>'mode'<>'gee_dashboard' OR c->'body'->'metadata'->>'cache_table'<>'ndvi_annual'
   OR c->'body'->'metadata'->>'requested_on'<>to_char((clock_timestamp() AT TIME ZONE 'UTC')::date,'YYYY-MM-DD') THEN RAISE EXCEPTION 'T_CREATE %',c; END IF;
 -- same scope, same day, new key -> same job (no duplicate GEE run)
 r:=gis.processing_command(a,'aaaaaaaa-0000-4000-8000-000000000002','create',jsonb_build_object('province',p,'district',null,'metric','ndvi','data_year',2024,'month',0,'mode','gee_dashboard','scenario','standard','expected_revision',1));
 IF r->'body'->>'id'<>c->'body'->>'id' THEN RAISE EXCEPTION 'T_DEDUP'; END IF;
 IF gis.edition_protocol((SELECT edition_id FROM gis.jobs WHERE id=(c->'body'->>'id')::uuid))<>'gee_dashboard' THEN RAISE EXCEPTION 'T_PROTOCOL'; END IF;
 -- the offline worker never claims it (another queued offline job may exist locally)
 r:=gis.queue_protocol_kind('claim',jsonb_build_object('worker_id',w),'gee_offline');
 IF r->'job'->>'id'=c->'body'->>'id' OR (r->'job'<>'null'::jsonb AND gis.edition_protocol((r->'job'->>'edition_id')::uuid)<>'gee_offline') THEN
   RAISE EXCEPTION 'T_OFFLINE_CLAIMED_GEE %',r; END IF;
 IF r->'job'<>'null'::jsonb THEN RAISE EXCEPTION 'T_LOCAL_QUEUE_NOT_IDLE'; END IF;
 job:=gis.queue_protocol_kind('claim',jsonb_build_object('worker_id',w),'gee_dashboard')->'job';
 IF job->>'id'<>c->'body'->>'id' OR job->>'processing_id' IS NULL OR job->'manifest'->>'provider'<>'gee_dashboard' THEN RAISE EXCEPTION 'T_CLAIM %',job; END IF;
 PERFORM set_config('t.job',job::text,false);
 rep:=jsonb_build_object('schema_version',1,'provider_build','gee-dashboard-v1','mode','gee_dashboard','synthetic',false,
   'processing_id',job->>'processing_id','input_hash',job->>'input_hash','input_revision',job->'input_revision','valid',true,'error_code',null,
   'statistics',jsonb_build_object('valid_pixels',null,'mean',0.4512,'min',-0.12,'max',0.91),'metadata',job->'manifest',
   'observation',jsonb_build_object('from_cache',false,'cached_at',null,'image_count',null,'data_quality',jsonb_build_object('n_images',41)),
   'cache',jsonb_build_object('table','ndvi_annual','province',p,'district',null,'year',2024,'month',0,'written',true));
 -- negative reports (each rejected, nothing recorded)
 FOR bad IN SELECT x FROM unnest(ARRAY[
   rep||'{"synthetic":true}', rep||'{"mode":"offline_synthetic"}', rep||'{"provider_build":"gee-offline-v1"}',
   jsonb_set(rep,'{statistics,mean}','3'), jsonb_set(rep,'{statistics,min}','0.6'), jsonb_set(rep,'{statistics,min}','null'),
   jsonb_set(rep,'{statistics,valid_pixels}','4'), jsonb_set(rep,'{cache,table}','"ndvi_monthly"'), jsonb_set(rep,'{cache,written}','false'),
   jsonb_set(rep,'{cache,year}','2023'), jsonb_set(rep,'{metadata,requested_on}','"2020-01-01"'), rep-'observation', rep||'{"extra":1}',
   jsonb_set(rep,'{observation,image_count}','-1'), rep||'{"error_code":"X"}']) x LOOP
   ok:=false;
   BEGIN PERFORM gis.queue_protocol_kind('complete',jsonb_build_object('job_id',job->>'id','worker_id',w,'lease_token',job->>'lease_token','report',bad),'gee_dashboard');
   EXCEPTION WHEN raise_exception THEN ok:=SQLERRM LIKE 'GIS_%'; END;
   IF NOT ok THEN RAISE EXCEPTION 'T_BAD_REPORT_ACCEPTED %',bad; END IF;
 END LOOP;
 -- wrong protocol cannot complete it
 ok:=false; BEGIN PERFORM gis.queue_protocol_kind('complete',jsonb_build_object('job_id',job->>'id','worker_id',w,'lease_token',job->>'lease_token','report',rep),'gee_offline');
 EXCEPTION WHEN insufficient_privilege THEN ok:=true; END; IF NOT ok THEN RAISE EXCEPTION 'T_CROSS_PROTOCOL'; END IF;
 r:=gis.queue_protocol_kind('complete',jsonb_build_object('job_id',job->>'id','worker_id',w,'lease_token',job->>'lease_token','report',rep),'gee_dashboard');
 IF r->>'state'<>'succeeded' THEN RAISE EXCEPTION 'T_COMPLETE %',r; END IF;
 PERFORM set_config('t.result',r::text,false);
END $t$;
-- Check the deferred catalog triggers for block one, then defer again for block two.
SET CONSTRAINTS ALL IMMEDIATE;
SET CONSTRAINTS ALL DEFERRED;

DO $t2$ DECLARE a uuid:=current_setting('t.actor')::uuid; w uuid:=current_setting('t.worker')::uuid; p text:=current_setting('t.province');
 job jsonb:=current_setting('t.job')::jsonb; r jsonb; c jsonb; j2 jsonb; rep jsonb; fr jsonb;
BEGIN
 r:=gis.processing_read(a,'job',jsonb_build_object('id',job->>'id'));
 IF r->>'candidate_status'<>'dashboard_cache_written' OR r->'result'->>'provider'<>'gee_dashboard' OR r->'result'->>'mode'<>'gee_dashboard'
   OR r->'result'->'report'->'statistics'->>'mean'<>'0.4512' THEN RAISE EXCEPTION 'T_READ %',r; END IF;
 IF EXISTS(SELECT 1 FROM gis.datasets d JOIN gis.jobs q ON q.edition_id=d.active_edition_id WHERE q.id=(job->>'id')::uuid)
   OR (SELECT e.state FROM gis.editions e JOIN gis.jobs q ON q.edition_id=e.id WHERE q.id=(job->>'id')::uuid)<>'draft'
   OR gis.eligible((SELECT edition_id FROM gis.jobs WHERE id=(job->>'id')::uuid),NULL) THEN RAISE EXCEPTION 'T_ACTIVATED'; END IF;
 -- monthly LST: mean only, transient failure then success on retry attempt
 c:=gis.processing_command(a,'aaaaaaaa-0000-4000-8000-000000000003','create',jsonb_build_object('province',p,'district',null,'metric','lst','data_year',2023,'month',4,'mode','gee_dashboard','scenario','standard','expected_revision',1));
 IF c->'body'->'metadata'->>'cache_table'<>'province_lst_monthly' THEN RAISE EXCEPTION 'T_MONTHLY_TABLE'; END IF;
 j2:=gis.queue_protocol_kind('claim',jsonb_build_object('worker_id',w),'gee_dashboard')->'job';
 fr:=jsonb_build_object('schema_version',1,'provider_build','gee-dashboard-v1','mode','gee_dashboard','synthetic',false,
   'processing_id',j2->>'processing_id','input_hash',j2->>'input_hash','input_revision',j2->'input_revision','valid',false,'error_code','NATIVE_PROCESS_FAILED',
   'statistics',jsonb_build_object('valid_pixels',null,'mean',null,'min',null,'max',null),'metadata',j2->'manifest','observation',null,'cache',null);
 r:=gis.queue_protocol_kind('fail',jsonb_build_object('job_id',j2->>'id','worker_id',w,'lease_token',j2->>'lease_token','error_code','transient','report',fr),'gee_dashboard');
 IF r->>'state'<>'queued' THEN RAISE EXCEPTION 'T_TRANSIENT %',r; END IF;
 UPDATE gis.jobs SET available_at=clock_timestamp() WHERE id=(j2->>'id')::uuid;
 j2:=gis.queue_protocol_kind('claim',jsonb_build_object('worker_id',w),'gee_dashboard')->'job';
 rep:=fr||jsonb_build_object('lease',null)-'lease'||jsonb_build_object('valid',true,'error_code',null,
   'statistics',jsonb_build_object('valid_pixels',null,'mean',31.27,'min',null,'max',null),
   'observation',jsonb_build_object('from_cache',false,'cached_at',null,'image_count',3,'data_quality',null),
   'cache',jsonb_build_object('table','province_lst_monthly','province',p,'district',null,'year',2023,'month',4,'written',true));
 BEGIN PERFORM gis.queue_protocol_kind('complete',jsonb_build_object('job_id',j2->>'id','worker_id',w,'lease_token',j2->>'lease_token',
     'report',jsonb_set(rep,'{statistics,max}','40')),'gee_dashboard'); RAISE EXCEPTION 'T_MONTHLY_EXTREMA';
 EXCEPTION WHEN raise_exception THEN IF SQLERRM NOT LIKE 'GIS_%' THEN RAISE; END IF; END;
 BEGIN PERFORM gis.queue_protocol_kind('complete',jsonb_build_object('job_id',j2->>'id','worker_id',w,'lease_token',j2->>'lease_token',
     'report',jsonb_set(rep,'{observation,image_count}','0')),'gee_dashboard'); RAISE EXCEPTION 'T_MONTHLY_ZERO_IMAGES';
 EXCEPTION WHEN raise_exception THEN IF SQLERRM NOT LIKE 'GIS_%' THEN RAISE; END IF; END;
 r:=gis.queue_protocol_kind('complete',jsonb_build_object('job_id',j2->>'id','worker_id',w,'lease_token',j2->>'lease_token','report',rep),'gee_dashboard');
 IF r->>'state'<>'succeeded' THEN RAISE EXCEPTION 'T_MONTHLY_COMPLETE %',r; END IF;
 -- no-data outcome: completes as invalid_data (failed, not retried)
 c:=gis.processing_command(a,'aaaaaaaa-0000-4000-8000-000000000004','create',jsonb_build_object('province',p,'district',null,'metric','ndvi','data_year',2019,'month',2,'mode','gee_dashboard','scenario','standard','expected_revision',1));
 j2:=gis.queue_protocol_kind('claim',jsonb_build_object('worker_id',w),'gee_dashboard')->'job';
 fr:=jsonb_set(jsonb_set(jsonb_set(fr,'{processing_id}',to_jsonb(j2->>'processing_id')),'{input_hash}',to_jsonb(j2->>'input_hash')),'{metadata}',j2->'manifest')||'{"error_code":"PROCESSING_NO_VALID_PIXELS"}';
 r:=gis.queue_protocol_kind('complete',jsonb_build_object('job_id',j2->>'id','worker_id',w,'lease_token',j2->>'lease_token','report',fr),'gee_dashboard');
 IF r->>'state'<>'failed' OR r->>'error_code'<>'invalid_data' THEN RAISE EXCEPTION 'T_NO_DATA %',r; END IF;
 -- offline mode still works end-to-end on its own protocol
 c:=gis.processing_command(a,'aaaaaaaa-0000-4000-8000-000000000005','create',jsonb_build_object('province',p,'district',null,'metric','ndvi','data_year',2024,'month',0,'mode','offline_synthetic','scenario','standard','expected_revision',1));
 IF c->'body'->>'mode'<>'offline_synthetic' OR c->'body'->'metadata'->'schema_version'<>'3'::jsonb THEN RAISE EXCEPTION 'T_OFFLINE_CREATE'; END IF;
 IF gis.queue_protocol_kind('claim',jsonb_build_object('worker_id',w),'gee_dashboard')->'job'<>'null'::jsonb THEN RAISE EXCEPTION 'T_GEE_CLAIMED_OFFLINE'; END IF;
 j2:=gis.queue_protocol_kind('claim',jsonb_build_object('worker_id',w),'gee_offline')->'job';
 IF j2->>'id' IS DISTINCT FROM c->'body'->>'id' THEN RAISE EXCEPTION 'T_OFFLINE_CLAIM'; END IF;
 r:=gis.processing_read(a,'jobs','{}');
 IF jsonb_array_length(r->'data')<4 THEN RAISE EXCEPTION 'T_LIST'; END IF;
 RAISE NOTICE 'LIFECYCLE_048_PASS';
END $t2$;
SET CONSTRAINTS ALL IMMEDIATE;
