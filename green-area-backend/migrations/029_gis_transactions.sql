-- Service RPC boundary. p_actor is attested by the backend's verified JWT;
-- no browser role may execute these wrappers. All payload keys are allowlisted.
GRANT CREATE ON SCHEMA public TO gis_owner;
SET LOCAL ROLE gis_owner;
SELECT gis.assert_environment();

CREATE FUNCTION gis.eligible(p_edition uuid,p_dataset uuid) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
 SELECT EXISTS(SELECT 1 FROM gis.editions e JOIN gis.results r ON r.id=e.validated_result_id AND r.edition_id=e.id
  JOIN gis.jobs j ON j.id=r.job_id JOIN gis.synthetic_fixtures f ON f.manifest=e.manifest
  JOIN gis.datasets d ON d.id=e.dataset_id AND f.kind=d.kind AND f.purpose=d.purpose
  WHERE e.id=p_edition AND e.dataset_id=p_dataset AND e.state='validated'
   AND r.valid AND r.provider='synthetic' AND r.input_revision=e.input_revision AND r.input_hash=e.input_hash
   AND j.state='succeeded' AND j.edition_id=e.id AND j.input_revision=e.input_revision AND j.input_hash=e.input_hash
   AND r.validator_version=j.validator_version AND r.validator_version='synthetic-v1')
$f$;

