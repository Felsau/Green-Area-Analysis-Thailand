-- A3 forward correction: explicit jsonb operator grouping, no contract/ACL change.
SET LOCAL ROLE gis_owner;
SELECT gis.assert_environment();
DO $guard$ BEGIN
 IF current_database() NOT IN ('postgres','gis_t1_upgrade') OR NOT gis.target_ok()
 OR NOT EXISTS(SELECT 1 FROM gis.environment WHERE singleton AND NOT activation_enabled
  AND runtime_instance=current_setting('gis.runtime_instance',true)
  AND baseline_fingerprint=current_setting('gis.baseline_fingerprint',true))
 OR NOT EXISTS(SELECT 1 FROM gis.schema_migrations WHERE version=39
  AND sha256='287c1259ac685645a8a43275ee0a9fbdb6ca5cf5483aeeb8eaf8f650adeeff59')
 OR EXISTS(SELECT 1 FROM gis.schema_migrations WHERE version>=40) THEN
 RAISE EXCEPTION 'GIS_LOCAL_BASELINE_039_REQUIRED'; END IF;
END $guard$;
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
   OR ((p_proof->'report')-'verifier_version') IS DISTINCT FROM r.report THEN RAISE EXCEPTION 'GIS_PREPARE_PROOF_INVALID'; END IF;
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

REVOKE ALL ON FUNCTION gis.ldd_publication_command(uuid,uuid,text,jsonb,jsonb,boolean,boolean)
 FROM PUBLIC,anon,authenticated,service_role,gis_worker,gis_native_worker;
RESET ROLE;
