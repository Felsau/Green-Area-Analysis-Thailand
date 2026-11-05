-- A6.4d-1 Local offline safety rehearsal. No approved Cloud identity or network.
DO $guard$ BEGIN
 IF current_database() NOT IN ('postgres','gis_t1_upgrade') OR current_setting('cluster_name')<>'green-area-gis-t0'
 OR NOT EXISTS(SELECT 1 FROM gis.environment WHERE singleton AND NOT activation_enabled
 AND runtime_instance=current_setting('gis.runtime_instance',true) AND baseline_fingerprint=current_setting('gis.baseline_fingerprint',true))
 OR NOT EXISTS(SELECT 1 FROM gis.schema_migrations WHERE version=44 AND sha256='874919e286d7870e61f0374502a513a53ca06d6085fd9ba0b2e17df329a08a9a')
 OR EXISTS(SELECT 1 FROM gis.schema_migrations WHERE version>=45) THEN RAISE EXCEPTION 'GIS_LOCAL_BASELINE_044_REQUIRED'; END IF;
END $guard$;
DO $role$ BEGIN
 IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='gis_gee_safety_worker') THEN
  IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='gis_gee_safety_worker' AND NOT rolsuper AND NOT rolbypassrls
   AND NOT rolcanlogin AND NOT rolcreatedb AND NOT rolcreaterole AND NOT rolreplication AND NOT rolinherit
   AND shobj_description(oid,'pg_authid')='gis-a6.4d1-rehearsal-only')
   OR EXISTS(SELECT 1 FROM pg_auth_members WHERE member='gis_gee_safety_worker'::regrole)
   OR EXISTS(SELECT 1 FROM pg_auth_members WHERE roleid='gis_gee_safety_worker'::regrole AND member NOT IN ('postgres'::regrole,'authenticator'::regrole))
   THEN RAISE EXCEPTION 'GIS_SAFETY_ROLE_COLLISION'; END IF;
 ELSE CREATE ROLE gis_gee_safety_worker NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOREPLICATION NOINHERIT;
 END IF;
END $role$;
COMMENT ON ROLE gis_gee_safety_worker IS 'gis-a6.4d1-rehearsal-only';
GRANT gis_gee_safety_worker TO authenticator WITH INHERIT FALSE, SET TRUE;
GRANT USAGE ON SCHEMA public TO gis_gee_safety_worker;
REVOKE ALL ON SCHEMA gis FROM gis_gee_safety_worker;
GRANT CREATE ON SCHEMA public TO gis_owner;
SET LOCAL ROLE gis_owner;
SELECT gis.assert_environment();

CREATE FUNCTION gis.safety_policy() RETURNS jsonb LANGUAGE sql IMMUTABLE SET search_path=pg_catalog AS $f$
 SELECT '{"schema_version":1,"kind":"unapproved","project_id":null,"project_number":null,"google_principal":null,"account_verified":false,"transport_verified":false,"live_enabled":false}'::jsonb
$f$;
CREATE TABLE gis.gee_safety_sessions(
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),actor_id uuid NOT NULL REFERENCES public.profiles(id),
 bound_worker uuid NOT NULL REFERENCES public.profiles(id),policy jsonb NOT NULL CHECK(policy=gis.safety_policy()),
 policy_sha256 text NOT NULL CHECK(policy_sha256=encode(sha256(convert_to(gis.gee_live_canonical(policy),'UTF8')),'hex')),
 started_at timestamptz NOT NULL,ends_at timestamptz NOT NULL CHECK(ends_at=started_at+interval '20 minutes'),
 state text NOT NULL DEFAULT 'open' CHECK(state IN ('open','stopped','expired','exhausted')),
 stopped_at timestamptz,stop_reason text CHECK(stop_reason IN ('operator_stop','window_expired','request_budget_exhausted')),
 CHECK((state='open' AND stopped_at IS NULL AND stop_reason IS NULL) OR (state<>'open' AND stopped_at IS NOT NULL AND stop_reason IS NOT NULL)));
CREATE TABLE gis.gee_safety_jobs(
 job_id uuid PRIMARY KEY REFERENCES gis.jobs(id),session_id uuid NOT NULL REFERENCES gis.gee_safety_sessions(id),
 UNIQUE(session_id,job_id));
CREATE TABLE gis.gee_safety_requests(
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),session_id uuid NOT NULL,job_id uuid NOT NULL,
 attempt_no integer NOT NULL CHECK(attempt_no BETWEEN 1 AND 2),lease_token uuid NOT NULL,worker_id uuid NOT NULL,
 request_key uuid NOT NULL,kind text NOT NULL CHECK(kind IN ('compute','reference','sdk_retry','discovery')),
 state text NOT NULL DEFAULT 'reserved' CHECK(state IN ('reserved','attempted','completed','uncertain')),
 reserved_at timestamptz NOT NULL DEFAULT clock_timestamp(),attempted_at timestamptz,finished_at timestamptz,
 evidence_sha256 text CHECK(evidence_sha256 ~ '^[0-9a-f]{64}$'),
 UNIQUE(session_id,request_key),
 FOREIGN KEY(session_id,job_id) REFERENCES gis.gee_safety_jobs(session_id,job_id),
 FOREIGN KEY(job_id,attempt_no,lease_token) REFERENCES gis.attempts(job_id,attempt_no,lease_token),
 CHECK((state='reserved' AND attempted_at IS NULL AND finished_at IS NULL AND evidence_sha256 IS NULL)
 OR (state='attempted' AND attempted_at IS NOT NULL AND finished_at IS NULL AND evidence_sha256 IS NULL)
 OR (state='completed' AND attempted_at IS NOT NULL AND finished_at IS NOT NULL AND evidence_sha256 IS NOT NULL)
 OR (state='uncertain' AND finished_at IS NOT NULL AND evidence_sha256 IS NULL)));
CREATE INDEX safety_requests_attempt ON gis.gee_safety_requests(job_id,attempt_no,lease_token);
DO $rls$ DECLARE t text; BEGIN
 FOREACH t IN ARRAY ARRAY['gee_safety_sessions','gee_safety_jobs','gee_safety_requests'] LOOP
  EXECUTE format('ALTER TABLE gis.%I ENABLE ROW LEVEL SECURITY',t);
  EXECUTE format('ALTER TABLE gis.%I FORCE ROW LEVEL SECURITY',t);
  EXECUTE format('CREATE POLICY owner_access ON gis.%I TO gis_owner USING(true) WITH CHECK(true)',t);
  EXECUTE format('REVOKE ALL ON gis.%I FROM PUBLIC,anon,authenticated,service_role,gis_worker,gis_native_worker,gis_gee_mock_worker,gis_gee_live_worker,gis_gee_safety_worker',t);
 END LOOP;
END $rls$;
CREATE FUNCTION gis.safety_mutation_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'GIS_SAFETY_HISTORY_IMMUTABLE'; END IF;
 IF TG_TABLE_NAME='gee_safety_sessions' THEN
  IF TG_OP='INSERT' THEN
   IF NEW.started_at>clock_timestamp() OR NEW.state<>'open' THEN RAISE EXCEPTION 'GIS_SAFETY_SESSION_INVALID'; END IF;
  ELSIF (to_jsonb(NEW)-ARRAY['state','stopped_at','stop_reason']) IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['state','stopped_at','stop_reason'])
   OR OLD.state<>'open' OR NEW.state='open' THEN RAISE EXCEPTION 'GIS_SAFETY_SESSION_IMMUTABLE'; END IF;
 ELSIF TG_TABLE_NAME='gee_safety_jobs' THEN
  IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'GIS_SAFETY_HISTORY_IMMUTABLE'; END IF;
  PERFORM 1 FROM gis.gee_safety_sessions WHERE id=NEW.session_id FOR UPDATE;
  IF (SELECT count(*) FROM gis.gee_safety_jobs WHERE session_id=NEW.session_id)>=4 THEN RAISE EXCEPTION 'GIS_SAFETY_JOB_BUDGET'; END IF;
 ELSE
  IF TG_OP='INSERT' THEN
   PERFORM 1 FROM gis.gee_safety_sessions WHERE id=NEW.session_id FOR UPDATE;
   IF NEW.state<>'reserved' OR (SELECT count(*) FROM gis.gee_safety_requests WHERE session_id=NEW.session_id)>=32 THEN RAISE EXCEPTION 'GIS_SAFETY_REQUEST_BUDGET'; END IF;
  ELSIF (to_jsonb(NEW)-ARRAY['state','attempted_at','finished_at','evidence_sha256']) IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['state','attempted_at','finished_at','evidence_sha256'])
   OR NOT ((OLD.state='reserved' AND NEW.state IN ('attempted','uncertain')) OR (OLD.state='attempted' AND NEW.state IN ('completed','uncertain')))
   OR (OLD.attempted_at IS NOT NULL AND OLD.attempted_at IS DISTINCT FROM NEW.attempted_at)
  THEN RAISE EXCEPTION 'GIS_SAFETY_HISTORY_IMMUTABLE'; END IF;
 END IF;
 RETURN NEW;
