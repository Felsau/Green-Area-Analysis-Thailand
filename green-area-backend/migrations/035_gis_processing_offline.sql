-- Phase 3 offline processing only. Runner owns transaction and append-only ledger.
-- No GEE compute/export, credential lookup, legacy cache write or activation.
GRANT CREATE ON SCHEMA public TO gis_owner;
GRANT SELECT(province,name_en,name_th),REFERENCES(province,name_en) ON public.districts TO gis_owner;
CREATE POLICY gis_owner_processing_districts ON public.districts FOR SELECT TO gis_owner USING(true);
SET LOCAL ROLE gis_owner;
SELECT gis.assert_environment();
DO $guard$
BEGIN
 IF current_database() NOT IN ('postgres','gis_t1_upgrade') OR current_setting('cluster_name')<>'green-area-gis-t0'
   OR NOT EXISTS(SELECT 1 FROM gis.environment WHERE singleton
     AND runtime_instance=current_setting('gis.runtime_instance',true)
     AND baseline_fingerprint=current_setting('gis.baseline_fingerprint',true))
   OR NOT EXISTS(SELECT 1 FROM gis.schema_migrations WHERE version=34
     AND sha256='be6edafd9ea9abd8bddcf90c0ac57a3149e2a1aa3aaa0995cc2c7c060e787069')
   OR EXISTS(SELECT 1 FROM gis.schema_migrations WHERE version>=35) THEN
   RAISE EXCEPTION 'GIS_LOCAL_BASELINE_034_REQUIRED'; END IF;
END $guard$;

CREATE TABLE gis.processing_requests(
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 dataset_id uuid NOT NULL REFERENCES gis.datasets(id),edition_id uuid NOT NULL UNIQUE,
 province text NOT NULL REFERENCES public.provinces(name_en),district text,
 metric text NOT NULL CHECK(metric IN ('ndvi','lst')),
 data_year integer NOT NULL CHECK(data_year BETWEEN 2013 AND 2200),
 month integer NOT NULL CHECK(month BETWEEN 0 AND 12),
 mode text NOT NULL CHECK(mode='offline_synthetic'),
 scenario text NOT NULL CHECK(scenario IN ('standard','no_data','transient_once')),
 requested_by uuid REFERENCES public.profiles(id) ON DELETE SET NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 FOREIGN KEY(edition_id,dataset_id) REFERENCES gis.editions(id,dataset_id),
 FOREIGN KEY(province,district) REFERENCES public.districts(province,name_en));
ALTER TABLE gis.processing_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE gis.processing_requests FORCE ROW LEVEL SECURITY;
CREATE POLICY owner_access ON gis.processing_requests TO gis_owner USING(true) WITH CHECK(true);
REVOKE ALL ON gis.processing_requests FROM PUBLIC,anon,authenticated,service_role,gis_worker,gis_native_worker;
CREATE INDEX gis_processing_requests_page ON gis.processing_requests(created_at,id);

ALTER TABLE gis.jobs DROP CONSTRAINT jobs_kind_check;
ALTER TABLE gis.jobs ADD CONSTRAINT jobs_kind_check CHECK(kind IN ('validate_synthetic_edition','validate_ldd_edition','process_offline_edition'));
ALTER TABLE gis.jobs DROP CONSTRAINT jobs_validator_version_check;
ALTER TABLE gis.jobs ADD CONSTRAINT jobs_validator_version_check CHECK(validator_version IN ('synthetic-v1','ldd-local-v1','gee-offline-v1'));
ALTER TABLE gis.results DROP CONSTRAINT results_provider_check;
ALTER TABLE gis.results ADD CONSTRAINT results_provider_check CHECK(provider IN ('synthetic','local_ldd','offline_processing'));

CREATE FUNCTION gis.guard_processing_request() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'GIS_HARD_DELETE_FORBIDDEN'; END IF;
 IF TG_OP='UPDATE' AND NOT(pg_trigger_depth()>1 AND NEW.requested_by IS NULL
   AND (to_jsonb(NEW)-'requested_by')=(to_jsonb(OLD)-'requested_by')) THEN
   RAISE EXCEPTION 'GIS_PROCESSING_INPUT_IMMUTABLE'; END IF;
 RETURN NEW;
END $f$;
CREATE TRIGGER immutable_processing_request BEFORE UPDATE OR DELETE ON gis.processing_requests
 FOR EACH ROW EXECUTE FUNCTION gis.guard_processing_request();


CREATE FUNCTION gis.processing_source(p_metric text,p_scenario text) RETURNS jsonb
LANGUAGE plpgsql IMMUTABLE SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE value jsonb;
BEGIN
 SELECT jsonb_build_object('fixture_id',fid,'sha256',sha,'byte_size',bytes) INTO value
 FROM (VALUES
('ndvi','standard','p3-ndvi-standard-v1','67d90bb99607073a2fcd61455c2b2bd13c98e0e53df6ada6bf4793f4830caabf',2904),
('ndvi','no_data','p3-ndvi-no-data-v1','c15d94ae4183bbcdfa322245ae90598c9d527db5a9bce5b858dbf6a2c86c6a25',2711),
('ndvi','transient_once','p3-ndvi-transient-once-v1','1cb31c9db70e8e1e5feb5869f9b8f49f352d7e9429a62a096a61bb537621f5a2',2910),
('lst','standard','p3-lst-standard-v1','ea10c93aa944930f13de0898350261021c351f850f45db78ad238838318b9a1e',2423),
('lst','no_data','p3-lst-no-data-v1','ccc7cfb27a3d8dd41e554d27b12b7b8a66a44ec8644af6e58c4ef911724678da',2398),
('lst','transient_once','p3-lst-transient-once-v1','5d55d3ce099d6916fb3aa68998f961c5a2fa05dae857e7708db3f3aef33929d3',2429)) fixture(metric,scenario,fid,sha,bytes)
 WHERE metric=p_metric AND scenario=p_scenario;
 IF value IS NULL THEN RAISE EXCEPTION 'GIS_PROCESSING_SOURCE_UNSUPPORTED'; END IF;
 RETURN value||jsonb_build_object('crs','EPSG:32647','bands',CASE WHEN p_metric='ndvi' THEN '["B8","B4","cs"]'::jsonb ELSE '["ST_B10","QA_PIXEL"]'::jsonb END,
  'units',CASE WHEN p_metric='ndvi' THEN 'unitless' ELSE 'celsius' END,
  'resolution',CASE WHEN p_metric='ndvi' THEN 10 ELSE 30 END,
  'source_collections',CASE WHEN p_metric='ndvi' THEN '["COPERNICUS/S2_SR_HARMONIZED","GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED"]'::jsonb
    ELSE '["LANDSAT/LC08/C02/T1_L2","LANDSAT/LC09/C02/T1_L2"]'::jsonb END,
  'cloud_mask',CASE WHEN p_metric='ndvi' THEN 's2-cloud-score-plus-0.6-scene20-fallback80-monthly80' ELSE 'landsat-qa-bits3-4-scene40' END,
  'legacy_pipeline_sha256','{"gee_utils.py":"d1f25fdca1c0562379d5f98002e9bea0a3c94d36f71df6bea45ec6bf94a9a175","ndvi_compute.py":"87b22a35e9dd610e6359f375de5dd9cfebd666bdcee28a22363179155b1febcd","lst.py":"748dcc2d6cc33108bdb7f07effadc2bcbb202e6436703fec68d7d0017004176f"}'::jsonb);