-- Row guards preserve immutable sources/history even if a future owner RPC has a bug.
-- Cross-table checks below are deferred until the entire state transaction is done.
CREATE FUNCTION gis.guard_row() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'GIS_HARD_DELETE_FORBIDDEN'; END IF;
 IF TG_TABLE_NAME='datasets' THEN
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
   IF NEW.active_edition_id IS DISTINCT FROM OLD.active_edition_id AND NOT EXISTS(
     SELECT 1 FROM gis.environment WHERE singleton AND activation_enabled) THEN RAISE EXCEPTION 'GIS_ACTIVATION_DISABLED'; END IF;
   IF NEW.created_by IS DISTINCT FROM OLD.created_by AND NOT(NEW.created_by IS NULL AND pg_trigger_depth()>1) THEN
    RAISE EXCEPTION 'GIS_ACTOR_IMMUTABLE'; END IF;
  END IF;
 ELSIF TG_TABLE_NAME='editions' THEN
  IF NEW.input_hash IS DISTINCT FROM gis.manifest_hash(NEW.manifest) THEN RAISE EXCEPTION 'GIS_HASH_INVARIANT'; END IF;
  IF TG_OP='INSERT' THEN
   IF NEW.state<>'draft' OR NEW.input_revision<>1 OR NEW.validated_result_id IS NOT NULL THEN RAISE EXCEPTION 'GIS_EDITION_INVARIANT'; END IF;
  ELSE
   IF ROW(NEW.id,NEW.dataset_id,NEW.cloned_from_id,NEW.created_at)
       IS DISTINCT FROM ROW(OLD.id,OLD.dataset_id,OLD.cloned_from_id,OLD.created_at) THEN RAISE EXCEPTION 'GIS_EDITION_IDENTITY_IMMUTABLE'; END IF;
   IF NEW.manifest IS DISTINCT FROM OLD.manifest OR NEW.input_hash IS DISTINCT FROM OLD.input_hash OR NEW.input_revision<>OLD.input_revision THEN
    IF OLD.state<>'draft' OR NEW.state<>'draft' OR NEW.input_revision<>OLD.input_revision+1 THEN RAISE EXCEPTION 'GIS_INPUT_IMMUTABLE'; END IF;
   END IF;
   IF NEW.state<>OLD.state AND NOT((OLD.state='draft' AND NEW.state IN ('validating','withdrawn'))
      OR (OLD.state='validating' AND NEW.state IN ('draft','validated')) OR (OLD.state='validated' AND NEW.state='withdrawn')) THEN
    RAISE EXCEPTION 'GIS_STATE_TRANSITION'; END IF;
   IF NEW.created_by IS DISTINCT FROM OLD.created_by AND NOT(NEW.created_by IS NULL AND pg_trigger_depth()>1) THEN
    RAISE EXCEPTION 'GIS_ACTOR_IMMUTABLE'; END IF;
  END IF;
 ELSIF TG_TABLE_NAME IN ('audit','receipts','results') THEN
  IF TG_OP='UPDATE' AND NOT(TG_TABLE_NAME IN ('audit','receipts') AND pg_trigger_depth()>1
      AND (to_jsonb(NEW)-'actor_id'-'subject_id')=(to_jsonb(OLD)-'actor_id'-'subject_id')
      AND (to_jsonb(NEW)->'actor_id') IN (to_jsonb(OLD)->'actor_id','null'::jsonb)
      AND COALESCE(to_jsonb(NEW)->'subject_id','null') IN (COALESCE(to_jsonb(OLD)->'subject_id','null'),'null'::jsonb)) THEN
   RAISE EXCEPTION 'GIS_HISTORY_IMMUTABLE'; END IF;
 ELSIF TG_TABLE_NAME='attempts' THEN
  IF TG_OP='INSERT' THEN
   IF NEW.state<>'running' OR NEW.progress<>0 THEN RAISE EXCEPTION 'GIS_ATTEMPT_INVARIANT'; END IF;
  ELSE
   IF ROW(NEW.id,NEW.job_id,NEW.attempt_no,NEW.worker_id,NEW.lease_token,NEW.started_at)
      IS DISTINCT FROM ROW(OLD.id,OLD.job_id,OLD.attempt_no,OLD.worker_id,OLD.lease_token,OLD.started_at)
      OR OLD.state<>'running' OR NEW.progress<OLD.progress THEN RAISE EXCEPTION 'GIS_ATTEMPT_IMMUTABLE'; END IF;
  END IF;
 ELSIF TG_TABLE_NAME='jobs' THEN
  IF TG_OP='INSERT' THEN
   IF NEW.state<>'queued' OR NEW.attempt_count<>0 THEN RAISE EXCEPTION 'GIS_JOB_INVARIANT'; END IF;
   IF NEW.parent_job_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM gis.jobs p
      WHERE p.id=NEW.parent_job_id AND p.parent_job_id IS NULL AND p.state='failed'
       AND p.error_code IN ('transient','attempts_exhausted') AND p.edition_id=NEW.edition_id
       AND p.input_revision=NEW.input_revision AND p.input_hash=NEW.input_hash AND p.validator_version=NEW.validator_version) THEN
    RAISE EXCEPTION 'GIS_RETRY_INVARIANT'; END IF;
  ELSE
   IF ROW(NEW.id,NEW.edition_id,NEW.parent_job_id,NEW.kind,NEW.input_revision,NEW.input_hash,NEW.validator_version,NEW.created_at)
       IS DISTINCT FROM ROW(OLD.id,OLD.edition_id,OLD.parent_job_id,OLD.kind,OLD.input_revision,OLD.input_hash,OLD.validator_version,OLD.created_at) THEN
    RAISE EXCEPTION 'GIS_JOB_INPUT_IMMUTABLE'; END IF;
   IF OLD.state IN ('succeeded','failed') AND (to_jsonb(NEW)-'requested_by') IS DISTINCT FROM (to_jsonb(OLD)-'requested_by') THEN
    RAISE EXCEPTION 'GIS_JOB_TERMINAL_IMMUTABLE'; END IF;
   IF NEW.state<>OLD.state AND NOT((OLD.state='queued' AND NEW.state='running') OR (OLD.state='running' AND NEW.state IN ('queued','succeeded','failed'))) THEN
    RAISE EXCEPTION 'GIS_JOB_TRANSITION'; END IF;
   IF (OLD.state='queued' AND NEW.state='running' AND NEW.attempt_count<>OLD.attempt_count+1)
      OR (NOT(OLD.state='queued' AND NEW.state='running') AND NEW.attempt_count<>OLD.attempt_count) THEN
    RAISE EXCEPTION 'GIS_ATTEMPT_INVARIANT'; END IF;
   IF NEW.requested_by IS DISTINCT FROM OLD.requested_by AND NOT(NEW.requested_by IS NULL AND pg_trigger_depth()>1) THEN
    RAISE EXCEPTION 'GIS_ACTOR_IMMUTABLE'; END IF;
  END IF;
 END IF;
 RETURN NEW;