END $f$;
DO $guard_triggers$ DECLARE t text; BEGIN
 FOREACH t IN ARRAY ARRAY['gee_safety_sessions','gee_safety_jobs','gee_safety_requests'] LOOP
  EXECUTE format('CREATE TRIGGER safety_history BEFORE INSERT OR UPDATE OR DELETE ON gis.%I FOR EACH ROW EXECUTE FUNCTION gis.safety_mutation_guard()',t);
 END LOOP;
END $guard_triggers$;

CREATE FUNCTION gis.safety_session(p_actor uuid,p_worker uuid) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE result uuid; start_value timestamptz:=clock_timestamp();v jsonb:=gis.safety_policy();
BEGIN
 PERFORM gis.authorize(p_actor,false);
 INSERT INTO gis.gee_safety_sessions(actor_id,bound_worker,policy,policy_sha256,started_at,ends_at)
 VALUES(p_actor,p_worker,v,encode(sha256(convert_to(gis.gee_live_canonical(v),'UTF8')),'hex'),start_value,start_value+interval '20 minutes') RETURNING id INTO result;
 INSERT INTO gis.audit(actor_id,operation,detail) VALUES(p_actor,'safety.session',jsonb_build_object('session_id',result,'execution','rehearsal','live_enabled',false));
 RETURN result;
END $f$;
CREATE FUNCTION gis.safety_manifest(p_input uuid,p_session uuid) RETURNS jsonb
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
 SELECT jsonb_build_object('schema_version',8,'provider','gee_safety_rehearsal','execution','rehearsal',
 'input_id',i.id,'session_id',s.id,'policy_sha256',s.policy_sha256,'semantic_request_sha256',i.value->>'request_sha256',
 'geometry_sha256',i.value->>'geometry_sha256','method_version',i.value->'request'->>'method_version')
 FROM gis.gee_live_inputs i CROSS JOIN gis.gee_safety_sessions s WHERE i.id=p_input AND s.id=p_session
$f$;
ALTER FUNCTION gis.manifest_hash(jsonb) RENAME TO a64d1_previous_manifest_hash;
CREATE FUNCTION gis.manifest_hash(p_manifest jsonb) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
BEGIN
 IF p_manifest->'schema_version' IS DISTINCT FROM '8'::jsonb THEN RETURN gis.a64d1_previous_manifest_hash(p_manifest); END IF;
 IF p_manifest IS NULL OR p_manifest IS DISTINCT FROM gis.safety_manifest((p_manifest->>'input_id')::uuid,(p_manifest->>'session_id')::uuid)
 THEN RAISE EXCEPTION 'GIS_SAFETY_MANIFEST_INVALID'; END IF;
 RETURN encode(sha256(convert_to(p_manifest::text,'UTF8')),'hex');
END $f$;
ALTER FUNCTION gis.edition_protocol(uuid) RENAME TO a64d1_previous_edition_protocol;
CREATE FUNCTION gis.edition_protocol(p_edition uuid) RETURNS text
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
 SELECT CASE WHEN manifest->'schema_version'='8'::jsonb THEN CASE WHEN EXISTS(SELECT 1 FROM gis.gee_safety_jobs b JOIN gis.jobs j ON j.id=b.job_id WHERE j.edition_id=e.id) THEN 'gee_safety_rehearsal' ELSE 'unsupported' END
 ELSE gis.a64d1_previous_edition_protocol(p_edition) END FROM gis.editions e WHERE id=p_edition
$f$;
ALTER FUNCTION gis.eligible(uuid,uuid) RENAME TO a64d1_previous_eligible;
CREATE FUNCTION gis.eligible(p_edition uuid,p_dataset uuid) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
 SELECT CASE WHEN EXISTS(SELECT 1 FROM gis.editions WHERE id=p_edition AND manifest->'schema_version'='8'::jsonb) THEN false ELSE gis.a64d1_previous_eligible(p_edition,p_dataset) END
$f$;

CREATE FUNCTION gis.safety_enqueue(p_actor uuid,p_key uuid,p_input uuid,p_session uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE s gis.gee_safety_sessions%ROWTYPE;i gis.gee_live_inputs%ROWTYPE;q gis.gee_live_requests%ROWTYPE;
 d gis.datasets%ROWTYPE;e gis.editions%ROWTYPE;j gis.jobs%ROWTYPE;r gis.receipts%ROWTYPE;m jsonb;body jsonb;h text;
BEGIN
 PERFORM gis.authorize(p_actor,false);
 IF p_key IS NULL THEN RAISE EXCEPTION 'GIS_REQUEST_ID_REQUIRED'; END IF;
 h:=encode(sha256(convert_to(jsonb_build_array(p_input,p_session)::text,'UTF8')),'hex');
 PERFORM pg_advisory_xact_lock(hashtextextended(p_actor::text||':'||p_key::text,0));
 SELECT * INTO r FROM gis.receipts WHERE actor_id=p_actor AND request_id=p_key;
 IF FOUND THEN
  IF r.operation<>'safety.create' OR r.payload_hash<>h THEN RAISE EXCEPTION 'GIS_IDEMPOTENCY_CONFLICT'; END IF;
  RETURN r.body;
 END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('safety-input:'||p_input::text,0));
 SELECT * INTO i FROM gis.gee_live_inputs WHERE id=p_input;
 IF NOT FOUND THEN RAISE EXCEPTION 'GIS_SAFETY_INPUT_REQUIRED'; END IF;
 SELECT * INTO q FROM gis.gee_live_requests WHERE input_id=p_input;
 IF FOUND THEN
  IF NOT EXISTS(SELECT 1 FROM gis.gee_safety_jobs WHERE job_id=q.job_id AND session_id=p_session) THEN RAISE EXCEPTION 'GIS_IDEMPOTENCY_CONFLICT'; END IF;
  body:=jsonb_build_object('job_id',q.job_id,'edition_id',q.edition_id,'dataset_id',q.dataset_id,'session_id',p_session);
 ELSE
  PERFORM pg_advisory_xact_lock(hashtextextended('gis-processing-dataset:'||(i.value->'request'->'scope'->>'province')||':'||(i.value->'request'->'period'->>'year')||':'||(i.value->'request'->'period'->>'month')||':'||(i.value->'request'->>'product'),0));
  INSERT INTO gis.datasets(province,data_year,month,kind,purpose,title,created_by)
   VALUES(i.value->'request'->'scope'->>'province',(i.value->'request'->'period'->>'year')::integer,(i.value->'request'->'period'->>'month')::integer,'geotiff',i.value->'request'->>'product','Offline safety rehearsal',p_actor) ON CONFLICT(province,data_year,month,kind,purpose) DO NOTHING;
  SELECT * INTO d FROM gis.datasets WHERE province=i.value->'request'->'scope'->>'province' AND data_year=(i.value->'request'->'period'->>'year')::integer AND month=(i.value->'request'->'period'->>'month')::integer AND kind='geotiff' AND purpose=i.value->'request'->>'product' FOR NO KEY UPDATE;
  SELECT * INTO s FROM gis.gee_safety_sessions WHERE id=p_session FOR UPDATE;
  IF NOT FOUND OR s.actor_id<>p_actor OR s.state<>'open' OR s.ends_at<=clock_timestamp() OR s.policy<>gis.safety_policy() THEN RAISE EXCEPTION 'GIS_SAFETY_SESSION_CLOSED'; END IF;
  IF (SELECT count(*) FROM gis.gee_safety_jobs WHERE session_id=s.id)>=4 THEN RAISE EXCEPTION 'GIS_SAFETY_JOB_BUDGET'; END IF;
  m:=gis.safety_manifest(p_input,p_session);
  INSERT INTO gis.editions(dataset_id,manifest,input_hash,created_by) VALUES(d.id,m,gis.manifest_hash(m),p_actor) RETURNING * INTO e;
  INSERT INTO gis.jobs(edition_id,kind,validator_version,input_revision,input_hash,requested_by) VALUES(e.id,'process_gee_safety_edition','gee-safety-rehearsal-v1',1,e.input_hash,p_actor) RETURNING * INTO j;
  INSERT INTO gis.gee_live_requests(input_id,dataset_id,edition_id,job_id,requested_by) VALUES(p_input,d.id,e.id,j.id,p_actor);
  INSERT INTO gis.gee_safety_jobs(job_id,session_id) VALUES(j.id,p_session);
  UPDATE gis.editions SET state='validating' WHERE id=e.id;
  body:=jsonb_build_object('job_id',j.id,'edition_id',e.id,'dataset_id',d.id,'session_id',s.id);
 END IF;
 body:=body||jsonb_build_object('execution','rehearsal','live_enabled',false,'publishable',false);
 INSERT INTO gis.receipts(actor_id,request_id,operation,payload_hash,status,body) VALUES(p_actor,p_key,'safety.create',h,202,body);
 INSERT INTO gis.audit(actor_id,operation,dataset_id,edition_id,job_id,detail) VALUES(p_actor,'safety.create',(body->>'dataset_id')::uuid,(body->>'edition_id')::uuid,(body->>'job_id')::uuid,jsonb_build_object('session_id',p_session));
 RETURN body;
