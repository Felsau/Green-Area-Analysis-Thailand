-- Genuine HTTPS foundation. Default empty runtime trust, no Live launch.
-- Extends the exact 044/045/046 validators/queue; historical bytes are untouched.
-- All identities/configuration/receipts are private; no publish/cache mutation.
DO $guard$ BEGIN
 IF current_database() NOT IN ('postgres','gis_t1_upgrade') OR current_setting('cluster_name')<>'green-area-gis-t0'
 OR NOT EXISTS(SELECT 1 FROM gis.schema_migrations WHERE version=46 AND sha256='bd4d94a0b993aa7d037f14f6957451052707b4af1cb614d9d45ae42c03cbe23c')
 OR EXISTS(SELECT 1 FROM gis.schema_migrations WHERE version>=47)
 OR NOT EXISTS(SELECT 1 FROM gis.environment WHERE singleton AND NOT activation_enabled
 AND runtime_instance=current_setting('gis.runtime_instance',true) AND baseline_fingerprint=current_setting('gis.baseline_fingerprint',true))
 THEN RAISE EXCEPTION 'GIS_HTTPS_LOCAL_BASELINE_REQUIRED';END IF;
END $guard$;
DO $roles$ DECLARE n text;BEGIN
 FOREACH n IN ARRAY ARRAY['gis_gee_https_worker','gis_gee_https_recorder'] LOOP
  IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname=n) THEN
   IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname=n AND NOT rolsuper AND NOT rolcanlogin AND NOT rolbypassrls
    AND NOT rolcreatedb AND NOT rolcreaterole AND NOT rolreplication AND NOT rolinherit
    AND shobj_description(oid,'pg_authid')='gis-a6-genuine-https-closed-runtime')
    OR EXISTS(SELECT 1 FROM pg_auth_members WHERE member=n::regrole)
    OR EXISTS(SELECT 1 FROM pg_auth_members WHERE roleid=n::regrole AND member NOT IN ('postgres'::regrole,'authenticator'::regrole))
   THEN RAISE EXCEPTION 'GIS_HTTPS_ROLE_COLLISION';END IF;
  ELSE EXECUTE format('CREATE ROLE %I NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOREPLICATION NOINHERIT',n);END IF;
  EXECUTE format('COMMENT ON ROLE %I IS %L',n,'gis-a6-genuine-https-closed-runtime');
  EXECUTE format('GRANT %I TO authenticator WITH INHERIT FALSE, SET TRUE',n);
  EXECUTE format('GRANT USAGE ON SCHEMA public TO %I',n);
  EXECUTE format('REVOKE ALL ON SCHEMA gis FROM %I',n);
 END LOOP;
END $roles$;
GRANT CREATE ON SCHEMA public TO gis_owner;
SET LOCAL ROLE gis_owner;

-- The attested local operator alone may register a reviewed runtime. No rows
-- are installed by this migration; a label/hash/worker RPC cannot approve one.
-- These pins are configuration, not proof of Google origin: the isolated,
-- authenticated recorder is the observation authority. Compromise of that
-- trusted process is outside the worker threat boundary.
CREATE TABLE gis.gee_https_runtimes(
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),recorder_id uuid NOT NULL REFERENCES public.profiles(id),
 image_id text NOT NULL CHECK(image_id ~ '^sha256:[0-9a-f]{64}$'),
 network_policy_sha256 text NOT NULL CHECK(network_policy_sha256 ~ '^[0-9a-f]{64}$'),
 credential_issuer_key_sha256 text NOT NULL CHECK(credential_issuer_key_sha256 ~ '^[0-9a-f]{64}$'),
 approved_by uuid NOT NULL REFERENCES public.profiles(id),
 approved_at timestamptz NOT NULL DEFAULT clock_timestamp(),expires_at timestamptz NOT NULL,
 CHECK(expires_at>approved_at AND expires_at<=approved_at+interval '20 minutes'));


CREATE TABLE gis.gee_https_authorities(
 job_id uuid PRIMARY KEY REFERENCES gis.jobs(id),
 session_id uuid NOT NULL REFERENCES gis.gee_safety_sessions(id),
 worker_id uuid NOT NULL REFERENCES public.profiles(id),
 recorder_id uuid NOT NULL REFERENCES public.profiles(id),
 mode text NOT NULL CHECK(mode='google_https'),
 project_id text NOT NULL CHECK(project_id='green-area-gis-sandbox'),
 project_number text NOT NULL CHECK(project_number='977478562022'),
 google_principal text NOT NULL CHECK(google_principal='gis-gee-smoke-worker@green-area-gis-sandbox.iam.gserviceaccount.com'),
 runtime_id uuid NOT NULL REFERENCES gis.gee_https_runtimes(id),
 principal_id text NOT NULL CHECK(principal_id='103297967369976617173'),
 period jsonb NOT NULL,
 input_revision integer NOT NULL,input_hash text NOT NULL,request_sha256 text NOT NULL,
 geometry_sha256 text NOT NULL,method_sha256 text NOT NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 CHECK(worker_id<>recorder_id));
CREATE TABLE gis.gee_https_receipts(
 request_id uuid PRIMARY KEY REFERENCES gis.gee_safety_requests(id),
 job_id uuid NOT NULL REFERENCES gis.gee_https_authorities(job_id),
 recorder_id uuid NOT NULL REFERENCES public.profiles(id),
 category text NOT NULL CHECK(category IN ('discovery','algorithms','catalog','compute')),
 uri text NOT NULL,method text NOT NULL CHECK(method IN ('GET','POST')),
 peer_ip inet NOT NULL,certificate_sha256 text NOT NULL CHECK(certificate_sha256 ~ '^[0-9a-f]{64}$'),
 tls_version text NOT NULL CHECK(tls_version IN ('TLSv1.2','TLSv1.3')),
 request_sha256 text NOT NULL CHECK(request_sha256 ~ '^[0-9a-f]{64}$'),
 response_sha256 text NOT NULL CHECK(response_sha256 ~ '^[0-9a-f]{64}$'),
 status integer NOT NULL CHECK(status BETWEEN 100 AND 599),
 observation jsonb CHECK(observation IS NULL OR jsonb_typeof(observation)='object' AND octet_length(observation::text)<=8192),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp());
CREATE TABLE gis.gee_https_seals(
 job_id uuid NOT NULL REFERENCES gis.gee_https_authorities(job_id),
 attempt_no integer NOT NULL,lease_token uuid NOT NULL,
 output_sha256 text NOT NULL CHECK(output_sha256 ~ '^[0-9a-f]{64}$'),
 evidence_sha256 text NOT NULL CHECK(evidence_sha256 ~ '^[0-9a-f]{64}$'),
 receipts uuid[] NOT NULL CHECK(cardinality(receipts) BETWEEN 1 AND 32),
 recorder_id uuid NOT NULL REFERENCES public.profiles(id),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY(job_id,attempt_no),
 FOREIGN KEY(job_id,attempt_no,lease_token) REFERENCES gis.attempts(job_id,attempt_no,lease_token));


DO $tables$ DECLARE t text;BEGIN
 FOREACH t IN ARRAY ARRAY['gee_https_runtimes','gee_https_authorities','gee_https_receipts','gee_https_seals'] LOOP
  EXECUTE format('ALTER TABLE gis.%I ENABLE ROW LEVEL SECURITY',t);
  EXECUTE format('ALTER TABLE gis.%I FORCE ROW LEVEL SECURITY',t);
  EXECUTE format('CREATE POLICY owner_access ON gis.%I TO gis_owner USING(true) WITH CHECK(true)',t);
  EXECUTE format('REVOKE ALL ON gis.%I FROM PUBLIC,anon,authenticated,service_role,gis_worker,gis_native_worker,gis_gee_mock_worker,gis_gee_live_worker,gis_gee_safety_worker,gis_gee_transport_recorder,gis_gee_https_worker,gis_gee_https_recorder',t);
  EXECUTE format('CREATE TRIGGER immutable_https BEFORE UPDATE OR DELETE ON gis.%I FOR EACH ROW EXECUTE FUNCTION gis.gee_live_immutable()',t);
 END LOOP;
END $tables$;


