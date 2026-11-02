-- T1 local/synthetic foundation. The guarded runner owns BEGIN/ledger/COMMIT.
-- No legacy migration is replayed and no legacy cache data is changed here.
DO $guard$
DECLARE r record; n text;
BEGIN
  IF current_database() NOT IN ('postgres','gis_t1_upgrade')
     OR current_setting('cluster_name') <> 'green-area-gis-t0'
     OR current_setting('gis.runtime_instance',true) !~ '^[0-9a-f]{32}$'
     OR current_setting('gis.baseline_fingerprint',true) !~ '^[0-9a-f]{64}$'
     OR current_setting('gis.runtime_instance',true) IS NULL
     OR current_setting('gis.baseline_fingerprint',true) IS NULL
     OR current_setting('server_version_num')::int < 170000 THEN
    RAISE EXCEPTION 'GIS_LOCAL_TARGET_REQUIRED';
  END IF;
  IF to_regclass('public.profiles') IS NULL OR to_regclass('public.provinces') IS NULL
     OR to_regclass('auth.users') IS NULL THEN RAISE EXCEPTION 'GIS_BASELINE_REQUIRED'; END IF;
  FOREACH n IN ARRAY ARRAY['gis_owner','gis_worker'] LOOP
    SELECT * INTO r FROM pg_roles WHERE rolname=n;
    IF FOUND THEN
      IF r.rolsuper OR r.rolbypassrls OR r.rolcanlogin OR r.rolcreatedb OR r.rolcreaterole
         OR r.rolreplication OR r.rolinherit
         OR shobj_description(r.oid,'pg_authid') IS DISTINCT FROM 'gis-t1-owned-v1'
         OR EXISTS(SELECT 1 FROM pg_auth_members m JOIN pg_roles a ON a.oid=m.member
                   WHERE (m.roleid=r.oid AND a.rolname<>'postgres') OR m.member=r.oid) THEN
        RAISE EXCEPTION 'GIS_ROLE_COLLISION';
      END IF;
    ELSE
      EXECUTE format('CREATE ROLE %I NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOREPLICATION NOINHERIT',n);
      EXECUTE format('COMMENT ON ROLE %I IS %L',n,'gis-t1-owned-v1');
    END IF;
  END LOOP;
  IF EXISTS(SELECT 1 FROM pg_namespace WHERE nspname='gis') THEN
    RAISE EXCEPTION 'GIS_SCHEMA_ALREADY_EXISTS';
  END IF;
END $guard$;

-- The local non-superuser migrator may SET ROLE; application roles never may.
GRANT gis_owner TO postgres WITH INHERIT FALSE, SET TRUE;
GRANT gis_worker TO postgres WITH INHERIT FALSE, SET TRUE;
CREATE SCHEMA gis AUTHORIZATION gis_owner;
REVOKE ALL ON SCHEMA gis FROM PUBLIC,anon,authenticated,service_role,gis_worker;
GRANT USAGE ON SCHEMA public TO gis_owner;
GRANT SELECT(id,role) ON public.profiles TO gis_owner;
GRANT SELECT(name_en,name_th,region) ON public.provinces TO gis_owner;
GRANT REFERENCES(id) ON public.profiles TO gis_owner;
GRANT REFERENCES(name_en) ON public.provinces TO gis_owner;
CREATE POLICY gis_owner_profiles_read ON public.profiles FOR SELECT TO gis_owner USING(true);
CREATE POLICY gis_owner_provinces_read ON public.provinces FOR SELECT TO gis_owner USING(true);
SET LOCAL ROLE gis_owner;
ALTER DEFAULT PRIVILEGES IN SCHEMA gis REVOKE ALL ON TABLES FROM PUBLIC,anon,authenticated,service_role,gis_worker;
ALTER DEFAULT PRIVILEGES IN SCHEMA gis REVOKE ALL ON SEQUENCES FROM PUBLIC,anon,authenticated,service_role,gis_worker;
ALTER DEFAULT PRIVILEGES IN SCHEMA gis REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC,anon,authenticated,service_role,gis_worker;

