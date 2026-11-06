-- 048 GEE Dashboard processing (scope 2.1.15). A GIS officer's processing request can
-- now name mode gee_dashboard: a host worker computes NDVI/LST with the existing
-- Dashboard backend GEE path and writes that path's own cache row, then completes the
-- job here with the values and image metadata. Offline mode and every older protocol
-- keep their reviewed behaviour; historical migration bytes are untouched.
-- Nothing here activates editions, opens the A6 genuine/live gates or stores secrets.
-- The attested operator supplies BEGIN/runtime proof and the INSERT-only ledger entry.
DO $guard$ BEGIN
 IF current_database() NOT IN ('postgres','gis_t1_upgrade') OR current_setting('cluster_name')<>'green-area-gis-t0'
 OR NOT EXISTS(SELECT 1 FROM gis.schema_migrations WHERE version=47 AND sha256='b04c63ca3f30a4605d8514bbbfc3195cdbe9a44dac3544b6ca19bf9a8c70962c')
 OR EXISTS(SELECT 1 FROM gis.schema_migrations WHERE version>=48)
 OR NOT EXISTS(SELECT 1 FROM gis.environment WHERE singleton AND NOT activation_enabled
 AND runtime_instance=current_setting('gis.runtime_instance',true) AND baseline_fingerprint=current_setting('gis.baseline_fingerprint',true))
 THEN RAISE EXCEPTION 'GIS_LOCAL_BASELINE_047_REQUIRED';END IF;
END $guard$;
GRANT CREATE ON SCHEMA public TO gis_owner;
SET LOCAL ROLE gis_owner;
SELECT gis.assert_environment();

ALTER TABLE gis.processing_requests DROP CONSTRAINT processing_requests_mode_check;
ALTER TABLE gis.processing_requests ADD CONSTRAINT processing_requests_mode_check CHECK(mode IN ('offline_synthetic','gee_dashboard'));
ALTER TABLE gis.processing_requests ADD CONSTRAINT processing_requests_gee_scenario_check CHECK(mode<>'gee_dashboard' OR scenario='standard');
ALTER TABLE gis.jobs DROP CONSTRAINT jobs_validator_version_check;
ALTER TABLE gis.jobs ADD CONSTRAINT jobs_validator_version_check CHECK(validator_version IN ('synthetic-v1','ldd-local-v1','gee-offline-v1','geotiff-local-v1','ldd-prepare-v1','geotiff-prepare-v1','gee-contract-mock-v1','gee-live-v2','gee-safety-rehearsal-v1','gee-dashboard-v1'));
ALTER TABLE gis.results DROP CONSTRAINT results_provider_check;
ALTER TABLE gis.results ADD CONSTRAINT results_provider_check CHECK(provider IN ('synthetic','local_ldd','offline_processing','local_geotiff','local_ldd_prepare','local_geotiff_prepare','gee_contract_mock','gee_live_v2','gee_safety_rehearsal','gee_genuine_https','gee_dashboard'));

-- Legacy cache table the Dashboard backend path itself writes for this scope/period.
CREATE FUNCTION gis.dashboard_cache_table(p_metric text,p_district text,p_month integer) RETURNS text
LANGUAGE sql IMMUTABLE SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
 SELECT CASE WHEN p_district IS NULL THEN CASE WHEN p_metric='ndvi' THEN 'ndvi' ELSE 'province_lst' END
   ELSE CASE WHEN p_metric='ndvi' THEN 'district_ndvi' ELSE 'district_lst' END END
  ||CASE WHEN p_month=0 THEN '_annual' ELSE '_monthly' END
$f$;

-- Wrapper: offline payloads go to the exact reviewed 035 body unchanged. The GEE
-- branch reuses that body's scope/date validation, then builds its own manifest.
ALTER FUNCTION gis.processing_manifest(jsonb) RENAME TO dashboard_previous_processing_manifest;
CREATE FUNCTION gis.processing_manifest(p_payload jsonb) RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE base jsonb; requested date;
BEGIN
 IF jsonb_typeof(p_payload) IS DISTINCT FROM 'object' OR p_payload->>'mode' IS DISTINCT FROM 'gee_dashboard' THEN
   RETURN gis.dashboard_previous_processing_manifest(p_payload); END IF;
 PERFORM gis.keys(p_payload,ARRAY['province','district','metric','data_year','month','mode','scenario','expected_revision','requested_on']);
 IF jsonb_typeof(p_payload->'requested_on') IS DISTINCT FROM 'string' OR COALESCE(p_payload->>'requested_on','') !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
   OR p_payload->>'scenario' IS DISTINCT FROM 'standard' THEN RAISE EXCEPTION 'GIS_INVALID_PAYLOAD'; END IF;
 requested:=(p_payload->>'requested_on')::date;
 base:=gis.dashboard_previous_processing_manifest((p_payload-'requested_on')||jsonb_build_object('mode','offline_synthetic'));
 RETURN jsonb_build_object('schema_version',9,'provider','gee_dashboard','mode','gee_dashboard',
   'provenance','gis-processing-gee-dashboard-v1','data_kind','summary',
   'province',base->'province','district',base->'district','metric',base->'metric','data_year',base->'data_year','month',base->'month',
   'start_date',base->'start_date','end_date',base->'end_date','scale_m',base->'scale_m','processing_version','gee-dashboard-v1',
   'source_collections',base->'source_collections','cloud_mask',base->'cloud_mask',
   'cache_table',gis.dashboard_cache_table(base->>'metric',base->>'district',(base->>'month')::integer),
   'requested_on',to_char(requested,'YYYY-MM-DD'));
END $f$;

ALTER FUNCTION gis.manifest_hash(jsonb) RENAME TO dashboard_previous_manifest_hash;
CREATE FUNCTION gis.manifest_hash(p_manifest jsonb) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
BEGIN
 IF p_manifest->'schema_version' IS DISTINCT FROM '9'::jsonb THEN RETURN gis.dashboard_previous_manifest_hash(p_manifest); END IF;
 -- Exact rebuild through the same validator; the catalog trigger re-checks the row link.
 IF p_manifest IS NULL OR p_manifest->>'provider' IS DISTINCT FROM 'gee_dashboard' OR p_manifest IS DISTINCT FROM gis.processing_manifest(
   jsonb_build_object('province',p_manifest->'province','district',p_manifest->'district','metric',p_manifest->'metric',
     'data_year',p_manifest->'data_year','month',p_manifest->'month','mode','gee_dashboard','scenario','standard',
     'expected_revision',1,'requested_on',p_manifest->'requested_on')) THEN
   RAISE EXCEPTION 'GIS_GEE_DASHBOARD_MANIFEST_INVALID'; END IF;
 RETURN encode(sha256(convert_to(p_manifest::text,'UTF8')),'hex');
