-- A6.4b injected-only future-live foundation. No Google, live runtime or publication.
-- The attested operator supplies BEGIN/runtime proof and INSERT-only ledger entry.
DO $guard$ BEGIN
 IF current_database() NOT IN ('postgres','gis_t1_upgrade') OR current_setting('cluster_name')<>'green-area-gis-t0'
 OR NOT EXISTS(SELECT 1 FROM gis.environment WHERE singleton AND NOT activation_enabled
   AND runtime_instance=current_setting('gis.runtime_instance',true) AND baseline_fingerprint=current_setting('gis.baseline_fingerprint',true))
 OR NOT EXISTS(SELECT 1 FROM gis.schema_migrations WHERE version=43 AND sha256='cc8d9fe7bd7163dd307a2f944614116bccd6460a50314d108cecc242320563b1')
 OR EXISTS(SELECT 1 FROM gis.schema_migrations WHERE version>=44) THEN
  RAISE EXCEPTION 'GIS_LOCAL_BASELINE_043_REQUIRED'; END IF;
END $guard$;
DO $role$ BEGIN
 IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='gis_gee_live_worker') THEN
  IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='gis_gee_live_worker' AND NOT rolsuper AND NOT rolbypassrls
   AND NOT rolcanlogin AND NOT rolcreatedb AND NOT rolcreaterole AND NOT rolreplication AND NOT rolinherit
   AND shobj_description(oid,'pg_authid')='gis-a6.4b-injected-only')
   OR EXISTS(SELECT 1 FROM pg_auth_members WHERE member='gis_gee_live_worker'::regrole)
   OR EXISTS(SELECT 1 FROM pg_auth_members WHERE roleid='gis_gee_live_worker'::regrole AND member NOT IN ('postgres'::regrole,'authenticator'::regrole))
  THEN RAISE EXCEPTION 'GIS_GEE_LIVE_ROLE_COLLISION'; END IF;
 ELSE
  CREATE ROLE gis_gee_live_worker NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOREPLICATION NOINHERIT;
 END IF;
END $role$;
COMMENT ON ROLE gis_gee_live_worker IS 'gis-a6.4b-injected-only';
GRANT gis_gee_live_worker TO authenticator WITH INHERIT FALSE, SET TRUE;
GRANT USAGE ON SCHEMA public TO gis_gee_live_worker;
REVOKE ALL ON SCHEMA gis FROM gis_gee_live_worker;
GRANT CREATE ON SCHEMA public TO gis_owner;
SET LOCAL ROLE gis_owner;
SELECT gis.assert_environment();

-- No registration RPC: only the attested test operator installs A6.1-validated
-- injected inputs without an expected-output oracle; never attest to real observations.
CREATE TABLE gis.gee_live_inputs(
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 value jsonb NOT NULL CHECK(jsonb_typeof(value)='object'),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp());
CREATE UNIQUE INDEX gee_live_inputs_content ON gis.gee_live_inputs((value->>'request_sha256'));
CREATE TABLE gis.gee_live_requests(
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 input_id uuid NOT NULL UNIQUE REFERENCES gis.gee_live_inputs(id),
 dataset_id uuid NOT NULL REFERENCES gis.datasets(id),
 edition_id uuid NOT NULL UNIQUE,job_id uuid NOT NULL UNIQUE REFERENCES gis.jobs(id),
 requested_by uuid REFERENCES public.profiles(id) ON DELETE SET NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 FOREIGN KEY(edition_id,dataset_id) REFERENCES gis.editions(id,dataset_id));
