-- A2 local LDD prepare/verification. Exact independent review before execution.
GRANT CREATE ON SCHEMA public TO gis_owner;
SET LOCAL ROLE gis_owner;
SELECT gis.assert_environment();
DO $guard$ BEGIN
 IF current_database() NOT IN ('postgres','gis_t1_upgrade')
 OR NOT gis.target_ok()
 OR NOT EXISTS(SELECT 1 FROM gis.environment WHERE singleton AND NOT activation_enabled
  AND runtime_instance=current_setting('gis.runtime_instance',true)
  AND baseline_fingerprint=current_setting('gis.baseline_fingerprint',true))
 OR NOT EXISTS(SELECT 1 FROM gis.schema_migrations WHERE version=37
  AND sha256='dd72c9acca8b13ac7a096a207a272cd549ebf066354dde85206e0b40a2ff068e')
 OR EXISTS(SELECT 1 FROM gis.schema_migrations WHERE version>=38) THEN
 RAISE EXCEPTION 'GIS_LOCAL_BASELINE_037_REQUIRED'; END IF;
END $guard$;
ALTER TABLE gis.jobs DROP CONSTRAINT jobs_kind_check;
ALTER TABLE gis.jobs ADD CONSTRAINT jobs_kind_check CHECK(kind IN
 ('validate_synthetic_edition','validate_ldd_edition','process_offline_edition','validate_geotiff_edition','prepare_ldd_edition'));
ALTER TABLE gis.jobs DROP CONSTRAINT jobs_validator_version_check;
ALTER TABLE gis.jobs ADD CONSTRAINT jobs_validator_version_check CHECK(validator_version IN
 ('synthetic-v1','ldd-local-v1','gee-offline-v1','geotiff-local-v1','ldd-prepare-v1'));
ALTER TABLE gis.results DROP CONSTRAINT results_provider_check;
ALTER TABLE gis.results ADD CONSTRAINT results_provider_check CHECK(provider IN
 ('synthetic','local_ldd','offline_processing','local_geotiff','local_ldd_prepare'));
CREATE OR REPLACE FUNCTION gis.check_catalog() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE eid uuid; e gis.editions%ROWTYPE; d gis.datasets%ROWTYPE;
BEGIN
 IF TG_TABLE_NAME='datasets' THEN
  SELECT * INTO d FROM gis.datasets WHERE id=NEW.id;
  IF d.active_edition_id IS NOT NULL AND NOT gis.eligible(d.active_edition_id,d.id) THEN RAISE EXCEPTION 'GIS_ACTIVE_INVARIANT'; END IF;
  RETURN NULL;
 END IF;
 IF TG_TABLE_NAME='editions' THEN eid:=NEW.id;
 ELSIF TG_TABLE_NAME='attempts' THEN SELECT edition_id INTO eid FROM gis.jobs WHERE id=NEW.job_id;
 ELSE eid:=NEW.edition_id; END IF;
 SELECT * INTO e FROM gis.editions WHERE id=eid;
 IF NOT FOUND THEN RETURN NULL; END IF;
 IF (e.state='validating') IS DISTINCT FROM EXISTS(SELECT 1 FROM gis.jobs WHERE edition_id=e.id AND kind<>'prepare_ldd_edition' AND state IN ('queued','running')) THEN
  RAISE EXCEPTION 'GIS_QUEUE_EDITION_INVARIANT'; END IF;
 IF e.state='validated' AND NOT gis.eligible(e.id,e.dataset_id) THEN RAISE EXCEPTION 'GIS_VALIDATION_INVARIANT'; END IF;
 IF e.state IN ('draft','validating') AND e.validated_result_id IS NOT NULL THEN RAISE EXCEPTION 'GIS_RESULT_INVARIANT'; END IF;
 IF EXISTS(SELECT 1 FROM gis.datasets WHERE active_edition_id=e.id) AND NOT gis.eligible(e.id,e.dataset_id) THEN
  RAISE EXCEPTION 'GIS_ACTIVE_INVARIANT'; END IF;
 IF EXISTS(SELECT 1 FROM gis.jobs j LEFT JOIN gis.results r ON r.job_id=j.id
   WHERE j.edition_id=e.id AND ((j.state='succeeded') IS DISTINCT FROM (r.id IS NOT NULL)
     OR (r.id IS NOT NULL AND (r.edition_id<>j.edition_id OR r.input_revision<>j.input_revision OR r.input_hash<>j.input_hash
       OR r.validator_version<>j.validator_version OR r.attempt_no<>j.attempt_count
       OR NOT EXISTS(SELECT 1 FROM gis.attempts a WHERE a.job_id=j.id AND a.attempt_no=r.attempt_no AND a.lease_token=r.lease_token AND a.state='succeeded'))))) THEN
  RAISE EXCEPTION 'GIS_JOB_RESULT_INVARIANT'; END IF;
 IF EXISTS(SELECT 1 FROM gis.jobs j WHERE j.edition_id=e.id AND (
    j.attempt_count<>(SELECT count(*) FROM gis.attempts a WHERE a.job_id=j.id)
    OR (j.state='running' AND NOT EXISTS(SELECT 1 FROM gis.attempts a WHERE a.job_id=j.id
      AND a.attempt_no=j.attempt_count AND a.lease_token=j.lease_token AND a.worker_id=j.worker_id AND a.state='running'))
    OR (j.state<>'running' AND EXISTS(SELECT 1 FROM gis.attempts a WHERE a.job_id=j.id AND a.state='running')))) THEN
  RAISE EXCEPTION 'GIS_ATTEMPT_INVARIANT'; END IF;
 RETURN NULL;
END $f$;

-- Same durable jobs/attempts/results; validation result pointer is never replaced.
CREATE TABLE gis.ldd_prepare_requests(
 job_id uuid PRIMARY KEY REFERENCES gis.jobs(id),
 edition_id uuid NOT NULL REFERENCES gis.editions(id),
 validation_result_id uuid NOT NULL,
 method_version text NOT NULL DEFAULT 'ldd-source-area-v1' CHECK(method_version='ldd-source-area-v1'),
 FOREIGN KEY(validation_result_id,edition_id) REFERENCES gis.results(id,edition_id));
CREATE TABLE gis.ldd_prepare_certificates(
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 job_id uuid NOT NULL UNIQUE REFERENCES gis.jobs(id),
 edition_id uuid NOT NULL REFERENCES gis.editions(id),
 validation_result_id uuid NOT NULL,
 geometry_artifact_id uuid NOT NULL REFERENCES gis.publication_artifacts(id),
 summary_artifact_id uuid NOT NULL REFERENCES gis.publication_artifacts(id),
 verifier_version text NOT NULL CHECK(verifier_version='ldd-trusted-bytes-v1'),
 coverage_mode text NOT NULL DEFAULT 'validated_source_footprint' CHECK(coverage_mode='validated_source_footprint'),
 verified_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 FOREIGN KEY(validation_result_id,edition_id) REFERENCES gis.results(id,edition_id));
CREATE TABLE gis.ldd_prepare_revocations(
 certificate_id uuid PRIMARY KEY REFERENCES gis.ldd_prepare_certificates(id),
 reason text NOT NULL CHECK(reason IN ('artifact_unavailable','artifact_corrupt','source_changed')),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp());
DO $acl$ DECLARE t text; BEGIN
 FOREACH t IN ARRAY ARRAY['ldd_prepare_requests','ldd_prepare_certificates','ldd_prepare_revocations'] LOOP
 EXECUTE format('ALTER TABLE gis.%I ENABLE ROW LEVEL SECURITY',t);
 EXECUTE format('ALTER TABLE gis.%I FORCE ROW LEVEL SECURITY',t);
 EXECUTE format('CREATE POLICY owner_access ON gis.%I TO gis_owner USING(true) WITH CHECK(true)',t);
 EXECUTE format('REVOKE ALL ON gis.%I FROM PUBLIC,anon,authenticated,service_role,gis_worker,gis_native_worker',t);
 END LOOP;