END $f$;

ALTER FUNCTION gis.edition_protocol(uuid) RENAME TO dashboard_previous_edition_protocol;
CREATE FUNCTION gis.edition_protocol(p_edition uuid) RETURNS text LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
 SELECT CASE WHEN e.manifest->'schema_version'='9'::jsonb THEN
   CASE WHEN EXISTS(SELECT 1 FROM gis.processing_requests q WHERE q.edition_id=e.id AND q.mode='gee_dashboard') THEN 'gee_dashboard' ELSE 'unsupported' END
 ELSE gis.dashboard_previous_edition_protocol(p_edition) END FROM gis.editions e WHERE e.id=p_edition
$f$;

-- Processing candidates are never activated; the Dashboard cache row is the output.
ALTER FUNCTION gis.eligible(uuid,uuid) RENAME TO dashboard_previous_eligible;
CREATE FUNCTION gis.eligible(p_edition uuid,p_dataset uuid) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
 SELECT CASE WHEN EXISTS(SELECT 1 FROM gis.editions WHERE id=p_edition AND manifest->'schema_version'='9'::jsonb)
   THEN false ELSE gis.dashboard_previous_eligible(p_edition,p_dataset) END
$f$;

ALTER FUNCTION gis.validate_processing_report(jsonb,gis.editions,gis.jobs) RENAME TO dashboard_previous_validate_processing_report;
CREATE FUNCTION gis.validate_processing_report(p_report jsonb,p_edition gis.editions,p_job gis.jobs) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE request gis.processing_requests%ROWTYPE; stats jsonb; obs jsonb; cache jsonb; lo numeric; hi numeric; item text;
BEGIN
 SELECT * INTO request FROM gis.processing_requests WHERE edition_id=p_edition.id;
 IF request.mode IS DISTINCT FROM 'gee_dashboard' THEN
   PERFORM gis.dashboard_previous_validate_processing_report(p_report,p_edition,p_job); RETURN; END IF;
 IF p_job.edition_id<>p_edition.id OR p_job.kind<>'process_offline_edition' OR p_job.validator_version<>'gee-dashboard-v1'
   OR p_edition.input_hash IS DISTINCT FROM gis.manifest_hash(p_edition.manifest)
   OR p_job.input_hash<>p_edition.input_hash OR p_job.input_revision<>p_edition.input_revision THEN
   RAISE EXCEPTION 'GIS_PROCESSING_INPUT_INVARIANT'; END IF;
 PERFORM gis.keys(p_report,ARRAY['schema_version','provider_build','mode','synthetic','processing_id','input_hash','input_revision','valid','error_code','statistics','metadata','observation','cache']);
 IF NOT p_report ?& ARRAY['schema_version','provider_build','mode','synthetic','processing_id','input_hash','input_revision','valid','error_code','statistics','metadata','observation','cache']
   OR octet_length(p_report::text)>16384 OR p_report->'schema_version' IS DISTINCT FROM '1'::jsonb
   OR p_report->>'provider_build' IS DISTINCT FROM 'gee-dashboard-v1' OR p_report->>'mode' IS DISTINCT FROM 'gee_dashboard'
   OR p_report->'synthetic' IS DISTINCT FROM 'false'::jsonb OR p_report->>'processing_id' IS DISTINCT FROM request.id::text
   OR p_report->>'input_hash' IS DISTINCT FROM p_job.input_hash OR p_report->'input_revision' IS DISTINCT FROM to_jsonb(p_job.input_revision)
   OR p_report->'metadata' IS DISTINCT FROM p_edition.manifest OR jsonb_typeof(p_report->'valid') IS DISTINCT FROM 'boolean' THEN
   RAISE EXCEPTION 'GIS_PROCESSING_REPORT_INVALID'; END IF;
 stats:=p_report->'statistics';
 PERFORM gis.keys(stats,ARRAY['valid_pixels','mean','min','max']);
 IF NOT stats ?& ARRAY['valid_pixels','mean','min','max'] OR stats->'valid_pixels' IS DISTINCT FROM 'null'::jsonb THEN
   RAISE EXCEPTION 'GIS_PROCESSING_REPORT_INVALID'; END IF;
 IF p_report->'valid'='false'::jsonb THEN
   IF jsonb_typeof(p_report->'error_code') IS DISTINCT FROM 'string' OR p_report->>'error_code' !~ '^[A-Z][A-Z0-9_]{0,59}$'
     OR stats->'mean' IS DISTINCT FROM 'null'::jsonb OR stats->'min' IS DISTINCT FROM 'null'::jsonb OR stats->'max' IS DISTINCT FROM 'null'::jsonb
     OR p_report->'observation' IS DISTINCT FROM 'null'::jsonb OR p_report->'cache' IS DISTINCT FROM 'null'::jsonb THEN
     RAISE EXCEPTION 'GIS_PROCESSING_REPORT_INVALID'; END IF;
   RETURN;
 END IF;
 -- Plausibility of real satellite summaries; not a fixed oracle like the offline mode.
 lo:=CASE WHEN request.metric='ndvi' THEN -1 ELSE -60 END; hi:=CASE WHEN request.metric='ndvi' THEN 1 ELSE 90 END;
 IF p_report->'error_code' IS DISTINCT FROM 'null'::jsonb OR jsonb_typeof(stats->'mean') IS DISTINCT FROM 'number'
   OR (stats->>'mean')::numeric NOT BETWEEN lo AND hi THEN RAISE EXCEPTION 'GIS_PROCESSING_SCIENTIFIC_INVARIANT'; END IF;
 IF request.month=0 THEN
   IF jsonb_typeof(stats->'min') IS DISTINCT FROM 'number' OR jsonb_typeof(stats->'max') IS DISTINCT FROM 'number'
     OR (stats->>'min')::numeric<lo OR (stats->>'max')::numeric>hi
     OR (stats->>'min')::numeric>(stats->>'mean')::numeric OR (stats->>'mean')::numeric>(stats->>'max')::numeric THEN
     RAISE EXCEPTION 'GIS_PROCESSING_SCIENTIFIC_INVARIANT'; END IF;
 ELSIF stats->'min' IS DISTINCT FROM 'null'::jsonb OR stats->'max' IS DISTINCT FROM 'null'::jsonb THEN
   -- The monthly Dashboard path yields a mean only; extrema are never invented.
   RAISE EXCEPTION 'GIS_PROCESSING_SCIENTIFIC_INVARIANT'; END IF;
 obs:=p_report->'observation';
 PERFORM gis.keys(obs,ARRAY['from_cache','cached_at','image_count','data_quality']);
 IF NOT obs ?& ARRAY['from_cache','cached_at','image_count','data_quality'] OR jsonb_typeof(obs->'from_cache') IS DISTINCT FROM 'boolean'
   OR (obs->'cached_at'<>'null'::jsonb AND jsonb_typeof(obs->'cached_at')<>'string')
   OR (obs->'image_count'<>'null'::jsonb AND (jsonb_typeof(obs->'image_count')<>'number' OR COALESCE(obs->>'image_count','') !~ '^[0-9]{1,6}$'))
   OR (request.month<>0 AND (obs->'image_count'='null'::jsonb OR (obs->>'image_count')::integer=0))
   OR (obs->'data_quality'<>'null'::jsonb AND jsonb_typeof(obs->'data_quality')<>'object') THEN
   RAISE EXCEPTION 'GIS_PROCESSING_REPORT_INVALID'; END IF;
 cache:=p_report->'cache';
 PERFORM gis.keys(cache,ARRAY['table','province','district','year','month','written']);
 IF NOT cache ?& ARRAY['table','province','district','year','month','written']
   OR cache->>'table' IS DISTINCT FROM p_edition.manifest->>'cache_table' OR cache->>'province' IS DISTINCT FROM request.province
   OR cache->'district' IS DISTINCT FROM COALESCE(to_jsonb(request.district),'null'::jsonb)
   OR cache->'year' IS DISTINCT FROM to_jsonb(request.data_year) OR cache->'month' IS DISTINCT FROM to_jsonb(request.month)
   OR cache->'written' IS DISTINCT FROM 'true'::jsonb THEN RAISE EXCEPTION 'GIS_PROCESSING_REPORT_INVALID'; END IF;
