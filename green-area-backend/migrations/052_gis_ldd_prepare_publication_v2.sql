-- 052 LDD preparation and publication accept the policy-v2 method (ldd-geometry-area-v2).
-- Until now prepare, verification and publication were pinned to ldd-source-area-v1, so a file that passes
-- only the policy-v2 validator (every real LDD package) could be validated but never prepared or shown.
-- The method of a preparation follows its validation: a validation report produced by the policy-v2
-- validator carries the LDD_POLICY_V2 marker and is prepared with v2; any other report keeps v1. Nobody
-- chooses the method in a request. Every v1 rule, artifact, certificate and published snapshot is unchanged:
-- the same functions run for v1, a v1 identity stays byte for byte the same, and v2 is checked by the same
-- rules with its own method name. A published identity always names the method its artifacts were made with.
-- Not included: approving Review Required results, new artifact kinds, larger artifact limits.
-- The attested operator supplies BEGIN/runtime proof and the INSERT-only ledger entry.
DO $guard$ BEGIN
 IF current_database() NOT IN ('postgres','gis_t1_upgrade') OR current_setting('cluster_name')<>'green-area-gis-t0'
 OR NOT EXISTS(SELECT 1 FROM gis.schema_migrations WHERE version=51 AND sha256='b2506ddd4f4ed5888fb0b25bfb3424e52aaee87d601a43523830db45b6347d5a')
 OR EXISTS(SELECT 1 FROM gis.schema_migrations WHERE version>=52)
 OR NOT EXISTS(SELECT 1 FROM gis.environment WHERE singleton AND NOT activation_enabled
 AND runtime_instance=current_setting('gis.runtime_instance',true) AND baseline_fingerprint=current_setting('gis.baseline_fingerprint',true))
 THEN RAISE EXCEPTION 'GIS_LOCAL_BASELINE_051_REQUIRED';END IF;
END $guard$;
-- public.gis_publication_read is replaced in place (as in 038); CREATE on public is granted for this transaction only.
GRANT CREATE ON SCHEMA public TO gis_owner;
SET LOCAL ROLE gis_owner;
SELECT gis.assert_environment();

-- 1. A preparation request may name either method; existing rows are all v1 and stay immutable.
ALTER TABLE gis.ldd_prepare_requests DROP CONSTRAINT ldd_prepare_requests_method_version_check;
ALTER TABLE gis.ldd_prepare_requests ADD CONSTRAINT ldd_prepare_requests_method_version_check
 CHECK(method_version IN ('ldd-source-area-v1','ldd-geometry-area-v2'));

-- 2. The method follows the validation result the request is bound to (ldd_prepare_command inserts the
--    request without a method; whatever an insert says, the validation decides).
CREATE FUNCTION gis.ldd_prepare_method() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE report jsonb;
BEGIN
 SELECT r.report INTO report FROM gis.results r WHERE r.id=NEW.validation_result_id AND r.edition_id=NEW.edition_id AND r.provider='local_ldd';
 NEW.method_version:=CASE WHEN jsonb_typeof(report->'warnings')='array' AND report->'warnings' @> '[{"code":"LDD_POLICY_V2"}]'::jsonb
  THEN 'ldd-geometry-area-v2' ELSE 'ldd-source-area-v1' END;
 RETURN NEW;
END $f$;
CREATE TRIGGER prepare_method BEFORE INSERT ON gis.ldd_prepare_requests FOR EACH ROW EXECUTE FUNCTION gis.ldd_prepare_method();

-- 3. A worker report must name the method of its request. A v2 report is checked by every rule of the
--    previous function under the method name that function expects; a v1 request still accepts only v1.
ALTER FUNCTION gis.ldd_prepare_report(uuid,jsonb) RENAME TO u052_previous_ldd_prepare_report;
CREATE FUNCTION gis.ldd_prepare_report(p_job uuid,p_report jsonb) RETURNS void
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE method text;
BEGIN
 SELECT method_version INTO method FROM gis.ldd_prepare_requests WHERE job_id=p_job;
 IF method='ldd-geometry-area-v2' THEN
  IF jsonb_typeof(p_report) IS DISTINCT FROM 'object' OR p_report->>'method_version' IS DISTINCT FROM method THEN
   RAISE EXCEPTION 'GIS_PREPARE_REPORT_INVALID'; END IF;
  PERFORM gis.u052_previous_ldd_prepare_report(p_job,jsonb_set(p_report,'{method_version}','"ldd-source-area-v1"'::jsonb));
 ELSE
  PERFORM gis.u052_previous_ldd_prepare_report(p_job,p_report);
 END IF;
