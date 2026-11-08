-- Phase 4: private immutable Local GeoTIFF upload and native validation only.
-- No activation, publish, cloud or legacy cache writes. Runner owns transaction/ledger.
GRANT CREATE ON SCHEMA public TO gis_owner;
SET LOCAL ROLE gis_owner;
SELECT gis.assert_environment();
DO $guard$
BEGIN
 IF current_database() NOT IN ('postgres','gis_t1_upgrade') OR NOT gis.target_ok()
   OR NOT EXISTS(SELECT 1 FROM gis.environment WHERE singleton
      AND runtime_instance=current_setting('gis.runtime_instance',true)
      AND baseline_fingerprint=current_setting('gis.baseline_fingerprint',true))
   OR NOT EXISTS(SELECT 1 FROM gis.schema_migrations WHERE version=35
      AND sha256='72cab77fd9f4c3b544bbd06031a5c8d412642ba14d07f246637bb7ab4d4e3341')
   OR EXISTS(SELECT 1 FROM gis.schema_migrations WHERE version>=36) THEN
   RAISE EXCEPTION 'GIS_LOCAL_BASELINE_035_REQUIRED'; END IF;
END $guard$;

CREATE TABLE gis.geotiff_uploads(
 id uuid PRIMARY KEY,
 dataset_id uuid NOT NULL REFERENCES gis.datasets(id),edition_id uuid NOT NULL UNIQUE,
 sha256 text NOT NULL CHECK(sha256 ~ '^[0-9a-f]{64}$'),
 byte_size bigint NOT NULL CHECK(byte_size BETWEEN 1 AND 20971520),
 crs text NOT NULL CHECK(crs IN ('EPSG:32647','EPSG:32648','EPSG:4326')),
 profile text NOT NULL CHECK(profile IN ('ndvi_ready','lst_celsius_ready','lst_kelvin_ready')),
 metric text NOT NULL CHECK(metric IN ('ndvi','lst')),
 mode text NOT NULL DEFAULT 'local_test' CHECK(mode='local_test'),
 uploaded_by uuid REFERENCES public.profiles(id) ON DELETE SET NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 CHECK(metric=CASE WHEN profile='ndvi_ready' THEN 'ndvi' ELSE 'lst' END),
 FOREIGN KEY(edition_id,dataset_id) REFERENCES gis.editions(id,dataset_id),
 UNIQUE(dataset_id,sha256,crs,profile));
ALTER TABLE gis.geotiff_uploads ENABLE ROW LEVEL SECURITY;
ALTER TABLE gis.geotiff_uploads FORCE ROW LEVEL SECURITY;
CREATE POLICY owner_access ON gis.geotiff_uploads TO gis_owner USING(true) WITH CHECK(true);
REVOKE ALL ON gis.geotiff_uploads FROM PUBLIC,anon,authenticated,service_role,gis_worker,gis_native_worker;

ALTER TABLE gis.jobs DROP CONSTRAINT jobs_kind_check;
ALTER TABLE gis.jobs ADD CONSTRAINT jobs_kind_check CHECK(kind IN ('validate_synthetic_edition','validate_ldd_edition','process_offline_edition','validate_geotiff_edition'));
ALTER TABLE gis.jobs DROP CONSTRAINT jobs_validator_version_check;
ALTER TABLE gis.jobs ADD CONSTRAINT jobs_validator_version_check CHECK(validator_version IN ('synthetic-v1','ldd-local-v1','gee-offline-v1','geotiff-local-v1'));
ALTER TABLE gis.results DROP CONSTRAINT results_provider_check;
ALTER TABLE gis.results ADD CONSTRAINT results_provider_check CHECK(provider IN ('synthetic','local_ldd','offline_processing','local_geotiff'));

CREATE FUNCTION gis.geotiff_manifest(p_upload gis.geotiff_uploads) RETURNS jsonb
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
 SELECT jsonb_build_object('schema_version',4,'provider','local_geotiff','provenance','local-geotiff-upload-v1',
  'sha256',(p_upload).sha256,'byte_size',(p_upload).byte_size,'crs',(p_upload).crs,'data_kind','raster',
  'profile',(p_upload).profile,'metric',(p_upload).metric,
  'bands',jsonb_build_array(CASE WHEN (p_upload).metric='ndvi' THEN 'NDVI' ELSE 'LST' END),
  'units',CASE (p_upload).profile WHEN 'ndvi_ready' THEN 'unitless' WHEN 'lst_celsius_ready' THEN 'celsius' ELSE 'kelvin' END)
$f$;

CREATE FUNCTION gis.geotiff_upload_row(p_upload gis.geotiff_uploads) RETURNS jsonb
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
 SELECT jsonb_build_object('upload_id',(p_upload).id,'dataset_id',(p_upload).dataset_id,'edition_id',(p_upload).edition_id,
  'sha256',(p_upload).sha256,'byte_size',(p_upload).byte_size,'crs',(p_upload).crs,'profile',(p_upload).profile,
  'metric',(p_upload).metric,'mode',(p_upload).mode,'created_at',(p_upload).created_at)
$f$;

CREATE FUNCTION gis.guard_geotiff_upload() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'GIS_HARD_DELETE_FORBIDDEN'; END IF;
 IF TG_OP='UPDATE' AND NOT(pg_trigger_depth()>1 AND NEW.uploaded_by IS NULL
   AND (to_jsonb(NEW)-'uploaded_by')=(to_jsonb(OLD)-'uploaded_by')) THEN
   RAISE EXCEPTION 'GIS_UPLOAD_IMMUTABLE'; END IF;
 RETURN NEW;
END $f$;
CREATE TRIGGER immutable_geotiff_upload BEFORE UPDATE OR DELETE ON gis.geotiff_uploads
 FOR EACH ROW EXECUTE FUNCTION gis.guard_geotiff_upload();