END $f$;

-- Same reviewed 035 trigger body; only the mode-dependent manifest/validator/provider differ.
CREATE OR REPLACE FUNCTION gis.check_processing_catalog() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE eid uuid; jid uuid; e gis.editions%ROWTYPE; d gis.datasets%ROWTYPE; request gis.processing_requests%ROWTYPE;
 j gis.jobs%ROWTYPE; a gis.attempts%ROWTYPE; r gis.results%ROWTYPE; manifest_value jsonb; gee boolean;
BEGIN
 IF TG_TABLE_NAME IN ('editions','processing_requests') THEN
   IF TG_TABLE_NAME='editions' THEN eid:=NEW.id; ELSE eid:=NEW.edition_id; END IF;
 ELSE
   IF TG_TABLE_NAME='jobs' THEN jid:=NEW.id; ELSE jid:=NEW.job_id; END IF;
   SELECT edition_id INTO eid FROM gis.jobs WHERE id=jid;
 END IF;
 SELECT * INTO e FROM gis.editions WHERE id=eid;
 SELECT * INTO request FROM gis.processing_requests WHERE edition_id=eid;
 IF request.id IS NULL THEN
   IF e.manifest->'schema_version' IN ('3'::jsonb,'9'::jsonb) OR (jid IS NOT NULL AND EXISTS(SELECT 1 FROM gis.jobs WHERE id=jid AND kind='process_offline_edition')) THEN
     RAISE EXCEPTION 'GIS_PROCESSING_ASSOCIATION_REQUIRED'; END IF;
   RETURN NULL;
 END IF;
 gee:=request.mode='gee_dashboard';
 SELECT * INTO d FROM gis.datasets WHERE id=e.dataset_id;
 manifest_value:=gis.processing_manifest(jsonb_build_object('province',request.province,'district',request.district,'metric',request.metric,
   'data_year',request.data_year,'month',request.month,'mode',request.mode,'scenario',request.scenario,'expected_revision',1)
   ||CASE WHEN gee THEN jsonb_build_object('requested_on',to_char((request.created_at AT TIME ZONE 'UTC')::date,'YYYY-MM-DD')) ELSE '{}'::jsonb END);
 IF e.dataset_id IS DISTINCT FROM request.dataset_id OR e.manifest IS DISTINCT FROM manifest_value
   OR e.input_hash IS DISTINCT FROM gis.manifest_hash(manifest_value) OR e.input_revision<>1
   OR d.province IS DISTINCT FROM request.province OR d.data_year IS DISTINCT FROM request.data_year OR d.month IS DISTINCT FROM request.month
   OR d.kind IS DISTINCT FROM 'geotiff' OR d.purpose IS DISTINCT FROM request.metric
   OR e.validated_result_id IS NOT NULL OR e.state NOT IN ('draft','validating') OR d.active_edition_id=e.id THEN
   RAISE EXCEPTION 'GIS_PROCESSING_INPUT_INVARIANT'; END IF;
 FOR j IN SELECT * FROM gis.jobs WHERE edition_id=e.id LOOP
   IF j.kind<>'process_offline_edition' OR j.validator_version<>(CASE WHEN gee THEN 'gee-dashboard-v1' ELSE 'gee-offline-v1' END) THEN
     RAISE EXCEPTION 'GIS_WORKER_PROTOCOL_MISMATCH'; END IF;
   IF j.state='succeeded' THEN
     SELECT * INTO a FROM gis.attempts WHERE job_id=j.id AND attempt_no=j.attempt_count;
     SELECT * INTO r FROM gis.results WHERE job_id=j.id;
     PERFORM gis.validate_processing_report(a.validation_report,e,j);
     IF a.state IS DISTINCT FROM 'succeeded' OR r.report IS DISTINCT FROM a.validation_report
       OR a.validation_report->'valid' IS DISTINCT FROM 'true'::jsonb
       OR r.provider IS DISTINCT FROM (CASE WHEN gee THEN 'gee_dashboard' ELSE 'offline_processing' END) THEN
       RAISE EXCEPTION 'GIS_PROCESSING_RESULT_INVARIANT'; END IF;
   END IF;
 END LOOP;
 IF TG_TABLE_NAME='attempts' THEN
   IF NEW.state='failed' THEN
     SELECT * INTO j FROM gis.jobs WHERE id=NEW.job_id;
     PERFORM gis.validate_processing_report(NEW.validation_report,e,j);
     IF NEW.validation_report->'valid' IS DISTINCT FROM 'false'::jsonb THEN RAISE EXCEPTION 'GIS_PROCESSING_REPORT_INVALID'; END IF;
   END IF;
 END IF;
 RETURN NULL;
