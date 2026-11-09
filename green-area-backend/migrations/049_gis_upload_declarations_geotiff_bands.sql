-- 049 Upload scope 2.1.13 and 2.1.16.
-- 1. Each new LDD or GeoTIFF upload records the officer's declared source, and a GeoTIFF
--    its acquisition date, beside the manifest. Declarations are not independently verified.
-- 2. GeoTIFF profiles ndvi_bands (B4+B8) and lst_st_b10 compute NDVI or LST over the
--    province boundary in the validation job already linked to the uploaded file.
-- Ready profiles, prepare and publication keep their reviewed behaviour: band profiles
-- cannot be prepared or published. Nothing here activates editions or touches cache tables.
-- The attested operator supplies BEGIN/runtime proof and the INSERT-only ledger entry.
DO $guard$ BEGIN
 IF current_database() NOT IN ('postgres','gis_t1_upgrade') OR current_setting('cluster_name')<>'green-area-gis-t0'
 OR NOT EXISTS(SELECT 1 FROM gis.schema_migrations WHERE version=48 AND sha256='9ab653c0d4fa1dbe56d7b845a5352d2c86e24187bdc4f72bf4a9cd966206deeb')
 OR EXISTS(SELECT 1 FROM gis.schema_migrations WHERE version>=49)
 OR NOT EXISTS(SELECT 1 FROM gis.environment WHERE singleton AND NOT activation_enabled
 AND runtime_instance=current_setting('gis.runtime_instance',true) AND baseline_fingerprint=current_setting('gis.baseline_fingerprint',true))
 THEN RAISE EXCEPTION 'GIS_LOCAL_BASELINE_048_REQUIRED';END IF;
END $guard$;
GRANT CREATE ON SCHEMA public TO gis_owner;
SET LOCAL ROLE gis_owner;
SELECT gis.assert_environment();

-- Declarations --------------------------------------------------------------------------
CREATE TABLE gis.upload_declarations(
 edition_id uuid PRIMARY KEY REFERENCES gis.editions(id),
 source_label text NOT NULL CHECK(length(btrim(source_label)) BETWEEN 1 AND 255 AND source_label !~ '[[:cntrl:]]'),
 acquisition_date date,
 declared_by uuid REFERENCES public.profiles(id) ON DELETE SET NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp());
ALTER TABLE gis.upload_declarations ENABLE ROW LEVEL SECURITY;
ALTER TABLE gis.upload_declarations FORCE ROW LEVEL SECURITY;
CREATE POLICY owner_access ON gis.upload_declarations TO gis_owner USING(true) WITH CHECK(true);
REVOKE ALL ON gis.upload_declarations FROM PUBLIC,anon,authenticated,service_role,gis_worker,gis_native_worker;

CREATE FUNCTION gis.guard_upload_declaration() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'GIS_HARD_DELETE_FORBIDDEN'; END IF;
 IF NOT(pg_trigger_depth()>1 AND NEW.declared_by IS NULL
   AND (to_jsonb(NEW)-'declared_by')=(to_jsonb(OLD)-'declared_by')) THEN RAISE EXCEPTION 'GIS_UPLOAD_IMMUTABLE'; END IF;
 RETURN NEW;
END $f$;
CREATE TRIGGER immutable_upload_declaration BEFORE UPDATE OR DELETE ON gis.upload_declarations
 FOR EACH ROW EXECUTE FUNCTION gis.guard_upload_declaration();

CREATE FUNCTION gis.upload_declaration_row(p_edition uuid) RETURNS jsonb
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
 SELECT jsonb_build_object('source_label',(SELECT source_label FROM gis.upload_declarations WHERE edition_id=p_edition),
  'acquisition_date',(SELECT acquisition_date FROM gis.upload_declarations WHERE edition_id=p_edition))
$f$;