-- Exact Phase 3 implementation retained as a private compatibility delegate.
CREATE FUNCTION gis.phase3_manifest_hash(p_manifest jsonb) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE expected jsonb;
BEGIN
 IF p_manifest->'schema_version' IS DISTINCT FROM '3'::jsonb THEN RETURN gis.phase2_manifest_hash(p_manifest); END IF;
 expected:=gis.processing_manifest(jsonb_build_object('province',p_manifest->'province','district',p_manifest->'district',
   'metric',p_manifest->'metric','data_year',p_manifest->'data_year','month',p_manifest->'month','mode',p_manifest->'mode',
   'scenario',p_manifest->'scenario','expected_revision',1));
 IF p_manifest IS DISTINCT FROM expected THEN RAISE EXCEPTION 'GIS_INVALID_PROCESSING_MANIFEST'; END IF;
 RETURN encode(sha256(convert_to(p_manifest::text,'UTF8')),'hex');
END $f$;

-- Exact Phase 3 implementation retained as a private compatibility delegate.
CREATE FUNCTION gis.phase3_command(p_actor uuid,p_request_id uuid,p_operation text,p_payload jsonb,p_backend_sandbox boolean)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE eid uuid;
BEGIN
 IF p_operation='retry' THEN SELECT edition_id INTO eid FROM gis.jobs WHERE id=(p_payload->>'job_id')::uuid;
 ELSIF p_operation IN ('enqueue','clone_edition','edit_edition','withdraw') THEN eid:=(p_payload->>'edition_id')::uuid;
 ELSIF p_operation IN ('activate','rollback') THEN eid:=(p_payload->>'edition_id')::uuid; END IF;
 IF (p_payload->'manifest'->'schema_version'='3'::jsonb) OR EXISTS(SELECT 1 FROM gis.editions WHERE id=eid AND manifest->'schema_version'='3'::jsonb) THEN
   PERFORM gis.authorize(p_actor,p_operation IN ('activate','rollback','withdraw'));
   RAISE EXCEPTION 'GIS_PROCESSING_COMMAND_REQUIRED'; END IF;
 RETURN gis.phase2_command(p_actor,p_request_id,p_operation,p_payload,p_backend_sandbox);
END $f$;

-- Exact Phase 3 implementation retained as a private compatibility delegate.
CREATE FUNCTION gis.phase3_eligible(p_edition uuid,p_dataset uuid) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
 SELECT CASE WHEN EXISTS(SELECT 1 FROM gis.editions WHERE id=p_edition AND manifest->'schema_version'='3'::jsonb)
   THEN false ELSE gis.phase2_eligible(p_edition,p_dataset) END
$f$;

