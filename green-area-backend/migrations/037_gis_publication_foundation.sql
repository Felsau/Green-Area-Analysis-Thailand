-- A1: immutable artifact declarations, NOT prepare/verification/publication.
-- The attested local runner owns BEGIN, exact review, ledger and COMMIT.
GRANT CREATE ON SCHEMA public TO gis_owner;
SET LOCAL ROLE gis_owner;
SELECT gis.assert_environment();
DO $guard$
BEGIN
 IF current_database() NOT IN ('postgres','gis_t1_upgrade')
    OR NOT gis.target_ok()
    OR NOT EXISTS(SELECT 1 FROM gis.environment WHERE singleton
      AND runtime_instance=current_setting('gis.runtime_instance',true)
      AND baseline_fingerprint=current_setting('gis.baseline_fingerprint',true)
      AND activation_enabled=false)
    OR NOT EXISTS(SELECT 1 FROM gis.schema_migrations WHERE version=36
      AND sha256='325e2f2293ddae556ee585fec4a7f45ace883b9931011aa2a95cfc222f28f08b')
    OR EXISTS(SELECT 1 FROM gis.schema_migrations WHERE version>=37) THEN
   RAISE EXCEPTION 'GIS_LOCAL_BASELINE_036_REQUIRED';
 END IF;
END $guard$;

CREATE TABLE gis.publication_artifacts(
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 dataset_id uuid NOT NULL REFERENCES gis.datasets(id),
 edition_id uuid NOT NULL,
 validation_result_id uuid NOT NULL,
 input_revision integer NOT NULL CHECK(input_revision>0),
 input_hash text NOT NULL CHECK(input_hash ~ '^[0-9a-f]{64}$'),
 source_sha256 text NOT NULL CHECK(source_sha256 ~ '^[0-9a-f]{64}$'),
 artifact_kind text NOT NULL CHECK(artifact_kind IN
   ('ldd_geometry','ldd_summary','ndvi_raster','ndvi_summary','lst_raster','lst_summary')),
 artifact_sha256 text NOT NULL CHECK(artifact_sha256 ~ '^[0-9a-f]{64}$'),
 byte_size bigint NOT NULL CHECK(byte_size BETWEEN 1 AND 20971520),
 method_version text NOT NULL CHECK(method_version ~ '^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$'),
 coverage_level text NOT NULL DEFAULT 'province' CHECK(coverage_level='province'),
 coverage_province text NOT NULL REFERENCES public.provinces(name_en),
 verification_state text NOT NULL DEFAULT 'unverified' CHECK(verification_state='unverified'),
 object_key text GENERATED ALWAYS AS ('sha256/'||artifact_sha256||'/'||artifact_kind) STORED,
 registered_by uuid REFERENCES public.profiles(id) ON DELETE SET NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 FOREIGN KEY(edition_id,dataset_id) REFERENCES gis.editions(id,dataset_id),
 FOREIGN KEY(validation_result_id,edition_id) REFERENCES gis.results(id,edition_id),
 UNIQUE(edition_id,artifact_kind,method_version));
CREATE INDEX publication_artifacts_dataset ON gis.publication_artifacts(dataset_id,edition_id);
ALTER TABLE gis.publication_artifacts ENABLE ROW LEVEL SECURITY;
ALTER TABLE gis.publication_artifacts FORCE ROW LEVEL SECURITY;
CREATE POLICY owner_access ON gis.publication_artifacts TO gis_owner USING(true) WITH CHECK(true);
REVOKE ALL ON gis.publication_artifacts FROM PUBLIC,anon,authenticated,service_role,gis_worker,gis_native_worker;

-- Report-based validation also supports GeoTIFF's intentionally draft Edition.
-- No synthetic fixture or offline processing result can stand for real input.
CREATE FUNCTION gis.publication_validation(p_edition uuid) RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE e gis.editions%ROWTYPE; d gis.datasets%ROWTYPE; r gis.results%ROWTYPE;
 j gis.jobs%ROWTYPE; a gis.attempts%ROWTYPE; source_hash text;
BEGIN
 PERFORM gis.assert_environment();
 SELECT * INTO e FROM gis.editions WHERE id=p_edition;
 IF NOT FOUND OR e.state IN ('validating','withdrawn')
    OR EXISTS(SELECT 1 FROM gis.jobs WHERE edition_id=e.id AND state IN ('queued','running')) THEN RETURN NULL; END IF;
 SELECT * INTO d FROM gis.datasets WHERE id=e.dataset_id;
 SELECT result.* INTO r FROM gis.results result JOIN gis.jobs job ON job.id=result.job_id
   JOIN gis.attempts attempt ON attempt.job_id=job.id AND attempt.attempt_no=job.attempt_count
   WHERE result.edition_id=e.id AND result.valid
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

