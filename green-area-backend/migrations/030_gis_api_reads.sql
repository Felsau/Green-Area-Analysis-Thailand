-- T2 forward-only API read contract. The guarded runner owns transaction+ledger.
-- No legacy schema/data, GIS state, queue lease or applied migration is rewritten.
SET LOCAL ROLE gis_owner;
SELECT gis.assert_environment();
DO $guard$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM gis.environment e WHERE singleton
    AND e.runtime_instance=current_setting('gis.runtime_instance',true)
    AND e.baseline_fingerprint=current_setting('gis.baseline_fingerprint',true))
    OR (SELECT count(*) FROM gis.schema_migrations WHERE
       (version=27 AND sha256='bc879ca55e26a506e4b36c887dede928b07c619c42c94ddf69282362abd351e5')
       OR (version=28 AND sha256='fcf5d9530b516d93dda0fc2ea5b01158809aad237c1e90863d09bd324c9000d1')
       OR (version=29 AND sha256='7faf7bf6abbd4e52ab8389423c3c1876c94af459fe9d7c5d2a7710ffc0f236a5'))<>3 THEN
  RAISE EXCEPTION 'GIS_LOCAL_TARGET_REQUIRED'; END IF;
END $guard$;

-- The T1 ledger was intentionally capped at29. Extend through a forward DDL
-- change, never by modifying027 or editing any applied checksum/ledger row.
ALTER TABLE gis.schema_migrations DROP CONSTRAINT schema_migrations_version_check;
ALTER TABLE gis.schema_migrations ADD CONSTRAINT schema_migrations_version_check CHECK(version>=27);

CREATE FUNCTION gis.api_project(p_row jsonb,p_fields text[]) RETURNS jsonb
LANGUAGE sql IMMUTABLE SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
 SELECT COALESCE(jsonb_object_agg(key,value),'{}'::jsonb)
 FROM jsonb_each(p_row) WHERE key=ANY(p_fields)
$f$;

