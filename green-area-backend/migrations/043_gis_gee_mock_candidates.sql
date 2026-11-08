-- A6.2 internal mock-only protocol. No HTTP live mode, Google access or publication.
-- The attested operator supplies BEGIN/runtime proof and INSERT-only ledger entry.
DO $guard$ BEGIN
 IF current_database() NOT IN ('postgres','gis_t1_upgrade') OR NOT gis.target_ok()
 OR NOT EXISTS(SELECT 1 FROM gis.environment WHERE singleton AND NOT activation_enabled
   AND runtime_instance=current_setting('gis.runtime_instance',true) AND baseline_fingerprint=current_setting('gis.baseline_fingerprint',true))
 OR NOT EXISTS(SELECT 1 FROM gis.schema_migrations WHERE version=42 AND sha256='f77fc41804e03f1021110ef00854cf95c8e77b86af1f90e0093f8c9f7ebde476')
 OR EXISTS(SELECT 1 FROM gis.schema_migrations WHERE version>=43) THEN
  RAISE EXCEPTION 'GIS_LOCAL_BASELINE_042_REQUIRED'; END IF;
END $guard$;
DO $role$ BEGIN
 IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='gis_gee_mock_worker') THEN
  IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='gis_gee_mock_worker' AND NOT rolsuper AND NOT rolbypassrls
   AND NOT rolcanlogin AND NOT rolcreatedb AND NOT rolcreaterole AND NOT rolreplication AND NOT rolinherit
   AND shobj_description(oid,'pg_authid')='gis-a6.2-mock-only')
   OR EXISTS(SELECT 1 FROM pg_auth_members WHERE member='gis_gee_mock_worker'::regrole)
   OR EXISTS(SELECT 1 FROM pg_auth_members WHERE roleid='gis_gee_mock_worker'::regrole AND member NOT IN ('postgres'::regrole,'authenticator'::regrole))
  THEN RAISE EXCEPTION 'GIS_GEE_MOCK_ROLE_COLLISION'; END IF;
 ELSE
  CREATE ROLE gis_gee_mock_worker NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOREPLICATION NOINHERIT;
 END IF;
END $role$;
COMMENT ON ROLE gis_gee_mock_worker IS 'gis-a6.2-mock-only';
GRANT gis_gee_mock_worker TO authenticator WITH INHERIT FALSE, SET TRUE;
GRANT USAGE ON SCHEMA public TO gis_gee_mock_worker;
REVOKE ALL ON SCHEMA gis FROM gis_gee_mock_worker;
GRANT CREATE ON SCHEMA public TO gis_owner;
SET LOCAL ROLE gis_owner;
SELECT gis.assert_environment();

-- No registration RPC: only the attested test operator installs A6.1-validated
-- synthetic cases. These records never attest to real observations.
CREATE TABLE gis.gee_mock_cases(
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 value jsonb NOT NULL CHECK(jsonb_typeof(value)='object'),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp());
CREATE UNIQUE INDEX gee_mock_cases_content ON gis.gee_mock_cases((value->>'request_sha256'),(value->>'output_sha256'));
CREATE TABLE gis.gee_mock_requests(
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 case_id uuid NOT NULL UNIQUE REFERENCES gis.gee_mock_cases(id),
 dataset_id uuid NOT NULL REFERENCES gis.datasets(id),
 edition_id uuid NOT NULL UNIQUE,job_id uuid NOT NULL UNIQUE REFERENCES gis.jobs(id),
 requested_by uuid REFERENCES public.profiles(id) ON DELETE SET NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 FOREIGN KEY(edition_id,dataset_id) REFERENCES gis.editions(id,dataset_id));
CREATE TABLE gis.gee_candidates(
 result_id uuid PRIMARY KEY REFERENCES gis.results(id),job_id uuid NOT NULL UNIQUE REFERENCES gis.jobs(id),
 request_id uuid NOT NULL UNIQUE REFERENCES gis.gee_mock_requests(id),
 dataset_id uuid NOT NULL REFERENCES gis.datasets(id),edition_id uuid NOT NULL,
 input_revision integer NOT NULL CHECK(input_revision=1),input_hash text NOT NULL CHECK(input_hash ~ '^[0-9a-f]{64}$'),
 semantic_request_sha256 text NOT NULL CHECK(semantic_request_sha256 ~ '^[0-9a-f]{64}$'),
 output_sha256 text NOT NULL CHECK(output_sha256 ~ '^[0-9a-f]{64}$'),
 worker_id uuid NOT NULL,attempt_no integer NOT NULL,lease_token uuid NOT NULL,
 output jsonb NOT NULL CHECK(jsonb_typeof(output)='object'),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 FOREIGN KEY(edition_id,dataset_id) REFERENCES gis.editions(id,dataset_id),
 FOREIGN KEY(job_id,attempt_no,lease_token) REFERENCES gis.attempts(job_id,attempt_no,lease_token));
DO $rls$ DECLARE t text; BEGIN
 FOREACH t IN ARRAY ARRAY['gee_mock_cases','gee_mock_requests','gee_candidates'] LOOP
  EXECUTE format('ALTER TABLE gis.%I ENABLE ROW LEVEL SECURITY',t);
  EXECUTE format('ALTER TABLE gis.%I FORCE ROW LEVEL SECURITY',t);
  EXECUTE format('CREATE POLICY owner_access ON gis.%I TO gis_owner USING(true) WITH CHECK(true)',t);
  EXECUTE format('REVOKE ALL ON gis.%I FROM PUBLIC,anon,authenticated,service_role,gis_worker,gis_native_worker,gis_gee_mock_worker',t);
 END LOOP;