END $acl$;
CREATE FUNCTION gis.ldd_prepare_immutable() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
BEGIN RAISE EXCEPTION 'GIS_PREPARE_IMMUTABLE'; END $f$;
DO $immutable$ DECLARE t text; BEGIN
 FOREACH t IN ARRAY ARRAY['ldd_prepare_requests','ldd_prepare_certificates','ldd_prepare_revocations'] LOOP
 EXECUTE format('CREATE TRIGGER immutable_prepare BEFORE UPDATE OR DELETE ON gis.%I FOR EACH ROW EXECUTE FUNCTION gis.ldd_prepare_immutable()',t);
 END LOOP;
END $immutable$;

CREATE FUNCTION gis.ldd_prepare_packet(p_job uuid) RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE j gis.jobs%ROWTYPE; e gis.editions%ROWTYPE; d gis.datasets%ROWTYPE; u gis.ldd_uploads%ROWTYPE; q gis.ldd_prepare_requests%ROWTYPE;
BEGIN
 SELECT * INTO j FROM gis.jobs WHERE id=p_job;
 SELECT * INTO q FROM gis.ldd_prepare_requests WHERE job_id=j.id;
 SELECT * INTO e FROM gis.editions WHERE id=j.edition_id;
 SELECT * INTO d FROM gis.datasets WHERE id=e.dataset_id;
 SELECT * INTO u FROM gis.ldd_uploads WHERE edition_id=e.id;
 IF q.job_id IS NULL OR u.id IS NULL OR j.kind<>'prepare_ldd_edition' THEN RAISE EXCEPTION 'GIS_PREPARE_NOT_FOUND'; END IF;
 RETURN jsonb_build_object('dataset_id',d.id,'edition_id',e.id,'job_id',j.id,
  'validation_result_id',q.validation_result_id,'method_version',q.method_version,
  'validation',jsonb_build_object('upload_id',u.id,'manifest',e.manifest,'input_hash',j.input_hash,
   'input_revision',j.input_revision,'attempt_number',greatest(1,j.attempt_count),'province',d.province,'data_year',d.data_year,'encoding',u.encoding));
END $f$;

CREATE FUNCTION gis.ldd_prepare_report(p_job uuid,p_report jsonb) RETURNS void
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE packet jsonb; k text; a jsonb;
BEGIN
 packet:=gis.ldd_prepare_packet(p_job);
 PERFORM gis.keys(p_report,ARRAY['schema_version','method_version','valid','error_code','dataset_id','edition_id','job_id',
   'validation_result_id','source_sha256','input_hash','input_revision','artifacts']);
 IF NOT p_report ?& ARRAY['schema_version','method_version','valid','error_code','dataset_id','edition_id','job_id',
   'validation_result_id','source_sha256','input_hash','input_revision','artifacts']
 OR p_report->'schema_version' IS DISTINCT FROM '1'::jsonb OR p_report->>'method_version' IS DISTINCT FROM 'ldd-source-area-v1'
 OR jsonb_typeof(p_report->'valid') IS DISTINCT FROM 'boolean'
 OR p_report->>'source_sha256' IS DISTINCT FROM packet#>>'{validation,manifest,sha256}'
 OR p_report->>'input_hash' IS DISTINCT FROM packet#>>'{validation,input_hash}'
 OR p_report->'input_revision' IS DISTINCT FROM packet#>'{validation,input_revision}' THEN RAISE EXCEPTION 'GIS_PREPARE_REPORT_INVALID'; END IF;
 FOREACH k IN ARRAY ARRAY['dataset_id','edition_id','job_id','validation_result_id'] LOOP
  IF p_report->k IS DISTINCT FROM packet->k THEN RAISE EXCEPTION 'GIS_PREPARE_REPORT_INVALID'; END IF;
 END LOOP;
 PERFORM gis.keys(p_report->'artifacts',ARRAY['ldd_geometry','ldd_summary']);
 IF p_report->'valid'='true'::jsonb THEN
  IF p_report->'error_code' IS DISTINCT FROM 'null'::jsonb OR NOT (p_report->'artifacts' ?& ARRAY['ldd_geometry','ldd_summary']) THEN RAISE EXCEPTION 'GIS_PREPARE_REPORT_INVALID'; END IF;
  FOREACH k IN ARRAY ARRAY['ldd_geometry','ldd_summary'] LOOP
   a:=p_report->'artifacts'->k;
   PERFORM gis.keys(a,ARRAY['sha256','byte_size']);
   IF NOT a ?& ARRAY['sha256','byte_size'] OR jsonb_typeof(a->'sha256') IS DISTINCT FROM 'string'
    OR a->>'sha256' !~ '^[0-9a-f]{64}$' OR jsonb_typeof(a->'byte_size') IS DISTINCT FROM 'number'
    OR a->>'byte_size' !~ '^[1-9][0-9]{0,7}$' OR (a->>'byte_size')::bigint>20971520 THEN RAISE EXCEPTION 'GIS_PREPARE_REPORT_INVALID'; END IF;
  END LOOP;
 ELSIF p_report->'artifacts'<>'{}'::jsonb OR jsonb_typeof(p_report->'error_code') IS DISTINCT FROM 'string'
   OR p_report->>'error_code' !~ '^[A-Z][A-Z0-9_]{0,59}$' THEN RAISE EXCEPTION 'GIS_PREPARE_REPORT_INVALID'; END IF;
END $f$;