CREATE FUNCTION gis.guard_publication_artifact() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE v jsonb; d gis.datasets%ROWTYPE;
BEGIN
 PERFORM gis.assert_environment();
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'GIS_ARTIFACT_IMMUTABLE'; END IF;
 IF TG_OP='UPDATE' THEN
   IF NEW.registered_by IS NULL AND OLD.registered_by IS NOT NULL AND pg_trigger_depth()>1
      AND (to_jsonb(NEW)-'registered_by'-'object_key')=(to_jsonb(OLD)-'registered_by'-'object_key') THEN RETURN NEW; END IF;
   RAISE EXCEPTION 'GIS_ARTIFACT_IMMUTABLE';
 END IF;
 SELECT * INTO d FROM gis.datasets WHERE id=NEW.dataset_id FOR NO KEY UPDATE;
 PERFORM id FROM gis.editions WHERE id=NEW.edition_id AND dataset_id=d.id FOR UPDATE;
 v:=gis.publication_validation(NEW.edition_id);
 IF v IS NULL OR v->>'dataset_id' IS DISTINCT FROM NEW.dataset_id::text
    OR v->>'validation_result_id' IS DISTINCT FROM NEW.validation_result_id::text
    OR (v->>'input_revision')::integer IS DISTINCT FROM NEW.input_revision
    OR v->>'input_hash' IS DISTINCT FROM NEW.input_hash
    OR v->>'source_sha256' IS DISTINCT FROM NEW.source_sha256
    OR d.province IS DISTINCT FROM NEW.coverage_province
    OR NEW.artifact_kind<>ALL(CASE d.purpose WHEN 'landuse' THEN ARRAY['ldd_geometry','ldd_summary']
      WHEN 'ndvi' THEN ARRAY['ndvi_raster','ndvi_summary'] WHEN 'lst' THEN ARRAY['lst_raster','lst_summary'] END) THEN
   RAISE EXCEPTION 'GIS_ARTIFACT_INPUT_MISMATCH';
 END IF;
 RETURN NEW;
END $f$;
CREATE TRIGGER immutable_publication_artifact BEFORE INSERT OR UPDATE OR DELETE ON gis.publication_artifacts
 FOR EACH ROW EXECUTE FUNCTION gis.guard_publication_artifact();

CREATE FUNCTION gis.publication_status(p_edition uuid,p_method_version text) RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE e gis.editions%ROWTYPE; d gis.datasets%ROWTYPE; v jsonb; required text[]; missing text[]; rows jsonb;
BEGIN
 PERFORM gis.assert_environment();
 IF p_method_version IS NULL OR p_method_version !~ '^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$' THEN
   RAISE EXCEPTION 'GIS_PUBLICATION_METHOD_REQUIRED'; END IF;
 SELECT * INTO e FROM gis.editions WHERE id=p_edition;
 IF NOT FOUND THEN RAISE EXCEPTION 'GIS_NOT_FOUND'; END IF;
 SELECT * INTO d FROM gis.datasets WHERE id=e.dataset_id;
 v:=gis.publication_validation(e.id);
 required:=CASE d.purpose WHEN 'landuse' THEN ARRAY['ldd_geometry','ldd_summary']
   WHEN 'ndvi' THEN ARRAY['ndvi_raster','ndvi_summary'] ELSE ARRAY['lst_raster','lst_summary'] END;
 SELECT COALESCE(array_agg(k ORDER BY k),ARRAY[]::text[]) INTO missing FROM unnest(required) k
   WHERE NOT EXISTS(SELECT 1 FROM gis.publication_artifacts a WHERE a.edition_id=e.id
     AND a.method_version=p_method_version AND a.artifact_kind=k
     AND a.validation_result_id=(v->>'validation_result_id')::uuid
     AND a.input_hash=e.input_hash AND a.input_revision=e.input_revision);
 SELECT COALESCE(jsonb_agg(to_jsonb(a)-'registered_by' ORDER BY a.artifact_kind),'[]'::jsonb) INTO rows
   FROM gis.publication_artifacts a WHERE a.edition_id=e.id AND a.method_version=p_method_version;
 RETURN jsonb_build_object('contract_version','1.0.0-a1','dataset_id',d.id,'edition_id',e.id,
   'edition_state',e.state,'validation_valid',v IS NOT NULL,
   'source_identity',CASE WHEN v IS NULL THEN NULL ELSE
     (v-'kind'-'purpose'-'input_revision')||jsonb_build_object('namespace','published','scope','province',
       'product',d.purpose,'method_version',p_method_version) END,
   'coverage',jsonb_build_object('level','province','province',d.province,'verified',false),
   'method_version',p_method_version,'required_artifacts',required,'missing_artifacts',missing,'artifacts',rows,
   'artifacts_complete',v IS NOT NULL AND cardinality(missing)=0,
   'verification_available',false,'coverage_verified',false,'ready_for_publication',false,
   'status',CASE WHEN v IS NULL THEN 'validation_required' WHEN cardinality(missing)>0 THEN 'artifacts_required'
     ELSE 'registered_unverified' END,'blocker','A1_TRUSTED_ARTIFACT_VERIFIER_NOT_IMPLEMENTED');
