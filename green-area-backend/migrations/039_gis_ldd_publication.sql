-- A3: Local annual LDD only. Broad activation_enabled remains false.
GRANT CREATE ON SCHEMA public TO gis_owner;
SET LOCAL ROLE gis_owner;
SELECT gis.assert_environment();
DO $guard$ BEGIN
 IF current_database() NOT IN ('postgres','gis_t1_upgrade') OR NOT gis.target_ok()
 OR NOT EXISTS(SELECT 1 FROM gis.environment WHERE singleton AND NOT activation_enabled
  AND runtime_instance=current_setting('gis.runtime_instance',true)
  AND baseline_fingerprint=current_setting('gis.baseline_fingerprint',true))
 OR NOT EXISTS(SELECT 1 FROM gis.schema_migrations WHERE version=38
  AND sha256='d830d0671c9d44a85274c52014b6ecdeef0019eca1421379f317e28fb594b995')
 OR EXISTS(SELECT 1 FROM gis.schema_migrations WHERE version>=39) THEN
 RAISE EXCEPTION 'GIS_LOCAL_BASELINE_038_REQUIRED'; END IF;
END $guard$;

CREATE FUNCTION gis.assert_ldd_publication() RETURNS void
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
BEGIN
 PERFORM gis.assert_environment();
 IF current_database() NOT IN ('postgres','gis_t1_upgrade') OR NOT gis.target_ok()
 OR NOT EXISTS(SELECT 1 FROM gis.environment WHERE singleton AND NOT activation_enabled)
 OR NOT EXISTS(SELECT 1 FROM gis.schema_migrations WHERE version=39) THEN RAISE EXCEPTION 'GIS_LDD_PUBLICATION_DISABLED'; END IF;
END $f$;

-- Audit is owner-only and immutable. Only this new command can create an ldd.*
-- authorization record BEFORE the pointer write. No caller-set GUC is authority.
CREATE FUNCTION gis.ldd_transition_authorized(p_dataset uuid,p_old uuid,p_new uuid,p_old_revision integer,p_new_revision integer) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
 SELECT EXISTS(SELECT 1 FROM gis.datasets d JOIN gis.audit a ON a.dataset_id=d.id
 WHERE d.id=p_dataset AND d.kind='ldd_shapefile' AND d.purpose='landuse' AND d.month=0
 AND p_new_revision=p_old_revision+1
 AND a.operation IN ('ldd.activate','ldd.rollback','ldd.withdraw')
 AND a.detail->>'transaction_id'=txid_current()::text
 AND a.detail->'previous_edition_id'=COALESCE(to_jsonb(p_old),'null'::jsonb)
 AND a.detail->'new_edition_id'=COALESCE(to_jsonb(p_new),'null'::jsonb)
 AND a.detail->'previous_revision'=to_jsonb(p_old_revision) AND a.detail->'new_revision'=to_jsonb(p_new_revision))
$f$;

-- Dataset-only replacement: all original identity/revision/actor/delete checks
-- are retained. Jobs/attempts/results/history still use the unchanged old guard.
CREATE FUNCTION gis.guard_ldd_dataset() RETURNS trigger
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
   AND NOT gis.ldd_transition_authorized(NEW.id,OLD.active_edition_id,NEW.active_edition_id,OLD.revision,NEW.revision) THEN
   RAISE EXCEPTION 'GIS_ACTIVATION_DISABLED'; END IF;
  IF NEW.created_by IS DISTINCT FROM OLD.created_by AND NOT(NEW.created_by IS NULL AND pg_trigger_depth()>1) THEN
   RAISE EXCEPTION 'GIS_ACTOR_IMMUTABLE'; END IF;
 END IF;
 RETURN NEW;
END $f$;
DROP TRIGGER immutable_row ON gis.datasets;
CREATE TRIGGER immutable_row BEFORE INSERT OR UPDATE OR DELETE ON gis.datasets FOR EACH ROW EXECUTE FUNCTION gis.guard_ldd_dataset();

