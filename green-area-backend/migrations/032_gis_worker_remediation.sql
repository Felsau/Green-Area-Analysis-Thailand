-- T3 remediation, forward-only. The attested local runner owns BEGIN and ledger INSERT.
-- Applied migration files/ledger rows and existing GIS/legacy history are never rewritten.
GRANT CREATE ON SCHEMA public TO gis_owner;
SET LOCAL ROLE gis_owner;
SELECT gis.assert_environment();
DO $guard$
BEGIN
 IF current_database() NOT IN ('postgres','gis_t1_upgrade')
    OR current_setting('cluster_name') <> 'green-area-gis-t0'
    OR NOT EXISTS(SELECT 1 FROM gis.environment WHERE singleton
      AND runtime_instance=current_setting('gis.runtime_instance',true)
      AND baseline_fingerprint=current_setting('gis.baseline_fingerprint',true))
    OR NOT EXISTS(SELECT 1 FROM gis.schema_migrations WHERE version=31
      AND sha256='85d345fa5b8dca615735618f7d9e689646dc4a286c285e0601b51f410192269c')
    OR EXISTS(SELECT 1 FROM gis.schema_migrations WHERE version>=32) THEN
   RAISE EXCEPTION 'GIS_LOCAL_BASELINE_031_REQUIRED';
 END IF;
 IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='gis_native_worker'
   AND NOT rolsuper AND NOT rolcanlogin AND NOT rolbypassrls AND NOT rolcreatedb
   AND NOT rolcreaterole AND NOT rolreplication AND NOT rolinherit)
   OR EXISTS(SELECT 1 FROM pg_auth_members WHERE member='gis_native_worker'::regrole) THEN
   RAISE EXCEPTION 'GIS_NATIVE_ROLE_BOUNDARY_REQUIRED';
 END IF;
END $guard$;

-- Only PostgREST may supply this authenticated context. A SECURITY DEFINER's
-- current_user is gis_owner, so check the session and SET LOCAL ROLE as well.
CREATE FUNCTION gis.native_subject() RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE claims jsonb; subject uuid;
BEGIN
 PERFORM gis.assert_environment();
 IF session_user<>'authenticator' OR current_setting('role',true)<>'gis_native_worker' THEN
   RAISE EXCEPTION 'GIS_NATIVE_IDENTITY_REQUIRED' USING ERRCODE='42501'; END IF;
 claims:=NULLIF(current_setting('request.jwt.claims',true),'')::jsonb;
 IF claims->>'role' IS DISTINCT FROM 'gis_native_worker'
   OR claims->>'iss' IS DISTINCT FROM 'http://127.0.0.1:55421/auth/v1'
   OR COALESCE(claims->>'sub','') !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' THEN
   RAISE EXCEPTION 'GIS_NATIVE_IDENTITY_REQUIRED' USING ERRCODE='42501'; END IF;
 subject:=(claims->>'sub')::uuid;
 RETURN subject;
END $f$;

-- Exact bounded report contract. Native code calculates GIS values; SQL checks
-- frozen input identity, typed outputs and mandatory scientific validation attestations.
CREATE FUNCTION gis.validate_native_report(p_report jsonb,p_manifest jsonb,p_hash text,p_revision integer)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE item jsonb; key_name text; value jsonb; row_value jsonb; count_values integer:=0;
 infrastructure boolean; required_checks jsonb; expected_values jsonb; actual_value jsonb;
 row_index integer; column_index integer; expected_count integer; expected_mean numeric;
 expected_min numeric; expected_max numeric;