CREATE TABLE gis.gee_live_candidates(
 result_id uuid PRIMARY KEY REFERENCES gis.results(id),job_id uuid NOT NULL UNIQUE REFERENCES gis.jobs(id),
 request_id uuid NOT NULL UNIQUE REFERENCES gis.gee_live_requests(id),
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
 FOREACH t IN ARRAY ARRAY['gee_live_inputs','gee_live_requests','gee_live_candidates'] LOOP
  EXECUTE format('ALTER TABLE gis.%I ENABLE ROW LEVEL SECURITY',t);
  EXECUTE format('ALTER TABLE gis.%I FORCE ROW LEVEL SECURITY',t);
  EXECUTE format('CREATE POLICY owner_access ON gis.%I TO gis_owner USING(true) WITH CHECK(true)',t);
  EXECUTE format('REVOKE ALL ON gis.%I FROM PUBLIC,anon,authenticated,service_role,gis_worker,gis_native_worker,gis_gee_mock_worker,gis_gee_live_worker',t);
 END LOOP;
END $rls$;
CREATE FUNCTION gis.gee_live_immutable() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
BEGIN RAISE EXCEPTION 'GIS_GEE_LIVE_IMMUTABLE'; END $f$;
DO $immutable$ DECLARE t text; BEGIN
 FOREACH t IN ARRAY ARRAY['gee_live_inputs','gee_live_requests','gee_live_candidates'] LOOP
  EXECUTE format('CREATE TRIGGER immutable_gee_live BEFORE UPDATE OR DELETE ON gis.%I FOR EACH ROW EXECUTE FUNCTION gis.gee_live_immutable()',t);
 END LOOP;
END $immutable$;

CREATE FUNCTION gis.gee_live_method(product text,month integer) RETURNS jsonb LANGUAGE sql IMMUTABLE SET search_path=pg_catalog AS $f$ SELECT CASE WHEN product='ndvi' AND month=0 THEN '{"version":"ndvi-annual-legacy-v1","product":"ndvi","frequency":"annual","collections":["COPERNICUS/S2_SR_HARMONIZED","GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED"],"bands":["B8","B4","cs"],"units":"unitless","scene_cloud_lt":20,"fallback_cloud_lt":80,"clear_score_gte":0.6,"reflectance_divisor":10000,"qa_mask_bits":[],"st_multiplier":null,"st_offset_kelvin":null,"celsius_subtract":null,"composite":"median_bands_then_normalized_difference","mask_negative_ndvi":true,"reduction_scale_m":500,"best_effort":true,"tile_scale":4,"max_pixels":10000000000,"legacy_sources":[["gee_utils.py","d1f25fdca1c0562379d5f98002e9bea0a3c94d36f71df6bea45ec6bf94a9a175"],["routers/ndvi/compute.py","87b22a35e9dd610e6359f375de5dd9cfebd666bdcee28a22363179155b1febcd"],["routers/lst.py","748dcc2d6cc33108bdb7f07effadc2bcbb202e6436703fec68d7d0017004176f"]]}'::jsonb WHEN product='ndvi' AND month BETWEEN 1 AND 12 THEN '{"version":"ndvi-monthly-legacy-v1","product":"ndvi","frequency":"monthly","collections":["COPERNICUS/S2_SR_HARMONIZED","GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED"],"bands":["B8","B4","cs"],"units":"unitless","scene_cloud_lt":80,"fallback_cloud_lt":null,"clear_score_gte":0.6,"reflectance_divisor":10000,"qa_mask_bits":[],"st_multiplier":null,"st_offset_kelvin":null,"celsius_subtract":null,"composite":"median_bands_then_normalized_difference","mask_negative_ndvi":false,"reduction_scale_m":500,"best_effort":true,"tile_scale":null,"max_pixels":10000000000,"legacy_sources":[["gee_utils.py","d1f25fdca1c0562379d5f98002e9bea0a3c94d36f71df6bea45ec6bf94a9a175"],["routers/ndvi/compute.py","87b22a35e9dd610e6359f375de5dd9cfebd666bdcee28a22363179155b1febcd"],["routers/lst.py","748dcc2d6cc33108bdb7f07effadc2bcbb202e6436703fec68d7d0017004176f"]]}'::jsonb WHEN product='lst' AND month=0 THEN '{"version":"lst-annual-legacy-v1","product":"lst","frequency":"annual","collections":["LANDSAT/LC08/C02/T1_L2","LANDSAT/LC09/C02/T1_L2"],"bands":["ST_B10","QA_PIXEL"],"units":"celsius","scene_cloud_lt":40,"fallback_cloud_lt":null,"clear_score_gte":null,"reflectance_divisor":null,"qa_mask_bits":[3,4],"st_multiplier":0.00341802,"st_offset_kelvin":149.0,"celsius_subtract":273.15,"composite":"scale_then_median","mask_negative_ndvi":false,"reduction_scale_m":500,"best_effort":true,"tile_scale":null,"max_pixels":10000000000,"legacy_sources":[["gee_utils.py","d1f25fdca1c0562379d5f98002e9bea0a3c94d36f71df6bea45ec6bf94a9a175"],["routers/ndvi/compute.py","87b22a35e9dd610e6359f375de5dd9cfebd666bdcee28a22363179155b1febcd"],["routers/lst.py","748dcc2d6cc33108bdb7f07effadc2bcbb202e6436703fec68d7d0017004176f"]]}'::jsonb WHEN product='lst' AND month BETWEEN 1 AND 12 THEN '{"version":"lst-monthly-legacy-v1","product":"lst","frequency":"monthly","collections":["LANDSAT/LC08/C02/T1_L2","LANDSAT/LC09/C02/T1_L2"],"bands":["ST_B10","QA_PIXEL"],"units":"celsius","scene_cloud_lt":40,"fallback_cloud_lt":null,"clear_score_gte":null,"reflectance_divisor":null,"qa_mask_bits":[3,4],"st_multiplier":0.00341802,"st_offset_kelvin":149.0,"celsius_subtract":273.15,"composite":"scale_then_median","mask_negative_ndvi":false,"reduction_scale_m":500,"best_effort":true,"tile_scale":null,"max_pixels":10000000000,"legacy_sources":[["gee_utils.py","d1f25fdca1c0562379d5f98002e9bea0a3c94d36f71df6bea45ec6bf94a9a175"],["routers/ndvi/compute.py","87b22a35e9dd610e6359f375de5dd9cfebd666bdcee28a22363179155b1febcd"],["routers/lst.py","748dcc2d6cc33108bdb7f07effadc2bcbb202e6436703fec68d7d0017004176f"]]}'::jsonb END $f$;
CREATE FUNCTION gis.gee_live_canonical(v jsonb) RETURNS text
LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog,gis AS $f$
DECLARE result text;
BEGIN
 CASE jsonb_typeof(v)
 WHEN 'object' THEN SELECT '{'||COALESCE(string_agg(to_jsonb(key)::text||':'||gis.gee_live_canonical(value),',' ORDER BY key COLLATE "C"),'')||'}' INTO result FROM jsonb_each(v);
 WHEN 'array' THEN SELECT '['||COALESCE(string_agg(gis.gee_live_canonical(value),',' ORDER BY ord),'')||']' INTO result FROM jsonb_array_elements(v) WITH ORDINALITY a(value,ord);
 WHEN 'number' THEN result:=(v#>>'{}')::numeric::text;
  IF position('.' in result)>0 THEN result:=rtrim(rtrim(result,'0'),'.'); END IF;
  IF (v#>>'{}')::numeric=0 THEN result:='0'; END IF;
 ELSE result:=v::text;
 END CASE;
 RETURN result;
END $f$;
CREATE FUNCTION gis.gee_live_geometry(v jsonb) RETURNS void
LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog,gis AS $f$
DECLARE polygons jsonb; polygon jsonb; ring jsonb; point jsonb; count_points integer:=0;
BEGIN
 PERFORM gis.keys(v,ARRAY['type','coordinates']);
 IF NOT v ?& ARRAY['type','coordinates'] OR v->>'type' IS NULL OR v->>'type' NOT IN ('Polygon','MultiPolygon')
 OR jsonb_typeof(v->'coordinates') IS DISTINCT FROM 'array' THEN RAISE EXCEPTION 'GIS_GEE_LIVE_GEOMETRY_INVALID'; END IF;
 polygons:=CASE WHEN v->>'type'='Polygon' THEN jsonb_build_array(v->'coordinates') ELSE v->'coordinates' END;
 IF jsonb_array_length(polygons) NOT BETWEEN 1 AND 10000 THEN RAISE EXCEPTION 'GIS_GEE_LIVE_GEOMETRY_INVALID'; END IF;
 FOR polygon IN SELECT * FROM jsonb_array_elements(polygons) LOOP
  IF jsonb_typeof(polygon) IS DISTINCT FROM 'array' OR jsonb_array_length(polygon)=0 THEN RAISE EXCEPTION 'GIS_GEE_LIVE_GEOMETRY_INVALID'; END IF;
  FOR ring IN SELECT * FROM jsonb_array_elements(polygon) LOOP
   IF jsonb_typeof(ring) IS DISTINCT FROM 'array' OR jsonb_array_length(ring)<4 OR ring->0 IS DISTINCT FROM ring->(jsonb_array_length(ring)-1) THEN RAISE EXCEPTION 'GIS_GEE_LIVE_GEOMETRY_INVALID'; END IF;
   FOR point IN SELECT * FROM jsonb_array_elements(ring) LOOP
    count_points:=count_points+1;
    IF count_points>200000 OR jsonb_typeof(point) IS DISTINCT FROM 'array' OR jsonb_array_length(point)<>2
    OR jsonb_typeof(point->0) IS DISTINCT FROM 'number' OR jsonb_typeof(point->1) IS DISTINCT FROM 'number'
    OR (point->>0)::numeric NOT BETWEEN -180 AND 180 OR (point->>1)::numeric NOT BETWEEN -90 AND 90
    OR to_jsonb((point->>0)::double precision) IS DISTINCT FROM point->0
    OR to_jsonb((point->>1)::double precision) IS DISTINCT FROM point->1
    THEN RAISE EXCEPTION 'GIS_GEE_LIVE_GEOMETRY_INVALID'; END IF;
   END LOOP;
  END LOOP;
 END LOOP;
END $f$;
CREATE FUNCTION gis.validate_gee_live_case() RETURNS trigger
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
 OR r->>'execution' IS DISTINCT FROM 'injected' OR r->'input_revision' IS DISTINCT FROM '1'::jsonb
 OR r->>'product' IS NULL OR r->>'product' NOT IN ('ndvi','lst')
 OR COALESCE(r->>'request_id','') !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
 OR COALESCE(p->>'project_id','') !~ '^[a-z][a-z0-9-]{4,28}[a-z0-9]$'
 OR COALESCE(p->>'project_number','') !~ '^[0-9]{6,30}$'
 OR COALESCE(p->>'principal','') !~ '^[a-z0-9-]+@[a-z][a-z0-9-]+[.]iam[.]gserviceaccount[.]com$'
 OR p->>'principal' NOT LIKE '%@'||(p->>'project_id')||'.iam.gserviceaccount.com'
 OR p->>'readiness' IS DISTINCT FROM 'not_verified'
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
 RETURN NEW;
END $f$;
CREATE TRIGGER validate_input BEFORE INSERT ON gis.gee_live_inputs FOR EACH ROW EXECUTE FUNCTION gis.validate_gee_live_case();

CREATE FUNCTION gis.gee_live_manifest(p_input uuid) RETURNS jsonb
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
 SELECT jsonb_build_object('schema_version',7,'provider','gee_live_v2','execution','injected','input_id',c.id,
  'semantic_request_sha256',c.value->>'request_sha256','geometry_sha256',c.value->>'geometry_sha256',
  'method_version',c.value->'request'->>'method_version') FROM gis.gee_live_inputs c WHERE c.id=p_input
$f$;
ALTER FUNCTION gis.manifest_hash(jsonb) RENAME TO a64b_previous_manifest_hash;
CREATE FUNCTION gis.manifest_hash(p_manifest jsonb) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
BEGIN
 IF p_manifest->'schema_version' IS DISTINCT FROM '7'::jsonb THEN RETURN gis.a64b_previous_manifest_hash(p_manifest); END IF;
 IF p_manifest IS DISTINCT FROM gis.gee_live_manifest((p_manifest->>'input_id')::uuid) OR p_manifest IS NULL THEN
  RAISE EXCEPTION 'GIS_GEE_LIVE_MANIFEST_INVALID'; END IF;
 RETURN encode(sha256(convert_to(p_manifest::text,'UTF8')),'hex');
END $f$;
ALTER FUNCTION gis.edition_protocol(uuid) RENAME TO a64b_previous_edition_protocol;
CREATE FUNCTION gis.edition_protocol(p_edition uuid) RETURNS text
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
 SELECT CASE WHEN e.manifest->'schema_version'='7'::jsonb THEN
  CASE WHEN EXISTS(SELECT 1 FROM gis.gee_live_requests q WHERE q.edition_id=e.id) THEN 'gee_live_v2' ELSE 'unsupported' END
  ELSE gis.a64b_previous_edition_protocol(p_edition) END FROM gis.editions e WHERE e.id=p_edition
$f$;
ALTER FUNCTION gis.eligible(uuid,uuid) RENAME TO a64b_previous_eligible;
CREATE FUNCTION gis.eligible(p_edition uuid,p_dataset uuid) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
 SELECT CASE WHEN EXISTS(SELECT 1 FROM gis.editions WHERE id=p_edition AND manifest->'schema_version'='7'::jsonb)
  THEN false ELSE gis.a64b_previous_eligible(p_edition,p_dataset) END
$f$;
ALTER TABLE gis.jobs DROP CONSTRAINT jobs_kind_check;
ALTER TABLE gis.jobs ADD CONSTRAINT jobs_kind_check CHECK(kind IN ('validate_synthetic_edition','validate_ldd_edition','process_offline_edition','validate_geotiff_edition','prepare_ldd_edition','prepare_geotiff_edition','process_gee_mock_edition','process_gee_live_edition'));
ALTER TABLE gis.jobs DROP CONSTRAINT jobs_validator_version_check;
ALTER TABLE gis.jobs ADD CONSTRAINT jobs_validator_version_check CHECK(validator_version IN ('synthetic-v1','ldd-local-v1','gee-offline-v1','geotiff-local-v1','ldd-prepare-v1','geotiff-prepare-v1','gee-contract-mock-v1','gee-live-v2'));
ALTER TABLE gis.results DROP CONSTRAINT results_provider_check;
ALTER TABLE gis.results ADD CONSTRAINT results_provider_check CHECK(provider IN ('synthetic','local_ldd','offline_processing','local_geotiff','local_ldd_prepare','local_geotiff_prepare','gee_contract_mock','gee_live_v2'));

CREATE FUNCTION gis.gee_live_claim_packet(p_job uuid) RETURNS jsonb
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
 SELECT jsonb_build_object('request_id',q.id,'request',c.value->'request','geometry',c.value->'geometry',
   'semantic_request_sha256',c.value->>'request_sha256') FROM gis.gee_live_requests q JOIN gis.gee_live_inputs c ON c.id=q.input_id WHERE q.job_id=p_job
$f$;
-- REPORT: no synthetic expected-output comparison. Trusted JWT + independent
-- identity/scientific invariants authorize only explicitly injected observations.
CREATE FUNCTION gis.validate_gee_live_report(p_report jsonb,p_edition gis.editions,p_job gis.jobs) RETURNS void
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
 OR c->>'execution' IS DISTINCT FROM 'injected' OR c->'synthetic' IS DISTINCT FROM 'true'::jsonb
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

CREATE FUNCTION gis.gee_live_record_candidate(p_job uuid,p_result uuid,p_worker uuid) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
BEGIN
 INSERT INTO gis.gee_live_candidates(result_id,job_id,request_id,dataset_id,edition_id,input_revision,input_hash,
 semantic_request_sha256,output_sha256,worker_id,attempt_no,lease_token,output)
 SELECT p_result,j.id,q.id,e.dataset_id,e.id,j.input_revision,j.input_hash,c.value->>'request_sha256',
 r.report->'output'->>'output_sha256',p_worker,j.attempt_count,j.lease_token,r.report->'output'
 FROM gis.jobs j JOIN gis.editions e ON e.id=j.edition_id JOIN gis.gee_live_requests q ON q.job_id=j.id
 JOIN gis.gee_live_inputs c ON c.id=q.input_id JOIN gis.results r ON r.id=p_result AND r.job_id=j.id WHERE j.id=p_job;
 IF NOT FOUND THEN RAISE EXCEPTION 'GIS_GEE_LIVE_REQUEST_MISSING'; END IF;
END $f$;
CREATE FUNCTION gis.gee_live_command(p_actor uuid,p_request_id uuid,p_operation text,p_payload jsonb,p_backend_injected boolean) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE c gis.gee_live_inputs%ROWTYPE; q gis.gee_live_requests%ROWTYPE; d gis.datasets%ROWTYPE;
 e gis.editions%ROWTYPE; j gis.jobs%ROWTYPE; receipt gis.receipts%ROWTYPE; h text; body jsonb; m jsonb;
BEGIN
 PERFORM gis.authorize(p_actor,false);
 IF p_backend_injected IS DISTINCT FROM true OR p_operation IS DISTINCT FROM 'create' THEN RAISE EXCEPTION 'GIS_GEE_LIVE_DISABLED'; END IF;
 PERFORM gis.keys(p_payload,ARRAY['input_id']);
 IF p_request_id IS NULL OR NOT p_payload ? 'input_id' THEN RAISE EXCEPTION 'GIS_REQUEST_ID_REQUIRED'; END IF;
 h:=encode(sha256(convert_to(p_payload::text,'UTF8')),'hex');
 PERFORM pg_advisory_xact_lock(hashtextextended(p_actor::text||':'||p_request_id::text,0));
 SELECT * INTO receipt FROM gis.receipts WHERE actor_id=p_actor AND request_id=p_request_id;
 IF FOUND THEN
  IF receipt.operation<>'gee_live.create' OR receipt.payload_hash<>h THEN RAISE EXCEPTION 'GIS_IDEMPOTENCY_CONFLICT'; END IF;
  RETURN jsonb_build_object('status',receipt.status,'body',receipt.body,'replayed',true);
 END IF;
 SELECT * INTO c FROM gis.gee_live_inputs WHERE id=(p_payload->>'input_id')::uuid;
 IF NOT FOUND THEN RAISE EXCEPTION 'GIS_GEE_LIVE_CASE_REQUIRED'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('gee-mock-case:'||c.id::text,0));
 SELECT * INTO q FROM gis.gee_live_requests WHERE input_id=c.id;
 IF NOT FOUND THEN
  PERFORM pg_advisory_xact_lock(hashtextextended('gis-processing-dataset:'||(c.value->'request'->'scope'->>'province')||':'||(c.value->'request'->'period'->>'year')||':'||(c.value->'request'->'period'->>'month')||':'||(c.value->'request'->>'product'),0));
  INSERT INTO gis.datasets(province,data_year,month,kind,purpose,title,created_by)
   VALUES(c.value->'request'->'scope'->>'province',(c.value->'request'->'period'->>'year')::integer,
    (c.value->'request'->'period'->>'month')::integer,'geotiff',c.value->'request'->>'product','GEE Live foundation (injected, not publishable)',p_actor)
   ON CONFLICT(province,data_year,month,kind,purpose) DO NOTHING;
  SELECT * INTO d FROM gis.datasets WHERE province=c.value->'request'->'scope'->>'province'
   AND data_year=(c.value->'request'->'period'->>'year')::integer AND month=(c.value->'request'->'period'->>'month')::integer
   AND kind='geotiff' AND purpose=c.value->'request'->>'product' FOR NO KEY UPDATE;
  m:=gis.gee_live_manifest(c.id);
  INSERT INTO gis.editions(dataset_id,manifest,input_hash,created_by) VALUES(d.id,m,gis.manifest_hash(m),p_actor) RETURNING * INTO e;
  INSERT INTO gis.jobs(edition_id,kind,validator_version,input_revision,input_hash,requested_by)
   VALUES(e.id,'process_gee_live_edition','gee-live-v2',e.input_revision,e.input_hash,p_actor) RETURNING * INTO j;
  INSERT INTO gis.gee_live_requests(input_id,dataset_id,edition_id,job_id,requested_by)
   VALUES(c.id,d.id,e.id,j.id,p_actor) RETURNING * INTO q;
  UPDATE gis.editions SET state='validating' WHERE id=e.id;
 END IF;
 body:=jsonb_build_object('request_id',q.id,'job_id',q.job_id,'edition_id',q.edition_id,'dataset_id',q.dataset_id,
   'execution','injected','live_enabled',false,'publishable',false);
 INSERT INTO gis.receipts(actor_id,request_id,operation,payload_hash,status,body) VALUES(p_actor,p_request_id,'gee_live.create',h,202,body);
 INSERT INTO gis.audit(actor_id,operation,dataset_id,edition_id,job_id,detail) VALUES(p_actor,'gee_live.create',q.dataset_id,q.edition_id,q.job_id,jsonb_build_object('input_id',c.id,'execution','injected'));
 RETURN jsonb_build_object('status',202,'body',body,'replayed',false);
END $f$;

CREATE FUNCTION gis.gee_live_subject() RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE c jsonb;
BEGIN
 PERFORM gis.assert_environment();
 IF session_user<>'authenticator' OR current_setting('role',true)<>'gis_gee_live_worker' THEN RAISE EXCEPTION 'GIS_GEE_LIVE_IDENTITY_REQUIRED' USING ERRCODE='42501'; END IF;
 c:=NULLIF(current_setting('request.jwt.claims',true),'')::jsonb;
 IF c->>'role' IS DISTINCT FROM 'gis_gee_live_worker' OR c->>'iss' IS DISTINCT FROM 'http://127.0.0.1:55421/auth/v1'
 OR COALESCE(c->>'sub','') !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' THEN
  RAISE EXCEPTION 'GIS_GEE_LIVE_IDENTITY_REQUIRED' USING ERRCODE='42501'; END IF;
 RETURN (c->>'sub')::uuid;
END $f$;
CREATE FUNCTION public.gis_gee_live_worker(p_action text,p_payload jsonb DEFAULT '{}') RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE subject uuid; e gis.editions%ROWTYPE; j gis.jobs%ROWTYPE; a gis.attempts%ROWTYPE; r gis.results%ROWTYPE;
BEGIN
 subject:=gis.gee_live_subject();
 PERFORM gis.keys(p_payload,CASE p_action WHEN 'claim' THEN ARRAY[]::text[] WHEN 'recover' THEN ARRAY[]::text[]
  WHEN 'heartbeat' THEN ARRAY['job_id','lease_token','progress'] WHEN 'complete' THEN ARRAY['job_id','lease_token','report']
  WHEN 'fail' THEN ARRAY['job_id','lease_token','report','error_code'] ELSE ARRAY[]::text[] END);
 IF p_action='recover' THEN RETURN gis.queue_protocol_kind(p_action,p_payload,'gee_live_v2'); END IF;
 IF p_action='complete' THEN
  SELECT ed.* INTO e FROM gis.editions ed JOIN gis.jobs q ON q.edition_id=ed.id WHERE q.id=(p_payload->>'job_id')::uuid FOR UPDATE OF ed;
  SELECT * INTO j FROM gis.jobs WHERE id=(p_payload->>'job_id')::uuid FOR UPDATE;
  IF j.state='succeeded' AND gis.edition_protocol(e.id)='gee_live_v2' THEN
   SELECT * INTO a FROM gis.attempts WHERE job_id=j.id AND attempt_no=j.attempt_count;
   SELECT * INTO r FROM gis.results WHERE job_id=j.id;
   IF a.worker_id IS DISTINCT FROM subject OR a.lease_token IS DISTINCT FROM (p_payload->>'lease_token')::uuid
    OR r.report IS DISTINCT FROM p_payload->'report' THEN RAISE EXCEPTION 'GIS_STALE_LEASE'; END IF;
   RETURN jsonb_build_object('job_id',j.id,'state','succeeded','result_id',r.id,'replayed',true);
  END IF;
 END IF;
 RETURN gis.queue_protocol_kind(p_action,p_payload||jsonb_build_object('worker_id',subject),'gee_live_v2');
END $f$;
CREATE FUNCTION public.gis_gee_live_readiness() RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE subject uuid;
BEGIN
 subject:=gis.gee_live_subject();
 IF NOT EXISTS(SELECT 1 FROM gis.schema_migrations WHERE version=44) THEN RAISE EXCEPTION 'GIS_GEE_LIVE_NOT_READY'; END IF;
 RETURN (SELECT jsonb_build_object('subject',subject,'worker_role','gis_gee_live_worker','database_name',database_name,
  'cluster_name',cluster_name,'runtime_instance',runtime_instance,'baseline_fingerprint',baseline_fingerprint,
  'protocol','gee_live_v2','execution','injected','live_enabled',false,'contract_version','2.0.0-a6.4b') FROM gis.environment WHERE singleton);
END $f$;
CREATE FUNCTION gis.check_gee_live_catalog() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE jid uuid; ids uuid[]; j gis.jobs%ROWTYPE; e gis.editions%ROWTYPE; q gis.gee_live_requests%ROWTYPE;
 c gis.gee_live_inputs%ROWTYPE; a gis.attempts%ROWTYPE; r gis.results%ROWTYPE; candidate gis.gee_live_candidates%ROWTYPE;
BEGIN
 IF TG_TABLE_NAME='editions' THEN SELECT array_agg(id) INTO ids FROM gis.jobs WHERE edition_id=NEW.id AND kind='process_gee_live_edition';
 ELSIF TG_TABLE_NAME='jobs' THEN ids:=ARRAY[NEW.id]; ELSE ids:=ARRAY[NEW.job_id]; END IF;
 FOREACH jid IN ARRAY COALESCE(ids,ARRAY[]::uuid[]) LOOP
  SELECT * INTO j FROM gis.jobs WHERE id=jid;
  IF j.kind<>'process_gee_live_edition' THEN CONTINUE; END IF;
  SELECT * INTO e FROM gis.editions WHERE id=j.edition_id;
  SELECT * INTO q FROM gis.gee_live_requests WHERE job_id=j.id;
  SELECT * INTO c FROM gis.gee_live_inputs WHERE id=q.input_id;
  IF q.id IS NULL OR q.edition_id<>e.id OR q.dataset_id<>e.dataset_id OR e.manifest IS DISTINCT FROM gis.gee_live_manifest(c.id)
   OR e.input_hash<>gis.manifest_hash(e.manifest) OR e.input_revision<>1 OR j.input_hash<>e.input_hash OR j.input_revision<>1
   OR j.validator_version<>'gee-live-v2' OR e.state NOT IN ('draft','validating') OR e.validated_result_id IS NOT NULL
   OR EXISTS(SELECT 1 FROM gis.datasets WHERE active_edition_id=e.id) THEN RAISE EXCEPTION 'GIS_GEE_LIVE_CATALOG_INVARIANT'; END IF;
  SELECT * INTO candidate FROM gis.gee_live_candidates WHERE job_id=j.id;
  IF j.state='succeeded' THEN
   SELECT * INTO a FROM gis.attempts WHERE job_id=j.id AND attempt_no=j.attempt_count;
   SELECT * INTO r FROM gis.results WHERE job_id=j.id;
   PERFORM gis.validate_gee_live_report(r.report,e,j);
   IF candidate.result_id IS NULL OR candidate.result_id<>r.id OR candidate.request_id<>q.id OR candidate.edition_id<>e.id
    OR candidate.dataset_id<>e.dataset_id OR candidate.input_hash<>j.input_hash OR candidate.input_revision<>j.input_revision
    OR candidate.semantic_request_sha256 IS DISTINCT FROM c.value->>'request_sha256'
    OR candidate.output_sha256 IS DISTINCT FROM r.report->'output'->>'output_sha256' OR candidate.output IS DISTINCT FROM r.report->'output'
    OR candidate.worker_id<>a.worker_id OR candidate.attempt_no<>a.attempt_no OR candidate.lease_token<>a.lease_token
    OR a.state<>'succeeded' OR a.validation_report IS DISTINCT FROM r.report OR r.provider<>'gee_live_v2'
    OR r.report->'valid' IS DISTINCT FROM 'true'::jsonb THEN RAISE EXCEPTION 'GIS_GEE_LIVE_CANDIDATE_INVARIANT'; END IF;
  ELSIF candidate.result_id IS NOT NULL THEN RAISE EXCEPTION 'GIS_GEE_LIVE_PREMATURE_CANDIDATE'; END IF;
 END LOOP;
 RETURN NULL;
END $f$;
DO $triggers$ DECLARE t text; BEGIN
 FOREACH t IN ARRAY ARRAY['editions','jobs','attempts','results','gee_live_requests','gee_live_candidates'] LOOP
  EXECUTE format('CREATE CONSTRAINT TRIGGER gee_live_integrity AFTER INSERT OR UPDATE ON gis.%I DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION gis.check_gee_live_catalog()',t);
 END LOOP;
END $triggers$;

CREATE OR REPLACE FUNCTION gis.queue_protocol_kind(p_action text,p_payload jsonb,p_protocol text) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE j gis.jobs%ROWTYPE; e gis.editions%ROWTYPE; candidate record;
 worker uuid; token uuid; jid uuid; eid uuid; rid uuid; v_now timestamptz;
 progress_value integer; report_value jsonb; code text; next_state text; n integer:=0;
 p_native boolean:=p_protocol<>'v1'; u gis.ldd_uploads%ROWTYPE; ldd_dataset gis.datasets%ROWTYPE; processing_request gis.processing_requests%ROWTYPE; geo gis.geotiff_uploads%ROWTYPE; geo_dataset gis.datasets%ROWTYPE;
BEGIN
 PERFORM gis.assert_environment();
 IF p_protocol NOT IN ('v1','v2','ldd','gee_offline','geotiff','gee_contract_mock','gee_live_v2') OR p_protocol IS NULL THEN RAISE EXCEPTION 'GIS_WORKER_PROTOCOL_MISMATCH'; END IF;
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
         VALUES(CASE WHEN p_protocol='gee_live_v2' THEN 'gee_live.'||p_action WHEN p_protocol='gee_contract_mock' THEN 'gee_mock.claim' WHEN p_protocol='geotiff' THEN 'geotiff.claim' WHEN p_protocol='gee_offline' THEN 'processing.claim' WHEN p_protocol='ldd' THEN 'ldd.claim' ELSE 'worker_v2.claim' END,e.dataset_id,e.id,j.id,jsonb_build_object('worker_id',worker,'attempt',j.attempt_count));
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
       VALUES(CASE WHEN p_protocol='gee_live_v2' THEN 'gee_live.'||p_action WHEN p_protocol='gee_contract_mock' THEN 'gee_mock.recover' WHEN p_protocol='geotiff' THEN 'geotiff.recover' WHEN p_protocol='gee_offline' THEN 'processing.recover' WHEN p_protocol='ldd' THEN 'ldd.recover' WHEN p_native THEN 'worker_v2.recover' ELSE 'worker.recover' END,e.dataset_id,e.id,j.id,
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
     IF p_protocol='gee_live_v2' THEN PERFORM gis.validate_gee_live_report(report_value,e,j);
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
       VALUES(j.id,e.id,j.input_revision,j.input_hash,j.validator_version,j.attempt_count,token,true,report_value,CASE WHEN p_protocol='gee_live_v2' THEN 'gee_live_v2' WHEN p_protocol='gee_contract_mock' THEN 'gee_contract_mock' WHEN p_protocol='geotiff' THEN 'local_geotiff' WHEN p_protocol='gee_offline' THEN 'offline_processing' WHEN p_protocol='ldd' THEN 'local_ldd' ELSE 'synthetic' END) RETURNING id INTO rid;
     IF p_protocol IN ('gee_offline','geotiff','gee_contract_mock','gee_live_v2') THEN
       UPDATE gis.editions SET state='draft',validated_result_id=NULL WHERE id=e.id;
     ELSE
       UPDATE gis.editions SET state='validated',validated_result_id=rid WHERE id=e.id;
     END IF;
     IF p_protocol='gee_live_v2' THEN PERFORM gis.gee_live_record_candidate(j.id,rid,worker); END IF;
     IF p_protocol='gee_contract_mock' THEN PERFORM gis.gee_mock_record_candidate(j.id,rid,worker); END IF;
     UPDATE gis.jobs SET state='succeeded',worker_id=NULL,lease_token=NULL,lease_until=NULL,progress=100,finished_at=v_now WHERE id=j.id;
     UPDATE gis.attempts SET state='succeeded',progress=100,finished_at=v_now WHERE job_id=j.id AND attempt_no=j.attempt_count AND lease_token=token;
     INSERT INTO gis.audit(operation,dataset_id,edition_id,job_id,detail)
       VALUES(CASE WHEN p_protocol='gee_live_v2' THEN 'gee_live.'||p_action WHEN p_protocol='gee_contract_mock' THEN 'gee_mock.complete' WHEN p_protocol='geotiff' THEN 'geotiff.complete' WHEN p_protocol='gee_offline' THEN 'processing.complete' WHEN p_protocol='ldd' THEN 'ldd.complete' WHEN p_native THEN 'worker_v2.complete' ELSE 'worker.complete' END,e.dataset_id,e.id,j.id,
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
     VALUES(CASE WHEN p_protocol='gee_live_v2' THEN 'gee_live.'||p_action WHEN p_protocol='gee_contract_mock' THEN 'gee_mock.fail' WHEN p_protocol='geotiff' THEN 'geotiff.fail' WHEN p_protocol='gee_offline' THEN 'processing.fail' WHEN p_protocol='ldd' THEN 'ldd.fail' WHEN p_native THEN 'worker_v2.fail' ELSE 'worker.fail' END,e.dataset_id,e.id,j.id,
       jsonb_build_object('attempt',j.attempt_count,'error_code',code,'state',next_state));
   RETURN CASE WHEN p_native THEN jsonb_build_object('job_id',j.id,'state',next_state,'error_code',code)
     ELSE jsonb_build_object('job_id',j.id,'state',next_state) END;
 END IF;
 RAISE EXCEPTION 'GIS_UNKNOWN_WORKER_ACTION';
END $f$;


DO $acl$ DECLARE f record; BEGIN
 FOR f IN SELECT p.oid::regprocedure::text AS signature FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
 WHERE (n.nspname='gis' AND (p.proname LIKE '%gee_live%' OR p.proname LIKE 'a64b_previous_%'
 OR p.proname IN ('manifest_hash','edition_protocol','eligible','queue_protocol_kind')))
 OR (n.nspname='public' AND p.proname LIKE 'gis_gee_live_%') LOOP
 EXECUTE format('REVOKE ALL ON FUNCTION %s FROM PUBLIC,anon,authenticated,service_role,gis_worker,gis_native_worker,gis_gee_mock_worker,gis_gee_live_worker',f.signature);
 END LOOP;
END $acl$;
GRANT EXECUTE ON FUNCTION public.gis_gee_live_worker(text,jsonb),public.gis_gee_live_readiness() TO gis_gee_live_worker;
REVOKE CREATE ON SCHEMA public FROM gis_owner;
RESET ROLE;
NOTIFY pgrst,'reload schema';