-- First declaration wins. The same file and key can repeat it but cannot change it.
CREATE FUNCTION gis.upload_declare(p_edition uuid,p_source jsonb,p_date jsonb,p_actor uuid) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE source_value text; date_value date; old gis.upload_declarations%ROWTYPE; d gis.datasets%ROWTYPE;
BEGIN
 IF jsonb_typeof(p_source) IS DISTINCT FROM 'string' OR length(btrim(p_source#>>'{}')) NOT BETWEEN 1 AND 255
 OR (p_source#>>'{}') ~ '[[:cntrl:]]' THEN RAISE EXCEPTION 'GIS_UPLOAD_SOURCE_REQUIRED'; END IF;
 source_value:=btrim(p_source#>>'{}');
 SELECT ds.* INTO d FROM gis.editions e JOIN gis.datasets ds ON ds.id=e.dataset_id WHERE e.id=p_edition;
 IF d.kind='geotiff' THEN
   IF jsonb_typeof(p_date) IS DISTINCT FROM 'string' OR COALESCE(p_date#>>'{}','') !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$' THEN RAISE EXCEPTION 'GIS_UPLOAD_DATE_REQUIRED'; END IF;
   BEGIN date_value:=(p_date#>>'{}')::date; EXCEPTION WHEN datetime_field_overflow OR invalid_datetime_format THEN RAISE EXCEPTION 'GIS_UPLOAD_DATE_REQUIRED'; END;
   IF to_char(date_value,'YYYY-MM-DD')<>(p_date#>>'{}') OR date_value>(clock_timestamp() AT TIME ZONE 'UTC')::date
   OR extract(year FROM date_value)::integer<>d.data_year OR (d.month<>0 AND extract(month FROM date_value)::integer<>d.month) THEN
     RAISE EXCEPTION 'GIS_UPLOAD_DATE_OUTSIDE_PERIOD'; END IF;
 ELSIF p_date IS NOT NULL AND p_date<>'null'::jsonb THEN RAISE EXCEPTION 'GIS_INVALID_PAYLOAD'; END IF;
 SELECT * INTO old FROM gis.upload_declarations WHERE edition_id=p_edition;
 IF FOUND THEN
   IF old.source_label IS DISTINCT FROM source_value OR old.acquisition_date IS DISTINCT FROM date_value THEN RAISE EXCEPTION 'GIS_UPLOAD_DECLARATION_CONFLICT'; END IF;
 ELSE
   INSERT INTO gis.upload_declarations(edition_id,source_label,acquisition_date,declared_by) VALUES(p_edition,source_value,date_value,p_actor);
 END IF;
END $f$;

ALTER FUNCTION gis.ldd_command(uuid,uuid,text,jsonb,boolean) RENAME TO u049_previous_ldd_command;
CREATE FUNCTION gis.ldd_command(p_actor uuid,p_request_id uuid,p_operation text,p_payload jsonb,p_backend_sandbox boolean)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE value jsonb; edition uuid;
BEGIN
 IF p_operation IS DISTINCT FROM 'upload' THEN RETURN gis.u049_previous_ldd_command(p_actor,p_request_id,p_operation,p_payload,p_backend_sandbox); END IF;
 value:=gis.u049_previous_ldd_command(p_actor,p_request_id,p_operation,p_payload-'source_label',p_backend_sandbox);
 edition:=(value->'body'->>'edition_id')::uuid;
 PERFORM gis.upload_declare(edition,p_payload->'source_label',NULL,p_actor);
 RETURN jsonb_set(value,'{body}',(value->'body')||gis.upload_declaration_row(edition));
END $f$;

CREATE OR REPLACE FUNCTION public.gis_ldd_read(p_actor uuid,p_upload_id uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE u gis.ldd_uploads%ROWTYPE; result_value jsonb;
BEGIN
 PERFORM gis.authorize(p_actor,false);
 SELECT * INTO u FROM gis.ldd_uploads WHERE id=p_upload_id;
 IF NOT FOUND THEN RAISE EXCEPTION 'GIS_NOT_FOUND'; END IF;
 SELECT gis.ldd_upload_row(u)||gis.upload_declaration_row(u.edition_id)||jsonb_build_object('state',e.state,'input_revision',e.input_revision,'input_hash',e.input_hash)
   INTO result_value FROM gis.editions e WHERE e.id=u.edition_id;
 RETURN result_value;
END $f$;

-- Edition reads show the declaration beside the upload the page already displays.
ALTER FUNCTION gis.api_read_row(text,jsonb) RENAME TO u049_previous_api_read_row;
CREATE FUNCTION gis.api_read_row(p_kind text,p_row jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE value jsonb;
BEGIN
 value:=gis.u049_previous_api_read_row(p_kind,p_row);
 IF p_kind IN ('editions','edition') AND value ? 'upload' THEN
   value:=jsonb_set(value,'{upload}',(value->'upload')||gis.upload_declaration_row((p_row->>'id')::uuid));
 END IF;
 RETURN value;
END $f$;

-- GeoTIFF band profiles -----------------------------------------------------------------
ALTER TABLE gis.geotiff_uploads DROP CONSTRAINT geotiff_uploads_profile_check;
ALTER TABLE gis.geotiff_uploads ADD CONSTRAINT geotiff_uploads_profile_check
 CHECK(profile IN ('ndvi_ready','lst_celsius_ready','lst_kelvin_ready','ndvi_bands','lst_st_b10'));
ALTER TABLE gis.geotiff_uploads DROP CONSTRAINT geotiff_uploads_check;
ALTER TABLE gis.geotiff_uploads ADD CONSTRAINT geotiff_uploads_check
 CHECK(metric=CASE WHEN profile IN ('ndvi_ready','ndvi_bands') THEN 'ndvi' ELSE 'lst' END);

-- Ready profiles build the exact same manifest as before.
CREATE OR REPLACE FUNCTION gis.geotiff_manifest(p_upload gis.geotiff_uploads) RETURNS jsonb
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
 SELECT jsonb_build_object('schema_version',4,'provider','local_geotiff','provenance','local-geotiff-upload-v1',
  'sha256',(p_upload).sha256,'byte_size',(p_upload).byte_size,'crs',(p_upload).crs,'data_kind','raster',
  'profile',(p_upload).profile,'metric',(p_upload).metric,
  'bands',CASE (p_upload).profile WHEN 'ndvi_bands' THEN jsonb_build_array('B4','B8') WHEN 'lst_st_b10' THEN jsonb_build_array('ST_B10')
    ELSE jsonb_build_array(CASE WHEN (p_upload).metric='ndvi' THEN 'NDVI' ELSE 'LST' END) END,
  'units',CASE (p_upload).profile WHEN 'ndvi_ready' THEN 'unitless' WHEN 'lst_celsius_ready' THEN 'celsius' WHEN 'lst_kelvin_ready' THEN 'kelvin'
    WHEN 'ndvi_bands' THEN 'reflectance' ELSE 'landsat_c2_l2_dn' END)
$f$;

CREATE OR REPLACE FUNCTION gis.a62_previous_manifest_hash(p_manifest jsonb) RETURNS text
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
   OR COALESCE(p_manifest->>'profile','') NOT IN ('ndvi_ready','lst_celsius_ready','lst_kelvin_ready','ndvi_bands','lst_st_b10') THEN
   RAISE EXCEPTION 'GIS_INVALID_GEOTIFF_MANIFEST'; END IF;
 u.sha256:=p_manifest->>'sha256';u.byte_size:=(p_manifest->>'byte_size')::bigint;u.crs:=p_manifest->>'crs';u.profile:=p_manifest->>'profile';
 u.metric:=CASE WHEN u.profile IN ('ndvi_ready','ndvi_bands') THEN 'ndvi' ELSE 'lst' END;
 IF p_manifest IS DISTINCT FROM gis.geotiff_manifest(u) THEN RAISE EXCEPTION 'GIS_INVALID_GEOTIFF_MANIFEST'; END IF;
 RETURN encode(sha256(convert_to(p_manifest::text,'UTF8')),'hex');
END $f$;

-- Current command body; only the profile lists and metric mapping differ.
CREATE OR REPLACE FUNCTION gis.geotiff_command(p_actor uuid,p_request_id uuid,p_operation text,p_payload jsonb,p_backend_sandbox boolean)
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
   IF COALESCE(p_payload->>'profile','') NOT IN ('ndvi_ready','lst_celsius_ready','lst_kelvin_ready','ndvi_bands','lst_st_b10')
     OR COALESCE(p_payload->>'crs','') NOT IN ('EPSG:32647','EPSG:32648','EPSG:4326') THEN RAISE EXCEPTION 'GIS_INVALID_PAYLOAD'; END IF;
   IF d.kind<>'geotiff' OR d.purpose IS DISTINCT FROM (CASE WHEN p_payload->>'profile' IN ('ndvi_ready','ndvi_bands') THEN 'ndvi' ELSE 'lst' END) THEN RAISE EXCEPTION 'GIS_GEOTIFF_DATASET_REQUIRED'; END IF;
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
   IF d.kind<>'geotiff' OR d.purpose IS DISTINCT FROM (CASE WHEN p_payload->>'profile' IN ('ndvi_ready','ndvi_bands') THEN 'ndvi' ELSE 'lst' END) THEN RAISE EXCEPTION 'GIS_GEOTIFF_DATASET_REQUIRED'; END IF;
   IF p_payload->'expected_revision' IS DISTINCT FROM to_jsonb(d.revision) THEN RAISE EXCEPTION 'GIS_REVISION_CONFLICT'; END IF;
   IF jsonb_typeof(p_payload->'sha256') IS DISTINCT FROM 'string' OR p_payload->>'sha256' !~ '^[0-9a-f]{64}$'
     OR jsonb_typeof(p_payload->'byte_size') IS DISTINCT FROM 'number' OR COALESCE(p_payload->>'byte_size','') !~ '^[0-9]{1,8}$'
     OR (p_payload->>'byte_size')::bigint NOT BETWEEN 1 AND 20971520
     OR p_payload->>'crs' IS NULL OR p_payload->>'crs' NOT IN ('EPSG:32647','EPSG:32648','EPSG:4326')
     OR COALESCE(p_payload->>'profile','') NOT IN ('ndvi_ready','lst_celsius_ready','lst_kelvin_ready','ndvi_bands','lst_st_b10')
     OR p_payload->>'upload_id' IS NULL THEN RAISE EXCEPTION 'GIS_INVALID_PAYLOAD'; END IF;
   SELECT * INTO u FROM gis.geotiff_uploads WHERE dataset_id=d.id AND sha256=p_payload->>'sha256'
     AND crs=p_payload->>'crs' AND profile=p_payload->>'profile';
   IF FOUND THEN
     body_value:=gis.geotiff_upload_row(u);
   ELSE
     new_upload.id:=(p_payload->>'upload_id')::uuid;new_upload.dataset_id:=d.id;
     new_upload.sha256:=p_payload->>'sha256';new_upload.byte_size:=(p_payload->>'byte_size')::bigint;
     new_upload.crs:=p_payload->>'crs';new_upload.profile:=p_payload->>'profile';new_upload.metric:=CASE WHEN new_upload.profile IN ('ndvi_ready','ndvi_bands') THEN 'ndvi' ELSE 'lst' END;
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

ALTER FUNCTION gis.geotiff_command(uuid,uuid,text,jsonb,boolean) RENAME TO u049_previous_geotiff_command;
CREATE FUNCTION gis.geotiff_command(p_actor uuid,p_request_id uuid,p_operation text,p_payload jsonb,p_backend_sandbox boolean)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE value jsonb; edition uuid;
BEGIN
 IF p_operation IS DISTINCT FROM 'upload' THEN RETURN gis.u049_previous_geotiff_command(p_actor,p_request_id,p_operation,p_payload,p_backend_sandbox); END IF;
 value:=gis.u049_previous_geotiff_command(p_actor,p_request_id,p_operation,p_payload-'source_label'-'acquisition_date',p_backend_sandbox);
 edition:=(value->'body'->>'edition_id')::uuid;
 PERFORM gis.upload_declare(edition,p_payload->'source_label',p_payload->'acquisition_date',p_actor);
 RETURN jsonb_set(value,'{body}',(value->'body')||gis.upload_declaration_row(edition));
END $f$;

CREATE OR REPLACE FUNCTION public.gis_geotiff_read(p_actor uuid,p_upload_id uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE u gis.geotiff_uploads%ROWTYPE; result_value jsonb;
BEGIN
 PERFORM gis.authorize(p_actor,false);
 SELECT * INTO u FROM gis.geotiff_uploads WHERE id=p_upload_id;
 IF NOT FOUND THEN RAISE EXCEPTION 'GIS_NOT_FOUND'; END IF;
 SELECT gis.geotiff_upload_row(u)||gis.upload_declaration_row(u.edition_id)||jsonb_build_object('state',e.state,'input_revision',e.input_revision,'input_hash',e.input_hash)
   INTO result_value FROM gis.editions e WHERE e.id=u.edition_id;
 RETURN result_value;
END $f$;

-- Band profile computed reports. Ready-profile reports stay on the reviewed validator.
ALTER FUNCTION gis.validate_geotiff_report(jsonb,gis.editions,gis.jobs) RENAME TO u049_ready_validate_geotiff_report;
CREATE FUNCTION gis.validate_geotiff_report(p_report jsonb,p_edition gis.editions,p_job gis.jobs) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE u gis.geotiff_uploads%ROWTYPE; d gis.datasets%ROWTYPE; stats jsonb; meta jsonb; cov jsonb; item jsonb; k text; v jsonb; band_total integer;
 required_checks jsonb:='["source_hash_match","tiff_structure","crs","bands","resolution","dimensions","dtype","nodata","scale_offset","units","coverage","scientific_range","metadata_consistency"]';
 output_low numeric; output_high numeric;
BEGIN
 SELECT * INTO u FROM gis.geotiff_uploads WHERE edition_id=p_edition.id;
 IF u.id IS NULL OR u.profile NOT IN ('ndvi_bands','lst_st_b10') THEN PERFORM gis.u049_ready_validate_geotiff_report(p_report,p_edition,p_job); RETURN; END IF;
 SELECT * INTO d FROM gis.datasets WHERE id=p_edition.dataset_id;
 IF d.kind<>'geotiff' OR d.purpose<>u.metric OR u.dataset_id<>d.id
   OR p_edition.manifest IS DISTINCT FROM gis.geotiff_manifest(u) OR p_edition.input_hash IS DISTINCT FROM gis.manifest_hash(p_edition.manifest)
   OR p_job.kind<>'validate_geotiff_edition' OR p_job.validator_version<>'geotiff-local-v1'
   OR p_job.edition_id<>p_edition.id OR p_job.input_revision<>p_edition.input_revision OR p_job.input_hash<>p_edition.input_hash THEN
   RAISE EXCEPTION 'GIS_GEOTIFF_INPUT_INVARIANT'; END IF;
 PERFORM gis.keys(p_report,ARRAY['schema_version','provider_build','upload_id','artifact_sha256','observed_sha256','byte_size','input_hash','input_revision',
  'province','data_year','valid','checks','errors','warnings','statistics','metadata','error_code','coverage']);
 IF NOT p_report ?& ARRAY['schema_version','provider_build','upload_id','artifact_sha256','observed_sha256','byte_size','input_hash','input_revision',
  'province','data_year','valid','checks','errors','warnings','statistics','metadata','error_code','coverage']
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
 IF jsonb_array_length(p_report->'checks')>13 OR jsonb_array_length(p_report->'errors')>20 OR jsonb_array_length(p_report->'warnings')>20
   OR EXISTS(SELECT 1 FROM jsonb_array_elements(p_report->'checks') x WHERE jsonb_typeof(x)<>'string' OR NOT required_checks @> jsonb_build_array(x))
   OR (SELECT count(*) FROM jsonb_array_elements(p_report->'checks'))<>(SELECT count(DISTINCT x) FROM jsonb_array_elements(p_report->'checks') x) THEN
   RAISE EXCEPTION 'GIS_GEOTIFF_REPORT_INVALID'; END IF;
 FOR item IN SELECT x FROM jsonb_array_elements((p_report->'errors')||(p_report->'warnings')) x LOOP
   PERFORM gis.keys(item,ARRAY['code','count']);
   IF NOT item ?& ARRAY['code','count'] OR jsonb_typeof(item->'code') IS DISTINCT FROM 'string' OR item->>'code' !~ '^[A-Z][A-Z0-9_]{0,59}$'
     OR jsonb_typeof(item->'count') IS DISTINCT FROM 'number' OR COALESCE(item->>'count','') !~ '^[0-9]{1,8}$' THEN RAISE EXCEPTION 'GIS_GEOTIFF_REPORT_INVALID'; END IF;
 END LOOP;
 stats:=p_report->'statistics';meta:=p_report->'metadata';cov:=p_report->'coverage';
 PERFORM gis.keys(stats,ARRAY['width','height','band_count','total_pixels','valid_pixels','nodata_pixels','nonfinite_pixels','outside_area_pixels','mean','min','max']);
 IF NOT stats ?& ARRAY['width','height','band_count','total_pixels','valid_pixels','nodata_pixels','nonfinite_pixels','outside_area_pixels','mean','min','max'] THEN RAISE EXCEPTION 'GIS_GEOTIFF_REPORT_INVALID'; END IF;
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
 IF cov<>'null'::jsonb THEN
   PERFORM gis.keys(cov,ARRAY['mode','boundary_sha256','boundary_approximate','fraction_of_province','fraction_of_file']);
   IF NOT cov ?& ARRAY['mode','boundary_sha256','boundary_approximate','fraction_of_province','fraction_of_file']
     OR cov->>'mode' IS DISTINCT FROM 'province_boundary_clip' OR cov->'boundary_approximate' IS DISTINCT FROM 'true'::jsonb
     OR COALESCE(cov->>'boundary_sha256','') !~ '^[0-9a-f]{64}$'
     OR jsonb_typeof(cov->'fraction_of_province') IS DISTINCT FROM 'number' OR (cov->>'fraction_of_province')::numeric NOT BETWEEN 0 AND 1
     OR jsonb_typeof(cov->'fraction_of_file') IS DISTINCT FROM 'number' OR (cov->>'fraction_of_file')::numeric NOT BETWEEN 0 AND 1 THEN
     RAISE EXCEPTION 'GIS_GEOTIFF_REPORT_INVALID'; END IF;
 END IF;
 IF p_report->'valid'='true'::jsonb THEN
   band_total:=CASE u.profile WHEN 'ndvi_bands' THEN 2 ELSE 1 END;
   output_low:=CASE u.metric WHEN 'ndvi' THEN -1 ELSE -100 END;output_high:=CASE u.metric WHEN 'ndvi' THEN 1 ELSE 100 END;
   IF NOT p_report->'checks' @> required_checks OR jsonb_array_length(p_report->'errors')<>0
     OR p_report->'error_code' IS DISTINCT FROM 'null'::jsonb OR p_report->>'observed_sha256' IS DISTINCT FROM u.sha256
     OR cov='null'::jsonb OR (cov->>'fraction_of_province')::numeric<=0 OR (cov->>'fraction_of_file')::numeric<=0
     OR (stats->>'width')::integer NOT BETWEEN 1 AND 16384 OR (stats->>'height')::integer NOT BETWEEN 1 AND 16384
     OR (stats->>'band_count')::integer<>band_total OR (stats->>'total_pixels')::bigint<>(stats->>'width')::bigint*(stats->>'height')::bigint
     OR (stats->>'total_pixels')::integer>16000000 OR (stats->>'valid_pixels')::integer<1 OR (stats->>'nonfinite_pixels')::integer<>0
     OR (stats->>'valid_pixels')::integer+(stats->>'nodata_pixels')::integer+(stats->>'outside_area_pixels')::integer<>(stats->>'total_pixels')::integer
     OR meta->>'crs' IS DISTINCT FROM u.crs OR meta->'bands' IS DISTINCT FROM p_edition.manifest->'bands'
     OR meta->>'profile' IS DISTINCT FROM u.profile OR meta->>'units' IS DISTINCT FROM p_edition.manifest->>'units'
     OR meta->>'output_units' IS DISTINCT FROM (CASE WHEN u.metric='ndvi' THEN 'unitless' ELSE 'celsius' END)
     OR COALESCE(meta->>'dtype','') NOT IN ('int16','uint16','float32','float64') OR (u.profile='lst_st_b10' AND meta->>'dtype'<>'uint16')
     OR jsonb_typeof(meta->'scales') IS DISTINCT FROM 'array' OR jsonb_array_length(meta->'scales')<>band_total
     OR jsonb_typeof(meta->'offsets') IS DISTINCT FROM 'array' OR jsonb_array_length(meta->'offsets')<>band_total
     OR jsonb_typeof(meta->'nodata') IS DISTINCT FROM 'number'
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

-- A band-profile edition has a computed result, not a publishable prepared raster.
ALTER FUNCTION gis.publication_validation(uuid) RENAME TO u049_previous_publication_validation;
CREATE FUNCTION gis.publication_validation(p_edition uuid) RETURNS jsonb
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
 SELECT CASE WHEN EXISTS(SELECT 1 FROM gis.geotiff_uploads u WHERE u.edition_id=p_edition AND u.profile IN ('ndvi_bands','lst_st_b10'))
   THEN NULL ELSE gis.u049_previous_publication_validation(p_edition) END
$f$;

DO $acl$ DECLARE f record;BEGIN
 FOR f IN SELECT p.oid::regprocedure AS sig FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
 WHERE n.nspname='gis' AND (p.proname IN ('guard_upload_declaration','upload_declaration_row','upload_declare','ldd_command','geotiff_command',
   'geotiff_manifest','a62_previous_manifest_hash','validate_geotiff_report','publication_validation','api_read_row') OR p.proname LIKE 'u049\_%') LOOP
 EXECUTE format('REVOKE ALL ON FUNCTION %s FROM PUBLIC,anon,authenticated,service_role,gis_worker,gis_native_worker,gis_gee_mock_worker,gis_gee_live_worker,gis_gee_safety_worker,gis_gee_transport_recorder,gis_gee_https_worker,gis_gee_https_recorder',f.sig);
 END LOOP;
END $acl$;
RESET ROLE;
REVOKE CREATE ON SCHEMA public FROM gis_owner;
NOTIFY pgrst,'reload schema';