-- Exact Phase 3 implementation retained as a private compatibility delegate.
CREATE FUNCTION gis.phase3_api_read_row(p_kind text,p_row jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE value jsonb;
BEGIN
 value:=gis.phase2_api_read_row(p_kind,p_row);
 IF p_kind='result' AND p_row->>'provider'='offline_processing' THEN
   value:=value||jsonb_build_object('mode','offline_synthetic','candidate_status','pending_review','report',p_row->'report');
 END IF;
 RETURN value;
END $f$;

CREATE OR REPLACE FUNCTION gis.manifest_hash(p_manifest jsonb) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE u gis.geotiff_uploads%ROWTYPE;
BEGIN
 IF p_manifest->'schema_version' IS DISTINCT FROM '4'::jsonb THEN RETURN gis.phase3_manifest_hash(p_manifest); END IF;
 PERFORM gis.keys(p_manifest,ARRAY['schema_version','provider','provenance','data_kind','sha256','byte_size','crs','profile','metric','bands','units']);
 IF NOT p_manifest ?& ARRAY['schema_version','provider','provenance','data_kind','sha256','byte_size','crs','profile','metric','bands','units']
   OR p_manifest->>'provider' IS DISTINCT FROM 'local_geotiff' OR p_manifest->>'provenance' IS DISTINCT FROM 'local-geotiff-upload-v1'
   OR p_manifest->>'data_kind' IS DISTINCT FROM 'raster'
   OR jsonb_typeof(p_manifest->'sha256') IS DISTINCT FROM 'string' OR p_manifest->>'sha256' !~ '^[0-9a-f]{64}$'
   OR jsonb_typeof(p_manifest->'byte_size') IS DISTINCT FROM 'number' OR COALESCE(p_manifest->>'byte_size','') !~ '^[1-9][0-9]{0,7}$'
   OR (p_manifest->>'byte_size')::bigint>20971520
   OR COALESCE(p_manifest->>'crs','') NOT IN ('EPSG:32647','EPSG:32648','EPSG:4326')
   OR COALESCE(p_manifest->>'profile','') NOT IN ('ndvi_ready','lst_celsius_ready','lst_kelvin_ready') THEN
   RAISE EXCEPTION 'GIS_INVALID_GEOTIFF_MANIFEST'; END IF;
 u.sha256:=p_manifest->>'sha256';u.byte_size:=(p_manifest->>'byte_size')::bigint;u.crs:=p_manifest->>'crs';u.profile:=p_manifest->>'profile';
 u.metric:=CASE WHEN u.profile='ndvi_ready' THEN 'ndvi' ELSE 'lst' END;
 IF p_manifest IS DISTINCT FROM gis.geotiff_manifest(u) THEN RAISE EXCEPTION 'GIS_INVALID_GEOTIFF_MANIFEST'; END IF;
 RETURN encode(sha256(convert_to(p_manifest::text,'UTF8')),'hex');
END $f$;

CREATE FUNCTION gis.validate_geotiff_report(p_report jsonb,p_edition gis.editions,p_job gis.jobs) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE u gis.geotiff_uploads%ROWTYPE; d gis.datasets%ROWTYPE; stats jsonb; meta jsonb; item jsonb; k text; v jsonb;
 required_checks jsonb:='["source_hash_match","tiff_structure","crs","bands","resolution","dimensions","dtype","nodata","scale_offset","units","scientific_range","metadata_consistency"]';
 low_value numeric; high_value numeric; output_low numeric; output_high numeric; input_units text;
BEGIN
 SELECT * INTO u FROM gis.geotiff_uploads WHERE edition_id=p_edition.id;
 SELECT * INTO d FROM gis.datasets WHERE id=p_edition.dataset_id;
 IF u.id IS NULL OR d.kind<>'geotiff' OR d.purpose<>u.metric OR u.dataset_id<>d.id
   OR p_edition.manifest IS DISTINCT FROM gis.geotiff_manifest(u) OR p_edition.input_hash IS DISTINCT FROM gis.manifest_hash(p_edition.manifest)
   OR p_job.kind<>'validate_geotiff_edition' OR p_job.validator_version<>'geotiff-local-v1'
   OR p_job.edition_id<>p_edition.id OR p_job.input_revision<>p_edition.input_revision OR p_job.input_hash<>p_edition.input_hash THEN
   RAISE EXCEPTION 'GIS_GEOTIFF_INPUT_INVARIANT'; END IF;
 PERFORM gis.keys(p_report,ARRAY['schema_version','provider_build','upload_id','artifact_sha256','observed_sha256','byte_size','input_hash','input_revision',
  'province','data_year','valid','checks','errors','warnings','statistics','metadata','error_code']);
 IF NOT p_report ?& ARRAY['schema_version','provider_build','upload_id','artifact_sha256','observed_sha256','byte_size','input_hash','input_revision',
  'province','data_year','valid','checks','errors','warnings','statistics','metadata','error_code']
   OR octet_length(p_report::text)>16384 OR p_report->'schema_version' IS DISTINCT FROM '1'::jsonb
   OR p_report->>'provider_build' IS DISTINCT FROM 'geotiff-local-v1' OR p_report->>'upload_id' IS DISTINCT FROM u.id::text
   OR p_report->>'artifact_sha256' IS DISTINCT FROM u.sha256 OR p_report->'byte_size' IS DISTINCT FROM to_jsonb(u.byte_size)
   OR p_report->>'input_hash' IS DISTINCT FROM p_job.input_hash OR p_report->'input_revision' IS DISTINCT FROM to_jsonb(p_job.input_revision)
   OR p_report->>'province' IS DISTINCT FROM d.province OR p_report->'data_year' IS DISTINCT FROM to_jsonb(d.data_year)
   OR jsonb_typeof(p_report->'valid') IS DISTINCT FROM 'boolean'
   OR jsonb_typeof(p_report->'checks') IS DISTINCT FROM 'array' OR jsonb_typeof(p_report->'errors') IS DISTINCT FROM 'array'
   OR jsonb_typeof(p_report->'warnings') IS DISTINCT FROM 'array' THEN RAISE EXCEPTION 'GIS_GEOTIFF_REPORT_INVALID'; END IF;
 IF p_report->'observed_sha256'<>'null'::jsonb AND (jsonb_typeof(p_report->'observed_sha256') IS DISTINCT FROM 'string'
   OR p_report->>'observed_sha256' !~ '^[0-9a-f]{64}$') THEN RAISE EXCEPTION 'GIS_GEOTIFF_REPORT_INVALID'; END IF;
 IF jsonb_array_length(p_report->'checks')>12 OR jsonb_array_length(p_report->'errors')>20 OR jsonb_array_length(p_report->'warnings')>20
   OR EXISTS(SELECT 1 FROM jsonb_array_elements(p_report->'checks') x WHERE jsonb_typeof(x)<>'string' OR NOT required_checks @> jsonb_build_array(x))
   OR (SELECT count(*) FROM jsonb_array_elements(p_report->'checks'))<>(SELECT count(DISTINCT x) FROM jsonb_array_elements(p_report->'checks') x) THEN
   RAISE EXCEPTION 'GIS_GEOTIFF_REPORT_INVALID'; END IF;
 FOR item IN SELECT x FROM jsonb_array_elements((p_report->'errors')||(p_report->'warnings')) x LOOP
   PERFORM gis.keys(item,ARRAY['code','count']);
   IF NOT item ?& ARRAY['code','count'] OR jsonb_typeof(item->'code') IS DISTINCT FROM 'string' OR item->>'code' !~ '^[A-Z][A-Z0-9_]{0,59}$'
     OR jsonb_typeof(item->'count') IS DISTINCT FROM 'number' OR COALESCE(item->>'count','') !~ '^[0-9]{1,8}$' THEN RAISE EXCEPTION 'GIS_GEOTIFF_REPORT_INVALID'; END IF;
 END LOOP;
 stats:=p_report->'statistics';meta:=p_report->'metadata';
 PERFORM gis.keys(stats,ARRAY['width','height','band_count','total_pixels','valid_pixels','nodata_pixels','nonfinite_pixels','mean','min','max']);
 IF NOT stats ?& ARRAY['width','height','band_count','total_pixels','valid_pixels','nodata_pixels','nonfinite_pixels','mean','min','max'] THEN RAISE EXCEPTION 'GIS_GEOTIFF_REPORT_INVALID'; END IF;
 FOR k,v IN SELECT key,value FROM jsonb_each(stats) LOOP
   IF k IN ('mean','min','max') THEN
     IF v<>'null'::jsonb AND (jsonb_typeof(v) IS DISTINCT FROM 'number' OR abs((v#>>'{}')::numeric)>1e30) THEN RAISE EXCEPTION 'GIS_GEOTIFF_REPORT_INVALID'; END IF;
   ELSIF jsonb_typeof(v) IS DISTINCT FROM 'number' OR COALESCE(v#>>'{}','') !~ '^[0-9]{1,9}$' OR (v#>>'{}')::numeric>100000000 THEN RAISE EXCEPTION 'GIS_GEOTIFF_REPORT_INVALID'; END IF;
 END LOOP;
 PERFORM gis.keys(meta,ARRAY['crs','bands','resolution','dtype','nodata','units','scales','offsets','profile','output_units']);
 IF NOT meta ?& ARRAY['crs','bands','resolution','dtype','nodata','units','scales','offsets','profile','output_units'] THEN RAISE EXCEPTION 'GIS_GEOTIFF_REPORT_INVALID'; END IF;
 FOR k,v IN SELECT key,value FROM jsonb_each(meta) LOOP
   IF k IN ('crs','dtype','units','profile','output_units') THEN
     IF v<>'null'::jsonb AND (jsonb_typeof(v) IS DISTINCT FROM 'string' OR length(v#>>'{}')>120) THEN RAISE EXCEPTION 'GIS_GEOTIFF_REPORT_INVALID'; END IF;
   ELSIF k='nodata' THEN
     IF v<>'null'::jsonb AND (jsonb_typeof(v) IS DISTINCT FROM 'number' OR abs((v#>>'{}')::numeric)>1e30) THEN RAISE EXCEPTION 'GIS_GEOTIFF_REPORT_INVALID'; END IF;
   ELSIF v<>'null'::jsonb THEN
     IF jsonb_typeof(v) IS DISTINCT FROM 'array' OR jsonb_array_length(v)>8 THEN RAISE EXCEPTION 'GIS_GEOTIFF_REPORT_INVALID'; END IF;
     FOR item IN SELECT value FROM jsonb_array_elements(v) LOOP
       IF k='bands' THEN
         IF jsonb_typeof(item) IS DISTINCT FROM 'string' OR length(item#>>'{}')>120 THEN RAISE EXCEPTION 'GIS_GEOTIFF_REPORT_INVALID'; END IF;
       ELSIF jsonb_typeof(item) IS DISTINCT FROM 'number' OR abs((item#>>'{}')::numeric)>1e30 THEN RAISE EXCEPTION 'GIS_GEOTIFF_REPORT_INVALID'; END IF;
     END LOOP;
   END IF;
 END LOOP;
 IF p_report->'valid'='true'::jsonb THEN
   input_units:=CASE u.profile WHEN 'ndvi_ready' THEN 'unitless' WHEN 'lst_celsius_ready' THEN 'celsius' ELSE 'kelvin' END;
   low_value:=CASE u.profile WHEN 'ndvi_ready' THEN -1 WHEN 'lst_celsius_ready' THEN -100 ELSE 173.15 END;
   high_value:=CASE u.profile WHEN 'ndvi_ready' THEN 1 WHEN 'lst_celsius_ready' THEN 100 ELSE 373.15 END;
   output_low:=CASE u.metric WHEN 'ndvi' THEN -1 ELSE -100 END;output_high:=CASE u.metric WHEN 'ndvi' THEN 1 ELSE 100 END;
   IF NOT p_report->'checks' @> required_checks OR jsonb_array_length(p_report->'errors')<>0
     OR p_report->'error_code' IS DISTINCT FROM 'null'::jsonb OR p_report->>'observed_sha256' IS DISTINCT FROM u.sha256
     OR (stats->>'width')::integer NOT BETWEEN 1 AND 16384 OR (stats->>'height')::integer NOT BETWEEN 1 AND 16384
     OR (stats->>'band_count')::integer<>1 OR (stats->>'total_pixels')::bigint<>(stats->>'width')::bigint*(stats->>'height')::bigint
     OR (stats->>'total_pixels')::integer>16000000 OR (stats->>'valid_pixels')::integer<1
     OR (stats->>'nonfinite_pixels')::integer<>0 OR (stats->>'valid_pixels')::integer+(stats->>'nodata_pixels')::integer<>(stats->>'total_pixels')::integer
     OR meta->>'crs' IS DISTINCT FROM u.crs OR meta->'bands' IS DISTINCT FROM p_edition.manifest->'bands'
     OR COALESCE(meta->>'dtype','') NOT IN ('float32','float64') OR meta->>'profile' IS DISTINCT FROM u.profile
     OR meta->>'units' IS DISTINCT FROM input_units OR meta->>'output_units' IS DISTINCT FROM (CASE WHEN u.metric='ndvi' THEN 'unitless' ELSE 'celsius' END)
     OR meta->'scales' IS DISTINCT FROM '[1]'::jsonb OR meta->'offsets' IS DISTINCT FROM '[0]'::jsonb
     OR jsonb_typeof(meta->'nodata') IS DISTINCT FROM 'number'
     OR (meta->>'nodata')::numeric BETWEEN low_value AND high_value
     OR jsonb_typeof(meta->'resolution') IS DISTINCT FROM 'array' OR jsonb_array_length(meta->'resolution')<>2 THEN RAISE EXCEPTION 'GIS_GEOTIFF_SCIENTIFIC_INVARIANT'; END IF;
   FOR item IN SELECT value FROM jsonb_array_elements(meta->'resolution') LOOP
     IF (item#>>'{}')::numeric NOT BETWEEN (CASE WHEN u.crs='EPSG:4326' THEN 0.000001 ELSE 0.01 END)
       AND (CASE WHEN u.crs='EPSG:4326' THEN 1 ELSE 1000 END) THEN RAISE EXCEPTION 'GIS_GEOTIFF_SCIENTIFIC_INVARIANT'; END IF;
   END LOOP;
   FOR k,v IN SELECT key,value FROM jsonb_each(stats) WHERE key IN ('mean','min','max') LOOP
     IF jsonb_typeof(v) IS DISTINCT FROM 'number' OR (v#>>'{}')::numeric NOT BETWEEN output_low AND output_high THEN RAISE EXCEPTION 'GIS_GEOTIFF_SCIENTIFIC_INVARIANT'; END IF;
   END LOOP;
   IF (stats->>'min')::numeric>(stats->>'mean')::numeric OR (stats->>'mean')::numeric>(stats->>'max')::numeric THEN RAISE EXCEPTION 'GIS_GEOTIFF_SCIENTIFIC_INVARIANT'; END IF;
 ELSE
   IF jsonb_typeof(p_report->'error_code') IS DISTINCT FROM 'string' OR p_report->>'error_code' !~ '^[A-Z][A-Z0-9_]{0,59}$'
     OR jsonb_array_length(p_report->'errors')=0 THEN RAISE EXCEPTION 'GIS_GEOTIFF_REPORT_INVALID'; END IF;
 END IF;
END $f$;

CREATE FUNCTION gis.geotiff_command(p_actor uuid,p_request_id uuid,p_operation text,p_payload jsonb,p_backend_sandbox boolean)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE d gis.datasets%ROWTYPE; e gis.editions%ROWTYPE; u gis.geotiff_uploads%ROWTYPE; j gis.jobs%ROWTYPE;
 r gis.receipts%ROWTYPE; new_upload gis.geotiff_uploads%ROWTYPE; body_value jsonb; status_value integer:=200;
 digest text; manifest_value jsonb; reason_value text; active_job gis.jobs%ROWTYPE;
BEGIN
 PERFORM gis.authorize(p_actor,false);
 IF p_request_id IS NULL THEN RAISE EXCEPTION 'GIS_REQUEST_ID_REQUIRED'; END IF;
 IF p_operation='preflight' THEN
   PERFORM gis.keys(p_payload,ARRAY['dataset_id','expected_revision','profile','crs']);
   SELECT * INTO d FROM gis.datasets WHERE id=(p_payload->>'dataset_id')::uuid;
   IF NOT FOUND THEN RAISE EXCEPTION 'GIS_NOT_FOUND'; END IF;
   IF COALESCE(p_payload->>'profile','') NOT IN ('ndvi_ready','lst_celsius_ready','lst_kelvin_ready')
     OR COALESCE(p_payload->>'crs','') NOT IN ('EPSG:32647','EPSG:32648','EPSG:4326') THEN RAISE EXCEPTION 'GIS_INVALID_PAYLOAD'; END IF;
   IF d.kind<>'geotiff' OR d.purpose IS DISTINCT FROM (CASE WHEN p_payload->>'profile'='ndvi_ready' THEN 'ndvi' ELSE 'lst' END) THEN RAISE EXCEPTION 'GIS_GEOTIFF_DATASET_REQUIRED'; END IF;
   IF p_payload->'expected_revision' IS DISTINCT FROM to_jsonb(d.revision) THEN RAISE EXCEPTION 'GIS_REVISION_CONFLICT'; END IF;
   RETURN jsonb_build_object('status',200,'body',jsonb_build_object('dataset_id',d.id,'revision',d.revision,'profile',p_payload->>'profile','crs',p_payload->>'crs','metric',d.purpose));
 END IF;
 PERFORM gis.keys(p_payload,CASE p_operation
   WHEN 'upload' THEN ARRAY['dataset_id','expected_revision','upload_id','sha256','byte_size','crs','profile']
   WHEN 'enqueue' THEN ARRAY['edition_id','expected_revision']
   WHEN 'retry' THEN ARRAY['job_id','expected_revision','input_hash','reason'] ELSE ARRAY[]::text[] END);
 IF p_operation NOT IN ('upload','enqueue','retry') THEN RAISE EXCEPTION 'GIS_UNKNOWN_OPERATION'; END IF;
 digest:=encode(sha256(convert_to(p_payload::text,'UTF8')),'hex');
 PERFORM pg_advisory_xact_lock(hashtextextended(p_actor::text||':'||p_request_id::text,0));
 PERFORM gis.authorize(p_actor,false);
 SELECT * INTO r FROM gis.receipts WHERE actor_id=p_actor AND request_id=p_request_id;
 IF FOUND THEN
   IF r.operation<>('geotiff.'||p_operation) OR r.payload_hash<>digest THEN RAISE EXCEPTION 'GIS_IDEMPOTENCY_CONFLICT'; END IF;
   RETURN jsonb_build_object('status',r.status,'body',r.body);
 END IF;
 IF p_operation='upload' THEN
   SELECT * INTO d FROM gis.datasets WHERE id=(p_payload->>'dataset_id')::uuid FOR NO KEY UPDATE;
   IF NOT FOUND THEN RAISE EXCEPTION 'GIS_NOT_FOUND'; END IF;
   IF d.kind<>'geotiff' OR d.purpose IS DISTINCT FROM (CASE WHEN p_payload->>'profile'='ndvi_ready' THEN 'ndvi' ELSE 'lst' END) THEN RAISE EXCEPTION 'GIS_GEOTIFF_DATASET_REQUIRED'; END IF;
   IF p_payload->'expected_revision' IS DISTINCT FROM to_jsonb(d.revision) THEN RAISE EXCEPTION 'GIS_REVISION_CONFLICT'; END IF;
   IF jsonb_typeof(p_payload->'sha256') IS DISTINCT FROM 'string' OR p_payload->>'sha256' !~ '^[0-9a-f]{64}$'
     OR jsonb_typeof(p_payload->'byte_size') IS DISTINCT FROM 'number' OR COALESCE(p_payload->>'byte_size','') !~ '^[0-9]{1,8}$'
     OR (p_payload->>'byte_size')::bigint NOT BETWEEN 1 AND 20971520
     OR p_payload->>'crs' IS NULL OR p_payload->>'crs' NOT IN ('EPSG:32647','EPSG:32648','EPSG:4326')
     OR COALESCE(p_payload->>'profile','') NOT IN ('ndvi_ready','lst_celsius_ready','lst_kelvin_ready')
     OR p_payload->>'upload_id' IS NULL THEN RAISE EXCEPTION 'GIS_INVALID_PAYLOAD'; END IF;
   SELECT * INTO u FROM gis.geotiff_uploads WHERE dataset_id=d.id AND sha256=p_payload->>'sha256'
     AND crs=p_payload->>'crs' AND profile=p_payload->>'profile';
   IF FOUND THEN
     body_value:=gis.geotiff_upload_row(u);
   ELSE
     new_upload.id:=(p_payload->>'upload_id')::uuid;new_upload.dataset_id:=d.id;
     new_upload.sha256:=p_payload->>'sha256';new_upload.byte_size:=(p_payload->>'byte_size')::bigint;
     new_upload.crs:=p_payload->>'crs';new_upload.profile:=p_payload->>'profile';new_upload.metric:=CASE WHEN new_upload.profile='ndvi_ready' THEN 'ndvi' ELSE 'lst' END;
     manifest_value:=gis.geotiff_manifest(new_upload);
     INSERT INTO gis.editions(dataset_id,manifest,input_hash,created_by)
       VALUES(d.id,manifest_value,gis.manifest_hash(manifest_value),p_actor) RETURNING * INTO e;
     INSERT INTO gis.geotiff_uploads(id,dataset_id,edition_id,sha256,byte_size,crs,profile,metric,uploaded_by)
       VALUES(new_upload.id,d.id,e.id,new_upload.sha256,new_upload.byte_size,new_upload.crs,new_upload.profile,new_upload.metric,p_actor) RETURNING * INTO u;
     body_value:=gis.geotiff_upload_row(u);status_value:=201;
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
   SELECT * INTO u FROM gis.geotiff_uploads WHERE edition_id=e.id;
   SELECT * INTO d FROM gis.datasets WHERE id=e.dataset_id;
   IF u.id IS NULL OR e.manifest IS DISTINCT FROM gis.geotiff_manifest(u) OR e.input_hash<>gis.manifest_hash(e.manifest) THEN RAISE EXCEPTION 'GIS_GEOTIFF_UPLOAD_REQUIRED'; END IF;
   IF p_payload->'expected_revision' IS DISTINCT FROM to_jsonb(e.input_revision) THEN RAISE EXCEPTION 'GIS_REVISION_CONFLICT'; END IF;
   IF p_operation='retry' THEN
     reason_value:=btrim(p_payload->>'reason');
     IF reason_value IS NULL OR length(reason_value) NOT BETWEEN 1 AND 500 THEN RAISE EXCEPTION 'GIS_REASON_REQUIRED'; END IF;
     IF j.kind<>'validate_geotiff_edition' OR j.parent_job_id IS NOT NULL OR j.state<>'failed'
       OR j.error_code NOT IN ('transient','attempts_exhausted') OR e.state<>'draft'
       OR j.input_revision<>e.input_revision OR j.input_hash<>e.input_hash OR p_payload->>'input_hash' IS DISTINCT FROM e.input_hash THEN
       RAISE EXCEPTION 'GIS_RETRY_INELIGIBLE'; END IF;
     IF EXISTS(SELECT 1 FROM gis.jobs WHERE parent_job_id=j.id) THEN RAISE EXCEPTION 'GIS_RETRY_ALREADY_USED'; END IF;
   ELSE
     SELECT * INTO active_job FROM gis.jobs WHERE edition_id=e.id AND input_revision=e.input_revision
       AND input_hash=e.input_hash AND validator_version='geotiff-local-v1' AND parent_job_id IS NULL;
     IF FOUND THEN
       body_value:=to_jsonb(active_job)-'worker_id'-'lease_token';
       status_value:=CASE WHEN active_job.state IN ('queued','running') THEN 202 ELSE 200 END;
     END IF;
   END IF;
   IF body_value IS NULL THEN
     IF e.state<>'draft' OR EXISTS(SELECT 1 FROM gis.jobs WHERE edition_id=e.id AND state IN ('queued','running')) THEN RAISE EXCEPTION 'GIS_EDITION_NOT_DRAFT'; END IF;
     INSERT INTO gis.jobs(edition_id,parent_job_id,kind,validator_version,input_revision,input_hash,requested_by)
       VALUES(e.id,CASE WHEN p_operation='retry' THEN j.id ELSE NULL END,'validate_geotiff_edition','geotiff-local-v1',e.input_revision,e.input_hash,p_actor) RETURNING * INTO active_job;
     UPDATE gis.editions SET state='validating',validated_result_id=NULL WHERE id=e.id;
     body_value:=to_jsonb(active_job)-'worker_id'-'lease_token';status_value:=202;
   END IF;
   j:=active_job;
 END IF;
 PERFORM gis.authorize(p_actor,false);
 INSERT INTO gis.audit(actor_id,operation,dataset_id,edition_id,job_id,reason,detail)
   VALUES(p_actor,'geotiff.'||p_operation,d.id,e.id,j.id,reason_value,
     CASE WHEN p_operation='upload' THEN jsonb_build_object('upload_id',u.id,'sha256',u.sha256) ELSE '{}'::jsonb END);
 INSERT INTO gis.receipts(actor_id,request_id,operation,payload_hash,status,body)
   VALUES(p_actor,p_request_id,'geotiff.'||p_operation,digest,status_value,body_value);
 RETURN jsonb_build_object('status',status_value,'body',body_value);
END $f$;

CREATE FUNCTION public.gis_geotiff_command(p_actor uuid,p_request_id uuid,p_operation text,p_payload jsonb,p_backend_sandbox boolean DEFAULT false)
RETURNS jsonb LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,gis
AS $f$ SELECT gis.geotiff_command(p_actor,p_request_id,p_operation,p_payload,p_backend_sandbox) $f$;

CREATE FUNCTION public.gis_geotiff_read(p_actor uuid,p_upload_id uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE u gis.geotiff_uploads%ROWTYPE; result_value jsonb;
BEGIN
 PERFORM gis.authorize(p_actor,false);
 SELECT * INTO u FROM gis.geotiff_uploads WHERE id=p_upload_id;
 IF NOT FOUND THEN RAISE EXCEPTION 'GIS_NOT_FOUND'; END IF;
 SELECT gis.geotiff_upload_row(u)||jsonb_build_object('state',e.state,'input_revision',e.input_revision,'input_hash',e.input_hash)
   INTO result_value FROM gis.editions e WHERE e.id=u.edition_id;
 RETURN result_value;
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

CREATE OR REPLACE FUNCTION gis.edition_protocol(p_edition uuid) RETURNS text
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
 SELECT CASE WHEN EXISTS(SELECT 1 FROM gis.geotiff_uploads u WHERE u.edition_id=e.id) AND e.manifest->'schema_version'='4'::jsonb THEN 'geotiff'
   WHEN e.manifest->'schema_version'='4'::jsonb THEN 'unsupported'
   WHEN EXISTS(SELECT 1 FROM gis.processing_requests q WHERE q.edition_id=e.id) AND e.manifest->'schema_version'='3'::jsonb
       AND e.manifest->>'provider'='offline_synthetic' THEN 'gee_offline'
   WHEN e.manifest->'schema_version'='3'::jsonb THEN 'unsupported'
   WHEN EXISTS(SELECT 1 FROM gis.ldd_uploads u WHERE u.edition_id=e.id) THEN 'ldd'
   WHEN e.manifest->>'provider'='synthetic' AND e.manifest->'schema_version'='2'::jsonb THEN 'v2'
   WHEN e.manifest->>'provider'='synthetic' AND e.manifest->'schema_version'='1'::jsonb THEN 'v1'
   ELSE 'unsupported' END FROM gis.editions e WHERE e.id=p_edition
$f$;

CREATE OR REPLACE FUNCTION gis.command(p_actor uuid,p_request_id uuid,p_operation text,p_payload jsonb,p_backend_sandbox boolean)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE eid uuid;
BEGIN
 IF p_operation='retry' THEN SELECT edition_id INTO eid FROM gis.jobs WHERE id=(p_payload->>'job_id')::uuid;
 ELSIF p_operation IN ('enqueue','clone_edition','edit_edition','withdraw','activate','rollback') THEN eid:=(p_payload->>'edition_id')::uuid; END IF;
 IF EXISTS(SELECT 1 FROM gis.geotiff_uploads WHERE edition_id=eid) AND p_operation IN ('enqueue','retry') THEN
   RETURN gis.geotiff_command(p_actor,p_request_id,p_operation,p_payload,p_backend_sandbox);
 END IF;
 IF p_payload->'manifest'->'schema_version'='4'::jsonb OR EXISTS(SELECT 1 FROM gis.editions WHERE id=eid AND manifest->'schema_version'='4'::jsonb) THEN
   PERFORM gis.authorize(p_actor,p_operation IN ('activate','rollback','withdraw'));
   RAISE EXCEPTION 'GIS_GEOTIFF_IMMUTABLE_VALIDATION_ONLY'; END IF;
 RETURN gis.phase3_command(p_actor,p_request_id,p_operation,p_payload,p_backend_sandbox);
END $f$;

CREATE OR REPLACE FUNCTION gis.eligible(p_edition uuid,p_dataset uuid) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
 SELECT CASE WHEN EXISTS(SELECT 1 FROM gis.editions WHERE id=p_edition AND manifest->'schema_version'='4'::jsonb)
   THEN false ELSE gis.phase3_eligible(p_edition,p_dataset) END
$f$;

CREATE OR REPLACE FUNCTION gis.api_read_row(p_kind text,p_row jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE value jsonb; u gis.geotiff_uploads%ROWTYPE;
BEGIN
 value:=gis.phase3_api_read_row(p_kind,p_row);
 IF p_kind IN ('editions','edition') THEN
   SELECT * INTO u FROM gis.geotiff_uploads WHERE edition_id=(p_row->>'id')::uuid;
   IF FOUND THEN value:=value||jsonb_build_object('upload',gis.geotiff_upload_row(u),'validation_only',true); END IF;
 ELSIF p_kind='result' AND p_row->>'provider'='local_geotiff' THEN
   value:=value||jsonb_build_object('mode','local_test','validation_only',true,'report',p_row->'report');
 END IF;
 RETURN value;
END $f$;

CREATE FUNCTION gis.check_geotiff_catalog() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE eid uuid; jid uuid; e gis.editions%ROWTYPE; d gis.datasets%ROWTYPE; u gis.geotiff_uploads%ROWTYPE;
 j gis.jobs%ROWTYPE; a gis.attempts%ROWTYPE; r gis.results%ROWTYPE;
BEGIN
 IF TG_TABLE_NAME IN ('editions','geotiff_uploads') THEN
   IF TG_TABLE_NAME='editions' THEN eid:=NEW.id; ELSE eid:=NEW.edition_id; END IF;
 ELSE
   IF TG_TABLE_NAME='jobs' THEN jid:=NEW.id; ELSE jid:=NEW.job_id; END IF;
   SELECT edition_id INTO eid FROM gis.jobs WHERE id=jid;
 END IF;
 SELECT * INTO e FROM gis.editions WHERE id=eid;
 SELECT * INTO u FROM gis.geotiff_uploads WHERE edition_id=eid;
 IF u.id IS NULL THEN
   IF e.manifest->'schema_version'='4'::jsonb OR (jid IS NOT NULL AND EXISTS(SELECT 1 FROM gis.jobs WHERE id=jid AND kind='validate_geotiff_edition')) THEN
     RAISE EXCEPTION 'GIS_GEOTIFF_ASSOCIATION_REQUIRED'; END IF;
   RETURN NULL;
 END IF;
 SELECT * INTO d FROM gis.datasets WHERE id=e.dataset_id;
 IF e.dataset_id IS DISTINCT FROM u.dataset_id OR e.manifest IS DISTINCT FROM gis.geotiff_manifest(u)
   OR e.input_hash IS DISTINCT FROM gis.manifest_hash(e.manifest) OR e.input_revision<>1
   OR d.kind IS DISTINCT FROM 'geotiff' OR d.purpose IS DISTINCT FROM u.metric
   OR e.validated_result_id IS NOT NULL OR e.state NOT IN ('draft','validating') OR d.active_edition_id=e.id THEN
   RAISE EXCEPTION 'GIS_GEOTIFF_INPUT_INVARIANT'; END IF;
 FOR j IN SELECT * FROM gis.jobs WHERE edition_id=e.id LOOP
   IF j.kind<>'validate_geotiff_edition' OR j.validator_version<>'geotiff-local-v1' THEN RAISE EXCEPTION 'GIS_WORKER_PROTOCOL_MISMATCH'; END IF;
   IF j.state='succeeded' THEN
     SELECT * INTO a FROM gis.attempts WHERE job_id=j.id AND attempt_no=j.attempt_count;
     SELECT * INTO r FROM gis.results WHERE job_id=j.id;
     PERFORM gis.validate_geotiff_report(a.validation_report,e,j);
     IF a.state IS DISTINCT FROM 'succeeded' OR r.report IS DISTINCT FROM a.validation_report
       OR a.validation_report->'valid' IS DISTINCT FROM 'true'::jsonb OR r.provider IS DISTINCT FROM 'local_geotiff' THEN
       RAISE EXCEPTION 'GIS_GEOTIFF_RESULT_INVARIANT'; END IF;
   END IF;
 END LOOP;
 IF TG_TABLE_NAME='attempts' THEN
   IF NEW.state='failed' THEN
     SELECT * INTO j FROM gis.jobs WHERE id=NEW.job_id;
     PERFORM gis.validate_geotiff_report(NEW.validation_report,e,j);
     IF NEW.validation_report->'valid' IS DISTINCT FROM 'false'::jsonb THEN RAISE EXCEPTION 'GIS_GEOTIFF_REPORT_INVALID'; END IF;
   END IF;
 END IF;
 RETURN NULL;
END $f$;
DO $triggers$
DECLARE t text;
BEGIN
 FOREACH t IN ARRAY ARRAY['geotiff_uploads','editions','jobs','attempts','results'] LOOP
   EXECUTE format('CREATE CONSTRAINT TRIGGER geotiff_catalog_integrity AFTER INSERT OR UPDATE ON gis.%I DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION gis.check_geotiff_catalog()',t);
 END LOOP;
END $triggers$;

CREATE FUNCTION public.gis_geotiff_worker(p_action text,p_payload jsonb DEFAULT '{}') RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE subject uuid;
BEGIN
 subject:=gis.native_subject();
 IF p_payload ? 'worker_id' AND p_payload->>'worker_id' IS DISTINCT FROM subject::text THEN
   RAISE EXCEPTION 'GIS_WORKER_IDENTITY_MISMATCH' USING ERRCODE='42501'; END IF;
 IF p_action='recover' THEN RETURN gis.queue_protocol_kind(p_action,p_payload,'geotiff'); END IF;
 RETURN gis.queue_protocol_kind(p_action,p_payload||jsonb_build_object('worker_id',subject),'geotiff');
END $f$;

CREATE FUNCTION public.gis_geotiff_readiness() RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE subject uuid; value jsonb;
BEGIN
 subject:=gis.native_subject();
 IF NOT EXISTS(SELECT 1 FROM gis.schema_migrations WHERE version=36) THEN RAISE EXCEPTION 'GIS_GEOTIFF_CONTRACT_NOT_READY'; END IF;
 SELECT jsonb_build_object('status','ready','contract_version','1.0.0-geotiff-local','worker_role','gis_native_worker',
   'subject',subject,'runtime_instance',runtime_instance,'baseline_fingerprint',baseline_fingerprint,
   'database_name',database_name,'cluster_name',cluster_name,'mode',mode,
   'migration_versions',(SELECT jsonb_agg(version ORDER BY version) FROM gis.schema_migrations))
   INTO value FROM gis.environment WHERE singleton;
 RETURN value;
END $f$;

REVOKE ALL ON ALL FUNCTIONS IN SCHEMA gis FROM PUBLIC,anon,authenticated,service_role,gis_worker,gis_native_worker;
REVOKE ALL ON FUNCTION public.gis_geotiff_command(uuid,uuid,text,jsonb,boolean),public.gis_geotiff_read(uuid,uuid),
 public.gis_geotiff_worker(text,jsonb),public.gis_geotiff_readiness()
 FROM PUBLIC,anon,authenticated,service_role,gis_worker,gis_native_worker;
GRANT EXECUTE ON FUNCTION public.gis_geotiff_command(uuid,uuid,text,jsonb,boolean),public.gis_geotiff_read(uuid,uuid) TO service_role;
GRANT EXECUTE ON FUNCTION public.gis_geotiff_worker(text,jsonb),public.gis_geotiff_readiness() TO gis_native_worker;
RESET ROLE;
REVOKE CREATE ON SCHEMA public FROM gis_owner;
NOTIFY pgrst,'reload schema';