END $f$;

CREATE FUNCTION gis.processing_manifest(p_payload jsonb) RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE year_value integer; month_value integer; start_value date; end_value date; province_value text; district_value text; metric_value text;
BEGIN
 PERFORM gis.keys(p_payload,ARRAY['province','district','metric','data_year','month','mode','scenario','expected_revision']);
 IF p_payload->>'mode' IS DISTINCT FROM 'offline_synthetic' THEN RAISE EXCEPTION 'GIS_GEE_LIVE_DISABLED'; END IF;
 IF p_payload->'expected_revision' IS DISTINCT FROM '1'::jsonb
   OR jsonb_typeof(p_payload->'province') IS DISTINCT FROM 'string'
   OR length(btrim(p_payload->>'province')) NOT BETWEEN 1 AND 120
   OR jsonb_typeof(p_payload->'metric') IS DISTINCT FROM 'string' OR p_payload->>'metric' NOT IN ('ndvi','lst')
   OR jsonb_typeof(p_payload->'data_year') IS DISTINCT FROM 'number' OR COALESCE(p_payload->>'data_year','') !~ '^[0-9]{4}$'
   OR jsonb_typeof(p_payload->'month') IS DISTINCT FROM 'number' OR COALESCE(p_payload->>'month','') !~ '^[0-9]{1,2}$'
   OR jsonb_typeof(p_payload->'scenario') IS DISTINCT FROM 'string' OR p_payload->>'scenario' NOT IN ('standard','no_data','transient_once')
   OR NOT p_payload ? 'district' OR (p_payload->'district'<>'null'::jsonb AND (jsonb_typeof(p_payload->'district')<>'string' OR length(p_payload->>'district') NOT BETWEEN 1 AND 120)) THEN
   RAISE EXCEPTION 'GIS_INVALID_PAYLOAD'; END IF;
 year_value:=(p_payload->>'data_year')::integer;month_value:=(p_payload->>'month')::integer;
 metric_value:=p_payload->>'metric';province_value:=p_payload->>'province';district_value:=p_payload->>'district';
 IF year_value<(CASE WHEN metric_value='ndvi' THEN 2017 ELSE 2013 END) OR year_value>extract(year FROM clock_timestamp())::integer
   OR month_value NOT BETWEEN 0 AND 12 THEN RAISE EXCEPTION 'GIS_PROCESSING_DATE_UNSUPPORTED'; END IF;
 IF NOT EXISTS(SELECT 1 FROM public.provinces WHERE name_en=province_value)
   OR (district_value IS NOT NULL AND NOT EXISTS(SELECT 1 FROM public.districts WHERE province=province_value AND name_en=district_value)) THEN
   RAISE EXCEPTION 'GIS_PROCESSING_SCOPE_UNSUPPORTED'; END IF;
 start_value:=make_date(year_value,CASE WHEN month_value=0 THEN 1 ELSE month_value END,1);
 end_value:=CASE WHEN month_value=0 THEN make_date(year_value+1,1,1) ELSE (start_value+interval '1 month')::date END;
 RETURN gis.processing_source(metric_value,p_payload->>'scenario')||jsonb_build_object(
   'schema_version',3,'provider','offline_synthetic','mode','offline_synthetic','provenance','gis-processing-offline-v1','data_kind','raster',
   'province',province_value,'district',district_value,'metric',metric_value,'data_year',year_value,'month',month_value,'scenario',p_payload->>'scenario',
   'start_date',to_char(start_value,'YYYY-MM-DD'),'end_date',to_char(end_value,'YYYY-MM-DD'),
   'scale_m',CASE WHEN district_value IS NULL THEN 500 ELSE 100 END,'processing_version','gee-offline-v1');
END $f$;

