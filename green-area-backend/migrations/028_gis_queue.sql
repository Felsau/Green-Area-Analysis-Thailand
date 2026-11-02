-- Durable queue primitives. No worker process or scientific validator is started.
SET LOCAL ROLE gis_owner;
SELECT gis.assert_environment();
CREATE TABLE gis.jobs(
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 edition_id uuid NOT NULL REFERENCES gis.editions(id),
 parent_job_id uuid UNIQUE REFERENCES gis.jobs(id),
 kind text NOT NULL DEFAULT 'validate_synthetic_edition' CHECK(kind='validate_synthetic_edition'),
 input_revision integer NOT NULL CHECK(input_revision>0),
 input_hash text NOT NULL CHECK(input_hash ~ '^[0-9a-f]{64}$'),
 validator_version text NOT NULL DEFAULT 'synthetic-v1' CHECK(validator_version='synthetic-v1'),
 state text NOT NULL DEFAULT 'queued' CHECK(state IN ('queued','running','succeeded','failed')),
 attempt_count integer NOT NULL DEFAULT 0 CHECK(attempt_count BETWEEN 0 AND 3),
 available_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 worker_id uuid,lease_token uuid,lease_until timestamptz,
 progress integer NOT NULL DEFAULT 0 CHECK(progress BETWEEN 0 AND 100),
 error_code text CHECK(error_code IN ('invalid_data','transient','attempts_exhausted')),
 requested_by uuid REFERENCES public.profiles(id) ON DELETE SET NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(), finished_at timestamptz,
 CHECK((state='running' AND worker_id IS NOT NULL AND lease_token IS NOT NULL AND lease_until IS NOT NULL)
    OR (state<>'running' AND worker_id IS NULL AND lease_token IS NULL AND lease_until IS NULL)));
CREATE UNIQUE INDEX jobs_one_active ON gis.jobs(edition_id) WHERE state IN ('queued','running');
CREATE UNIQUE INDEX jobs_original_fingerprint ON gis.jobs(edition_id,input_revision,input_hash,validator_version) WHERE parent_job_id IS NULL;
CREATE INDEX jobs_ready ON gis.jobs(available_at,created_at,id) WHERE state='queued';
CREATE TABLE gis.attempts(
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),job_id uuid NOT NULL REFERENCES gis.jobs(id),
 attempt_no integer NOT NULL CHECK(attempt_no BETWEEN 1 AND 3),worker_id uuid NOT NULL,lease_token uuid NOT NULL UNIQUE,
 state text NOT NULL CHECK(state IN ('running','succeeded','failed','expired')),
 progress integer NOT NULL DEFAULT 0 CHECK(progress BETWEEN 0 AND 100),
 error_code text,started_at timestamptz NOT NULL DEFAULT clock_timestamp(),finished_at timestamptz,
 UNIQUE(job_id,attempt_no),UNIQUE(job_id,attempt_no,lease_token));
CREATE TABLE gis.results(
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),job_id uuid NOT NULL UNIQUE REFERENCES gis.jobs(id),
 edition_id uuid NOT NULL REFERENCES gis.editions(id),
 input_revision integer NOT NULL,input_hash text NOT NULL,validator_version text NOT NULL,
 attempt_no integer NOT NULL,lease_token uuid NOT NULL,
 provider text NOT NULL DEFAULT 'synthetic' CHECK(provider='synthetic'),
 valid boolean NOT NULL CHECK(valid),report jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),UNIQUE(id,edition_id),
 FOREIGN KEY(job_id,attempt_no,lease_token) REFERENCES gis.attempts(job_id,attempt_no,lease_token));
ALTER TABLE gis.editions ADD CONSTRAINT edition_result_same_edition FOREIGN KEY(validated_result_id,id) REFERENCES gis.results(id,edition_id);
ALTER TABLE gis.audit ADD CONSTRAINT audit_job_fk FOREIGN KEY(job_id) REFERENCES gis.jobs(id);
DO $rls$
DECLARE t text;
BEGIN
 FOREACH t IN ARRAY ARRAY['jobs','attempts','results'] LOOP
  EXECUTE format('ALTER TABLE gis.%I ENABLE ROW LEVEL SECURITY',t);
  EXECUTE format('ALTER TABLE gis.%I FORCE ROW LEVEL SECURITY',t);
  EXECUTE format('CREATE POLICY owner_access ON gis.%I TO gis_owner USING(true) WITH CHECK(true)',t);
 END LOOP;
END $rls$;

