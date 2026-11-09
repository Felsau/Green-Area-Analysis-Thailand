-- TEST ONLY. Stand-ins for what a Supabase project already provides, so that the
-- installer can be exercised on a plain postgres:17 container. Run this as the
-- container's superuser. Never run this against a real project.
--
-- Create `postgres` first, as a non-superuser with CREATEROLE. Its other attributes
-- and memberships below were read from the pinned supabase/postgres image
-- (dev/gis_local/images.lock.json), not from the real project.
BEGIN;
CREATE ROLE anon NOLOGIN;
CREATE ROLE authenticated NOLOGIN;
CREATE ROLE service_role NOLOGIN BYPASSRLS;
CREATE ROLE authenticator LOGIN NOINHERIT;
GRANT anon,authenticated,service_role TO authenticator;
ALTER ROLE postgres BYPASSRLS;
GRANT pg_read_all_data,pg_monitor,pg_signal_backend,pg_create_subscription,
 authenticator,anon,authenticated,service_role TO postgres;

CREATE ROLE supabase_auth_admin NOLOGIN;
CREATE SCHEMA auth AUTHORIZATION supabase_auth_admin;
CREATE TABLE auth.users(
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 email text,
 raw_user_meta_data jsonb);
ALTER TABLE auth.users OWNER TO supabase_auth_admin;
CREATE FUNCTION auth.uid() RETURNS uuid LANGUAGE sql STABLE AS
 $$ SELECT NULLIF(current_setting('request.jwt.claim.sub',true),'')::uuid $$;
ALTER FUNCTION auth.uid() OWNER TO supabase_auth_admin;
GRANT USAGE ON SCHEMA auth TO postgres,anon,authenticated,service_role;
GRANT ALL ON auth.users TO postgres;
GRANT EXECUTE ON FUNCTION auth.uid() TO postgres,anon,authenticated,service_role;
COMMIT;
