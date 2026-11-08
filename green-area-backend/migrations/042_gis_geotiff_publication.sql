-- A4.2: Local uploaded ready-profile GeoTIFF only, broad gate remains closed.
GRANT CREATE ON SCHEMA public TO gis_owner;
SET LOCAL ROLE gis_owner;
SELECT gis.assert_environment();
DO $guard$ BEGIN
 IF current_database() NOT IN ('postgres','gis_t1_upgrade') OR NOT gis.target_ok()
 OR NOT EXISTS(SELECT 1 FROM gis.environment WHERE singleton AND NOT activation_enabled
   AND runtime_instance=current_setting('gis.runtime_instance',true) AND baseline_fingerprint=current_setting('gis.baseline_fingerprint',true))
 OR NOT EXISTS(SELECT 1 FROM gis.schema_migrations WHERE version=41 AND sha256='fa870b836db27d12af696c43bde60baff9d90458e357ee05f699ce423355171b')
 OR EXISTS(SELECT 1 FROM gis.schema_migrations WHERE version>=42) THEN RAISE EXCEPTION 'GIS_LOCAL_BASELINE_041_REQUIRED'; END IF;
END $guard$;

-- Acceptance records informed Local use, never verified observation dates or
-- complete provincial coverage. Actual byte verification remains independent.
CREATE TABLE gis.geotiff_publication_acceptances(
 certificate_id uuid PRIMARY KEY REFERENCES gis.geotiff_prepare_certificates(id),
 identity jsonb NOT NULL CHECK(jsonb_typeof(identity)='object'),
 accepted_by uuid NOT NULL,
 reason text NOT NULL CHECK(length(btrim(reason)) BETWEEN 1 AND 500),
 accepted_at timestamptz NOT NULL DEFAULT clock_timestamp());
ALTER TABLE gis.geotiff_publication_acceptances ENABLE ROW LEVEL SECURITY;
ALTER TABLE gis.geotiff_publication_acceptances FORCE ROW LEVEL SECURITY;
CREATE POLICY owner_access ON gis.geotiff_publication_acceptances TO gis_owner USING(true) WITH CHECK(true);
REVOKE ALL ON gis.geotiff_publication_acceptances FROM PUBLIC,anon,authenticated,service_role,gis_worker,gis_native_worker;
CREATE TRIGGER immutable_acceptance BEFORE UPDATE OR DELETE ON gis.geotiff_publication_acceptances
 FOR EACH ROW EXECUTE FUNCTION gis.geotiff_prepare_immutable();

CREATE FUNCTION gis.assert_geotiff_publication() RETURNS void
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
BEGIN
 PERFORM gis.assert_environment();
 IF current_database() NOT IN ('postgres','gis_t1_upgrade') OR NOT gis.target_ok()
 OR NOT EXISTS(SELECT 1 FROM gis.environment WHERE singleton AND NOT activation_enabled)
 OR NOT EXISTS(SELECT 1 FROM gis.schema_migrations WHERE version=42) THEN RAISE EXCEPTION 'GIS_GEOTIFF_PUBLICATION_DISABLED'; END IF;
END $f$;