END $rls$;
CREATE FUNCTION gis.gee_mock_immutable() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
BEGIN RAISE EXCEPTION 'GIS_GEE_MOCK_IMMUTABLE'; END $f$;
DO $immutable$ DECLARE t text; BEGIN
 FOREACH t IN ARRAY ARRAY['gee_mock_cases','gee_mock_requests','gee_candidates'] LOOP
  EXECUTE format('CREATE TRIGGER immutable_gee_mock BEFORE UPDATE OR DELETE ON gis.%I FOR EACH ROW EXECUTE FUNCTION gis.gee_mock_immutable()',t);
 END LOOP;
END $immutable$;

CREATE FUNCTION gis.validate_gee_mock_case() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE v jsonb:=NEW.value; r jsonb; o jsonb; y integer; m integer; product text; method text; start_value date; end_value date;
BEGIN
 PERFORM gis.assert_environment();
 PERFORM gis.keys(v,ARRAY['request','request_canonical','request_sha256','geometry','geometry_canonical','geometry_sha256','output','output_canonical','output_sha256']);
 IF NOT v ?& ARRAY['request','request_canonical','request_sha256','geometry','geometry_canonical','geometry_sha256','output','output_canonical','output_sha256']
 OR octet_length(v::text)>32768 THEN RAISE EXCEPTION 'GIS_GEE_MOCK_CASE_INVALID'; END IF;
 IF COALESCE(v->>'request_sha256','') !~ '^[0-9a-f]{64}$'
 OR COALESCE(v->>'geometry_sha256','') !~ '^[0-9a-f]{64}$'
 OR COALESCE(v->>'output_sha256','') !~ '^[0-9a-f]{64}$' THEN RAISE EXCEPTION 'GIS_GEE_MOCK_HASH_MISMATCH'; END IF;
 r:=v->'request';o:=v->'output'->'content';
 IF r->'schema_version' IS DISTINCT FROM '1'::jsonb OR r->>'mode' IS DISTINCT FROM 'live_gee'
 OR r->'input_revision' IS DISTINCT FROM '1'::jsonb OR r->'boundary'->>'scope' IS DISTINCT FROM 'province'
 OR r->'boundary'->>'crs' IS DISTINCT FROM 'EPSG:4326'
 OR r->>'product' NOT IN ('ndvi','lst') OR r->>'product' IS NULL
 OR COALESCE(r->'period'->>'year','') !~ '^[0-9]{4}$' OR COALESCE(r->'period'->>'month','') !~ '^[0-9]{1,2}$'
 OR NOT EXISTS(SELECT 1 FROM public.provinces WHERE name_en=r->'boundary'->>'province') THEN
  RAISE EXCEPTION 'GIS_GEE_MOCK_REQUEST_INVALID'; END IF;
 y:=(r->'period'->>'year')::integer;m:=(r->'period'->>'month')::integer;product:=r->>'product';
 IF y<(CASE WHEN product='ndvi' THEN 2017 ELSE 2013 END) OR y>2200 OR m NOT BETWEEN 0 AND 12 THEN RAISE EXCEPTION 'GIS_GEE_MOCK_PERIOD_INVALID'; END IF;
 start_value:=make_date(y,CASE WHEN m=0 THEN 1 ELSE m END,1);
 end_value:=CASE WHEN m=0 THEN make_date(y+1,1,1) ELSE (start_value+interval '1 month')::date END;
 method:=product||CASE WHEN m=0 THEN '-annual-legacy-v1' ELSE '-monthly-legacy-v1' END;
 IF r->'period'->>'start' IS DISTINCT FROM start_value::text OR r->'period'->>'end_exclusive' IS DISTINCT FROM end_value::text
 OR r->>'method_version' IS DISTINCT FROM method
 OR o->'schema_version' IS DISTINCT FROM '1'::jsonb OR o->>'mode' IS DISTINCT FROM 'live_gee'
 OR o->>'execution' IS DISTINCT FROM 'mock' OR o->'synthetic' IS DISTINCT FROM 'true'::jsonb
 OR o->'publishable' IS DISTINCT FROM 'false'::jsonb OR o->>'endpoint_parity' IS DISTINCT FROM 'summary_only'
 OR o->'boundary' IS DISTINCT FROM r->'boundary' OR o->'period' IS DISTINCT FROM r->'period'
 OR o->'input_revision' IS DISTINCT FROM r->'input_revision' OR o->'method'->>'version' IS DISTINCT FROM method
 OR o->'method'->>'product' IS DISTINCT FROM product
 OR o->'method'->>'units' IS DISTINCT FROM (CASE WHEN product='ndvi' THEN 'unitless' ELSE 'celsius' END)
 OR o->>'status' NOT IN ('candidate','no_data','incomplete','failed') OR o->>'status' IS NULL THEN
  RAISE EXCEPTION 'GIS_GEE_MOCK_OUTPUT_INVALID'; END IF;
 -- Python's A6.1 validator owns canonical formatting and scientific invariants.
 -- SQL independently binds exact parsed documents and their declared byte hashes;
 -- workers/clients have no permission to register or replace those documents.
 IF (v->>'request_canonical')::jsonb IS DISTINCT FROM jsonb_build_object('request',r-'request_id','method',o->'method')
 OR (v->>'geometry_canonical')::jsonb IS DISTINCT FROM v->'geometry'
 OR (v->>'output_canonical')::jsonb IS DISTINCT FROM o
 OR v->>'request_sha256' IS DISTINCT FROM encode(sha256(convert_to(v->>'request_canonical','UTF8')),'hex')
 OR v->>'geometry_sha256' IS DISTINCT FROM encode(sha256(convert_to(v->>'geometry_canonical','UTF8')),'hex')
 OR v->>'output_sha256' IS DISTINCT FROM encode(sha256(convert_to(v->>'output_canonical','UTF8')),'hex')
 OR r->'boundary'->>'geometry_sha256' IS DISTINCT FROM v->>'geometry_sha256'
 OR o->>'request_hash' IS DISTINCT FROM v->>'request_sha256'
 OR v->'output'->>'output_sha256' IS DISTINCT FROM v->>'output_sha256' THEN
  RAISE EXCEPTION 'GIS_GEE_MOCK_HASH_MISMATCH'; END IF;
 RETURN NEW;