END $f$;

-- 4. Readiness: the certificate, its artifacts and the stored report all carry the method of the request.
--    For v1 this is the same condition as before (method 'ldd-source-area-v1' everywhere).
CREATE OR REPLACE FUNCTION gis.publication_ready(p_edition uuid,p_dataset uuid) RETURNS boolean
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE validation jsonb;
BEGIN
 PERFORM gis.assert_environment();validation:=gis.publication_validation(p_edition);
 IF validation IS NULL OR validation->>'dataset_id' IS DISTINCT FROM p_dataset::text OR validation->>'kind'<>'ldd_shapefile' THEN RETURN false; END IF;
 RETURN EXISTS(SELECT 1 FROM gis.ldd_prepare_certificates c
 JOIN gis.jobs j ON j.id=c.job_id JOIN gis.results r ON r.job_id=j.id AND r.provider='local_ldd_prepare'
 JOIN gis.ldd_prepare_requests q ON q.job_id=c.job_id
 JOIN gis.publication_artifacts g ON g.id=c.geometry_artifact_id
 JOIN gis.publication_artifacts s ON s.id=c.summary_artifact_id
 WHERE c.edition_id=p_edition AND c.validation_result_id=(validation->>'validation_result_id')::uuid AND j.state='succeeded'
 AND g.edition_id=p_edition AND s.edition_id=p_edition AND g.dataset_id=p_dataset AND s.dataset_id=p_dataset
 AND g.artifact_kind='ldd_geometry' AND s.artifact_kind='ldd_summary'
 AND q.method_version IN ('ldd-source-area-v1','ldd-geometry-area-v2')
 AND g.method_version=q.method_version AND s.method_version=g.method_version AND r.report->>'method_version'=q.method_version
 AND g.validation_result_id=c.validation_result_id AND s.validation_result_id=c.validation_result_id
 AND g.input_hash=validation->>'input_hash' AND s.input_hash=g.input_hash
 AND g.source_sha256=validation->>'source_sha256' AND s.source_sha256=g.source_sha256
 AND g.artifact_sha256=r.report#>>'{artifacts,ldd_geometry,sha256}' AND s.artifact_sha256=r.report#>>'{artifacts,ldd_summary,sha256}'
 AND NOT EXISTS(SELECT 1 FROM gis.ldd_prepare_revocations WHERE certificate_id=c.id));
END $f$;

