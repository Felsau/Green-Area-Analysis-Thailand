-- Step1 feasibility provisioning only. Not migration031; no ledger changes.
-- The operator runner owns BEGIN/GUCs/COMMIT and attests the exact local stack.
SET LOCAL ROLE gis_owner;
SELECT gis.assert_environment();
DO $guard$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM gis.environment WHERE singleton
   AND runtime_instance=current_setting('gis.runtime_instance',true)
   AND baseline_fingerprint=current_setting('gis.baseline_fingerprint',true))
   OR NOT EXISTS(SELECT 1 FROM gis.schema_migrations WHERE version=30
     AND sha256='6e7cc972d648fe717539c63131f752440c79446a5ffcbe8608b232cd63a4914f') THEN
  RAISE EXCEPTION 'T3_LOCAL_T2_IDENTITY_REQUIRED'; END IF;
END $guard$;
RESET ROLE;

DO $role$
DECLARE r record;
BEGIN
 SELECT * INTO r FROM pg_roles WHERE rolname='gis_native_worker';
 IF FOUND THEN
  IF r.rolsuper OR r.rolbypassrls OR r.rolcanlogin OR r.rolcreatedb OR r.rolcreaterole
   OR r.rolreplication OR r.rolinherit
   OR shobj_description(r.oid,'pg_authid') IS DISTINCT FROM 'gis-t3-native-worker-v1'
   OR EXISTS(SELECT 1 FROM pg_auth_members m JOIN pg_roles a ON a.oid=m.member
      WHERE (m.roleid=r.oid AND a.rolname NOT IN ('postgres','authenticator')) OR m.member=r.oid) THEN
   RAISE EXCEPTION 'T3_WORKER_ROLE_COLLISION'; END IF;
 ELSE
  CREATE ROLE gis_native_worker NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB
    NOCREATEROLE NOREPLICATION NOINHERIT;
  COMMENT ON ROLE gis_native_worker IS 'gis-t3-native-worker-v1';
 END IF;
 IF to_regprocedure('public.gis_identity_probe_t3()') IS NOT NULL THEN
  RAISE EXCEPTION 'T3_IDENTITY_PROBE_ALREADY_EXISTS'; END IF;
END $role$;

GRANT gis_native_worker TO authenticator WITH INHERIT FALSE, SET TRUE;
GRANT USAGE ON SCHEMA public TO gis_native_worker;

CREATE FUNCTION public.gis_identity_probe_t3() RETURNS jsonb
LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog AS $probe$
DECLARE claims jsonb;
BEGIN
 IF current_database()<>'postgres' OR current_setting('cluster_name')<>'green-area-gis-t0'
    OR current_user<>'gis_native_worker' OR session_user<>'authenticator' THEN
   RAISE EXCEPTION 'T3_REAL_WORKER_JWT_REQUIRED' USING ERRCODE='42501'; END IF;
 claims:=NULLIF(current_setting('request.jwt.claims',true),'')::jsonb;
 IF claims->>'role' IS DISTINCT FROM 'gis_native_worker'
    OR claims->>'sub' IS NULL THEN
   RAISE EXCEPTION 'T3_REAL_WORKER_JWT_REQUIRED' USING ERRCODE='42501'; END IF;
 RETURN jsonb_build_object('sql_role',current_user,'session_role',session_user,
   'subject',(claims->>'sub')::uuid,'jwt_role',claims->>'role',
   'database_name',current_database(),'cluster_name',current_setting('cluster_name'),
   'superuser',(SELECT rolsuper FROM pg_roles WHERE rolname=current_user),
   'bypass_rls',(SELECT rolbypassrls FROM pg_roles WHERE rolname=current_user),
   'can_create_role',(SELECT rolcreaterole FROM pg_roles WHERE rolname=current_user),
   'can_create_database',(SELECT rolcreatedb FROM pg_roles WHERE rolname=current_user),
   'owner_member',pg_has_role(current_user,'gis_owner','MEMBER'),
   'service_member',pg_has_role(current_user,'service_role','MEMBER'),
   'legacy_worker_member',pg_has_role(current_user,'gis_worker','MEMBER'));
END $probe$;
COMMENT ON FUNCTION public.gis_identity_probe_t3() IS 'gis-t3-native-probe-v1';
REVOKE ALL ON FUNCTION public.gis_identity_probe_t3()
  FROM PUBLIC,anon,authenticated,service_role,gis_worker;
GRANT EXECUTE ON FUNCTION public.gis_identity_probe_t3() TO gis_native_worker;
NOTIFY pgrst,'reload schema';