CREATE FUNCTION gis.worker(p_action text,p_payload jsonb DEFAULT '{}') RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE j gis.jobs%ROWTYPE; e gis.editions%ROWTYPE; worker uuid; token uuid;
 v_now timestamptz; eid uuid; jid uuid; code text; next_state text; n integer:=0;
 progress_value integer; report_value jsonb; rid uuid; candidate record;
BEGIN
 PERFORM gis.assert_environment();
 IF p_action='claim' THEN
  PERFORM gis.keys(p_payload,ARRAY['worker_id']); worker:=(p_payload->>'worker_id')::uuid;
  IF worker IS NULL THEN RAISE EXCEPTION 'GIS_WORKER_REQUIRED'; END IF;
  IF NOT pg_try_advisory_xact_lock(hashtextextended('gis-t1-single-claim',0)) THEN RETURN NULL; END IF;
  -- One concurrent native validation. Expired work must be recovered first.
  IF EXISTS(SELECT 1 FROM gis.jobs WHERE state='running') THEN RETURN NULL; END IF;
  SELECT * INTO j FROM gis.jobs WHERE state='queued' AND attempt_count<3 AND available_at<=clock_timestamp()
   ORDER BY available_at,created_at,id FOR UPDATE SKIP LOCKED LIMIT 1;
  IF NOT FOUND THEN RETURN NULL; END IF;
  v_now:=clock_timestamp(); token:=gen_random_uuid();
  UPDATE gis.jobs SET state='running',attempt_count=attempt_count+1,worker_id=worker,
   lease_token=token,lease_until=v_now+interval '60 seconds',progress=0,error_code=NULL WHERE id=j.id RETURNING * INTO j;
  INSERT INTO gis.attempts(job_id,attempt_no,worker_id,lease_token,state,started_at)
   VALUES(j.id,j.attempt_count,worker,token,'running',v_now);
  -- Inputs are frozen by edition state; claim never locks or changes edition.
  SELECT * INTO e FROM gis.editions WHERE id=j.edition_id;
  RETURN jsonb_build_object('job_id',j.id,'edition_id',j.edition_id,'worker_id',worker,'lease_token',token,
   'lease_until',j.lease_until,'attempt_no',j.attempt_count,'input_revision',j.input_revision,
   'input_hash',j.input_hash,'validator_version',j.validator_version,'manifest',e.manifest);
 ELSIF p_action='recover' THEN
  PERFORM gis.keys(p_payload,ARRAY[]::text[]);
  FOR candidate IN SELECT id,edition_id FROM gis.jobs WHERE state='running' AND lease_until<=clock_timestamp()
      ORDER BY lease_until,id LIMIT 20 LOOP
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
    VALUES('worker.recover',e.dataset_id,e.id,j.id,jsonb_build_object('attempt',j.attempt_count,'terminal',j.attempt_count=3));
   n:=n+1;
  END LOOP;
  RETURN jsonb_build_object('recovered',n);
 ELSIF p_action IN ('heartbeat','complete','fail') THEN
  PERFORM gis.keys(p_payload,CASE p_action
   WHEN 'heartbeat' THEN ARRAY['job_id','worker_id','lease_token','progress']
   WHEN 'complete' THEN ARRAY['job_id','worker_id','lease_token','report']
   ELSE ARRAY['job_id','worker_id','lease_token','error_code'] END);
  jid:=(p_payload->>'job_id')::uuid;worker:=(p_payload->>'worker_id')::uuid;token:=(p_payload->>'lease_token')::uuid;
  IF p_action<>'heartbeat' THEN
   SELECT edition_id INTO eid FROM gis.jobs WHERE id=jid;
   SELECT * INTO e FROM gis.editions WHERE id=eid FOR UPDATE;
  END IF;
  SELECT * INTO j FROM gis.jobs WHERE id=jid FOR UPDATE;
  v_now:=clock_timestamp(); -- Deliberately after all row locks.
  IF NOT FOUND OR j.state<>'running' OR j.worker_id IS DISTINCT FROM worker
     OR j.lease_token IS DISTINCT FROM token OR j.lease_until<=v_now THEN
   RAISE EXCEPTION 'GIS_STALE_LEASE'; END IF;
  IF p_action='heartbeat' THEN
   progress_value:=(p_payload->>'progress')::integer;
   IF progress_value IS NULL OR progress_value<j.progress OR progress_value>99 THEN RAISE EXCEPTION 'GIS_INVALID_PROGRESS'; END IF;
   UPDATE gis.jobs SET progress=progress_value,lease_until=v_now+interval '60 seconds' WHERE id=j.id;
   UPDATE gis.attempts SET progress=progress_value WHERE job_id=j.id AND attempt_no=j.attempt_count AND lease_token=token;
   RETURN jsonb_build_object('job_id',j.id,'lease_until',v_now+interval '60 seconds','progress',progress_value);
  END IF;
  IF e.state<>'validating' OR e.input_revision<>j.input_revision OR e.input_hash<>j.input_hash THEN
   RAISE EXCEPTION 'GIS_INPUT_CHANGED'; END IF;
  IF p_action='complete' THEN
   report_value:=p_payload->'report';
   PERFORM gis.keys(report_value,ARRAY['valid','fixture_id','checks']);
   IF report_value->'valid' IS DISTINCT FROM 'true'::jsonb
     OR report_value->>'fixture_id' IS DISTINCT FROM e.manifest->>'fixture_id'
     OR jsonb_typeof(report_value->'checks') IS DISTINCT FROM 'array'
     OR jsonb_array_length(report_value->'checks')>30
     OR EXISTS(SELECT 1 FROM jsonb_array_elements(report_value->'checks') v
       WHERE jsonb_typeof(v)<>'string' OR v#>>'{}' NOT IN ('synthetic_fixture_match','metadata_shape','source_hash_match','bounded_input'))
     OR NOT EXISTS(SELECT 1 FROM gis.synthetic_fixtures WHERE manifest=e.manifest)
     OR e.manifest->>'fixture_id' IN ('invalid-v1','transient-v1') THEN RAISE EXCEPTION 'GIS_INVALID_RESULT'; END IF;
   INSERT INTO gis.results(job_id,edition_id,input_revision,input_hash,validator_version,attempt_no,lease_token,valid,report)
    VALUES(j.id,e.id,j.input_revision,j.input_hash,j.validator_version,j.attempt_count,token,true,report_value) RETURNING id INTO rid;
   UPDATE gis.editions SET state='validated',validated_result_id=rid WHERE id=e.id;
   UPDATE gis.jobs SET state='succeeded',worker_id=NULL,lease_token=NULL,lease_until=NULL,progress=100,finished_at=v_now WHERE id=j.id;
   UPDATE gis.attempts SET state='succeeded',progress=100,finished_at=v_now WHERE job_id=j.id AND attempt_no=j.attempt_count AND lease_token=token;
   INSERT INTO gis.audit(operation,dataset_id,edition_id,job_id,detail)
    VALUES('worker.complete',e.dataset_id,e.id,j.id,jsonb_build_object('result_id',rid,'attempt',j.attempt_count));
   RETURN jsonb_build_object('job_id',j.id,'state','succeeded','result_id',rid);
  END IF;
  code:=p_payload->>'error_code';
  IF code IS NULL OR code NOT IN ('invalid_data','transient') THEN RAISE EXCEPTION 'GIS_INVALID_FAILURE'; END IF;
  next_state:=CASE WHEN code='transient' AND j.attempt_count<3 THEN 'queued' ELSE 'failed' END;
  UPDATE gis.attempts SET state='failed',error_code=code,finished_at=v_now WHERE job_id=j.id AND attempt_no=j.attempt_count AND lease_token=token;
  UPDATE gis.jobs SET state=next_state,worker_id=NULL,lease_token=NULL,lease_until=NULL,
   error_code=CASE WHEN next_state='failed' THEN code ELSE NULL END,progress=0,
   available_at=v_now+make_interval(secs=>CASE j.attempt_count WHEN 1 THEN 5 ELSE 20 END+floor(random()*3)::int),
   finished_at=CASE WHEN next_state='failed' THEN v_now ELSE NULL END WHERE id=j.id;
  IF next_state='failed' THEN UPDATE gis.editions SET state='draft' WHERE id=e.id; END IF;
  INSERT INTO gis.audit(operation,dataset_id,edition_id,job_id,detail)
   VALUES('worker.fail',e.dataset_id,e.id,j.id,jsonb_build_object('attempt',j.attempt_count,'error_code',code,'state',next_state));
  RETURN jsonb_build_object('job_id',j.id,'state',next_state);
 END IF;
 RAISE EXCEPTION 'GIS_UNKNOWN_WORKER_ACTION';
END $f$;
REVOKE ALL ON ALL TABLES IN SCHEMA gis FROM PUBLIC,anon,authenticated,service_role,gis_worker;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA gis FROM PUBLIC,anon,authenticated,service_role,gis_worker;
RESET ROLE;