END $f$;
CREATE TRIGGER validate_case BEFORE INSERT ON gis.gee_mock_cases FOR EACH ROW EXECUTE FUNCTION gis.validate_gee_mock_case();

CREATE FUNCTION gis.gee_mock_manifest(p_case uuid) RETURNS jsonb
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
 SELECT jsonb_build_object('schema_version',6,'provider','gee_contract_mock','execution','mock','case_id',c.id,
  'semantic_request_sha256',c.value->>'request_sha256','geometry_sha256',c.value->>'geometry_sha256',
  'method_version',c.value->'request'->>'method_version') FROM gis.gee_mock_cases c WHERE c.id=p_case
$f$;
ALTER FUNCTION gis.manifest_hash(jsonb) RENAME TO a62_previous_manifest_hash;
CREATE FUNCTION gis.manifest_hash(p_manifest jsonb) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
BEGIN
 IF p_manifest->'schema_version' IS DISTINCT FROM '6'::jsonb THEN RETURN gis.a62_previous_manifest_hash(p_manifest); END IF;
 IF p_manifest IS DISTINCT FROM gis.gee_mock_manifest((p_manifest->>'case_id')::uuid) OR p_manifest IS NULL THEN
  RAISE EXCEPTION 'GIS_GEE_MOCK_MANIFEST_INVALID'; END IF;
 RETURN encode(sha256(convert_to(p_manifest::text,'UTF8')),'hex');
END $f$;
ALTER FUNCTION gis.edition_protocol(uuid) RENAME TO a62_previous_edition_protocol;
CREATE FUNCTION gis.edition_protocol(p_edition uuid) RETURNS text
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
 SELECT CASE WHEN e.manifest->'schema_version'='6'::jsonb THEN
  CASE WHEN EXISTS(SELECT 1 FROM gis.gee_mock_requests q WHERE q.edition_id=e.id) THEN 'gee_contract_mock' ELSE 'unsupported' END
  ELSE gis.a62_previous_edition_protocol(p_edition) END FROM gis.editions e WHERE e.id=p_edition
$f$;
ALTER FUNCTION gis.eligible(uuid,uuid) RENAME TO a62_previous_eligible;
CREATE FUNCTION gis.eligible(p_edition uuid,p_dataset uuid) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
 SELECT CASE WHEN EXISTS(SELECT 1 FROM gis.editions WHERE id=p_edition AND manifest->'schema_version'='6'::jsonb)
  THEN false ELSE gis.a62_previous_eligible(p_edition,p_dataset) END
$f$;
ALTER TABLE gis.jobs DROP CONSTRAINT jobs_kind_check;
ALTER TABLE gis.jobs ADD CONSTRAINT jobs_kind_check CHECK(kind IN ('validate_synthetic_edition','validate_ldd_edition','process_offline_edition','validate_geotiff_edition','prepare_ldd_edition','prepare_geotiff_edition','process_gee_mock_edition'));
ALTER TABLE gis.jobs DROP CONSTRAINT jobs_validator_version_check;
ALTER TABLE gis.jobs ADD CONSTRAINT jobs_validator_version_check CHECK(validator_version IN ('synthetic-v1','ldd-local-v1','gee-offline-v1','geotiff-local-v1','ldd-prepare-v1','geotiff-prepare-v1','gee-contract-mock-v1'));
ALTER TABLE gis.results DROP CONSTRAINT results_provider_check;
ALTER TABLE gis.results ADD CONSTRAINT results_provider_check CHECK(provider IN ('synthetic','local_ldd','offline_processing','local_geotiff','local_ldd_prepare','local_geotiff_prepare','gee_contract_mock'));

CREATE FUNCTION gis.gee_mock_claim_packet(p_job uuid) RETURNS jsonb
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
 SELECT jsonb_build_object('request_id',q.id,'request',c.value->'request','geometry',c.value->'geometry',
   'semantic_request_sha256',c.value->>'request_sha256') FROM gis.gee_mock_requests q JOIN gis.gee_mock_cases c ON c.id=q.case_id WHERE q.job_id=p_job
