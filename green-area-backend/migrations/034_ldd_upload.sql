-- Phase 2: local immutable LDD upload association and native queue extension.
-- Reviewed forward migration only; guarded local runner owns transaction/ledger.
GRANT CREATE ON SCHEMA public TO gis_owner;
SET LOCAL ROLE gis_owner;
SELECT gis.assert_environment();
DO $guard$
BEGIN
 IF current_database() NOT IN ('postgres','gis_t1_upgrade') OR NOT gis.target_ok()
   OR NOT EXISTS(SELECT 1 FROM gis.environment WHERE singleton
      AND runtime_instance=current_setting('gis.runtime_instance',true)
      AND baseline_fingerprint=current_setting('gis.baseline_fingerprint',true))
   OR NOT EXISTS(SELECT 1 FROM gis.schema_migrations WHERE version=33
      AND sha256='bce2e1fd6021c5b1de51e159ac5fa1f26e4042637ffda63084df7c450f12f824')
   OR EXISTS(SELECT 1 FROM gis.schema_migrations WHERE version>=34) THEN
   RAISE EXCEPTION 'GIS_LOCAL_BASELINE_033_REQUIRED'; END IF;
END $guard$;

CREATE TABLE gis.ldd_uploads(
 id uuid PRIMARY KEY,
 dataset_id uuid NOT NULL REFERENCES gis.datasets(id),
 edition_id uuid NOT NULL UNIQUE,
 sha256 text NOT NULL CHECK(sha256 ~ '^[0-9a-f]{64}$'),
 byte_size bigint NOT NULL CHECK(byte_size BETWEEN 1 AND 20971520),
 crs text NOT NULL CHECK(crs IN ('EPSG:32647','EPSG:32648','EPSG:4326')),
 encoding text NOT NULL CHECK(encoding IN ('auto','utf-8','cp874','tis-620')),
 uploaded_by uuid REFERENCES public.profiles(id) ON DELETE SET NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 FOREIGN KEY(edition_id,dataset_id) REFERENCES gis.editions(id,dataset_id),
 UNIQUE(dataset_id,sha256,crs,encoding));
ALTER TABLE gis.ldd_uploads ENABLE ROW LEVEL SECURITY;
ALTER TABLE gis.ldd_uploads FORCE ROW LEVEL SECURITY;
CREATE POLICY owner_access ON gis.ldd_uploads TO gis_owner USING(true) WITH CHECK(true);
REVOKE ALL ON gis.ldd_uploads FROM PUBLIC,anon,authenticated,service_role,gis_worker,gis_native_worker;

ALTER TABLE gis.jobs DROP CONSTRAINT jobs_kind_check;
ALTER TABLE gis.jobs ADD CONSTRAINT jobs_kind_check CHECK(kind IN ('validate_synthetic_edition','validate_ldd_edition'));
ALTER TABLE gis.jobs DROP CONSTRAINT jobs_validator_version_check;
ALTER TABLE gis.jobs ADD CONSTRAINT jobs_validator_version_check CHECK(validator_version IN ('synthetic-v1','ldd-local-v1'));
ALTER TABLE gis.results DROP CONSTRAINT results_provider_check;
ALTER TABLE gis.results ADD CONSTRAINT results_provider_check CHECK(provider IN ('synthetic','local_ldd'));

CREATE FUNCTION gis.ldd_manifest(p_upload gis.ldd_uploads) RETURNS jsonb
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
 SELECT jsonb_build_object('schema_version',1,'provider','real','sha256',(p_upload).sha256,
   'byte_size',(p_upload).byte_size,'provenance','local-ldd-upload-v1','crs',(p_upload).crs,
   'data_kind','polygon','attributes',jsonb_build_array('LUL1_CODE','LU_CODE','Shape_Area'))
$f$;

CREATE FUNCTION gis.ldd_upload_row(p_upload gis.ldd_uploads) RETURNS jsonb
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
 SELECT jsonb_build_object('upload_id',(p_upload).id,'dataset_id',(p_upload).dataset_id,'edition_id',(p_upload).edition_id,
  'sha256',(p_upload).sha256,'byte_size',(p_upload).byte_size,'crs',(p_upload).crs,'encoding',(p_upload).encoding,
  'created_at',(p_upload).created_at)
$f$;

CREATE FUNCTION gis.guard_ldd_upload() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'GIS_HARD_DELETE_FORBIDDEN'; END IF;
 IF TG_OP='UPDATE' AND NOT(pg_trigger_depth()>1 AND NEW.uploaded_by IS NULL
   AND (to_jsonb(NEW)-'uploaded_by')=(to_jsonb(OLD)-'uploaded_by')) THEN
   RAISE EXCEPTION 'GIS_UPLOAD_IMMUTABLE'; END IF;
 RETURN NEW;
END $f$;

-- Queue routing is determined from immutable server-side association, never a
-- protocol supplied by an HTTP caller or Worker payload.
CREATE FUNCTION gis.edition_protocol(p_edition uuid) RETURNS text
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
 SELECT CASE WHEN EXISTS(SELECT 1 FROM gis.ldd_uploads u WHERE u.edition_id=e.id) THEN 'ldd'
   WHEN e.manifest->>'provider'='synthetic' AND e.manifest->'schema_version'='2'::jsonb THEN 'v2'
   WHEN e.manifest->>'provider'='synthetic' AND e.manifest->'schema_version'='1'::jsonb THEN 'v1'
   ELSE 'unsupported' END FROM gis.editions e WHERE e.id=p_edition
$f$;
CREATE TRIGGER immutable_upload BEFORE UPDATE OR DELETE ON gis.ldd_uploads
 FOR EACH ROW EXECUTE FUNCTION gis.guard_ldd_upload();

CREATE FUNCTION gis.validate_ldd_report(p_report jsonb,p_edition gis.editions,p_job gis.jobs) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE u gis.ldd_uploads%ROWTYPE; d gis.datasets%ROWTYPE; item jsonb; stats jsonb; k text; v jsonb;
 total numeric; known_total numeric:=0; required_checks jsonb;
