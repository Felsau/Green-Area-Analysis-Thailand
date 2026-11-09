-- 051 LDD validation reports may name a second boundary asset.
-- Migration 034 accepted one boundary_sha256, the GADM asset (province_boundaries.json). The policy-v2
-- validator now reads province_boundaries_ldd.json: the province layer shipped in the LDD package for the
-- 24 provinces that supplied one, the same GADM outline for the rest. A report may name either asset.
-- Any other hash is still refused, and every other rule of the previous validator (the 034 rules, the
-- 049 declarations and the 050 audit object) applies unchanged: the previous function is called with the
-- hash it expects, and the stored report keeps the hash it carried.
-- Nothing here changes what passes validation, prepare or publication.
-- The attested operator supplies BEGIN/runtime proof and the INSERT-only ledger entry.
DO $guard$ BEGIN
 IF current_database() NOT IN ('postgres','gis_t1_upgrade') OR NOT gis.target_ok()
 OR NOT EXISTS(SELECT 1 FROM gis.schema_migrations WHERE version=50 AND sha256='87a09b59ddeae481a0f927ebde641fa915260837bc82729fd8effcb026bac893')
 OR EXISTS(SELECT 1 FROM gis.schema_migrations WHERE version>=51)
 OR NOT EXISTS(SELECT 1 FROM gis.environment WHERE singleton AND NOT activation_enabled
 AND runtime_instance=current_setting('gis.runtime_instance',true) AND baseline_fingerprint=current_setting('gis.baseline_fingerprint',true))
 THEN RAISE EXCEPTION 'GIS_LOCAL_BASELINE_050_REQUIRED';END IF;
END $guard$;
SET LOCAL ROLE gis_owner;
SELECT gis.assert_environment();

ALTER FUNCTION gis.validate_ldd_report(jsonb,gis.editions,gis.jobs) RENAME TO u051_previous_validate_ldd_report;
CREATE FUNCTION gis.validate_ldd_report(p_report jsonb,p_edition gis.editions,p_job gis.jobs) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
BEGIN
 IF jsonb_typeof(p_report)='object' AND p_report->>'boundary_sha256'='1b6cf62b8f43504078c51c9ca3e94f6fffe56c2ca1b3765674d5aa2d7c62e1ac' THEN
  PERFORM gis.u051_previous_validate_ldd_report(
   jsonb_set(p_report,'{boundary_sha256}',to_jsonb('ac2b28255f22861ab644bf083fa40f28dd9da1294648d4b01cfc6f9cdc156a21'::text)),p_edition,p_job);
 ELSE
  PERFORM gis.u051_previous_validate_ldd_report(p_report,p_edition,p_job);
 END IF;
END $f$;

DO $acl$ DECLARE f record;BEGIN
 FOR f IN SELECT p.oid::regprocedure AS sig FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
 WHERE n.nspname='gis' AND p.proname IN ('validate_ldd_report','u051_previous_validate_ldd_report') LOOP
 EXECUTE format('REVOKE ALL ON FUNCTION %s FROM PUBLIC,anon,authenticated,service_role,gis_worker,gis_native_worker,gis_gee_mock_worker,gis_gee_live_worker,gis_gee_safety_worker,gis_gee_transport_recorder,gis_gee_https_worker,gis_gee_https_recorder',f.sig);
 END LOOP;
END $acl$;
RESET ROLE;
NOTIFY pgrst,'reload schema';