CREATE FUNCTION gis.ldd_publication_command(p_actor uuid,p_request_id uuid,p_operation text,p_payload jsonb,p_proof jsonb,p_backend_local boolean,p_probe boolean) RETURNS jsonb
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
 OR p_payload->>'method_version' IS DISTINCT FROM 'ldd-source-area-v1'
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
   OR (p_proof->'report'-'verifier_version') IS DISTINCT FROM r.report THEN RAISE EXCEPTION 'GIS_PREPARE_PROOF_INVALID'; END IF;
 ELSE
  IF p_proof IS NOT NULL THEN RAISE EXCEPTION 'GIS_PREPARE_PROOF_INVALID'; END IF;
 END IF;
 -- An inactive withdrawal never clears some other active Edition.
 IF p_operation='withdraw' AND previous IS DISTINCT FROM e.id THEN next_pointer:=previous; END IF;
 next_revision:=d.revision+CASE WHEN next_pointer IS DISTINCT FROM previous THEN 1 ELSE 0 END;
 INSERT INTO gis.audit(actor_id,operation,dataset_id,edition_id,reason,detail)
 VALUES(p_actor,'ldd.'||p_operation,d.id,e.id,btrim(p_payload->>'reason'),
  jsonb_build_object('transaction_id',txid_current()::text,'previous_edition_id',previous,'new_edition_id',next_pointer,
   'previous_revision',d.revision,'new_revision',next_revision,'method_version','ldd-source-area-v1',
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

-- Dashboard read: signed-in normal users may read published data, not catalog.
CREATE FUNCTION gis.ldd_published_packet(p_actor uuid,p_province text,p_year integer,p_expected text) RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE d gis.datasets%ROWTYPE; c gis.ldd_prepare_certificates%ROWTYPE; v jsonb; report jsonb; identity jsonb; snapshot text;
BEGIN
 PERFORM gis.assert_ldd_publication();
 IF p_actor IS NULL OR NOT EXISTS(SELECT 1 FROM public.profiles WHERE id=p_actor) THEN RAISE EXCEPTION 'GIS_FORBIDDEN'; END IF;
 SELECT * INTO d FROM gis.datasets WHERE province=p_province AND data_year=p_year AND month=0 AND kind='ldd_shapefile' AND purpose='landuse';
 IF NOT FOUND OR d.active_edition_id IS NULL THEN RAISE EXCEPTION 'GIS_LDD_NOT_PUBLISHED'; END IF;
 v:=gis.publication_validation(d.active_edition_id);
 IF NOT gis.publication_ready(d.active_edition_id,d.id) THEN RAISE EXCEPTION 'GIS_LDD_PUBLISHED_UNAVAILABLE'; END IF;
 SELECT * INTO c FROM gis.ldd_prepare_certificates WHERE edition_id=d.active_edition_id AND validation_result_id=(v->>'validation_result_id')::uuid;
 SELECT r.report INTO report FROM gis.results r WHERE job_id=c.job_id;
 identity:=(v-'kind'-'purpose'-'input_revision')||jsonb_build_object('namespace','published','scope','province','product','landuse','method_version','ldd-source-area-v1');
 snapshot:=encode(sha256(convert_to(jsonb_build_object('identity',identity,'revision',d.revision,
  'certificate',c.id,'artifacts',report->'artifacts')::text,'UTF8')),'hex');
 IF p_expected IS NOT NULL THEN
  IF p_expected IS DISTINCT FROM snapshot THEN RAISE EXCEPTION 'GIS_SOURCE_CHANGED'; END IF;
  RETURN jsonb_build_object('snapshot_id',snapshot);
 END IF;
 RETURN jsonb_build_object('snapshot_id',snapshot,'dataset',gis.api_read_row('dataset',to_jsonb(d)),
  'certificate_id',c.id,'source_identity',identity,'prepare_request',gis.ldd_prepare_packet(c.job_id),'candidate',report);
END $f$;

CREATE FUNCTION public.gis_ldd_publication_command(p_actor uuid,p_request_id uuid,p_operation text,p_payload jsonb,p_proof jsonb DEFAULT NULL,p_backend_local boolean DEFAULT false,p_probe boolean DEFAULT false) RETURNS jsonb
LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,gis
AS $f$ SELECT gis.ldd_publication_command(p_actor,p_request_id,p_operation,p_payload,p_proof,p_backend_local,p_probe) $f$;
CREATE FUNCTION public.gis_ldd_published_read(p_actor uuid,p_province text,p_year integer,p_expected text DEFAULT NULL) RETURNS jsonb
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,gis
AS $f$ SELECT gis.ldd_published_packet(p_actor,p_province,p_year,p_expected) $f$;
CREATE FUNCTION public.gis_ldd_published_unavailable(p_actor uuid,p_province text,p_year integer,p_snapshot text,p_certificate uuid) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE d gis.datasets%ROWTYPE; packet jsonb;
BEGIN
 PERFORM gis.assert_ldd_publication();
 IF p_actor IS NULL OR NOT EXISTS(SELECT 1 FROM public.profiles WHERE id=p_actor) THEN RAISE EXCEPTION 'GIS_FORBIDDEN'; END IF;
 SELECT * INTO d FROM gis.datasets WHERE province=p_province AND data_year=p_year AND month=0 AND kind='ldd_shapefile' AND purpose='landuse' FOR NO KEY UPDATE;
 PERFORM id FROM gis.editions WHERE id=d.active_edition_id FOR UPDATE;
 packet:=gis.ldd_published_packet(p_actor,p_province,p_year,NULL);
 IF packet->>'snapshot_id' IS DISTINCT FROM p_snapshot OR packet->>'certificate_id' IS DISTINCT FROM p_certificate::text THEN RAISE EXCEPTION 'GIS_SOURCE_CHANGED'; END IF;
 INSERT INTO gis.ldd_prepare_revocations(certificate_id,reason) VALUES(p_certificate,'artifact_corrupt') ON CONFLICT DO NOTHING;
 INSERT INTO gis.audit(actor_id,operation,dataset_id,edition_id,reason)
 VALUES(p_actor,'ldd.unavailable',d.id,d.active_edition_id,'Published source/artifact byte check failed');
END $f$;
DO $acl$ DECLARE f record; BEGIN
 FOR f IN SELECT p.oid::regprocedure signature FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
 WHERE n.nspname IN ('gis','public') AND (p.proname IN ('assert_ldd_publication','ldd_transition_authorized','guard_ldd_dataset','ldd_publication_command','ldd_published_packet')
  OR p.proname IN ('gis_ldd_publication_command','gis_ldd_published_read','gis_ldd_published_unavailable')) LOOP
 EXECUTE format('REVOKE ALL ON FUNCTION %s FROM PUBLIC,anon,authenticated,service_role,gis_worker,gis_native_worker',f.signature);
 END LOOP;
END $acl$;
GRANT EXECUTE ON FUNCTION public.gis_ldd_publication_command(uuid,uuid,text,jsonb,jsonb,boolean,boolean),
 public.gis_ldd_published_read(uuid,text,integer,text),public.gis_ldd_published_unavailable(uuid,text,integer,text,uuid) TO service_role;
RESET ROLE;
REVOKE CREATE ON SCHEMA public FROM gis_owner;
