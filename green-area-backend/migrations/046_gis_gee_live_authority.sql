-- A6 offline SDK authority. Fake HTTP is NEVER genuine Google evidence.
-- No real-runtime approval, credentials, publication, old ledger edits or gates.
DO $preflight$ BEGIN
 IF current_database() NOT IN ('postgres','gis_t1_upgrade')
 OR NOT gis.target_ok()
 OR NOT EXISTS(SELECT 1 FROM gis.schema_migrations WHERE version=45 AND sha256='a7ae1f4cfd99f4bd0d728b3ca290fb4a2734d05f585c3a192c9611a0b317b395')
 OR EXISTS(SELECT 1 FROM gis.schema_migrations WHERE version>=46)
 OR NOT EXISTS(SELECT 1 FROM gis.environment WHERE singleton AND NOT activation_enabled
 AND runtime_instance=current_setting('gis.runtime_instance',true) AND baseline_fingerprint=current_setting('gis.baseline_fingerprint',true))
 THEN RAISE EXCEPTION 'GIS_TRANSPORT_LOCAL_BASELINE_REQUIRED'; END IF;
 IF EXISTS(SELECT 1 FROM gis.environment WHERE activation_enabled) THEN RAISE EXCEPTION 'GIS_TRANSPORT_CLOSED_GATE_REQUIRED'; END IF;
END $preflight$;
DO $role$ BEGIN
 IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='gis_gee_transport_recorder') THEN
  IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='gis_gee_transport_recorder' AND NOT rolsuper AND NOT rolbypassrls
   AND NOT rolcanlogin AND NOT rolcreatedb AND NOT rolcreaterole AND NOT rolreplication AND NOT rolinherit
   AND shobj_description(oid,'pg_authid')='gis-a6-sdk-fake-http-recorder')
   OR EXISTS(SELECT 1 FROM pg_auth_members WHERE member='gis_gee_transport_recorder'::regrole)
   OR EXISTS(SELECT 1 FROM pg_auth_members WHERE roleid='gis_gee_transport_recorder'::regrole AND member NOT IN ('postgres'::regrole,'authenticator'::regrole))
  THEN RAISE EXCEPTION 'GIS_TRANSPORT_ROLE_COLLISION'; END IF;
 ELSE
  CREATE ROLE gis_gee_transport_recorder NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOINHERIT NOBYPASSRLS;
 END IF;
END $role$;
COMMENT ON ROLE gis_gee_transport_recorder IS 'gis-a6-sdk-fake-http-recorder';
GRANT gis_gee_transport_recorder TO authenticator WITH INHERIT FALSE, SET TRUE;
GRANT USAGE ON SCHEMA public TO gis_gee_transport_recorder;
REVOKE ALL ON SCHEMA gis FROM gis_gee_transport_recorder;
GRANT CREATE ON SCHEMA public TO gis_owner;
SET LOCAL ROLE gis_owner;

CREATE TABLE gis.gee_transport_authorities(
 job_id uuid PRIMARY KEY REFERENCES gis.jobs(id),
 session_id uuid NOT NULL REFERENCES gis.gee_safety_sessions(id),
 worker_id uuid NOT NULL REFERENCES public.profiles(id),
 recorder_id uuid NOT NULL REFERENCES public.profiles(id),
 mode text NOT NULL CHECK(mode='fake_http'),
 project_id text NOT NULL CHECK(project_id='green-area-gis-sandbox'),
 project_number text NOT NULL CHECK(project_number='977478562022'),
 google_principal text NOT NULL CHECK(google_principal='offline-test@green-area-gis-sandbox.iam.gserviceaccount.com'),
 input_revision integer NOT NULL,input_hash text NOT NULL,request_sha256 text NOT NULL,
 geometry_sha256 text NOT NULL,method_sha256 text NOT NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 CHECK(worker_id<>recorder_id));