CREATE TABLE gis.schema_migrations(
 version integer PRIMARY KEY CHECK(version BETWEEN 27 AND 29),
 sha256 text NOT NULL CHECK(sha256 ~ '^[0-9a-f]{64}$'),
 applied_at timestamptz NOT NULL DEFAULT clock_timestamp());
CREATE TABLE gis.environment(
 singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton),
 runtime_instance text NOT NULL CHECK(runtime_instance ~ '^[0-9a-f]{32}$'),
 baseline_fingerprint text NOT NULL CHECK(baseline_fingerprint ~ '^[0-9a-f]{64}$'),
 database_name text NOT NULL CHECK(database_name IN ('postgres','gis_t1_upgrade')),
 cluster_name text NOT NULL CHECK(cluster_name='green-area-gis-t0'),
 mode text NOT NULL DEFAULT 'local_synthetic' CHECK(mode='local_synthetic'),
 activation_enabled boolean NOT NULL DEFAULT false);
INSERT INTO gis.environment(runtime_instance,baseline_fingerprint,database_name,cluster_name)
VALUES(current_setting('gis.runtime_instance'),current_setting('gis.baseline_fingerprint'),current_database(),current_setting('cluster_name'));
CREATE TABLE gis.officers(
 user_id uuid PRIMARY KEY REFERENCES public.profiles(id) ON DELETE CASCADE,
 granted_by uuid REFERENCES public.profiles(id) ON DELETE SET NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp());
CREATE TABLE gis.datasets(
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 province text NOT NULL REFERENCES public.provinces(name_en),
 data_year integer NOT NULL CHECK(data_year BETWEEN 1980 AND 2200),
 month integer NOT NULL CHECK(month BETWEEN 0 AND 12),
 kind text NOT NULL, purpose text NOT NULL,
 title text NOT NULL CHECK(length(title) BETWEEN 1 AND 200),
 revision integer NOT NULL DEFAULT 1 CHECK(revision>0),
 active_edition_id uuid,
 created_by uuid REFERENCES public.profiles(id) ON DELETE SET NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 CHECK((kind='ldd_shapefile' AND purpose='landuse' AND month=0)
    OR (kind='geotiff' AND purpose IN ('ndvi','lst'))),
 UNIQUE(province,data_year,month,kind,purpose));
CREATE TABLE gis.editions(
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 dataset_id uuid NOT NULL REFERENCES gis.datasets(id),
 cloned_from_id uuid REFERENCES gis.editions(id),
 state text NOT NULL DEFAULT 'draft' CHECK(state IN ('draft','validating','validated','withdrawn')),
 input_revision integer NOT NULL DEFAULT 1 CHECK(input_revision>0),
 manifest jsonb NOT NULL CHECK(jsonb_typeof(manifest)='object'),
 input_hash text NOT NULL CHECK(input_hash ~ '^[0-9a-f]{64}$'),
 validated_result_id uuid,
 created_by uuid REFERENCES public.profiles(id) ON DELETE SET NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 UNIQUE(id,dataset_id));
ALTER TABLE gis.datasets ADD CONSTRAINT dataset_active_same_dataset
 FOREIGN KEY(active_edition_id,id) REFERENCES gis.editions(id,dataset_id);
CREATE TABLE gis.audit(
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 actor_id uuid REFERENCES public.profiles(id) ON DELETE SET NULL,
 subject_id uuid REFERENCES public.profiles(id) ON DELETE SET NULL,
 operation text NOT NULL, dataset_id uuid REFERENCES gis.datasets(id),
 edition_id uuid REFERENCES gis.editions(id), job_id uuid,
 reason text CHECK(length(reason)<=500), detail jsonb NOT NULL DEFAULT '{}',
 created_at timestamptz NOT NULL DEFAULT clock_timestamp());