END $f$;

-- Fail closed intentionally: A1 has no trusted file/coverage verifier. A2/A4
-- must add one through independently reviewed forward SQL before readiness.
CREATE FUNCTION gis.publication_ready(p_edition uuid,p_dataset uuid) RETURNS boolean
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
BEGIN
 PERFORM gis.assert_environment();
 RETURN false;
END $f$;
CREATE FUNCTION gis.guard_publication_pointer() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
BEGIN
 IF NEW.active_edition_id IS DISTINCT FROM OLD.active_edition_id AND NEW.active_edition_id IS NOT NULL
    AND NOT gis.publication_ready(NEW.active_edition_id,NEW.id) THEN
   RAISE EXCEPTION 'GIS_PUBLICATION_NOT_READY'; END IF;
 RETURN NEW;
END $f$;
-- immutable_row sorts first, so the existing closed-gate rejection is retained.
CREATE TRIGGER publication_pointer_guard BEFORE UPDATE OF active_edition_id ON gis.datasets
 FOR EACH ROW EXECUTE FUNCTION gis.guard_publication_pointer();

CREATE FUNCTION gis.publication_register(p_actor uuid,p_request_id uuid,p_payload jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE v jsonb; d gis.datasets%ROWTYPE; e gis.editions%ROWTYPE; a gis.publication_artifacts%ROWTYPE;
 receipt gis.receipts%ROWTYPE; digest text; reason_value text; body_value jsonb;
BEGIN
 PERFORM gis.authorize(p_actor,true);
 IF p_request_id IS NULL THEN RAISE EXCEPTION 'GIS_REQUEST_ID_REQUIRED'; END IF;
 PERFORM gis.keys(p_payload,ARRAY['edition_id','expected_dataset_revision','expected_input_revision','input_hash',
   'validation_result_id','source_sha256','artifact_kind','artifact_sha256','byte_size','method_version','reason']);
 IF NOT p_payload ?& ARRAY['edition_id','expected_dataset_revision','expected_input_revision','input_hash',
   'validation_result_id','source_sha256','artifact_kind','artifact_sha256','byte_size','method_version','reason'] THEN
   RAISE EXCEPTION 'GIS_INVALID_PAYLOAD'; END IF;
 reason_value:=btrim(p_payload->>'reason');
 IF jsonb_typeof(p_payload->'reason') IS DISTINCT FROM 'string' OR length(reason_value) NOT BETWEEN 1 AND 500 THEN
   RAISE EXCEPTION 'GIS_REASON_REQUIRED'; END IF;
 IF jsonb_typeof(p_payload->'expected_dataset_revision') IS DISTINCT FROM 'number'
    OR jsonb_typeof(p_payload->'expected_input_revision') IS DISTINCT FROM 'number'
    OR jsonb_typeof(p_payload->'byte_size') IS DISTINCT FROM 'number'
    OR p_payload->>'expected_dataset_revision' !~ '^[1-9][0-9]{0,8}$'
    OR p_payload->>'expected_input_revision' !~ '^[1-9][0-9]{0,8}$'
    OR p_payload->>'byte_size' !~ '^[1-9][0-9]{0,8}$' THEN RAISE EXCEPTION 'GIS_INVALID_PAYLOAD'; END IF;
 digest:=encode(sha256(convert_to(p_payload::text,'UTF8')),'hex');
 PERFORM pg_advisory_xact_lock(hashtextextended(p_actor::text||':'||p_request_id::text,0));
 PERFORM gis.authorize(p_actor,true);
 SELECT * INTO receipt FROM gis.receipts WHERE actor_id=p_actor AND request_id=p_request_id;
 IF FOUND THEN
   IF receipt.operation<>'publication.register' OR receipt.payload_hash<>digest THEN RAISE EXCEPTION 'GIS_IDEMPOTENCY_CONFLICT'; END IF;
   RETURN jsonb_build_object('status',receipt.status,'body',receipt.body);
 END IF;
 SELECT * INTO e FROM gis.editions WHERE id=(p_payload->>'edition_id')::uuid;
 IF NOT FOUND THEN RAISE EXCEPTION 'GIS_NOT_FOUND'; END IF;
 SELECT * INTO d FROM gis.datasets WHERE id=e.dataset_id FOR NO KEY UPDATE;
 SELECT * INTO e FROM gis.editions WHERE id=e.id FOR UPDATE;
 IF d.revision IS DISTINCT FROM (p_payload->>'expected_dataset_revision')::integer
    OR e.input_revision IS DISTINCT FROM (p_payload->>'expected_input_revision')::integer THEN
   RAISE EXCEPTION 'GIS_REVISION_CONFLICT'; END IF;
 v:=gis.publication_validation(e.id);
 IF v IS NULL THEN RAISE EXCEPTION 'GIS_PUBLICATION_VALIDATION_REQUIRED'; END IF;
 IF v->>'input_hash' IS DISTINCT FROM p_payload->>'input_hash'
    OR v->>'source_sha256' IS DISTINCT FROM p_payload->>'source_sha256'
    OR v->>'validation_result_id' IS DISTINCT FROM p_payload->>'validation_result_id' THEN
   RAISE EXCEPTION 'GIS_ARTIFACT_INPUT_MISMATCH'; END IF;
 IF EXISTS(SELECT 1 FROM gis.publication_artifacts WHERE edition_id=e.id
    AND artifact_kind=p_payload->>'artifact_kind' AND method_version=p_payload->>'method_version') THEN
   RAISE EXCEPTION 'GIS_ARTIFACT_ALREADY_REGISTERED'; END IF;
 INSERT INTO gis.publication_artifacts(dataset_id,edition_id,validation_result_id,input_revision,input_hash,
   source_sha256,artifact_kind,artifact_sha256,byte_size,method_version,coverage_province,registered_by)
 VALUES(d.id,e.id,(v->>'validation_result_id')::uuid,e.input_revision,e.input_hash,v->>'source_sha256',
   p_payload->>'artifact_kind',p_payload->>'artifact_sha256',(p_payload->>'byte_size')::bigint,
   p_payload->>'method_version',d.province,p_actor) RETURNING * INTO a;
 body_value:=to_jsonb(a)-'registered_by';
 PERFORM gis.authorize(p_actor,true);
 INSERT INTO gis.audit(actor_id,operation,dataset_id,edition_id,reason,detail)
   VALUES(p_actor,'publication.register',d.id,e.id,reason_value,
     jsonb_build_object('artifact_id',a.id,'artifact_sha256',a.artifact_sha256,'method_version',a.method_version));
 INSERT INTO gis.receipts(actor_id,request_id,operation,payload_hash,status,body)
   VALUES(p_actor,p_request_id,'publication.register',digest,201,body_value);
 RETURN jsonb_build_object('status',201,'body',body_value);
END $f$;

CREATE FUNCTION public.gis_publication_register(p_actor uuid,p_request_id uuid,p_payload jsonb) RETURNS jsonb
LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,gis
AS $f$ SELECT gis.publication_register(p_actor,p_request_id,p_payload) $f$;
CREATE FUNCTION public.gis_publication_read(p_actor uuid,p_edition uuid,p_method_version text) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
BEGIN
 PERFORM gis.authorize(p_actor,false);
 RETURN gis.publication_status(p_edition,p_method_version);
END $f$;

REVOKE ALL ON FUNCTION gis.publication_validation(uuid),gis.guard_publication_artifact(),
 gis.publication_status(uuid,text),gis.publication_ready(uuid,uuid),gis.guard_publication_pointer(),
 gis.publication_register(uuid,uuid,jsonb) FROM PUBLIC,anon,authenticated,service_role,gis_worker,gis_native_worker;
REVOKE ALL ON FUNCTION public.gis_publication_register(uuid,uuid,jsonb),public.gis_publication_read(uuid,uuid,text)
 FROM PUBLIC,anon,authenticated,service_role,gis_worker,gis_native_worker;
GRANT EXECUTE ON FUNCTION public.gis_publication_register(uuid,uuid,jsonb),public.gis_publication_read(uuid,uuid,text) TO service_role;
RESET ROLE;
REVOKE CREATE ON SCHEMA public FROM gis_owner;