-- Exact Phase 2 body retained for V1/V2 compatibility.
CREATE FUNCTION gis.phase2_manifest_hash(p_manifest jsonb) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE ver text;
BEGIN
 IF jsonb_typeof(p_manifest) IS DISTINCT FROM 'object' OR octet_length(p_manifest::text)>65536 THEN
   RAISE EXCEPTION 'GIS_INVALID_PAYLOAD'; END IF;
 ver := p_manifest->>'schema_version';
 IF ver = '1' THEN
   PERFORM gis.keys(p_manifest,ARRAY['schema_version','provider','fixture_id','sha256','byte_size','provenance','crs','data_kind','bands','units','nodata','resolution','attributes']);
   IF p_manifest->>'provider' NOT IN ('synthetic','real')
      OR p_manifest->>'provider' IS NULL
      OR COALESCE(p_manifest->>'sha256','') !~ '^[0-9a-f]{64}$'
      OR COALESCE(p_manifest->>'byte_size','') !~ '^[1-9][0-9]{0,8}$'
      OR COALESCE(p_manifest->>'provenance','') !~ '^[A-Za-z0-9 _.-]{1,100}$'
      OR COALESCE(p_manifest->>'crs','') !~ '^EPSG:[0-9]{4,6}$'
      OR COALESCE(p_manifest->>'data_kind','') NOT IN ('raster','polygon')
      OR p_manifest::text ~ '(https?://|file:|\\\\|\.\./)' THEN RAISE EXCEPTION 'GIS_INVALID_MANIFEST'; END IF;
   IF p_manifest->>'provider'='real' THEN
    IF p_manifest ? 'fixture_id' OR (p_manifest->>'data_kind'='raster' AND
        (jsonb_typeof(p_manifest->'bands') IS DISTINCT FROM 'array'
         OR jsonb_array_length(p_manifest->'bands') NOT BETWEEN 1 AND 8
         OR COALESCE(p_manifest->>'units','') NOT IN ('celsius','unitless','categories')
         OR jsonb_typeof(p_manifest->'nodata') IS DISTINCT FROM 'number'
         OR jsonb_typeof(p_manifest->'resolution') IS DISTINCT FROM 'number'))
      OR (p_manifest->>'data_kind'='polygon' AND jsonb_typeof(p_manifest->'attributes') IS DISTINCT FROM 'array') THEN
      RAISE EXCEPTION 'GIS_INVALID_MANIFEST'; END IF;
    IF EXISTS(SELECT 1 FROM jsonb_array_elements(COALESCE(p_manifest->'bands','[]')) value
        WHERE jsonb_typeof(value)<>'string' OR value#>>'{}' !~ '^[A-Za-z][A-Za-z0-9_]{0,39}$')
      OR EXISTS(SELECT 1 FROM jsonb_array_elements(COALESCE(p_manifest->'attributes','[]')) value
        WHERE jsonb_typeof(value)<>'string' OR value#>>'{}' !~ '^[A-Za-z][A-Za-z0-9_]{0,39}$')
      OR (p_manifest ? 'resolution' AND (p_manifest->>'resolution')::numeric NOT BETWEEN 0.001 AND 10000)
      OR (p_manifest ? 'nodata' AND abs((p_manifest->>'nodata')::numeric)>1e12)
      OR (p_manifest ? 'attributes' AND jsonb_array_length(p_manifest->'attributes')>30) THEN
      RAISE EXCEPTION 'GIS_INVALID_MANIFEST'; END IF;
   END IF;
   IF p_manifest->>'provider'='synthetic' AND NOT EXISTS(SELECT 1 FROM gis.synthetic_fixtures WHERE manifest=p_manifest) THEN
     RAISE EXCEPTION 'GIS_SYNTHETIC_MANIFEST_NOT_ALLOWLISTED'; END IF;
 ELSIF ver = '2' THEN
   PERFORM gis.keys(p_manifest,ARRAY['schema_version','provider','fixture_id','sha256','byte_size','provenance','crs','data_kind','profile','provider_build','bands','units','nodata','resolution','attributes','scales','offsets']);
   IF p_manifest->>'provider' <> 'synthetic'
      OR COALESCE(p_manifest->>'sha256','') !~ '^[0-9a-f]{64}$'
      OR COALESCE(p_manifest->>'byte_size','') !~ '^[1-9][0-9]{0,8}$'
      OR COALESCE(p_manifest->>'provenance','') !~ '^[A-Za-z0-9 _.-]{1,100}$'
      OR COALESCE(p_manifest->>'crs','') !~ '^EPSG:[0-9]{4,6}$'
      OR COALESCE(p_manifest->>'data_kind','') NOT IN ('raster','polygon')
      OR COALESCE(p_manifest->>'provider_build','') !~ '^[A-Za-z0-9 _.-]{1,60}$'
      OR p_manifest::text ~ '(https?://|file:|\\\\|\.\./)' THEN RAISE EXCEPTION 'GIS_INVALID_MANIFEST'; END IF;
   IF NOT EXISTS(SELECT 1 FROM gis.synthetic_fixtures WHERE manifest=p_manifest) THEN
     RAISE EXCEPTION 'GIS_SYNTHETIC_MANIFEST_NOT_ALLOWLISTED'; END IF;
 ELSE
   RAISE EXCEPTION 'GIS_INVALID_MANIFEST';
 END IF;
 RETURN encode(sha256(convert_to(p_manifest::text,'UTF8')),'hex');
END $f$;

CREATE OR REPLACE FUNCTION gis.manifest_hash(p_manifest jsonb) RETURNS text
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

CREATE FUNCTION gis.phase2_command(p_actor uuid,p_request_id uuid,p_operation text,p_payload jsonb,p_backend_sandbox boolean)
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
CREATE FUNCTION gis.phase2_eligible(p_edition uuid,p_dataset uuid) RETURNS boolean
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
CREATE FUNCTION gis.phase2_api_read_row(p_kind text,p_row jsonb) RETURNS jsonb
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

CREATE FUNCTION gis.validate_processing_report(p_report jsonb,p_edition gis.editions,p_job gis.jobs) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE request gis.processing_requests%ROWTYPE; stats jsonb; item jsonb; n integer; expected_mean numeric; expected_min numeric; expected_max numeric; tolerance numeric;
BEGIN
 SELECT * INTO request FROM gis.processing_requests WHERE edition_id=p_edition.id;
 IF NOT FOUND OR p_job.edition_id<>p_edition.id OR p_job.kind<>'process_offline_edition' OR p_job.validator_version<>'gee-offline-v1'
   OR p_edition.input_hash IS DISTINCT FROM gis.manifest_hash(p_edition.manifest)
   OR p_job.input_hash<>p_edition.input_hash OR p_job.input_revision<>p_edition.input_revision THEN
   RAISE EXCEPTION 'GIS_PROCESSING_INPUT_INVARIANT'; END IF;
 PERFORM gis.keys(p_report,ARRAY['schema_version','provider_build','mode','synthetic','processing_id','artifact_sha256','input_hash','input_revision','valid','error_code','statistics','metadata']);
 IF NOT p_report ?& ARRAY['schema_version','provider_build','mode','synthetic','processing_id','artifact_sha256','input_hash','input_revision','valid','error_code','statistics','metadata']
   OR octet_length(p_report::text)>16384 OR p_report->'schema_version' IS DISTINCT FROM '1'::jsonb
   OR p_report->>'provider_build' IS DISTINCT FROM 'gee-offline-v1' OR p_report->>'mode' IS DISTINCT FROM 'offline_synthetic'
   OR p_report->'synthetic' IS DISTINCT FROM 'true'::jsonb OR p_report->>'processing_id' IS DISTINCT FROM request.id::text
   OR p_report->>'artifact_sha256' IS DISTINCT FROM p_edition.manifest->>'sha256'
   OR p_report->>'input_hash' IS DISTINCT FROM p_job.input_hash OR p_report->'input_revision' IS DISTINCT FROM to_jsonb(p_job.input_revision)
   OR p_report->'metadata' IS DISTINCT FROM p_edition.manifest OR jsonb_typeof(p_report->'valid') IS DISTINCT FROM 'boolean' THEN
   RAISE EXCEPTION 'GIS_PROCESSING_REPORT_INVALID'; END IF;
 stats:=p_report->'statistics';
 PERFORM gis.keys(stats,ARRAY['valid_pixels','mean','min','max']);
 IF NOT stats ?& ARRAY['valid_pixels','mean','min','max'] OR jsonb_typeof(stats->'valid_pixels') IS DISTINCT FROM 'number'
   OR COALESCE(stats->>'valid_pixels','') !~ '^[0-4]$' THEN RAISE EXCEPTION 'GIS_PROCESSING_REPORT_INVALID'; END IF;
 n:=(stats->>'valid_pixels')::integer;
 IF p_report->'valid'='true'::jsonb THEN
   IF n=0 OR request.scenario='no_data' OR (request.scenario='transient_once' AND p_job.attempt_count=1)
      OR p_report->'error_code' IS DISTINCT FROM 'null'::jsonb THEN RAISE EXCEPTION 'GIS_PROCESSING_SCIENTIFIC_INVARIANT'; END IF;
   FOR item IN SELECT value FROM jsonb_each(stats-'valid_pixels') LOOP
     IF jsonb_typeof(item) IS DISTINCT FROM 'number' OR abs((item#>>'{}')::numeric)>100 THEN
       RAISE EXCEPTION 'GIS_PROCESSING_SCIENTIFIC_INVARIANT'; END IF;
   END LOOP;
   IF (stats->>'min')::numeric>(stats->>'mean')::numeric OR (stats->>'mean')::numeric>(stats->>'max')::numeric THEN
     RAISE EXCEPTION 'GIS_PROCESSING_SCIENTIFIC_INVARIANT'; END IF;
   -- These are invariant expectations for six fixed synthetic source files,
   -- not assertions about a selected province/district or live observations.
   IF request.metric='ndvi' THEN
     expected_mean:=CASE WHEN request.month=0 THEN 0.4921 ELSE 0.1614 END;
     expected_min:=CASE WHEN request.month=0 THEN 0.4286 ELSE -0.5 END;expected_max:=0.5556;tolerance:=0.00001;
     IF n<>(CASE WHEN request.month=0 THEN 2 ELSE 3 END) THEN RAISE EXCEPTION 'GIS_PROCESSING_SCIENTIFIC_INVARIANT'; END IF;
   ELSE
     expected_mean:=29.66;expected_min:=22.82;expected_max:=36.5;tolerance:=0.00001;
     IF n<>2 THEN RAISE EXCEPTION 'GIS_PROCESSING_SCIENTIFIC_INVARIANT'; END IF;
   END IF;
   IF abs((stats->>'mean')::numeric-expected_mean)>tolerance OR abs((stats->>'min')::numeric-expected_min)>tolerance
      OR abs((stats->>'max')::numeric-expected_max)>tolerance THEN RAISE EXCEPTION 'GIS_PROCESSING_SCIENTIFIC_INVARIANT'; END IF;
 ELSE
   IF jsonb_typeof(p_report->'error_code') IS DISTINCT FROM 'string' OR p_report->>'error_code' !~ '^[A-Z][A-Z0-9_]{0,59}$'
     OR n<>0 OR stats->'mean' IS DISTINCT FROM 'null'::jsonb OR stats->'min' IS DISTINCT FROM 'null'::jsonb
     OR stats->'max' IS DISTINCT FROM 'null'::jsonb THEN RAISE EXCEPTION 'GIS_PROCESSING_REPORT_INVALID'; END IF;
 END IF;
END $f$;

CREATE FUNCTION gis.processing_job_row(p_job uuid) RETURNS jsonb
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
 SELECT gis.api_read_row('job',to_jsonb(j))||jsonb_build_object('processing_id',q.id,'mode',q.mode,'metadata',e.manifest,
  'candidate_status',CASE WHEN j.state='succeeded' THEN 'pending_review' ELSE 'not_ready' END,
  'result',(SELECT gis.api_read_row('result',to_jsonb(r)) FROM gis.results r WHERE r.job_id=j.id))
 FROM gis.jobs j JOIN gis.processing_requests q ON q.edition_id=j.edition_id JOIN gis.editions e ON e.id=q.edition_id
 WHERE j.id=p_job AND j.kind='process_offline_edition'
$f$;

CREATE FUNCTION gis.processing_command(p_actor uuid,p_request_id uuid,p_operation text,p_payload jsonb,p_backend_sandbox boolean DEFAULT false)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE request gis.processing_requests%ROWTYPE; d gis.datasets%ROWTYPE; e gis.editions%ROWTYPE; j gis.jobs%ROWTYPE;
 receipt gis.receipts%ROWTYPE; digest text; manifest_value jsonb; body_value jsonb; reason_value text; status_value integer:=202;
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
   manifest_value:=gis.processing_manifest(p_payload);
   PERFORM pg_advisory_xact_lock(hashtextextended('gis-processing-dataset:'||(manifest_value->>'province')||':'||(manifest_value->>'data_year')||':'||(manifest_value->>'month')||':'||(manifest_value->>'metric'),0));
   SELECT * INTO d FROM gis.datasets WHERE province=manifest_value->>'province' AND data_year=(manifest_value->>'data_year')::integer
     AND month=(manifest_value->>'month')::integer AND kind='geotiff' AND purpose=manifest_value->>'metric' FOR NO KEY UPDATE;
   IF NOT FOUND THEN
     INSERT INTO gis.datasets(province,data_year,month,kind,purpose,title,created_by)
       VALUES(manifest_value->>'province',(manifest_value->>'data_year')::integer,(manifest_value->>'month')::integer,'geotiff',manifest_value->>'metric',
         'Offline synthetic processing (not live GEE)',p_actor) ON CONFLICT(province,data_year,month,kind,purpose) DO NOTHING;
     SELECT * INTO d FROM gis.datasets WHERE province=manifest_value->>'province' AND data_year=(manifest_value->>'data_year')::integer
       AND month=(manifest_value->>'month')::integer AND kind='geotiff' AND purpose=manifest_value->>'metric' FOR NO KEY UPDATE;
   END IF;
   -- Content dedup is immutable scope/source/version specific. An explicit retry
   -- is the only way to rerun a failed original; a new key cannot reset budgets.
   SELECT ed.* INTO e FROM gis.editions ed JOIN gis.processing_requests q ON q.edition_id=ed.id
     WHERE ed.dataset_id=d.id AND ed.manifest=manifest_value ORDER BY ed.created_at,ed.id LIMIT 1 FOR UPDATE OF ed;
   IF FOUND THEN
     SELECT * INTO j FROM gis.jobs WHERE edition_id=e.id AND parent_job_id IS NULL;
     status_value:=CASE WHEN j.state IN ('queued','running') THEN 202 ELSE 200 END;
   ELSE
     INSERT INTO gis.editions(dataset_id,manifest,input_hash,created_by)
       VALUES(d.id,manifest_value,gis.manifest_hash(manifest_value),p_actor) RETURNING * INTO e;
     INSERT INTO gis.processing_requests(dataset_id,edition_id,province,district,metric,data_year,month,mode,scenario,requested_by)
       VALUES(d.id,e.id,manifest_value->>'province',manifest_value->>'district',manifest_value->>'metric',(manifest_value->>'data_year')::integer,
         (manifest_value->>'month')::integer,'offline_synthetic',manifest_value->>'scenario',p_actor) RETURNING * INTO request;
     INSERT INTO gis.jobs(edition_id,kind,validator_version,input_revision,input_hash,requested_by)
       VALUES(e.id,'process_offline_edition','gee-offline-v1',e.input_revision,e.input_hash,p_actor) RETURNING * INTO j;
     UPDATE gis.editions SET state='validating' WHERE id=e.id;
   END IF;
 ELSE
   SELECT * INTO j FROM gis.jobs WHERE id=(p_payload->>'job_id')::uuid;
   IF NOT FOUND THEN RAISE EXCEPTION 'GIS_NOT_FOUND'; END IF;
   SELECT * INTO e FROM gis.editions WHERE id=j.edition_id FOR UPDATE;
   SELECT * INTO j FROM gis.jobs WHERE id=j.id FOR UPDATE;
   SELECT * INTO request FROM gis.processing_requests WHERE edition_id=e.id;
   IF request.id IS NULL OR j.kind<>'process_offline_edition' THEN RAISE EXCEPTION 'GIS_NOT_FOUND'; END IF;
   IF p_payload->'expected_revision' IS DISTINCT FROM to_jsonb(e.input_revision) OR p_payload->>'input_hash' IS DISTINCT FROM e.input_hash THEN
     RAISE EXCEPTION 'GIS_REVISION_CONFLICT'; END IF;
   reason_value:=btrim(p_payload->>'reason');
   IF reason_value IS NULL OR length(reason_value) NOT BETWEEN 1 AND 500 THEN RAISE EXCEPTION 'GIS_REASON_REQUIRED'; END IF;
   IF j.parent_job_id IS NOT NULL OR j.state<>'failed' OR j.error_code NOT IN ('transient','attempts_exhausted')
     OR e.state<>'draft' OR j.input_revision<>e.input_revision OR j.input_hash<>e.input_hash THEN RAISE EXCEPTION 'GIS_RETRY_INELIGIBLE'; END IF;
   IF EXISTS(SELECT 1 FROM gis.jobs WHERE parent_job_id=j.id) THEN RAISE EXCEPTION 'GIS_RETRY_ALREADY_USED'; END IF;
   INSERT INTO gis.jobs(edition_id,parent_job_id,kind,validator_version,input_revision,input_hash,requested_by)
     VALUES(e.id,j.id,'process_offline_edition','gee-offline-v1',e.input_revision,e.input_hash,p_actor) RETURNING * INTO j;
   UPDATE gis.editions SET state='validating' WHERE id=e.id;
 END IF;
 PERFORM gis.authorize(p_actor,false);
 body_value:=gis.processing_job_row(j.id);
 INSERT INTO gis.audit(actor_id,operation,dataset_id,edition_id,job_id,reason,detail)
   VALUES(p_actor,'processing.'||p_operation,e.dataset_id,e.id,j.id,reason_value,jsonb_build_object('mode','offline_synthetic','state',j.state));
 INSERT INTO gis.receipts(actor_id,request_id,operation,payload_hash,status,body)
   VALUES(p_actor,p_request_id,'processing.'||p_operation,digest,status_value,body_value);
 RETURN jsonb_build_object('status',status_value,'body',body_value);
END $f$;

CREATE FUNCTION public.gis_processing_command(p_actor uuid,p_request_id uuid,p_operation text,p_payload jsonb,p_backend_sandbox boolean DEFAULT false)
RETURNS jsonb LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,gis
AS $f$ SELECT gis.processing_command(p_actor,p_request_id,p_operation,p_payload,p_backend_sandbox) $f$;

CREATE OR REPLACE FUNCTION gis.queue_protocol_kind(p_action text,p_payload jsonb,p_protocol text) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE j gis.jobs%ROWTYPE; e gis.editions%ROWTYPE; candidate record;
 worker uuid; token uuid; jid uuid; eid uuid; rid uuid; v_now timestamptz;
 progress_value integer; report_value jsonb; code text; next_state text; n integer:=0;
 p_native boolean:=p_protocol<>'v1'; u gis.ldd_uploads%ROWTYPE; ldd_dataset gis.datasets%ROWTYPE; processing_request gis.processing_requests%ROWTYPE;
BEGIN
 PERFORM gis.assert_environment();
 IF p_protocol NOT IN ('v1','v2','ldd','gee_offline') OR p_protocol IS NULL THEN RAISE EXCEPTION 'GIS_WORKER_PROTOCOL_MISMATCH'; END IF;
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
     IF p_protocol='gee_offline' THEN
       SELECT * INTO processing_request FROM gis.processing_requests WHERE edition_id=e.id;
       report_value:=report_value||jsonb_build_object('processing_id',processing_request.id);
     END IF;
     IF p_native THEN
       INSERT INTO gis.audit(operation,dataset_id,edition_id,job_id,detail)
         VALUES(CASE WHEN p_protocol='gee_offline' THEN 'processing.claim' WHEN p_protocol='ldd' THEN 'ldd.claim' ELSE 'worker_v2.claim' END,e.dataset_id,e.id,j.id,jsonb_build_object('worker_id',worker,'attempt',j.attempt_count));
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
       VALUES(CASE WHEN p_protocol='gee_offline' THEN 'processing.recover' WHEN p_protocol='ldd' THEN 'ldd.recover' WHEN p_native THEN 'worker_v2.recover' ELSE 'worker.recover' END,e.dataset_id,e.id,j.id,
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
     IF p_protocol='gee_offline' THEN PERFORM gis.validate_processing_report(report_value,e,j);
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
       VALUES(j.id,e.id,j.input_revision,j.input_hash,j.validator_version,j.attempt_count,token,true,report_value,CASE WHEN p_protocol='gee_offline' THEN 'offline_processing' WHEN p_protocol='ldd' THEN 'local_ldd' ELSE 'synthetic' END) RETURNING id INTO rid;
     IF p_protocol='gee_offline' THEN
       UPDATE gis.editions SET state='draft',validated_result_id=NULL WHERE id=e.id;
     ELSE
       UPDATE gis.editions SET state='validated',validated_result_id=rid WHERE id=e.id;
     END IF;
     UPDATE gis.jobs SET state='succeeded',worker_id=NULL,lease_token=NULL,lease_until=NULL,progress=100,finished_at=v_now WHERE id=j.id;
     UPDATE gis.attempts SET state='succeeded',progress=100,finished_at=v_now WHERE job_id=j.id AND attempt_no=j.attempt_count AND lease_token=token;
     INSERT INTO gis.audit(operation,dataset_id,edition_id,job_id,detail)
       VALUES(CASE WHEN p_protocol='gee_offline' THEN 'processing.complete' WHEN p_protocol='ldd' THEN 'ldd.complete' WHEN p_native THEN 'worker_v2.complete' ELSE 'worker.complete' END,e.dataset_id,e.id,j.id,
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
     VALUES(CASE WHEN p_protocol='gee_offline' THEN 'processing.fail' WHEN p_protocol='ldd' THEN 'ldd.fail' WHEN p_native THEN 'worker_v2.fail' ELSE 'worker.fail' END,e.dataset_id,e.id,j.id,
       jsonb_build_object('attempt',j.attempt_count,'error_code',code,'state',next_state));
   RETURN CASE WHEN p_native THEN jsonb_build_object('job_id',j.id,'state',next_state,'error_code',code)
     ELSE jsonb_build_object('job_id',j.id,'state',next_state) END;
 END IF;
 RAISE EXCEPTION 'GIS_UNKNOWN_WORKER_ACTION';
END $f$;

CREATE OR REPLACE FUNCTION gis.edition_protocol(p_edition uuid) RETURNS text
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
 SELECT CASE WHEN EXISTS(SELECT 1 FROM gis.processing_requests q WHERE q.edition_id=e.id) AND e.manifest->'schema_version'='3'::jsonb
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
 ELSIF p_operation IN ('enqueue','clone_edition','edit_edition','withdraw') THEN eid:=(p_payload->>'edition_id')::uuid;
 ELSIF p_operation IN ('activate','rollback') THEN eid:=(p_payload->>'edition_id')::uuid; END IF;
 IF (p_payload->'manifest'->'schema_version'='3'::jsonb) OR EXISTS(SELECT 1 FROM gis.editions WHERE id=eid AND manifest->'schema_version'='3'::jsonb) THEN
   PERFORM gis.authorize(p_actor,p_operation IN ('activate','rollback','withdraw'));
   RAISE EXCEPTION 'GIS_PROCESSING_COMMAND_REQUIRED'; END IF;
 RETURN gis.phase2_command(p_actor,p_request_id,p_operation,p_payload,p_backend_sandbox);
END $f$;

CREATE OR REPLACE FUNCTION gis.eligible(p_edition uuid,p_dataset uuid) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
 SELECT CASE WHEN EXISTS(SELECT 1 FROM gis.editions WHERE id=p_edition AND manifest->'schema_version'='3'::jsonb)
   THEN false ELSE gis.phase2_eligible(p_edition,p_dataset) END
$f$;

CREATE OR REPLACE FUNCTION gis.api_read_row(p_kind text,p_row jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE value jsonb;
BEGIN
 value:=gis.phase2_api_read_row(p_kind,p_row);
 IF p_kind='result' AND p_row->>'provider'='offline_processing' THEN
   value:=value||jsonb_build_object('mode','offline_synthetic','candidate_status','pending_review','report',p_row->'report');
 END IF;
 RETURN value;
END $f$;

CREATE FUNCTION gis.check_processing_catalog() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE eid uuid; jid uuid; e gis.editions%ROWTYPE; d gis.datasets%ROWTYPE; request gis.processing_requests%ROWTYPE;
 j gis.jobs%ROWTYPE; a gis.attempts%ROWTYPE; r gis.results%ROWTYPE; manifest_value jsonb;
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
   IF e.manifest->'schema_version'='3'::jsonb OR (jid IS NOT NULL AND EXISTS(SELECT 1 FROM gis.jobs WHERE id=jid AND kind='process_offline_edition')) THEN
     RAISE EXCEPTION 'GIS_PROCESSING_ASSOCIATION_REQUIRED'; END IF;
   RETURN NULL;
 END IF;
 SELECT * INTO d FROM gis.datasets WHERE id=e.dataset_id;
 manifest_value:=gis.processing_manifest(jsonb_build_object('province',request.province,'district',request.district,'metric',request.metric,
   'data_year',request.data_year,'month',request.month,'mode',request.mode,'scenario',request.scenario,'expected_revision',1));
 IF e.dataset_id IS DISTINCT FROM request.dataset_id OR e.manifest IS DISTINCT FROM manifest_value
   OR e.input_hash IS DISTINCT FROM gis.manifest_hash(manifest_value) OR e.input_revision<>1
   OR d.province IS DISTINCT FROM request.province OR d.data_year IS DISTINCT FROM request.data_year OR d.month IS DISTINCT FROM request.month
   OR d.kind IS DISTINCT FROM 'geotiff' OR d.purpose IS DISTINCT FROM request.metric
   OR e.validated_result_id IS NOT NULL OR e.state NOT IN ('draft','validating') OR d.active_edition_id=e.id THEN
   RAISE EXCEPTION 'GIS_PROCESSING_INPUT_INVARIANT'; END IF;
 FOR j IN SELECT * FROM gis.jobs WHERE edition_id=e.id LOOP
   IF j.kind<>'process_offline_edition' OR j.validator_version<>'gee-offline-v1' THEN RAISE EXCEPTION 'GIS_WORKER_PROTOCOL_MISMATCH'; END IF;
   IF j.state='succeeded' THEN
     SELECT * INTO a FROM gis.attempts WHERE job_id=j.id AND attempt_no=j.attempt_count;
     SELECT * INTO r FROM gis.results WHERE job_id=j.id;
     PERFORM gis.validate_processing_report(a.validation_report,e,j);
     IF a.state IS DISTINCT FROM 'succeeded' OR r.report IS DISTINCT FROM a.validation_report
       OR a.validation_report->'valid' IS DISTINCT FROM 'true'::jsonb OR r.provider IS DISTINCT FROM 'offline_processing' THEN
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
DO $triggers$
DECLARE t text;
BEGIN
 FOREACH t IN ARRAY ARRAY['processing_requests','editions','jobs','attempts','results'] LOOP
   EXECUTE format('CREATE CONSTRAINT TRIGGER processing_catalog_integrity AFTER INSERT OR UPDATE ON gis.%I DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION gis.check_processing_catalog()',t);
 END LOOP;
END $triggers$;

CREATE FUNCTION public.gis_processing_worker(p_action text,p_payload jsonb DEFAULT '{}') RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE subject uuid;
BEGIN
 subject:=gis.native_subject();
 IF p_payload ? 'worker_id' AND p_payload->>'worker_id' IS DISTINCT FROM subject::text THEN
   RAISE EXCEPTION 'GIS_WORKER_IDENTITY_MISMATCH' USING ERRCODE='42501'; END IF;
 IF p_action='recover' THEN RETURN gis.queue_protocol_kind(p_action,p_payload,'gee_offline'); END IF;
 RETURN gis.queue_protocol_kind(p_action,p_payload||jsonb_build_object('worker_id',subject),'gee_offline');
END $f$;

CREATE FUNCTION public.gis_processing_readiness() RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE subject uuid; value jsonb;
BEGIN
 subject:=gis.native_subject();
 IF NOT EXISTS(SELECT 1 FROM gis.schema_migrations WHERE version=35) THEN RAISE EXCEPTION 'GIS_PROCESSING_CONTRACT_NOT_READY'; END IF;
 SELECT jsonb_build_object('status','ready','contract_version','1.0.0-processing-offline','worker_role','gis_native_worker',
   'subject',subject,'runtime_instance',runtime_instance,'baseline_fingerprint',baseline_fingerprint,
   'database_name',database_name,'cluster_name',cluster_name,'mode',mode,
   'migration_versions',(SELECT jsonb_agg(version ORDER BY version) FROM gis.schema_migrations))
   INTO value FROM gis.environment WHERE singleton;
 RETURN value;
END $f$;

CREATE FUNCTION gis.processing_read(p_actor uuid,p_kind text,p_payload jsonb DEFAULT '{}') RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE rows_value jsonb; last_value jsonb; result_value jsonb; row_value jsonb; allowed text[];
 limit_value integer:=20; cursor_time timestamptz; cursor_id uuid; job_value uuid; edition_value uuid;
 province_value text; metric_value text; state_value text; more boolean; delegated jsonb;
BEGIN
 PERFORM gis.authorize(p_actor,false);
 allowed:=CASE p_kind
   WHEN 'options' THEN ARRAY['province'] WHEN 'jobs' THEN ARRAY['limit','cursor','state','metric','province']
   WHEN 'job' THEN ARRAY['id'] WHEN 'result' THEN ARRAY['id']
   WHEN 'attempts' THEN ARRAY['job_id','limit','cursor'] WHEN 'history' THEN ARRAY['job_id','limit','cursor'] END;
 IF allowed IS NULL THEN RAISE EXCEPTION 'GIS_UNKNOWN_READ'; END IF;
 PERFORM gis.keys(p_payload,allowed);
 IF p_kind='options' THEN
   IF p_payload ? 'province' AND (jsonb_typeof(p_payload->'province') IS DISTINCT FROM 'string'
      OR NOT EXISTS(SELECT 1 FROM public.provinces WHERE name_en=p_payload->>'province')) THEN RAISE EXCEPTION 'GIS_PROCESSING_SCOPE_UNSUPPORTED'; END IF;
   RETURN jsonb_build_object('mode','offline_synthetic','live_enabled',false,'processing_version','gee-offline-v1',
    'provinces',(SELECT COALESCE(jsonb_agg(jsonb_build_object('name_en',name_en,'name_th',name_th) ORDER BY name_en),'[]'::jsonb) FROM public.provinces),
    'districts',(SELECT COALESCE(jsonb_agg(jsonb_build_object('province',province,'name_en',name_en,'name_th',name_th) ORDER BY name_en),'[]'::jsonb)
      FROM public.districts WHERE province=p_payload->>'province'));
 END IF;
 IF p_kind IN ('job','result','attempts','history') THEN
   job_value:=(CASE WHEN p_kind IN ('job','result') THEN p_payload->>'id' ELSE p_payload->>'job_id' END)::uuid;
   row_value:=gis.processing_job_row(job_value);
   IF row_value IS NULL THEN RAISE EXCEPTION 'GIS_NOT_FOUND'; END IF;
   IF p_kind='job' THEN RETURN row_value; END IF;
   IF p_kind='result' THEN
     RETURN jsonb_build_object('job_id',job_value,'state',row_value->'state','candidate_status',row_value->'candidate_status',
       'result',row_value->'result','error_code',row_value->'error_code');
   END IF;
   delegated:=p_payload-'job_id';
   IF p_kind='attempts' THEN delegated:=delegated||jsonb_build_object('job_id',job_value);
   ELSE
     SELECT edition_id INTO edition_value FROM gis.jobs WHERE id=job_value;
     delegated:=delegated||jsonb_build_object('edition_id',edition_value);
   END IF;
   RETURN gis.read(p_actor,p_kind,delegated);
 END IF;
 IF p_payload ? 'limit' THEN
   IF jsonb_typeof(p_payload->'limit') IS DISTINCT FROM 'number' OR COALESCE(p_payload->>'limit','') !~ '^[0-9]{1,3}$' THEN
     RAISE EXCEPTION 'GIS_INVALID_LIMIT'; END IF;
   limit_value:=(p_payload->>'limit')::integer;
 END IF;
 IF limit_value NOT BETWEEN 1 AND 100 THEN RAISE EXCEPTION 'GIS_INVALID_LIMIT'; END IF;
 IF p_payload ? 'cursor' AND p_payload->'cursor'<>'null'::jsonb THEN
   PERFORM gis.keys(p_payload->'cursor',ARRAY['created_at','id']);
   IF jsonb_typeof(p_payload->'cursor'->'created_at') IS DISTINCT FROM 'string'
     OR jsonb_typeof(p_payload->'cursor'->'id') IS DISTINCT FROM 'string'
     OR COALESCE(p_payload->'cursor'->>'created_at','') !~ '(Z|[+-][0-9]{2}:[0-9]{2})$' THEN RAISE EXCEPTION 'GIS_INVALID_CURSOR'; END IF;
   cursor_time:=(p_payload->'cursor'->>'created_at')::timestamptz;cursor_id:=(p_payload->'cursor'->>'id')::uuid;
 END IF;
 IF p_payload ? 'state' THEN
   IF jsonb_typeof(p_payload->'state') IS DISTINCT FROM 'string' OR p_payload->>'state' NOT IN ('queued','running','succeeded','failed') THEN
     RAISE EXCEPTION 'GIS_INVALID_FILTER'; END IF;
   state_value:=p_payload->>'state';
 END IF;
 IF p_payload ? 'metric' THEN
   IF jsonb_typeof(p_payload->'metric') IS DISTINCT FROM 'string' OR p_payload->>'metric' NOT IN ('ndvi','lst') THEN RAISE EXCEPTION 'GIS_INVALID_FILTER'; END IF;
   metric_value:=p_payload->>'metric';
 END IF;
 IF p_payload ? 'province' THEN
   IF jsonb_typeof(p_payload->'province') IS DISTINCT FROM 'string' OR length(p_payload->>'province') NOT BETWEEN 1 AND 120 THEN RAISE EXCEPTION 'GIS_INVALID_FILTER'; END IF;
   province_value:=p_payload->>'province';
 END IF;
 SELECT COALESCE(jsonb_agg(gis.processing_job_row(page.id) ORDER BY page.created_at,page.id),'[]'::jsonb) INTO rows_value
 FROM (SELECT j.id,j.created_at FROM gis.jobs j JOIN gis.processing_requests q ON q.edition_id=j.edition_id
   WHERE j.kind='process_offline_edition' AND (state_value IS NULL OR j.state=state_value)
     AND (metric_value IS NULL OR q.metric=metric_value) AND (province_value IS NULL OR q.province=province_value)
     AND (cursor_time IS NULL OR (j.created_at,j.id)>(cursor_time,cursor_id))
   ORDER BY j.created_at,j.id LIMIT limit_value+1) page;
 more:=jsonb_array_length(rows_value)>limit_value;
 IF more THEN rows_value:=rows_value-limit_value; END IF;
 last_value:=rows_value->(jsonb_array_length(rows_value)-1);
 RETURN jsonb_build_object('data',rows_value,'has_more',more,'next_cursor',CASE WHEN more THEN
   jsonb_build_object('created_at',last_value->>'created_at','id',last_value->>'id') ELSE NULL END);
END $f$;

CREATE FUNCTION public.gis_processing_read(p_actor uuid,p_kind text,p_payload jsonb DEFAULT '{}') RETURNS jsonb
LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,gis
AS $f$ SELECT gis.processing_read(p_actor,p_kind,p_payload) $f$;

REVOKE ALL ON ALL FUNCTIONS IN SCHEMA gis FROM PUBLIC,anon,authenticated,service_role,gis_worker,gis_native_worker;
REVOKE ALL ON FUNCTION public.gis_processing_command(uuid,uuid,text,jsonb,boolean),public.gis_processing_read(uuid,text,jsonb),
 public.gis_processing_worker(text,jsonb),public.gis_processing_readiness()
 FROM PUBLIC,anon,authenticated,service_role,gis_worker,gis_native_worker;
GRANT EXECUTE ON FUNCTION public.gis_processing_command(uuid,uuid,text,jsonb,boolean),public.gis_processing_read(uuid,text,jsonb) TO service_role;
GRANT EXECUTE ON FUNCTION public.gis_processing_worker(text,jsonb),public.gis_processing_readiness() TO gis_native_worker;
RESET ROLE;
REVOKE REFERENCES(province,name_en) ON public.districts FROM gis_owner;
REVOKE CREATE ON SCHEMA public FROM gis_owner;
NOTIFY pgrst,'reload schema';