CREATE TABLE gis.receipts(
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 actor_id uuid REFERENCES public.profiles(id) ON DELETE SET NULL,
 request_id uuid NOT NULL, operation text NOT NULL, payload_hash text NOT NULL,
 status integer NOT NULL, body jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(), UNIQUE(actor_id,request_id));
CREATE TABLE gis.synthetic_fixtures(
 id text PRIMARY KEY,kind text NOT NULL,purpose text NOT NULL,manifest jsonb NOT NULL UNIQUE);
INSERT INTO gis.synthetic_fixtures(id,kind,purpose,manifest)
SELECT id,kind,purpose,
 jsonb_build_object('schema_version',1,'provider','synthetic','fixture_id',id,
 'sha256',encode(sha256(convert_to(id,'UTF8')),'hex'),'byte_size',octet_length(id),
 'provenance','gis-t1-fixture-v1','crs','EPSG:4326','data_kind',CASE WHEN kind='geotiff' THEN 'raster' ELSE 'polygon' END)
 || CASE WHEN kind='geotiff' THEN jsonb_build_object('bands',jsonb_build_array(purpose),'units',CASE purpose WHEN 'lst' THEN 'celsius' ELSE 'unitless' END,'nodata',-9999,'resolution',30)
         ELSE jsonb_build_object('attributes',jsonb_build_array('landuse_code')) END
FROM (VALUES('ndvi-valid-v1','geotiff','ndvi'),('lst-valid-v1','geotiff','lst'),
 ('ldd-valid-v1','ldd_shapefile','landuse'),('invalid-v1','geotiff','ndvi'),
 ('transient-v1','geotiff','ndvi')) f(id,kind,purpose);

CREATE FUNCTION gis.assert_environment() RETURNS void LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,gis AS $f$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM gis.environment WHERE singleton
   AND database_name=current_database() AND cluster_name=current_setting('cluster_name')
   AND runtime_instance ~ '^[0-9a-f]{32}$' AND baseline_fingerprint ~ '^[0-9a-f]{64}$'
   AND mode='local_synthetic') THEN RAISE EXCEPTION 'GIS_LOCAL_TARGET_REQUIRED'; END IF;
END $f$;
CREATE FUNCTION gis.authorize(p_actor uuid,p_admin boolean DEFAULT false) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE a boolean;
BEGIN
 PERFORM gis.assert_environment();
 PERFORM pg_advisory_xact_lock(hashtextextended('gis-auth:'||COALESCE(p_actor::text,''),0));
 SELECT role='admin' INTO a FROM public.profiles WHERE id=p_actor;
 IF a IS NULL OR (NOT a AND (p_admin OR NOT EXISTS(SELECT 1 FROM gis.officers WHERE user_id=p_actor))) THEN
   RAISE EXCEPTION 'GIS_FORBIDDEN' USING ERRCODE='42501'; END IF;
 RETURN a;
END $f$;
CREATE FUNCTION gis.keys(p_payload jsonb,p_keys text[]) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
BEGIN
 IF jsonb_typeof(p_payload) IS DISTINCT FROM 'object' OR octet_length(p_payload::text)>65536
    OR EXISTS(SELECT 1 FROM jsonb_object_keys(p_payload) k WHERE NOT k=ANY(p_keys)) THEN
   RAISE EXCEPTION 'GIS_INVALID_PAYLOAD'; END IF;