END $f$;

CREATE FUNCTION gis.check_catalog() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE eid uuid; e gis.editions%ROWTYPE; d gis.datasets%ROWTYPE;
BEGIN
 IF TG_TABLE_NAME='datasets' THEN
  SELECT * INTO d FROM gis.datasets WHERE id=NEW.id;
  IF d.active_edition_id IS NOT NULL AND NOT gis.eligible(d.active_edition_id,d.id) THEN RAISE EXCEPTION 'GIS_ACTIVE_INVARIANT'; END IF;
  RETURN NULL;
 END IF;
 IF TG_TABLE_NAME='editions' THEN eid:=NEW.id;
 ELSIF TG_TABLE_NAME='attempts' THEN SELECT edition_id INTO eid FROM gis.jobs WHERE id=NEW.job_id;
 ELSE eid:=NEW.edition_id; END IF;
 SELECT * INTO e FROM gis.editions WHERE id=eid;
 IF NOT FOUND THEN RETURN NULL; END IF;
 IF (e.state='validating') IS DISTINCT FROM EXISTS(SELECT 1 FROM gis.jobs WHERE edition_id=e.id AND state IN ('queued','running')) THEN
  RAISE EXCEPTION 'GIS_QUEUE_EDITION_INVARIANT'; END IF;
 IF e.state='validated' AND NOT gis.eligible(e.id,e.dataset_id) THEN RAISE EXCEPTION 'GIS_VALIDATION_INVARIANT'; END IF;
 IF e.state IN ('draft','validating') AND e.validated_result_id IS NOT NULL THEN RAISE EXCEPTION 'GIS_RESULT_INVARIANT'; END IF;
 IF EXISTS(SELECT 1 FROM gis.datasets WHERE active_edition_id=e.id) AND NOT gis.eligible(e.id,e.dataset_id) THEN
  RAISE EXCEPTION 'GIS_ACTIVE_INVARIANT'; END IF;
 IF EXISTS(SELECT 1 FROM gis.jobs j LEFT JOIN gis.results r ON r.job_id=j.id
   WHERE j.edition_id=e.id AND ((j.state='succeeded') IS DISTINCT FROM (r.id IS NOT NULL)
     OR (r.id IS NOT NULL AND (r.edition_id<>j.edition_id OR r.input_revision<>j.input_revision OR r.input_hash<>j.input_hash
       OR r.validator_version<>j.validator_version OR r.attempt_no<>j.attempt_count
       OR NOT EXISTS(SELECT 1 FROM gis.attempts a WHERE a.job_id=j.id AND a.attempt_no=r.attempt_no AND a.lease_token=r.lease_token AND a.state='succeeded'))))) THEN
  RAISE EXCEPTION 'GIS_JOB_RESULT_INVARIANT'; END IF;
 IF EXISTS(SELECT 1 FROM gis.jobs j WHERE j.edition_id=e.id AND (
    j.attempt_count<>(SELECT count(*) FROM gis.attempts a WHERE a.job_id=j.id)
    OR (j.state='running' AND NOT EXISTS(SELECT 1 FROM gis.attempts a WHERE a.job_id=j.id
      AND a.attempt_no=j.attempt_count AND a.lease_token=j.lease_token AND a.worker_id=j.worker_id AND a.state='running'))
    OR (j.state<>'running' AND EXISTS(SELECT 1 FROM gis.attempts a WHERE a.job_id=j.id AND a.state='running')))) THEN
  RAISE EXCEPTION 'GIS_ATTEMPT_INVARIANT'; END IF;
 RETURN NULL;
END $f$;