CREATE FUNCTION gis.geotiff_publication_identity(p_certificate uuid) RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE c gis.geotiff_prepare_certificates%ROWTYPE; e gis.editions%ROWTYPE; d gis.datasets%ROWTYPE; r gis.results%ROWTYPE;
BEGIN
 SELECT * INTO c FROM gis.geotiff_prepare_certificates WHERE id=p_certificate;
 SELECT * INTO e FROM gis.editions WHERE id=c.edition_id;
 SELECT * INTO d FROM gis.datasets WHERE id=e.dataset_id;
 SELECT * INTO r FROM gis.results WHERE job_id=c.job_id;
 IF c.id IS NULL OR d.kind<>'geotiff' OR d.purpose NOT IN ('ndvi','lst') OR e.manifest->>'crs'<>'EPSG:4326'
 OR e.manifest->>'profile' NOT IN ('ndvi_ready','lst_celsius_ready','lst_kelvin_ready')
 OR e.manifest->>'metric' IS DISTINCT FROM d.purpose OR e.validated_result_id IS NOT NULL
 OR r.provider IS DISTINCT FROM 'local_geotiff_prepare' OR NOT r.valid THEN RETURN NULL; END IF;
 RETURN jsonb_build_object('dataset_id',d.id,'edition_id',e.id,'validation_result_id',c.validation_result_id,
  'certificate_id',c.id,'input_revision',e.input_revision,'input_hash',e.input_hash,'source_sha256',e.manifest->>'sha256',
  'province',d.province,'data_year',d.data_year,'month',d.month,'product',d.purpose,'profile',e.manifest->>'profile',
  'method_version','geotiff-grid-celsius-v1','coverage_mode','source_footprint_intersection','period_verified',false,
  'complete_province_inventory',false,'crs','EPSG:4326','output_units',CASE WHEN d.purpose='ndvi' THEN 'unitless' ELSE 'celsius' END,
  'policy_version','local-declared-period-footprint-v1','artifacts',r.report->'artifacts');
END $f$;

CREATE FUNCTION gis.check_geotiff_acceptance() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
BEGIN
 IF NEW.identity IS DISTINCT FROM gis.geotiff_publication_identity(NEW.certificate_id)
 OR NOT EXISTS(SELECT 1 FROM public.profiles WHERE id=NEW.accepted_by AND role='admin') THEN
  RAISE EXCEPTION 'GIS_PREPARE_PROOF_INVALID'; END IF;
 RETURN NULL;
END $f$;
CREATE CONSTRAINT TRIGGER geotiff_acceptance_integrity AFTER INSERT ON gis.geotiff_publication_acceptances
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION gis.check_geotiff_acceptance();

CREATE FUNCTION gis.geotiff_publication_ready(p_edition uuid,p_dataset uuid) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
 SELECT EXISTS(SELECT 1 FROM gis.editions e JOIN gis.datasets d ON d.id=e.dataset_id
 JOIN gis.geotiff_prepare_certificates c ON c.edition_id=e.id
 JOIN gis.geotiff_publication_acceptances a ON a.certificate_id=c.id
 WHERE e.id=p_edition AND d.id=p_dataset AND e.state='draft' AND e.validated_result_id IS NULL
 AND a.identity=gis.geotiff_publication_identity(c.id)
 AND c.validation_result_id::text=gis.publication_validation(e.id)->>'validation_result_id'
 AND NOT EXISTS(SELECT 1 FROM gis.geotiff_prepare_revocations WHERE certificate_id=c.id)
 AND gis.geotiff_prepared_ready(e.id,d.id))
$f$;

CREATE FUNCTION gis.geotiff_transition_authorized(p_dataset uuid,p_old uuid,p_new uuid,p_old_revision integer,p_new_revision integer) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
 SELECT EXISTS(SELECT 1 FROM gis.datasets d JOIN gis.audit a ON a.dataset_id=d.id
 WHERE d.id=p_dataset AND d.kind='geotiff' AND d.purpose IN ('ndvi','lst') AND p_new_revision=p_old_revision+1
 AND a.operation IN ('geotiff.activate','geotiff.rollback','geotiff.withdraw')
 AND a.detail->>'transaction_id'=txid_current()::text
 AND a.detail->'previous_edition_id'=COALESCE(to_jsonb(p_old),'null'::jsonb)
 AND a.detail->'new_edition_id'=COALESCE(to_jsonb(p_new),'null'::jsonb)
 AND a.detail->'previous_revision'=to_jsonb(p_old_revision) AND a.detail->'new_revision'=to_jsonb(p_new_revision)
 AND a.detail->>'policy_version'='local-declared-period-footprint-v1')
$f$;