CREATE TABLE gis.gee_transport_receipts(
 request_id uuid PRIMARY KEY REFERENCES gis.gee_safety_requests(id),
 job_id uuid NOT NULL REFERENCES gis.gee_transport_authorities(job_id),
 recorder_id uuid NOT NULL REFERENCES public.profiles(id),
 category text NOT NULL CHECK(category IN ('discovery','algorithms','catalog','token','compute')),
 request_sha256 text NOT NULL CHECK(request_sha256 ~ '^[0-9a-f]{64}$'),
 response_sha256 text NOT NULL CHECK(response_sha256 ~ '^[0-9a-f]{64}$'),
 status integer NOT NULL CHECK(status BETWEEN 100 AND 599),
 observation jsonb CHECK(observation IS NULL OR jsonb_typeof(observation)='object' AND octet_length(observation::text)<=8192),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp());
CREATE TABLE gis.gee_transport_seals(
 job_id uuid NOT NULL REFERENCES gis.gee_transport_authorities(job_id),
 attempt_no integer NOT NULL,lease_token uuid NOT NULL,
 output_sha256 text NOT NULL CHECK(output_sha256 ~ '^[0-9a-f]{64}$'),
 evidence_sha256 text NOT NULL CHECK(evidence_sha256 ~ '^[0-9a-f]{64}$'),
 receipts uuid[] NOT NULL CHECK(cardinality(receipts) BETWEEN 1 AND 32),
 recorder_id uuid NOT NULL REFERENCES public.profiles(id),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY(job_id,attempt_no),
 FOREIGN KEY(job_id,attempt_no,lease_token) REFERENCES gis.attempts(job_id,attempt_no,lease_token));
DO $tables$ DECLARE t text; BEGIN
 FOREACH t IN ARRAY ARRAY['gee_transport_authorities','gee_transport_receipts','gee_transport_seals'] LOOP
  EXECUTE format('ALTER TABLE gis.%I ENABLE ROW LEVEL SECURITY',t);
  EXECUTE format('ALTER TABLE gis.%I FORCE ROW LEVEL SECURITY',t);
  EXECUTE format('CREATE POLICY owner_access ON gis.%I TO gis_owner USING(true) WITH CHECK(true)',t);
  EXECUTE format('REVOKE ALL ON gis.%I FROM PUBLIC,anon,authenticated,service_role,gis_worker,gis_native_worker,gis_gee_mock_worker,gis_gee_live_worker,gis_gee_safety_worker,gis_gee_transport_recorder',t);
  EXECUTE format('CREATE TRIGGER immutable_transport BEFORE UPDATE OR DELETE ON gis.%I FOR EACH ROW EXECUTE FUNCTION gis.gee_live_immutable()',t);
 END LOOP;
END $tables$;

-- Operator-only fixture registration. Cannot install any google_https authority.
CREATE FUNCTION gis.transport_authorize_fake(p_job uuid,p_recorder uuid) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE j gis.jobs%ROWTYPE;s gis.gee_safety_sessions%ROWTYPE;v jsonb;
BEGIN
 PERFORM gis.assert_environment();
 PERFORM 1 FROM gis.editions e JOIN gis.jobs q ON q.edition_id=e.id WHERE q.id=p_job FOR UPDATE OF e;
 SELECT * INTO j FROM gis.jobs WHERE id=p_job FOR UPDATE;
 SELECT x.* INTO s FROM gis.gee_safety_sessions x JOIN gis.gee_safety_jobs b ON b.session_id=x.id WHERE b.job_id=p_job FOR UPDATE OF x;
 SELECT i.value INTO v FROM gis.gee_live_inputs i JOIN gis.gee_live_requests r ON r.input_id=i.id WHERE r.job_id=p_job;
 IF j.kind IS DISTINCT FROM 'process_gee_safety_edition' OR j.state IS DISTINCT FROM 'queued'
 OR j.attempt_count<>0 OR s.state IS DISTINCT FROM 'open' OR s.ends_at<=clock_timestamp()
 OR s.bound_worker=p_recorder OR v->'request'->'project' IS DISTINCT FROM
 jsonb_build_object('project_id','green-area-gis-sandbox','project_number','977478562022',
 'principal','offline-test@green-area-gis-sandbox.iam.gserviceaccount.com','readiness','not_verified')
 THEN RAISE EXCEPTION 'GIS_TRANSPORT_FAKE_BINDING_REQUIRED'; END IF;
 INSERT INTO gis.gee_transport_authorities(job_id,session_id,worker_id,recorder_id,mode,project_id,project_number,google_principal,
 input_revision,input_hash,request_sha256,geometry_sha256,method_sha256)
 VALUES(p_job,s.id,s.bound_worker,p_recorder,'fake_http','green-area-gis-sandbox','977478562022',
 'offline-test@green-area-gis-sandbox.iam.gserviceaccount.com',j.input_revision,j.input_hash,v->>'request_sha256',v->>'geometry_sha256',
 encode(sha256(convert_to(gis.gee_live_canonical(v->'method'),'UTF8')),'hex'));
 INSERT INTO gis.audit(operation,job_id,detail) VALUES('transport.authorize_fake',p_job,jsonb_build_object('mode','fake_http','live_enabled',false));