CREATE FUNCTION gis.ldd_prepare_command(p_actor uuid,p_request_id uuid,p_operation text,p_payload jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE d gis.datasets%ROWTYPE; e gis.editions%ROWTYPE; j gis.jobs%ROWTYPE; original gis.jobs%ROWTYPE;
 receipt gis.receipts%ROWTYPE; v jsonb; digest text; body jsonb; code integer;
BEGIN
 PERFORM gis.authorize(p_actor,false);
 IF p_request_id IS NULL THEN RAISE EXCEPTION 'GIS_REQUEST_ID_REQUIRED'; END IF;
 PERFORM gis.keys(p_payload,ARRAY['edition_id','expected_dataset_revision','expected_input_revision','input_hash','province','data_year','job_id','reason']);
 IF p_operation NOT IN ('enqueue','retry') OR NOT p_payload ?& ARRAY['edition_id','expected_dataset_revision','expected_input_revision','input_hash','province','data_year'] THEN RAISE EXCEPTION 'GIS_INVALID_PAYLOAD'; END IF;
 digest:=encode(sha256(convert_to(p_payload::text,'UTF8')),'hex');
 PERFORM pg_advisory_xact_lock(hashtextextended(p_actor::text||':'||p_request_id::text,0));
 PERFORM gis.authorize(p_actor,false);
 SELECT * INTO receipt FROM gis.receipts WHERE actor_id=p_actor AND request_id=p_request_id;
 IF FOUND THEN
  IF receipt.operation<>'prepare.'||p_operation OR receipt.payload_hash<>digest THEN RAISE EXCEPTION 'GIS_IDEMPOTENCY_CONFLICT'; END IF;
  RETURN jsonb_build_object('status',receipt.status,'body',receipt.body);
 END IF;
 SELECT * INTO e FROM gis.editions WHERE id=(p_payload->>'edition_id')::uuid;
 IF NOT FOUND THEN RAISE EXCEPTION 'GIS_NOT_FOUND'; END IF;
 SELECT * INTO d FROM gis.datasets WHERE id=e.dataset_id FOR NO KEY UPDATE;
 SELECT * INTO e FROM gis.editions WHERE id=e.id FOR UPDATE;
 v:=gis.publication_validation(e.id);
 IF v IS NULL OR d.kind<>'ldd_shapefile' THEN RAISE EXCEPTION 'GIS_PREPARE_VALIDATION_REQUIRED'; END IF;
 IF p_payload->'expected_dataset_revision' IS DISTINCT FROM to_jsonb(d.revision)
 OR p_payload->'expected_input_revision' IS DISTINCT FROM to_jsonb(e.input_revision)
 OR p_payload->>'input_hash' IS DISTINCT FROM e.input_hash OR p_payload->>'province' IS DISTINCT FROM d.province
 OR p_payload->'data_year' IS DISTINCT FROM to_jsonb(d.data_year) THEN RAISE EXCEPTION 'GIS_REVISION_CONFLICT'; END IF;
 IF p_operation='retry' THEN
  IF length(btrim(p_payload->>'reason')) NOT BETWEEN 1 AND 500 OR p_payload->>'reason' IS NULL THEN RAISE EXCEPTION 'GIS_REASON_REQUIRED'; END IF;
  SELECT * INTO original FROM gis.jobs WHERE id=(p_payload->>'job_id')::uuid FOR UPDATE;
  IF original.edition_id IS DISTINCT FROM e.id OR original.kind<>'prepare_ldd_edition' OR original.parent_job_id IS NOT NULL
    OR original.state<>'failed' OR original.error_code NOT IN ('transient','attempts_exhausted') THEN RAISE EXCEPTION 'GIS_RETRY_INELIGIBLE'; END IF;
  IF EXISTS(SELECT 1 FROM gis.jobs WHERE parent_job_id=original.id) THEN RAISE EXCEPTION 'GIS_RETRY_ALREADY_USED'; END IF;
 ELSE
  SELECT * INTO j FROM gis.jobs WHERE edition_id=e.id AND validator_version='ldd-prepare-v1' AND parent_job_id IS NULL;
 END IF;
 IF j.id IS NULL THEN
  IF EXISTS(SELECT 1 FROM gis.jobs WHERE edition_id=e.id AND state IN ('queued','running')) THEN RAISE EXCEPTION 'GIS_PREPARE_BUSY'; END IF;
  INSERT INTO gis.jobs(edition_id,parent_job_id,kind,validator_version,input_revision,input_hash,requested_by)
   VALUES(e.id,original.id,'prepare_ldd_edition','ldd-prepare-v1',e.input_revision,e.input_hash,p_actor) RETURNING * INTO j;
  INSERT INTO gis.ldd_prepare_requests(job_id,edition_id,validation_result_id) VALUES(j.id,e.id,(v->>'validation_result_id')::uuid);
 END IF;
 code:=CASE WHEN j.state IN ('queued','running') THEN 202 ELSE 200 END;
 body:=gis.api_read_row('job',to_jsonb(j));
 INSERT INTO gis.audit(actor_id,operation,dataset_id,edition_id,job_id,reason)
 VALUES(p_actor,'prepare.'||p_operation,d.id,e.id,j.id,p_payload->>'reason');
 INSERT INTO gis.receipts(actor_id,request_id,operation,payload_hash,status,body) VALUES(p_actor,p_request_id,'prepare.'||p_operation,digest,code,body);
 RETURN jsonb_build_object('status',code,'body',body);
END $f$;

CREATE FUNCTION gis.ldd_prepare_worker(p_action text,p_payload jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE subject uuid; j gis.jobs%ROWTYPE; e gis.editions%ROWTYPE; token uuid; now_value timestamptz; report jsonb;
 candidate record; recovered integer:=0; next_state text; error_value text; value integer;
BEGIN
 subject:=gis.native_subject();
 IF p_payload ? 'worker_id' AND p_payload->>'worker_id' IS DISTINCT FROM subject::text THEN RAISE EXCEPTION 'GIS_WORKER_IDENTITY_MISMATCH' USING ERRCODE='42501'; END IF;
 IF p_action='claim' THEN
  PERFORM gis.keys(p_payload,ARRAY[]::text[]);
  IF NOT pg_try_advisory_xact_lock(hashtextextended('gis-t1-single-claim',0)) OR EXISTS(SELECT 1 FROM gis.jobs WHERE state='running') THEN RETURN jsonb_build_object('job',NULL); END IF;
  FOR candidate IN SELECT id,edition_id FROM gis.jobs WHERE kind='prepare_ldd_edition' AND state='queued'
    AND attempt_count<3 AND available_at<=clock_timestamp() ORDER BY available_at,created_at,id LIMIT 20 LOOP
   SELECT * INTO e FROM gis.editions WHERE id=candidate.edition_id FOR UPDATE SKIP LOCKED;
   IF NOT FOUND THEN CONTINUE; END IF;
   SELECT * INTO j FROM gis.jobs WHERE id=candidate.id FOR UPDATE SKIP LOCKED;
   IF NOT FOUND OR j.state<>'queued' OR j.available_at>clock_timestamp() THEN CONTINUE; END IF;
   IF gis.publication_validation(e.id) IS NULL THEN RAISE EXCEPTION 'GIS_PREPARE_VALIDATION_REQUIRED'; END IF;
   token:=gen_random_uuid();now_value:=clock_timestamp();
   UPDATE gis.jobs SET state='running',worker_id=subject,lease_token=token,lease_until=now_value+interval '60 seconds',
     attempt_count=attempt_count+1,progress=0,error_code=NULL WHERE id=j.id RETURNING * INTO j;
   INSERT INTO gis.attempts(job_id,attempt_no,worker_id,lease_token,state,started_at) VALUES(j.id,j.attempt_count,subject,token,'running',now_value);
   INSERT INTO gis.audit(operation,dataset_id,edition_id,job_id,detail) VALUES('prepare.claim',e.dataset_id,e.id,j.id,jsonb_build_object('attempt',j.attempt_count));
   RETURN jsonb_build_object('job',jsonb_build_object('id',j.id,'lease_token',token,'kind',j.kind,'prepare_request',gis.ldd_prepare_packet(j.id)));
  END LOOP;
  RETURN jsonb_build_object('job',NULL);
 ELSIF p_action='recover' THEN
  PERFORM gis.keys(p_payload,ARRAY[]::text[]);
  FOR candidate IN SELECT id,edition_id FROM gis.jobs WHERE kind='prepare_ldd_edition' AND state='running'
    AND lease_until<=clock_timestamp() ORDER BY lease_until,id LIMIT 20 LOOP
   SELECT * INTO e FROM gis.editions WHERE id=candidate.edition_id FOR UPDATE SKIP LOCKED;
   IF NOT FOUND THEN CONTINUE; END IF;
   SELECT * INTO j FROM gis.jobs WHERE id=candidate.id FOR UPDATE SKIP LOCKED;
   now_value:=clock_timestamp();
   IF NOT FOUND OR j.state<>'running' OR j.lease_until>now_value THEN CONTINUE; END IF;
   UPDATE gis.attempts SET state='expired',error_code='lease_expired',finished_at=now_value WHERE job_id=j.id AND attempt_no=j.attempt_count AND lease_token=j.lease_token;
   UPDATE gis.jobs SET state=CASE WHEN attempt_count<3 THEN 'queued' ELSE 'failed' END,worker_id=NULL,lease_token=NULL,lease_until=NULL,
    progress=0,available_at=now_value+interval '5 seconds',error_code=CASE WHEN attempt_count=3 THEN 'attempts_exhausted' ELSE NULL END,
    finished_at=CASE WHEN attempt_count=3 THEN now_value ELSE NULL END WHERE id=j.id;
   INSERT INTO gis.audit(operation,dataset_id,edition_id,job_id,detail) VALUES('prepare.recover',e.dataset_id,e.id,j.id,jsonb_build_object('attempt',j.attempt_count));
   recovered:=recovered+1;
  END LOOP;
  RETURN jsonb_build_object('recovered',recovered);
 ELSIF p_action IN ('heartbeat','complete','fail') THEN
  PERFORM gis.keys(p_payload,CASE p_action WHEN 'heartbeat' THEN ARRAY['job_id','lease_token','progress']
    WHEN 'complete' THEN ARRAY['job_id','lease_token','report'] ELSE ARRAY['job_id','lease_token','report','error_code'] END);
  SELECT * INTO j FROM gis.jobs WHERE id=(p_payload->>'job_id')::uuid;
  SELECT * INTO e FROM gis.editions WHERE id=j.edition_id FOR UPDATE;
  SELECT * INTO j FROM gis.jobs WHERE id=(p_payload->>'job_id')::uuid FOR UPDATE;
  now_value:=clock_timestamp();
  IF NOT FOUND OR j.kind<>'prepare_ldd_edition' OR j.state<>'running' OR j.worker_id IS DISTINCT FROM subject
    OR j.lease_token IS DISTINCT FROM (p_payload->>'lease_token')::uuid OR j.lease_until<=now_value THEN RAISE EXCEPTION 'GIS_STALE_LEASE'; END IF;
  IF gis.publication_validation(e.id) IS NULL OR e.input_revision<>j.input_revision OR e.input_hash<>j.input_hash THEN RAISE EXCEPTION 'GIS_INPUT_CHANGED'; END IF;
  IF p_action='heartbeat' THEN
   IF jsonb_typeof(p_payload->'progress') IS DISTINCT FROM 'number' OR p_payload->>'progress' !~ '^[0-9]{1,2}$' THEN RAISE EXCEPTION 'GIS_INVALID_PROGRESS'; END IF;
   value:=(p_payload->>'progress')::integer;
   IF value<j.progress OR value>99 THEN RAISE EXCEPTION 'GIS_INVALID_PROGRESS'; END IF;
   UPDATE gis.jobs SET progress=value,lease_until=now_value+interval '60 seconds' WHERE id=j.id;
   UPDATE gis.attempts SET progress=value WHERE job_id=j.id AND attempt_no=j.attempt_count;
   RETURN jsonb_build_object('progress',value);
  END IF;
  report:=p_payload->'report';PERFORM gis.ldd_prepare_report(j.id,report);
  IF p_action='complete' AND report->'valid'='true'::jsonb THEN
   UPDATE gis.attempts SET state='succeeded',progress=100,finished_at=now_value,validation_report=report WHERE job_id=j.id AND attempt_no=j.attempt_count;
   INSERT INTO gis.results(job_id,edition_id,input_revision,input_hash,validator_version,attempt_no,lease_token,provider,valid,report)
    VALUES(j.id,e.id,j.input_revision,j.input_hash,j.validator_version,j.attempt_count,j.lease_token,'local_ldd_prepare',true,report);
   UPDATE gis.jobs SET state='succeeded',progress=100,finished_at=now_value,worker_id=NULL,lease_token=NULL,lease_until=NULL WHERE id=j.id;
   INSERT INTO gis.audit(operation,dataset_id,edition_id,job_id,detail) VALUES('prepare.complete',e.dataset_id,e.id,j.id,jsonb_build_object('attempt',j.attempt_count));
   RETURN jsonb_build_object('job_id',j.id,'state','succeeded');
  END IF;
  error_value:=CASE WHEN p_action='complete' THEN 'invalid_data' ELSE p_payload->>'error_code' END;
  IF error_value NOT IN ('invalid_data','transient') OR error_value IS NULL OR report->'valid'<>'false'::jsonb
    OR (error_value='transient' AND report->>'error_code' NOT IN ('NATIVE_TIMEOUT','NATIVE_MEMORY_LIMIT','NATIVE_PROCESS_FAILED','WORKER_SHUTDOWN','NATIVE_OUTPUT_LIMIT')) THEN RAISE EXCEPTION 'GIS_INVALID_FAILURE'; END IF;
  next_state:=CASE WHEN error_value='transient' AND j.attempt_count<3 THEN 'queued' ELSE 'failed' END;
  UPDATE gis.attempts SET state='failed',error_code=error_value,finished_at=now_value,validation_report=report WHERE job_id=j.id AND attempt_no=j.attempt_count;
  UPDATE gis.jobs SET state=next_state,progress=0,worker_id=NULL,lease_token=NULL,lease_until=NULL,available_at=now_value+interval '5 seconds',
   error_code=CASE WHEN next_state='failed' THEN error_value ELSE NULL END,finished_at=CASE WHEN next_state='failed' THEN now_value ELSE NULL END WHERE id=j.id;
  INSERT INTO gis.audit(operation,dataset_id,edition_id,job_id,detail) VALUES('prepare.fail',e.dataset_id,e.id,j.id,jsonb_build_object('attempt',j.attempt_count,'error_code',error_value));
  RETURN jsonb_build_object('job_id',j.id,'state',next_state);
 END IF;
 RAISE EXCEPTION 'GIS_UNKNOWN_WORKER_ACTION';
END $f$;

CREATE OR REPLACE FUNCTION gis.check_ldd_catalog() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE eid uuid; jid uuid; e gis.editions%ROWTYPE; u gis.ldd_uploads%ROWTYPE;
 j gis.jobs%ROWTYPE; a gis.attempts%ROWTYPE; r gis.results%ROWTYPE;
BEGIN
 IF TG_TABLE_NAME IN ('editions','ldd_uploads') THEN
   IF TG_TABLE_NAME='editions' THEN eid:=NEW.id; ELSE eid:=NEW.edition_id; END IF;
 ELSE
   IF TG_TABLE_NAME='jobs' THEN jid:=NEW.id; ELSE jid:=NEW.job_id; END IF;
   SELECT edition_id INTO eid FROM gis.jobs WHERE id=jid;
 END IF;
 SELECT * INTO u FROM gis.ldd_uploads WHERE edition_id=eid;
 IF NOT FOUND THEN
   -- A job cannot label itself LDD without an immutable upload association.
   IF jid IS NOT NULL AND EXISTS(SELECT 1 FROM gis.jobs WHERE id=jid AND kind='validate_ldd_edition') THEN
     RAISE EXCEPTION 'GIS_LDD_UPLOAD_REQUIRED'; END IF;
   RETURN NULL;
 END IF;
 SELECT * INTO e FROM gis.editions WHERE id=eid;
 IF e.dataset_id IS DISTINCT FROM u.dataset_id OR e.manifest IS DISTINCT FROM gis.ldd_manifest(u)
   OR e.input_hash IS DISTINCT FROM gis.manifest_hash(e.manifest) THEN RAISE EXCEPTION 'GIS_LDD_INPUT_INVARIANT'; END IF;
 FOR j IN SELECT * FROM gis.jobs WHERE edition_id=e.id AND kind<>'prepare_ldd_edition' LOOP
   IF j.kind<>'validate_ldd_edition' OR j.validator_version<>'ldd-local-v1' THEN RAISE EXCEPTION 'GIS_WORKER_PROTOCOL_MISMATCH'; END IF;
   IF j.state='succeeded' THEN
     SELECT * INTO a FROM gis.attempts WHERE job_id=j.id AND attempt_no=j.attempt_count;
     SELECT * INTO r FROM gis.results WHERE job_id=j.id;
     PERFORM gis.validate_ldd_report(a.validation_report,e,j);
     IF a.state IS DISTINCT FROM 'succeeded' OR r.report IS DISTINCT FROM a.validation_report
       OR a.validation_report->'valid' IS DISTINCT FROM 'true'::jsonb OR r.provider IS DISTINCT FROM 'local_ldd' THEN
       RAISE EXCEPTION 'GIS_LDD_RESULT_INVARIANT'; END IF;
   END IF;
 END LOOP;
 IF TG_TABLE_NAME='attempts' THEN
   IF NEW.state='failed' THEN
     SELECT * INTO j FROM gis.jobs WHERE id=NEW.job_id;
     IF j.kind='prepare_ldd_edition' THEN RETURN NULL; END IF;
     PERFORM gis.validate_ldd_report(NEW.validation_report,e,j);
   END IF;
 END IF;
 RETURN NULL;
END $f$;

CREATE OR REPLACE FUNCTION gis.publication_validation(p_edition uuid) RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE e gis.editions%ROWTYPE; d gis.datasets%ROWTYPE; r gis.results%ROWTYPE;
 j gis.jobs%ROWTYPE; a gis.attempts%ROWTYPE; source_hash text;
BEGIN
 PERFORM gis.assert_environment();
 SELECT * INTO e FROM gis.editions WHERE id=p_edition;
 IF NOT FOUND OR e.state IN ('validating','withdrawn')
    OR EXISTS(SELECT 1 FROM gis.jobs WHERE edition_id=e.id AND kind<>'prepare_ldd_edition' AND state IN ('queued','running')) THEN RETURN NULL; END IF;
 SELECT * INTO d FROM gis.datasets WHERE id=e.dataset_id;
 SELECT result.* INTO r FROM gis.results result JOIN gis.jobs job ON job.id=result.job_id
   JOIN gis.attempts attempt ON attempt.job_id=job.id AND attempt.attempt_no=job.attempt_count
   WHERE result.edition_id=e.id AND result.valid
     AND ((result.provider='local_ldd' AND job.kind='validate_ldd_edition' AND job.validator_version='ldd-local-v1')
       OR (result.provider='local_geotiff' AND job.kind='validate_geotiff_edition' AND job.validator_version='geotiff-local-v1'))
     AND result.input_revision=e.input_revision AND result.input_hash=e.input_hash
     AND job.edition_id=e.id AND job.state='succeeded'
     AND job.input_revision=e.input_revision AND job.input_hash=e.input_hash
     AND result.validator_version=job.validator_version AND result.attempt_no=job.attempt_count
     AND attempt.state='succeeded' AND attempt.lease_token=result.lease_token
     AND attempt.validation_report=result.report AND result.report->'valid'='true'::jsonb
   ORDER BY result.created_at DESC,result.id DESC LIMIT 1;
 IF NOT FOUND THEN RETURN NULL; END IF;
 SELECT * INTO j FROM gis.jobs WHERE id=r.job_id;
 SELECT * INTO a FROM gis.attempts WHERE job_id=j.id AND attempt_no=j.attempt_count;
 IF r.provider='local_ldd' AND j.kind='validate_ldd_edition' AND j.validator_version='ldd-local-v1'
    AND d.kind='ldd_shapefile' AND d.purpose='landuse' AND d.month=0
    AND e.state='validated' AND e.validated_result_id=r.id THEN
   SELECT u.sha256 INTO source_hash FROM gis.ldd_uploads u WHERE u.edition_id=e.id AND u.dataset_id=d.id
     AND e.manifest=gis.ldd_manifest(u);
   IF source_hash IS NULL THEN RETURN NULL; END IF;
   PERFORM gis.validate_ldd_report(r.report,e,j);
 ELSIF r.provider='local_geotiff' AND j.kind='validate_geotiff_edition' AND j.validator_version='geotiff-local-v1'
    AND d.kind='geotiff' AND d.purpose IN ('ndvi','lst') AND e.state='draft' AND e.validated_result_id IS NULL THEN
   SELECT u.sha256 INTO source_hash FROM gis.geotiff_uploads u WHERE u.edition_id=e.id AND u.dataset_id=d.id
     AND u.metric=d.purpose AND e.manifest=gis.geotiff_manifest(u);
   IF source_hash IS NULL THEN RETURN NULL; END IF;
   PERFORM gis.validate_geotiff_report(r.report,e,j);
 ELSE RETURN NULL;
 END IF;
 IF e.input_hash IS DISTINCT FROM gis.manifest_hash(e.manifest) THEN RETURN NULL; END IF;
 RETURN jsonb_build_object('dataset_id',d.id,'edition_id',e.id,'validation_result_id',r.id,
   'input_revision',e.input_revision,'input_hash',e.input_hash,'source_sha256',source_hash,
   'province',d.province,'data_year',d.data_year,'month',d.month,'kind',d.kind,'purpose',d.purpose);
END $f$;

CREATE OR REPLACE FUNCTION gis.queue_protocol_kind(p_action text,p_payload jsonb,p_protocol text) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE j gis.jobs%ROWTYPE; e gis.editions%ROWTYPE; candidate record;
 worker uuid; token uuid; jid uuid; eid uuid; rid uuid; v_now timestamptz;
 progress_value integer; report_value jsonb; code text; next_state text; n integer:=0;
 p_native boolean:=p_protocol<>'v1'; u gis.ldd_uploads%ROWTYPE; ldd_dataset gis.datasets%ROWTYPE; processing_request gis.processing_requests%ROWTYPE; geo gis.geotiff_uploads%ROWTYPE; geo_dataset gis.datasets%ROWTYPE;
BEGIN
 PERFORM gis.assert_environment();
 IF p_protocol NOT IN ('v1','v2','ldd','gee_offline','geotiff') OR p_protocol IS NULL THEN RAISE EXCEPTION 'GIS_WORKER_PROTOCOL_MISMATCH'; END IF;
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
        AND q.kind<>'prepare_ldd_edition' AND gis.edition_protocol(d.id)=p_protocol
      ORDER BY q.available_at,q.created_at,q.id LIMIT 20 LOOP
     SELECT * INTO e FROM gis.editions WHERE id=candidate.edition_id FOR UPDATE SKIP LOCKED;
     IF NOT FOUND THEN CONTINUE; END IF;
     SELECT * INTO j FROM gis.jobs WHERE id=candidate.id FOR UPDATE SKIP LOCKED;
     IF NOT FOUND THEN CONTINUE; END IF;
     v_now:=clock_timestamp();
     IF j.state<>'queued' OR j.attempt_count>=3 OR j.available_at>v_now
       OR e.state<>'validating' OR gis.edition_protocol(e.id) IS DISTINCT FROM p_protocol THEN CONTINUE; END IF;
     token:=gen_random_uuid();
     UPDATE gis.jobs SET state='running',attempt_count=attempt_count+1,worker_id=worker,
       lease_token=token,lease_until=v_now+interval '60 seconds',progress=0,error_code=NULL
       WHERE id=j.id RETURNING * INTO j;
     INSERT INTO gis.attempts(job_id,attempt_no,worker_id,lease_token,state,started_at)
       VALUES(j.id,j.attempt_count,worker,token,'running',v_now);
     report_value:=jsonb_build_object('job_id',j.id,'edition_id',e.id,'worker_id',worker,'lease_token',token,
       'lease_until',j.lease_until,'attempt_no',j.attempt_count,'input_revision',j.input_revision,
       'input_hash',j.input_hash,'validator_version',j.validator_version,'manifest',e.manifest);
     IF p_protocol='ldd' THEN
       SELECT * INTO u FROM gis.ldd_uploads WHERE edition_id=e.id;
       SELECT * INTO ldd_dataset FROM gis.datasets WHERE id=e.dataset_id;
       report_value:=report_value||gis.ldd_upload_row(u)||jsonb_build_object('province',ldd_dataset.province,'data_year',ldd_dataset.data_year);
     END IF;
     IF p_protocol='geotiff' THEN
       SELECT * INTO geo FROM gis.geotiff_uploads WHERE edition_id=e.id;
       SELECT * INTO geo_dataset FROM gis.datasets WHERE id=e.dataset_id;
       report_value:=report_value||gis.geotiff_upload_row(geo)||jsonb_build_object('province',geo_dataset.province,'data_year',geo_dataset.data_year);
     END IF;
     IF p_protocol='gee_offline' THEN
       SELECT * INTO processing_request FROM gis.processing_requests WHERE edition_id=e.id;
       report_value:=report_value||jsonb_build_object('processing_id',processing_request.id);
     END IF;
     IF p_native THEN
       INSERT INTO gis.audit(operation,dataset_id,edition_id,job_id,detail)
         VALUES(CASE WHEN p_protocol='geotiff' THEN 'geotiff.claim' WHEN p_protocol='gee_offline' THEN 'processing.claim' WHEN p_protocol='ldd' THEN 'ldd.claim' ELSE 'worker_v2.claim' END,e.dataset_id,e.id,j.id,jsonb_build_object('worker_id',worker,'attempt',j.attempt_count));
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
       AND q.kind<>'prepare_ldd_edition' AND gis.edition_protocol(d.id)=p_protocol
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
       VALUES(CASE WHEN p_protocol='geotiff' THEN 'geotiff.recover' WHEN p_protocol='gee_offline' THEN 'processing.recover' WHEN p_protocol='ldd' THEN 'ldd.recover' WHEN p_native THEN 'worker_v2.recover' ELSE 'worker.recover' END,e.dataset_id,e.id,j.id,
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
   IF NOT FOUND OR gis.edition_protocol(e.id) IS DISTINCT FROM p_protocol THEN
     RAISE EXCEPTION 'GIS_WORKER_PROTOCOL_MISMATCH' USING ERRCODE='42501'; END IF;
   SELECT * INTO j FROM gis.jobs WHERE id=jid FOR UPDATE;
   v_now:=clock_timestamp();
   IF NOT FOUND OR j.kind='prepare_ldd_edition' OR j.state<>'running' OR j.worker_id IS DISTINCT FROM worker
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
     IF p_protocol='geotiff' THEN PERFORM gis.validate_geotiff_report(report_value,e,j);
     ELSIF p_protocol='gee_offline' THEN PERFORM gis.validate_processing_report(report_value,e,j);
     ELSIF p_protocol='ldd' THEN PERFORM gis.validate_ldd_report(report_value,e,j);
     ELSE PERFORM gis.validate_native_report(report_value,e.manifest,j.input_hash,j.input_revision); END IF;
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
     INSERT INTO gis.results(job_id,edition_id,input_revision,input_hash,validator_version,attempt_no,lease_token,valid,report,provider)
       VALUES(j.id,e.id,j.input_revision,j.input_hash,j.validator_version,j.attempt_count,token,true,report_value,CASE WHEN p_protocol='geotiff' THEN 'local_geotiff' WHEN p_protocol='gee_offline' THEN 'offline_processing' WHEN p_protocol='ldd' THEN 'local_ldd' ELSE 'synthetic' END) RETURNING id INTO rid;
     IF p_protocol IN ('gee_offline','geotiff') THEN
       UPDATE gis.editions SET state='draft',validated_result_id=NULL WHERE id=e.id;
     ELSE
       UPDATE gis.editions SET state='validated',validated_result_id=rid WHERE id=e.id;
     END IF;
     UPDATE gis.jobs SET state='succeeded',worker_id=NULL,lease_token=NULL,lease_until=NULL,progress=100,finished_at=v_now WHERE id=j.id;
     UPDATE gis.attempts SET state='succeeded',progress=100,finished_at=v_now WHERE job_id=j.id AND attempt_no=j.attempt_count AND lease_token=token;
     INSERT INTO gis.audit(operation,dataset_id,edition_id,job_id,detail)
       VALUES(CASE WHEN p_protocol='geotiff' THEN 'geotiff.complete' WHEN p_protocol='gee_offline' THEN 'processing.complete' WHEN p_protocol='ldd' THEN 'ldd.complete' WHEN p_native THEN 'worker_v2.complete' ELSE 'worker.complete' END,e.dataset_id,e.id,j.id,
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
     VALUES(CASE WHEN p_protocol='geotiff' THEN 'geotiff.fail' WHEN p_protocol='gee_offline' THEN 'processing.fail' WHEN p_protocol='ldd' THEN 'ldd.fail' WHEN p_native THEN 'worker_v2.fail' ELSE 'worker.fail' END,e.dataset_id,e.id,j.id,
       jsonb_build_object('attempt',j.attempt_count,'error_code',code,'state',next_state));
   RETURN CASE WHEN p_native THEN jsonb_build_object('job_id',j.id,'state',next_state,'error_code',code)
     ELSE jsonb_build_object('job_id',j.id,'state',next_state) END;
 END IF;
 RAISE EXCEPTION 'GIS_UNKNOWN_WORKER_ACTION';
END $f$;

CREATE FUNCTION gis.check_ldd_prepare_catalog() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE j gis.jobs%ROWTYPE; q gis.ldd_prepare_requests%ROWTYPE; r gis.results%ROWTYPE; e gis.editions%ROWTYPE;
 validation gis.results%ROWTYPE; a gis.attempts%ROWTYPE; jid uuid;
BEGIN
 IF TG_TABLE_NAME='editions' THEN
  -- Withdrawn history may remain; an active preparation cannot change input.
  IF EXISTS(SELECT 1 FROM gis.jobs WHERE edition_id=NEW.id AND kind='prepare_ldd_edition'
    AND state IN ('queued','running') AND (NEW.state<>'validated' OR input_hash<>NEW.input_hash OR input_revision<>NEW.input_revision)) THEN
    RAISE EXCEPTION 'GIS_PREPARE_INPUT_CHANGED'; END IF;
  RETURN NULL;
 END IF;
 IF TG_TABLE_NAME='jobs' THEN jid:=NEW.id; ELSE jid:=NEW.job_id; END IF;
 SELECT * INTO j FROM gis.jobs WHERE id=jid;
 IF TG_TABLE_NAME='ldd_prepare_requests' AND j.kind IS DISTINCT FROM 'prepare_ldd_edition' THEN RAISE EXCEPTION 'GIS_PREPARE_INPUT_CHANGED'; END IF;
 IF j.kind<>'prepare_ldd_edition' OR j.id IS NULL THEN RETURN NULL; END IF;
 SELECT * INTO e FROM gis.editions WHERE id=j.edition_id;
 SELECT * INTO q FROM gis.ldd_prepare_requests WHERE job_id=j.id;
 SELECT * INTO validation FROM gis.results WHERE id=q.validation_result_id;
 IF q.job_id IS NULL OR q.edition_id<>e.id OR validation.edition_id<>e.id OR validation.provider<>'local_ldd'
   OR validation.input_hash<>j.input_hash OR validation.input_revision<>j.input_revision
   OR j.validator_version<>'ldd-prepare-v1' OR j.input_hash<>e.input_hash OR j.input_revision<>e.input_revision THEN
   RAISE EXCEPTION 'GIS_PREPARE_INPUT_CHANGED'; END IF;
 IF j.state='succeeded' THEN
  SELECT * INTO r FROM gis.results WHERE job_id=j.id;
  SELECT * INTO a FROM gis.attempts WHERE job_id=j.id AND attempt_no=j.attempt_count;
  PERFORM gis.ldd_prepare_report(j.id,r.report);
  IF r.provider IS DISTINCT FROM 'local_ldd_prepare' OR r.report->'valid' IS DISTINCT FROM 'true'::jsonb
   OR a.validation_report IS DISTINCT FROM r.report THEN RAISE EXCEPTION 'GIS_PREPARE_REPORT_INVALID'; END IF;
 ELSIF TG_TABLE_NAME='attempts' THEN
  IF NEW.state='failed' THEN PERFORM gis.ldd_prepare_report(j.id,NEW.validation_report); END IF;
 END IF;
 RETURN NULL;
END $f$;
DO $triggers$ DECLARE t text; BEGIN
 FOREACH t IN ARRAY ARRAY['jobs','attempts','results','ldd_prepare_requests','editions'] LOOP
 EXECUTE format('CREATE CONSTRAINT TRIGGER prepare_catalog_integrity AFTER INSERT OR UPDATE ON gis.%I DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION gis.check_ldd_prepare_catalog()',t);
 END LOOP;
END $triggers$;

CREATE OR REPLACE FUNCTION gis.publication_ready(p_edition uuid,p_dataset uuid) RETURNS boolean
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE validation jsonb;
BEGIN
 PERFORM gis.assert_environment();validation:=gis.publication_validation(p_edition);
 IF validation IS NULL OR validation->>'dataset_id' IS DISTINCT FROM p_dataset::text OR validation->>'kind'<>'ldd_shapefile' THEN RETURN false; END IF;
 RETURN EXISTS(SELECT 1 FROM gis.ldd_prepare_certificates c
 JOIN gis.jobs j ON j.id=c.job_id JOIN gis.results r ON r.job_id=j.id AND r.provider='local_ldd_prepare'
 JOIN gis.publication_artifacts g ON g.id=c.geometry_artifact_id
 JOIN gis.publication_artifacts s ON s.id=c.summary_artifact_id
 WHERE c.edition_id=p_edition AND c.validation_result_id=(validation->>'validation_result_id')::uuid AND j.state='succeeded'
 AND g.edition_id=p_edition AND s.edition_id=p_edition AND g.dataset_id=p_dataset AND s.dataset_id=p_dataset
 AND g.artifact_kind='ldd_geometry' AND s.artifact_kind='ldd_summary'
 AND g.method_version='ldd-source-area-v1' AND s.method_version=g.method_version
 AND g.validation_result_id=c.validation_result_id AND s.validation_result_id=c.validation_result_id
 AND g.input_hash=validation->>'input_hash' AND s.input_hash=g.input_hash
 AND g.source_sha256=validation->>'source_sha256' AND s.source_sha256=g.source_sha256
 AND g.artifact_sha256=r.report#>>'{artifacts,ldd_geometry,sha256}' AND s.artifact_sha256=r.report#>>'{artifacts,ldd_summary,sha256}'
 AND NOT EXISTS(SELECT 1 FROM gis.ldd_prepare_revocations WHERE certificate_id=c.id));
END $f$;

-- Service-only certifier. The Backend constructs p_proof only after trusted
-- byte verification; no HTTP/admin payload, worker JWT or ready boolean reaches it.
CREATE FUNCTION gis.ldd_verify_complete(p_actor uuid,p_request_id uuid,p_job uuid,p_proof jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE j gis.jobs%ROWTYPE; e gis.editions%ROWTYPE; d gis.datasets%ROWTYPE; v jsonb; r gis.results%ROWTYPE;
 c gis.ldd_prepare_certificates%ROWTYPE; a gis.publication_artifacts%ROWTYPE; g uuid; s uuid; k text;
 receipt gis.receipts%ROWTYPE; digest text; body jsonb;
BEGIN
 PERFORM gis.authorize(p_actor,false);
 IF p_request_id IS NULL THEN RAISE EXCEPTION 'GIS_REQUEST_ID_REQUIRED'; END IF;
 digest:=encode(sha256(convert_to(jsonb_build_object('job_id',p_job,'proof',p_proof)::text,'UTF8')),'hex');
 PERFORM pg_advisory_xact_lock(hashtextextended(p_actor::text||':'||p_request_id::text,0));
 PERFORM gis.authorize(p_actor,false);
 SELECT * INTO receipt FROM gis.receipts WHERE actor_id=p_actor AND request_id=p_request_id;
 IF FOUND AND (receipt.operation<>'prepare.verify' OR receipt.payload_hash<>digest) THEN RAISE EXCEPTION 'GIS_IDEMPOTENCY_CONFLICT'; END IF;
 SELECT * INTO j FROM gis.jobs WHERE id=p_job;
 SELECT * INTO e FROM gis.editions WHERE id=j.edition_id;
 SELECT * INTO d FROM gis.datasets WHERE id=e.dataset_id FOR NO KEY UPDATE;
 SELECT * INTO e FROM gis.editions WHERE id=e.id FOR UPDATE;
 SELECT * INTO j FROM gis.jobs WHERE id=p_job FOR UPDATE;
 v:=gis.publication_validation(e.id);
 SELECT * INTO r FROM gis.results WHERE job_id=j.id;
 IF v IS NULL OR j.kind<>'prepare_ldd_edition' OR j.state<>'succeeded' OR r.provider<>'local_ldd_prepare'
 OR j.input_hash<>e.input_hash OR j.input_revision<>e.input_revision THEN RAISE EXCEPTION 'GIS_PREPARE_NOT_READY'; END IF;
 PERFORM gis.keys(p_proof,ARRAY['schema_version','method_version','valid','error_code','dataset_id','edition_id','job_id',
   'validation_result_id','source_sha256','input_hash','input_revision','artifacts','verifier_version']);
 IF p_proof->>'verifier_version' IS DISTINCT FROM 'ldd-trusted-bytes-v1'
  OR (p_proof-'verifier_version') IS DISTINCT FROM r.report OR p_proof->'valid' IS DISTINCT FROM 'true'::jsonb THEN
   RAISE EXCEPTION 'GIS_PREPARE_PROOF_INVALID'; END IF;
 PERFORM gis.ldd_prepare_report(j.id,p_proof-'verifier_version');
 SELECT * INTO c FROM gis.ldd_prepare_certificates WHERE job_id=j.id;
 IF FOUND THEN
  IF EXISTS(SELECT 1 FROM gis.ldd_prepare_revocations WHERE certificate_id=c.id) THEN RAISE EXCEPTION 'GIS_PREPARE_CERTIFICATE_REVOKED'; END IF;
  IF receipt.id IS NOT NULL THEN RETURN receipt.body; END IF;
  body:=jsonb_build_object('certificate_id',c.id,'ready_for_publication',true);
  INSERT INTO gis.receipts(actor_id,request_id,operation,payload_hash,status,body) VALUES(p_actor,p_request_id,'prepare.verify',digest,200,body);
  RETURN body;
 END IF;
 FOREACH k IN ARRAY ARRAY['ldd_geometry','ldd_summary'] LOOP
  SELECT * INTO a FROM gis.publication_artifacts WHERE edition_id=e.id AND method_version='ldd-source-area-v1' AND artifact_kind=k;
  IF NOT FOUND THEN
   INSERT INTO gis.publication_artifacts(dataset_id,edition_id,validation_result_id,input_revision,input_hash,source_sha256,
     artifact_kind,artifact_sha256,byte_size,method_version,coverage_province,registered_by)
   VALUES(d.id,e.id,(v->>'validation_result_id')::uuid,e.input_revision,e.input_hash,v->>'source_sha256',k,
     p_proof#>>ARRAY['artifacts',k,'sha256'],(p_proof#>>ARRAY['artifacts',k,'byte_size'])::bigint,'ldd-source-area-v1',d.province,p_actor) RETURNING * INTO a;
  ELSIF a.validation_result_id IS DISTINCT FROM (v->>'validation_result_id')::uuid OR a.input_hash<>e.input_hash
    OR a.artifact_sha256 IS DISTINCT FROM p_proof#>>ARRAY['artifacts',k,'sha256']
    OR a.byte_size IS DISTINCT FROM (p_proof#>>ARRAY['artifacts',k,'byte_size'])::bigint THEN RAISE EXCEPTION 'GIS_ARTIFACT_INPUT_MISMATCH'; END IF;
  IF k='ldd_geometry' THEN g:=a.id; ELSE s:=a.id; END IF;
 END LOOP;
 INSERT INTO gis.ldd_prepare_certificates(job_id,edition_id,validation_result_id,geometry_artifact_id,summary_artifact_id,verifier_version)
 VALUES(j.id,e.id,(v->>'validation_result_id')::uuid,g,s,'ldd-trusted-bytes-v1') RETURNING * INTO c;
 INSERT INTO gis.audit(actor_id,operation,dataset_id,edition_id,job_id,detail)
 VALUES(p_actor,'prepare.verified',d.id,e.id,j.id,jsonb_build_object('certificate_id',c.id,'coverage_mode',c.coverage_mode));
 body:=jsonb_build_object('certificate_id',c.id,'ready_for_publication',true);
 INSERT INTO gis.receipts(actor_id,request_id,operation,payload_hash,status,body) VALUES(p_actor,p_request_id,'prepare.verify',digest,200,body);
 RETURN body;
END $f$;

CREATE FUNCTION gis.ldd_prepare_read(p_actor uuid,p_edition uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE j gis.jobs%ROWTYPE; e gis.editions%ROWTYPE; r gis.results%ROWTYPE; c gis.ldd_prepare_certificates%ROWTYPE;
BEGIN
 PERFORM gis.authorize(p_actor,false);
 SELECT * INTO e FROM gis.editions WHERE id=p_edition;
 IF NOT FOUND THEN RAISE EXCEPTION 'GIS_NOT_FOUND'; END IF;
 SELECT * INTO j FROM gis.jobs WHERE edition_id=e.id AND kind='prepare_ldd_edition' ORDER BY created_at DESC,id DESC LIMIT 1;
 IF NOT FOUND THEN RETURN jsonb_build_object('status','not_prepared','ready_for_publication',false); END IF;
 SELECT * INTO r FROM gis.results WHERE job_id=j.id;
 SELECT * INTO c FROM gis.ldd_prepare_certificates WHERE job_id=j.id;
 RETURN jsonb_build_object('status',j.state,'job',gis.api_read_row('job',to_jsonb(j)),
  'attempts',(SELECT COALESCE(jsonb_agg(gis.api_read_row('attempts',to_jsonb(a)) ORDER BY attempt_no),'[]'::jsonb) FROM gis.attempts a WHERE job_id=j.id),
  'prepare_request',gis.ldd_prepare_packet(j.id),'candidate',r.report,
  'certificate',CASE WHEN c.id IS NULL THEN NULL ELSE to_jsonb(c) END,
  'ready_for_publication',gis.publication_ready(e.id,e.dataset_id),
  'preview_only',true,'complete_province_inventory',false);
END $f$;

CREATE FUNCTION public.gis_ldd_prepare_command(p_actor uuid,p_request_id uuid,p_operation text,p_payload jsonb) RETURNS jsonb
LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,gis
AS $f$ SELECT gis.ldd_prepare_command(p_actor,p_request_id,p_operation,p_payload) $f$;
CREATE FUNCTION public.gis_ldd_prepare_read(p_actor uuid,p_edition uuid) RETURNS jsonb
LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,gis
AS $f$ SELECT gis.ldd_prepare_read(p_actor,p_edition) $f$;
CREATE FUNCTION public.gis_ldd_verify_complete(p_actor uuid,p_request_id uuid,p_job uuid,p_proof jsonb) RETURNS jsonb
LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,gis
AS $f$ SELECT gis.ldd_verify_complete(p_actor,p_request_id,p_job,p_proof) $f$;
CREATE FUNCTION public.gis_ldd_verify_revoke(p_actor uuid,p_certificate uuid,p_reason text) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE c gis.ldd_prepare_certificates%ROWTYPE;
BEGIN
 PERFORM gis.authorize(p_actor,false);
 SELECT * INTO c FROM gis.ldd_prepare_certificates WHERE id=p_certificate;
 IF NOT FOUND THEN RAISE EXCEPTION 'GIS_NOT_FOUND'; END IF;
 PERFORM id FROM gis.datasets WHERE id=(SELECT dataset_id FROM gis.editions WHERE id=c.edition_id) FOR NO KEY UPDATE;
 PERFORM id FROM gis.editions WHERE id=c.edition_id FOR UPDATE;
 PERFORM id FROM gis.jobs WHERE id=c.job_id FOR UPDATE;
 IF p_reason NOT IN ('artifact_unavailable','artifact_corrupt','source_changed') OR p_reason IS NULL THEN RAISE EXCEPTION 'GIS_INVALID_PAYLOAD'; END IF;
 INSERT INTO gis.ldd_prepare_revocations(certificate_id,reason) VALUES(c.id,p_reason) ON CONFLICT DO NOTHING;
 INSERT INTO gis.audit(actor_id,operation,edition_id,job_id,reason) VALUES(p_actor,'prepare.revoked',c.edition_id,c.job_id,p_reason);
END $f$;
CREATE FUNCTION public.gis_ldd_prepare_worker(p_action text,p_payload jsonb DEFAULT '{}') RETURNS jsonb
LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,gis
AS $f$ SELECT gis.ldd_prepare_worker(p_action,p_payload) $f$;
CREATE FUNCTION public.gis_ldd_prepare_readiness() RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE subject uuid;
BEGIN
 subject:=gis.native_subject();
 IF NOT EXISTS(SELECT 1 FROM gis.schema_migrations WHERE version=38) THEN RAISE EXCEPTION 'GIS_PREPARE_NOT_READY'; END IF;
 RETURN (SELECT jsonb_build_object('status','ready','contract_version','1.0.0-a2','subject',subject,'worker_role','gis_native_worker',
  'runtime_instance',runtime_instance,'baseline_fingerprint',baseline_fingerprint,'database_name',database_name,'cluster_name',cluster_name,'mode',mode,
  'migration_versions',(SELECT jsonb_agg(version) FROM gis.schema_migrations)) FROM gis.environment WHERE singleton);
END $f$;

-- Keep declarations unverified. Current certificate is a DB fact, not a live
-- filesystem guarantee. Every HTTP preview/readiness must recheck actual bytes.
CREATE OR REPLACE FUNCTION public.gis_publication_read(p_actor uuid,p_edition uuid,p_method_version text) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE value jsonb; ready boolean;
BEGIN
 PERFORM gis.authorize(p_actor,false);value:=gis.publication_status(p_edition,p_method_version);
 ready:=p_method_version='ldd-source-area-v1' AND gis.publication_ready(p_edition,(value->>'dataset_id')::uuid);
 RETURN value||jsonb_build_object('verification_available',p_method_version='ldd-source-area-v1','coverage_verified',ready,
   'ready_for_publication',ready,'certificate_only_requires_live_byte_check',true,'complete_province_inventory',false,
   'status',CASE WHEN ready THEN 'verified_for_local_review' ELSE value->>'status' END,
   'blocker',CASE WHEN ready THEN NULL ELSE 'TRUSTED_VERIFICATION_REQUIRED' END);
END $f$;

DO $revoke$ DECLARE f record; BEGIN
 FOR f IN SELECT p.oid::regprocedure signature FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
 WHERE n.nspname IN ('gis','public') AND (p.proname LIKE 'ldd_prepare%' OR p.proname LIKE 'ldd_verify%'
 OR p.proname LIKE 'gis_ldd_prepare%' OR p.proname LIKE 'gis_ldd_verify%' OR p.proname='check_ldd_prepare_catalog') LOOP
 EXECUTE format('REVOKE ALL ON FUNCTION %s FROM PUBLIC,anon,authenticated,service_role,gis_worker,gis_native_worker',f.signature);
 END LOOP;
END $revoke$;
GRANT EXECUTE ON FUNCTION public.gis_ldd_prepare_command(uuid,uuid,text,jsonb),public.gis_ldd_prepare_read(uuid,uuid),
 public.gis_ldd_verify_complete(uuid,uuid,uuid,jsonb),public.gis_ldd_verify_revoke(uuid,uuid,text) TO service_role;
GRANT EXECUTE ON FUNCTION public.gis_ldd_prepare_worker(text,jsonb),public.gis_ldd_prepare_readiness() TO gis_native_worker;
RESET ROLE;
REVOKE CREATE ON SCHEMA public FROM gis_owner;