END $f$;
CREATE FUNCTION gis.manifest_hash(p_manifest jsonb) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
BEGIN
 PERFORM gis.keys(p_manifest,ARRAY['schema_version','provider','fixture_id','sha256','byte_size','provenance','crs','data_kind','bands','units','nodata','resolution','attributes']);
 IF p_manifest->>'schema_version' IS DISTINCT FROM '1'
    OR p_manifest->>'provider' NOT IN ('synthetic','real')
    OR p_manifest->>'provider' IS NULL
    OR COALESCE(p_manifest->>'sha256','') !~ '^[0-9a-f]{64}$'
    OR COALESCE(p_manifest->>'byte_size','') !~ '^[1-9][0-9]{0,8}$'
    OR COALESCE(p_manifest->>'provenance','') !~ '^[A-Za-z0-9 _.-]{1,100}$'
    OR COALESCE(p_manifest->>'crs','') !~ '^EPSG:[0-9]{4,6}$'
    OR COALESCE(p_manifest->>'data_kind','') NOT IN ('raster','polygon')
    OR p_manifest::text ~ '(https?://|file:|\\\\|\.\./)' THEN RAISE EXCEPTION 'GIS_INVALID_MANIFEST'; END IF;
 IF p_manifest->>'provider'='real' THEN
  IF p_manifest ? 'fixture_id' OR (p_manifest->>'data_kind'='raster' AND
      (jsonb_typeof(p_manifest->'bands') IS DISTINCT FROM 'array'
       OR jsonb_array_length(p_manifest->'bands') NOT BETWEEN 1 AND 8
       OR COALESCE(p_manifest->>'units','') NOT IN ('celsius','unitless','categories')
       OR jsonb_typeof(p_manifest->'nodata') IS DISTINCT FROM 'number'
       OR jsonb_typeof(p_manifest->'resolution') IS DISTINCT FROM 'number'))
    OR (p_manifest->>'data_kind'='polygon' AND jsonb_typeof(p_manifest->'attributes') IS DISTINCT FROM 'array') THEN
    RAISE EXCEPTION 'GIS_INVALID_MANIFEST'; END IF;
  IF EXISTS(SELECT 1 FROM jsonb_array_elements(COALESCE(p_manifest->'bands','[]')) value
      WHERE jsonb_typeof(value)<>'string' OR value#>>'{}' !~ '^[A-Za-z][A-Za-z0-9_]{0,39}$')
    OR EXISTS(SELECT 1 FROM jsonb_array_elements(COALESCE(p_manifest->'attributes','[]')) value
      WHERE jsonb_typeof(value)<>'string' OR value#>>'{}' !~ '^[A-Za-z][A-Za-z0-9_]{0,39}$')
    OR (p_manifest ? 'resolution' AND (p_manifest->>'resolution')::numeric NOT BETWEEN 0.001 AND 10000)
    OR (p_manifest ? 'nodata' AND abs((p_manifest->>'nodata')::numeric)>1e12)
    OR (p_manifest ? 'attributes' AND jsonb_array_length(p_manifest->'attributes')>30) THEN
    RAISE EXCEPTION 'GIS_INVALID_MANIFEST'; END IF;
 END IF;
 IF p_manifest->>'provider'='synthetic' AND NOT EXISTS(SELECT 1 FROM gis.synthetic_fixtures WHERE manifest=p_manifest) THEN
   RAISE EXCEPTION 'GIS_SYNTHETIC_MANIFEST_NOT_ALLOWLISTED'; END IF;
 RETURN encode(sha256(convert_to(p_manifest::text,'UTF8')),'hex');
END $f$;

DO $rls$
DECLARE t text;
BEGIN
 FOREACH t IN ARRAY ARRAY['schema_migrations','environment','officers','datasets','editions','audit','receipts','synthetic_fixtures'] LOOP
   EXECUTE format('ALTER TABLE gis.%I ENABLE ROW LEVEL SECURITY',t);
   EXECUTE format('ALTER TABLE gis.%I FORCE ROW LEVEL SECURITY',t);
   EXECUTE format('CREATE POLICY owner_access ON gis.%I TO gis_owner USING(true) WITH CHECK(true)',t);
 END LOOP;
END $rls$;
REVOKE ALL ON ALL TABLES IN SCHEMA gis FROM PUBLIC,anon,authenticated,service_role,gis_worker;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA gis FROM PUBLIC,anon,authenticated,service_role,gis_worker;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA gis FROM PUBLIC,anon,authenticated,service_role,gis_worker;
RESET ROLE;