BEGIN
 IF jsonb_typeof(p_report) IS DISTINCT FROM 'object' OR octet_length(p_report::text)>16384
   OR NOT p_report ?& ARRAY['schema_version','fixture_id','artifact_sha256','input_hash','input_revision',
     'provider_build','valid','checks','warnings','statistics','error_code'] THEN
   RAISE EXCEPTION 'GIS_NATIVE_REPORT_REQUIRED'; END IF;
 PERFORM gis.keys(p_report,ARRAY['schema_version','fixture_id','artifact_sha256','input_hash','input_revision',
   'provider_build','valid','checks','warnings','statistics','error_code','values']);
 IF p_manifest->'schema_version' IS DISTINCT FROM '2'::jsonb
   OR p_report->'schema_version' IS DISTINCT FROM '2'::jsonb
   OR jsonb_typeof(p_report->'fixture_id') IS DISTINCT FROM 'string'
   OR p_report->>'fixture_id' IS DISTINCT FROM p_manifest->>'fixture_id'
   OR jsonb_typeof(p_report->'artifact_sha256') IS DISTINCT FROM 'string'
   OR p_report->>'artifact_sha256' IS DISTINCT FROM p_manifest->>'sha256'
   OR p_report->>'input_hash' IS DISTINCT FROM p_hash
   OR jsonb_typeof(p_report->'input_hash') IS DISTINCT FROM 'string'
   OR p_report->'input_revision' IS DISTINCT FROM to_jsonb(p_revision)
   OR jsonb_typeof(p_report->'provider_build') IS DISTINCT FROM 'string'
   OR p_report->>'provider_build' IS DISTINCT FROM p_manifest->>'provider_build'
   OR p_report->>'provider_build' IS DISTINCT FROM 't3-native-v1'
   OR jsonb_typeof(p_report->'valid') IS DISTINCT FROM 'boolean'
   OR NOT EXISTS(SELECT 1 FROM gis.synthetic_fixtures WHERE manifest=p_manifest)
   OR jsonb_typeof(p_report->'checks') IS DISTINCT FROM 'array'
   OR jsonb_typeof(p_report->'warnings') IS DISTINCT FROM 'array'
   OR jsonb_typeof(p_report->'statistics') IS DISTINCT FROM 'object' THEN
   RAISE EXCEPTION 'GIS_NATIVE_REPORT_INVALID'; END IF;
 IF jsonb_array_length(p_report->'checks')>8 OR jsonb_array_length(p_report->'warnings')>16 THEN
   RAISE EXCEPTION 'GIS_NATIVE_REPORT_INVALID'; END IF;
 IF EXISTS(SELECT 1 FROM jsonb_array_elements(p_report->'checks') v WHERE jsonb_typeof(v)<>'string'
   OR v#>>'{}' NOT IN ('synthetic_fixture_match','metadata_shape','source_hash_match','bounded_input',
     'native_validation','scientific_expected_results'))
   OR (SELECT count(*) FROM jsonb_array_elements(p_report->'checks'))<>
      (SELECT count(DISTINCT v) FROM jsonb_array_elements(p_report->'checks') v) THEN
   RAISE EXCEPTION 'GIS_NATIVE_REPORT_INVALID'; END IF;
 infrastructure:=p_report->>'error_code' IN ('NATIVE_TIMEOUT','NATIVE_MEMORY_LIMIT','NATIVE_PROCESS_FAILED',
   'TRANSIENT_SYNTHETIC','WORKER_SHUTDOWN','NATIVE_OUTPUT_LIMIT');
 IF p_report->'valid'='true'::jsonb THEN
   IF p_report->'error_code' IS DISTINCT FROM 'null'::jsonb
      OR p_manifest->>'fixture_id' IN ('t3-unknown-v2','t3-zip-unsafe-v2','t3-zip-symlink-v2','t3-ldd-missing-v2','t3-nodata-v2') THEN
     RAISE EXCEPTION 'GIS_NATIVE_REPORT_INVALID'; END IF;
 ELSIF jsonb_typeof(p_report->'error_code') IS DISTINCT FROM 'string'
   OR p_report->>'error_code' NOT IN ('UNKNOWN_CODE_REVIEW_REQUIRED','ZIP_PATH_UNSAFE','ZIP_SYMLINK',
     'MISSING_COMPONENT_DBF','ALL_NODATA','VALIDATION_FAILED','NATIVE_TIMEOUT','NATIVE_MEMORY_LIMIT',
     'NATIVE_PROCESS_FAILED','TRANSIENT_SYNTHETIC','WORKER_SHUTDOWN','NATIVE_OUTPUT_LIMIT') THEN
   RAISE EXCEPTION 'GIS_NATIVE_REPORT_INVALID';
 END IF;
 required_checks:='["synthetic_fixture_match","metadata_shape","source_hash_match","bounded_input"]'::jsonb;
 IF NOT COALESCE(infrastructure,false) THEN
   required_checks:=required_checks||'["native_validation","scientific_expected_results"]'::jsonb;
 END IF;
 IF NOT p_report->'checks' @> required_checks THEN RAISE EXCEPTION 'GIS_NATIVE_REPORT_INVALID'; END IF;
 FOR item IN SELECT v FROM jsonb_array_elements(p_report->'warnings') v LOOP
   IF jsonb_typeof(item) IS DISTINCT FROM 'object' OR NOT item ?& ARRAY['code','count'] THEN
     RAISE EXCEPTION 'GIS_NATIVE_REPORT_INVALID'; END IF;
   PERFORM gis.keys(item,ARRAY['code','count','codes']);
   IF item->>'code' IS DISTINCT FROM 'UNKNOWN_CODE_REVIEW_REQUIRED'
     OR jsonb_typeof(item->'count') IS DISTINCT FROM 'number'
     OR COALESCE(item->>'count','') !~ '^[0-9]{1,6}$' THEN RAISE EXCEPTION 'GIS_NATIVE_REPORT_INVALID'; END IF;
   IF item ? 'codes' THEN
     IF jsonb_typeof(item->'codes') IS DISTINCT FROM 'array' OR jsonb_array_length(item->'codes')>16 THEN
       RAISE EXCEPTION 'GIS_NATIVE_REPORT_INVALID'; END IF;
     IF EXISTS(SELECT 1 FROM jsonb_array_elements(item->'codes') v WHERE jsonb_typeof(v)<>'string'
       OR length(v#>>'{}')>40 OR v#>>'{}' !~ '^[A-Za-z0-9_./+-]+$') THEN
       RAISE EXCEPTION 'GIS_NATIVE_REPORT_INVALID'; END IF;
   END IF;
 END LOOP;
 FOR key_name,value IN SELECT key,v FROM jsonb_each(p_report->'statistics') t(key,v) LOOP
   IF key_name NOT IN ('feature_count','total_area_m2','unknown_area_m2','area_U_m2','area_A_m2',
     'unknown_code_count','valid_pixels','mean','min','max') OR jsonb_typeof(value) NOT IN ('number','null') THEN
     RAISE EXCEPTION 'GIS_NATIVE_REPORT_INVALID'; END IF;
   IF jsonb_typeof(value)='number' AND abs((value#>>'{}')::numeric)>1e12 THEN
     RAISE EXCEPTION 'GIS_NATIVE_REPORT_INVALID'; END IF;
   IF key_name IN ('feature_count','unknown_code_count','valid_pixels') AND (
      jsonb_typeof(value) IS DISTINCT FROM 'number' OR value#>>'{}' !~ '^[0-9]{1,6}$') THEN
     RAISE EXCEPTION 'GIS_NATIVE_REPORT_INVALID'; END IF;
   IF key_name IN ('total_area_m2','unknown_area_m2','area_U_m2','area_A_m2') AND (
      jsonb_typeof(value) IS DISTINCT FROM 'number' OR (value#>>'{}')::numeric<0) THEN
     RAISE EXCEPTION 'GIS_NATIVE_REPORT_INVALID'; END IF;
 END LOOP;
 IF p_report->'valid'='true'::jsonb THEN
   IF p_manifest->>'data_kind'='polygon' THEN
     IF NOT p_report->'statistics' @> '{"feature_count":3,"total_area_m2":6400,"unknown_area_m2":0,"area_U_m2":3200,"area_A_m2":3200,"unknown_code_count":0}'::jsonb THEN
       RAISE EXCEPTION 'GIS_NATIVE_SCIENTIFIC_INVARIANT'; END IF;
   ELSE
     expected_values:=CASE p_manifest->>'fixture_id'
       WHEN 't3-s2-v2' THEN '[[0.6,0,-0.6,null],[null,null,0.6,0.6]]'::jsonb
       WHEN 't3-lst-v2' THEN '[[29.6609,29.47974494,null],[null,null,29.6609]]'::jsonb
       WHEN 't3-ndvi-ready-v2' THEN '[[0.6,0,-0.6],[null,0.2,0.4]]'::jsonb
       WHEN 't3-lst-ready-v2' THEN '[[29.6609,0,10],[null,20,30]]'::jsonb
       WHEN 't3-kelvin-v2' THEN '[[29.6609,0,10],[null,20,30]]'::jsonb END;
     IF expected_values IS NULL OR NOT p_report->'statistics' ?& ARRAY['valid_pixels','mean','min','max']
        OR jsonb_typeof(p_report->'statistics'->'valid_pixels') IS DISTINCT FROM 'number'
        OR (p_report->'statistics'->>'valid_pixels')::numeric<=0
        OR EXISTS(SELECT 1 FROM jsonb_each(p_report->'statistics') t(key,v) WHERE v='null'::jsonb)
        OR jsonb_typeof(p_report->'values') IS DISTINCT FROM 'array'
        OR jsonb_array_length(p_report->'values')<>jsonb_array_length(expected_values) THEN
       RAISE EXCEPTION 'GIS_NATIVE_SCIENTIFIC_INVARIANT'; END IF;
     SELECT count(*),avg((v#>>'{}')::numeric),min((v#>>'{}')::numeric),max((v#>>'{}')::numeric)
       INTO expected_count,expected_mean,expected_min,expected_max
       FROM jsonb_array_elements(expected_values) rows_value
       CROSS JOIN LATERAL jsonb_array_elements(rows_value) v WHERE v<>'null'::jsonb;
     IF (p_report->'statistics'->>'valid_pixels')::integer<>expected_count
       OR abs((p_report->'statistics'->>'mean')::numeric-expected_mean)>0.00005
       OR abs((p_report->'statistics'->>'min')::numeric-expected_min)>0.00005
       OR abs((p_report->'statistics'->>'max')::numeric-expected_max)>0.00005 THEN
       RAISE EXCEPTION 'GIS_NATIVE_SCIENTIFIC_INVARIANT'; END IF;
     FOR row_index IN 0..jsonb_array_length(expected_values)-1 LOOP
       row_value:=expected_values->row_index;
       IF jsonb_typeof(p_report->'values'->row_index) IS DISTINCT FROM 'array'
          OR jsonb_array_length(p_report->'values'->row_index)<>jsonb_array_length(row_value) THEN
         RAISE EXCEPTION 'GIS_NATIVE_SCIENTIFIC_INVARIANT'; END IF;
       FOR column_index IN 0..jsonb_array_length(row_value)-1 LOOP
         value:=row_value->column_index;actual_value:=p_report->'values'->row_index->column_index;
         IF value='null'::jsonb THEN
           IF actual_value IS DISTINCT FROM 'null'::jsonb THEN RAISE EXCEPTION 'GIS_NATIVE_SCIENTIFIC_INVARIANT'; END IF;
         ELSIF jsonb_typeof(actual_value) IS DISTINCT FROM 'number'
           OR abs((actual_value#>>'{}')::numeric-(value#>>'{}')::numeric)>0.00005 THEN
           RAISE EXCEPTION 'GIS_NATIVE_SCIENTIFIC_INVARIANT';
         END IF;
       END LOOP;
     END LOOP;
   END IF;
 END IF;
 IF p_report ? 'values' THEN
   IF jsonb_typeof(p_report->'values') IS DISTINCT FROM 'array' OR jsonb_array_length(p_report->'values')>8 THEN
     RAISE EXCEPTION 'GIS_NATIVE_REPORT_INVALID'; END IF;
   FOR row_value IN SELECT v FROM jsonb_array_elements(p_report->'values') v LOOP
     IF jsonb_typeof(row_value) IS DISTINCT FROM 'array' OR jsonb_array_length(row_value)>8 THEN
       RAISE EXCEPTION 'GIS_NATIVE_REPORT_INVALID'; END IF;
     FOR value IN SELECT v FROM jsonb_array_elements(row_value) v LOOP
       count_values:=count_values+1;
       IF count_values>64 OR jsonb_typeof(value) NOT IN ('number','null') THEN
         RAISE EXCEPTION 'GIS_NATIVE_REPORT_INVALID'; END IF;
       IF jsonb_typeof(value)='number' AND abs((value#>>'{}')::numeric)>1e12 THEN
         RAISE EXCEPTION 'GIS_NATIVE_REPORT_INVALID'; END IF;
     END LOOP;
   END LOOP;
 END IF;
END $f$;

-- Shared queue/state protocol. This is private; neither worker role can choose
-- a protocol directly. All multi-row mutations lock edition -> job -> attempt.
CREATE FUNCTION gis.queue_protocol(p_action text,p_payload jsonb,p_native boolean) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE j gis.jobs%ROWTYPE; e gis.editions%ROWTYPE; candidate record;
 worker uuid; token uuid; jid uuid; eid uuid; rid uuid; v_now timestamptz;
 progress_value integer; report_value jsonb; code text; next_state text; n integer:=0;
BEGIN
 PERFORM gis.assert_environment();
 IF p_action='claim' THEN
   PERFORM gis.keys(p_payload,ARRAY['worker_id']);
   worker:=(p_payload->>'worker_id')::uuid;
   IF worker IS NULL THEN RAISE EXCEPTION 'GIS_WORKER_REQUIRED'; END IF;
   IF NOT pg_try_advisory_xact_lock(hashtextextended('gis-t1-single-claim',0)) THEN
     RETURN CASE WHEN p_native THEN jsonb_build_object('job',NULL) ELSE NULL END; END IF;
   IF EXISTS(SELECT 1 FROM gis.jobs WHERE state='running') THEN
     RETURN CASE WHEN p_native THEN jsonb_build_object('job',NULL) ELSE NULL END; END IF;
   FOR candidate IN SELECT q.id,q.edition_id FROM gis.jobs q JOIN gis.editions d ON d.id=q.edition_id
      WHERE q.state='queued' AND q.attempt_count<3 AND q.available_at<=clock_timestamp()
        AND (d.manifest->'schema_version'='2'::jsonb)=p_native
      ORDER BY q.available_at,q.created_at,q.id LIMIT 20 LOOP
     SELECT * INTO e FROM gis.editions WHERE id=candidate.edition_id FOR UPDATE SKIP LOCKED;
     IF NOT FOUND THEN CONTINUE; END IF;
     SELECT * INTO j FROM gis.jobs WHERE id=candidate.id FOR UPDATE SKIP LOCKED;
     IF NOT FOUND THEN CONTINUE; END IF;
     v_now:=clock_timestamp();
     IF j.state<>'queued' OR j.attempt_count>=3 OR j.available_at>v_now
       OR e.state<>'validating' OR (e.manifest->'schema_version'='2'::jsonb)<>p_native THEN CONTINUE; END IF;
     token:=gen_random_uuid();
     UPDATE gis.jobs SET state='running',attempt_count=attempt_count+1,worker_id=worker,
       lease_token=token,lease_until=v_now+interval '60 seconds',progress=0,error_code=NULL
       WHERE id=j.id RETURNING * INTO j;
     INSERT INTO gis.attempts(job_id,attempt_no,worker_id,lease_token,state,started_at)
       VALUES(j.id,j.attempt_count,worker,token,'running',v_now);
     report_value:=jsonb_build_object('job_id',j.id,'edition_id',e.id,'worker_id',worker,'lease_token',token,
       'lease_until',j.lease_until,'attempt_no',j.attempt_count,'input_revision',j.input_revision,
       'input_hash',j.input_hash,'validator_version',j.validator_version,'manifest',e.manifest);
     IF p_native THEN
       INSERT INTO gis.audit(operation,dataset_id,edition_id,job_id,detail)
         VALUES('worker_v2.claim',e.dataset_id,e.id,j.id,jsonb_build_object('worker_id',worker,'attempt',j.attempt_count));
       RETURN jsonb_build_object('job',report_value||jsonb_build_object('id',j.id,'dataset_id',e.dataset_id,
         'kind',j.kind,'attempt_number',j.attempt_count));
     END IF;
     RETURN report_value;
   END LOOP;
   RETURN CASE WHEN p_native THEN jsonb_build_object('job',NULL) ELSE NULL END;
 ELSIF p_action='recover' THEN
   PERFORM gis.keys(p_payload,ARRAY[]::text[]);
   FOR candidate IN SELECT q.id,q.edition_id FROM gis.jobs q JOIN gis.editions d ON d.id=q.edition_id
     WHERE q.state='running' AND q.lease_until<=clock_timestamp()
       AND (d.manifest->'schema_version'='2'::jsonb)=p_native
     ORDER BY q.lease_until,q.id LIMIT 20 LOOP
     SELECT * INTO e FROM gis.editions WHERE id=candidate.edition_id FOR UPDATE SKIP LOCKED;
     IF NOT FOUND THEN CONTINUE; END IF;
     SELECT * INTO j FROM gis.jobs WHERE id=candidate.id FOR UPDATE SKIP LOCKED;
     IF NOT FOUND THEN CONTINUE; END IF;
     v_now:=clock_timestamp();
     IF j.state<>'running' OR j.lease_until>v_now THEN CONTINUE; END IF;
     UPDATE gis.attempts SET state='expired',error_code='lease_expired',finished_at=v_now
       WHERE job_id=j.id AND attempt_no=j.attempt_count AND lease_token=j.lease_token AND state='running';
     IF j.attempt_count<3 THEN
       UPDATE gis.jobs SET state='queued',worker_id=NULL,lease_token=NULL,lease_until=NULL,progress=0,
         available_at=v_now+make_interval(secs=>CASE j.attempt_count WHEN 1 THEN 5 ELSE 20 END+floor(random()*3)::int)
         WHERE id=j.id;
     ELSE
       UPDATE gis.jobs SET state='failed',worker_id=NULL,lease_token=NULL,lease_until=NULL,
         error_code='attempts_exhausted',finished_at=v_now WHERE id=j.id;
       UPDATE gis.editions SET state='draft' WHERE id=e.id AND state='validating';
     END IF;
     INSERT INTO gis.audit(operation,dataset_id,edition_id,job_id,detail)
       VALUES(CASE WHEN p_native THEN 'worker_v2.recover' ELSE 'worker.recover' END,e.dataset_id,e.id,j.id,
         jsonb_build_object('attempt',j.attempt_count,'terminal',j.attempt_count=3));
     n:=n+1;
   END LOOP;
   RETURN jsonb_build_object('recovered',n);
 ELSIF p_action IN ('heartbeat','complete','fail') THEN
   PERFORM gis.keys(p_payload,CASE p_action
     WHEN 'heartbeat' THEN ARRAY['job_id','worker_id','lease_token','progress']
     WHEN 'complete' THEN ARRAY['job_id','worker_id','lease_token','report']
     ELSE CASE WHEN p_native THEN ARRAY['job_id','worker_id','lease_token','error_code','report']
          ELSE ARRAY['job_id','worker_id','lease_token','error_code'] END END);
   jid:=(p_payload->>'job_id')::uuid; worker:=(p_payload->>'worker_id')::uuid; token:=(p_payload->>'lease_token')::uuid;
   SELECT edition_id INTO eid FROM gis.jobs WHERE id=jid;
   SELECT * INTO e FROM gis.editions WHERE id=eid FOR UPDATE;
   IF NOT FOUND OR (e.manifest->'schema_version'='2'::jsonb)<>p_native THEN
     RAISE EXCEPTION 'GIS_WORKER_PROTOCOL_MISMATCH' USING ERRCODE='42501'; END IF;
   SELECT * INTO j FROM gis.jobs WHERE id=jid FOR UPDATE;
   v_now:=clock_timestamp();
   IF NOT FOUND OR j.state<>'running' OR j.worker_id IS DISTINCT FROM worker
     OR j.lease_token IS DISTINCT FROM token OR j.lease_until<=v_now THEN RAISE EXCEPTION 'GIS_STALE_LEASE'; END IF;
   IF p_action='heartbeat' THEN
     IF jsonb_typeof(p_payload->'progress') IS DISTINCT FROM 'number'
       OR COALESCE(p_payload->>'progress','') !~ '^[0-9]{1,2}$' THEN RAISE EXCEPTION 'GIS_INVALID_PROGRESS'; END IF;
     progress_value:=(p_payload->>'progress')::integer;
     IF progress_value<j.progress OR progress_value>99 THEN RAISE EXCEPTION 'GIS_INVALID_PROGRESS'; END IF;
     UPDATE gis.jobs SET progress=progress_value,lease_until=v_now+interval '60 seconds' WHERE id=j.id;
     UPDATE gis.attempts SET progress=progress_value WHERE job_id=j.id AND attempt_no=j.attempt_count AND lease_token=token;
     RETURN jsonb_build_object('job_id',j.id,'lease_until',v_now+interval '60 seconds','progress',progress_value);
   END IF;
   IF e.state<>'validating' OR e.input_revision<>j.input_revision OR e.input_hash<>j.input_hash THEN
     RAISE EXCEPTION 'GIS_INPUT_CHANGED'; END IF;
   IF p_native THEN
     report_value:=p_payload->'report';
     PERFORM gis.validate_native_report(report_value,e.manifest,j.input_hash,j.input_revision);
     IF p_action='fail' AND report_value->'valid'<>'false'::jsonb THEN RAISE EXCEPTION 'GIS_INVALID_FAILURE'; END IF;
     IF p_action='complete' AND report_value->>'error_code' IN ('NATIVE_TIMEOUT','NATIVE_MEMORY_LIMIT',
       'NATIVE_PROCESS_FAILED','TRANSIENT_SYNTHETIC','WORKER_SHUTDOWN','NATIVE_OUTPUT_LIMIT') THEN
       RAISE EXCEPTION 'GIS_TRANSIENT_REQUIRES_FAIL'; END IF;
     UPDATE gis.attempts SET validation_report=report_value WHERE job_id=j.id AND attempt_no=j.attempt_count AND lease_token=token;
   ELSIF p_action='complete' THEN
     report_value:=p_payload->'report';
     PERFORM gis.keys(report_value,ARRAY['valid','fixture_id','checks']);
     IF report_value->'valid' IS DISTINCT FROM 'true'::jsonb
       OR report_value->>'fixture_id' IS DISTINCT FROM e.manifest->>'fixture_id'
       OR jsonb_typeof(report_value->'checks') IS DISTINCT FROM 'array'
       OR jsonb_array_length(report_value->'checks')>30
       OR EXISTS(SELECT 1 FROM jsonb_array_elements(report_value->'checks') v WHERE jsonb_typeof(v)<>'string'
         OR v#>>'{}' NOT IN ('synthetic_fixture_match','metadata_shape','source_hash_match','bounded_input'))
       OR NOT EXISTS(SELECT 1 FROM gis.synthetic_fixtures WHERE manifest=e.manifest)
       OR e.manifest->>'fixture_id' IN ('invalid-v1','transient-v1') THEN RAISE EXCEPTION 'GIS_INVALID_RESULT'; END IF;
   END IF;
   IF p_action='complete' AND report_value->'valid'='true'::jsonb THEN
     INSERT INTO gis.results(job_id,edition_id,input_revision,input_hash,validator_version,attempt_no,lease_token,valid,report)
       VALUES(j.id,e.id,j.input_revision,j.input_hash,j.validator_version,j.attempt_count,token,true,report_value) RETURNING id INTO rid;
     UPDATE gis.editions SET state='validated',validated_result_id=rid WHERE id=e.id;
     UPDATE gis.jobs SET state='succeeded',worker_id=NULL,lease_token=NULL,lease_until=NULL,progress=100,finished_at=v_now WHERE id=j.id;
     UPDATE gis.attempts SET state='succeeded',progress=100,finished_at=v_now WHERE job_id=j.id AND attempt_no=j.attempt_count AND lease_token=token;
     INSERT INTO gis.audit(operation,dataset_id,edition_id,job_id,detail)
       VALUES(CASE WHEN p_native THEN 'worker_v2.complete' ELSE 'worker.complete' END,e.dataset_id,e.id,j.id,
         jsonb_build_object('result_id',rid,'attempt',j.attempt_count));
     RETURN jsonb_build_object('job_id',j.id,'state','succeeded','result_id',rid);
   END IF;
   IF p_action='complete' THEN code:='invalid_data';
   ELSE code:=p_payload->>'error_code'; END IF;
   IF code IS NULL OR code NOT IN ('invalid_data','transient') THEN RAISE EXCEPTION 'GIS_INVALID_FAILURE'; END IF;
   IF p_native AND p_action='fail' AND (code<>'transient' OR report_value->>'error_code' NOT IN (
     'NATIVE_TIMEOUT','NATIVE_MEMORY_LIMIT','NATIVE_PROCESS_FAILED','TRANSIENT_SYNTHETIC','WORKER_SHUTDOWN','NATIVE_OUTPUT_LIMIT')) THEN
     RAISE EXCEPTION 'GIS_INVALID_FAILURE'; END IF;
   next_state:=CASE WHEN code='transient' AND j.attempt_count<3 THEN 'queued' ELSE 'failed' END;
   UPDATE gis.attempts SET state='failed',error_code=code,finished_at=v_now
     WHERE job_id=j.id AND attempt_no=j.attempt_count AND lease_token=token;
   UPDATE gis.jobs SET state=next_state,worker_id=NULL,lease_token=NULL,lease_until=NULL,
     error_code=CASE WHEN next_state='failed' THEN code ELSE NULL END,progress=0,
     available_at=v_now+make_interval(secs=>CASE j.attempt_count WHEN 1 THEN 5 ELSE 20 END+floor(random()*3)::int),
     finished_at=CASE WHEN next_state='failed' THEN v_now ELSE NULL END WHERE id=j.id;
   IF next_state='failed' THEN UPDATE gis.editions SET state='draft' WHERE id=e.id; END IF;
   INSERT INTO gis.audit(operation,dataset_id,edition_id,job_id,detail)
     VALUES(CASE WHEN p_native THEN 'worker_v2.fail' ELSE 'worker.fail' END,e.dataset_id,e.id,j.id,
       jsonb_build_object('attempt',j.attempt_count,'error_code',code,'state',next_state));
   RETURN CASE WHEN p_native THEN jsonb_build_object('job_id',j.id,'state',next_state,'error_code',code)
     ELSE jsonb_build_object('job_id',j.id,'state',next_state) END;
 END IF;
 RAISE EXCEPTION 'GIS_UNKNOWN_WORKER_ACTION';
END $f$;

CREATE OR REPLACE FUNCTION gis.worker(p_action text,p_payload jsonb DEFAULT '{}') RETURNS jsonb
LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,gis
AS $f$ SELECT gis.queue_protocol(p_action,p_payload,false) $f$;

CREATE OR REPLACE FUNCTION gis.worker_v2(p_action text,p_payload jsonb DEFAULT '{}') RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE subject uuid;
BEGIN
 subject:=gis.native_subject();
 IF p_payload ? 'worker_id' AND p_payload->>'worker_id' IS DISTINCT FROM subject::text THEN
   RAISE EXCEPTION 'GIS_WORKER_IDENTITY_MISMATCH' USING ERRCODE='42501'; END IF;
 IF p_action='recover' THEN RETURN gis.queue_protocol(p_action,p_payload,true); END IF;
 RETURN gis.queue_protocol(p_action,p_payload||jsonb_build_object('worker_id',subject),true);
END $f$;

-- Deferred integrity prevents ANY old/future owner RPC from marking Native V2
-- successful without the exact native report. No existing row is updated/rewritten.
CREATE FUNCTION gis.check_native_catalog() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE j gis.jobs%ROWTYPE; e gis.editions%ROWTYPE; a gis.attempts%ROWTYPE; r gis.results%ROWTYPE; jid uuid;
BEGIN
 IF TG_TABLE_NAME='editions' THEN
   FOR jid IN SELECT id FROM gis.jobs WHERE edition_id=NEW.id AND state='succeeded' LOOP
     SELECT * INTO j FROM gis.jobs WHERE id=jid;
     SELECT * INTO e FROM gis.editions WHERE id=j.edition_id;
     IF e.manifest->'schema_version'='2'::jsonb THEN
       SELECT * INTO a FROM gis.attempts WHERE job_id=j.id AND attempt_no=j.attempt_count;
       SELECT * INTO r FROM gis.results WHERE job_id=j.id;
       PERFORM gis.validate_native_report(a.validation_report,e.manifest,j.input_hash,j.input_revision);
       IF a.state<>'succeeded' OR r.report IS DISTINCT FROM a.validation_report OR a.validation_report->'valid'<>'true'::jsonb THEN
         RAISE EXCEPTION 'GIS_NATIVE_RESULT_INVARIANT'; END IF;
     END IF;
   END LOOP;
   RETURN NULL;
 END IF;
 jid:=CASE WHEN TG_TABLE_NAME='jobs' THEN NEW.id ELSE NEW.job_id END;
 SELECT * INTO j FROM gis.jobs WHERE id=jid;
 SELECT * INTO e FROM gis.editions WHERE id=j.edition_id;
 IF e.manifest->'schema_version' IS DISTINCT FROM '2'::jsonb THEN RETURN NULL; END IF;
 IF j.state='succeeded' THEN
   SELECT * INTO a FROM gis.attempts WHERE job_id=j.id AND attempt_no=j.attempt_count;
   SELECT * INTO r FROM gis.results WHERE job_id=j.id;
   PERFORM gis.validate_native_report(a.validation_report,e.manifest,j.input_hash,j.input_revision);
   IF a.state<>'succeeded' OR r.report IS DISTINCT FROM a.validation_report OR a.validation_report->'valid'<>'true'::jsonb THEN
     RAISE EXCEPTION 'GIS_NATIVE_RESULT_INVARIANT'; END IF;
 ELSIF TG_TABLE_NAME='attempts' AND NEW.state='failed' THEN
   PERFORM gis.validate_native_report(NEW.validation_report,e.manifest,j.input_hash,j.input_revision);
 END IF;
 RETURN NULL;
END $f$;
CREATE CONSTRAINT TRIGGER native_catalog_integrity AFTER INSERT OR UPDATE ON gis.jobs
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION gis.check_native_catalog();
CREATE CONSTRAINT TRIGGER native_catalog_integrity AFTER INSERT OR UPDATE ON gis.editions
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION gis.check_native_catalog();
CREATE CONSTRAINT TRIGGER native_catalog_integrity AFTER INSERT OR UPDATE ON gis.attempts
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION gis.check_native_catalog();
CREATE CONSTRAINT TRIGGER native_catalog_integrity AFTER INSERT OR UPDATE ON gis.results
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION gis.check_native_catalog();

CREATE OR REPLACE FUNCTION public.gis_worker_readiness_v2() RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE subject uuid; result_value jsonb;
BEGIN
 subject:=gis.native_subject();
 IF NOT EXISTS(SELECT 1 FROM gis.schema_migrations WHERE version=32) THEN
   RAISE EXCEPTION 'GIS_NATIVE_CONTRACT_NOT_READY'; END IF;
 SELECT jsonb_build_object('status','ready','contract_version','1.3.0-t3-remediation',
   'worker_role','gis_native_worker','subject',subject,'runtime_instance',runtime_instance,
   'baseline_fingerprint',baseline_fingerprint,'database_name',database_name,'cluster_name',cluster_name,
   'migration_versions',(SELECT jsonb_agg(version ORDER BY version) FROM gis.schema_migrations))
   INTO result_value FROM gis.environment WHERE singleton;
 RETURN result_value;
END $f$;

REVOKE ALL ON ALL FUNCTIONS IN SCHEMA gis FROM PUBLIC,anon,authenticated,service_role,gis_worker,gis_native_worker;
REVOKE ALL ON FUNCTION public.gis_worker_v2(text,jsonb),public.gis_worker_readiness_v2()
 FROM PUBLIC,anon,authenticated,service_role,gis_worker,gis_native_worker;
GRANT EXECUTE ON FUNCTION public.gis_worker_v2(text,jsonb),public.gis_worker_readiness_v2() TO gis_native_worker;
RESET ROLE;
REVOKE CREATE ON SCHEMA public FROM gis_owner;
NOTIFY pgrst,'reload schema';