CREATE FUNCTION gis.geotiff_withdrawal_authorized(p_edition uuid) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
 SELECT EXISTS(SELECT 1 FROM gis.audit a JOIN gis.editions e ON e.id=a.edition_id
 JOIN gis.geotiff_prepare_certificates c ON c.edition_id=e.id AND c.id::text=a.detail->>'retired_certificate_id'
 WHERE e.id=p_edition AND a.operation='geotiff.withdraw' AND a.dataset_id=e.dataset_id
 AND a.detail->>'retired_input_hash'=e.input_hash AND a.detail->>'policy_version'='local-declared-period-footprint-v1')
$f$;

-- Narrow replacements below are generated from the exact committed predecessor
-- bodies, retaining every non-GeoTIFF branch (see independent SQL review).
CREATE OR REPLACE FUNCTION gis.eligible(p_edition uuid,p_dataset uuid) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
 SELECT CASE WHEN EXISTS(SELECT 1 FROM gis.editions WHERE id=p_edition AND manifest->'schema_version'='4'::jsonb)
   THEN gis.geotiff_publication_ready(p_edition,p_dataset) ELSE gis.phase3_eligible(p_edition,p_dataset) END
$f$;

CREATE OR REPLACE FUNCTION gis.publication_ready(p_edition uuid,p_dataset uuid) RETURNS boolean
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE validation jsonb;
BEGIN
 PERFORM gis.assert_environment();
 IF EXISTS(SELECT 1 FROM gis.datasets WHERE id=p_dataset AND kind='geotiff') THEN RETURN gis.geotiff_publication_ready(p_edition,p_dataset); END IF;
 validation:=gis.publication_validation(p_edition);
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

CREATE OR REPLACE FUNCTION gis.guard_ldd_dataset() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'GIS_HARD_DELETE_FORBIDDEN'; END IF;
 IF TG_OP='INSERT' THEN
  IF NEW.data_year>extract(year FROM clock_timestamp())::integer+1 OR NEW.revision<>1 OR NEW.active_edition_id IS NOT NULL THEN
   RAISE EXCEPTION 'GIS_DATASET_INVARIANT'; END IF;
 ELSE
  IF ROW(NEW.id,NEW.province,NEW.data_year,NEW.month,NEW.kind,NEW.purpose,NEW.created_at)
   IS DISTINCT FROM ROW(OLD.id,OLD.province,OLD.data_year,OLD.month,OLD.kind,OLD.purpose,OLD.created_at) THEN
   RAISE EXCEPTION 'GIS_DATASET_IDENTITY_IMMUTABLE'; END IF;
  IF NEW.title IS DISTINCT FROM OLD.title OR NEW.active_edition_id IS DISTINCT FROM OLD.active_edition_id THEN
   IF NEW.revision<>OLD.revision+1 THEN RAISE EXCEPTION 'GIS_REVISION_INVARIANT'; END IF;
  ELSIF NEW.revision NOT IN (OLD.revision,OLD.revision+1) THEN RAISE EXCEPTION 'GIS_REVISION_INVARIANT'; END IF;
  IF NEW.active_edition_id IS DISTINCT FROM OLD.active_edition_id
   AND NOT EXISTS(SELECT 1 FROM gis.environment WHERE singleton AND activation_enabled)
   AND NOT gis.ldd_transition_authorized(NEW.id,OLD.active_edition_id,NEW.active_edition_id,OLD.revision,NEW.revision)
   AND NOT gis.geotiff_transition_authorized(NEW.id,OLD.active_edition_id,NEW.active_edition_id,OLD.revision,NEW.revision) THEN
   RAISE EXCEPTION 'GIS_ACTIVATION_DISABLED'; END IF;
  IF NEW.created_by IS DISTINCT FROM OLD.created_by AND NOT(NEW.created_by IS NULL AND pg_trigger_depth()>1) THEN
   RAISE EXCEPTION 'GIS_ACTOR_IMMUTABLE'; END IF;
 END IF;
 RETURN NEW;
END $f$;