END $f$;

CREATE FUNCTION gis.transport_subject() RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE c jsonb;
BEGIN
 PERFORM gis.assert_environment();
 IF session_user<>'authenticator' OR current_setting('role',true)<>'gis_gee_transport_recorder' THEN RAISE EXCEPTION 'GIS_TRANSPORT_IDENTITY_REQUIRED' USING ERRCODE='42501'; END IF;
 c:=NULLIF(current_setting('request.jwt.claims',true),'')::jsonb;
 IF c->>'role' IS DISTINCT FROM 'gis_gee_transport_recorder' OR c->>'iss' IS DISTINCT FROM 'http://127.0.0.1:55421/auth/v1'
 OR COALESCE(c->>'sub','') !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
 THEN RAISE EXCEPTION 'GIS_TRANSPORT_IDENTITY_REQUIRED' USING ERRCODE='42501'; END IF;
 RETURN (c->>'sub')::uuid;
END $f$;

-- Unbound 045 jobs retain the exact old validator. Bound jobs ALSO require a
-- recorder seal, including completion through the old public worker RPC.
ALTER FUNCTION gis.validate_safety_report(jsonb,gis.editions,gis.jobs) RENAME TO a6_transport_previous_validate_safety_report;
CREATE FUNCTION gis.validate_safety_report(p_report jsonb,p_edition gis.editions,p_job gis.jobs) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE a gis.gee_transport_authorities%ROWTYPE;seal gis.gee_transport_seals%ROWTYPE;ids uuid[];
BEGIN
 PERFORM gis.a6_transport_previous_validate_safety_report(p_report,p_edition,p_job);
 SELECT * INTO a FROM gis.gee_transport_authorities WHERE job_id=p_job.id;
 IF NOT FOUND THEN RETURN; END IF;
 IF a.worker_id IS DISTINCT FROM p_job.worker_id OR a.input_revision IS DISTINCT FROM p_job.input_revision
 OR a.input_hash IS DISTINCT FROM p_job.input_hash THEN RAISE EXCEPTION 'GIS_TRANSPORT_INPUT_MISMATCH'; END IF;
 IF p_report->'base'->'output' IS DISTINCT FROM 'null'::jsonb THEN
  SELECT * INTO seal FROM gis.gee_transport_seals WHERE job_id=p_job.id AND attempt_no=p_job.attempt_count;
  SELECT array_agg(value::uuid ORDER BY value::uuid) INTO ids FROM jsonb_array_elements_text(p_report->'receipts');
  IF seal.job_id IS NULL OR seal.lease_token IS DISTINCT FROM p_job.lease_token OR seal.recorder_id IS DISTINCT FROM a.recorder_id
  OR seal.output_sha256 IS DISTINCT FROM p_report->'base'->'output'->>'output_sha256'
  OR seal.evidence_sha256 IS DISTINCT FROM p_report->'base'->'output'->'content'->>'evidence_sha256'
  OR seal.receipts IS DISTINCT FROM ids THEN RAISE EXCEPTION 'GIS_TRANSPORT_RECORDER_SEAL_REQUIRED'; END IF;
 END IF;