END $f$;

-- Every work path locks Edition -> Job -> Session -> Reservation, never reverse.
CREATE FUNCTION gis.safety_lock(p_job uuid,p_worker uuid,p_token uuid,p_active boolean DEFAULT true) RETURNS gis.gee_safety_sessions
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE j gis.jobs%ROWTYPE;s gis.gee_safety_sessions%ROWTYPE;started timestamptz;
BEGIN
 PERFORM gis.assert_environment();
 PERFORM 1 FROM gis.editions e JOIN gis.jobs q ON q.edition_id=e.id WHERE q.id=p_job FOR UPDATE OF e;
 SELECT * INTO j FROM gis.jobs WHERE id=p_job FOR UPDATE;
 IF NOT FOUND OR j.kind<>'process_gee_safety_edition' OR j.state<>'running' OR j.worker_id IS DISTINCT FROM p_worker OR j.lease_token IS DISTINCT FROM p_token OR j.lease_until<=clock_timestamp() THEN RAISE EXCEPTION 'GIS_STALE_LEASE'; END IF;
 SELECT x.* INTO s FROM gis.gee_safety_sessions x JOIN gis.gee_safety_jobs b ON b.session_id=x.id WHERE b.job_id=p_job FOR UPDATE OF x;
 IF NOT FOUND OR s.bound_worker IS DISTINCT FROM p_worker OR s.policy IS DISTINCT FROM gis.safety_policy() THEN RAISE EXCEPTION 'GIS_SAFETY_WORKER_MISMATCH'; END IF;
 IF p_active THEN
  IF s.state<>'open' OR s.ends_at<=clock_timestamp() THEN RAISE EXCEPTION 'GIS_SAFETY_SESSION_CLOSED'; END IF;
  SELECT min(started_at) INTO started FROM gis.attempts WHERE job_id=j.id;
  IF started IS NULL OR started+interval '180 seconds'<=clock_timestamp() THEN RAISE EXCEPTION 'GIS_SAFETY_JOB_TIMEOUT'; END IF;
 END IF;
 RETURN s;
END $f$;
CREATE FUNCTION gis.safety_claim_guard(p_job uuid,p_worker uuid) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE s gis.gee_safety_sessions%ROWTYPE;
BEGIN
 SELECT x.* INTO s FROM gis.gee_safety_sessions x JOIN gis.gee_safety_jobs b ON b.session_id=x.id WHERE b.job_id=p_job FOR UPDATE OF x;
 IF NOT FOUND OR s.bound_worker IS DISTINCT FROM p_worker OR s.state<>'open' OR s.ends_at<=clock_timestamp() OR s.policy IS DISTINCT FROM gis.safety_policy() THEN RAISE EXCEPTION 'GIS_SAFETY_SESSION_CLOSED'; END IF;
 IF EXISTS(SELECT 1 FROM gis.attempts WHERE job_id=p_job GROUP BY job_id HAVING min(started_at)+interval '180 seconds'<=clock_timestamp()) THEN RAISE EXCEPTION 'GIS_SAFETY_JOB_TIMEOUT'; END IF;
END $f$;
CREATE FUNCTION gis.safety_abandon(p_job uuid,p_attempt integer,p_token uuid) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
BEGIN
 PERFORM 1 FROM gis.gee_safety_sessions s JOIN gis.gee_safety_jobs b ON b.session_id=s.id WHERE b.job_id=p_job FOR UPDATE OF s;
 UPDATE gis.gee_safety_requests SET state='uncertain',finished_at=clock_timestamp(),evidence_sha256=NULL WHERE job_id=p_job AND attempt_no=p_attempt AND lease_token=p_token AND state IN ('reserved','attempted');
 INSERT INTO gis.audit(operation,job_id,detail) VALUES('safety.uncertainty',p_job,jsonb_build_object('attempt',p_attempt,'remote_cancellation_proven',false));
END $f$;