CREATE OR REPLACE FUNCTION gis.check_geotiff_catalog() RETURNS trigger
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
   OR e.validated_result_id IS NOT NULL
   OR (e.state NOT IN ('draft','validating') AND NOT(e.state='withdrawn' AND gis.geotiff_withdrawal_authorized(e.id)))
   OR (d.active_edition_id=e.id AND NOT gis.geotiff_publication_ready(e.id,d.id)) THEN
   RAISE EXCEPTION 'GIS_GEOTIFF_INPUT_INVARIANT'; END IF;
 FOR j IN SELECT * FROM gis.jobs WHERE edition_id=e.id AND kind<>'prepare_geotiff_edition' LOOP
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
     IF j.kind='prepare_geotiff_edition' THEN RETURN NULL; END IF;
     PERFORM gis.validate_geotiff_report(NEW.validation_report,e,j);
     IF NEW.validation_report->'valid' IS DISTINCT FROM 'false'::jsonb THEN RAISE EXCEPTION 'GIS_GEOTIFF_REPORT_INVALID'; END IF;
   END IF;
 END IF;
 RETURN NULL;
END $f$;

CREATE FUNCTION gis.geotiff_publication_command(p_actor uuid,p_request_id uuid,p_operation text,p_payload jsonb,p_proof jsonb,p_backend_local boolean,p_probe boolean) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE d gis.datasets%ROWTYPE; e gis.editions%ROWTYPE; target gis.editions%ROWTYPE;
 history gis.geotiff_prepare_certificates%ROWTYPE; c gis.geotiff_prepare_certificates%ROWTYPE;
 r gis.results%ROWTYPE; receipt gis.receipts%ROWTYPE; identity jsonb; digest text; previous uuid;
 next_pointer uuid; next_revision integer; event_id uuid; body jsonb;