$f$;
CREATE FUNCTION gis.validate_gee_mock_report(p_report jsonb,p_edition gis.editions,p_job gis.jobs) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE c gis.gee_mock_cases%ROWTYPE; expected_valid boolean; expected_error text;
BEGIN
 SELECT x.* INTO c FROM gis.gee_mock_cases x JOIN gis.gee_mock_requests q ON q.case_id=x.id
  WHERE q.edition_id=p_edition.id AND q.job_id=p_job.id AND q.dataset_id=p_edition.dataset_id;
 IF NOT FOUND OR p_job.kind<>'process_gee_mock_edition' OR p_job.validator_version<>'gee-contract-mock-v1'
 OR p_edition.input_revision<>1 OR p_job.input_revision<>p_edition.input_revision OR p_job.input_hash<>p_edition.input_hash
 OR p_edition.input_hash<>gis.manifest_hash(p_edition.manifest) THEN RAISE EXCEPTION 'GIS_GEE_MOCK_INPUT_MISMATCH'; END IF;
 PERFORM gis.keys(p_report,ARRAY['schema_version','protocol','input_hash','input_revision','semantic_request_sha256','valid','error_code','output']);
 IF NOT p_report ?& ARRAY['schema_version','protocol','input_hash','input_revision','semantic_request_sha256','valid','error_code','output']
 OR p_report->'schema_version' IS DISTINCT FROM '1'::jsonb OR p_report->>'protocol' IS DISTINCT FROM 'gee_contract_mock'
 OR p_report->>'input_hash' IS DISTINCT FROM p_job.input_hash OR p_report->'input_revision' IS DISTINCT FROM to_jsonb(p_job.input_revision)
 OR p_report->>'semantic_request_sha256' IS DISTINCT FROM c.value->>'request_sha256' THEN RAISE EXCEPTION 'GIS_GEE_MOCK_REPORT_INVALID'; END IF;
 IF p_report->>'error_code' IN ('NATIVE_TIMEOUT','NATIVE_MEMORY_LIMIT','NATIVE_PROCESS_FAILED','WORKER_SHUTDOWN','NATIVE_OUTPUT_LIMIT') THEN
  IF p_report->'valid' IS DISTINCT FROM 'false'::jsonb OR p_report->'output' IS DISTINCT FROM 'null'::jsonb THEN RAISE EXCEPTION 'GIS_GEE_MOCK_REPORT_INVALID'; END IF;
  RETURN;
 END IF;
 expected_valid:=c.value->'output'->'content'->>'status'='candidate';
 expected_error:=CASE WHEN expected_valid THEN NULL WHEN c.value->'output'->'content'->>'error_code'='GEE_TRANSIENT' THEN 'TRANSIENT_SYNTHETIC' ELSE 'invalid_data' END;
 IF p_report->'output' IS DISTINCT FROM c.value->'output' OR p_report->'valid' IS DISTINCT FROM to_jsonb(expected_valid)
 OR p_report->>'error_code' IS DISTINCT FROM expected_error THEN RAISE EXCEPTION 'GIS_GEE_MOCK_REPORT_NOT_ALLOWLISTED'; END IF;
END $f$;
CREATE FUNCTION gis.gee_mock_record_candidate(p_job uuid,p_result uuid,p_worker uuid) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
BEGIN
 INSERT INTO gis.gee_candidates(result_id,job_id,request_id,dataset_id,edition_id,input_revision,input_hash,
  semantic_request_sha256,output_sha256,worker_id,attempt_no,lease_token,output)
 SELECT p_result,j.id,q.id,e.dataset_id,e.id,j.input_revision,j.input_hash,c.value->>'request_sha256',
  c.value->>'output_sha256',p_worker,j.attempt_count,j.lease_token,c.value->'output'
 FROM gis.jobs j JOIN gis.editions e ON e.id=j.edition_id JOIN gis.gee_mock_requests q ON q.job_id=j.id
 JOIN gis.gee_mock_cases c ON c.id=q.case_id WHERE j.id=p_job;
 IF NOT FOUND THEN RAISE EXCEPTION 'GIS_GEE_MOCK_REQUEST_MISSING'; END IF;
END $f$;

CREATE FUNCTION gis.gee_mock_command(p_actor uuid,p_request_id uuid,p_operation text,p_payload jsonb,p_backend_mock boolean) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE c gis.gee_mock_cases%ROWTYPE; q gis.gee_mock_requests%ROWTYPE; d gis.datasets%ROWTYPE;
 e gis.editions%ROWTYPE; j gis.jobs%ROWTYPE; receipt gis.receipts%ROWTYPE; h text; body jsonb; m jsonb;
BEGIN
 PERFORM gis.authorize(p_actor,false);
 IF p_backend_mock IS DISTINCT FROM true OR p_operation IS DISTINCT FROM 'create' THEN RAISE EXCEPTION 'GIS_GEE_LIVE_DISABLED'; END IF;
 PERFORM gis.keys(p_payload,ARRAY['case_id']);
 IF p_request_id IS NULL OR NOT p_payload ? 'case_id' THEN RAISE EXCEPTION 'GIS_REQUEST_ID_REQUIRED'; END IF;
 h:=encode(sha256(convert_to(p_payload::text,'UTF8')),'hex');
 PERFORM pg_advisory_xact_lock(hashtextextended(p_actor::text||':'||p_request_id::text,0));
 SELECT * INTO receipt FROM gis.receipts WHERE actor_id=p_actor AND request_id=p_request_id;
 IF FOUND THEN
  IF receipt.operation<>'gee_mock.create' OR receipt.payload_hash<>h THEN RAISE EXCEPTION 'GIS_IDEMPOTENCY_CONFLICT'; END IF;
  RETURN jsonb_build_object('status',receipt.status,'body',receipt.body,'replayed',true);
 END IF;
 SELECT * INTO c FROM gis.gee_mock_cases WHERE id=(p_payload->>'case_id')::uuid;
 IF NOT FOUND THEN RAISE EXCEPTION 'GIS_GEE_MOCK_CASE_REQUIRED'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('gee-mock-case:'||c.id::text,0));
 SELECT * INTO q FROM gis.gee_mock_requests WHERE case_id=c.id;
 IF NOT FOUND THEN
  PERFORM pg_advisory_xact_lock(hashtextextended('gis-processing-dataset:'||(c.value->'request'->'boundary'->>'province')||':'||(c.value->'request'->'period'->>'year')||':'||(c.value->'request'->'period'->>'month')||':'||(c.value->'request'->>'product'),0));
  INSERT INTO gis.datasets(province,data_year,month,kind,purpose,title,created_by)
   VALUES(c.value->'request'->'boundary'->>'province',(c.value->'request'->'period'->>'year')::integer,
    (c.value->'request'->'period'->>'month')::integer,'geotiff',c.value->'request'->>'product','GEE contract mock (not live)',p_actor)
   ON CONFLICT(province,data_year,month,kind,purpose) DO NOTHING;
  SELECT * INTO d FROM gis.datasets WHERE province=c.value->'request'->'boundary'->>'province'
   AND data_year=(c.value->'request'->'period'->>'year')::integer AND month=(c.value->'request'->'period'->>'month')::integer
   AND kind='geotiff' AND purpose=c.value->'request'->>'product' FOR NO KEY UPDATE;
  m:=gis.gee_mock_manifest(c.id);
  INSERT INTO gis.editions(dataset_id,manifest,input_hash,created_by) VALUES(d.id,m,gis.manifest_hash(m),p_actor) RETURNING * INTO e;
  INSERT INTO gis.jobs(edition_id,kind,validator_version,input_revision,input_hash,requested_by)
   VALUES(e.id,'process_gee_mock_edition','gee-contract-mock-v1',e.input_revision,e.input_hash,p_actor) RETURNING * INTO j;
  INSERT INTO gis.gee_mock_requests(case_id,dataset_id,edition_id,job_id,requested_by)
   VALUES(c.id,d.id,e.id,j.id,p_actor) RETURNING * INTO q;
  UPDATE gis.editions SET state='validating' WHERE id=e.id;
 END IF;
 body:=jsonb_build_object('request_id',q.id,'job_id',q.job_id,'edition_id',q.edition_id,'dataset_id',q.dataset_id,
   'execution','mock','live_enabled',false,'publishable',false);
 INSERT INTO gis.receipts(actor_id,request_id,operation,payload_hash,status,body) VALUES(p_actor,p_request_id,'gee_mock.create',h,202,body);
 INSERT INTO gis.audit(actor_id,operation,dataset_id,edition_id,job_id,detail) VALUES(p_actor,'gee_mock.create',q.dataset_id,q.edition_id,q.job_id,jsonb_build_object('case_id',c.id,'execution','mock'));
 RETURN jsonb_build_object('status',202,'body',body,'replayed',false);