CREATE OR REPLACE FUNCTION gis.validate_gee_live_case() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE v jsonb:=NEW.value; r jsonb; p jsonb; s jsonb; y integer; m integer; start_value date; end_value date;
BEGIN
 PERFORM gis.assert_environment();
 PERFORM gis.keys(v,ARRAY['request','method','geometry','request_canonical','geometry_canonical','request_sha256','geometry_sha256']);
 IF NOT v ?& ARRAY['request','method','geometry','request_canonical','geometry_canonical','request_sha256','geometry_sha256']
 OR octet_length(v::text)>16384 THEN RAISE EXCEPTION 'GIS_GEE_LIVE_INPUT_INVALID'; END IF;
 r:=v->'request';p:=r->'project';s:=r->'scope';
 PERFORM gis.keys(r,ARRAY['schema_version','protocol','request_id','input_revision','execution','product','period','scope','project','method_version']);
 PERFORM gis.keys(p,ARRAY['project_id','project_number','principal','readiness']);
 PERFORM gis.keys(s,ARRAY['kind','province','boundary_version','province_geometry_sha256','geometry_sha256','geometry_crs']);
 IF NOT r ?& ARRAY['schema_version','protocol','request_id','input_revision','execution','product','period','scope','project','method_version']
 OR NOT p ?& ARRAY['project_id','project_number','principal','readiness']
 OR NOT s ?& ARRAY['kind','province','boundary_version','province_geometry_sha256','geometry_sha256','geometry_crs']
 OR jsonb_typeof(p->'project_id') IS DISTINCT FROM 'string' OR jsonb_typeof(p->'project_number') IS DISTINCT FROM 'string'
 OR jsonb_typeof(p->'principal') IS DISTINCT FROM 'string' OR jsonb_typeof(r->'request_id') IS DISTINCT FROM 'string'
 OR jsonb_typeof(v->'request_canonical') IS DISTINCT FROM 'string' OR jsonb_typeof(v->'geometry_canonical') IS DISTINCT FROM 'string'
 THEN RAISE EXCEPTION 'GIS_GEE_LIVE_INPUT_INVALID'; END IF;
 PERFORM gis.gee_live_geometry(v->'geometry');
 IF r->'schema_version' IS DISTINCT FROM '2'::jsonb OR r->>'protocol' IS DISTINCT FROM 'gee_live_v2'
 OR (r->>'execution' IS NULL OR r->>'execution' NOT IN ('injected','live')) OR r->'input_revision' IS DISTINCT FROM '1'::jsonb
 OR r->>'product' IS NULL OR r->>'product' NOT IN ('ndvi','lst')
 OR COALESCE(r->>'request_id','') !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
 OR COALESCE(p->>'project_id','') !~ '^[a-z][a-z0-9-]{4,28}[a-z0-9]$'
 OR COALESCE(p->>'project_number','') !~ '^[0-9]{6,30}$'
 OR COALESCE(p->>'principal','') !~ '^[a-z0-9-]+@[a-z][a-z0-9-]+[.]iam[.]gserviceaccount[.]com$'
 OR p->>'principal' NOT LIKE '%@'||(p->>'project_id')||'.iam.gserviceaccount.com'
 OR p->>'readiness' IS DISTINCT FROM (CASE WHEN r->>'execution'='live' THEN 'verified_sandbox' ELSE 'not_verified' END)
 OR s->>'kind' IS NULL OR s->>'kind' NOT IN ('province','sandbox_roi')
 OR s->>'geometry_crs' IS DISTINCT FROM 'EPSG:4326'
 OR COALESCE(s->>'boundary_version','') !~ '^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$'
 OR COALESCE(s->>'province_geometry_sha256','') !~ '^[0-9a-f]{64}$'
 OR COALESCE(v->>'geometry_sha256','') !~ '^[0-9a-f]{64}$'
 OR COALESCE(v->>'request_sha256','') !~ '^[0-9a-f]{64}$'
 OR s->>'geometry_sha256' IS DISTINCT FROM v->>'geometry_sha256'
 OR (s->>'kind'='province' AND s->>'geometry_sha256' IS DISTINCT FROM s->>'province_geometry_sha256')
 OR NOT EXISTS(SELECT 1 FROM public.provinces WHERE name_en=s->>'province')
 OR COALESCE(r->'period'->>'year','') !~ '^[0-9]{4}$' OR COALESCE(r->'period'->>'month','') !~ '^[0-9]{1,2}$'
 THEN RAISE EXCEPTION 'GIS_GEE_LIVE_INPUT_INVALID'; END IF;
 y:=(r->'period'->>'year')::integer;m:=(r->'period'->>'month')::integer;
 IF y<(CASE WHEN r->>'product'='ndvi' THEN 2017 ELSE 2013 END) OR y>2200 OR m NOT BETWEEN 0 AND 12 THEN RAISE EXCEPTION 'GIS_GEE_LIVE_PERIOD_INVALID'; END IF;
 start_value:=make_date(y,CASE WHEN m=0 THEN 1 ELSE m END,1);
 end_value:=CASE WHEN m=0 THEN make_date(y+1,1,1) ELSE (start_value+interval '1 month')::date END;
 IF r->'period' IS DISTINCT FROM jsonb_build_object('year',y,'month',m,'start',start_value,'end_exclusive',end_value)
 OR v->'method' IS DISTINCT FROM gis.gee_live_method(r->>'product',m)
 OR r->>'method_version' IS DISTINCT FROM v->'method'->>'version'
 OR (v->>'request_canonical')::jsonb IS DISTINCT FROM jsonb_build_object('request',r-'request_id','method',v->'method')
 OR (v->>'geometry_canonical')::jsonb IS DISTINCT FROM v->'geometry'
 OR v->>'request_canonical' IS DISTINCT FROM gis.gee_live_canonical(jsonb_build_object('request',r-'request_id','method',v->'method'))
 OR v->>'geometry_canonical' IS DISTINCT FROM gis.gee_live_canonical(v->'geometry')
 OR v->>'request_sha256' IS DISTINCT FROM encode(sha256(convert_to(v->>'request_canonical','UTF8')),'hex')
 OR v->>'geometry_sha256' IS DISTINCT FROM encode(sha256(convert_to(v->>'geometry_canonical','UTF8')),'hex')
 THEN RAISE EXCEPTION 'GIS_GEE_LIVE_INPUT_HASH_MISMATCH'; END IF;
 IF r->>'execution'='live' THEN
  IF p IS DISTINCT FROM '{"project_id":"green-area-gis-sandbox","project_number":"977478562022","principal":"gis-gee-smoke-worker@green-area-gis-sandbox.iam.gserviceaccount.com","readiness":"verified_sandbox"}'::jsonb
  OR s->>'kind'<>'sandbox_roi' OR m=0 OR end_value>(clock_timestamp() AT TIME ZONE 'UTC')::date
  OR v->'geometry'->>'type'<>'Polygon' OR jsonb_array_length(v->'geometry'->'coordinates')<>1
  OR EXISTS(SELECT 1 FROM jsonb_array_elements(v->'geometry'->'coordinates'->0) point_value
    WHERE (point_value->>0)::numeric NOT BETWEEN 97 AND 106 OR (point_value->>1)::numeric NOT BETWEEN 5 AND 21)
  OR (SELECT max((point_value->>0)::numeric)-min((point_value->>0)::numeric)>.05 OR max((point_value->>1)::numeric)-min((point_value->>1)::numeric)>.05
      FROM jsonb_array_elements(v->'geometry'->'coordinates'->0) point_value)
  THEN RAISE EXCEPTION 'GIS_HTTPS_SMOKE_INPUT_REJECTED';END IF;
 END IF;
 RETURN NEW;
END $f$;

CREATE OR REPLACE FUNCTION gis.safety_manifest(p_input uuid,p_session uuid) RETURNS jsonb
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
 SELECT jsonb_build_object('schema_version',8,
 'provider',CASE WHEN i.value->'request'->>'execution'='live' THEN 'gee_genuine_https' ELSE 'gee_safety_rehearsal' END,
 'execution',CASE WHEN i.value->'request'->>'execution'='live' THEN 'live' ELSE 'rehearsal' END,
 'input_id',i.id,'session_id',s.id,'policy_sha256',s.policy_sha256,'semantic_request_sha256',i.value->>'request_sha256',
 'geometry_sha256',i.value->>'geometry_sha256','method_version',i.value->'request'->>'method_version')
 FROM gis.gee_live_inputs i CROSS JOIN gis.gee_safety_sessions s WHERE i.id=p_input AND s.id=p_session
$f$;
ALTER FUNCTION gis.edition_protocol(uuid) RENAME TO https_previous_edition_protocol;
CREATE FUNCTION gis.edition_protocol(p_edition uuid) RETURNS text LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
 SELECT CASE WHEN e.manifest->>'provider'='gee_genuine_https' AND EXISTS(SELECT 1 FROM gis.gee_live_requests r WHERE r.edition_id=e.id)
 THEN 'gee_genuine_https' ELSE gis.https_previous_edition_protocol(p_edition) END FROM gis.editions e WHERE e.id=p_edition
$f$;


CREATE FUNCTION gis.https_assert_authority(p_job uuid,p_recorder uuid DEFAULT NULL,p_active boolean DEFAULT true) RETURNS gis.gee_https_authorities
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE a gis.gee_https_authorities%ROWTYPE;j gis.jobs%ROWTYPE;r gis.gee_https_runtimes%ROWTYPE;v jsonb;s gis.gee_safety_sessions%ROWTYPE;
BEGIN
 PERFORM gis.assert_environment();
 SELECT * INTO a FROM gis.gee_https_authorities WHERE job_id=p_job;
 SELECT * INTO j FROM gis.jobs WHERE id=p_job;
 SELECT * INTO r FROM gis.gee_https_runtimes WHERE id=a.runtime_id;
 SELECT x.value INTO v FROM gis.gee_live_inputs x JOIN gis.gee_live_requests q ON q.input_id=x.id WHERE q.job_id=p_job;
 SELECT x.* INTO s FROM gis.gee_safety_sessions x JOIN gis.gee_safety_jobs b ON b.session_id=x.id WHERE b.job_id=p_job;
 IF a.job_id IS NULL OR r.id IS NULL OR (p_active AND r.expires_at<=clock_timestamp()) OR r.approved_at>clock_timestamp()
 OR s.id IS DISTINCT FROM a.session_id OR s.bound_worker IS DISTINCT FROM a.worker_id
 OR r.recorder_id IS DISTINCT FROM a.recorder_id OR (p_recorder IS NOT NULL AND p_recorder IS DISTINCT FROM a.recorder_id)
 OR j.input_revision IS DISTINCT FROM a.input_revision OR j.input_hash IS DISTINCT FROM a.input_hash
 OR a.request_sha256 IS DISTINCT FROM v->>'request_sha256' OR a.geometry_sha256 IS DISTINCT FROM v->>'geometry_sha256'
 OR a.method_sha256 IS DISTINCT FROM encode(sha256(convert_to(gis.gee_live_canonical(v->'method'),'UTF8')),'hex')
 OR a.period IS DISTINCT FROM v->'request'->'period' OR v->'request'->>'execution' IS DISTINCT FROM 'live'
 OR v->'request'->'project' IS DISTINCT FROM jsonb_build_object('project_id',a.project_id,'project_number',a.project_number,'principal',a.google_principal,'readiness','verified_sandbox')
 OR EXISTS(SELECT 1 FROM gis.gee_transport_authorities WHERE job_id=p_job)
 THEN RAISE EXCEPTION 'GIS_HTTPS_APPROVAL_REQUIRED';END IF;
 RETURN a;