BEGIN
 PERFORM gis.assert_geotiff_publication();PERFORM gis.authorize(p_actor,true);
 IF p_backend_local IS DISTINCT FROM true THEN RAISE EXCEPTION 'GIS_GEOTIFF_PUBLICATION_DISABLED'; END IF;
 IF p_operation NOT IN ('activate','rollback','withdraw') OR p_operation IS NULL THEN RAISE EXCEPTION 'GIS_UNKNOWN_OPERATION'; END IF;
 IF p_request_id IS NULL THEN RAISE EXCEPTION 'GIS_REQUEST_ID_REQUIRED'; END IF;
 PERFORM gis.keys(p_payload,ARRAY['dataset_id','edition_id','expected_dataset_revision','expected_active_edition_id',
  'expected_input_revision','input_hash','validation_result_id','source_sha256','province','data_year','month','product','profile',
  'certificate_id','method_version','coverage_mode','policy_version','acknowledge_unverified_period','acknowledge_limited_coverage','reason','replacement_edition_id']);
 IF NOT p_payload ?& ARRAY['dataset_id','edition_id','expected_dataset_revision','expected_active_edition_id',
  'expected_input_revision','input_hash','validation_result_id','source_sha256','province','data_year','month','product','profile','certificate_id',
  'method_version','coverage_mode','policy_version','acknowledge_unverified_period','acknowledge_limited_coverage','reason']
 OR jsonb_typeof(p_payload->'reason') IS DISTINCT FROM 'string' OR length(btrim(p_payload->>'reason')) NOT BETWEEN 1 AND 500
 OR p_payload->>'method_version' IS DISTINCT FROM 'geotiff-grid-celsius-v1'
 OR p_payload->>'coverage_mode' IS DISTINCT FROM 'source_footprint_intersection'
 OR p_payload->>'policy_version' IS DISTINCT FROM 'local-declared-period-footprint-v1'
 OR p_payload->'acknowledge_unverified_period' IS DISTINCT FROM 'true'::jsonb
 OR p_payload->'acknowledge_limited_coverage' IS DISTINCT FROM 'true'::jsonb THEN RAISE EXCEPTION 'GIS_INVALID_PAYLOAD'; END IF;
 digest:=encode(sha256(convert_to(p_payload::text,'UTF8')),'hex');
 PERFORM pg_advisory_xact_lock(hashtextextended(p_actor::text||':'||p_request_id::text,0));
 PERFORM gis.authorize(p_actor,true);
 SELECT * INTO receipt FROM gis.receipts WHERE actor_id=p_actor AND request_id=p_request_id;
 IF FOUND THEN
  IF receipt.operation<>'geotiff.'||p_operation OR receipt.payload_hash<>digest THEN RAISE EXCEPTION 'GIS_IDEMPOTENCY_CONFLICT'; END IF;
  RETURN jsonb_build_object('status',200,'body',receipt.body||jsonb_build_object('replayed',true,'operation_history',true));
 END IF;
 IF p_probe IS true THEN RETURN jsonb_build_object('status',200,'body',jsonb_build_object('receipt_exists',false)); END IF;
 SELECT * INTO d FROM gis.datasets WHERE id=(p_payload->>'dataset_id')::uuid FOR NO KEY UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'GIS_NOT_FOUND'; END IF;
 IF d.kind<>'geotiff' OR d.purpose NOT IN ('ndvi','lst') THEN RAISE EXCEPTION 'GIS_GEOTIFF_PUBLICATION_UNSUPPORTED'; END IF;
 next_pointer:=CASE WHEN p_operation='withdraw' THEN (p_payload->>'replacement_edition_id')::uuid ELSE (p_payload->>'edition_id')::uuid END;
 IF p_operation='withdraw' AND NOT p_payload ? 'replacement_edition_id' THEN RAISE EXCEPTION 'GIS_EXPECTED_POINTER_REQUIRED'; END IF;
 PERFORM id FROM gis.editions WHERE id=(p_payload->>'edition_id')::uuid OR id=next_pointer ORDER BY id FOR UPDATE;
 SELECT * INTO e FROM gis.editions WHERE id=(p_payload->>'edition_id')::uuid;
 IF NOT FOUND OR e.dataset_id<>d.id THEN RAISE EXCEPTION 'GIS_NOT_FOUND'; END IF;
 SELECT * INTO history FROM gis.geotiff_prepare_certificates WHERE id=(p_payload->>'certificate_id')::uuid AND edition_id=e.id;
 IF history.id IS NULL OR NOT EXISTS(SELECT 1 FROM gis.geotiff_uploads WHERE edition_id=e.id AND dataset_id=d.id) THEN
  RAISE EXCEPTION 'GIS_GEOTIFF_PUBLICATION_UNSUPPORTED'; END IF;
 previous:=d.active_edition_id;
 IF p_payload->'expected_dataset_revision' IS DISTINCT FROM to_jsonb(d.revision)
 OR (p_payload->>'expected_active_edition_id')::uuid IS DISTINCT FROM previous
 OR p_payload->'expected_input_revision' IS DISTINCT FROM to_jsonb(e.input_revision)
 OR p_payload->>'input_hash' IS DISTINCT FROM e.input_hash
 OR (p_payload->>'validation_result_id')::uuid IS DISTINCT FROM history.validation_result_id
 OR p_payload->>'source_sha256' IS DISTINCT FROM e.manifest->>'sha256'
 OR p_payload->>'province' IS DISTINCT FROM d.province OR p_payload->'data_year' IS DISTINCT FROM to_jsonb(d.data_year)
 OR p_payload->'month' IS DISTINCT FROM to_jsonb(d.month) OR p_payload->>'product' IS DISTINCT FROM d.purpose
 OR p_payload->>'profile' IS DISTINCT FROM e.manifest->>'profile' THEN RAISE EXCEPTION 'GIS_REVISION_CONFLICT'; END IF;
 IF p_operation='withdraw' THEN
  IF e.state<>'draft' THEN RAISE EXCEPTION 'GIS_WITHDRAWAL_INELIGIBLE'; END IF;
  IF previous IS DISTINCT FROM e.id AND next_pointer IS NOT NULL THEN RAISE EXCEPTION 'GIS_REPLACEMENT_FOR_INACTIVE_EDITION'; END IF;
  IF next_pointer=e.id THEN RAISE EXCEPTION 'GIS_ACTIVATION_INELIGIBLE'; END IF;
 ELSE
  IF next_pointer=previous THEN RAISE EXCEPTION 'GIS_REVISION_CONFLICT'; END IF;
  IF p_operation='rollback' AND NOT EXISTS(SELECT 1 FROM gis.audit WHERE dataset_id=d.id
   AND operation IN ('geotiff.activate','geotiff.rollback','geotiff.withdraw') AND detail->>'new_edition_id'=e.id::text) THEN RAISE EXCEPTION 'GIS_ROLLBACK_INELIGIBLE'; END IF;
 END IF;
 IF next_pointer IS NOT NULL THEN
  SELECT * INTO target FROM gis.editions WHERE id=next_pointer;
  SELECT * INTO c FROM gis.geotiff_prepare_certificates WHERE edition_id=target.id AND id=(p_proof->>'certificate_id')::uuid;
  PERFORM id FROM gis.jobs WHERE id=history.job_id OR id=c.job_id ORDER BY id FOR UPDATE;
  SELECT * INTO r FROM gis.results WHERE job_id=c.job_id;
  identity:=gis.geotiff_publication_identity(c.id);
  IF target.dataset_id IS DISTINCT FROM d.id OR target.state<>'draft' OR identity IS NULL
   OR NOT gis.geotiff_prepared_ready(target.id,d.id) THEN RAISE EXCEPTION 'GIS_PUBLICATION_NOT_READY'; END IF;
  PERFORM gis.keys(p_proof,ARRAY['certificate_id','report','identity']);
  IF p_proof->>'certificate_id' IS DISTINCT FROM c.id::text OR p_proof->'identity' IS DISTINCT FROM identity
   OR p_proof#>>'{report,verifier_version}' IS DISTINCT FROM 'geotiff-publication-bytes-v1'
   OR ((p_proof->'report')-'verifier_version') IS DISTINCT FROM r.report THEN RAISE EXCEPTION 'GIS_PREPARE_PROOF_INVALID'; END IF;
  INSERT INTO gis.geotiff_publication_acceptances(certificate_id,identity,accepted_by,reason)
   VALUES(c.id,identity,p_actor,btrim(p_payload->>'reason')) ON CONFLICT DO NOTHING;
  IF NOT gis.geotiff_publication_ready(target.id,d.id) THEN RAISE EXCEPTION 'GIS_PUBLICATION_NOT_READY'; END IF;
 ELSE
  IF p_proof IS NOT NULL THEN RAISE EXCEPTION 'GIS_PREPARE_PROOF_INVALID'; END IF;
 END IF;
 IF p_operation='withdraw' AND previous IS DISTINCT FROM e.id THEN next_pointer:=previous; END IF;
 next_revision:=d.revision+CASE WHEN next_pointer IS DISTINCT FROM previous THEN 1 ELSE 0 END;
 INSERT INTO gis.audit(actor_id,operation,dataset_id,edition_id,reason,detail)
 VALUES(p_actor,'geotiff.'||p_operation,d.id,e.id,btrim(p_payload->>'reason'),
  jsonb_build_object('transaction_id',txid_current()::text,'previous_edition_id',previous,'new_edition_id',next_pointer,
   'previous_revision',d.revision,'new_revision',next_revision,'policy_version','local-declared-period-footprint-v1',
   'certificate_id',c.id,'identity',identity,'retired_certificate_id',history.id,'retired_input_hash',e.input_hash)) RETURNING id INTO event_id;
 IF next_pointer IS DISTINCT FROM previous THEN UPDATE gis.datasets SET active_edition_id=next_pointer,revision=next_revision WHERE id=d.id RETURNING * INTO d; END IF;
 IF p_operation='withdraw' THEN UPDATE gis.editions SET state='withdrawn' WHERE id=e.id; END IF;
 PERFORM gis.authorize(p_actor,true);
 body:=jsonb_build_object('dataset',gis.api_read_row('dataset',to_jsonb(d)),'edition_id',e.id,'operation',p_operation,
  'event_id',event_id,'local_only',true,'period_verified',false,'complete_province_inventory',false,'receipt_exists',true,'replayed',false);
 INSERT INTO gis.receipts(actor_id,request_id,operation,payload_hash,status,body) VALUES(p_actor,p_request_id,'geotiff.'||p_operation,digest,200,body);
 RETURN jsonb_build_object('status',200,'body',body);