END $f$;

CREATE FUNCTION gis.gee_mock_subject() RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE c jsonb;
BEGIN
 PERFORM gis.assert_environment();
 IF session_user<>'authenticator' OR current_setting('role',true)<>'gis_gee_mock_worker' THEN RAISE EXCEPTION 'GIS_GEE_MOCK_IDENTITY_REQUIRED' USING ERRCODE='42501'; END IF;
 c:=NULLIF(current_setting('request.jwt.claims',true),'')::jsonb;
 IF c->>'role' IS DISTINCT FROM 'gis_gee_mock_worker' OR c->>'iss' IS DISTINCT FROM 'http://127.0.0.1:55421/auth/v1'
 OR COALESCE(c->>'sub','') !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' THEN
  RAISE EXCEPTION 'GIS_GEE_MOCK_IDENTITY_REQUIRED' USING ERRCODE='42501'; END IF;
 RETURN (c->>'sub')::uuid;
END $f$;
CREATE FUNCTION public.gis_gee_mock_worker(p_action text,p_payload jsonb DEFAULT '{}') RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE subject uuid; e gis.editions%ROWTYPE; j gis.jobs%ROWTYPE; a gis.attempts%ROWTYPE; r gis.results%ROWTYPE;
BEGIN
 subject:=gis.gee_mock_subject();
 PERFORM gis.keys(p_payload,CASE p_action WHEN 'claim' THEN ARRAY[]::text[] WHEN 'recover' THEN ARRAY[]::text[]
  WHEN 'heartbeat' THEN ARRAY['job_id','lease_token','progress'] WHEN 'complete' THEN ARRAY['job_id','lease_token','report']
  WHEN 'fail' THEN ARRAY['job_id','lease_token','report','error_code'] ELSE ARRAY[]::text[] END);
 IF p_action='recover' THEN RETURN gis.queue_protocol_kind(p_action,p_payload,'gee_contract_mock'); END IF;
 IF p_action='complete' THEN
  SELECT ed.* INTO e FROM gis.editions ed JOIN gis.jobs q ON q.edition_id=ed.id WHERE q.id=(p_payload->>'job_id')::uuid FOR UPDATE OF ed;
  SELECT * INTO j FROM gis.jobs WHERE id=(p_payload->>'job_id')::uuid FOR UPDATE;
  IF j.state='succeeded' AND gis.edition_protocol(e.id)='gee_contract_mock' THEN
   SELECT * INTO a FROM gis.attempts WHERE job_id=j.id AND attempt_no=j.attempt_count;
   SELECT * INTO r FROM gis.results WHERE job_id=j.id;
   IF a.worker_id IS DISTINCT FROM subject OR a.lease_token IS DISTINCT FROM (p_payload->>'lease_token')::uuid
    OR r.report IS DISTINCT FROM p_payload->'report' THEN RAISE EXCEPTION 'GIS_STALE_LEASE'; END IF;
   RETURN jsonb_build_object('job_id',j.id,'state','succeeded','result_id',r.id,'replayed',true);
  END IF;
 END IF;
 RETURN gis.queue_protocol_kind(p_action,p_payload||jsonb_build_object('worker_id',subject),'gee_contract_mock');
END $f$;
CREATE FUNCTION public.gis_gee_mock_readiness() RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE subject uuid;
BEGIN
 subject:=gis.gee_mock_subject();
 IF NOT EXISTS(SELECT 1 FROM gis.schema_migrations WHERE version=43) THEN RAISE EXCEPTION 'GIS_GEE_MOCK_NOT_READY'; END IF;
 RETURN (SELECT jsonb_build_object('subject',subject,'worker_role','gis_gee_mock_worker','database_name',database_name,
  'cluster_name',cluster_name,'runtime_instance',runtime_instance,'baseline_fingerprint',baseline_fingerprint,
  'protocol','gee_contract_mock','live_enabled',false,'contract_version','1.0.0-a6.2') FROM gis.environment WHERE singleton);