END $f$;
CREATE FUNCTION gis.https_authorize(p_job uuid,p_recorder uuid,p_runtime uuid) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE j gis.jobs%ROWTYPE;s gis.gee_safety_sessions%ROWTYPE;r gis.gee_https_runtimes%ROWTYPE;v jsonb;
BEGIN
 PERFORM gis.assert_environment();
 PERFORM 1 FROM gis.editions e JOIN gis.jobs q ON q.edition_id=e.id WHERE q.id=p_job FOR UPDATE OF e;
 SELECT * INTO j FROM gis.jobs WHERE id=p_job FOR UPDATE;
 SELECT x.* INTO s FROM gis.gee_safety_sessions x JOIN gis.gee_safety_jobs b ON b.session_id=x.id WHERE b.job_id=p_job FOR UPDATE OF x;
 SELECT * INTO r FROM gis.gee_https_runtimes WHERE id=p_runtime;
 SELECT i.value INTO v FROM gis.gee_live_inputs i JOIN gis.gee_live_requests q ON q.input_id=i.id WHERE q.job_id=p_job;
 IF j.state IS DISTINCT FROM 'queued' OR j.kind IS DISTINCT FROM 'process_gee_safety_edition' OR j.attempt_count<>0
 OR s.state IS DISTINCT FROM 'open' OR s.ends_at<=clock_timestamp() OR r.recorder_id IS DISTINCT FROM p_recorder
 OR r.expires_at<=clock_timestamp() OR s.bound_worker=p_recorder OR v->'request'->>'execution' IS DISTINCT FROM 'live'
 THEN RAISE EXCEPTION 'GIS_HTTPS_APPROVAL_REQUIRED';END IF;
 INSERT INTO gis.gee_https_authorities(job_id,session_id,worker_id,recorder_id,runtime_id,principal_id,period,mode,project_id,project_number,google_principal,
 input_revision,input_hash,request_sha256,geometry_sha256,method_sha256)
 VALUES(j.id,s.id,s.bound_worker,p_recorder,r.id,'103297967369976617173',v->'request'->'period','google_https','green-area-gis-sandbox','977478562022',
 'gis-gee-smoke-worker@green-area-gis-sandbox.iam.gserviceaccount.com',j.input_revision,j.input_hash,v->>'request_sha256',v->>'geometry_sha256',
 encode(sha256(convert_to(gis.gee_live_canonical(v->'method'),'UTF8')),'hex'));
 PERFORM gis.https_assert_authority(j.id,p_recorder);
 INSERT INTO gis.audit(operation,job_id,detail) VALUES('https.approve',j.id,jsonb_build_object('runtime_id',r.id,'publishable',false));
END $f$;


CREATE FUNCTION gis.validate_https_report(p_report jsonb,p_edition gis.editions,p_job gis.jobs) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE v jsonb; c jsonb; e jsonb; s jsonb; raw jsonb; status text; expected text; field text;
 n integer; d integer; val numeric; result numeric; seen integer; scene jsonb;
BEGIN
 SELECT x.value INTO v FROM gis.gee_live_inputs x JOIN gis.gee_live_requests q ON q.input_id=x.id
 WHERE q.edition_id=p_edition.id AND q.job_id=p_job.id AND q.dataset_id=p_edition.dataset_id;
 IF v IS NULL OR p_job.kind<>'process_gee_live_edition' OR p_job.validator_version<>'gee-live-v2'
 OR p_edition.input_revision<>1 OR p_job.input_revision<>1 OR p_job.input_hash<>p_edition.input_hash
 OR p_edition.input_hash<>gis.manifest_hash(p_edition.manifest) THEN RAISE EXCEPTION 'GIS_GEE_LIVE_INPUT_MISMATCH'; END IF;
 PERFORM gis.keys(p_report,ARRAY['schema_version','protocol','input_hash','input_revision','semantic_request_sha256','valid','error_code','output','output_canonical','evidence_canonical']);
 IF NOT p_report ?& ARRAY['schema_version','protocol','input_hash','input_revision','semantic_request_sha256','valid','error_code','output','output_canonical','evidence_canonical']
 OR octet_length(p_report::text)>16384 OR p_report->'schema_version' IS DISTINCT FROM '2'::jsonb
 OR p_report->>'protocol' IS DISTINCT FROM 'gee_live_v2' OR p_report->>'input_hash' IS DISTINCT FROM p_job.input_hash
 OR p_report->'input_revision' IS DISTINCT FROM to_jsonb(p_job.input_revision)
 OR p_report->>'semantic_request_sha256' IS DISTINCT FROM v->>'request_sha256'
 THEN RAISE EXCEPTION 'GIS_GEE_LIVE_REPORT_INVALID'; END IF;
 IF p_report->>'error_code' IN ('NATIVE_TIMEOUT','NATIVE_MEMORY_LIMIT','NATIVE_PROCESS_FAILED','WORKER_SHUTDOWN','NATIVE_OUTPUT_LIMIT') THEN
  IF p_report->'valid' IS DISTINCT FROM 'false'::jsonb OR p_report->'output' IS DISTINCT FROM 'null'::jsonb
  OR p_report->'output_canonical' IS DISTINCT FROM 'null'::jsonb OR p_report->'evidence_canonical' IS DISTINCT FROM 'null'::jsonb
  THEN RAISE EXCEPTION 'GIS_GEE_LIVE_REPORT_INVALID'; END IF;
  RETURN;
 END IF;
 c:=p_report->'output'->'content';e:=c->'evidence';s:=c->'statistics';raw:=e->'raw_statistics';
 PERFORM gis.keys(p_report->'output',ARRAY['content','output_sha256']);
 PERFORM gis.keys(c,ARRAY['schema_version','protocol','request','request_sha256','geometry_sha256','execution','synthetic','publishable','endpoint_parity','as_of','status','evidence','evidence_sha256','statistics']);
 PERFORM gis.keys(e,ARRAY['request_sha256','geometry_sha256','project','method','period','scenes','scene_count','complete','valid_pixels','raw_statistics','units','geometry_crs','reduction_crs','nominal_scale_m','effective_scale_m','nodata']);
 IF c->'schema_version' IS DISTINCT FROM '2'::jsonb OR c->>'protocol' IS DISTINCT FROM 'gee_live_v2'
 OR c->'request' IS DISTINCT FROM v->'request' OR c->>'request_sha256' IS DISTINCT FROM v->>'request_sha256'
 OR c->>'geometry_sha256' IS DISTINCT FROM v->>'geometry_sha256'
 OR c->>'execution' IS DISTINCT FROM 'live' OR c->'synthetic' IS DISTINCT FROM 'false'::jsonb
 OR c->'publishable' IS DISTINCT FROM 'false'::jsonb OR c->>'endpoint_parity' IS DISTINCT FROM 'summary_only'
 OR e->>'request_sha256' IS DISTINCT FROM v->>'request_sha256' OR e->>'geometry_sha256' IS DISTINCT FROM v->>'geometry_sha256'
 OR e->'project' IS DISTINCT FROM v->'request'->'project' OR e->'method' IS DISTINCT FROM v->'method'
 OR e->'period' IS DISTINCT FROM v->'request'->'period' OR e->>'units' IS DISTINCT FROM v->'method'->>'units'
 OR e->>'geometry_crs' IS DISTINCT FROM 'EPSG:4326' OR e->'nominal_scale_m' IS DISTINCT FROM '500'::jsonb
 OR e->>'nodata' IS DISTINCT FROM 'null' OR e->'reduction_crs' IS DISTINCT FROM 'null'::jsonb
 OR e->'effective_scale_m' IS DISTINCT FROM 'null'::jsonb
 OR jsonb_typeof(e->'scenes') IS DISTINCT FROM 'array' OR jsonb_array_length(e->'scenes')>32
 OR jsonb_typeof(e->'scene_count') IS DISTINCT FROM 'number' OR COALESCE(e->>'scene_count','') !~ '^[0-9]{1,2}$'
 OR jsonb_typeof(e->'complete') IS DISTINCT FROM 'boolean'
 OR COALESCE(c->>'as_of','') !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
 OR (c->>'as_of')::date>(clock_timestamp() AT TIME ZONE 'UTC')::date
 OR (p_report->>'output_canonical')::jsonb IS DISTINCT FROM c OR (p_report->>'evidence_canonical')::jsonb IS DISTINCT FROM e
 OR p_report->>'output_canonical' IS DISTINCT FROM gis.gee_live_canonical(c)
 OR p_report->>'evidence_canonical' IS DISTINCT FROM gis.gee_live_canonical(e)
 OR p_report->'output'->>'output_sha256' IS DISTINCT FROM encode(sha256(convert_to(p_report->>'output_canonical','UTF8')),'hex')
 OR c->>'evidence_sha256' IS DISTINCT FROM encode(sha256(convert_to(p_report->>'evidence_canonical','UTF8')),'hex')
 THEN RAISE EXCEPTION 'GIS_GEE_LIVE_EVIDENCE_INVALID'; END IF;
 n:=(e->>'scene_count')::integer;
 IF n<>jsonb_array_length(e->'scenes') OR n<>(SELECT count(DISTINCT x->>'image_id') FROM jsonb_array_elements(e->'scenes') x)
 THEN RAISE EXCEPTION 'GIS_GEE_LIVE_SCENES_INVALID'; END IF;
 FOR scene IN SELECT * FROM jsonb_array_elements(e->'scenes') LOOP
  PERFORM gis.keys(scene,ARRAY['collection','image_id','acquired']);
  IF NOT COALESCE(v->'method'->'collections' ? (scene->>'collection'),false) OR scene->>'collection' LIKE '%CLOUD_SCORE_PLUS%'
  OR COALESCE(scene->>'image_id','') !~ '^[A-Za-z0-9_./-]{1,240}$' OR position('..' in scene->>'image_id')>0
  OR left(scene->>'image_id',length(scene->>'collection')+1) IS DISTINCT FROM (scene->>'collection')||'/'
  OR COALESCE(scene->>'acquired','') !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
  OR (scene->>'acquired')::date<(v->'request'->'period'->>'start')::date
  OR (scene->>'acquired')::date>=(v->'request'->'period'->>'end_exclusive')::date
  THEN RAISE EXCEPTION 'GIS_GEE_LIVE_SCENES_INVALID'; END IF;
 END LOOP;
 IF e->'valid_pixels' IS DISTINCT FROM 'null'::jsonb AND (jsonb_typeof(e->'valid_pixels') IS DISTINCT FROM 'number'
 OR COALESCE(e->>'valid_pixels','') !~ '^[0-9]{1,13}$' OR (e->>'valid_pixels')::numeric>1e12)
 THEN RAISE EXCEPTION 'GIS_GEE_LIVE_PIXELS_INVALID'; END IF;
 IF NOT e ? 'valid_pixels' THEN RAISE EXCEPTION 'GIS_GEE_LIVE_PIXELS_INVALID'; END IF;
 PERFORM gis.keys(raw,ARRAY['mean','min','max']);PERFORM gis.keys(s,ARRAY['mean','min','max']);
 IF NOT raw ?& ARRAY['mean','min','max'] OR NOT s ?& ARRAY['mean','min','max'] THEN RAISE EXCEPTION 'GIS_GEE_LIVE_STATS_INVALID'; END IF;
 IF (n=0 AND e->'valid_pixels' NOT IN ('0'::jsonb,'null'::jsonb))
 OR ((n=0 OR e->'valid_pixels'='0'::jsonb) AND raw IS DISTINCT FROM '{"mean":null,"min":null,"max":null}'::jsonb)
 THEN RAISE EXCEPTION 'GIS_GEE_LIVE_NODATA_CONTRADICTION'; END IF;
 FOREACH field IN ARRAY ARRAY['mean','min','max'] LOOP
  IF raw->field IS DISTINCT FROM 'null'::jsonb THEN
   IF jsonb_typeof(raw->field) IS DISTINCT FROM 'number' THEN RAISE EXCEPTION 'GIS_GEE_LIVE_STATS_INVALID'; END IF;
   val:=(raw->>field)::numeric;
   IF abs(val)>1e308 OR to_jsonb(val::double precision) IS DISTINCT FROM raw->field THEN RAISE EXCEPTION 'GIS_GEE_LIVE_NUMERIC_INVALID'; END IF;
   IF v->'request'->>'product'='ndvi' AND (val>1 OR val<(CASE WHEN v->'method'->'mask_negative_ndvi'='true'::jsonb THEN 0 ELSE -1 END)) THEN RAISE EXCEPTION 'GIS_GEE_LIVE_STATS_INVALID'; END IF;
  END IF;
 END LOOP;
 IF (raw->>'min')::numeric>(raw->>'mean')::numeric OR (raw->>'mean')::numeric>(raw->>'max')::numeric
 OR (raw->>'min')::numeric>(raw->>'max')::numeric THEN RAISE EXCEPTION 'GIS_GEE_LIVE_STATS_INVALID'; END IF;
 expected:=CASE WHEN e->'complete'<>'true'::jsonb OR (c->>'as_of')::date<(v->'request'->'period'->>'end_exclusive')::date OR e->'valid_pixels'='null'::jsonb THEN 'incomplete'
 WHEN n=0 OR e->'valid_pixels'='0'::jsonb THEN 'no_data'
 WHEN raw->'mean'='null'::jsonb THEN 'incomplete'
 WHEN v->'request'->'period'->'month'='0'::jsonb AND (raw->'min'='null'::jsonb OR raw->'max'='null'::jsonb) THEN 'incomplete' ELSE 'candidate' END;
 status:=c->>'status';
 IF status IS DISTINCT FROM expected OR p_report->'valid' IS DISTINCT FROM to_jsonb(expected='candidate')
 OR p_report->>'error_code' IS DISTINCT FROM (CASE WHEN expected='candidate' THEN NULL ELSE 'invalid_data' END)
 THEN RAISE EXCEPTION 'GIS_GEE_LIVE_STATUS_INVALID'; END IF;
 IF expected<>'candidate' AND s IS DISTINCT FROM '{"mean":null,"min":null,"max":null}'::jsonb THEN RAISE EXCEPTION 'GIS_GEE_LIVE_STATS_INVALID'; END IF;
 IF expected='candidate' THEN
  d:=CASE WHEN v->'request'->>'product'='ndvi' THEN 4 ELSE 2 END;
  FOREACH field IN ARRAY ARRAY['mean','min','max'] LOOP
   IF field<>'mean' AND v->'request'->'period'->'month'<>'0'::jsonb THEN
    IF s->field IS DISTINCT FROM 'null'::jsonb THEN RAISE EXCEPTION 'GIS_GEE_LIVE_STATS_INVALID'; END IF;
   ELSE
    IF jsonb_typeof(s->field) IS DISTINCT FROM 'number' THEN RAISE EXCEPTION 'GIS_GEE_LIVE_STATS_INVALID'; END IF;
    result:=(s->>field)::numeric;val:=(raw->>field)::numeric;
    IF abs(result)>1e308 OR to_jsonb(result::double precision) IS DISTINCT FROM s->field THEN RAISE EXCEPTION 'GIS_GEE_LIVE_NUMERIC_INVALID'; END IF;
    -- Independent precision/error bounds; Python additionally enforces exact
    -- binary-float round(), including its documented tie behavior.
    IF result<>round(result,d) OR abs(result-val)>power(10::numeric,-d)/2+1e-12 THEN RAISE EXCEPTION 'GIS_GEE_LIVE_STATS_INVALID'; END IF;
   END IF;
  END LOOP;
 END IF;