END $f$;

CREATE FUNCTION gis.geotiff_published_packet(p_actor uuid,p_province text,p_year integer,p_month integer,p_product text,p_expected text) RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE d gis.datasets%ROWTYPE; c gis.geotiff_prepare_certificates%ROWTYPE; identity jsonb; report jsonb; snapshot text;
BEGIN
 PERFORM gis.assert_geotiff_publication();
 IF p_actor IS NULL OR NOT EXISTS(SELECT 1 FROM public.profiles WHERE id=p_actor) THEN RAISE EXCEPTION 'GIS_FORBIDDEN'; END IF;
 IF p_product NOT IN ('ndvi','lst') OR p_month NOT BETWEEN 0 AND 12 OR p_product IS NULL OR p_month IS NULL THEN RAISE EXCEPTION 'GIS_INVALID_PAYLOAD'; END IF;
 SELECT * INTO d FROM gis.datasets WHERE province=p_province AND data_year=p_year AND month=p_month AND purpose=p_product AND kind='geotiff';
 IF NOT FOUND OR d.active_edition_id IS NULL THEN RAISE EXCEPTION 'GIS_GEOTIFF_NOT_PUBLISHED'; END IF;
 IF NOT gis.geotiff_publication_ready(d.active_edition_id,d.id) THEN RAISE EXCEPTION 'GIS_GEOTIFF_PUBLISHED_UNAVAILABLE'; END IF;
 SELECT cert.* INTO c FROM gis.geotiff_prepare_certificates cert JOIN gis.geotiff_publication_acceptances a ON a.certificate_id=cert.id
 WHERE cert.edition_id=d.active_edition_id AND a.identity=gis.geotiff_publication_identity(cert.id)
 AND cert.validation_result_id::text=gis.publication_validation(d.active_edition_id)->>'validation_result_id'
 AND NOT EXISTS(SELECT 1 FROM gis.geotiff_prepare_revocations WHERE certificate_id=cert.id);
 identity:=gis.geotiff_publication_identity(c.id);
 SELECT r.report INTO report FROM gis.results r WHERE r.job_id=c.job_id;
 snapshot:=encode(sha256(convert_to(jsonb_build_object('identity',identity,'revision',d.revision)::text,'UTF8')),'hex');
 IF p_expected IS NOT NULL THEN
  IF p_expected IS DISTINCT FROM snapshot THEN RAISE EXCEPTION 'GIS_SOURCE_CHANGED'; END IF;
  RETURN jsonb_build_object('snapshot_id',snapshot);
 END IF;
 RETURN jsonb_build_object('snapshot_id',snapshot,'dataset',gis.api_read_row('dataset',to_jsonb(d)),
  'certificate_id',c.id,'identity',identity,'prepare_request',gis.geotiff_prepare_packet(c.job_id),'candidate',report);