CREATE FUNCTION gis.api_read_row(p_kind text,p_row jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE fields text[]; result_value jsonb; checks_value jsonb; fixture text; code text;
BEGIN
 fields:=CASE
  WHEN p_kind IN ('datasets','dataset') THEN ARRAY['id','province','data_year','month','kind','purpose','title','revision','active_edition_id','created_at']
  WHEN p_kind IN ('editions','edition') THEN ARRAY['id','dataset_id','cloned_from_id','state','input_revision','manifest','input_hash','validated_result_id','created_at']
  WHEN p_kind IN ('jobs','job') THEN ARRAY['id','edition_id','parent_job_id','kind','input_revision','input_hash','validator_version','state','attempt_count','available_at','progress','created_at','finished_at']
  WHEN p_kind='attempts' THEN ARRAY['id','job_id','attempt_no','state','progress','started_at','finished_at']
  WHEN p_kind='history' THEN ARRAY['id','operation','dataset_id','edition_id','job_id','reason','created_at']
  WHEN p_kind='officers' THEN ARRAY['id','user_id','created_at']
  WHEN p_kind='result' THEN ARRAY['id','job_id','edition_id','input_revision','input_hash','validator_version','attempt_no','provider','valid','created_at']
 END;
 IF fields IS NULL THEN RAISE EXCEPTION 'GIS_UNKNOWN_READ'; END IF;
 IF p_row IS NULL THEN RETURN NULL; END IF;
 result_value:=gis.api_project(p_row,fields);
 IF p_kind IN ('jobs','job','attempts') THEN
  code:=p_row->>'error_code';
  result_value:=result_value||jsonb_build_object('error_code',CASE
   WHEN code IN ('invalid_data','transient','attempts_exhausted','lease_expired') THEN code
   WHEN code IS NULL THEN NULL ELSE 'internal_error' END);
 ELSIF p_kind='history' THEN
  result_value:=result_value||jsonb_build_object('detail',gis.api_project(p_row->'detail',
   ARRAY['previous_edition_id','new_edition_id','result_id','attempt','terminal','error_code','state']));
 ELSIF p_kind='result' THEN
  -- Synthetic report shape only. Never return a raw exception, native-library
  -- log, provider credential, worker identity or opaque lease token.
  fixture:=p_row->'report'->>'fixture_id';
  IF NOT EXISTS(SELECT 1 FROM gis.synthetic_fixtures WHERE id=fixture) THEN fixture:=NULL; END IF;
  SELECT COALESCE(jsonb_agg(value ORDER BY ordinal),'[]'::jsonb) INTO checks_value
   FROM jsonb_array_elements(CASE WHEN jsonb_typeof(p_row->'report'->'checks')='array'
     THEN p_row->'report'->'checks' ELSE '[]'::jsonb END) WITH ORDINALITY AS c(value,ordinal)
   WHERE value IN ('"synthetic_fixture_match"'::jsonb,'"metadata_shape"'::jsonb,'"source_hash_match"'::jsonb,'"bounded_input"'::jsonb);
  result_value:=result_value||jsonb_build_object('report',jsonb_build_object(
   'valid',p_row->'valid','fixture_id',fixture,'checks',checks_value));
 END IF;
 RETURN result_value;
END $f$;

CREATE OR REPLACE FUNCTION gis.read(p_actor uuid,p_kind text,p_payload jsonb DEFAULT '{}') RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE rows_value jsonb; last_value jsonb; result_value jsonb; job_value jsonb;
 limit_value integer:=20; cursor_time timestamptz; cursor_id uuid; more boolean;
 province_value text; year_value integer; month_value integer; kind_value text; purpose_value text;
 dataset_value uuid; edition_value uuid; job_id_value uuid; state_value text; detail_id uuid;
 source_sql text; predicate_sql text; stamp_column text:='created_at'; id_column text:='id';
 allowed text[]; admin_value boolean; officer_value boolean; caps jsonb;
BEGIN
 PERFORM gis.assert_environment();
 IF p_kind='me' THEN
  PERFORM gis.keys(p_payload,ARRAY[]::text[]);
  SELECT role='admin' INTO admin_value FROM public.profiles WHERE id=p_actor;
  IF admin_value IS NULL THEN RAISE EXCEPTION 'GIS_FORBIDDEN' USING ERRCODE='42501'; END IF;
  officer_value:=EXISTS(SELECT 1 FROM gis.officers WHERE user_id=p_actor);
  caps:=CASE WHEN admin_value OR officer_value THEN jsonb_build_array('read_catalog','create_dataset','edit_draft','clone_edition','enqueue_validation','eligible_retry') ELSE '[]'::jsonb END;
  IF admin_value THEN caps:=caps||jsonb_build_array('grant_officer','revoke_officer','sandbox_activate','sandbox_withdraw','sandbox_rollback'); END IF;
  RETURN jsonb_build_object('admin',admin_value,'officer',officer_value,'capabilities',caps,
   'synthetic_only',true,'activation_enabled',(SELECT activation_enabled FROM gis.environment WHERE singleton));
 END IF;
 PERFORM gis.authorize(p_actor,p_kind='officers');
 allowed:=CASE p_kind
  WHEN 'provinces' THEN ARRAY[]::text[] WHEN 'fixtures' THEN ARRAY[]::text[]
  WHEN 'dataset' THEN ARRAY['id'] WHEN 'edition' THEN ARRAY['id'] WHEN 'job' THEN ARRAY['id'] WHEN 'result' THEN ARRAY['id']
  WHEN 'datasets' THEN ARRAY['limit','cursor','province','data_year','month','kind','purpose']
  WHEN 'editions' THEN ARRAY['limit','cursor','dataset_id','state']
  WHEN 'jobs' THEN ARRAY['limit','cursor','province','data_year','month','kind','purpose','dataset_id','edition_id','state']
  WHEN 'attempts' THEN ARRAY['limit','cursor','job_id'] WHEN 'history' THEN ARRAY['limit','cursor','edition_id']
  WHEN 'officers' THEN ARRAY['limit','cursor'] END;
 IF allowed IS NULL THEN RAISE EXCEPTION 'GIS_UNKNOWN_READ'; END IF;
 PERFORM gis.keys(p_payload,allowed);
 IF p_kind='provinces' THEN
  SELECT COALESCE(jsonb_agg(jsonb_build_object('name_en',name_en,'name_th',name_th,'region',region) ORDER BY name_en),'[]'::jsonb)
   INTO rows_value FROM public.provinces;
  RETURN jsonb_build_object('data',rows_value,'next_cursor',NULL,'has_more',false);
 ELSIF p_kind='fixtures' THEN
  SELECT COALESCE(jsonb_agg(to_jsonb(f) ORDER BY id),'[]'::jsonb) INTO rows_value FROM gis.synthetic_fixtures f;
  RETURN jsonb_build_object('data',rows_value,'next_cursor',NULL,'has_more',false);
 ELSIF p_kind IN ('dataset','edition','job','result') THEN
  IF jsonb_typeof(p_payload->'id') IS DISTINCT FROM 'string' THEN RAISE EXCEPTION 'GIS_INVALID_PAYLOAD'; END IF;
  detail_id:=(p_payload->>'id')::uuid;
  IF p_kind='dataset' THEN SELECT gis.api_read_row(p_kind,to_jsonb(t)) INTO rows_value FROM gis.datasets t WHERE id=detail_id;
  ELSIF p_kind='edition' THEN SELECT gis.api_read_row(p_kind,to_jsonb(t)) INTO rows_value FROM gis.editions t WHERE id=detail_id;
  ELSE
   SELECT gis.api_read_row('job',to_jsonb(t)) INTO job_value FROM gis.jobs t WHERE id=detail_id;
   IF job_value IS NULL THEN RAISE EXCEPTION 'GIS_NOT_FOUND'; END IF;
   SELECT gis.api_read_row('result',to_jsonb(r)) INTO result_value FROM gis.results r WHERE job_id=detail_id;
   IF p_kind='result' THEN RETURN jsonb_build_object('job_id',detail_id,'state',job_value->'state',
     'result',result_value,'error_code',job_value->'error_code'); END IF;
   rows_value:=job_value||jsonb_build_object('result',result_value);
  END IF;
  IF rows_value IS NULL THEN RAISE EXCEPTION 'GIS_NOT_FOUND'; END IF;
  RETURN rows_value;
 END IF;

 IF p_payload ? 'limit' THEN
  IF jsonb_typeof(p_payload->'limit') IS DISTINCT FROM 'number'
     OR COALESCE(p_payload->>'limit','') !~ '^[0-9]{1,3}$' THEN RAISE EXCEPTION 'GIS_INVALID_LIMIT'; END IF;
  limit_value:=(p_payload->>'limit')::integer;
 END IF;
 IF limit_value NOT BETWEEN 1 AND 100 THEN RAISE EXCEPTION 'GIS_INVALID_LIMIT'; END IF;
 IF p_payload ? 'cursor' AND p_payload->'cursor'<>'null'::jsonb THEN
  PERFORM gis.keys(p_payload->'cursor',ARRAY['created_at','id']);
  IF jsonb_typeof(p_payload->'cursor'->'created_at') IS DISTINCT FROM 'string'
    OR jsonb_typeof(p_payload->'cursor'->'id') IS DISTINCT FROM 'string'
    OR COALESCE(p_payload->'cursor'->>'created_at','') !~ '(Z|[+-][0-9]{2}:[0-9]{2})$' THEN RAISE EXCEPTION 'GIS_INVALID_CURSOR'; END IF;
  cursor_time:=(p_payload->'cursor'->>'created_at')::timestamptz;
  cursor_id:=(p_payload->'cursor'->>'id')::uuid;
 END IF;
 IF p_payload ? 'province' THEN
  IF jsonb_typeof(p_payload->'province') IS DISTINCT FROM 'string' OR length(btrim(p_payload->>'province')) NOT BETWEEN 1 AND 120 THEN
   RAISE EXCEPTION 'GIS_INVALID_FILTER'; END IF;
  province_value:=p_payload->>'province';
 END IF;
 IF p_payload ? 'data_year' THEN
  IF jsonb_typeof(p_payload->'data_year') IS DISTINCT FROM 'number' OR COALESCE(p_payload->>'data_year','') !~ '^[0-9]{4}$' THEN RAISE EXCEPTION 'GIS_INVALID_FILTER'; END IF;
  year_value:=(p_payload->>'data_year')::integer;
  IF year_value NOT BETWEEN 1980 AND extract(year FROM clock_timestamp())::integer+1 THEN RAISE EXCEPTION 'GIS_INVALID_FILTER'; END IF;
 END IF;
 IF p_payload ? 'month' THEN
  IF jsonb_typeof(p_payload->'month') IS DISTINCT FROM 'number' OR COALESCE(p_payload->>'month','') !~ '^[0-9]{1,2}$' THEN RAISE EXCEPTION 'GIS_INVALID_FILTER'; END IF;
  month_value:=(p_payload->>'month')::integer;
  IF month_value NOT BETWEEN 0 AND 12 THEN RAISE EXCEPTION 'GIS_INVALID_FILTER'; END IF;
 END IF;
 IF p_payload ? 'kind' THEN
  kind_value:=p_payload->>'kind';
  IF kind_value IS NULL OR kind_value NOT IN ('ldd_shapefile','geotiff') THEN RAISE EXCEPTION 'GIS_INVALID_FILTER'; END IF;
 END IF;
 IF p_payload ? 'purpose' THEN
  purpose_value:=p_payload->>'purpose';
  IF purpose_value IS NULL OR purpose_value NOT IN ('landuse','ndvi','lst') THEN RAISE EXCEPTION 'GIS_INVALID_FILTER'; END IF;
 END IF;
 IF (kind_value='ldd_shapefile' AND (purpose_value IN ('ndvi','lst') OR month_value<>0))
   OR (kind_value='geotiff' AND purpose_value='landuse') THEN RAISE EXCEPTION 'GIS_INVALID_FILTER'; END IF;
 dataset_value:=(p_payload->>'dataset_id')::uuid;
 edition_value:=(p_payload->>'edition_id')::uuid;
 job_id_value:=(p_payload->>'job_id')::uuid;
 state_value:=p_payload->>'state';
 IF p_payload ? 'state' AND (state_value IS NULL OR
   (p_kind='jobs' AND state_value NOT IN ('queued','running','succeeded','failed')) OR
   (p_kind='editions' AND state_value NOT IN ('draft','validating','validated','withdrawn'))) THEN RAISE EXCEPTION 'GIS_INVALID_FILTER'; END IF;
 IF p_kind='editions' THEN
  IF dataset_value IS NULL THEN RAISE EXCEPTION 'GIS_INVALID_PAYLOAD'; END IF;
  IF NOT EXISTS(SELECT 1 FROM gis.datasets WHERE id=dataset_value) THEN RAISE EXCEPTION 'GIS_NOT_FOUND'; END IF;
 ELSIF p_kind='history' THEN
  IF edition_value IS NULL THEN RAISE EXCEPTION 'GIS_INVALID_PAYLOAD'; END IF;
  IF NOT EXISTS(SELECT 1 FROM gis.editions WHERE id=edition_value) THEN RAISE EXCEPTION 'GIS_NOT_FOUND'; END IF;
 ELSIF p_kind='attempts' THEN
  IF job_id_value IS NULL THEN RAISE EXCEPTION 'GIS_INVALID_PAYLOAD'; END IF;
  IF NOT EXISTS(SELECT 1 FROM gis.jobs WHERE id=job_id_value) THEN RAISE EXCEPTION 'GIS_NOT_FOUND'; END IF;
 END IF;

 -- SQL fragments are an internal closed allowlist. All cursor/filter values are
 -- bound parameters; no caller input becomes an identifier or SQL expression.
 IF p_kind='datasets' THEN
  source_sql:='gis.datasets t';
  predicate_sql:='($4::text IS NULL OR t.province=$4) AND ($5::int IS NULL OR t.data_year=$5) AND ($6::int IS NULL OR t.month=$6) AND ($7::text IS NULL OR t.kind=$7) AND ($8::text IS NULL OR t.purpose=$8)';
 ELSIF p_kind='editions' THEN
  source_sql:='gis.editions t'; predicate_sql:='t.dataset_id=$9 AND ($11::text IS NULL OR t.state=$11)';
 ELSIF p_kind='jobs' THEN
  source_sql:='gis.jobs t JOIN gis.editions e ON e.id=t.edition_id JOIN gis.datasets d ON d.id=e.dataset_id';
  predicate_sql:='($4::text IS NULL OR d.province=$4) AND ($5::int IS NULL OR d.data_year=$5) AND ($6::int IS NULL OR d.month=$6) AND ($7::text IS NULL OR d.kind=$7) AND ($8::text IS NULL OR d.purpose=$8) AND ($9::uuid IS NULL OR d.id=$9) AND ($10::uuid IS NULL OR e.id=$10) AND ($11::text IS NULL OR t.state=$11)';
 ELSIF p_kind='attempts' THEN
  source_sql:='gis.attempts t'; predicate_sql:='t.job_id=$12'; stamp_column:='started_at';
 ELSIF p_kind='history' THEN
  source_sql:='gis.audit t'; predicate_sql:='t.edition_id=$10';
 ELSIF p_kind='officers' THEN
  source_sql:='gis.officers t'; predicate_sql:='true'; id_column:='user_id';
 END IF;
 EXECUTE format('SELECT COALESCE(jsonb_agg(gis.api_read_row($13,raw) ORDER BY stamp,id),''[]''::jsonb) FROM
  (SELECT to_jsonb(t)||jsonb_build_object(''id'',t.%I) AS raw,t.%I AS stamp,t.%I AS id FROM %s
   WHERE (%s) AND ($2::timestamptz IS NULL OR (t.%I,t.%I)>($2,$3::uuid)) ORDER BY t.%I,t.%I LIMIT $1) page',
   id_column,stamp_column,id_column,source_sql,predicate_sql,stamp_column,id_column,stamp_column,id_column)
 INTO rows_value USING limit_value+1,cursor_time,cursor_id,province_value,year_value,month_value,
  kind_value,purpose_value,dataset_value,edition_value,state_value,job_id_value,p_kind;
 more:=jsonb_array_length(rows_value)>limit_value;
 IF more THEN rows_value:=rows_value-limit_value; END IF;
 last_value:=rows_value->(jsonb_array_length(rows_value)-1);
 RETURN jsonb_build_object('data',rows_value,'has_more',more,'next_cursor',CASE WHEN more THEN
  jsonb_build_object('created_at',last_value->>stamp_column,'id',last_value->>'id') ELSE NULL END);
END $f$;

-- Match stable cursor order / parent filters without changing any legacy index.
CREATE INDEX gis_datasets_page ON gis.datasets(created_at,id);
CREATE INDEX gis_editions_parent_page ON gis.editions(dataset_id,created_at,id);
CREATE INDEX gis_jobs_page ON gis.jobs(created_at,id);
CREATE INDEX gis_attempts_parent_page ON gis.attempts(job_id,started_at,id);
CREATE INDEX gis_audit_edition_page ON gis.audit(edition_id,created_at,id);
CREATE INDEX gis_officers_page ON gis.officers(created_at,user_id);

REVOKE ALL ON FUNCTION gis.api_project(jsonb,text[]),gis.api_read_row(text,jsonb),gis.read(uuid,text,jsonb)
 FROM PUBLIC,anon,authenticated,service_role,gis_worker;
RESET ROLE;
GRANT CREATE ON SCHEMA public TO gis_owner;
SET LOCAL ROLE gis_owner;
CREATE FUNCTION public.gis_readiness() RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
BEGIN
 PERFORM gis.assert_environment();
 IF NOT EXISTS(SELECT 1 FROM gis.schema_migrations WHERE version=30) THEN
  RAISE EXCEPTION 'GIS_SCHEMA_NOT_READY'; END IF;
 RETURN (SELECT jsonb_build_object('runtime_instance',runtime_instance,'baseline_fingerprint',baseline_fingerprint,
  'database_name',current_database(),'cluster_name',current_setting('cluster_name'),'mode',mode,
  'activation_enabled',activation_enabled,'contract_version','1.1.0-t2',
  'migration_versions',(SELECT jsonb_agg(version ORDER BY version) FROM gis.schema_migrations))
  FROM gis.environment WHERE singleton);
END $f$;
REVOKE ALL ON FUNCTION public.gis_readiness() FROM PUBLIC,anon,authenticated,service_role,gis_worker;
GRANT EXECUTE ON FUNCTION public.gis_readiness() TO service_role;
RESET ROLE;
REVOKE CREATE ON SCHEMA public FROM gis_owner;
-- Notification is delivered only after the runner commits DDL+version30 ledger.
NOTIFY pgrst,'reload schema';