END $f$;

CREATE FUNCTION gis.validate_https_safety_report(p_report jsonb,p_edition gis.editions,p_job gis.jobs) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE s gis.gee_safety_sessions%ROWTYPE;v gis.jobs%ROWTYPE:=p_job;base jsonb;ids uuid[];n integer;
BEGIN
 PERFORM gis.https_assert_authority(p_job.id,NULL,p_report->'base'->'output' IS DISTINCT FROM 'null'::jsonb);
 PERFORM gis.keys(p_report,ARRAY['schema_version','protocol','execution','live_enabled','session_id','policy_sha256','valid','error_code','base','receipts','failure_kind']);
 SELECT x.* INTO s FROM gis.gee_safety_sessions x JOIN gis.gee_safety_jobs b ON b.session_id=x.id WHERE b.job_id=p_job.id;
 base:=p_report->'base';
 IF NOT p_report ? 'failure_kind' OR (p_report->'failure_kind' IS DISTINCT FROM 'null'::jsonb AND p_report->>'failure_kind' NOT IN ('request_timeout','job_timeout','lease_expired','budget_exhausted','session_stopped','accounting_uncertain','transient')) OR (p_report->'valid'='true'::jsonb AND p_report->'failure_kind' IS DISTINCT FROM 'null'::jsonb) THEN RAISE EXCEPTION 'GIS_SAFETY_REPORT_INVALID'; END IF;
 IF s.id IS NULL OR p_report->'schema_version' IS DISTINCT FROM '4'::jsonb OR p_report->>'protocol' IS DISTINCT FROM 'gee_genuine_https'
 OR p_report->>'execution' IS DISTINCT FROM 'live' OR p_report->'live_enabled' IS DISTINCT FROM 'false'::jsonb
 OR p_report->>'session_id' IS DISTINCT FROM s.id::text OR p_report->>'policy_sha256' IS DISTINCT FROM s.policy_sha256
 OR p_report->'valid' IS DISTINCT FROM base->'valid' OR p_report->'error_code' IS DISTINCT FROM base->'error_code'
 OR jsonb_typeof(p_report->'receipts') IS DISTINCT FROM 'array' OR octet_length(p_report::text)>16384
 THEN RAISE EXCEPTION 'GIS_SAFETY_REPORT_INVALID'; END IF;
 v.kind:='process_gee_live_edition';v.validator_version:='gee-live-v2';
 PERFORM gis.validate_https_report(base,p_edition,v);
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

ALTER FUNCTION gis.validate_safety_report(jsonb,gis.editions,gis.jobs) RENAME TO https_previous_validate_safety_report;
CREATE FUNCTION gis.validate_safety_report(p_report jsonb,p_edition gis.editions,p_job gis.jobs) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE seal gis.gee_https_seals%ROWTYPE;a gis.gee_https_authorities%ROWTYPE;ids uuid[];
BEGIN
 IF p_edition.manifest->>'provider' IS DISTINCT FROM 'gee_genuine_https' THEN
  PERFORM gis.https_previous_validate_safety_report(p_report,p_edition,p_job);RETURN;END IF;
 PERFORM gis.validate_https_safety_report(p_report,p_edition,p_job);
 IF p_report->'base'->'output' IS DISTINCT FROM 'null'::jsonb THEN
  a:=gis.https_assert_authority(p_job.id);
  SELECT * INTO seal FROM gis.gee_https_seals WHERE job_id=p_job.id AND attempt_no=p_job.attempt_count;
  SELECT array_agg(value::uuid ORDER BY value::uuid) INTO ids FROM jsonb_array_elements_text(p_report->'receipts');
  IF seal.job_id IS NULL OR seal.lease_token IS DISTINCT FROM p_job.lease_token OR seal.recorder_id IS DISTINCT FROM a.recorder_id
  OR a.worker_id IS DISTINCT FROM p_job.worker_id OR seal.receipts IS DISTINCT FROM ids
  OR seal.output_sha256 IS DISTINCT FROM p_report->'base'->'output'->>'output_sha256'
  OR seal.evidence_sha256 IS DISTINCT FROM p_report->'base'->'output'->'content'->>'evidence_sha256'
  THEN RAISE EXCEPTION 'GIS_HTTPS_RECORDER_SEAL_REQUIRED';END IF;
 END IF;
END $f$;


CREATE FUNCTION gis.https_endpoint(p_uri text,p_method text,p_category text) RETURNS boolean
LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog AS $f$
DECLARE base text:=split_part(p_uri,'?',1);query text:=split_part(p_uri,'?',2);pairs text[];part text;seen text[]:=ARRAY[]::text[];key text;
BEGIN
 IF p_uri IS NULL OR p_method IS NULL OR p_category IS NULL OR length(p_uri)>2048 OR p_uri ~ '[#@[:space:]]'
 OR length(p_uri)-length(replace(p_uri,'?',''))>1 THEN RETURN false;END IF;
 IF p_category='catalog' THEN RETURN p_uri='https://storage.googleapis.com/earthengine-stac/catalog/catalog_deprecated.json' AND p_method='GET';END IF;
 IF NOT (CASE p_category
  WHEN 'discovery' THEN base='https://earthengine.googleapis.com/$discovery/rest' AND p_method='GET'
  WHEN 'algorithms' THEN base ~ '^https://earthengine[.]googleapis[.]com/v1(alpha)?/projects/green-area-gis-sandbox/algorithms$' AND p_method='GET'
  WHEN 'compute' THEN base ~ '^https://earthengine[.]googleapis[.]com/v1(alpha)?/projects/green-area-gis-sandbox/value:compute$' AND p_method='POST'
  ELSE false END) THEN RETURN false;END IF;
 IF query<>'' THEN
  pairs:=string_to_array(query,'&');
  FOREACH part IN ARRAY pairs LOOP
   key:=split_part(part,'=',1);
   IF key=ANY(seen) OR NOT (part IN ('prettyPrint=false','prettyPrint=true','alt=json')
    OR p_category='discovery' AND part IN ('version=v1','version=v1alpha')) THEN RETURN false;END IF;
   seen:=array_append(seen,key);
  END LOOP;
 END IF;
 RETURN p_category<>'discovery' OR 'version'=ANY(seen);