END $f$;

CREATE FUNCTION gis.transport_record(p_subject uuid,p_action text,p_payload jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE subject uuid:=p_subject;j gis.jobs%ROWTYPE;a gis.gee_transport_authorities%ROWTYPE;
 r gis.gee_safety_requests%ROWTYPE;output jsonb;wrapped jsonb;ids uuid[];rid uuid;sha text;obs jsonb;evidence jsonb;valid boolean;
BEGIN
 PERFORM gis.assert_environment();
 IF p_action='readiness' THEN
  PERFORM gis.keys(p_payload,ARRAY[]::text[]);
  RETURN jsonb_build_object('subject',subject,'mode','fake_http','live_enabled',false,'genuine_completion_enabled',false);
 END IF;
 IF p_action LIKE 'live%' OR p_action LIKE 'genuine%' THEN RAISE EXCEPTION 'GEE_TRUSTED_LIVE_NOT_APPROVED'; END IF;
 IF p_action NOT IN ('reserve','attempted','response','uncertain','seal') THEN RAISE EXCEPTION 'GIS_TRANSPORT_ACTION_REJECTED'; END IF;
 -- Same lock order as 045. Never accept a worker/session/project from payload.
 PERFORM 1 FROM gis.editions e JOIN gis.jobs q ON q.edition_id=e.id WHERE q.id=(p_payload->>'job_id')::uuid FOR UPDATE OF e;
 SELECT * INTO j FROM gis.jobs WHERE id=(p_payload->>'job_id')::uuid FOR UPDATE;
 SELECT * INTO a FROM gis.gee_transport_authorities WHERE job_id=j.id;
 IF a.job_id IS NULL OR a.recorder_id IS DISTINCT FROM subject OR a.worker_id IS DISTINCT FROM j.worker_id
 OR a.mode IS DISTINCT FROM 'fake_http' OR a.input_revision IS DISTINCT FROM j.input_revision OR a.input_hash IS DISTINCT FROM j.input_hash
 THEN RAISE EXCEPTION 'GIS_TRANSPORT_AUTHORITY_REQUIRED'; END IF;
 PERFORM gis.safety_lock(j.id,a.worker_id,(p_payload->>'lease_token')::uuid,p_action<>'uncertain');
 IF p_action IN ('reserve','attempted','uncertain') THEN
  RETURN gis.safety_budget(a.worker_id,p_action,p_payload);
 ELSIF p_action='response' THEN
  PERFORM gis.keys(p_payload,ARRAY['job_id','lease_token','request_id','request_sha256','response_sha256','status','category','observation']);
  SELECT * INTO r FROM gis.gee_safety_requests WHERE id=(p_payload->>'request_id')::uuid FOR UPDATE;
  IF r.job_id IS DISTINCT FROM j.id OR r.session_id IS DISTINCT FROM a.session_id OR r.attempt_no IS DISTINCT FROM j.attempt_count
  OR r.lease_token IS DISTINCT FROM j.lease_token OR r.state IS DISTINCT FROM 'attempted'
  OR r.attempted_at+interval '120 seconds'<=clock_timestamp() THEN RAISE EXCEPTION 'GIS_TRANSPORT_RECEIPT_REJECTED'; END IF;
  obs:=NULLIF(p_payload->'observation','null'::jsonb);
  IF p_payload->>'category'='compute' AND p_payload->>'status'='200' THEN
   PERFORM gis.keys(obs,ARRAY['scene_ids','acquired_ms','scene_count','valid_pixels','mean','min','max','complete']);
   IF obs IS NULL OR NOT obs ?& ARRAY['scene_ids','acquired_ms','scene_count','valid_pixels','mean','min','max','complete']
   OR p_payload->>'response_sha256' IS DISTINCT FROM encode(sha256(convert_to(gis.gee_live_canonical(jsonb_build_object('result',obs)),'UTF8')),'hex')
   THEN RAISE EXCEPTION 'GIS_TRANSPORT_RESPONSE_HASH_MISMATCH'; END IF;
  ELSIF obs IS NOT NULL THEN RAISE EXCEPTION 'GIS_TRANSPORT_OBSERVATION_REJECTED'; END IF;
  INSERT INTO gis.gee_transport_receipts(request_id,job_id,recorder_id,category,request_sha256,response_sha256,status,observation)
  VALUES(r.id,j.id,subject,p_payload->>'category',p_payload->>'request_sha256',p_payload->>'response_sha256',(p_payload->>'status')::integer,obs);
  RETURN jsonb_build_object('request_id',r.id,'state','recorded','mode',a.mode);
 END IF;
 PERFORM gis.keys(p_payload,ARRAY['job_id','lease_token','output','receipts']);
 output:=p_payload->'output';
 SELECT array_agg(value::uuid ORDER BY value::uuid) INTO ids FROM jsonb_array_elements_text(p_payload->'receipts');
 IF COALESCE(cardinality(ids),0)=0 OR cardinality(ids)>32
 OR cardinality(ids)<>(SELECT count(DISTINCT x) FROM unnest(ids) x)
 OR cardinality(ids)<>(SELECT count(*) FROM gis.gee_safety_requests WHERE job_id=j.id AND attempt_no=j.attempt_count AND lease_token=j.lease_token)
 OR cardinality(ids)<>(SELECT count(*) FROM gis.gee_transport_receipts t JOIN gis.gee_safety_requests b ON b.id=t.request_id
 WHERE t.request_id=ANY(ids) AND t.job_id=j.id AND t.recorder_id=subject AND b.state='attempted'
 AND b.attempt_no=j.attempt_count AND b.lease_token=j.lease_token)
 OR NOT EXISTS(SELECT 1 FROM gis.gee_transport_receipts WHERE request_id=ANY(ids) AND category='compute' AND status=200)
 THEN RAISE EXCEPTION 'GIS_TRANSPORT_RECEIPT_SET_REJECTED'; END IF;
 SELECT t.observation INTO obs FROM gis.gee_transport_receipts t WHERE t.request_id=ANY(ids) AND t.category='compute' AND t.status=200 ORDER BY t.created_at DESC,t.request_id DESC LIMIT 1;
 evidence:=output->'content'->'evidence';
 IF obs->'scene_count' IS DISTINCT FROM evidence->'scene_count' OR obs->'complete' IS DISTINCT FROM evidence->'complete'
 OR obs->'valid_pixels' IS DISTINCT FROM evidence->'valid_pixels'
 OR obs->'mean' IS DISTINCT FROM evidence->'raw_statistics'->'mean'
 OR obs->'min' IS DISTINCT FROM evidence->'raw_statistics'->'min' OR obs->'max' IS DISTINCT FROM evidence->'raw_statistics'->'max'
 OR obs->'scene_ids' IS DISTINCT FROM (SELECT COALESCE(jsonb_agg(x->>'image_id'),'[]'::jsonb) FROM jsonb_array_elements(evidence->'scenes') x)
 OR (SELECT jsonb_agg((to_timestamp(value::numeric/1000) AT TIME ZONE 'UTC')::date::text) FROM jsonb_array_elements_text(obs->'acquired_ms')) IS DISTINCT FROM
 (SELECT jsonb_agg(x->>'acquired') FROM jsonb_array_elements(evidence->'scenes') x)
 THEN RAISE EXCEPTION 'GIS_TRANSPORT_OBSERVATION_MISMATCH'; END IF;
 sha:=output->'content'->>'evidence_sha256';
 FOREACH rid IN ARRAY ids LOOP
  PERFORM gis.safety_budget(a.worker_id,'finished',jsonb_build_object('job_id',j.id,'lease_token',j.lease_token,'request_id',rid,'evidence_sha256',sha));
 END LOOP;
 valid:=output->'content'->>'status'='candidate';
 wrapped:=jsonb_build_object('schema_version',3,'protocol','gee_safety_rehearsal','execution','rehearsal','live_enabled',false,
 'session_id',a.session_id,'policy_sha256',(SELECT policy_sha256 FROM gis.gee_safety_sessions WHERE id=a.session_id),
 'valid',valid,'error_code',CASE WHEN valid THEN NULL ELSE 'invalid_data' END,
 'base',jsonb_build_object('schema_version',2,'protocol','gee_live_v2','valid',valid,'error_code',CASE WHEN valid THEN NULL ELSE 'invalid_data' END,
 'input_hash',j.input_hash,'input_revision',j.input_revision,'semantic_request_sha256',a.request_sha256,'output',output,
 'output_canonical',gis.gee_live_canonical(output->'content'),'evidence_canonical',gis.gee_live_canonical(evidence)),
 'receipts',to_jsonb(ids),'failure_kind',null);
 -- Full scientific/output/request validation BEFORE seal; hashes alone cannot
 -- authorize an observation. The stored mode always remains synthetic fake_http.
 PERFORM gis.a6_transport_previous_validate_safety_report(wrapped,(SELECT e FROM gis.editions e WHERE e.id=j.edition_id),j);
 INSERT INTO gis.gee_transport_seals(job_id,attempt_no,lease_token,output_sha256,evidence_sha256,receipts,recorder_id)
 VALUES(j.id,j.attempt_count,j.lease_token,output->>'output_sha256',sha,ids,subject);
 INSERT INTO gis.audit(operation,job_id,detail) VALUES('transport.seal_fake',j.id,jsonb_build_object('attempt',j.attempt_count,'mode',a.mode,'publishable',false));
 RETURN wrapped;
END $f$;

CREATE FUNCTION public.gis_gee_transport_recorder(p_action text,p_payload jsonb DEFAULT '{}') RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
BEGIN
 RETURN gis.transport_record(gis.transport_subject(),p_action,p_payload);
END $f$;

-- Enforce the recorder invariant at transaction commit too (old RPC/direct
-- owner writes cannot leave an authority-bound candidate without its seal).
CREATE FUNCTION gis.check_transport_catalog() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE j gis.jobs%ROWTYPE;e gis.editions%ROWTYPE;r gis.results%ROWTYPE;
BEGIN
 SELECT * INTO j FROM gis.jobs WHERE id=NEW.job_id;
 IF j.state='succeeded' THEN
  SELECT worker_id,lease_token INTO j.worker_id,j.lease_token FROM gis.attempts WHERE job_id=j.id AND attempt_no=j.attempt_count;
  SELECT * INTO e FROM gis.editions WHERE id=j.edition_id;
  SELECT * INTO r FROM gis.results WHERE job_id=j.id;
  PERFORM gis.validate_safety_report(r.report,e,j);
 END IF;
 RETURN NULL;
END $f$;
CREATE CONSTRAINT TRIGGER transport_candidate_integrity AFTER INSERT ON gis.gee_transport_seals
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION gis.check_transport_catalog();

DO $acl$ DECLARE f record; BEGIN
 FOR f IN SELECT p.oid::regprocedure AS signature FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
 WHERE (n.nspname='gis' AND p.proname IN ('transport_authorize_fake','transport_subject','transport_record','validate_safety_report',
 'a6_transport_previous_validate_safety_report','check_transport_catalog'))
 OR (n.nspname='public' AND p.proname='gis_gee_transport_recorder') LOOP
  EXECUTE format('REVOKE ALL ON FUNCTION %s FROM PUBLIC,anon,authenticated,service_role,gis_worker,gis_native_worker,gis_gee_mock_worker,gis_gee_live_worker,gis_gee_safety_worker,gis_gee_transport_recorder',f.signature);
 END LOOP;
END $acl$;
GRANT EXECUTE ON FUNCTION public.gis_gee_transport_recorder(text,jsonb) TO gis_gee_transport_recorder;
REVOKE CREATE ON SCHEMA public FROM gis_owner;
RESET ROLE;
NOTIFY pgrst,'reload schema';