END $f$;

CREATE FUNCTION public.gis_geotiff_publication_command(p_actor uuid,p_request_id uuid,p_operation text,p_payload jsonb,p_proof jsonb DEFAULT NULL,p_backend_local boolean DEFAULT false,p_probe boolean DEFAULT false) RETURNS jsonb
LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,gis
AS $f$ SELECT gis.geotiff_publication_command(p_actor,p_request_id,p_operation,p_payload,p_proof,p_backend_local,p_probe) $f$;
CREATE FUNCTION public.gis_geotiff_published_read(p_actor uuid,p_province text,p_year integer,p_month integer,p_product text,p_expected text DEFAULT NULL) RETURNS jsonb
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,gis
AS $f$ SELECT gis.geotiff_published_packet(p_actor,p_province,p_year,p_month,p_product,p_expected) $f$;
CREATE FUNCTION public.gis_geotiff_publication_status(p_actor uuid,p_edition uuid) RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE e gis.editions%ROWTYPE; c gis.geotiff_prepare_certificates%ROWTYPE;
BEGIN
 PERFORM gis.assert_geotiff_publication();PERFORM gis.authorize(p_actor,false);
 SELECT * INTO e FROM gis.editions WHERE id=p_edition;
 IF NOT FOUND THEN RAISE EXCEPTION 'GIS_NOT_FOUND'; END IF;
 SELECT * INTO c FROM gis.geotiff_prepare_certificates WHERE edition_id=e.id ORDER BY verified_at DESC,id DESC LIMIT 1;
 RETURN jsonb_build_object('certificate_id',c.id,'validation_result_id',c.validation_result_id,'identity',gis.geotiff_publication_identity(c.id),
  'policy_accepted',EXISTS(SELECT 1 FROM gis.geotiff_publication_acceptances WHERE certificate_id=c.id),
  'catalog_prepared',gis.geotiff_prepared_ready(e.id,e.dataset_id),'period_verified',false,'complete_province_inventory',false);