END $f$;

CREATE FUNCTION gis.https_record(p_subject uuid,p_action text,p_payload jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE subject uuid:=p_subject;j gis.jobs%ROWTYPE;a gis.gee_https_authorities%ROWTYPE;
 r gis.gee_safety_requests%ROWTYPE;output jsonb;wrapped jsonb;ids uuid[];rid uuid;sha text;obs jsonb;evidence jsonb;valid boolean;
BEGIN
 PERFORM gis.assert_environment();
 IF p_action='readiness' THEN
  PERFORM gis.keys(p_payload,ARRAY[]::text[]);
  RETURN jsonb_build_object('subject',subject,'mode','google_https','live_enabled',false,'genuine_completion_enabled',false);
 END IF;

 IF p_action NOT IN ('reserve','attempted','response','uncertain','seal') THEN RAISE EXCEPTION 'GIS_TRANSPORT_ACTION_REJECTED'; END IF;
 -- Same lock order as 045. Never accept a worker/session/project from payload.
 PERFORM 1 FROM gis.editions e JOIN gis.jobs q ON q.edition_id=e.id WHERE q.id=(p_payload->>'job_id')::uuid FOR UPDATE OF e;
 SELECT * INTO j FROM gis.jobs WHERE id=(p_payload->>'job_id')::uuid FOR UPDATE;
 SELECT * INTO a FROM gis.gee_https_authorities WHERE job_id=j.id;
 IF a.job_id IS NULL OR a.recorder_id IS DISTINCT FROM subject OR a.worker_id IS DISTINCT FROM j.worker_id
 OR a.mode IS DISTINCT FROM 'google_https' OR a.input_revision IS DISTINCT FROM j.input_revision OR a.input_hash IS DISTINCT FROM j.input_hash
 THEN RAISE EXCEPTION 'GIS_TRANSPORT_AUTHORITY_REQUIRED'; END IF;
 PERFORM gis.https_assert_authority(j.id,subject,p_action<>'uncertain');
 PERFORM gis.safety_lock(j.id,a.worker_id,(p_payload->>'lease_token')::uuid,p_action<>'uncertain');
 IF p_action IN ('reserve','attempted','uncertain') THEN
  RETURN gis.safety_budget(a.worker_id,p_action,p_payload);
 ELSIF p_action='response' THEN
  PERFORM gis.keys(p_payload,ARRAY['job_id','lease_token','request_id','request_sha256','response_sha256','status','category','observation','uri','method','peer_ip','certificate_sha256','tls_version','response_body']);
  SELECT * INTO r FROM gis.gee_safety_requests WHERE id=(p_payload->>'request_id')::uuid FOR UPDATE;
  IF r.job_id IS DISTINCT FROM j.id OR r.session_id IS DISTINCT FROM a.session_id OR r.attempt_no IS DISTINCT FROM j.attempt_count
  OR r.lease_token IS DISTINCT FROM j.lease_token OR r.state IS DISTINCT FROM 'attempted'
  OR r.attempted_at+interval '120 seconds'<=clock_timestamp() THEN RAISE EXCEPTION 'GIS_TRANSPORT_RECEIPT_REJECTED'; END IF;
  IF p_payload->>'tls_version' NOT IN ('TLSv1.2','TLSv1.3') OR p_payload->>'tls_version' IS NULL
  OR COALESCE(p_payload->>'certificate_sha256','') !~ '^[0-9a-f]{64}$'
  OR COALESCE(octet_length(p_payload->>'response_body'),0) NOT BETWEEN 1 AND 1048576
  OR p_payload->>'response_sha256' IS DISTINCT FROM encode(sha256(convert_to(p_payload->>'response_body','UTF8')),'hex')
  OR p_payload->>'category' NOT IN ('discovery','algorithms','catalog','compute')
  OR (p_payload->>'peer_ip')::inet <<= '127.0.0.0/8'::inet OR (p_payload->>'peer_ip')::inet <<= '10.0.0.0/8'::inet
  OR (p_payload->>'peer_ip')::inet <<= '192.168.0.0/16'::inet OR (p_payload->>'peer_ip')::inet <<= '172.16.0.0/12'::inet
  OR (p_payload->>'peer_ip')::inet <<= '169.254.0.0/16'::inet OR (p_payload->>'peer_ip')::inet <<= '::1/128'::inet
  OR NOT gis.https_endpoint(p_payload->>'uri',p_payload->>'method',p_payload->>'category')
  THEN RAISE EXCEPTION 'GIS_HTTPS_OBSERVATION_REJECTED';END IF;
  obs:=NULLIF(p_payload->'observation','null'::jsonb);
  IF obs IS DISTINCT FROM (CASE WHEN p_payload->>'category'='compute' AND p_payload->>'status'='200'
   THEN (p_payload->>'response_body')::jsonb->'result' ELSE NULL END)
  THEN RAISE EXCEPTION 'GIS_HTTPS_BODY_MISMATCH';END IF;
  IF p_payload->>'category'='compute' AND p_payload->>'status'='200' THEN
   PERFORM gis.keys(obs,ARRAY['scene_ids','acquired_ms','scene_count','valid_pixels','mean','min','max','complete']);
   IF obs IS NULL OR NOT obs ?& ARRAY['scene_ids','acquired_ms','scene_count','valid_pixels','mean','min','max','complete']

   THEN RAISE EXCEPTION 'GIS_TRANSPORT_RESPONSE_HASH_MISMATCH'; END IF;
  ELSIF obs IS NOT NULL THEN RAISE EXCEPTION 'GIS_TRANSPORT_OBSERVATION_REJECTED'; END IF;
  INSERT INTO gis.gee_https_receipts(request_id,job_id,recorder_id,category,request_sha256,response_sha256,status,observation,uri,method,peer_ip,certificate_sha256,tls_version)
  VALUES(r.id,j.id,subject,p_payload->>'category',p_payload->>'request_sha256',p_payload->>'response_sha256',(p_payload->>'status')::integer,obs,p_payload->>'uri',p_payload->>'method',(p_payload->>'peer_ip')::inet,p_payload->>'certificate_sha256',p_payload->>'tls_version');
  RETURN jsonb_build_object('request_id',r.id,'state','recorded','mode',a.mode);
 END IF;
 PERFORM gis.keys(p_payload,ARRAY['job_id','lease_token','output','receipts']);
 output:=p_payload->'output';
 SELECT array_agg(value::uuid ORDER BY value::uuid) INTO ids FROM jsonb_array_elements_text(p_payload->'receipts');
 IF COALESCE(cardinality(ids),0)=0 OR cardinality(ids)>32
 OR cardinality(ids)<>(SELECT count(DISTINCT x) FROM unnest(ids) x)
 OR cardinality(ids)<>(SELECT count(*) FROM gis.gee_safety_requests WHERE job_id=j.id AND attempt_no=j.attempt_count AND lease_token=j.lease_token)
 OR cardinality(ids)<>(SELECT count(*) FROM gis.gee_https_receipts t JOIN gis.gee_safety_requests b ON b.id=t.request_id
 WHERE t.request_id=ANY(ids) AND t.job_id=j.id AND t.recorder_id=subject AND b.state='attempted'
 AND b.attempt_no=j.attempt_count AND b.lease_token=j.lease_token)
 OR NOT EXISTS(SELECT 1 FROM gis.gee_https_receipts WHERE request_id=ANY(ids) AND category='compute' AND status=200)
 THEN RAISE EXCEPTION 'GIS_TRANSPORT_RECEIPT_SET_REJECTED'; END IF;
 SELECT t.observation INTO obs FROM gis.gee_https_receipts t WHERE t.request_id=ANY(ids) AND t.category='compute' AND t.status=200 ORDER BY t.created_at DESC,t.request_id DESC LIMIT 1;
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
 wrapped:=jsonb_build_object('schema_version',4,'protocol','gee_genuine_https','execution','live','live_enabled',false,
 'session_id',a.session_id,'policy_sha256',(SELECT policy_sha256 FROM gis.gee_safety_sessions WHERE id=a.session_id),
 'valid',valid,'error_code',CASE WHEN valid THEN NULL ELSE 'invalid_data' END,
 'base',jsonb_build_object('schema_version',2,'protocol','gee_live_v2','valid',valid,'error_code',CASE WHEN valid THEN NULL ELSE 'invalid_data' END,
 'input_hash',j.input_hash,'input_revision',j.input_revision,'semantic_request_sha256',a.request_sha256,'output',output,
 'output_canonical',gis.gee_live_canonical(output->'content'),'evidence_canonical',gis.gee_live_canonical(evidence)),
 'receipts',to_jsonb(ids),'failure_kind',null);
 -- Full scientific/output/request validation BEFORE seal; hashes alone cannot
 -- authorize Google origin. Only the separately bound trusted recorder may observe HTTPS.
 PERFORM gis.validate_https_safety_report(wrapped,(SELECT e FROM gis.editions e WHERE e.id=j.edition_id),j);
 INSERT INTO gis.gee_https_seals(job_id,attempt_no,lease_token,output_sha256,evidence_sha256,receipts,recorder_id)
 VALUES(j.id,j.attempt_count,j.lease_token,output->>'output_sha256',sha,ids,subject);
 INSERT INTO gis.audit(operation,job_id,detail) VALUES('https.seal',j.id,jsonb_build_object('attempt',j.attempt_count,'mode',a.mode,'publishable',false));
 RETURN wrapped;
END $f$;

CREATE FUNCTION gis.https_subject(p_role text) RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE c jsonb;
BEGIN
 PERFORM gis.assert_environment();
 IF p_role NOT IN ('gis_gee_https_worker','gis_gee_https_recorder') OR session_user<>'authenticator'
 OR current_setting('role',true) IS DISTINCT FROM p_role THEN RAISE EXCEPTION 'GIS_HTTPS_IDENTITY_REQUIRED' USING ERRCODE='42501';END IF;
 c:=NULLIF(current_setting('request.jwt.claims',true),'')::jsonb;
 IF c->>'role' IS DISTINCT FROM p_role OR c->>'iss' IS DISTINCT FROM 'http://127.0.0.1:55421/auth/v1'
 OR COALESCE(c->>'sub','') !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
 THEN RAISE EXCEPTION 'GIS_HTTPS_IDENTITY_REQUIRED' USING ERRCODE='42501';END IF;
 RETURN (c->>'sub')::uuid;
END $f$;
CREATE FUNCTION public.gis_gee_https_recorder(p_action text,p_payload jsonb DEFAULT '{}') RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
BEGIN RETURN gis.https_record(gis.https_subject('gis_gee_https_recorder'),p_action,p_payload);END $f$;
CREATE FUNCTION public.gis_gee_https_readiness() RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE subject uuid;
BEGIN subject:=gis.https_subject('gis_gee_https_worker');
 RETURN (SELECT jsonb_build_object('subject',subject,'worker_role','gis_gee_https_worker','database_name',database_name,
 'cluster_name',cluster_name,'runtime_instance',runtime_instance,'baseline_fingerprint',baseline_fingerprint,
 'protocol','gee_genuine_https','live_enabled',false,'contract_version','1.0.0-a6-genuine') FROM gis.environment WHERE singleton);
END $f$;


ALTER TABLE gis.results DROP CONSTRAINT results_provider_check;
ALTER TABLE gis.results ADD CONSTRAINT results_provider_check CHECK(provider IN ('synthetic','local_ldd','offline_processing','local_geotiff','local_ldd_prepare','local_geotiff_prepare','gee_contract_mock','gee_live_v2','gee_safety_rehearsal','gee_genuine_https'));


CREATE OR REPLACE FUNCTION gis.queue_protocol_kind(p_action text,p_payload jsonb,p_protocol text) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE safety_session gis.gee_safety_sessions%ROWTYPE; j gis.jobs%ROWTYPE; e gis.editions%ROWTYPE; candidate record;
 worker uuid; token uuid; jid uuid; eid uuid; rid uuid; v_now timestamptz;
 progress_value integer; report_value jsonb; code text; next_state text; n integer:=0;
 p_native boolean:=p_protocol<>'v1'; u gis.ldd_uploads%ROWTYPE; ldd_dataset gis.datasets%ROWTYPE; processing_request gis.processing_requests%ROWTYPE; geo gis.geotiff_uploads%ROWTYPE; geo_dataset gis.datasets%ROWTYPE;
BEGIN
 PERFORM gis.assert_environment();
 IF p_protocol NOT IN ('v1','v2','ldd','gee_offline','geotiff','gee_contract_mock','gee_live_v2','gee_safety_rehearsal','gee_genuine_https') OR p_protocol IS NULL THEN RAISE EXCEPTION 'GIS_WORKER_PROTOCOL_MISMATCH'; END IF;
 IF p_action='claim' THEN
   PERFORM gis.keys(p_payload,ARRAY['worker_id']);
   worker:=(p_payload->>'worker_id')::uuid;
   IF worker IS NULL THEN RAISE EXCEPTION 'GIS_WORKER_REQUIRED'; END IF;
   IF NOT pg_try_advisory_xact_lock(hashtextextended('gis-t1-single-claim',0)) THEN
     RETURN CASE WHEN p_native THEN jsonb_build_object('job',NULL) ELSE NULL END; END IF;
   IF EXISTS(SELECT 1 FROM gis.jobs WHERE state='running') THEN
     RETURN CASE WHEN p_native THEN jsonb_build_object('job',NULL) ELSE NULL END; END IF;
   FOR candidate IN SELECT q.id,q.edition_id FROM gis.jobs q JOIN gis.editions d ON d.id=q.edition_id
      WHERE q.state='queued' AND q.attempt_count<(CASE WHEN p_protocol IN ('gee_safety_rehearsal','gee_genuine_https') THEN 2 ELSE 3 END) AND q.available_at<=clock_timestamp()
        AND q.kind NOT IN ('prepare_ldd_edition','prepare_geotiff_edition') AND gis.edition_protocol(d.id)=p_protocol
        AND (p_protocol NOT IN ('gee_safety_rehearsal','gee_genuine_https') OR EXISTS(SELECT 1 FROM gis.gee_safety_jobs b JOIN gis.gee_safety_sessions s ON s.id=b.session_id WHERE b.job_id=q.id AND s.bound_worker=CASE WHEN p_action='claim' THEN worker ELSE (p_payload->>'worker_id')::uuid END AND s.state='open' AND s.ends_at>clock_timestamp()))
      ORDER BY q.available_at,q.created_at,q.id LIMIT 20 LOOP
     SELECT * INTO e FROM gis.editions WHERE id=candidate.edition_id FOR UPDATE SKIP LOCKED;
     IF NOT FOUND THEN CONTINUE; END IF;
     SELECT * INTO j FROM gis.jobs WHERE id=candidate.id FOR UPDATE SKIP LOCKED;
     IF NOT FOUND THEN CONTINUE; END IF;
     v_now:=clock_timestamp();
     IF j.state<>'queued' OR j.attempt_count>=(CASE WHEN p_protocol IN ('gee_safety_rehearsal','gee_genuine_https') THEN 2 ELSE 3 END) OR j.available_at>v_now
       OR e.state<>'validating' OR gis.edition_protocol(e.id) IS DISTINCT FROM p_protocol THEN CONTINUE; END IF;
     IF p_protocol='gee_genuine_https' THEN PERFORM gis.https_assert_authority(j.id);END IF;
     IF p_protocol IN ('gee_safety_rehearsal','gee_genuine_https') THEN PERFORM gis.safety_claim_guard(j.id,worker); END IF;
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
     IF p_protocol IN ('gee_safety_rehearsal','gee_genuine_https') THEN
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
         VALUES(CASE WHEN p_protocol IN ('gee_safety_rehearsal','gee_genuine_https') THEN 'safety.'||p_action WHEN p_protocol='gee_live_v2' THEN 'gee_live.'||p_action WHEN p_protocol='gee_contract_mock' THEN 'gee_mock.claim' WHEN p_protocol='geotiff' THEN 'geotiff.claim' WHEN p_protocol='gee_offline' THEN 'processing.claim' WHEN p_protocol='ldd' THEN 'ldd.claim' ELSE 'worker_v2.claim' END,e.dataset_id,e.id,j.id,jsonb_build_object('worker_id',worker,'attempt',j.attempt_count));
       RETURN jsonb_build_object('job',report_value||jsonb_build_object('id',j.id,'dataset_id',e.dataset_id,
         'kind',j.kind,'attempt_number',j.attempt_count));
     END IF;
     RETURN report_value;
   END LOOP;
   RETURN CASE WHEN p_native THEN jsonb_build_object('job',NULL) ELSE NULL END;
 ELSIF p_action='recover' THEN
   PERFORM gis.keys(p_payload,CASE WHEN p_protocol IN ('gee_safety_rehearsal','gee_genuine_https') THEN ARRAY['worker_id'] ELSE ARRAY[]::text[] END);
   FOR candidate IN SELECT q.id,q.edition_id FROM gis.jobs q JOIN gis.editions d ON d.id=q.edition_id
     WHERE q.state='running' AND q.lease_until<=clock_timestamp()
       AND q.kind NOT IN ('prepare_ldd_edition','prepare_geotiff_edition') AND gis.edition_protocol(d.id)=p_protocol
        AND (p_protocol NOT IN ('gee_safety_rehearsal','gee_genuine_https') OR EXISTS(SELECT 1 FROM gis.gee_safety_jobs b JOIN gis.gee_safety_sessions s ON s.id=b.session_id WHERE b.job_id=q.id AND s.bound_worker=CASE WHEN p_action='claim' THEN worker ELSE (p_payload->>'worker_id')::uuid END AND s.state='open' AND s.ends_at>clock_timestamp()))
     ORDER BY q.lease_until,q.id LIMIT 20 LOOP
     SELECT * INTO e FROM gis.editions WHERE id=candidate.edition_id FOR UPDATE SKIP LOCKED;
     IF NOT FOUND THEN CONTINUE; END IF;
     SELECT * INTO j FROM gis.jobs WHERE id=candidate.id FOR UPDATE SKIP LOCKED;
     IF NOT FOUND THEN CONTINUE; END IF;
     v_now:=clock_timestamp();
     IF j.state<>'running' OR j.lease_until>v_now THEN CONTINUE; END IF;
     IF p_protocol IN ('gee_safety_rehearsal','gee_genuine_https') THEN PERFORM gis.safety_abandon(j.id,j.attempt_count,j.lease_token); END IF;
     UPDATE gis.attempts SET state='expired',error_code='lease_expired',finished_at=v_now
       WHERE job_id=j.id AND attempt_no=j.attempt_count AND lease_token=j.lease_token AND state='running';
     IF p_protocol IN ('gee_safety_rehearsal','gee_genuine_https') THEN SELECT s.* INTO safety_session FROM gis.gee_safety_sessions s JOIN gis.gee_safety_jobs b ON b.session_id=s.id WHERE b.job_id=j.id; END IF;
     IF j.attempt_count<(CASE WHEN p_protocol IN ('gee_safety_rehearsal','gee_genuine_https') THEN 2 ELSE 3 END) AND (p_protocol NOT IN ('gee_safety_rehearsal','gee_genuine_https') OR (safety_session.state='open' AND safety_session.ends_at>clock_timestamp() AND NOT EXISTS(SELECT 1 FROM gis.attempts a WHERE a.job_id=j.id GROUP BY a.job_id HAVING min(a.started_at)+interval '180 seconds'<=clock_timestamp()))) THEN
       UPDATE gis.jobs SET state='queued',worker_id=NULL,lease_token=NULL,lease_until=NULL,progress=0,
         available_at=v_now+make_interval(secs=>CASE j.attempt_count WHEN 1 THEN 5 ELSE 20 END+floor(random()*3)::int)
         WHERE id=j.id;
     ELSE
       UPDATE gis.jobs SET state='failed',worker_id=NULL,lease_token=NULL,lease_until=NULL,
         error_code='attempts_exhausted',finished_at=v_now WHERE id=j.id;
       UPDATE gis.editions SET state='draft' WHERE id=e.id AND state='validating';
     END IF;
     INSERT INTO gis.audit(operation,dataset_id,edition_id,job_id,detail)
       VALUES(CASE WHEN p_protocol IN ('gee_safety_rehearsal','gee_genuine_https') THEN 'safety.'||p_action WHEN p_protocol='gee_live_v2' THEN 'gee_live.'||p_action WHEN p_protocol='gee_contract_mock' THEN 'gee_mock.recover' WHEN p_protocol='geotiff' THEN 'geotiff.recover' WHEN p_protocol='gee_offline' THEN 'processing.recover' WHEN p_protocol='ldd' THEN 'ldd.recover' WHEN p_native THEN 'worker_v2.recover' ELSE 'worker.recover' END,e.dataset_id,e.id,j.id,
         jsonb_build_object('attempt',j.attempt_count,'terminal',j.attempt_count=(CASE WHEN p_protocol IN ('gee_safety_rehearsal','gee_genuine_https') THEN 2 ELSE 3 END)));
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
   IF p_protocol='gee_genuine_https' AND p_action<>'fail' THEN PERFORM gis.https_assert_authority(j.id);END IF;
   IF p_protocol IN ('gee_safety_rehearsal','gee_genuine_https') THEN PERFORM gis.safety_lock(j.id,worker,token,p_action<>'fail'); END IF;
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
     IF p_protocol IN ('gee_safety_rehearsal','gee_genuine_https') THEN PERFORM gis.validate_safety_report(report_value,e,j);
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
       VALUES(j.id,e.id,j.input_revision,j.input_hash,j.validator_version,j.attempt_count,token,true,report_value,CASE WHEN p_protocol IN ('gee_safety_rehearsal','gee_genuine_https') THEN p_protocol WHEN p_protocol='gee_live_v2' THEN 'gee_live_v2' WHEN p_protocol='gee_contract_mock' THEN 'gee_contract_mock' WHEN p_protocol='geotiff' THEN 'local_geotiff' WHEN p_protocol='gee_offline' THEN 'offline_processing' WHEN p_protocol='ldd' THEN 'local_ldd' ELSE 'synthetic' END) RETURNING id INTO rid;
     IF p_protocol IN ('gee_offline','geotiff','gee_contract_mock','gee_live_v2','gee_safety_rehearsal','gee_genuine_https') THEN
       UPDATE gis.editions SET state='draft',validated_result_id=NULL WHERE id=e.id;
     ELSE
       UPDATE gis.editions SET state='validated',validated_result_id=rid WHERE id=e.id;
     END IF;
     IF p_protocol IN ('gee_safety_rehearsal','gee_genuine_https') THEN PERFORM gis.safety_record_candidate(j.id,rid,worker); END IF;
     IF p_protocol='gee_live_v2' THEN PERFORM gis.gee_live_record_candidate(j.id,rid,worker); END IF;
     IF p_protocol='gee_contract_mock' THEN PERFORM gis.gee_mock_record_candidate(j.id,rid,worker); END IF;
     UPDATE gis.jobs SET state='succeeded',worker_id=NULL,lease_token=NULL,lease_until=NULL,progress=100,finished_at=v_now WHERE id=j.id;
     UPDATE gis.attempts SET state='succeeded',progress=100,finished_at=v_now WHERE job_id=j.id AND attempt_no=j.attempt_count AND lease_token=token;
     INSERT INTO gis.audit(operation,dataset_id,edition_id,job_id,detail)
       VALUES(CASE WHEN p_protocol IN ('gee_safety_rehearsal','gee_genuine_https') THEN 'safety.'||p_action WHEN p_protocol='gee_live_v2' THEN 'gee_live.'||p_action WHEN p_protocol='gee_contract_mock' THEN 'gee_mock.complete' WHEN p_protocol='geotiff' THEN 'geotiff.complete' WHEN p_protocol='gee_offline' THEN 'processing.complete' WHEN p_protocol='ldd' THEN 'ldd.complete' WHEN p_native THEN 'worker_v2.complete' ELSE 'worker.complete' END,e.dataset_id,e.id,j.id,
         jsonb_build_object('result_id',rid,'attempt',j.attempt_count));
     RETURN jsonb_build_object('job_id',j.id,'state','succeeded','result_id',rid);
   END IF;
   IF p_action='complete' THEN code:='invalid_data';
   ELSE code:=p_payload->>'error_code'; END IF;
   IF code IS NULL OR code NOT IN ('invalid_data','transient') THEN RAISE EXCEPTION 'GIS_INVALID_FAILURE'; END IF;
   IF p_native AND p_action='fail' AND (code<>'transient' OR report_value->>'error_code' NOT IN (
     'NATIVE_TIMEOUT','NATIVE_MEMORY_LIMIT','NATIVE_PROCESS_FAILED','TRANSIENT_SYNTHETIC','WORKER_SHUTDOWN','NATIVE_OUTPUT_LIMIT')) THEN
     RAISE EXCEPTION 'GIS_INVALID_FAILURE'; END IF;
   IF p_protocol IN ('gee_safety_rehearsal','gee_genuine_https') THEN PERFORM gis.safety_abandon(j.id,j.attempt_count,token); END IF;
   next_state:=CASE WHEN code='transient' AND (p_protocol NOT IN ('gee_safety_rehearsal','gee_genuine_https') OR EXISTS(SELECT 1 FROM gis.gee_safety_sessions s JOIN gis.gee_safety_jobs b ON b.session_id=s.id WHERE b.job_id=j.id AND s.state='open' AND s.ends_at>clock_timestamp())) AND j.attempt_count<(CASE WHEN p_protocol IN ('gee_safety_rehearsal','gee_genuine_https') THEN 2 ELSE 3 END) THEN 'queued' ELSE 'failed' END;
   UPDATE gis.attempts SET state='failed',error_code=code,finished_at=v_now
     WHERE job_id=j.id AND attempt_no=j.attempt_count AND lease_token=token;
   UPDATE gis.jobs SET state=next_state,worker_id=NULL,lease_token=NULL,lease_until=NULL,
     error_code=CASE WHEN next_state='failed' THEN code ELSE NULL END,progress=0,
     available_at=v_now+make_interval(secs=>CASE j.attempt_count WHEN 1 THEN 5 ELSE 20 END+floor(random()*3)::int),
     finished_at=CASE WHEN next_state='failed' THEN v_now ELSE NULL END WHERE id=j.id;
   IF next_state='failed' THEN UPDATE gis.editions SET state='draft' WHERE id=e.id; END IF;
   INSERT INTO gis.audit(operation,dataset_id,edition_id,job_id,detail)
     VALUES(CASE WHEN p_protocol IN ('gee_safety_rehearsal','gee_genuine_https') THEN 'safety.'||p_action WHEN p_protocol='gee_live_v2' THEN 'gee_live.'||p_action WHEN p_protocol='gee_contract_mock' THEN 'gee_mock.fail' WHEN p_protocol='geotiff' THEN 'geotiff.fail' WHEN p_protocol='gee_offline' THEN 'processing.fail' WHEN p_protocol='ldd' THEN 'ldd.fail' WHEN p_native THEN 'worker_v2.fail' ELSE 'worker.fail' END,e.dataset_id,e.id,j.id,
       jsonb_build_object('attempt',j.attempt_count,'error_code',code,'state',next_state));
   RETURN CASE WHEN p_native THEN jsonb_build_object('job_id',j.id,'state',next_state,'error_code',code)
     ELSE jsonb_build_object('job_id',j.id,'state',next_state) END;
 END IF;
 RAISE EXCEPTION 'GIS_UNKNOWN_WORKER_ACTION';
END $f$;

CREATE OR REPLACE FUNCTION gis.check_safety_catalog() RETURNS trigger
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
    OR a.state<>'succeeded' OR a.validation_report IS DISTINCT FROM r.report OR r.provider<>(CASE WHEN e.manifest->>'provider'='gee_genuine_https' THEN 'gee_genuine_https' ELSE 'gee_safety_rehearsal' END)
    OR r.report->'valid' IS DISTINCT FROM 'true'::jsonb THEN RAISE EXCEPTION 'GIS_SAFETY_CANDIDATE_INVARIANT'; END IF;
  ELSIF c.result_id IS NOT NULL THEN RAISE EXCEPTION 'GIS_SAFETY_PREMATURE_CANDIDATE'; END IF;
 END LOOP;RETURN NULL;
END $f$;

CREATE FUNCTION gis.https_finalize_protocol(p_worker uuid,p_protocol text) RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE c record;j gis.jobs%ROWTYPE;s gis.gee_safety_sessions%ROWTYPE;n integer:=0;
BEGIN
 IF p_protocol NOT IN ('gee_safety_rehearsal','gee_genuine_https') THEN RAISE EXCEPTION 'GIS_WORKER_PROTOCOL_MISMATCH';END IF;
 FOR c IN SELECT q.id,q.edition_id FROM gis.jobs q JOIN gis.gee_safety_jobs b ON b.job_id=q.id JOIN gis.gee_safety_sessions x ON x.id=b.session_id WHERE gis.edition_protocol(q.edition_id)=p_protocol AND x.bound_worker=p_worker AND ((p_protocol='gee_genuine_https' AND EXISTS(SELECT 1 FROM gis.gee_https_authorities h JOIN gis.gee_https_runtimes rt ON rt.id=h.runtime_id WHERE h.job_id=q.id AND rt.expires_at<=clock_timestamp())) OR x.state<>'open' OR x.ends_at<=clock_timestamp() OR EXISTS(SELECT 1 FROM gis.attempts a WHERE a.job_id=q.id GROUP BY a.job_id HAVING min(a.started_at)+interval '180 seconds'<=clock_timestamp())) AND (q.state='queued' OR q.state='running' AND q.lease_until<=clock_timestamp()) ORDER BY q.id LIMIT 20 LOOP
  PERFORM 1 FROM gis.editions WHERE id=c.edition_id FOR UPDATE SKIP LOCKED;IF NOT FOUND THEN CONTINUE; END IF;
  SELECT * INTO j FROM gis.jobs WHERE id=c.id FOR UPDATE SKIP LOCKED;IF NOT FOUND OR j.state NOT IN ('queued','running') OR (j.state='running' AND j.lease_until>clock_timestamp()) THEN CONTINUE; END IF;
  SELECT x.* INTO s FROM gis.gee_safety_sessions x JOIN gis.gee_safety_jobs b ON b.session_id=x.id WHERE b.job_id=j.id FOR UPDATE OF x SKIP LOCKED;IF NOT FOUND THEN CONTINUE;END IF;
  IF s.state='open' AND s.ends_at>clock_timestamp() AND NOT (p_protocol='gee_genuine_https' AND EXISTS(SELECT 1 FROM gis.gee_https_authorities h JOIN gis.gee_https_runtimes rt ON rt.id=h.runtime_id WHERE h.job_id=j.id AND rt.expires_at<=clock_timestamp())) AND NOT EXISTS(SELECT 1 FROM gis.attempts a WHERE a.job_id=j.id GROUP BY a.job_id HAVING min(a.started_at)+interval '180 seconds'<=clock_timestamp()) THEN CONTINUE; END IF;
  IF s.state='open' AND p_protocol='gee_genuine_https' AND EXISTS(SELECT 1 FROM gis.gee_https_authorities h JOIN gis.gee_https_runtimes rt ON rt.id=h.runtime_id WHERE h.job_id=j.id AND rt.expires_at<=clock_timestamp()) THEN UPDATE gis.gee_safety_sessions SET state='stopped',stopped_at=clock_timestamp(),stop_reason='operator_stop' WHERE id=s.id;END IF;
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

CREATE OR REPLACE FUNCTION gis.safety_finalize_stopped(p_worker uuid) RETURNS integer
LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
 SELECT gis.https_finalize_protocol(p_worker,'gee_safety_rehearsal')
$f$;
CREATE FUNCTION gis.https_session_integrity() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
BEGIN
 IF (SELECT count(DISTINCT i.value->'request'->>'execution') FROM gis.gee_safety_jobs b
  JOIN gis.gee_live_requests r ON r.job_id=b.job_id JOIN gis.gee_live_inputs i ON i.id=r.input_id WHERE b.session_id=NEW.session_id)>1
 THEN RAISE EXCEPTION 'GIS_HTTPS_MIXED_SESSION_FORBIDDEN';END IF;
 RETURN NULL;
END $f$;
CREATE CONSTRAINT TRIGGER https_session_integrity AFTER INSERT ON gis.gee_safety_jobs
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION gis.https_session_integrity();


CREATE FUNCTION gis.https_rehearsal_budget(p_worker uuid,p_action text,p_payload jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM gis.jobs j WHERE j.id=(p_payload->>'job_id')::uuid AND gis.edition_protocol(j.edition_id)='gee_safety_rehearsal')
 THEN RAISE EXCEPTION 'GIS_WORKER_PROTOCOL_MISMATCH';END IF;
 RETURN gis.safety_budget(p_worker,p_action,p_payload);
END $f$;
CREATE FUNCTION gis.https_assert_rehearsal_session(p_session uuid) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
BEGIN
 IF EXISTS(SELECT 1 FROM gis.gee_safety_jobs b JOIN gis.jobs q ON q.id=b.job_id JOIN gis.editions ed ON ed.id=q.edition_id
 WHERE b.session_id=p_session AND gis.edition_protocol(ed.id)='gee_genuine_https')
 THEN RAISE EXCEPTION 'GIS_WORKER_PROTOCOL_MISMATCH';END IF;
END $f$;

CREATE OR REPLACE FUNCTION public.gis_gee_safety_worker(p_action text,p_payload jsonb DEFAULT '{}') RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE subject uuid;s gis.gee_safety_sessions%ROWTYPE;e gis.editions%ROWTYPE;j gis.jobs%ROWTYPE;a gis.attempts%ROWTYPE;r gis.results%ROWTYPE;
BEGIN
 subject:=gis.safety_subject();
 IF p_action LIKE 'live%' THEN RAISE EXCEPTION 'GEE_TRUSTED_LIVE_NOT_APPROVED'; END IF;
 IF p_action IN ('reserve','attempted','finished','uncertain') THEN RETURN gis.https_rehearsal_budget(subject,p_action,p_payload);END IF;
 IF p_action='stop' THEN
  PERFORM gis.keys(p_payload,ARRAY['session_id']);
  SELECT * INTO s FROM gis.gee_safety_sessions WHERE id=(p_payload->>'session_id')::uuid FOR UPDATE;
  IF NOT FOUND OR s.bound_worker IS DISTINCT FROM subject THEN RAISE EXCEPTION 'GIS_SAFETY_WORKER_MISMATCH'; END IF;
  PERFORM gis.https_assert_rehearsal_session(s.id);
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

CREATE FUNCTION public.gis_gee_https_worker(p_action text,p_payload jsonb DEFAULT '{}') RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE subject uuid;s gis.gee_safety_sessions%ROWTYPE;e gis.editions%ROWTYPE;j gis.jobs%ROWTYPE;a gis.attempts%ROWTYPE;r gis.results%ROWTYPE;
BEGIN
 subject:=gis.https_subject('gis_gee_https_worker');
 IF p_action LIKE 'live%' THEN RAISE EXCEPTION 'GEE_TRUSTED_LIVE_NOT_APPROVED'; END IF;
 IF p_action IN ('reserve','attempted','finished','uncertain') THEN RAISE EXCEPTION 'GIS_HTTPS_RECORDER_REQUIRED';END IF;
 IF p_action='stop' THEN
  PERFORM gis.keys(p_payload,ARRAY['session_id']);
  SELECT * INTO s FROM gis.gee_safety_sessions WHERE id=(p_payload->>'session_id')::uuid FOR UPDATE;
  IF NOT FOUND OR s.bound_worker IS DISTINCT FROM subject THEN RAISE EXCEPTION 'GIS_SAFETY_WORKER_MISMATCH'; END IF;
  IF NOT EXISTS(SELECT 1 FROM gis.gee_safety_jobs b JOIN gis.jobs q ON q.id=b.job_id JOIN gis.editions ed ON ed.id=q.edition_id
   WHERE b.session_id=s.id AND gis.edition_protocol(ed.id)='gee_genuine_https')
  THEN RAISE EXCEPTION 'GIS_WORKER_PROTOCOL_MISMATCH';END IF;
  IF s.state='open' THEN UPDATE gis.gee_safety_sessions SET state='stopped',stopped_at=clock_timestamp(),stop_reason='operator_stop' WHERE id=s.id RETURNING * INTO s; END IF;
  RETURN jsonb_build_object('session_id',s.id,'state',s.state);
 END IF;
 PERFORM gis.keys(p_payload,CASE p_action WHEN 'claim' THEN ARRAY[]::text[] WHEN 'recover' THEN ARRAY[]::text[] WHEN 'heartbeat' THEN ARRAY['job_id','lease_token','progress'] WHEN 'complete' THEN ARRAY['job_id','lease_token','report'] WHEN 'fail' THEN ARRAY['job_id','lease_token','report','error_code'] ELSE ARRAY[]::text[] END);
 IF p_action='recover' THEN
  PERFORM gis.https_finalize_protocol(subject,'gee_genuine_https');
  RETURN gis.queue_protocol_kind(p_action,jsonb_build_object('worker_id',subject),'gee_genuine_https');
 END IF;
 IF p_action='complete' THEN
  SELECT ed.* INTO e FROM gis.editions ed JOIN gis.jobs q ON q.edition_id=ed.id WHERE q.id=(p_payload->>'job_id')::uuid FOR UPDATE OF ed;
  SELECT * INTO j FROM gis.jobs WHERE id=(p_payload->>'job_id')::uuid FOR UPDATE;
  IF j.state='succeeded' AND gis.edition_protocol(e.id)='gee_genuine_https' THEN
   SELECT * INTO a FROM gis.attempts WHERE job_id=j.id AND attempt_no=j.attempt_count;SELECT * INTO r FROM gis.results WHERE job_id=j.id;
   IF a.worker_id IS DISTINCT FROM subject OR a.lease_token IS DISTINCT FROM (p_payload->>'lease_token')::uuid OR r.report IS DISTINCT FROM p_payload->'report' THEN RAISE EXCEPTION 'GIS_STALE_LEASE'; END IF;
   RETURN jsonb_build_object('job_id',j.id,'state','succeeded','result_id',r.id,'replayed',true);
  END IF;
 END IF;
 RETURN gis.queue_protocol_kind(p_action,p_payload||jsonb_build_object('worker_id',subject),'gee_genuine_https');
END $f$;

CREATE FUNCTION gis.check_https_catalog() RETURNS trigger
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
CREATE CONSTRAINT TRIGGER https_candidate_integrity AFTER INSERT ON gis.gee_https_seals
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION gis.check_https_catalog();


DO $acl$ DECLARE f record;BEGIN
 FOR f IN SELECT p.oid::regprocedure AS sig FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
 WHERE (n.nspname='gis' AND (p.proname LIKE '%https%' OR p.proname IN ('edition_protocol','safety_manifest','safety_finalize_stopped','validate_gee_live_case','validate_safety_report','check_safety_catalog','queue_protocol_kind')))
 OR (n.nspname='public' AND p.proname IN ('gis_gee_https_worker','gis_gee_https_recorder','gis_gee_https_readiness','gis_gee_safety_worker')) LOOP
 EXECUTE format('REVOKE ALL ON FUNCTION %s FROM PUBLIC,anon,authenticated,service_role,gis_worker,gis_native_worker,gis_gee_mock_worker,gis_gee_live_worker,gis_gee_safety_worker,gis_gee_transport_recorder,gis_gee_https_worker,gis_gee_https_recorder',f.sig);
 END LOOP;
END $acl$;
GRANT EXECUTE ON FUNCTION public.gis_gee_https_worker(text,jsonb),public.gis_gee_https_readiness() TO gis_gee_https_worker;
GRANT EXECUTE ON FUNCTION public.gis_gee_https_recorder(text,jsonb) TO gis_gee_https_recorder;
GRANT EXECUTE ON FUNCTION public.gis_gee_safety_worker(text,jsonb) TO gis_gee_safety_worker;
REVOKE CREATE ON SCHEMA public FROM gis_owner;
RESET ROLE;
NOTIFY pgrst,'reload schema';