BEGIN
 SELECT * INTO u FROM gis.ldd_uploads WHERE edition_id=p_edition.id;
 SELECT * INTO d FROM gis.datasets WHERE id=p_edition.dataset_id;
 IF u.id IS NULL OR d.kind<>'ldd_shapefile' OR d.purpose<>'landuse' OR d.month<>0
   OR p_edition.manifest IS DISTINCT FROM gis.ldd_manifest(u)
   OR p_job.kind<>'validate_ldd_edition' OR p_job.validator_version<>'ldd-local-v1'
   OR p_job.edition_id<>p_edition.id OR p_job.input_revision<>p_edition.input_revision
   OR p_job.input_hash<>p_edition.input_hash THEN RAISE EXCEPTION 'GIS_LDD_INPUT_INVARIANT'; END IF;
 IF jsonb_typeof(p_report) IS DISTINCT FROM 'object' OR octet_length(p_report::text)>16384
   OR NOT p_report ?& ARRAY['schema_version','provider_build','upload_id','artifact_sha256','byte_size',
       'input_hash','input_revision','province','data_year','crs','encoding','valid','checks','errors','warnings',
       'statistics','error_code','boundary_sha256'] THEN RAISE EXCEPTION 'GIS_LDD_REPORT_REQUIRED'; END IF;
 PERFORM gis.keys(p_report,ARRAY['schema_version','provider_build','upload_id','artifact_sha256','byte_size',
       'input_hash','input_revision','province','data_year','crs','encoding','valid','checks','errors','warnings',
       'statistics','error_code','boundary_sha256','observed_sha256']);
 IF p_report->'schema_version' IS DISTINCT FROM '1'::jsonb
   OR p_report->>'provider_build' IS DISTINCT FROM 'ldd-local-v1'
   OR p_report->>'upload_id' IS DISTINCT FROM u.id::text
   OR p_report->>'artifact_sha256' IS DISTINCT FROM u.sha256
   OR p_report->'byte_size' IS DISTINCT FROM to_jsonb(u.byte_size)
   OR p_report->>'input_hash' IS DISTINCT FROM p_job.input_hash
   OR p_report->'input_revision' IS DISTINCT FROM to_jsonb(p_job.input_revision)
   OR p_report->>'province' IS DISTINCT FROM d.province OR p_report->'data_year' IS DISTINCT FROM to_jsonb(d.data_year)
   OR p_report->>'crs' IS DISTINCT FROM u.crs
   OR p_report->>'boundary_sha256' IS DISTINCT FROM 'ac2b28255f22861ab644bf083fa40f28dd9da1294648d4b01cfc6f9cdc156a21'
   OR jsonb_typeof(p_report->'valid') IS DISTINCT FROM 'boolean'
   OR jsonb_typeof(p_report->'checks') IS DISTINCT FROM 'array'
   OR jsonb_typeof(p_report->'errors') IS DISTINCT FROM 'array'
   OR jsonb_typeof(p_report->'warnings') IS DISTINCT FROM 'array'
   OR jsonb_typeof(p_report->'statistics') IS DISTINCT FROM 'object'
   OR p_report->>'encoding' IS NULL OR p_report->>'encoding' NOT IN ('auto','utf-8','cp874','tis-620') THEN
   RAISE EXCEPTION 'GIS_LDD_REPORT_INVALID'; END IF;
 IF p_report ? 'observed_sha256' AND p_report->'observed_sha256'<>'null'::jsonb
   AND (jsonb_typeof(p_report->'observed_sha256') IS DISTINCT FROM 'string'
     OR p_report->>'observed_sha256' !~ '^[0-9a-f]{64}$') THEN RAISE EXCEPTION 'GIS_LDD_REPORT_INVALID'; END IF;
 required_checks:='["source_hash_match","archive_safety","components","crs","geometry","attributes","encoding","ldd_codes","province_bounds","dataset_association"]';
 IF jsonb_array_length(p_report->'checks')>10 OR jsonb_array_length(p_report->'errors')>20 OR jsonb_array_length(p_report->'warnings')>20
   OR EXISTS(SELECT 1 FROM jsonb_array_elements(p_report->'checks') x WHERE jsonb_typeof(x)<>'string' OR NOT required_checks @> jsonb_build_array(x))
   OR (SELECT count(*) FROM jsonb_array_elements(p_report->'checks'))<>(SELECT count(DISTINCT x) FROM jsonb_array_elements(p_report->'checks') x) THEN
   RAISE EXCEPTION 'GIS_LDD_REPORT_INVALID'; END IF;
 FOR item IN SELECT x FROM jsonb_array_elements((p_report->'errors')||(p_report->'warnings')) x LOOP
   PERFORM gis.keys(item,ARRAY['code','count']);
   IF jsonb_typeof(item->'code') IS DISTINCT FROM 'string' OR item->>'code' !~ '^[A-Z0-9_]{1,60}$'
     OR jsonb_typeof(item->'count') IS DISTINCT FROM 'number' OR COALESCE(item->>'count','') !~ '^[0-9]{1,9}$' THEN
     RAISE EXCEPTION 'GIS_LDD_REPORT_INVALID'; END IF;
 END LOOP;
 stats:=p_report->'statistics';
 PERFORM gis.keys(stats,ARRAY['feature_count','total_area_m2','unknown_area_m2','unknown_code_count','composite_feature_count','geometry_error_count','area_by_main_m2']);
 IF NOT stats ?& ARRAY['feature_count','total_area_m2','unknown_area_m2','unknown_code_count','composite_feature_count','geometry_error_count','area_by_main_m2']
   OR jsonb_typeof(stats->'area_by_main_m2') IS DISTINCT FROM 'object' THEN RAISE EXCEPTION 'GIS_LDD_REPORT_INVALID'; END IF;
 FOR k,v IN SELECT key,value FROM jsonb_each(stats-'area_by_main_m2') LOOP
   IF jsonb_typeof(v) IS DISTINCT FROM 'number' OR abs((v#>>'{}')::numeric)>1e12 OR (v#>>'{}')::numeric<0 THEN RAISE EXCEPTION 'GIS_LDD_REPORT_INVALID'; END IF;
   IF k IN ('feature_count','unknown_code_count','composite_feature_count','geometry_error_count') AND v#>>'{}' !~ '^[0-9]{1,9}$' THEN RAISE EXCEPTION 'GIS_LDD_REPORT_INVALID'; END IF;
 END LOOP;
 PERFORM gis.keys(stats->'area_by_main_m2',ARRAY['U','A','F','W','M']);
 IF NOT (stats->'area_by_main_m2') ?& ARRAY['U','A','F','W','M'] THEN RAISE EXCEPTION 'GIS_LDD_REPORT_INVALID'; END IF;
 FOR k,v IN SELECT key,value FROM jsonb_each(stats->'area_by_main_m2') LOOP
   IF jsonb_typeof(v) IS DISTINCT FROM 'number' OR (v#>>'{}')::numeric<0 OR (v#>>'{}')::numeric>1e12 THEN RAISE EXCEPTION 'GIS_LDD_REPORT_INVALID'; END IF;
   known_total:=known_total+(v#>>'{}')::numeric;
 END LOOP;
 IF p_report->'valid'='true'::jsonb THEN
   total:=(stats->>'total_area_m2')::numeric;
   IF NOT p_report->'checks' @> required_checks OR jsonb_array_length(p_report->'errors')<>0
     OR p_report->'error_code' IS DISTINCT FROM 'null'::jsonb OR p_report->>'observed_sha256' IS DISTINCT FROM u.sha256
     OR p_report->>'encoding'='auto' OR (u.encoding<>'auto' AND p_report->>'encoding'<>u.encoding)
     OR (stats->>'feature_count')::integer<1 OR total<=0
     OR (stats->>'unknown_area_m2')::numeric<>0 OR (stats->>'unknown_code_count')::integer<>0
     OR (stats->>'geometry_error_count')::integer<>0
     OR abs(known_total-total)>greatest(0.05,total*0.00001) THEN RAISE EXCEPTION 'GIS_LDD_SCIENTIFIC_INVARIANT'; END IF;
 ELSE
   IF jsonb_typeof(p_report->'error_code') IS DISTINCT FROM 'string' OR p_report->>'error_code' !~ '^[A-Z0-9_]{1,60}$'
     OR jsonb_array_length(p_report->'errors')=0 THEN RAISE EXCEPTION 'GIS_LDD_REPORT_INVALID'; END IF;
 END IF;
END $f$;

CREATE FUNCTION gis.ldd_command(p_actor uuid,p_request_id uuid,p_operation text,p_payload jsonb,p_backend_sandbox boolean)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE d gis.datasets%ROWTYPE; e gis.editions%ROWTYPE; u gis.ldd_uploads%ROWTYPE; j gis.jobs%ROWTYPE;
 r gis.receipts%ROWTYPE; new_upload gis.ldd_uploads%ROWTYPE; body_value jsonb; status_value integer:=200;
 digest text; manifest_value jsonb; reason_value text; active_job gis.jobs%ROWTYPE;
BEGIN
 PERFORM gis.authorize(p_actor,false);
 IF p_request_id IS NULL THEN RAISE EXCEPTION 'GIS_REQUEST_ID_REQUIRED'; END IF;
 PERFORM gis.keys(p_payload,CASE p_operation
   WHEN 'upload' THEN ARRAY['dataset_id','expected_revision','upload_id','sha256','byte_size','crs','encoding']
   WHEN 'enqueue' THEN ARRAY['edition_id','expected_revision']
   WHEN 'retry' THEN ARRAY['job_id','expected_revision','input_hash','reason'] ELSE ARRAY[]::text[] END);
 IF p_operation NOT IN ('upload','enqueue','retry') THEN RAISE EXCEPTION 'GIS_UNKNOWN_OPERATION'; END IF;
 digest:=encode(sha256(convert_to(p_payload::text,'UTF8')),'hex');
 PERFORM pg_advisory_xact_lock(hashtextextended(p_actor::text||':'||p_request_id::text,0));
 PERFORM gis.authorize(p_actor,false);
 SELECT * INTO r FROM gis.receipts WHERE actor_id=p_actor AND request_id=p_request_id;
 IF FOUND THEN
   IF r.operation<>(CASE WHEN p_operation='upload' THEN 'ldd.upload' ELSE p_operation END) OR r.payload_hash<>digest THEN RAISE EXCEPTION 'GIS_IDEMPOTENCY_CONFLICT'; END IF;
   RETURN jsonb_build_object('status',r.status,'body',r.body);
 END IF;
 IF p_operation='upload' THEN
   SELECT * INTO d FROM gis.datasets WHERE id=(p_payload->>'dataset_id')::uuid FOR NO KEY UPDATE;
   IF NOT FOUND THEN RAISE EXCEPTION 'GIS_NOT_FOUND'; END IF;
   IF d.kind<>'ldd_shapefile' OR d.purpose<>'landuse' OR d.month<>0 THEN RAISE EXCEPTION 'GIS_LDD_DATASET_REQUIRED'; END IF;
   IF p_payload->'expected_revision' IS DISTINCT FROM to_jsonb(d.revision) THEN RAISE EXCEPTION 'GIS_REVISION_CONFLICT'; END IF;
   IF jsonb_typeof(p_payload->'sha256') IS DISTINCT FROM 'string' OR p_payload->>'sha256' !~ '^[0-9a-f]{64}$'
     OR jsonb_typeof(p_payload->'byte_size') IS DISTINCT FROM 'number' OR COALESCE(p_payload->>'byte_size','') !~ '^[0-9]{1,8}$'
     OR (p_payload->>'byte_size')::bigint NOT BETWEEN 1 AND 20971520
     OR p_payload->>'crs' IS NULL OR p_payload->>'crs' NOT IN ('EPSG:32647','EPSG:32648','EPSG:4326')
     OR p_payload->>'encoding' IS NULL OR p_payload->>'encoding' NOT IN ('auto','utf-8','cp874','tis-620')
     OR p_payload->>'upload_id' IS NULL THEN RAISE EXCEPTION 'GIS_INVALID_PAYLOAD'; END IF;
   SELECT * INTO u FROM gis.ldd_uploads WHERE dataset_id=d.id AND sha256=p_payload->>'sha256'
     AND crs=p_payload->>'crs' AND encoding=p_payload->>'encoding';
   IF FOUND THEN
     body_value:=gis.ldd_upload_row(u);
   ELSE
     new_upload.id:=(p_payload->>'upload_id')::uuid;new_upload.dataset_id:=d.id;
     new_upload.sha256:=p_payload->>'sha256';new_upload.byte_size:=(p_payload->>'byte_size')::bigint;
     new_upload.crs:=p_payload->>'crs';new_upload.encoding:=p_payload->>'encoding';
     manifest_value:=gis.ldd_manifest(new_upload);
     INSERT INTO gis.editions(dataset_id,manifest,input_hash,created_by)
       VALUES(d.id,manifest_value,gis.manifest_hash(manifest_value),p_actor) RETURNING * INTO e;
     INSERT INTO gis.ldd_uploads(id,dataset_id,edition_id,sha256,byte_size,crs,encoding,uploaded_by)
       VALUES(new_upload.id,d.id,e.id,new_upload.sha256,new_upload.byte_size,new_upload.crs,new_upload.encoding,p_actor) RETURNING * INTO u;
     body_value:=gis.ldd_upload_row(u);status_value:=201;
   END IF;
   e.id:=u.edition_id;
 ELSE
   IF p_operation='retry' THEN
     SELECT * INTO j FROM gis.jobs WHERE id=(p_payload->>'job_id')::uuid;
     IF NOT FOUND THEN RAISE EXCEPTION 'GIS_NOT_FOUND'; END IF;
     SELECT * INTO e FROM gis.editions WHERE id=j.edition_id FOR UPDATE;
     SELECT * INTO j FROM gis.jobs WHERE id=j.id FOR UPDATE;
   ELSE
     SELECT * INTO e FROM gis.editions WHERE id=(p_payload->>'edition_id')::uuid FOR UPDATE;
   END IF;
   IF e.id IS NULL THEN RAISE EXCEPTION 'GIS_NOT_FOUND'; END IF;
   SELECT * INTO u FROM gis.ldd_uploads WHERE edition_id=e.id;
   SELECT * INTO d FROM gis.datasets WHERE id=e.dataset_id;
   IF u.id IS NULL OR e.manifest IS DISTINCT FROM gis.ldd_manifest(u) OR e.input_hash<>gis.manifest_hash(e.manifest) THEN RAISE EXCEPTION 'GIS_LDD_UPLOAD_REQUIRED'; END IF;
   IF p_payload->'expected_revision' IS DISTINCT FROM to_jsonb(e.input_revision) THEN RAISE EXCEPTION 'GIS_REVISION_CONFLICT'; END IF;
   IF p_operation='retry' THEN
     reason_value:=btrim(p_payload->>'reason');
     IF reason_value IS NULL OR length(reason_value) NOT BETWEEN 1 AND 500 THEN RAISE EXCEPTION 'GIS_REASON_REQUIRED'; END IF;
     IF j.kind<>'validate_ldd_edition' OR j.parent_job_id IS NOT NULL OR j.state<>'failed'
       OR j.error_code NOT IN ('transient','attempts_exhausted') OR e.state<>'draft'
       OR j.input_revision<>e.input_revision OR j.input_hash<>e.input_hash OR p_payload->>'input_hash' IS DISTINCT FROM e.input_hash THEN
       RAISE EXCEPTION 'GIS_RETRY_INELIGIBLE'; END IF;
     IF EXISTS(SELECT 1 FROM gis.jobs WHERE parent_job_id=j.id) THEN RAISE EXCEPTION 'GIS_RETRY_ALREADY_USED'; END IF;
   ELSE
     SELECT * INTO active_job FROM gis.jobs WHERE edition_id=e.id AND input_revision=e.input_revision
       AND input_hash=e.input_hash AND validator_version='ldd-local-v1' AND parent_job_id IS NULL;
     IF FOUND THEN
       body_value:=to_jsonb(active_job)-'worker_id'-'lease_token';
       status_value:=CASE WHEN active_job.state IN ('queued','running') THEN 202 ELSE 200 END;
     END IF;
   END IF;
   IF body_value IS NULL THEN
     IF e.state<>'draft' OR EXISTS(SELECT 1 FROM gis.jobs WHERE edition_id=e.id AND state IN ('queued','running')) THEN RAISE EXCEPTION 'GIS_EDITION_NOT_DRAFT'; END IF;
     INSERT INTO gis.jobs(edition_id,parent_job_id,kind,validator_version,input_revision,input_hash,requested_by)
       VALUES(e.id,CASE WHEN p_operation='retry' THEN j.id ELSE NULL END,'validate_ldd_edition','ldd-local-v1',e.input_revision,e.input_hash,p_actor) RETURNING * INTO active_job;
     UPDATE gis.editions SET state='validating',validated_result_id=NULL WHERE id=e.id;
     body_value:=to_jsonb(active_job)-'worker_id'-'lease_token';status_value:=202;
   END IF;
   j:=active_job;
 END IF;
 PERFORM gis.authorize(p_actor,false);
 INSERT INTO gis.audit(actor_id,operation,dataset_id,edition_id,job_id,reason,detail)
   VALUES(p_actor,CASE WHEN p_operation='upload' THEN 'ldd.upload' ELSE p_operation END,d.id,e.id,j.id,reason_value,
     CASE WHEN p_operation='upload' THEN jsonb_build_object('upload_id',u.id,'sha256',u.sha256) ELSE '{}'::jsonb END);
 INSERT INTO gis.receipts(actor_id,request_id,operation,payload_hash,status,body)
   VALUES(p_actor,p_request_id,CASE WHEN p_operation='upload' THEN 'ldd.upload' ELSE p_operation END,digest,status_value,body_value);
 RETURN jsonb_build_object('status',status_value,'body',body_value);
END $f$;

CREATE FUNCTION public.gis_ldd_command(p_actor uuid,p_request_id uuid,p_operation text,p_payload jsonb,p_backend_sandbox boolean DEFAULT false)
RETURNS jsonb LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,gis
AS $f$ SELECT gis.ldd_command(p_actor,p_request_id,p_operation,p_payload,p_backend_sandbox) $f$;

CREATE FUNCTION public.gis_ldd_read(p_actor uuid,p_upload_id uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE u gis.ldd_uploads%ROWTYPE; result_value jsonb;
BEGIN
 PERFORM gis.authorize(p_actor,false);
 SELECT * INTO u FROM gis.ldd_uploads WHERE id=p_upload_id;
 IF NOT FOUND THEN RAISE EXCEPTION 'GIS_NOT_FOUND'; END IF;
 SELECT gis.ldd_upload_row(u)||jsonb_build_object('state',e.state,'input_revision',e.input_revision,'input_hash',e.input_hash)
   INTO result_value FROM gis.editions e WHERE e.id=u.edition_id;
 RETURN result_value;
END $f$;


-- Exact Phase 1 implementation retained as a private compatibility delegate.
CREATE FUNCTION gis.phase1_command(p_actor uuid,p_request_id uuid,p_operation text,p_payload jsonb,p_backend_sandbox boolean)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE d gis.datasets%ROWTYPE; e gis.editions%ROWTYPE; source_edition gis.editions%ROWTYPE;
 j gis.jobs%ROWTYPE; receipt gis.receipts%ROWTYPE; body_value jsonb; status_value integer:=200;
 payload_digest text; manifest_digest text; admin_required boolean; reason_value text;
 expected_pointer uuid; replacement uuid; subject uuid; active_job gis.jobs%ROWTYPE;
BEGIN
 admin_required:=p_operation IN ('grant_officer','revoke_officer','activate','rollback','withdraw');
 -- Actor/subject locks have a consistent order even when two admins target each other.
 IF p_operation IN ('grant_officer','revoke_officer') THEN
  subject:=(p_payload->>'user_id')::uuid;
  IF subject IS NOT NULL AND p_actor IS NOT NULL THEN
   PERFORM pg_advisory_xact_lock(hashtextextended('gis-auth:'||u::text,0))
     FROM (SELECT DISTINCT unnest(ARRAY[p_actor,subject]) u ORDER BY u) ordered_actors;
  END IF;
 END IF;
 PERFORM gis.authorize(p_actor,admin_required);
 IF p_request_id IS NULL THEN RAISE EXCEPTION 'GIS_REQUEST_ID_REQUIRED'; END IF;
 PERFORM gis.keys(p_payload,CASE p_operation
  WHEN 'create_dataset' THEN ARRAY['province','data_year','month','kind','purpose','title']
  WHEN 'edit_dataset' THEN ARRAY['dataset_id','expected_revision','title']
  WHEN 'create_edition' THEN ARRAY['dataset_id','manifest']
  WHEN 'clone_edition' THEN ARRAY['edition_id','expected_revision']
  WHEN 'edit_edition' THEN ARRAY['edition_id','expected_revision','manifest']
  WHEN 'enqueue' THEN ARRAY['edition_id','expected_revision']
  WHEN 'retry' THEN ARRAY['job_id','expected_revision','input_hash','reason']
  WHEN 'grant_officer' THEN ARRAY['user_id','reason']
  WHEN 'revoke_officer' THEN ARRAY['user_id','reason']
  WHEN 'activate' THEN ARRAY['dataset_id','edition_id','expected_revision','expected_active_edition_id','reason']
  WHEN 'rollback' THEN ARRAY['dataset_id','edition_id','expected_revision','expected_active_edition_id','reason']
  WHEN 'withdraw' THEN ARRAY['edition_id','expected_revision','expected_dataset_revision','expected_active_edition_id','replacement_edition_id','reason']
  ELSE ARRAY[]::text[] END);
 IF p_operation NOT IN ('create_dataset','edit_dataset','create_edition','clone_edition','edit_edition','enqueue','retry',
  'grant_officer','revoke_officer','activate','rollback','withdraw') THEN RAISE EXCEPTION 'GIS_UNKNOWN_OPERATION'; END IF;
 IF p_operation IN ('activate','rollback','withdraw') AND (p_backend_sandbox IS DISTINCT FROM true
     OR NOT EXISTS(SELECT 1 FROM gis.environment WHERE singleton AND activation_enabled)) THEN
  RAISE EXCEPTION 'GIS_ACTIVATION_DISABLED'; END IF;
 payload_digest:=encode(sha256(convert_to(p_payload::text,'UTF8')),'hex');
 PERFORM pg_advisory_xact_lock(hashtextextended(p_actor::text||':'||p_request_id::text,0));
 PERFORM gis.authorize(p_actor,admin_required); -- Also recheck access after a contended receipt lock.
 SELECT * INTO receipt FROM gis.receipts WHERE actor_id=p_actor AND request_id=p_request_id;
 IF FOUND THEN
  IF receipt.operation<>p_operation OR receipt.payload_hash<>payload_digest THEN RAISE EXCEPTION 'GIS_IDEMPOTENCY_CONFLICT'; END IF;
  RETURN jsonb_build_object('status',receipt.status,'body',receipt.body);
 END IF;
 IF p_operation IN ('retry','grant_officer','revoke_officer','activate','rollback','withdraw') THEN
  reason_value:=btrim(p_payload->>'reason');
  IF reason_value IS NULL OR length(reason_value) NOT BETWEEN 1 AND 500 THEN RAISE EXCEPTION 'GIS_REASON_REQUIRED'; END IF;
 END IF;

 IF p_operation='create_dataset' THEN
  IF (p_payload->>'data_year')::integer NOT BETWEEN 1980 AND extract(year FROM clock_timestamp())::integer+1 THEN
   RAISE EXCEPTION 'GIS_INVALID_YEAR'; END IF;
  INSERT INTO gis.datasets(province,data_year,month,kind,purpose,title,created_by)
   VALUES(p_payload->>'province',(p_payload->>'data_year')::integer,(p_payload->>'month')::integer,
    p_payload->>'kind',p_payload->>'purpose',btrim(p_payload->>'title'),p_actor) RETURNING * INTO d;
  body_value:=to_jsonb(d);status_value:=201;
 ELSIF p_operation='edit_dataset' THEN
  SELECT * INTO d FROM gis.datasets WHERE id=(p_payload->>'dataset_id')::uuid FOR NO KEY UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'GIS_NOT_FOUND'; END IF;
  IF d.revision IS DISTINCT FROM (p_payload->>'expected_revision')::integer THEN RAISE EXCEPTION 'GIS_REVISION_CONFLICT'; END IF;
  UPDATE gis.datasets SET title=btrim(p_payload->>'title'),revision=revision+1 WHERE id=d.id RETURNING * INTO d;
  body_value:=to_jsonb(d);
 ELSIF p_operation IN ('create_edition','clone_edition') THEN
  IF p_operation='clone_edition' THEN
   SELECT * INTO source_edition FROM gis.editions WHERE id=(p_payload->>'edition_id')::uuid;
   IF NOT FOUND THEN RAISE EXCEPTION 'GIS_NOT_FOUND'; END IF;
   -- Dataset before edition: activation/withdrawal use the same order.
   SELECT * INTO d FROM gis.datasets WHERE id=source_edition.dataset_id FOR KEY SHARE;
   SELECT * INTO source_edition FROM gis.editions WHERE id=source_edition.id FOR SHARE;
   IF source_edition.input_revision IS DISTINCT FROM (p_payload->>'expected_revision')::integer THEN RAISE EXCEPTION 'GIS_REVISION_CONFLICT'; END IF;
   manifest_digest:=gis.manifest_hash(source_edition.manifest);
  ELSE
   SELECT * INTO d FROM gis.datasets WHERE id=(p_payload->>'dataset_id')::uuid FOR KEY SHARE;
   IF NOT FOUND THEN RAISE EXCEPTION 'GIS_NOT_FOUND'; END IF;
   manifest_digest:=gis.manifest_hash(p_payload->'manifest');
  END IF;
  INSERT INTO gis.editions(dataset_id,cloned_from_id,manifest,input_hash,created_by)
   VALUES(d.id,source_edition.id,CASE WHEN p_operation='clone_edition' THEN source_edition.manifest ELSE p_payload->'manifest' END,
    manifest_digest,p_actor) RETURNING * INTO e;
  body_value:=to_jsonb(e);status_value:=201;
 ELSIF p_operation='edit_edition' THEN
  SELECT * INTO e FROM gis.editions WHERE id=(p_payload->>'edition_id')::uuid FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'GIS_NOT_FOUND'; END IF;
  IF e.state<>'draft' OR e.input_revision IS DISTINCT FROM (p_payload->>'expected_revision')::integer THEN RAISE EXCEPTION 'GIS_REVISION_CONFLICT'; END IF;
  manifest_digest:=gis.manifest_hash(p_payload->'manifest');
  UPDATE gis.editions SET manifest=p_payload->'manifest',input_hash=manifest_digest,input_revision=input_revision+1,
   validated_result_id=NULL WHERE id=e.id RETURNING * INTO e;
  body_value:=to_jsonb(e);
 ELSIF p_operation IN ('enqueue','retry') THEN
  IF p_operation='retry' THEN
   SELECT * INTO j FROM gis.jobs WHERE id=(p_payload->>'job_id')::uuid;
   IF NOT FOUND THEN RAISE EXCEPTION 'GIS_NOT_FOUND'; END IF;
   SELECT * INTO e FROM gis.editions WHERE id=j.edition_id FOR UPDATE;
   SELECT * INTO j FROM gis.jobs WHERE id=j.id FOR UPDATE;
  ELSE
   SELECT * INTO e FROM gis.editions WHERE id=(p_payload->>'edition_id')::uuid FOR UPDATE;
   IF NOT FOUND THEN RAISE EXCEPTION 'GIS_NOT_FOUND'; END IF;
  END IF;
  IF e.input_revision IS DISTINCT FROM (p_payload->>'expected_revision')::integer THEN RAISE EXCEPTION 'GIS_REVISION_CONFLICT'; END IF;
  SELECT * INTO d FROM gis.datasets WHERE id=e.dataset_id;
  IF NOT EXISTS(SELECT 1 FROM gis.synthetic_fixtures f WHERE f.manifest=e.manifest AND f.kind=d.kind AND f.purpose=d.purpose)
     OR e.input_hash<>gis.manifest_hash(e.manifest) THEN RAISE EXCEPTION 'GIS_SYNTHETIC_ONLY'; END IF;
  IF p_operation='retry' THEN
   IF j.parent_job_id IS NOT NULL OR j.state<>'failed' OR j.error_code NOT IN ('transient','attempts_exhausted')
      OR e.state<>'draft' OR j.input_revision<>e.input_revision OR j.input_hash<>e.input_hash
      OR p_payload->>'input_hash' IS DISTINCT FROM e.input_hash THEN RAISE EXCEPTION 'GIS_RETRY_INELIGIBLE'; END IF;
   SELECT * INTO active_job FROM gis.jobs WHERE parent_job_id=j.id;
   IF FOUND THEN RAISE EXCEPTION 'GIS_RETRY_ALREADY_USED'; END IF;
  ELSE
   SELECT * INTO active_job FROM gis.jobs WHERE edition_id=e.id AND input_revision=e.input_revision
    AND input_hash=e.input_hash AND validator_version='synthetic-v1'
    ORDER BY (state IN ('queued','running')) DESC,created_at DESC,id DESC LIMIT 1;
   IF FOUND THEN
    body_value:=to_jsonb(active_job)-'lease_token'-'worker_id';
    status_value:=CASE WHEN active_job.state IN ('queued','running') THEN 202 ELSE 200 END;
   END IF;
  END IF;
  IF body_value IS NULL THEN
   IF e.state<>'draft' OR EXISTS(SELECT 1 FROM gis.jobs WHERE edition_id=e.id AND state IN ('queued','running')) THEN
    RAISE EXCEPTION 'GIS_EDITION_NOT_DRAFT'; END IF;
   INSERT INTO gis.jobs(edition_id,parent_job_id,input_revision,input_hash,requested_by)
    VALUES(e.id,CASE WHEN p_operation='retry' THEN j.id ELSE NULL END,e.input_revision,e.input_hash,p_actor) RETURNING * INTO active_job;
   UPDATE gis.editions SET state='validating',validated_result_id=NULL WHERE id=e.id;
   body_value:=to_jsonb(active_job)-'lease_token'-'worker_id'; status_value:=202;
  END IF;
  j:=active_job;
 ELSIF p_operation IN ('grant_officer','revoke_officer') THEN
  subject:=(p_payload->>'user_id')::uuid;
  PERFORM pg_advisory_xact_lock(hashtextextended('gis-auth:'||COALESCE(subject::text,''),0));
  IF NOT EXISTS(SELECT 1 FROM public.profiles WHERE id=subject) THEN RAISE EXCEPTION 'GIS_NOT_FOUND'; END IF;
  IF p_operation='grant_officer' THEN
   INSERT INTO gis.officers(user_id,granted_by) VALUES(subject,p_actor) ON CONFLICT(user_id) DO NOTHING;
  ELSE DELETE FROM gis.officers WHERE user_id=subject; END IF;
  body_value:=jsonb_build_object('officer',p_operation='grant_officer');
 ELSIF p_operation IN ('activate','rollback') THEN
  SELECT * INTO d FROM gis.datasets WHERE id=(p_payload->>'dataset_id')::uuid FOR NO KEY UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'GIS_NOT_FOUND'; END IF;
  SELECT * INTO e FROM gis.editions WHERE id=(p_payload->>'edition_id')::uuid FOR UPDATE;
  IF NOT FOUND OR e.dataset_id<>d.id THEN RAISE EXCEPTION 'GIS_NOT_FOUND'; END IF;
  IF NOT p_payload ? 'expected_active_edition_id' THEN RAISE EXCEPTION 'GIS_EXPECTED_POINTER_REQUIRED'; END IF;
  expected_pointer:=(p_payload->>'expected_active_edition_id')::uuid;
  IF d.revision IS DISTINCT FROM (p_payload->>'expected_revision')::integer OR d.active_edition_id IS DISTINCT FROM expected_pointer THEN
   RAISE EXCEPTION 'GIS_REVISION_CONFLICT'; END IF;
  IF NOT gis.eligible(e.id,d.id) THEN RAISE EXCEPTION 'GIS_ACTIVATION_INELIGIBLE'; END IF;
  IF p_operation='rollback' AND NOT EXISTS(SELECT 1 FROM gis.audit WHERE dataset_id=d.id
    AND operation IN ('activate','rollback','withdraw') AND detail->>'new_edition_id'=e.id::text) THEN
   RAISE EXCEPTION 'GIS_ROLLBACK_INELIGIBLE'; END IF;
  UPDATE gis.datasets SET active_edition_id=e.id,revision=revision+1 WHERE id=d.id RETURNING * INTO d;
  body_value:=to_jsonb(d);
 ELSIF p_operation='withdraw' THEN
  SELECT * INTO e FROM gis.editions WHERE id=(p_payload->>'edition_id')::uuid;
  IF NOT FOUND THEN RAISE EXCEPTION 'GIS_NOT_FOUND'; END IF;
  SELECT * INTO d FROM gis.datasets WHERE id=e.dataset_id FOR NO KEY UPDATE;
  -- Lock both editions in UUID order to avoid opposite replacement deadlocks.
  replacement:=(p_payload->>'replacement_edition_id')::uuid;
  PERFORM id FROM gis.editions WHERE id=e.id OR id=replacement ORDER BY id FOR UPDATE;
  SELECT * INTO e FROM gis.editions WHERE id=e.id;
  IF NOT p_payload ? 'expected_active_edition_id' OR NOT p_payload ? 'replacement_edition_id' THEN RAISE EXCEPTION 'GIS_EXPECTED_POINTER_REQUIRED'; END IF;
  expected_pointer:=(p_payload->>'expected_active_edition_id')::uuid;
  IF d.revision IS DISTINCT FROM (p_payload->>'expected_dataset_revision')::integer
    OR e.input_revision IS DISTINCT FROM (p_payload->>'expected_revision')::integer
    OR d.active_edition_id IS DISTINCT FROM expected_pointer THEN RAISE EXCEPTION 'GIS_REVISION_CONFLICT'; END IF;
  IF e.state IN ('withdrawn','validating') THEN RAISE EXCEPTION 'GIS_WITHDRAWAL_INELIGIBLE'; END IF;
  IF d.active_edition_id=e.id THEN
   IF replacement=e.id OR (replacement IS NOT NULL AND NOT gis.eligible(replacement,d.id)) THEN RAISE EXCEPTION 'GIS_ACTIVATION_INELIGIBLE'; END IF;
   UPDATE gis.datasets SET active_edition_id=replacement,revision=revision+1 WHERE id=d.id RETURNING * INTO d;
  ELSIF replacement IS NOT NULL THEN RAISE EXCEPTION 'GIS_REPLACEMENT_FOR_INACTIVE_EDITION'; END IF;
  UPDATE gis.editions SET state='withdrawn' WHERE id=e.id RETURNING * INTO e;
  body_value:=jsonb_build_object('edition',to_jsonb(e),'dataset',to_jsonb(d));
 END IF;
 -- Receipts never retain actor/subject UUID copies in immutable JSON. The live
 -- relational actor columns use SET NULL and shared catalog content survives.
 body_value:=body_value-'created_by'-'requested_by'-'granted_by'-'actor_id';
 IF p_operation='withdraw' THEN
  body_value:=jsonb_build_object('edition',(body_value->'edition')-'created_by',
   'dataset',(body_value->'dataset')-'created_by');
 END IF;
 PERFORM gis.authorize(p_actor,admin_required);
 INSERT INTO gis.audit(actor_id,subject_id,operation,dataset_id,edition_id,job_id,reason,detail)
  VALUES(p_actor,subject,p_operation,d.id,e.id,j.id,reason_value,
   CASE WHEN p_operation IN ('activate','rollback','withdraw') THEN jsonb_build_object('previous_edition_id',expected_pointer,'new_edition_id',d.active_edition_id)
        ELSE '{}'::jsonb END);
 INSERT INTO gis.receipts(actor_id,request_id,operation,payload_hash,status,body)
  VALUES(p_actor,p_request_id,p_operation,payload_digest,status_value,body_value);
 RETURN jsonb_build_object('status',status_value,'body',body_value);
END $f$;

-- Exact Phase 1 implementation retained as a private compatibility delegate.
CREATE FUNCTION gis.phase1_eligible(p_edition uuid,p_dataset uuid) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
 SELECT EXISTS(SELECT 1 FROM gis.editions e JOIN gis.results r ON r.id=e.validated_result_id AND r.edition_id=e.id
  JOIN gis.jobs j ON j.id=r.job_id JOIN gis.synthetic_fixtures f ON f.manifest=e.manifest
  JOIN gis.datasets d ON d.id=e.dataset_id AND f.kind=d.kind AND f.purpose=d.purpose
  WHERE e.id=p_edition AND e.dataset_id=p_dataset AND e.state='validated'
   AND r.valid AND r.provider='synthetic' AND r.input_revision=e.input_revision AND r.input_hash=e.input_hash
   AND j.state='succeeded' AND j.edition_id=e.id AND j.input_revision=e.input_revision AND j.input_hash=e.input_hash
   AND r.validator_version=j.validator_version AND r.validator_version='synthetic-v1')
$f$;

-- Exact Phase 1 implementation retained as a private compatibility delegate.
CREATE FUNCTION gis.phase1_api_read_row(p_kind text,p_row jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE fields text[]; result_value jsonb; checks_value jsonb; fixture text; code text;
BEGIN
 fields:=CASE
  WHEN p_kind IN ('datasets','dataset') THEN ARRAY['id','province','data_year','month','kind','purpose','title','revision','active_edition_id','created_at']
  WHEN p_kind IN ('editions','edition') THEN ARRAY['id','dataset_id','cloned_from_id','state','input_revision','manifest','input_hash','validated_result_id','created_at']
  WHEN p_kind IN ('jobs','job') THEN ARRAY['id','edition_id','parent_job_id','kind','input_revision','input_hash','validator_version','state','attempt_count','available_at','progress','created_at','finished_at']
  WHEN p_kind='attempts' THEN ARRAY['id','job_id','attempt_no','state','progress','started_at','finished_at','validation_report']
  WHEN p_kind='history' THEN ARRAY['id','operation','dataset_id','edition_id','job_id','reason','created_at']
  WHEN p_kind='officers' THEN ARRAY['id','user_id','created_at']
  WHEN p_kind='result' THEN ARRAY['id','job_id','edition_id','input_revision','input_hash','validator_version','attempt_no','provider','valid','created_at']
 END;
 IF fields IS NULL THEN RAISE EXCEPTION 'GIS_UNKNOWN_READ'; END IF;
 IF p_row IS NULL THEN RETURN NULL; END IF;
 result_value:=gis.api_project(p_row,fields);
 IF p_kind IN ('jobs','job','attempts') THEN
  code:=p_row->>'error_code';
  result_value:=result_value||jsonb_build_object('error_code',CASE
   WHEN code IN ('invalid_data','transient','attempts_exhausted','lease_expired') THEN code
   WHEN code IS NULL THEN NULL ELSE 'internal_error' END);
 ELSIF p_kind='history' THEN
  result_value:=result_value||jsonb_build_object('detail',gis.api_project(p_row->'detail',
   ARRAY['result_id','attempt','terminal','error_code','state','worker_id','user_id','previous_edition_id','replacement_edition_id']));
 ELSIF p_kind='result' THEN
  fixture:=p_row->'report'->>'fixture_id';
  checks_value:=p_row->'report'->'checks';
  result_value:=result_value||jsonb_build_object('report',jsonb_build_object(
   'valid',p_row->'report'->'valid',
   'fixture_id',CASE WHEN fixture ~ '^[A-Za-z0-9_-]{1,60}$' THEN fixture ELSE NULL END,
   'checks',CASE WHEN jsonb_typeof(checks_value)='array' THEN checks_value ELSE '[]'::jsonb END));
 END IF;
 RETURN result_value;
END $f$;

CREATE FUNCTION gis.queue_protocol_kind(p_action text,p_payload jsonb,p_protocol text) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE j gis.jobs%ROWTYPE; e gis.editions%ROWTYPE; candidate record;
 worker uuid; token uuid; jid uuid; eid uuid; rid uuid; v_now timestamptz;
 progress_value integer; report_value jsonb; code text; next_state text; n integer:=0;
 p_native boolean:=p_protocol<>'v1'; u gis.ldd_uploads%ROWTYPE; ldd_dataset gis.datasets%ROWTYPE;
BEGIN
 PERFORM gis.assert_environment();
 IF p_protocol NOT IN ('v1','v2','ldd') OR p_protocol IS NULL THEN RAISE EXCEPTION 'GIS_WORKER_PROTOCOL_MISMATCH'; END IF;
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
        AND gis.edition_protocol(d.id)=p_protocol
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
     IF p_native THEN
       INSERT INTO gis.audit(operation,dataset_id,edition_id,job_id,detail)
         VALUES(CASE WHEN p_protocol='ldd' THEN 'ldd.claim' ELSE 'worker_v2.claim' END,e.dataset_id,e.id,j.id,jsonb_build_object('worker_id',worker,'attempt',j.attempt_count));
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
       AND gis.edition_protocol(d.id)=p_protocol
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
       VALUES(CASE WHEN p_protocol='ldd' THEN 'ldd.recover' WHEN p_native THEN 'worker_v2.recover' ELSE 'worker.recover' END,e.dataset_id,e.id,j.id,
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
     IF p_protocol='ldd' THEN PERFORM gis.validate_ldd_report(report_value,e,j);
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
       VALUES(j.id,e.id,j.input_revision,j.input_hash,j.validator_version,j.attempt_count,token,true,report_value,CASE WHEN p_protocol='ldd' THEN 'local_ldd' ELSE 'synthetic' END) RETURNING id INTO rid;
     UPDATE gis.editions SET state='validated',validated_result_id=rid WHERE id=e.id;
     UPDATE gis.jobs SET state='succeeded',worker_id=NULL,lease_token=NULL,lease_until=NULL,progress=100,finished_at=v_now WHERE id=j.id;
     UPDATE gis.attempts SET state='succeeded',progress=100,finished_at=v_now WHERE job_id=j.id AND attempt_no=j.attempt_count AND lease_token=token;
     INSERT INTO gis.audit(operation,dataset_id,edition_id,job_id,detail)
       VALUES(CASE WHEN p_protocol='ldd' THEN 'ldd.complete' WHEN p_native THEN 'worker_v2.complete' ELSE 'worker.complete' END,e.dataset_id,e.id,j.id,
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
     VALUES(CASE WHEN p_protocol='ldd' THEN 'ldd.fail' WHEN p_native THEN 'worker_v2.fail' ELSE 'worker.fail' END,e.dataset_id,e.id,j.id,
       jsonb_build_object('attempt',j.attempt_count,'error_code',code,'state',next_state));
   RETURN CASE WHEN p_native THEN jsonb_build_object('job_id',j.id,'state',next_state,'error_code',code)
     ELSE jsonb_build_object('job_id',j.id,'state',next_state) END;
 END IF;
 RAISE EXCEPTION 'GIS_UNKNOWN_WORKER_ACTION';
END $f$;

CREATE OR REPLACE FUNCTION gis.queue_protocol(p_action text,p_payload jsonb,p_native boolean) RETURNS jsonb
LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,gis
AS $f$ SELECT gis.queue_protocol_kind(p_action,p_payload,CASE WHEN p_native THEN 'v2' ELSE 'v1' END) $f$;

CREATE OR REPLACE FUNCTION gis.command(p_actor uuid,p_request_id uuid,p_operation text,p_payload jsonb,p_backend_sandbox boolean)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE eid uuid;
BEGIN
 IF p_operation='retry' THEN SELECT edition_id INTO eid FROM gis.jobs WHERE id=(p_payload->>'job_id')::uuid;
 ELSIF p_operation IN ('enqueue','clone_edition','edit_edition') THEN eid:=(p_payload->>'edition_id')::uuid;
 END IF;
 IF EXISTS(SELECT 1 FROM gis.ldd_uploads WHERE edition_id=eid) THEN
   IF p_operation IN ('clone_edition','edit_edition') THEN
     PERFORM gis.authorize(p_actor,false);
     RAISE EXCEPTION 'GIS_UPLOADED_EDITION_IMMUTABLE';
   END IF;
   RETURN gis.ldd_command(p_actor,p_request_id,p_operation,p_payload,p_backend_sandbox);
 END IF;
 RETURN gis.phase1_command(p_actor,p_request_id,p_operation,p_payload,p_backend_sandbox);
END $f$;

-- The public entrypoint is recreated to invalidate prior cached SQL plans.
CREATE OR REPLACE FUNCTION public.gis_command(p_actor uuid,p_request_id uuid,p_operation text,p_payload jsonb DEFAULT '{}',p_backend_sandbox boolean DEFAULT false)
RETURNS jsonb LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,gis
AS $f$ SELECT gis.command(p_actor,p_request_id,p_operation,p_payload,p_backend_sandbox) $f$;

CREATE OR REPLACE FUNCTION gis.eligible(p_edition uuid,p_dataset uuid) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
 SELECT gis.phase1_eligible(p_edition,p_dataset) OR EXISTS(
  SELECT 1 FROM gis.editions e JOIN gis.ldd_uploads u ON u.edition_id=e.id AND u.dataset_id=e.dataset_id
    JOIN gis.datasets d ON d.id=e.dataset_id
    JOIN gis.results r ON r.id=e.validated_result_id AND r.edition_id=e.id
    JOIN gis.jobs j ON j.id=r.job_id AND j.edition_id=e.id
  WHERE e.id=p_edition AND e.dataset_id=p_dataset AND e.state='validated'
    AND e.manifest=gis.ldd_manifest(u) AND e.input_hash=gis.manifest_hash(e.manifest)
    AND d.kind='ldd_shapefile' AND d.purpose='landuse' AND d.month=0
    AND r.valid AND r.provider='local_ldd' AND r.input_revision=e.input_revision AND r.input_hash=e.input_hash
    AND j.state='succeeded' AND j.kind='validate_ldd_edition' AND j.input_revision=e.input_revision AND j.input_hash=e.input_hash
    AND r.validator_version='ldd-local-v1' AND r.validator_version=j.validator_version)
$f$;

CREATE OR REPLACE FUNCTION gis.api_read_row(p_kind text,p_row jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE value jsonb; u gis.ldd_uploads%ROWTYPE;
BEGIN
 value:=gis.phase1_api_read_row(p_kind,p_row);
 IF p_kind IN ('editions','edition') THEN
   SELECT * INTO u FROM gis.ldd_uploads WHERE edition_id=(p_row->>'id')::uuid;
   IF FOUND THEN value:=value||jsonb_build_object('upload',gis.ldd_upload_row(u)); END IF;
 ELSIF p_kind='result' AND p_row->>'provider'='local_ldd' THEN
   value:=value||jsonb_build_object('report',p_row->'report');
 END IF;
 RETURN value;
END $f$;

CREATE FUNCTION gis.check_ldd_catalog() RETURNS trigger
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
 FOR j IN SELECT * FROM gis.jobs WHERE edition_id=e.id LOOP
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
     PERFORM gis.validate_ldd_report(NEW.validation_report,e,j);
   END IF;
 END IF;
 RETURN NULL;
END $f$;
DO $triggers$
DECLARE t text;
BEGIN
 FOREACH t IN ARRAY ARRAY['ldd_uploads','editions','jobs','attempts','results'] LOOP
   EXECUTE format('CREATE CONSTRAINT TRIGGER ldd_catalog_integrity AFTER INSERT OR UPDATE ON gis.%I DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION gis.check_ldd_catalog()',t);
 END LOOP;
END $triggers$;

CREATE FUNCTION public.gis_ldd_worker(p_action text,p_payload jsonb DEFAULT '{}') RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE subject uuid;
BEGIN
 subject:=gis.native_subject();
 IF p_payload ? 'worker_id' AND p_payload->>'worker_id' IS DISTINCT FROM subject::text THEN
   RAISE EXCEPTION 'GIS_WORKER_IDENTITY_MISMATCH' USING ERRCODE='42501'; END IF;
 IF p_action='recover' THEN RETURN gis.queue_protocol_kind(p_action,p_payload,'ldd'); END IF;
 RETURN gis.queue_protocol_kind(p_action,p_payload||jsonb_build_object('worker_id',subject),'ldd');
END $f$;

CREATE FUNCTION public.gis_ldd_readiness() RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE subject uuid; value jsonb;
BEGIN
 subject:=gis.native_subject();
 IF NOT EXISTS(SELECT 1 FROM gis.schema_migrations WHERE version=34) THEN RAISE EXCEPTION 'GIS_LDD_CONTRACT_NOT_READY'; END IF;
 SELECT jsonb_build_object('status','ready','contract_version','1.0.0-ldd-local','worker_role','gis_native_worker',
   'subject',subject,'runtime_instance',runtime_instance,'baseline_fingerprint',baseline_fingerprint,
   'database_name',database_name,'cluster_name',cluster_name,'mode',mode,
   'migration_versions',(SELECT jsonb_agg(version ORDER BY version) FROM gis.schema_migrations))
   INTO value FROM gis.environment WHERE singleton;
 RETURN value;
END $f$;

REVOKE ALL ON ALL FUNCTIONS IN SCHEMA gis FROM PUBLIC,anon,authenticated,service_role,gis_worker,gis_native_worker;
REVOKE ALL ON FUNCTION public.gis_ldd_command(uuid,uuid,text,jsonb,boolean),public.gis_ldd_read(uuid,uuid),
 public.gis_ldd_worker(text,jsonb),public.gis_ldd_readiness()
 FROM PUBLIC,anon,authenticated,service_role,gis_worker,gis_native_worker;
GRANT EXECUTE ON FUNCTION public.gis_ldd_command(uuid,uuid,text,jsonb,boolean),public.gis_ldd_read(uuid,uuid) TO service_role;
GRANT EXECUTE ON FUNCTION public.gis_ldd_worker(text,jsonb),public.gis_ldd_readiness() TO gis_native_worker;
-- Preserve the pre-existing Backend RPC ACL; no new browser access is granted.
REVOKE ALL ON FUNCTION public.gis_command(uuid,uuid,text,jsonb,boolean) FROM PUBLIC,anon,authenticated,gis_worker,gis_native_worker;
GRANT EXECUTE ON FUNCTION public.gis_command(uuid,uuid,text,jsonb,boolean) TO service_role;
RESET ROLE;
REVOKE CREATE ON SCHEMA public FROM gis_owner;
NOTIFY pgrst,'reload schema';