END $f$;
CREATE FUNCTION public.gis_gee_mock_command(p_actor uuid,p_request_id uuid,p_operation text,p_payload jsonb,p_backend_mock boolean DEFAULT false) RETURNS jsonb
LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
 SELECT gis.gee_mock_command(p_actor,p_request_id,p_operation,p_payload,p_backend_mock)
$f$;
CREATE FUNCTION public.gis_gee_mock_read(p_actor uuid,p_job uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
BEGIN
 PERFORM gis.authorize(p_actor,false);
 RETURN (SELECT jsonb_build_object('job',to_jsonb(j),'request',to_jsonb(q),'candidate',to_jsonb(c),
   'attempts',(SELECT COALESCE(jsonb_agg(to_jsonb(a) ORDER BY attempt_no),'[]') FROM gis.attempts a WHERE a.job_id=j.id))
  FROM gis.jobs j JOIN gis.gee_mock_requests q ON q.job_id=j.id LEFT JOIN gis.gee_candidates c ON c.job_id=j.id WHERE j.id=p_job);
END $f$;

CREATE FUNCTION gis.check_gee_mock_catalog() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE jid uuid; ids uuid[]; j gis.jobs%ROWTYPE; e gis.editions%ROWTYPE; q gis.gee_mock_requests%ROWTYPE;
 c gis.gee_mock_cases%ROWTYPE; a gis.attempts%ROWTYPE; r gis.results%ROWTYPE; candidate gis.gee_candidates%ROWTYPE;
BEGIN
 IF TG_TABLE_NAME='editions' THEN SELECT array_agg(id) INTO ids FROM gis.jobs WHERE edition_id=NEW.id AND kind='process_gee_mock_edition';
 ELSIF TG_TABLE_NAME='jobs' THEN ids:=ARRAY[NEW.id]; ELSE ids:=ARRAY[NEW.job_id]; END IF;
 FOREACH jid IN ARRAY COALESCE(ids,ARRAY[]::uuid[]) LOOP
  SELECT * INTO j FROM gis.jobs WHERE id=jid;
  IF j.kind<>'process_gee_mock_edition' THEN CONTINUE; END IF;
  SELECT * INTO e FROM gis.editions WHERE id=j.edition_id;
  SELECT * INTO q FROM gis.gee_mock_requests WHERE job_id=j.id;
  SELECT * INTO c FROM gis.gee_mock_cases WHERE id=q.case_id;
  IF q.id IS NULL OR q.edition_id<>e.id OR q.dataset_id<>e.dataset_id OR e.manifest IS DISTINCT FROM gis.gee_mock_manifest(c.id)
   OR e.input_hash<>gis.manifest_hash(e.manifest) OR e.input_revision<>1 OR j.input_hash<>e.input_hash OR j.input_revision<>1
   OR j.validator_version<>'gee-contract-mock-v1' OR e.state NOT IN ('draft','validating') OR e.validated_result_id IS NOT NULL
   OR EXISTS(SELECT 1 FROM gis.datasets WHERE active_edition_id=e.id) THEN RAISE EXCEPTION 'GIS_GEE_MOCK_CATALOG_INVARIANT'; END IF;
  SELECT * INTO candidate FROM gis.gee_candidates WHERE job_id=j.id;
  IF j.state='succeeded' THEN
   SELECT * INTO a FROM gis.attempts WHERE job_id=j.id AND attempt_no=j.attempt_count;
   SELECT * INTO r FROM gis.results WHERE job_id=j.id;
   PERFORM gis.validate_gee_mock_report(r.report,e,j);
   IF candidate.result_id IS NULL OR candidate.result_id<>r.id OR candidate.request_id<>q.id OR candidate.edition_id<>e.id
    OR candidate.dataset_id<>e.dataset_id OR candidate.input_hash<>j.input_hash OR candidate.input_revision<>j.input_revision
    OR candidate.semantic_request_sha256 IS DISTINCT FROM c.value->>'request_sha256'
    OR candidate.output_sha256 IS DISTINCT FROM c.value->>'output_sha256' OR candidate.output IS DISTINCT FROM c.value->'output'
    OR candidate.worker_id<>a.worker_id OR candidate.attempt_no<>a.attempt_no OR candidate.lease_token<>a.lease_token
    OR a.state<>'succeeded' OR a.validation_report IS DISTINCT FROM r.report OR r.provider<>'gee_contract_mock'
    OR r.report->'valid' IS DISTINCT FROM 'true'::jsonb THEN RAISE EXCEPTION 'GIS_GEE_MOCK_CANDIDATE_INVARIANT'; END IF;
  ELSIF candidate.result_id IS NOT NULL THEN RAISE EXCEPTION 'GIS_GEE_MOCK_PREMATURE_CANDIDATE'; END IF;
 END LOOP;
 RETURN NULL;
END $f$;
DO $triggers$ DECLARE t text; BEGIN
 FOREACH t IN ARRAY ARRAY['editions','jobs','attempts','results','gee_mock_requests','gee_candidates'] LOOP
  EXECUTE format('CREATE CONSTRAINT TRIGGER gee_mock_integrity AFTER INSERT OR UPDATE ON gis.%I DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION gis.check_gee_mock_catalog()',t);
 END LOOP;
END $triggers$;

-- The current shared queue implementation follows; only the new protocol arms
-- are added. Lock ordering, one-running-job limit, lease/backoff and retries stay.

CREATE OR REPLACE FUNCTION gis.queue_protocol_kind(p_action text,p_payload jsonb,p_protocol text) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE j gis.jobs%ROWTYPE; e gis.editions%ROWTYPE; candidate record;
 worker uuid; token uuid; jid uuid; eid uuid; rid uuid; v_now timestamptz;
 progress_value integer; report_value jsonb; code text; next_state text; n integer:=0;
 p_native boolean:=p_protocol<>'v1'; u gis.ldd_uploads%ROWTYPE; ldd_dataset gis.datasets%ROWTYPE; processing_request gis.processing_requests%ROWTYPE; geo gis.geotiff_uploads%ROWTYPE; geo_dataset gis.datasets%ROWTYPE;
BEGIN
 PERFORM gis.assert_environment();
 IF p_protocol NOT IN ('v1','v2','ldd','gee_offline','geotiff','gee_contract_mock') OR p_protocol IS NULL THEN RAISE EXCEPTION 'GIS_WORKER_PROTOCOL_MISMATCH'; END IF;
 IF p_action='claim' THEN
   PERFORM gis.keys(p_payload,ARRAY['worker_id']);
   worker:=(p_payload->>'worker_id')::uuid;
   IF worker IS NULL THEN RAISE EXCEPTION 'GIS_WORKER_REQUIRED'; END IF;
   IF NOT pg_try_advisory_xact_lock(hashtextextended('gis-t1-single-claim',0)) THEN
     RETURN CASE WHEN p_native THEN jsonb_build_object('job',NULL) ELSE NULL END; END IF;
   IF EXISTS(SELECT 1 FROM gis.jobs WHERE state='running') THEN
     RETURN CASE WHEN p_native THEN jsonb_build_object('job',NULL) ELSE NULL END; END IF;
   FOR candidate IN SELECT q.id,q.edition_id FROM gis.jobs q JOIN gis.editions d ON d.id=q.edition_id
      WHERE q.state='queued' AND q.attempt_count<3 AND q.available_at<=clock_timestamp()
        AND q.kind NOT IN ('prepare_ldd_edition','prepare_geotiff_edition') AND gis.edition_protocol(d.id)=p_protocol
      ORDER BY q.available_at,q.created_at,q.id LIMIT 20 LOOP
     SELECT * INTO e FROM gis.editions WHERE id=candidate.edition_id FOR UPDATE SKIP LOCKED;
     IF NOT FOUND THEN CONTINUE; END IF;
     SELECT * INTO j FROM gis.jobs WHERE id=candidate.id FOR UPDATE SKIP LOCKED;
     IF NOT FOUND THEN CONTINUE; END IF;
     v_now:=clock_timestamp();
     IF j.state<>'queued' OR j.attempt_count>=3 OR j.available_at>v_now
       OR e.state<>'validating' OR gis.edition_protocol(e.id) IS DISTINCT FROM p_protocol THEN CONTINUE; END IF;
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
     IF p_protocol='gee_contract_mock' THEN
       report_value:=report_value||gis.gee_mock_claim_packet(j.id);
     END IF;
     IF p_protocol='gee_offline' THEN
       SELECT * INTO processing_request FROM gis.processing_requests WHERE edition_id=e.id;
       report_value:=report_value||jsonb_build_object('processing_id',processing_request.id);
     END IF;
     IF p_native THEN
       INSERT INTO gis.audit(operation,dataset_id,edition_id,job_id,detail)
         VALUES(CASE WHEN p_protocol='gee_contract_mock' THEN 'gee_mock.claim' WHEN p_protocol='geotiff' THEN 'geotiff.claim' WHEN p_protocol='gee_offline' THEN 'processing.claim' WHEN p_protocol='ldd' THEN 'ldd.claim' ELSE 'worker_v2.claim' END,e.dataset_id,e.id,j.id,jsonb_build_object('worker_id',worker,'attempt',j.attempt_count));
       RETURN jsonb_build_object('job',report_value||jsonb_build_object('id',j.id,'dataset_id',e.dataset_id,
         'kind',j.kind,'attempt_number',j.attempt_count));
     END IF;
     RETURN report_value;
   END LOOP;
   RETURN CASE WHEN p_native THEN jsonb_build_object('job',NULL) ELSE NULL END;
 ELSIF p_action='recover' THEN
   PERFORM gis.keys(p_payload,ARRAY[]::text[]);
   FOR candidate IN SELECT q.id,q.edition_id FROM gis.jobs q JOIN gis.editions d ON d.id=q.edition_id
     WHERE q.state='running' AND q.lease_until<=clock_timestamp()
       AND q.kind NOT IN ('prepare_ldd_edition','prepare_geotiff_edition') AND gis.edition_protocol(d.id)=p_protocol
     ORDER BY q.lease_until,q.id LIMIT 20 LOOP
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
       VALUES(CASE WHEN p_protocol='gee_contract_mock' THEN 'gee_mock.recover' WHEN p_protocol='geotiff' THEN 'geotiff.recover' WHEN p_protocol='gee_offline' THEN 'processing.recover' WHEN p_protocol='ldd' THEN 'ldd.recover' WHEN p_native THEN 'worker_v2.recover' ELSE 'worker.recover' END,e.dataset_id,e.id,j.id,
         jsonb_build_object('attempt',j.attempt_count,'terminal',j.attempt_count=3));
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
     IF p_protocol='gee_contract_mock' THEN PERFORM gis.validate_gee_mock_report(report_value,e,j);
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
       VALUES(j.id,e.id,j.input_revision,j.input_hash,j.validator_version,j.attempt_count,token,true,report_value,CASE WHEN p_protocol='gee_contract_mock' THEN 'gee_contract_mock' WHEN p_protocol='geotiff' THEN 'local_geotiff' WHEN p_protocol='gee_offline' THEN 'offline_processing' WHEN p_protocol='ldd' THEN 'local_ldd' ELSE 'synthetic' END) RETURNING id INTO rid;
     IF p_protocol IN ('gee_offline','geotiff','gee_contract_mock') THEN
       UPDATE gis.editions SET state='draft',validated_result_id=NULL WHERE id=e.id;
     ELSE
       UPDATE gis.editions SET state='validated',validated_result_id=rid WHERE id=e.id;
     END IF;
     IF p_protocol='gee_contract_mock' THEN PERFORM gis.gee_mock_record_candidate(j.id,rid,worker); END IF;
     UPDATE gis.jobs SET state='succeeded',worker_id=NULL,lease_token=NULL,lease_until=NULL,progress=100,finished_at=v_now WHERE id=j.id;
     UPDATE gis.attempts SET state='succeeded',progress=100,finished_at=v_now WHERE job_id=j.id AND attempt_no=j.attempt_count AND lease_token=token;
     INSERT INTO gis.audit(operation,dataset_id,edition_id,job_id,detail)
       VALUES(CASE WHEN p_protocol='gee_contract_mock' THEN 'gee_mock.complete' WHEN p_protocol='geotiff' THEN 'geotiff.complete' WHEN p_protocol='gee_offline' THEN 'processing.complete' WHEN p_protocol='ldd' THEN 'ldd.complete' WHEN p_native THEN 'worker_v2.complete' ELSE 'worker.complete' END,e.dataset_id,e.id,j.id,
         jsonb_build_object('result_id',rid,'attempt',j.attempt_count));
     RETURN jsonb_build_object('job_id',j.id,'state','succeeded','result_id',rid);
   END IF;
   IF p_action='complete' THEN code:='invalid_data';
   ELSE code:=p_payload->>'error_code'; END IF;
   IF code IS NULL OR code NOT IN ('invalid_data','transient') THEN RAISE EXCEPTION 'GIS_INVALID_FAILURE'; END IF;
   IF p_native AND p_action='fail' AND (code<>'transient' OR report_value->>'error_code' NOT IN (
     'NATIVE_TIMEOUT','NATIVE_MEMORY_LIMIT','NATIVE_PROCESS_FAILED','TRANSIENT_SYNTHETIC','WORKER_SHUTDOWN','NATIVE_OUTPUT_LIMIT')) THEN
     RAISE EXCEPTION 'GIS_INVALID_FAILURE'; END IF;
   next_state:=CASE WHEN code='transient' AND j.attempt_count<3 THEN 'queued' ELSE 'failed' END;
   UPDATE gis.attempts SET state='failed',error_code=code,finished_at=v_now
     WHERE job_id=j.id AND attempt_no=j.attempt_count AND lease_token=token;
   UPDATE gis.jobs SET state=next_state,worker_id=NULL,lease_token=NULL,lease_until=NULL,
     error_code=CASE WHEN next_state='failed' THEN code ELSE NULL END,progress=0,
     available_at=v_now+make_interval(secs=>CASE j.attempt_count WHEN 1 THEN 5 ELSE 20 END+floor(random()*3)::int),
     finished_at=CASE WHEN next_state='failed' THEN v_now ELSE NULL END WHERE id=j.id;
   IF next_state='failed' THEN UPDATE gis.editions SET state='draft' WHERE id=e.id; END IF;
   INSERT INTO gis.audit(operation,dataset_id,edition_id,job_id,detail)
     VALUES(CASE WHEN p_protocol='gee_contract_mock' THEN 'gee_mock.fail' WHEN p_protocol='geotiff' THEN 'geotiff.fail' WHEN p_protocol='gee_offline' THEN 'processing.fail' WHEN p_protocol='ldd' THEN 'ldd.fail' WHEN p_native THEN 'worker_v2.fail' ELSE 'worker.fail' END,e.dataset_id,e.id,j.id,
       jsonb_build_object('attempt',j.attempt_count,'error_code',code,'state',next_state));
   RETURN CASE WHEN p_native THEN jsonb_build_object('job_id',j.id,'state',next_state,'error_code',code)
     ELSE jsonb_build_object('job_id',j.id,'state',next_state) END;
 END IF;
 RAISE EXCEPTION 'GIS_UNKNOWN_WORKER_ACTION';
END $f$;


DO $acl$ DECLARE f record; BEGIN
 FOR f IN SELECT p.oid::regprocedure::text AS signature FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
 WHERE (n.nspname='gis' AND (p.proname LIKE '%gee_mock%' OR p.proname LIKE 'a62_previous_%'
   OR p.proname IN ('manifest_hash','edition_protocol','eligible','queue_protocol_kind')))
 OR (n.nspname='public' AND p.proname LIKE 'gis_gee_mock_%') LOOP
  EXECUTE format('REVOKE ALL ON FUNCTION %s FROM PUBLIC,anon,authenticated,service_role,gis_worker,gis_native_worker,gis_gee_mock_worker',f.signature);
 END LOOP;
END $acl$;
GRANT EXECUTE ON FUNCTION public.gis_gee_mock_worker(text,jsonb),public.gis_gee_mock_readiness() TO gis_gee_mock_worker;
GRANT EXECUTE ON FUNCTION public.gis_gee_mock_command(uuid,uuid,text,jsonb,boolean),public.gis_gee_mock_read(uuid,uuid) TO service_role;
REVOKE CREATE ON SCHEMA public FROM gis_owner;
RESET ROLE;
NOTIFY pgrst,'reload schema';