END $f$;
CREATE FUNCTION public.gis_geotiff_published_unavailable(p_actor uuid,p_province text,p_year integer,p_month integer,p_product text,p_snapshot text,p_certificate uuid) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE d gis.datasets%ROWTYPE; packet jsonb;
BEGIN
 PERFORM gis.assert_geotiff_publication();
 IF p_actor IS NULL OR NOT EXISTS(SELECT 1 FROM public.profiles WHERE id=p_actor) THEN RAISE EXCEPTION 'GIS_FORBIDDEN'; END IF;
 SELECT * INTO d FROM gis.datasets WHERE province=p_province AND data_year=p_year AND month=p_month AND kind='geotiff' AND purpose=p_product FOR NO KEY UPDATE;
 PERFORM id FROM gis.editions WHERE id=d.active_edition_id FOR UPDATE;
 packet:=gis.geotiff_published_packet(p_actor,p_province,p_year,p_month,p_product,NULL);
 IF packet->>'snapshot_id' IS DISTINCT FROM p_snapshot OR packet->>'certificate_id' IS DISTINCT FROM p_certificate::text THEN RAISE EXCEPTION 'GIS_SOURCE_CHANGED'; END IF;
 INSERT INTO gis.geotiff_prepare_revocations(certificate_id,reason) VALUES(p_certificate,'artifact_corrupt') ON CONFLICT DO NOTHING;
 INSERT INTO gis.audit(actor_id,operation,dataset_id,edition_id,reason) VALUES(p_actor,'geotiff.unavailable',d.id,d.active_edition_id,'Fresh source/artifact byte verification failed');
END $f$;

DO $acl$ DECLARE f record; BEGIN
 FOR f IN SELECT p.oid::regprocedure signature FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
 WHERE n.nspname IN ('gis','public') AND (p.proname IN ('assert_geotiff_publication','check_geotiff_acceptance','geotiff_transition_authorized','geotiff_withdrawal_authorized','geotiff_publication_identity','geotiff_publication_ready','geotiff_publication_command','geotiff_published_packet') OR p.proname LIKE 'gis_geotiff_publ%') LOOP
  EXECUTE format('REVOKE ALL ON FUNCTION %s FROM PUBLIC,anon,authenticated,service_role,gis_worker,gis_native_worker',f.signature);
 END LOOP;
END $acl$;
GRANT EXECUTE ON FUNCTION public.gis_geotiff_publication_command(uuid,uuid,text,jsonb,jsonb,boolean,boolean),
 public.gis_geotiff_published_read(uuid,text,integer,integer,text,text),public.gis_geotiff_publication_status(uuid,uuid),
 public.gis_geotiff_published_unavailable(uuid,text,integer,integer,text,text,uuid) TO service_role;
RESET ROLE;
REVOKE CREATE ON SCHEMA public FROM gis_owner;
