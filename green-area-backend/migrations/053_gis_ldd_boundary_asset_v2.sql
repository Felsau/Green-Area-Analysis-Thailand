-- 053 LDD validation reports may name the 41-province boundary asset.
-- province_boundaries_ldd.json is rebuilt from all 77 LDD packages: the province layer shipped in the package
-- for the 41 provinces that supply one (the 24 of 051 plus 17 northern provinces), the same GADM outline for
-- the other 36. 051 is left as applied (its sha256 is bound by the ledger and the approval records), so its
-- header still describes the 24-province asset; this header is the description of the current one.
-- A report naming the new asset is checked exactly as a report naming the 24-province asset: the previous
-- function is called with that hash, so every rule of 034/049/050/051 applies unchanged, and the stored report
-- keeps the hash it carried. The 24-province hash and the GADM hash are still accepted; any other is refused.
-- Nothing here changes what passes validation, prepare or publication.
-- The attested operator supplies BEGIN/runtime proof and the INSERT-only ledger entry.
DO $guard$ BEGIN
 IF current_database() NOT IN ('postgres','gis_t1_upgrade') OR NOT gis.target_ok()
 OR NOT EXISTS(SELECT 1 FROM gis.schema_migrations WHERE version=52 AND sha256='329ce1a52a47db9735a8fca99488e00f0881c0403a4878268f07c77f6f229875')
 OR EXISTS(SELECT 1 FROM gis.schema_migrations WHERE version>=53)
 OR NOT EXISTS(SELECT 1 FROM gis.environment WHERE singleton AND NOT activation_enabled
 AND runtime_instance=current_setting('gis.runtime_instance',true) AND baseline_fingerprint=current_setting('gis.baseline_fingerprint',true))
 THEN RAISE EXCEPTION 'GIS_LOCAL_BASELINE_052_REQUIRED';END IF;
END $guard$;
SET LOCAL ROLE gis_owner;
SELECT gis.assert_environment();

ALTER FUNCTION gis.validate_ldd_report(jsonb,gis.editions,gis.jobs) RENAME TO u053_previous_validate_ldd_report;
CREATE FUNCTION gis.validate_ldd_report(p_report jsonb,p_edition gis.editions,p_job gis.jobs) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
BEGIN
 IF jsonb_typeof(p_report)='object' AND p_report->>'boundary_sha256'='49473e7e59aeecfe4b3dff1c9b6ebc21ffe859fa76de47c46c45e1d55dae93a3' THEN
  PERFORM gis.u053_previous_validate_ldd_report(
   jsonb_set(p_report,'{boundary_sha256}',to_jsonb('1b6cf62b8f43504078c51c9ca3e94f6fffe56c2ca1b3765674d5aa2d7c62e1ac'::text)),p_edition,p_job);
 ELSE
  PERFORM gis.u053_previous_validate_ldd_report(p_report,p_edition,p_job);
 END IF;
END $f$;

DO $acl$ DECLARE f record;BEGIN
 FOR f IN SELECT p.oid::regprocedure AS sig FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
 WHERE n.nspname='gis' AND p.proname IN ('validate_ldd_report','u053_previous_validate_ldd_report') LOOP
 EXECUTE format('REVOKE ALL ON FUNCTION %s FROM PUBLIC,anon,authenticated,service_role,gis_worker,gis_native_worker,gis_gee_mock_worker,gis_gee_live_worker,gis_gee_safety_worker,gis_gee_transport_recorder,gis_gee_https_worker,gis_gee_https_recorder',f.sig);
 END LOOP;
END $acl$;
RESET ROLE;
NOTIFY pgrst,'reload schema';