-- 5. Verification registers the artifacts under the method of the request (038 used the v1 literal).
--    Everything else is the 038 function unchanged.
CREATE OR REPLACE FUNCTION gis.ldd_verify_complete(p_actor uuid,p_request_id uuid,p_job uuid,p_proof jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE j gis.jobs%ROWTYPE; e gis.editions%ROWTYPE; d gis.datasets%ROWTYPE; v jsonb; r gis.results%ROWTYPE;
 c gis.ldd_prepare_certificates%ROWTYPE; a gis.publication_artifacts%ROWTYPE; g uuid; s uuid; k text;
 receipt gis.receipts%ROWTYPE; digest text; body jsonb; method text;
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
 SELECT method_version INTO method FROM gis.ldd_prepare_requests WHERE job_id=j.id;
 IF v IS NULL OR j.kind<>'prepare_ldd_edition' OR j.state<>'succeeded' OR r.provider<>'local_ldd_prepare'
 OR j.input_hash<>e.input_hash OR j.input_revision<>e.input_revision OR method IS NULL THEN RAISE EXCEPTION 'GIS_PREPARE_NOT_READY'; END IF;
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
  SELECT * INTO a FROM gis.publication_artifacts WHERE edition_id=e.id AND method_version=method AND artifact_kind=k;
  IF NOT FOUND THEN
   INSERT INTO gis.publication_artifacts(dataset_id,edition_id,validation_result_id,input_revision,input_hash,source_sha256,
     artifact_kind,artifact_sha256,byte_size,method_version,coverage_province,registered_by)
   VALUES(d.id,e.id,(v->>'validation_result_id')::uuid,e.input_revision,e.input_hash,v->>'source_sha256',k,
     p_proof#>>ARRAY['artifacts',k,'sha256'],(p_proof#>>ARRAY['artifacts',k,'byte_size'])::bigint,method,d.province,p_actor) RETURNING * INTO a;
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

-- 6. Catalog read: ready only when the current certificate was made with the method asked about.
CREATE OR REPLACE FUNCTION public.gis_publication_read(p_actor uuid,p_edition uuid,p_method_version text) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE value jsonb; ready boolean;
BEGIN
 PERFORM gis.authorize(p_actor,false);value:=gis.publication_status(p_edition,p_method_version);
 ready:=COALESCE(p_method_version IN ('ldd-source-area-v1','ldd-geometry-area-v2'),false)
  AND gis.publication_ready(p_edition,(value->>'dataset_id')::uuid)
  AND EXISTS(SELECT 1 FROM gis.ldd_prepare_certificates c JOIN gis.ldd_prepare_requests q ON q.job_id=c.job_id
   JOIN gis.editions e ON e.id=c.edition_id
   WHERE c.edition_id=p_edition AND c.validation_result_id=e.validated_result_id AND q.method_version=p_method_version
   AND NOT EXISTS(SELECT 1 FROM gis.ldd_prepare_revocations x WHERE x.certificate_id=c.id));
 RETURN value||jsonb_build_object('verification_available',COALESCE(p_method_version IN ('ldd-source-area-v1','ldd-geometry-area-v2'),false),
   'coverage_verified',ready,
   'ready_for_publication',ready,'certificate_only_requires_live_byte_check',true,'complete_province_inventory',false,
   'status',CASE WHEN ready THEN 'verified_for_local_review' ELSE value->>'status' END,
   'blocker',CASE WHEN ready THEN NULL ELSE 'TRUSTED_VERIFICATION_REQUIRED' END);
END $f$;

-- 7. Publication commands accept either method. The payload must name the method of the Edition's own
--    certificate; the audit records that method. Everything else is the 040 function unchanged, and the
--    new check runs after every earlier check so the v1 error codes stay as they were.
CREATE OR REPLACE FUNCTION gis.ldd_publication_command(p_actor uuid,p_request_id uuid,p_operation text,p_payload jsonb,p_proof jsonb,p_backend_local boolean,p_probe boolean) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE d gis.datasets%ROWTYPE; e gis.editions%ROWTYPE; target gis.editions%ROWTYPE;
 c gis.ldd_prepare_certificates%ROWTYPE; r gis.results%ROWTYPE; receipt gis.receipts%ROWTYPE;
 digest text; previous uuid; next_pointer uuid; next_revision integer; event_id uuid; body jsonb;
BEGIN
 PERFORM gis.assert_ldd_publication();PERFORM gis.authorize(p_actor,true);
 IF p_backend_local IS DISTINCT FROM true THEN RAISE EXCEPTION 'GIS_LDD_PUBLICATION_DISABLED'; END IF;
 IF p_operation NOT IN ('activate','rollback','withdraw') OR p_operation IS NULL THEN RAISE EXCEPTION 'GIS_UNKNOWN_OPERATION'; END IF;
 IF p_request_id IS NULL THEN RAISE EXCEPTION 'GIS_REQUEST_ID_REQUIRED'; END IF;
 PERFORM gis.keys(p_payload,ARRAY['dataset_id','edition_id','expected_dataset_revision','expected_active_edition_id',
  'expected_input_revision','input_hash','validation_result_id','source_sha256','province','data_year','method_version','coverage_mode','reason','replacement_edition_id']);
 IF NOT p_payload ?& ARRAY['dataset_id','edition_id','expected_dataset_revision','expected_active_edition_id',
  'expected_input_revision','input_hash','validation_result_id','source_sha256','province','data_year','method_version','coverage_mode','reason']
 OR jsonb_typeof(p_payload->'reason') IS DISTINCT FROM 'string' OR length(btrim(p_payload->>'reason')) NOT BETWEEN 1 AND 500
 OR COALESCE(p_payload->>'method_version','') NOT IN ('ldd-source-area-v1','ldd-geometry-area-v2')
 OR p_payload->>'coverage_mode' IS DISTINCT FROM 'validated_source_footprint' THEN RAISE EXCEPTION 'GIS_INVALID_PAYLOAD'; END IF;
 digest:=encode(sha256(convert_to(p_payload::text,'UTF8')),'hex');
 PERFORM pg_advisory_xact_lock(hashtextextended(p_actor::text||':'||p_request_id::text,0));
 PERFORM gis.authorize(p_actor,true);
 SELECT * INTO receipt FROM gis.receipts WHERE actor_id=p_actor AND request_id=p_request_id;
 IF FOUND THEN
  IF receipt.operation<>'ldd.'||p_operation OR receipt.payload_hash<>digest THEN RAISE EXCEPTION 'GIS_IDEMPOTENCY_CONFLICT'; END IF;
  RETURN jsonb_build_object('status',200,'body',receipt.body||jsonb_build_object('replayed',true,'operation_history',true));
 END IF;
 IF p_probe IS true THEN RETURN jsonb_build_object('status',200,'body',jsonb_build_object('receipt_exists',false)); END IF;
 SELECT * INTO d FROM gis.datasets WHERE id=(p_payload->>'dataset_id')::uuid FOR NO KEY UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'GIS_NOT_FOUND'; END IF;
 IF d.kind<>'ldd_shapefile' OR d.purpose<>'landuse' OR d.month<>0 THEN RAISE EXCEPTION 'GIS_LDD_PUBLICATION_UNSUPPORTED'; END IF;
 next_pointer:=CASE WHEN p_operation='withdraw' THEN (p_payload->>'replacement_edition_id')::uuid ELSE (p_payload->>'edition_id')::uuid END;
 IF p_operation='withdraw' AND NOT p_payload ? 'replacement_edition_id' THEN RAISE EXCEPTION 'GIS_EXPECTED_POINTER_REQUIRED'; END IF;
 PERFORM id FROM gis.editions WHERE id=(p_payload->>'edition_id')::uuid OR id=next_pointer ORDER BY id FOR UPDATE;
 SELECT * INTO e FROM gis.editions WHERE id=(p_payload->>'edition_id')::uuid;
 IF NOT FOUND OR e.dataset_id<>d.id THEN RAISE EXCEPTION 'GIS_NOT_FOUND'; END IF;
 -- The narrow path never retires old V1/V2 fixtures or unrelated drafts.
 -- Historical certification is enough for withdrawal of a corrupt/revoked
 -- upload; current filesystem availability is deliberately not required.
 IF NOT EXISTS(SELECT 1 FROM gis.ldd_uploads u WHERE u.edition_id=e.id AND u.dataset_id=d.id
   AND e.manifest=gis.ldd_manifest(u))
 OR (p_operation='withdraw' AND NOT EXISTS(SELECT 1 FROM gis.ldd_prepare_certificates history
   WHERE history.edition_id=e.id AND history.validation_result_id=e.validated_result_id)) THEN
  RAISE EXCEPTION 'GIS_LDD_PUBLICATION_UNSUPPORTED'; END IF;
 previous:=d.active_edition_id;
 IF p_payload->'expected_dataset_revision' IS DISTINCT FROM to_jsonb(d.revision)
 OR (p_payload->>'expected_active_edition_id')::uuid IS DISTINCT FROM previous
 OR p_payload->'expected_input_revision' IS DISTINCT FROM to_jsonb(e.input_revision)
 OR p_payload->>'input_hash' IS DISTINCT FROM e.input_hash
 OR (p_payload->>'validation_result_id')::uuid IS DISTINCT FROM e.validated_result_id
 OR p_payload->>'source_sha256' IS DISTINCT FROM e.manifest->>'sha256'
 OR p_payload->>'province' IS DISTINCT FROM d.province OR p_payload->'data_year' IS DISTINCT FROM to_jsonb(d.data_year) THEN
 RAISE EXCEPTION 'GIS_REVISION_CONFLICT'; END IF;
 IF p_operation='withdraw' THEN
  IF e.state NOT IN ('draft','validated') THEN RAISE EXCEPTION 'GIS_WITHDRAWAL_INELIGIBLE'; END IF;
  IF previous IS DISTINCT FROM e.id AND next_pointer IS NOT NULL THEN RAISE EXCEPTION 'GIS_REPLACEMENT_FOR_INACTIVE_EDITION'; END IF;
  IF next_pointer=e.id THEN RAISE EXCEPTION 'GIS_ACTIVATION_INELIGIBLE'; END IF;
 ELSE
  IF next_pointer=previous THEN RAISE EXCEPTION 'GIS_REVISION_CONFLICT'; END IF;
  IF p_operation='rollback' AND NOT EXISTS(SELECT 1 FROM gis.audit WHERE dataset_id=d.id
   AND operation IN ('ldd.activate','ldd.rollback','ldd.withdraw') AND detail->>'new_edition_id'=e.id::text) THEN
   RAISE EXCEPTION 'GIS_ROLLBACK_INELIGIBLE'; END IF;
 END IF;
 IF next_pointer IS NOT NULL THEN
  SELECT * INTO target FROM gis.editions WHERE id=next_pointer;
  IF target.dataset_id IS DISTINCT FROM d.id OR NOT gis.eligible(target.id,d.id)
   OR NOT gis.publication_ready(target.id,d.id) THEN RAISE EXCEPTION 'GIS_PUBLICATION_NOT_READY'; END IF;
  SELECT * INTO c FROM gis.ldd_prepare_certificates WHERE edition_id=target.id AND validation_result_id=target.validated_result_id;
  SELECT * INTO r FROM gis.results WHERE job_id=c.job_id;
  PERFORM gis.keys(p_proof,ARRAY['certificate_id','report']);
  IF p_proof->>'certificate_id' IS DISTINCT FROM c.id::text
   OR p_proof#>>'{report,verifier_version}' IS DISTINCT FROM 'ldd-publication-bytes-v1'
   OR ((p_proof->'report')-'verifier_version') IS DISTINCT FROM r.report THEN RAISE EXCEPTION 'GIS_PREPARE_PROOF_INVALID'; END IF;
 ELSE
  IF p_proof IS NOT NULL THEN RAISE EXCEPTION 'GIS_PREPARE_PROOF_INVALID'; END IF;
 END IF;
 -- The payload names the method of the Edition's own certificate (a replacement may use another method).
 IF NOT EXISTS(SELECT 1 FROM gis.ldd_prepare_certificates own JOIN gis.ldd_prepare_requests q ON q.job_id=own.job_id
   WHERE own.edition_id=e.id AND own.validation_result_id=e.validated_result_id AND q.method_version=p_payload->>'method_version') THEN
  RAISE EXCEPTION 'GIS_PUBLICATION_METHOD_MISMATCH'; END IF;
 -- An inactive withdrawal never clears some other active Edition.
 IF p_operation='withdraw' AND previous IS DISTINCT FROM e.id THEN next_pointer:=previous; END IF;
 next_revision:=d.revision+CASE WHEN next_pointer IS DISTINCT FROM previous THEN 1 ELSE 0 END;
 INSERT INTO gis.audit(actor_id,operation,dataset_id,edition_id,reason,detail)
 VALUES(p_actor,'ldd.'||p_operation,d.id,e.id,btrim(p_payload->>'reason'),
  jsonb_build_object('transaction_id',txid_current()::text,'previous_edition_id',previous,'new_edition_id',next_pointer,
   'previous_revision',d.revision,'new_revision',next_revision,'method_version',p_payload->>'method_version',
   'coverage_mode','validated_source_footprint','certificate_id',c.id,'input_hash',target.input_hash,
   'source_sha256',target.manifest->>'sha256','artifacts',r.report->'artifacts')) RETURNING id INTO event_id;
 IF next_pointer IS DISTINCT FROM previous THEN
  UPDATE gis.datasets SET active_edition_id=next_pointer,revision=next_revision WHERE id=d.id RETURNING * INTO d;
 END IF;
 IF p_operation='withdraw' THEN UPDATE gis.editions SET state='withdrawn' WHERE id=e.id; END IF;
 PERFORM gis.authorize(p_actor,true);
 body:=jsonb_build_object('dataset',gis.api_read_row('dataset',to_jsonb(d)),'edition_id',e.id,'operation',p_operation,
  'event_id',event_id,'local_only',true,'complete_province_inventory',false,'receipt_exists',true,'replayed',false);
 INSERT INTO gis.receipts(actor_id,request_id,operation,payload_hash,status,body)
 VALUES(p_actor,p_request_id,'ldd.'||p_operation,digest,200,body);
 RETURN jsonb_build_object('status',200,'body',body);
END $f$;

-- 8. The Dashboard read names the method of the active certificate. A v1 identity, and so a v1 snapshot id,
--    is unchanged.
CREATE OR REPLACE FUNCTION gis.ldd_published_packet(p_actor uuid,p_province text,p_year integer,p_expected text) RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE d gis.datasets%ROWTYPE; c gis.ldd_prepare_certificates%ROWTYPE; v jsonb; report jsonb; identity jsonb; snapshot text; method text;
BEGIN
 PERFORM gis.assert_ldd_publication();
 IF p_actor IS NULL OR NOT EXISTS(SELECT 1 FROM public.profiles WHERE id=p_actor) THEN RAISE EXCEPTION 'GIS_FORBIDDEN'; END IF;
 SELECT * INTO d FROM gis.datasets WHERE province=p_province AND data_year=p_year AND month=0 AND kind='ldd_shapefile' AND purpose='landuse';
 IF NOT FOUND OR d.active_edition_id IS NULL THEN RAISE EXCEPTION 'GIS_LDD_NOT_PUBLISHED'; END IF;
 v:=gis.publication_validation(d.active_edition_id);
 IF NOT gis.publication_ready(d.active_edition_id,d.id) THEN RAISE EXCEPTION 'GIS_LDD_PUBLISHED_UNAVAILABLE'; END IF;
 SELECT * INTO c FROM gis.ldd_prepare_certificates WHERE edition_id=d.active_edition_id AND validation_result_id=(v->>'validation_result_id')::uuid;
 SELECT r.report INTO report FROM gis.results r WHERE job_id=c.job_id;
 SELECT q.method_version INTO method FROM gis.ldd_prepare_requests q WHERE q.job_id=c.job_id;
 identity:=(v-'kind'-'purpose'-'input_revision')||jsonb_build_object('namespace','published','scope','province','product','landuse','method_version',method);
 snapshot:=encode(sha256(convert_to(jsonb_build_object('identity',identity,'revision',d.revision,
  'certificate',c.id,'artifacts',report->'artifacts')::text,'UTF8')),'hex');
 IF p_expected IS NOT NULL THEN
  IF p_expected IS DISTINCT FROM snapshot THEN RAISE EXCEPTION 'GIS_SOURCE_CHANGED'; END IF;
  RETURN jsonb_build_object('snapshot_id',snapshot);
 END IF;
 RETURN jsonb_build_object('snapshot_id',snapshot,'dataset',gis.api_read_row('dataset',to_jsonb(d)),
  'certificate_id',c.id,'source_identity',identity,'prepare_request',gis.ldd_prepare_packet(c.job_id),'candidate',report);
END $f$;

DO $acl$ DECLARE f record;BEGIN
 FOR f IN SELECT p.oid::regprocedure AS sig FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
 WHERE n.nspname='gis' AND p.proname IN ('ldd_prepare_method','ldd_prepare_report','u052_previous_ldd_prepare_report','publication_ready',
  'ldd_verify_complete','ldd_publication_command','ldd_published_packet') LOOP
 EXECUTE format('REVOKE ALL ON FUNCTION %s FROM PUBLIC,anon,authenticated,service_role,gis_worker,gis_native_worker,gis_gee_mock_worker,gis_gee_live_worker,gis_gee_safety_worker,gis_gee_transport_recorder,gis_gee_https_worker,gis_gee_https_recorder',f.sig);
 END LOOP;
END $acl$;
RESET ROLE;
REVOKE CREATE ON SCHEMA public FROM gis_owner;
NOTIFY pgrst,'reload schema';