DO $triggers$
DECLARE t text;
BEGIN
 FOREACH t IN ARRAY ARRAY['datasets','editions','jobs','attempts','results','audit','receipts'] LOOP
  EXECUTE format('CREATE TRIGGER immutable_row BEFORE INSERT OR UPDATE OR DELETE ON gis.%I FOR EACH ROW EXECUTE FUNCTION gis.guard_row()',t);
 END LOOP;
 FOREACH t IN ARRAY ARRAY['datasets','editions','jobs','attempts','results'] LOOP
  EXECUTE format('CREATE CONSTRAINT TRIGGER catalog_integrity AFTER INSERT OR UPDATE ON gis.%I DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION gis.check_catalog()',t);
 END LOOP;
END $triggers$;

CREATE FUNCTION gis.command(p_actor uuid,p_request_id uuid,p_operation text,p_payload jsonb,p_backend_sandbox boolean)
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

CREATE FUNCTION gis.read(p_actor uuid,p_kind text,p_payload jsonb DEFAULT '{}') RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE is_admin boolean; rows_value jsonb; limit_value integer; table_name text; time_column text;
 filter_column text; filter_value uuid; cursor_time timestamptz; cursor_id uuid; last_value jsonb; more boolean;
BEGIN
 PERFORM gis.assert_environment();
 IF p_kind='me' THEN
  PERFORM gis.keys(p_payload,ARRAY[]::text[]);
  IF NOT EXISTS(SELECT 1 FROM public.profiles WHERE id=p_actor) THEN RAISE EXCEPTION 'GIS_FORBIDDEN' USING ERRCODE='42501'; END IF;
  RETURN jsonb_build_object('admin',EXISTS(SELECT 1 FROM public.profiles WHERE id=p_actor AND role='admin'),
   'officer',EXISTS(SELECT 1 FROM gis.officers WHERE user_id=p_actor),'synthetic_only',true,
   'activation_enabled',(SELECT activation_enabled FROM gis.environment WHERE singleton));
 END IF;
 is_admin:=gis.authorize(p_actor,p_kind='officers');
 PERFORM gis.keys(p_payload,ARRAY['id','dataset_id','edition_id','job_id','limit','cursor']);
 IF p_kind='provinces' THEN
  SELECT COALESCE(jsonb_agg(to_jsonb(p) ORDER BY p.name_en),'[]') INTO rows_value FROM public.provinces p;
  RETURN jsonb_build_object('data',rows_value,'next_cursor',NULL,'has_more',false);
 ELSIF p_kind='fixtures' THEN
  SELECT COALESCE(jsonb_agg(to_jsonb(f) ORDER BY f.id),'[]') INTO rows_value FROM gis.synthetic_fixtures f;
  RETURN jsonb_build_object('data',rows_value,'next_cursor',NULL,'has_more',false);
 ELSIF p_kind='officers' THEN
  SELECT COALESCE(jsonb_agg(to_jsonb(o) ORDER BY o.created_at,o.user_id),'[]') INTO rows_value FROM gis.officers o;
  RETURN jsonb_build_object('data',rows_value,'next_cursor',NULL,'has_more',false);
 END IF;
 table_name:=CASE p_kind WHEN 'datasets' THEN 'datasets' WHEN 'dataset' THEN 'datasets'
  WHEN 'editions' THEN 'editions' WHEN 'edition' THEN 'editions' WHEN 'jobs' THEN 'jobs' WHEN 'job' THEN 'jobs'
  WHEN 'attempts' THEN 'attempts' WHEN 'history' THEN 'audit' END;
 IF table_name IS NULL THEN RAISE EXCEPTION 'GIS_UNKNOWN_READ'; END IF;
 IF p_kind IN ('dataset','edition','job') THEN
  EXECUTE format('SELECT to_jsonb(t)-''lease_token''-''worker_id'' FROM gis.%I t WHERE id=$1',table_name)
   INTO rows_value USING (p_payload->>'id')::uuid;
  IF rows_value IS NULL THEN RAISE EXCEPTION 'GIS_NOT_FOUND'; END IF;
  RETURN rows_value;
 END IF;
 limit_value:=COALESCE((p_payload->>'limit')::integer,20);
 IF limit_value NOT BETWEEN 1 AND 100 THEN RAISE EXCEPTION 'GIS_INVALID_LIMIT'; END IF;
 time_column:=CASE WHEN table_name='attempts' THEN 'started_at' ELSE 'created_at' END;
 IF p_payload->'cursor' IS NOT NULL AND p_payload->'cursor'<>'null'::jsonb THEN
  PERFORM gis.keys(p_payload->'cursor',ARRAY['created_at','id']);
  cursor_time:=(p_payload->'cursor'->>'created_at')::timestamptz;cursor_id:=(p_payload->'cursor'->>'id')::uuid;
  IF cursor_time IS NULL OR cursor_id IS NULL THEN RAISE EXCEPTION 'GIS_INVALID_CURSOR'; END IF;
 END IF;
 filter_column:=CASE WHEN p_kind='editions' THEN 'dataset_id' WHEN p_kind='attempts' THEN 'job_id'
  WHEN p_kind='history' THEN 'edition_id' ELSE 'id' END;
 filter_value:=CASE WHEN p_kind='editions' THEN (p_payload->>'dataset_id')::uuid
  WHEN p_kind='attempts' THEN (p_payload->>'job_id')::uuid WHEN p_kind='history' THEN (p_payload->>'edition_id')::uuid END;
 EXECUTE format('SELECT COALESCE(jsonb_agg(obj ORDER BY stamp,id),''[]''::jsonb) FROM
  (SELECT to_jsonb(t)-''lease_token''-''worker_id'' AS obj,%I AS stamp,id FROM gis.%I t
   WHERE ($1::uuid IS NULL OR %I=$1) AND ($2::timestamptz IS NULL OR (%I,id)>($2,$3))
   ORDER BY %I,id LIMIT $4) page',time_column,table_name,filter_column,time_column,time_column)
  INTO rows_value USING filter_value,cursor_time,cursor_id,limit_value+1;
 more:=jsonb_array_length(rows_value)>limit_value;
 IF more THEN rows_value:=rows_value-limit_value; END IF;
 last_value:=rows_value->(jsonb_array_length(rows_value)-1);
 RETURN jsonb_build_object('data',rows_value,'has_more',more,'next_cursor',CASE WHEN more THEN
   jsonb_build_object('created_at',last_value->>time_column,'id',last_value->>'id') ELSE NULL END);
END $f$;

CREATE FUNCTION public.gis_command(p_actor uuid,p_request_id uuid,p_operation text,p_payload jsonb DEFAULT '{}',p_backend_sandbox boolean DEFAULT false)
RETURNS jsonb LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,gis
AS $f$ SELECT gis.command(p_actor,p_request_id,p_operation,p_payload,p_backend_sandbox) $f$;
CREATE FUNCTION public.gis_read(p_actor uuid,p_kind text,p_payload jsonb DEFAULT '{}')
RETURNS jsonb LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,gis
AS $f$ SELECT gis.read(p_actor,p_kind,p_payload) $f$;
CREATE FUNCTION public.gis_worker(p_action text,p_payload jsonb DEFAULT '{}')
RETURNS jsonb LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,gis
AS $f$ SELECT gis.worker(p_action,p_payload) $f$;

REVOKE ALL ON ALL FUNCTIONS IN SCHEMA gis FROM PUBLIC,anon,authenticated,service_role,gis_worker;
REVOKE ALL ON FUNCTION public.gis_command(uuid,uuid,text,jsonb,boolean) FROM PUBLIC,anon,authenticated,service_role,gis_worker;
REVOKE ALL ON FUNCTION public.gis_read(uuid,text,jsonb) FROM PUBLIC,anon,authenticated,service_role,gis_worker;
REVOKE ALL ON FUNCTION public.gis_worker(text,jsonb) FROM PUBLIC,anon,authenticated,service_role,gis_worker;
GRANT EXECUTE ON FUNCTION public.gis_command(uuid,uuid,text,jsonb,boolean),public.gis_read(uuid,text,jsonb) TO service_role;
GRANT EXECUTE ON FUNCTION public.gis_worker(text,jsonb) TO gis_worker;
GRANT USAGE ON SCHEMA public TO gis_worker;
RESET ROLE;
REVOKE CREATE ON SCHEMA public FROM gis_owner;