END $f$;

CREATE OR REPLACE FUNCTION gis.processing_job_row(p_job uuid) RETURNS jsonb
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
 SELECT gis.api_read_row('job',to_jsonb(j))||jsonb_build_object('processing_id',q.id,'mode',q.mode,'metadata',e.manifest,
  'candidate_status',CASE WHEN j.state<>'succeeded' THEN 'not_ready' WHEN q.mode='gee_dashboard' THEN 'dashboard_cache_written' ELSE 'pending_review' END,
  'result',(SELECT gis.api_read_row('result',to_jsonb(r)) FROM gis.results r WHERE r.job_id=j.id))
 FROM gis.jobs j JOIN gis.processing_requests q ON q.edition_id=j.edition_id JOIN gis.editions e ON e.id=q.edition_id
 WHERE j.id=p_job AND j.kind='process_offline_edition'
$f$;

ALTER FUNCTION gis.api_read_row(text,jsonb) RENAME TO dashboard_previous_api_read_row;
CREATE FUNCTION gis.api_read_row(p_kind text,p_row jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
BEGIN
 IF p_kind='result' AND p_row->>'provider'='gee_dashboard' THEN
   -- Same base projection as an offline result, then the GEE mode/report on top.
   RETURN gis.dashboard_previous_api_read_row(p_kind,p_row||jsonb_build_object('provider','offline_processing'))
     ||jsonb_build_object('provider','gee_dashboard','mode','gee_dashboard','candidate_status','dashboard_cache_written','report',p_row->'report');
 END IF;
 RETURN gis.dashboard_previous_api_read_row(p_kind,p_row);
END $f$;

ALTER FUNCTION gis.processing_read(uuid,text,jsonb) RENAME TO dashboard_previous_processing_read;
CREATE FUNCTION gis.processing_read(p_actor uuid,p_kind text,p_payload jsonb DEFAULT '{}') RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE value jsonb;
BEGIN
 value:=gis.dashboard_previous_processing_read(p_actor,p_kind,p_payload);
 IF p_kind='options' THEN
   -- live_enabled stays false: it names the A6 genuine path, which remains closed.
   value:=value||jsonb_build_object('modes',jsonb_build_array('offline_synthetic','gee_dashboard'),
     'gee_dashboard',jsonb_build_object('enabled',true,'processing_version','gee-dashboard-v1',
       'source','Existing Dashboard GEE path (backend project credentials)','writes','dashboard cache row for the requested period only'));
 END IF;
 RETURN value;
END $f$;

CREATE OR REPLACE FUNCTION gis.processing_command(p_actor uuid,p_request_id uuid,p_operation text,p_payload jsonb,p_backend_sandbox boolean DEFAULT false)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE request gis.processing_requests%ROWTYPE; d gis.datasets%ROWTYPE; e gis.editions%ROWTYPE; j gis.jobs%ROWTYPE;
 receipt gis.receipts%ROWTYPE; digest text; manifest_value jsonb; body_value jsonb; reason_value text; status_value integer:=202;
 v_now timestamptz; gee boolean; mode_value text;
BEGIN
 PERFORM gis.authorize(p_actor,false);
 IF p_request_id IS NULL THEN RAISE EXCEPTION 'GIS_REQUEST_ID_REQUIRED'; END IF;
 IF p_operation NOT IN ('create','retry') OR p_operation IS NULL THEN RAISE EXCEPTION 'GIS_UNKNOWN_OPERATION'; END IF;
 PERFORM gis.keys(p_payload,CASE WHEN p_operation='create' THEN ARRAY['province','district','metric','data_year','month','mode','scenario','expected_revision']
   ELSE ARRAY['job_id','expected_revision','input_hash','reason'] END);
 digest:=encode(sha256(convert_to(p_payload::text,'UTF8')),'hex');
 PERFORM pg_advisory_xact_lock(hashtextextended(p_actor::text||':'||p_request_id::text,0));
 PERFORM gis.authorize(p_actor,false);
 SELECT * INTO receipt FROM gis.receipts WHERE actor_id=p_actor AND request_id=p_request_id;
 IF FOUND THEN
   IF receipt.operation IS DISTINCT FROM 'processing.'||p_operation OR receipt.payload_hash<>digest THEN RAISE EXCEPTION 'GIS_IDEMPOTENCY_CONFLICT'; END IF;
   RETURN jsonb_build_object('status',receipt.status,'body',receipt.body);
 END IF;
 IF p_operation='create' THEN
   v_now:=clock_timestamp();
   gee:=p_payload->>'mode'='gee_dashboard';
   -- The request date is server-assigned (never caller input): one GEE run per scope/day.
   manifest_value:=gis.processing_manifest(p_payload||CASE WHEN gee
     THEN jsonb_build_object('requested_on',to_char((v_now AT TIME ZONE 'UTC')::date,'YYYY-MM-DD')) ELSE '{}'::jsonb END);
   mode_value:=manifest_value->>'mode';
   PERFORM pg_advisory_xact_lock(hashtextextended('gis-processing-dataset:'||(manifest_value->>'province')||':'||(manifest_value->>'data_year')||':'||(manifest_value->>'month')||':'||(manifest_value->>'metric'),0));
   SELECT * INTO d FROM gis.datasets WHERE province=manifest_value->>'province' AND data_year=(manifest_value->>'data_year')::integer
     AND month=(manifest_value->>'month')::integer AND kind='geotiff' AND purpose=manifest_value->>'metric' FOR NO KEY UPDATE;
   IF NOT FOUND THEN
     INSERT INTO gis.datasets(province,data_year,month,kind,purpose,title,created_by)
       VALUES(manifest_value->>'province',(manifest_value->>'data_year')::integer,(manifest_value->>'month')::integer,'geotiff',manifest_value->>'metric',
         CASE WHEN gee THEN 'NDVI/LST processing requests' ELSE 'Offline synthetic processing (not live GEE)' END,p_actor)
       ON CONFLICT(province,data_year,month,kind,purpose) DO NOTHING;
     SELECT * INTO d FROM gis.datasets WHERE province=manifest_value->>'province' AND data_year=(manifest_value->>'data_year')::integer
       AND month=(manifest_value->>'month')::integer AND kind='geotiff' AND purpose=manifest_value->>'metric' FOR NO KEY UPDATE;
   END IF;
   SELECT ed.* INTO e FROM gis.editions ed JOIN gis.processing_requests q ON q.edition_id=ed.id
     WHERE ed.dataset_id=d.id AND ed.manifest=manifest_value ORDER BY ed.created_at,ed.id LIMIT 1 FOR UPDATE OF ed;
   IF FOUND THEN
     SELECT * INTO j FROM gis.jobs WHERE edition_id=e.id AND parent_job_id IS NULL;
     status_value:=CASE WHEN j.state IN ('queued','running') THEN 202 ELSE 200 END;
   ELSE
     INSERT INTO gis.editions(dataset_id,manifest,input_hash,created_by)
       VALUES(d.id,manifest_value,gis.manifest_hash(manifest_value),p_actor) RETURNING * INTO e;
     INSERT INTO gis.processing_requests(dataset_id,edition_id,province,district,metric,data_year,month,mode,scenario,requested_by,created_at)
       VALUES(d.id,e.id,manifest_value->>'province',manifest_value->>'district',manifest_value->>'metric',(manifest_value->>'data_year')::integer,
         (manifest_value->>'month')::integer,mode_value,CASE WHEN gee THEN 'standard' ELSE manifest_value->>'scenario' END,p_actor,v_now) RETURNING * INTO request;
     INSERT INTO gis.jobs(edition_id,kind,validator_version,input_revision,input_hash,requested_by)
       VALUES(e.id,'process_offline_edition',CASE WHEN gee THEN 'gee-dashboard-v1' ELSE 'gee-offline-v1' END,e.input_revision,e.input_hash,p_actor) RETURNING * INTO j;
     UPDATE gis.editions SET state='validating' WHERE id=e.id;
   END IF;
 ELSE
   SELECT * INTO j FROM gis.jobs WHERE id=(p_payload->>'job_id')::uuid;
   IF NOT FOUND THEN RAISE EXCEPTION 'GIS_NOT_FOUND'; END IF;
   SELECT * INTO e FROM gis.editions WHERE id=j.edition_id FOR UPDATE;
   SELECT * INTO j FROM gis.jobs WHERE id=j.id FOR UPDATE;
   SELECT * INTO request FROM gis.processing_requests WHERE edition_id=e.id;
   IF request.id IS NULL OR j.kind<>'process_offline_edition' THEN RAISE EXCEPTION 'GIS_NOT_FOUND'; END IF;
   mode_value:=request.mode;
   IF p_payload->'expected_revision' IS DISTINCT FROM to_jsonb(e.input_revision) OR p_payload->>'input_hash' IS DISTINCT FROM e.input_hash THEN
     RAISE EXCEPTION 'GIS_REVISION_CONFLICT'; END IF;
   reason_value:=btrim(p_payload->>'reason');
   IF reason_value IS NULL OR length(reason_value) NOT BETWEEN 1 AND 500 THEN RAISE EXCEPTION 'GIS_REASON_REQUIRED'; END IF;
   IF j.parent_job_id IS NOT NULL OR j.state<>'failed' OR j.error_code NOT IN ('transient','attempts_exhausted')
     OR e.state<>'draft' OR j.input_revision<>e.input_revision OR j.input_hash<>e.input_hash THEN RAISE EXCEPTION 'GIS_RETRY_INELIGIBLE'; END IF;
   IF EXISTS(SELECT 1 FROM gis.jobs WHERE parent_job_id=j.id) THEN RAISE EXCEPTION 'GIS_RETRY_ALREADY_USED'; END IF;
   INSERT INTO gis.jobs(edition_id,parent_job_id,kind,validator_version,input_revision,input_hash,requested_by)
     VALUES(e.id,j.id,'process_offline_edition',j.validator_version,e.input_revision,e.input_hash,p_actor) RETURNING * INTO j;
   UPDATE gis.editions SET state='validating' WHERE id=e.id;
 END IF;
 PERFORM gis.authorize(p_actor,false);
 body_value:=gis.processing_job_row(j.id);
 INSERT INTO gis.audit(actor_id,operation,dataset_id,edition_id,job_id,reason,detail)
   VALUES(p_actor,'processing.'||p_operation,e.dataset_id,e.id,j.id,reason_value,jsonb_build_object('mode',mode_value,'state',j.state));
 INSERT INTO gis.receipts(actor_id,request_id,operation,payload_hash,status,body)
   VALUES(p_actor,p_request_id,'processing.'||p_operation,digest,status_value,body_value);
 RETURN jsonb_build_object('status',status_value,'body',body_value);
END $f$;

CREATE FUNCTION public.gis_gee_dashboard_worker(p_action text,p_payload jsonb DEFAULT '{}') RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE subject uuid;
BEGIN
 subject:=gis.native_subject();
 IF p_payload ? 'worker_id' AND p_payload->>'worker_id' IS DISTINCT FROM subject::text THEN
   RAISE EXCEPTION 'GIS_WORKER_IDENTITY_MISMATCH' USING ERRCODE='42501'; END IF;
 IF p_action='recover' THEN RETURN gis.queue_protocol_kind(p_action,p_payload,'gee_dashboard'); END IF;
 RETURN gis.queue_protocol_kind(p_action,p_payload||jsonb_build_object('worker_id',subject),'gee_dashboard');
END $f$;

CREATE FUNCTION public.gis_gee_dashboard_readiness() RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE subject uuid; value jsonb;
BEGIN
 subject:=gis.native_subject();
 IF NOT EXISTS(SELECT 1 FROM gis.schema_migrations WHERE version=48) THEN RAISE EXCEPTION 'GIS_GEE_DASHBOARD_CONTRACT_NOT_READY'; END IF;
 SELECT jsonb_build_object('status','ready','contract_version','1.0.0-gee-dashboard','worker_role','gis_native_worker',
   'protocol','gee_dashboard','subject',subject,'runtime_instance',runtime_instance,'baseline_fingerprint',baseline_fingerprint,
   'database_name',database_name,'cluster_name',cluster_name,
   'migration_versions',(SELECT jsonb_agg(version ORDER BY version) FROM gis.schema_migrations))
   INTO value FROM gis.environment WHERE singleton;
 RETURN value;
END $f$;

CREATE OR REPLACE FUNCTION gis.queue_protocol_kind(p_action text,p_payload jsonb,p_protocol text) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE safety_session gis.gee_safety_sessions%ROWTYPE; j gis.jobs%ROWTYPE; e gis.editions%ROWTYPE; candidate record;
 worker uuid; token uuid; jid uuid; eid uuid; rid uuid; v_now timestamptz;
 progress_value integer; report_value jsonb; code text; next_state text; n integer:=0;
 p_native boolean:=p_protocol<>'v1'; u gis.ldd_uploads%ROWTYPE; ldd_dataset gis.datasets%ROWTYPE; processing_request gis.processing_requests%ROWTYPE; geo gis.geotiff_uploads%ROWTYPE; geo_dataset gis.datasets%ROWTYPE;
BEGIN
 PERFORM gis.assert_environment();
 IF p_protocol NOT IN ('v1','v2','ldd','gee_offline','gee_dashboard','geotiff','gee_contract_mock','gee_live_v2','gee_safety_rehearsal','gee_genuine_https') OR p_protocol IS NULL THEN RAISE EXCEPTION 'GIS_WORKER_PROTOCOL_MISMATCH'; END IF;
 IF p_action='claim' THEN
   PERFORM gis.keys(p_payload,ARRAY['worker_id']);
   worker:=(p_payload->>'worker_id')::uuid;
   IF worker IS NULL THEN RAISE EXCEPTION 'GIS_WORKER_REQUIRED'; END IF;
   IF NOT pg_try_advisory_xact_lock(hashtextextended('gis-t1-single-claim',0)) THEN
     RETURN CASE WHEN p_native THEN jsonb_build_object('job',NULL) ELSE NULL END; END IF;
   IF EXISTS(SELECT 1 FROM gis.jobs WHERE state='running') THEN
     RETURN CASE WHEN p_native THEN jsonb_build_object('job',NULL) ELSE NULL END; END IF;
   FOR candidate IN SELECT q.id,q.edition_id FROM gis.jobs q JOIN gis.editions d ON d.id=q.edition_id
      WHERE q.state='queued' AND q.attempt_count<(CASE WHEN p_protocol IN ('gee_safety_rehearsal','gee_genuine_https') THEN 2 ELSE 3 END) AND q.available_at<=clock_timestamp()
        AND q.kind NOT IN ('prepare_ldd_edition','prepare_geotiff_edition') AND gis.edition_protocol(d.id)=p_protocol
        AND (p_protocol NOT IN ('gee_safety_rehearsal','gee_genuine_https') OR EXISTS(SELECT 1 FROM gis.gee_safety_jobs b JOIN gis.gee_safety_sessions s ON s.id=b.session_id WHERE b.job_id=q.id AND s.bound_worker=CASE WHEN p_action='claim' THEN worker ELSE (p_payload->>'worker_id')::uuid END AND s.state='open' AND s.ends_at>clock_timestamp()))
      ORDER BY q.available_at,q.created_at,q.id LIMIT 20 LOOP
     SELECT * INTO e FROM gis.editions WHERE id=candidate.edition_id FOR UPDATE SKIP LOCKED;
     IF NOT FOUND THEN CONTINUE; END IF;
     SELECT * INTO j FROM gis.jobs WHERE id=candidate.id FOR UPDATE SKIP LOCKED;
     IF NOT FOUND THEN CONTINUE; END IF;
     v_now:=clock_timestamp();
     IF j.state<>'queued' OR j.attempt_count>=(CASE WHEN p_protocol IN ('gee_safety_rehearsal','gee_genuine_https') THEN 2 ELSE 3 END) OR j.available_at>v_now
       OR e.state<>'validating' OR gis.edition_protocol(e.id) IS DISTINCT FROM p_protocol THEN CONTINUE; END IF;
     IF p_protocol='gee_genuine_https' THEN PERFORM gis.https_assert_authority(j.id);END IF;
     IF p_protocol IN ('gee_safety_rehearsal','gee_genuine_https') THEN PERFORM gis.safety_claim_guard(j.id,worker); END IF;
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
     IF p_protocol IN ('gee_safety_rehearsal','gee_genuine_https') THEN
       report_value:=report_value||gis.gee_live_claim_packet(j.id)||jsonb_build_object('session_id',e.manifest->>'session_id','policy_sha256',e.manifest->>'policy_sha256','job_remaining_seconds',(SELECT greatest(0,extract(epoch FROM(min(started_at)+interval '180 seconds'-clock_timestamp()))) FROM gis.attempts WHERE job_id=j.id));
     END IF;
     IF p_protocol='gee_live_v2' THEN
       report_value:=report_value||gis.gee_live_claim_packet(j.id);
     END IF;
     IF p_protocol='gee_contract_mock' THEN
       report_value:=report_value||gis.gee_mock_claim_packet(j.id);
     END IF;
     IF p_protocol IN ('gee_offline','gee_dashboard') THEN
       SELECT * INTO processing_request FROM gis.processing_requests WHERE edition_id=e.id;
       report_value:=report_value||jsonb_build_object('processing_id',processing_request.id);
     END IF;
     IF p_native THEN
       INSERT INTO gis.audit(operation,dataset_id,edition_id,job_id,detail)
         VALUES(CASE WHEN p_protocol IN ('gee_safety_rehearsal','gee_genuine_https') THEN 'safety.'||p_action WHEN p_protocol='gee_live_v2' THEN 'gee_live.'||p_action WHEN p_protocol='gee_contract_mock' THEN 'gee_mock.claim' WHEN p_protocol='geotiff' THEN 'geotiff.claim' WHEN p_protocol IN ('gee_offline','gee_dashboard') THEN 'processing.claim' WHEN p_protocol='ldd' THEN 'ldd.claim' ELSE 'worker_v2.claim' END,e.dataset_id,e.id,j.id,jsonb_build_object('worker_id',worker,'attempt',j.attempt_count));
       RETURN jsonb_build_object('job',report_value||jsonb_build_object('id',j.id,'dataset_id',e.dataset_id,
         'kind',j.kind,'attempt_number',j.attempt_count));
     END IF;
     RETURN report_value;
   END LOOP;
   RETURN CASE WHEN p_native THEN jsonb_build_object('job',NULL) ELSE NULL END;
 ELSIF p_action='recover' THEN
   PERFORM gis.keys(p_payload,CASE WHEN p_protocol IN ('gee_safety_rehearsal','gee_genuine_https') THEN ARRAY['worker_id'] ELSE ARRAY[]::text[] END);
   FOR candidate IN SELECT q.id,q.edition_id FROM gis.jobs q JOIN gis.editions d ON d.id=q.edition_id
     WHERE q.state='running' AND q.lease_until<=clock_timestamp()
       AND q.kind NOT IN ('prepare_ldd_edition','prepare_geotiff_edition') AND gis.edition_protocol(d.id)=p_protocol
        AND (p_protocol NOT IN ('gee_safety_rehearsal','gee_genuine_https') OR EXISTS(SELECT 1 FROM gis.gee_safety_jobs b JOIN gis.gee_safety_sessions s ON s.id=b.session_id WHERE b.job_id=q.id AND s.bound_worker=CASE WHEN p_action='claim' THEN worker ELSE (p_payload->>'worker_id')::uuid END AND s.state='open' AND s.ends_at>clock_timestamp()))
     ORDER BY q.lease_until,q.id LIMIT 20 LOOP
     SELECT * INTO e FROM gis.editions WHERE id=candidate.edition_id FOR UPDATE SKIP LOCKED;
     IF NOT FOUND THEN CONTINUE; END IF;
     SELECT * INTO j FROM gis.jobs WHERE id=candidate.id FOR UPDATE SKIP LOCKED;
     IF NOT FOUND THEN CONTINUE; END IF;
     v_now:=clock_timestamp();
     IF j.state<>'running' OR j.lease_until>v_now THEN CONTINUE; END IF;
     IF p_protocol IN ('gee_safety_rehearsal','gee_genuine_https') THEN PERFORM gis.safety_abandon(j.id,j.attempt_count,j.lease_token); END IF;
     UPDATE gis.attempts SET state='expired',error_code='lease_expired',finished_at=v_now
       WHERE job_id=j.id AND attempt_no=j.attempt_count AND lease_token=j.lease_token AND state='running';
     IF p_protocol IN ('gee_safety_rehearsal','gee_genuine_https') THEN SELECT s.* INTO safety_session FROM gis.gee_safety_sessions s JOIN gis.gee_safety_jobs b ON b.session_id=s.id WHERE b.job_id=j.id; END IF;
     IF j.attempt_count<(CASE WHEN p_protocol IN ('gee_safety_rehearsal','gee_genuine_https') THEN 2 ELSE 3 END) AND (p_protocol NOT IN ('gee_safety_rehearsal','gee_genuine_https') OR (safety_session.state='open' AND safety_session.ends_at>clock_timestamp() AND NOT EXISTS(SELECT 1 FROM gis.attempts a WHERE a.job_id=j.id GROUP BY a.job_id HAVING min(a.started_at)+interval '180 seconds'<=clock_timestamp()))) THEN
       UPDATE gis.jobs SET state='queued',worker_id=NULL,lease_token=NULL,lease_until=NULL,progress=0,
         available_at=v_now+make_interval(secs=>CASE j.attempt_count WHEN 1 THEN 5 ELSE 20 END+floor(random()*3)::int)
         WHERE id=j.id;
     ELSE
       UPDATE gis.jobs SET state='failed',worker_id=NULL,lease_token=NULL,lease_until=NULL,
         error_code='attempts_exhausted',finished_at=v_now WHERE id=j.id;
       UPDATE gis.editions SET state='draft' WHERE id=e.id AND state='validating';
     END IF;
     INSERT INTO gis.audit(operation,dataset_id,edition_id,job_id,detail)
       VALUES(CASE WHEN p_protocol IN ('gee_safety_rehearsal','gee_genuine_https') THEN 'safety.'||p_action WHEN p_protocol='gee_live_v2' THEN 'gee_live.'||p_action WHEN p_protocol='gee_contract_mock' THEN 'gee_mock.recover' WHEN p_protocol='geotiff' THEN 'geotiff.recover' WHEN p_protocol IN ('gee_offline','gee_dashboard') THEN 'processing.recover' WHEN p_protocol='ldd' THEN 'ldd.recover' WHEN p_native THEN 'worker_v2.recover' ELSE 'worker.recover' END,e.dataset_id,e.id,j.id,
         jsonb_build_object('attempt',j.attempt_count,'terminal',j.attempt_count=(CASE WHEN p_protocol IN ('gee_safety_rehearsal','gee_genuine_https') THEN 2 ELSE 3 END)));
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
   IF NOT FOUND OR j.kind IN ('prepare_ldd_edition','prepare_geotiff_edition') OR j.state<>'running' OR j.worker_id IS DISTINCT FROM worker
     OR j.lease_token IS DISTINCT FROM token OR j.lease_until<=v_now THEN RAISE EXCEPTION 'GIS_STALE_LEASE'; END IF;
   IF p_protocol='gee_genuine_https' AND p_action<>'fail' THEN PERFORM gis.https_assert_authority(j.id);END IF;
   IF p_protocol IN ('gee_safety_rehearsal','gee_genuine_https') THEN PERFORM gis.safety_lock(j.id,worker,token,p_action<>'fail'); END IF;
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
     IF p_protocol IN ('gee_safety_rehearsal','gee_genuine_https') THEN PERFORM gis.validate_safety_report(report_value,e,j);
     ELSIF p_protocol='gee_live_v2' THEN PERFORM gis.validate_gee_live_report(report_value,e,j);
     ELSIF p_protocol='gee_contract_mock' THEN PERFORM gis.validate_gee_mock_report(report_value,e,j);
     ELSIF p_protocol='geotiff' THEN PERFORM gis.validate_geotiff_report(report_value,e,j);
     ELSIF p_protocol IN ('gee_offline','gee_dashboard') THEN PERFORM gis.validate_processing_report(report_value,e,j);
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
       VALUES(j.id,e.id,j.input_revision,j.input_hash,j.validator_version,j.attempt_count,token,true,report_value,CASE WHEN p_protocol IN ('gee_safety_rehearsal','gee_genuine_https') THEN p_protocol WHEN p_protocol='gee_live_v2' THEN 'gee_live_v2' WHEN p_protocol='gee_contract_mock' THEN 'gee_contract_mock' WHEN p_protocol='geotiff' THEN 'local_geotiff' WHEN p_protocol='gee_dashboard' THEN 'gee_dashboard' WHEN p_protocol='gee_offline' THEN 'offline_processing' WHEN p_protocol='ldd' THEN 'local_ldd' ELSE 'synthetic' END) RETURNING id INTO rid;
     IF p_protocol IN ('gee_offline','gee_dashboard','geotiff','gee_contract_mock','gee_live_v2','gee_safety_rehearsal','gee_genuine_https') THEN
       UPDATE gis.editions SET state='draft',validated_result_id=NULL WHERE id=e.id;
     ELSE
       UPDATE gis.editions SET state='validated',validated_result_id=rid WHERE id=e.id;
     END IF;
     IF p_protocol IN ('gee_safety_rehearsal','gee_genuine_https') THEN PERFORM gis.safety_record_candidate(j.id,rid,worker); END IF;
     IF p_protocol='gee_live_v2' THEN PERFORM gis.gee_live_record_candidate(j.id,rid,worker); END IF;
     IF p_protocol='gee_contract_mock' THEN PERFORM gis.gee_mock_record_candidate(j.id,rid,worker); END IF;
     UPDATE gis.jobs SET state='succeeded',worker_id=NULL,lease_token=NULL,lease_until=NULL,progress=100,finished_at=v_now WHERE id=j.id;
     UPDATE gis.attempts SET state='succeeded',progress=100,finished_at=v_now WHERE job_id=j.id AND attempt_no=j.attempt_count AND lease_token=token;
     INSERT INTO gis.audit(operation,dataset_id,edition_id,job_id,detail)
       VALUES(CASE WHEN p_protocol IN ('gee_safety_rehearsal','gee_genuine_https') THEN 'safety.'||p_action WHEN p_protocol='gee_live_v2' THEN 'gee_live.'||p_action WHEN p_protocol='gee_contract_mock' THEN 'gee_mock.complete' WHEN p_protocol='geotiff' THEN 'geotiff.complete' WHEN p_protocol IN ('gee_offline','gee_dashboard') THEN 'processing.complete' WHEN p_protocol='ldd' THEN 'ldd.complete' WHEN p_native THEN 'worker_v2.complete' ELSE 'worker.complete' END,e.dataset_id,e.id,j.id,
         jsonb_build_object('result_id',rid,'attempt',j.attempt_count));
     RETURN jsonb_build_object('job_id',j.id,'state','succeeded','result_id',rid);
   END IF;
   IF p_action='complete' THEN code:='invalid_data';
   ELSE code:=p_payload->>'error_code'; END IF;
   IF code IS NULL OR code NOT IN ('invalid_data','transient') THEN RAISE EXCEPTION 'GIS_INVALID_FAILURE'; END IF;
   IF p_native AND p_action='fail' AND (code<>'transient' OR report_value->>'error_code' NOT IN (
     'NATIVE_TIMEOUT','NATIVE_MEMORY_LIMIT','NATIVE_PROCESS_FAILED','TRANSIENT_SYNTHETIC','WORKER_SHUTDOWN','NATIVE_OUTPUT_LIMIT')) THEN
     RAISE EXCEPTION 'GIS_INVALID_FAILURE'; END IF;
   IF p_protocol IN ('gee_safety_rehearsal','gee_genuine_https') THEN PERFORM gis.safety_abandon(j.id,j.attempt_count,token); END IF;
   next_state:=CASE WHEN code='transient' AND (p_protocol NOT IN ('gee_safety_rehearsal','gee_genuine_https') OR EXISTS(SELECT 1 FROM gis.gee_safety_sessions s JOIN gis.gee_safety_jobs b ON b.session_id=s.id WHERE b.job_id=j.id AND s.state='open' AND s.ends_at>clock_timestamp())) AND j.attempt_count<(CASE WHEN p_protocol IN ('gee_safety_rehearsal','gee_genuine_https') THEN 2 ELSE 3 END) THEN 'queued' ELSE 'failed' END;
   UPDATE gis.attempts SET state='failed',error_code=code,finished_at=v_now
     WHERE job_id=j.id AND attempt_no=j.attempt_count AND lease_token=token;
   UPDATE gis.jobs SET state=next_state,worker_id=NULL,lease_token=NULL,lease_until=NULL,
     error_code=CASE WHEN next_state='failed' THEN code ELSE NULL END,progress=0,
     available_at=v_now+make_interval(secs=>CASE j.attempt_count WHEN 1 THEN 5 ELSE 20 END+floor(random()*3)::int),
     finished_at=CASE WHEN next_state='failed' THEN v_now ELSE NULL END WHERE id=j.id;
   IF next_state='failed' THEN UPDATE gis.editions SET state='draft' WHERE id=e.id; END IF;
   INSERT INTO gis.audit(operation,dataset_id,edition_id,job_id,detail)
     VALUES(CASE WHEN p_protocol IN ('gee_safety_rehearsal','gee_genuine_https') THEN 'safety.'||p_action WHEN p_protocol='gee_live_v2' THEN 'gee_live.'||p_action WHEN p_protocol='gee_contract_mock' THEN 'gee_mock.fail' WHEN p_protocol='geotiff' THEN 'geotiff.fail' WHEN p_protocol IN ('gee_offline','gee_dashboard') THEN 'processing.fail' WHEN p_protocol='ldd' THEN 'ldd.fail' WHEN p_native THEN 'worker_v2.fail' ELSE 'worker.fail' END,e.dataset_id,e.id,j.id,
       jsonb_build_object('attempt',j.attempt_count,'error_code',code,'state',next_state));
   RETURN CASE WHEN p_native THEN jsonb_build_object('job_id',j.id,'state',next_state,'error_code',code)
     ELSE jsonb_build_object('job_id',j.id,'state',next_state) END;
 END IF;
 RAISE EXCEPTION 'GIS_UNKNOWN_WORKER_ACTION';
END $f$;

DO $acl$ DECLARE f record;BEGIN
 FOR f IN SELECT p.oid::regprocedure AS sig FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
 WHERE (n.nspname='gis' AND p.proname IN ('dashboard_cache_table','processing_manifest','manifest_hash','edition_protocol','eligible',
   'validate_processing_report','api_read_row','processing_read','check_processing_catalog','processing_job_row','processing_command','queue_protocol_kind')
   OR (n.nspname='gis' AND p.proname LIKE 'dashboard\_previous\_%'))
 OR (n.nspname='public' AND p.proname IN ('gis_gee_dashboard_worker','gis_gee_dashboard_readiness')) LOOP
 EXECUTE format('REVOKE ALL ON FUNCTION %s FROM PUBLIC,anon,authenticated,service_role,gis_worker,gis_native_worker,gis_gee_mock_worker,gis_gee_live_worker,gis_gee_safety_worker,gis_gee_transport_recorder,gis_gee_https_worker,gis_gee_https_recorder',f.sig);
 END LOOP;
END $acl$;
GRANT EXECUTE ON FUNCTION public.gis_gee_dashboard_worker(text,jsonb),public.gis_gee_dashboard_readiness() TO gis_native_worker;
RESET ROLE;
REVOKE CREATE ON SCHEMA public FROM gis_owner;
NOTIFY pgrst,'reload schema';