CREATE FUNCTION gis.safety_budget(p_worker uuid,p_action text,p_payload jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE s gis.gee_safety_sessions%ROWTYPE;j gis.jobs%ROWTYPE;r gis.gee_safety_requests%ROWTYPE;
 jid uuid:=(p_payload->>'job_id')::uuid;token uuid:=(p_payload->>'lease_token')::uuid;sha text;
BEGIN
 s:=gis.safety_lock(jid,p_worker,token,p_action<>'uncertain');
 SELECT * INTO j FROM gis.jobs WHERE id=jid;
 IF p_action='reserve' THEN
  PERFORM gis.keys(p_payload,ARRAY['job_id','lease_token','request_key','kind']);
  IF p_payload->>'request_key' IS NULL OR p_payload->>'kind' IS NULL OR p_payload->>'kind' NOT IN ('compute','sdk_retry','reference','discovery') THEN RAISE EXCEPTION 'GIS_SAFETY_REQUEST_INVALID'; END IF;
  SELECT * INTO r FROM gis.gee_safety_requests WHERE session_id=s.id AND request_key=(p_payload->>'request_key')::uuid FOR UPDATE;
  IF FOUND THEN
   IF r.job_id<>jid OR r.attempt_no<>j.attempt_count OR r.lease_token<>token OR r.worker_id<>p_worker OR r.kind<>p_payload->>'kind' THEN RAISE EXCEPTION 'GIS_IDEMPOTENCY_CONFLICT'; END IF;
   RETURN jsonb_build_object('request_id',r.id,'state',r.state,'replayed',true);
  END IF;
  IF (SELECT count(*) FROM gis.gee_safety_requests WHERE session_id=s.id)>=32 THEN
   UPDATE gis.gee_safety_sessions SET state='exhausted',stopped_at=clock_timestamp(),stop_reason='request_budget_exhausted' WHERE id=s.id;
   INSERT INTO gis.audit(operation,job_id,detail) VALUES('safety.exhausted',jid,jsonb_build_object('session_id',s.id,'consumed',32));
   RETURN jsonb_build_object('granted',false,'state','exhausted','consumed',32);
  END IF;
  INSERT INTO gis.gee_safety_requests(session_id,job_id,attempt_no,lease_token,worker_id,request_key,kind) VALUES(s.id,jid,j.attempt_count,token,p_worker,(p_payload->>'request_key')::uuid,p_payload->>'kind') RETURNING * INTO r;
 ELSE
  PERFORM gis.keys(p_payload,CASE WHEN p_action='finished' THEN ARRAY['job_id','lease_token','request_id','evidence_sha256'] ELSE ARRAY['job_id','lease_token','request_id'] END);
  SELECT * INTO r FROM gis.gee_safety_requests WHERE id=(p_payload->>'request_id')::uuid FOR UPDATE;
  IF NOT FOUND OR r.session_id<>s.id OR r.job_id<>jid OR r.worker_id<>p_worker OR r.attempt_no<>j.attempt_count OR r.lease_token<>token THEN RAISE EXCEPTION 'GIS_SAFETY_RESERVATION_MISMATCH'; END IF;
  IF p_action='attempted' THEN
   IF r.state<>'reserved' THEN RAISE EXCEPTION 'GIS_SAFETY_ONE_USE'; END IF;
   UPDATE gis.gee_safety_requests SET state='attempted',attempted_at=clock_timestamp() WHERE id=r.id RETURNING * INTO r;
  ELSIF p_action='finished' THEN
   sha:=p_payload->>'evidence_sha256';IF COALESCE(sha,'') !~ '^[0-9a-f]{64}$' THEN RAISE EXCEPTION 'GIS_SAFETY_EVIDENCE_REQUIRED'; END IF;
   IF r.state='completed' AND r.evidence_sha256=sha THEN RETURN jsonb_build_object('request_id',r.id,'state',r.state,'replayed',true); END IF;
   IF r.state<>'attempted' THEN RAISE EXCEPTION 'GIS_SAFETY_ONE_USE'; END IF;
   IF r.attempted_at+interval '120 seconds'<=clock_timestamp() THEN
    UPDATE gis.gee_safety_requests SET state='uncertain',finished_at=clock_timestamp() WHERE id=r.id RETURNING * INTO r;
   ELSE UPDATE gis.gee_safety_requests SET state='completed',finished_at=clock_timestamp(),evidence_sha256=sha WHERE id=r.id RETURNING * INTO r; END IF;
  ELSIF p_action='uncertain' THEN
   IF r.state IN ('reserved','attempted') THEN UPDATE gis.gee_safety_requests SET state='uncertain',finished_at=clock_timestamp() WHERE id=r.id RETURNING * INTO r; END IF;
  ELSE RAISE EXCEPTION 'GIS_SAFETY_ACTION_REJECTED'; END IF;
 END IF;
 INSERT INTO gis.audit(operation,job_id,detail) VALUES('safety.'||p_action,jid,jsonb_build_object('session_id',s.id,'request_id',r.id,'state',r.state,'kind',r.kind));
 RETURN jsonb_build_object('request_id',r.id,'state',r.state,'consumed',(SELECT count(*) FROM gis.gee_safety_requests WHERE session_id=s.id));
END $f$;

CREATE FUNCTION gis.validate_safety_report(p_report jsonb,p_edition gis.editions,p_job gis.jobs) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE s gis.gee_safety_sessions%ROWTYPE;v gis.jobs%ROWTYPE:=p_job;base jsonb;ids uuid[];n integer;
BEGIN
 PERFORM gis.keys(p_report,ARRAY['schema_version','protocol','execution','live_enabled','session_id','policy_sha256','valid','error_code','base','receipts','failure_kind']);
 SELECT x.* INTO s FROM gis.gee_safety_sessions x JOIN gis.gee_safety_jobs b ON b.session_id=x.id WHERE b.job_id=p_job.id;
 base:=p_report->'base';
 IF NOT p_report ? 'failure_kind' OR (p_report->'failure_kind' IS DISTINCT FROM 'null'::jsonb AND p_report->>'failure_kind' NOT IN ('request_timeout','job_timeout','lease_expired','budget_exhausted','session_stopped','accounting_uncertain','transient')) OR (p_report->'valid'='true'::jsonb AND p_report->'failure_kind' IS DISTINCT FROM 'null'::jsonb) THEN RAISE EXCEPTION 'GIS_SAFETY_REPORT_INVALID'; END IF;
 IF s.id IS NULL OR p_report->'schema_version' IS DISTINCT FROM '3'::jsonb OR p_report->>'protocol' IS DISTINCT FROM 'gee_safety_rehearsal'
 OR p_report->>'execution' IS DISTINCT FROM 'rehearsal' OR p_report->'live_enabled' IS DISTINCT FROM 'false'::jsonb
 OR p_report->>'session_id' IS DISTINCT FROM s.id::text OR p_report->>'policy_sha256' IS DISTINCT FROM s.policy_sha256
 OR p_report->'valid' IS DISTINCT FROM base->'valid' OR p_report->'error_code' IS DISTINCT FROM base->'error_code'
 OR jsonb_typeof(p_report->'receipts') IS DISTINCT FROM 'array' OR octet_length(p_report::text)>16384
 THEN RAISE EXCEPTION 'GIS_SAFETY_REPORT_INVALID'; END IF;
 v.kind:='process_gee_live_edition';v.validator_version:='gee-live-v2';
 PERFORM gis.validate_gee_live_report(base,p_edition,v);
 IF base->'output' IS DISTINCT FROM 'null'::jsonb THEN
  IF s.state<>'open' OR s.ends_at<=clock_timestamp() OR s.bound_worker IS DISTINCT FROM p_job.worker_id THEN RAISE EXCEPTION 'GIS_SAFETY_SESSION_CLOSED'; END IF;
  IF NOT EXISTS(SELECT 1 FROM gis.attempts WHERE job_id=p_job.id GROUP BY job_id HAVING min(started_at)+interval '180 seconds'>clock_timestamp()) THEN RAISE EXCEPTION 'GIS_SAFETY_JOB_TIMEOUT'; END IF;
  SELECT array_agg(value::uuid),count(DISTINCT value) INTO ids,n FROM jsonb_array_elements_text(p_report->'receipts');
  IF COALESCE(n,0)=0 OR n<>jsonb_array_length(p_report->'receipts') OR n>32
  OR n<>(SELECT count(*) FROM gis.gee_safety_requests WHERE job_id=p_job.id AND attempt_no=p_job.attempt_count AND lease_token=p_job.lease_token)
  OR n<>(SELECT count(*) FROM gis.gee_safety_requests WHERE id=ANY(ids) AND session_id=s.id AND job_id=p_job.id AND attempt_no=p_job.attempt_count AND lease_token=p_job.lease_token AND worker_id=p_job.worker_id AND state='completed' AND evidence_sha256=base->'output'->'content'->>'evidence_sha256')
  THEN RAISE EXCEPTION 'GIS_SAFETY_TRANSPORT_EVIDENCE_REQUIRED'; END IF;
 ELSIF p_report->'receipts'<>'[]'::jsonb THEN RAISE EXCEPTION 'GIS_SAFETY_REPORT_INVALID'; END IF;
END $f$;
CREATE FUNCTION gis.safety_record_candidate(p_job uuid,p_result uuid,p_worker uuid) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
BEGIN
 INSERT INTO gis.gee_live_candidates(result_id,job_id,request_id,dataset_id,edition_id,input_revision,input_hash,semantic_request_sha256,output_sha256,worker_id,attempt_no,lease_token,output)
 SELECT r.id,j.id,q.id,e.dataset_id,e.id,j.input_revision,j.input_hash,i.value->>'request_sha256',r.report->'base'->'output'->>'output_sha256',p_worker,j.attempt_count,j.lease_token,r.report->'base'->'output'
 FROM gis.jobs j JOIN gis.editions e ON e.id=j.edition_id JOIN gis.gee_live_requests q ON q.job_id=j.id JOIN gis.gee_live_inputs i ON i.id=q.input_id JOIN gis.results r ON r.id=p_result AND r.job_id=j.id WHERE j.id=p_job;
 IF NOT FOUND THEN RAISE EXCEPTION 'GIS_SAFETY_INPUT_REQUIRED'; END IF;
END $f$;

CREATE FUNCTION gis.safety_subject() RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE c jsonb;
BEGIN
 PERFORM gis.assert_environment();
 IF session_user<>'authenticator' OR current_setting('role',true)<>'gis_gee_safety_worker' THEN RAISE EXCEPTION 'GIS_SAFETY_IDENTITY_REQUIRED' USING ERRCODE='42501'; END IF;
 c:=NULLIF(current_setting('request.jwt.claims',true),'')::jsonb;
 IF c->>'role' IS DISTINCT FROM 'gis_gee_safety_worker' OR c->>'iss' IS DISTINCT FROM 'http://127.0.0.1:55421/auth/v1' OR COALESCE(c->>'sub','') !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' THEN RAISE EXCEPTION 'GIS_SAFETY_IDENTITY_REQUIRED' USING ERRCODE='42501'; END IF;
 RETURN (c->>'sub')::uuid;
END $f$;
CREATE FUNCTION gis.safety_finalize_stopped(p_worker uuid) RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE c record;j gis.jobs%ROWTYPE;s gis.gee_safety_sessions%ROWTYPE;n integer:=0;
BEGIN
 FOR c IN SELECT q.id,q.edition_id FROM gis.jobs q JOIN gis.gee_safety_jobs b ON b.job_id=q.id JOIN gis.gee_safety_sessions x ON x.id=b.session_id WHERE x.bound_worker=p_worker AND (x.state<>'open' OR x.ends_at<=clock_timestamp() OR EXISTS(SELECT 1 FROM gis.attempts a WHERE a.job_id=q.id GROUP BY a.job_id HAVING min(a.started_at)+interval '180 seconds'<=clock_timestamp())) AND (q.state='queued' OR q.state='running' AND q.lease_until<=clock_timestamp()) ORDER BY q.id LIMIT 20 LOOP
  PERFORM 1 FROM gis.editions WHERE id=c.edition_id FOR UPDATE SKIP LOCKED;IF NOT FOUND THEN CONTINUE; END IF;
  SELECT * INTO j FROM gis.jobs WHERE id=c.id FOR UPDATE SKIP LOCKED;IF NOT FOUND OR j.state NOT IN ('queued','running') OR (j.state='running' AND j.lease_until>clock_timestamp()) THEN CONTINUE; END IF;
  SELECT x.* INTO s FROM gis.gee_safety_sessions x JOIN gis.gee_safety_jobs b ON b.session_id=x.id WHERE b.job_id=j.id FOR UPDATE OF x SKIP LOCKED;IF NOT FOUND THEN CONTINUE;END IF;
  IF s.state='open' AND s.ends_at>clock_timestamp() AND NOT EXISTS(SELECT 1 FROM gis.attempts a WHERE a.job_id=j.id GROUP BY a.job_id HAVING min(a.started_at)+interval '180 seconds'<=clock_timestamp()) THEN CONTINUE; END IF;
  IF s.state='open' AND s.ends_at<=clock_timestamp() THEN UPDATE gis.gee_safety_sessions SET state='expired',stopped_at=clock_timestamp(),stop_reason='window_expired' WHERE id=s.id; END IF;
  IF j.state='running' THEN
   PERFORM gis.safety_abandon(j.id,j.attempt_count,j.lease_token);
   UPDATE gis.attempts SET state='expired',error_code='lease_expired',finished_at=clock_timestamp() WHERE job_id=j.id AND attempt_no=j.attempt_count AND state='running';
  END IF;
  UPDATE gis.jobs SET state='failed',worker_id=NULL,lease_token=NULL,lease_until=NULL,error_code='invalid_data',finished_at=clock_timestamp() WHERE id=j.id;
  UPDATE gis.editions SET state='draft' WHERE id=j.edition_id;
  INSERT INTO gis.audit(operation,job_id,edition_id,detail) VALUES('safety.stopped',j.id,j.edition_id,jsonb_build_object('session_id',s.id));n:=n+1;
 END LOOP;RETURN n;
END $f$;
CREATE FUNCTION public.gis_gee_safety_worker(p_action text,p_payload jsonb DEFAULT '{}') RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE subject uuid;s gis.gee_safety_sessions%ROWTYPE;e gis.editions%ROWTYPE;j gis.jobs%ROWTYPE;a gis.attempts%ROWTYPE;r gis.results%ROWTYPE;
BEGIN
 subject:=gis.safety_subject();
 IF p_action LIKE 'live%' THEN RAISE EXCEPTION 'GEE_TRUSTED_LIVE_NOT_APPROVED'; END IF;
 IF p_action IN ('reserve','attempted','finished','uncertain') THEN RETURN gis.safety_budget(subject,p_action,p_payload); END IF;
 IF p_action='stop' THEN
  PERFORM gis.keys(p_payload,ARRAY['session_id']);
  SELECT * INTO s FROM gis.gee_safety_sessions WHERE id=(p_payload->>'session_id')::uuid FOR UPDATE;
  IF NOT FOUND OR s.bound_worker IS DISTINCT FROM subject THEN RAISE EXCEPTION 'GIS_SAFETY_WORKER_MISMATCH'; END IF;
  IF s.state='open' THEN UPDATE gis.gee_safety_sessions SET state='stopped',stopped_at=clock_timestamp(),stop_reason='operator_stop' WHERE id=s.id RETURNING * INTO s; END IF;
  RETURN jsonb_build_object('session_id',s.id,'state',s.state);
 END IF;
 PERFORM gis.keys(p_payload,CASE p_action WHEN 'claim' THEN ARRAY[]::text[] WHEN 'recover' THEN ARRAY[]::text[] WHEN 'heartbeat' THEN ARRAY['job_id','lease_token','progress'] WHEN 'complete' THEN ARRAY['job_id','lease_token','report'] WHEN 'fail' THEN ARRAY['job_id','lease_token','report','error_code'] ELSE ARRAY[]::text[] END);
 IF p_action='recover' THEN
  PERFORM gis.safety_finalize_stopped(subject);
  RETURN gis.queue_protocol_kind(p_action,jsonb_build_object('worker_id',subject),'gee_safety_rehearsal');
 END IF;
 IF p_action='complete' THEN
  SELECT ed.* INTO e FROM gis.editions ed JOIN gis.jobs q ON q.edition_id=ed.id WHERE q.id=(p_payload->>'job_id')::uuid FOR UPDATE OF ed;
  SELECT * INTO j FROM gis.jobs WHERE id=(p_payload->>'job_id')::uuid FOR UPDATE;
  IF j.state='succeeded' AND gis.edition_protocol(e.id)='gee_safety_rehearsal' THEN
   SELECT * INTO a FROM gis.attempts WHERE job_id=j.id AND attempt_no=j.attempt_count;SELECT * INTO r FROM gis.results WHERE job_id=j.id;
   IF a.worker_id IS DISTINCT FROM subject OR a.lease_token IS DISTINCT FROM (p_payload->>'lease_token')::uuid OR r.report IS DISTINCT FROM p_payload->'report' THEN RAISE EXCEPTION 'GIS_STALE_LEASE'; END IF;
   RETURN jsonb_build_object('job_id',j.id,'state','succeeded','result_id',r.id,'replayed',true);
  END IF;
 END IF;
 RETURN gis.queue_protocol_kind(p_action,p_payload||jsonb_build_object('worker_id',subject),'gee_safety_rehearsal');
END $f$;
CREATE FUNCTION public.gis_gee_safety_readiness() RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE subject uuid;
BEGIN
 subject:=gis.safety_subject();
 IF NOT EXISTS(SELECT 1 FROM gis.schema_migrations WHERE version=45) THEN RAISE EXCEPTION 'GIS_SAFETY_NOT_READY'; END IF;
 RETURN (SELECT jsonb_build_object('subject',subject,'worker_role','gis_gee_safety_worker','database_name',database_name,'cluster_name',cluster_name,'runtime_instance',runtime_instance,'baseline_fingerprint',baseline_fingerprint,'protocol','gee_safety_rehearsal','live_enabled',false,'contract_version','1.0.0-a6.4d1') FROM gis.environment WHERE singleton);
END $f$;

-- GENERATED SHARED QUEUE AND DEFERRED INVARIANTS FOLLOW.
ALTER TABLE gis.jobs DROP CONSTRAINT jobs_kind_check;
ALTER TABLE gis.jobs ADD CONSTRAINT jobs_kind_check CHECK(kind IN ('validate_synthetic_edition','validate_ldd_edition','process_offline_edition','validate_geotiff_edition','prepare_ldd_edition','prepare_geotiff_edition','process_gee_mock_edition','process_gee_live_edition','process_gee_safety_edition'));
ALTER TABLE gis.jobs DROP CONSTRAINT jobs_validator_version_check;
ALTER TABLE gis.jobs ADD CONSTRAINT jobs_validator_version_check CHECK(validator_version IN ('synthetic-v1','ldd-local-v1','gee-offline-v1','geotiff-local-v1','ldd-prepare-v1','geotiff-prepare-v1','gee-contract-mock-v1','gee-live-v2','gee-safety-rehearsal-v1'));
ALTER TABLE gis.results DROP CONSTRAINT results_provider_check;
ALTER TABLE gis.results ADD CONSTRAINT results_provider_check CHECK(provider IN ('synthetic','local_ldd','offline_processing','local_geotiff','local_ldd_prepare','local_geotiff_prepare','gee_contract_mock','gee_live_v2','gee_safety_rehearsal'));
CREATE OR REPLACE FUNCTION gis.guard_row() RETURNS trigger
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
   IF NEW.state<>OLD.state AND NOT((OLD.kind='process_gee_safety_edition' AND OLD.state='queued' AND NEW.state='failed' AND EXISTS(SELECT 1 FROM gis.gee_safety_jobs b JOIN gis.gee_safety_sessions s ON s.id=b.session_id WHERE b.job_id=OLD.id AND (s.state<>'open' OR s.ends_at<=clock_timestamp() OR EXISTS(SELECT 1 FROM gis.attempts a WHERE a.job_id=OLD.id GROUP BY a.job_id HAVING min(a.started_at)+interval '180 seconds'<=clock_timestamp())))) OR (OLD.state='queued' AND NEW.state='running') OR (OLD.state='running' AND NEW.state IN ('queued','succeeded','failed'))) THEN
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


CREATE FUNCTION gis.check_safety_catalog() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE jid uuid;ids uuid[];j gis.jobs%ROWTYPE;v gis.jobs%ROWTYPE;e gis.editions%ROWTYPE;
 q gis.gee_live_requests%ROWTYPE;s gis.gee_safety_sessions%ROWTYPE;a gis.attempts%ROWTYPE;r gis.results%ROWTYPE;c gis.gee_live_candidates%ROWTYPE;
BEGIN
 IF TG_TABLE_NAME='editions' THEN SELECT array_agg(id) INTO ids FROM gis.jobs WHERE edition_id=NEW.id AND kind='process_gee_safety_edition';
 ELSIF TG_TABLE_NAME='jobs' THEN ids:=ARRAY[NEW.id];ELSE ids:=ARRAY[NEW.job_id];END IF;
 FOREACH jid IN ARRAY COALESCE(ids,ARRAY[]::uuid[]) LOOP
  SELECT * INTO j FROM gis.jobs WHERE id=jid;IF j.kind<>'process_gee_safety_edition' THEN CONTINUE; END IF;
  SELECT * INTO e FROM gis.editions WHERE id=j.edition_id;
  SELECT * INTO q FROM gis.gee_live_requests WHERE job_id=j.id;
  SELECT x.* INTO s FROM gis.gee_safety_sessions x JOIN gis.gee_safety_jobs b ON b.session_id=x.id WHERE b.job_id=j.id;
  IF q.id IS NULL OR s.id IS NULL OR q.edition_id<>e.id OR q.dataset_id<>e.dataset_id
   OR e.manifest IS DISTINCT FROM gis.safety_manifest(q.input_id,s.id) OR e.input_hash<>gis.manifest_hash(e.manifest)
   OR e.input_revision<>1 OR j.input_revision<>1 OR j.input_hash<>e.input_hash OR j.validator_version<>'gee-safety-rehearsal-v1'
   OR j.attempt_count>2 OR e.state NOT IN ('draft','validating') OR e.validated_result_id IS NOT NULL
   OR EXISTS(SELECT 1 FROM gis.datasets WHERE active_edition_id=e.id) THEN RAISE EXCEPTION 'GIS_SAFETY_CATALOG_INVARIANT'; END IF;
  IF EXISTS(SELECT 1 FROM gis.gee_safety_requests b JOIN gis.attempts t ON t.job_id=b.job_id AND t.attempt_no=b.attempt_no AND t.lease_token=b.lease_token WHERE b.job_id=j.id AND (b.session_id<>s.id OR b.worker_id<>s.bound_worker OR b.worker_id<>t.worker_id)) THEN RAISE EXCEPTION 'GIS_SAFETY_RESERVATION_INVARIANT'; END IF;
  SELECT * INTO c FROM gis.gee_live_candidates WHERE job_id=j.id;
  IF j.state='succeeded' THEN
   SELECT * INTO a FROM gis.attempts WHERE job_id=j.id AND attempt_no=j.attempt_count;
   SELECT * INTO r FROM gis.results WHERE job_id=j.id;
   v:=j;v.worker_id:=a.worker_id;v.lease_token:=a.lease_token;
   PERFORM gis.validate_safety_report(r.report,e,v);
   IF c.result_id IS NULL OR c.result_id<>r.id OR c.job_id<>j.id OR c.request_id<>q.id OR c.dataset_id<>e.dataset_id OR c.edition_id<>e.id
    OR c.input_revision<>j.input_revision OR c.input_hash<>j.input_hash OR c.semantic_request_sha256 IS DISTINCT FROM e.manifest->>'semantic_request_sha256'
    OR c.output IS DISTINCT FROM r.report->'base'->'output' OR c.output_sha256 IS DISTINCT FROM c.output->>'output_sha256'
    OR c.worker_id<>a.worker_id OR c.attempt_no<>a.attempt_no OR c.lease_token<>a.lease_token
    OR a.state<>'succeeded' OR a.validation_report IS DISTINCT FROM r.report OR r.provider<>'gee_safety_rehearsal'
    OR r.report->'valid' IS DISTINCT FROM 'true'::jsonb THEN RAISE EXCEPTION 'GIS_SAFETY_CANDIDATE_INVARIANT'; END IF;
  ELSIF c.result_id IS NOT NULL THEN RAISE EXCEPTION 'GIS_SAFETY_PREMATURE_CANDIDATE'; END IF;
 END LOOP;RETURN NULL;
END $f$;
DO $invariants$ DECLARE t text;BEGIN
 FOREACH t IN ARRAY ARRAY['editions','jobs','attempts','results','gee_live_requests','gee_live_candidates','gee_safety_jobs','gee_safety_requests'] LOOP
  EXECUTE format('CREATE CONSTRAINT TRIGGER safety_integrity AFTER INSERT OR UPDATE ON gis.%I DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION gis.check_safety_catalog()',t);
 END LOOP;
END $invariants$;
CREATE OR REPLACE FUNCTION gis.queue_protocol_kind(p_action text,p_payload jsonb,p_protocol text) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE safety_session gis.gee_safety_sessions%ROWTYPE; j gis.jobs%ROWTYPE; e gis.editions%ROWTYPE; candidate record;
 worker uuid; token uuid; jid uuid; eid uuid; rid uuid; v_now timestamptz;
 progress_value integer; report_value jsonb; code text; next_state text; n integer:=0;
 p_native boolean:=p_protocol<>'v1'; u gis.ldd_uploads%ROWTYPE; ldd_dataset gis.datasets%ROWTYPE; processing_request gis.processing_requests%ROWTYPE; geo gis.geotiff_uploads%ROWTYPE; geo_dataset gis.datasets%ROWTYPE;
BEGIN
 PERFORM gis.assert_environment();
 IF p_protocol NOT IN ('v1','v2','ldd','gee_offline','geotiff','gee_contract_mock','gee_live_v2','gee_safety_rehearsal') OR p_protocol IS NULL THEN RAISE EXCEPTION 'GIS_WORKER_PROTOCOL_MISMATCH'; END IF;
 IF p_action='claim' THEN
   PERFORM gis.keys(p_payload,ARRAY['worker_id']);
   worker:=(p_payload->>'worker_id')::uuid;
   IF worker IS NULL THEN RAISE EXCEPTION 'GIS_WORKER_REQUIRED'; END IF;
   IF NOT pg_try_advisory_xact_lock(hashtextextended('gis-t1-single-claim',0)) THEN
     RETURN CASE WHEN p_native THEN jsonb_build_object('job',NULL) ELSE NULL END; END IF;
   IF EXISTS(SELECT 1 FROM gis.jobs WHERE state='running') THEN
     RETURN CASE WHEN p_native THEN jsonb_build_object('job',NULL) ELSE NULL END; END IF;
   FOR candidate IN SELECT q.id,q.edition_id FROM gis.jobs q JOIN gis.editions d ON d.id=q.edition_id
      WHERE q.state='queued' AND q.attempt_count<(CASE WHEN p_protocol='gee_safety_rehearsal' THEN 2 ELSE 3 END) AND q.available_at<=clock_timestamp()
        AND q.kind NOT IN ('prepare_ldd_edition','prepare_geotiff_edition') AND gis.edition_protocol(d.id)=p_protocol
        AND (p_protocol<>'gee_safety_rehearsal' OR EXISTS(SELECT 1 FROM gis.gee_safety_jobs b JOIN gis.gee_safety_sessions s ON s.id=b.session_id WHERE b.job_id=q.id AND s.bound_worker=CASE WHEN p_action='claim' THEN worker ELSE (p_payload->>'worker_id')::uuid END AND s.state='open' AND s.ends_at>clock_timestamp()))
      ORDER BY q.available_at,q.created_at,q.id LIMIT 20 LOOP
     SELECT * INTO e FROM gis.editions WHERE id=candidate.edition_id FOR UPDATE SKIP LOCKED;
     IF NOT FOUND THEN CONTINUE; END IF;
     SELECT * INTO j FROM gis.jobs WHERE id=candidate.id FOR UPDATE SKIP LOCKED;
     IF NOT FOUND THEN CONTINUE; END IF;
     v_now:=clock_timestamp();
     IF j.state<>'queued' OR j.attempt_count>=(CASE WHEN p_protocol='gee_safety_rehearsal' THEN 2 ELSE 3 END) OR j.available_at>v_now
       OR e.state<>'validating' OR gis.edition_protocol(e.id) IS DISTINCT FROM p_protocol THEN CONTINUE; END IF;
     IF p_protocol='gee_safety_rehearsal' THEN PERFORM gis.safety_claim_guard(j.id,worker); END IF;
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
     IF p_protocol='gee_safety_rehearsal' THEN
       report_value:=report_value||gis.gee_live_claim_packet(j.id)||jsonb_build_object('session_id',e.manifest->>'session_id','policy_sha256',e.manifest->>'policy_sha256','job_remaining_seconds',(SELECT greatest(0,extract(epoch FROM(min(started_at)+interval '180 seconds'-clock_timestamp()))) FROM gis.attempts WHERE job_id=j.id));
     END IF;
     IF p_protocol='gee_live_v2' THEN
       report_value:=report_value||gis.gee_live_claim_packet(j.id);
     END IF;
     IF p_protocol='gee_contract_mock' THEN
       report_value:=report_value||gis.gee_mock_claim_packet(j.id);
     END IF;
     IF p_protocol='gee_offline' THEN
       SELECT * INTO processing_request FROM gis.processing_requests WHERE edition_id=e.id;
       report_value:=report_value||jsonb_build_object('processing_id',processing_request.id);
     END IF;
     IF p_native THEN
       INSERT INTO gis.audit(operation,dataset_id,edition_id,job_id,detail)
         VALUES(CASE WHEN p_protocol='gee_safety_rehearsal' THEN 'safety.'||p_action WHEN p_protocol='gee_live_v2' THEN 'gee_live.'||p_action WHEN p_protocol='gee_contract_mock' THEN 'gee_mock.claim' WHEN p_protocol='geotiff' THEN 'geotiff.claim' WHEN p_protocol='gee_offline' THEN 'processing.claim' WHEN p_protocol='ldd' THEN 'ldd.claim' ELSE 'worker_v2.claim' END,e.dataset_id,e.id,j.id,jsonb_build_object('worker_id',worker,'attempt',j.attempt_count));
       RETURN jsonb_build_object('job',report_value||jsonb_build_object('id',j.id,'dataset_id',e.dataset_id,
         'kind',j.kind,'attempt_number',j.attempt_count));
     END IF;
     RETURN report_value;
   END LOOP;
   RETURN CASE WHEN p_native THEN jsonb_build_object('job',NULL) ELSE NULL END;
 ELSIF p_action='recover' THEN
   PERFORM gis.keys(p_payload,CASE WHEN p_protocol='gee_safety_rehearsal' THEN ARRAY['worker_id'] ELSE ARRAY[]::text[] END);
   FOR candidate IN SELECT q.id,q.edition_id FROM gis.jobs q JOIN gis.editions d ON d.id=q.edition_id
     WHERE q.state='running' AND q.lease_until<=clock_timestamp()
       AND q.kind NOT IN ('prepare_ldd_edition','prepare_geotiff_edition') AND gis.edition_protocol(d.id)=p_protocol
        AND (p_protocol<>'gee_safety_rehearsal' OR EXISTS(SELECT 1 FROM gis.gee_safety_jobs b JOIN gis.gee_safety_sessions s ON s.id=b.session_id WHERE b.job_id=q.id AND s.bound_worker=CASE WHEN p_action='claim' THEN worker ELSE (p_payload->>'worker_id')::uuid END AND s.state='open' AND s.ends_at>clock_timestamp()))
     ORDER BY q.lease_until,q.id LIMIT 20 LOOP
     SELECT * INTO e FROM gis.editions WHERE id=candidate.edition_id FOR UPDATE SKIP LOCKED;
     IF NOT FOUND THEN CONTINUE; END IF;
     SELECT * INTO j FROM gis.jobs WHERE id=candidate.id FOR UPDATE SKIP LOCKED;
     IF NOT FOUND THEN CONTINUE; END IF;
     v_now:=clock_timestamp();
     IF j.state<>'running' OR j.lease_until>v_now THEN CONTINUE; END IF;
     IF p_protocol='gee_safety_rehearsal' THEN PERFORM gis.safety_abandon(j.id,j.attempt_count,j.lease_token); END IF;
     UPDATE gis.attempts SET state='expired',error_code='lease_expired',finished_at=v_now
       WHERE job_id=j.id AND attempt_no=j.attempt_count AND lease_token=j.lease_token AND state='running';
     IF p_protocol='gee_safety_rehearsal' THEN SELECT s.* INTO safety_session FROM gis.gee_safety_sessions s JOIN gis.gee_safety_jobs b ON b.session_id=s.id WHERE b.job_id=j.id; END IF;
     IF j.attempt_count<(CASE WHEN p_protocol='gee_safety_rehearsal' THEN 2 ELSE 3 END) AND (p_protocol<>'gee_safety_rehearsal' OR (safety_session.state='open' AND safety_session.ends_at>clock_timestamp() AND NOT EXISTS(SELECT 1 FROM gis.attempts a WHERE a.job_id=j.id GROUP BY a.job_id HAVING min(a.started_at)+interval '180 seconds'<=clock_timestamp()))) THEN
       UPDATE gis.jobs SET state='queued',worker_id=NULL,lease_token=NULL,lease_until=NULL,progress=0,
         available_at=v_now+make_interval(secs=>CASE j.attempt_count WHEN 1 THEN 5 ELSE 20 END+floor(random()*3)::int)
         WHERE id=j.id;
     ELSE
       UPDATE gis.jobs SET state='failed',worker_id=NULL,lease_token=NULL,lease_until=NULL,
         error_code='attempts_exhausted',finished_at=v_now WHERE id=j.id;
       UPDATE gis.editions SET state='draft' WHERE id=e.id AND state='validating';
     END IF;
     INSERT INTO gis.audit(operation,dataset_id,edition_id,job_id,detail)
       VALUES(CASE WHEN p_protocol='gee_safety_rehearsal' THEN 'safety.'||p_action WHEN p_protocol='gee_live_v2' THEN 'gee_live.'||p_action WHEN p_protocol='gee_contract_mock' THEN 'gee_mock.recover' WHEN p_protocol='geotiff' THEN 'geotiff.recover' WHEN p_protocol='gee_offline' THEN 'processing.recover' WHEN p_protocol='ldd' THEN 'ldd.recover' WHEN p_native THEN 'worker_v2.recover' ELSE 'worker.recover' END,e.dataset_id,e.id,j.id,
         jsonb_build_object('attempt',j.attempt_count,'terminal',j.attempt_count=(CASE WHEN p_protocol='gee_safety_rehearsal' THEN 2 ELSE 3 END)));
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
   IF NOT FOUND OR j.kind IN ('prepare_ldd_edition','prepare_geotiff_edition') OR j.state<>'running' OR j.worker_id IS DISTINCT FROM worker
     OR j.lease_token IS DISTINCT FROM token OR j.lease_until<=v_now THEN RAISE EXCEPTION 'GIS_STALE_LEASE'; END IF;
   IF p_protocol='gee_safety_rehearsal' THEN PERFORM gis.safety_lock(j.id,worker,token,p_action<>'fail'); END IF;
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
     IF p_protocol='gee_safety_rehearsal' THEN PERFORM gis.validate_safety_report(report_value,e,j);
     ELSIF p_protocol='gee_live_v2' THEN PERFORM gis.validate_gee_live_report(report_value,e,j);
     ELSIF p_protocol='gee_contract_mock' THEN PERFORM gis.validate_gee_mock_report(report_value,e,j);
     ELSIF p_protocol='geotiff' THEN PERFORM gis.validate_geotiff_report(report_value,e,j);
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
       VALUES(j.id,e.id,j.input_revision,j.input_hash,j.validator_version,j.attempt_count,token,true,report_value,CASE WHEN p_protocol='gee_safety_rehearsal' THEN 'gee_safety_rehearsal' WHEN p_protocol='gee_live_v2' THEN 'gee_live_v2' WHEN p_protocol='gee_contract_mock' THEN 'gee_contract_mock' WHEN p_protocol='geotiff' THEN 'local_geotiff' WHEN p_protocol='gee_offline' THEN 'offline_processing' WHEN p_protocol='ldd' THEN 'local_ldd' ELSE 'synthetic' END) RETURNING id INTO rid;
     IF p_protocol IN ('gee_offline','geotiff','gee_contract_mock','gee_live_v2','gee_safety_rehearsal') THEN
       UPDATE gis.editions SET state='draft',validated_result_id=NULL WHERE id=e.id;
     ELSE
       UPDATE gis.editions SET state='validated',validated_result_id=rid WHERE id=e.id;
     END IF;
     IF p_protocol='gee_safety_rehearsal' THEN PERFORM gis.safety_record_candidate(j.id,rid,worker); END IF;
     IF p_protocol='gee_live_v2' THEN PERFORM gis.gee_live_record_candidate(j.id,rid,worker); END IF;
     IF p_protocol='gee_contract_mock' THEN PERFORM gis.gee_mock_record_candidate(j.id,rid,worker); END IF;
     UPDATE gis.jobs SET state='succeeded',worker_id=NULL,lease_token=NULL,lease_until=NULL,progress=100,finished_at=v_now WHERE id=j.id;
     UPDATE gis.attempts SET state='succeeded',progress=100,finished_at=v_now WHERE job_id=j.id AND attempt_no=j.attempt_count AND lease_token=token;
     INSERT INTO gis.audit(operation,dataset_id,edition_id,job_id,detail)
       VALUES(CASE WHEN p_protocol='gee_safety_rehearsal' THEN 'safety.'||p_action WHEN p_protocol='gee_live_v2' THEN 'gee_live.'||p_action WHEN p_protocol='gee_contract_mock' THEN 'gee_mock.complete' WHEN p_protocol='geotiff' THEN 'geotiff.complete' WHEN p_protocol='gee_offline' THEN 'processing.complete' WHEN p_protocol='ldd' THEN 'ldd.complete' WHEN p_native THEN 'worker_v2.complete' ELSE 'worker.complete' END,e.dataset_id,e.id,j.id,
         jsonb_build_object('result_id',rid,'attempt',j.attempt_count));
     RETURN jsonb_build_object('job_id',j.id,'state','succeeded','result_id',rid);
   END IF;
   IF p_action='complete' THEN code:='invalid_data';
   ELSE code:=p_payload->>'error_code'; END IF;
   IF code IS NULL OR code NOT IN ('invalid_data','transient') THEN RAISE EXCEPTION 'GIS_INVALID_FAILURE'; END IF;
   IF p_native AND p_action='fail' AND (code<>'transient' OR report_value->>'error_code' NOT IN (
     'NATIVE_TIMEOUT','NATIVE_MEMORY_LIMIT','NATIVE_PROCESS_FAILED','TRANSIENT_SYNTHETIC','WORKER_SHUTDOWN','NATIVE_OUTPUT_LIMIT')) THEN
     RAISE EXCEPTION 'GIS_INVALID_FAILURE'; END IF;
   IF p_protocol='gee_safety_rehearsal' THEN PERFORM gis.safety_abandon(j.id,j.attempt_count,token); END IF;
   next_state:=CASE WHEN code='transient' AND (p_protocol<>'gee_safety_rehearsal' OR EXISTS(SELECT 1 FROM gis.gee_safety_sessions s JOIN gis.gee_safety_jobs b ON b.session_id=s.id WHERE b.job_id=j.id AND s.state='open' AND s.ends_at>clock_timestamp())) AND j.attempt_count<(CASE WHEN p_protocol='gee_safety_rehearsal' THEN 2 ELSE 3 END) THEN 'queued' ELSE 'failed' END;
   UPDATE gis.attempts SET state='failed',error_code=code,finished_at=v_now
     WHERE job_id=j.id AND attempt_no=j.attempt_count AND lease_token=token;
   UPDATE gis.jobs SET state=next_state,worker_id=NULL,lease_token=NULL,lease_until=NULL,
     error_code=CASE WHEN next_state='failed' THEN code ELSE NULL END,progress=0,
     available_at=v_now+make_interval(secs=>CASE j.attempt_count WHEN 1 THEN 5 ELSE 20 END+floor(random()*3)::int),
     finished_at=CASE WHEN next_state='failed' THEN v_now ELSE NULL END WHERE id=j.id;
   IF next_state='failed' THEN UPDATE gis.editions SET state='draft' WHERE id=e.id; END IF;
   INSERT INTO gis.audit(operation,dataset_id,edition_id,job_id,detail)
     VALUES(CASE WHEN p_protocol='gee_safety_rehearsal' THEN 'safety.'||p_action WHEN p_protocol='gee_live_v2' THEN 'gee_live.'||p_action WHEN p_protocol='gee_contract_mock' THEN 'gee_mock.fail' WHEN p_protocol='geotiff' THEN 'geotiff.fail' WHEN p_protocol='gee_offline' THEN 'processing.fail' WHEN p_protocol='ldd' THEN 'ldd.fail' WHEN p_native THEN 'worker_v2.fail' ELSE 'worker.fail' END,e.dataset_id,e.id,j.id,
       jsonb_build_object('attempt',j.attempt_count,'error_code',code,'state',next_state));
   RETURN CASE WHEN p_native THEN jsonb_build_object('job_id',j.id,'state',next_state,'error_code',code)
     ELSE jsonb_build_object('job_id',j.id,'state',next_state) END;
 END IF;
 RAISE EXCEPTION 'GIS_UNKNOWN_WORKER_ACTION';
END $f$;



DO $acl$ DECLARE f record; BEGIN
 FOR f IN SELECT p.oid::regprocedure::text AS signature FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
 WHERE (n.nspname='gis' AND (p.proname LIKE '%safety%' OR p.proname LIKE 'a64d1_previous_%' OR p.proname IN ('manifest_hash','edition_protocol','eligible','queue_protocol_kind')))
 OR (n.nspname='public' AND p.proname LIKE 'gis_gee_safety_%') LOOP
  EXECUTE format('REVOKE ALL ON FUNCTION %s FROM PUBLIC,anon,authenticated,service_role,gis_worker,gis_native_worker,gis_gee_mock_worker,gis_gee_live_worker,gis_gee_safety_worker',f.signature);
 END LOOP;
END $acl$;
GRANT EXECUTE ON FUNCTION public.gis_gee_safety_worker(text,jsonb),public.gis_gee_safety_readiness() TO gis_gee_safety_worker;
REVOKE CREATE ON SCHEMA public FROM gis_owner;
RESET ROLE;
NOTIFY pgrst,'reload schema';
