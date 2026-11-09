-- 050 Validation reports for LDD uploads may carry a closed `audit` object: policy version,
-- outcome, field mapping, per-parcel outcome counts, boundary counts, and bounded samples of
-- unknown codes and geometry repairs. Reports without it stay valid, so stored results and
-- older workers keep working. Nothing here changes what passes validation, prepare or
-- publication: a Review Required edition remains not usable.
-- The attested operator supplies BEGIN/runtime proof and the INSERT-only ledger entry.
DO $guard$ BEGIN
 IF current_database() NOT IN ('postgres','gis_t1_upgrade') OR NOT gis.target_ok()
 OR NOT EXISTS(SELECT 1 FROM gis.schema_migrations WHERE version=49 AND sha256='f3cb090958ce86be8d0f05628b4a58f5aa5cf236d900d89ed409eb2dbebc31bb')
 OR EXISTS(SELECT 1 FROM gis.schema_migrations WHERE version>=50)
 OR NOT EXISTS(SELECT 1 FROM gis.environment WHERE singleton AND NOT activation_enabled
 AND runtime_instance=current_setting('gis.runtime_instance',true) AND baseline_fingerprint=current_setting('gis.baseline_fingerprint',true))
 THEN RAISE EXCEPTION 'GIS_LOCAL_BASELINE_049_REQUIRED';END IF;
END $guard$;
SET LOCAL ROLE gis_owner;
SELECT gis.assert_environment();

CREATE FUNCTION gis.validate_ldd_audit(p_audit jsonb,p_report jsonb) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE item jsonb; k text; v jsonb; outcome text; total numeric:=0;
 review_codes text[]:=ARRAY['UNKNOWN_CODE_REVIEW_REQUIRED','BOUNDARY_OUTSIDE_REVIEW_REQUIRED','BOUNDARY_OUTSIDE_AREA_REVIEW_REQUIRED','AREA_DECLARED_MISMATCH_REVIEW_REQUIRED','GEOMETRY_REPAIR_LIMIT_REVIEW_REQUIRED'];
BEGIN
 IF jsonb_typeof(p_audit) IS DISTINCT FROM 'object' THEN RAISE EXCEPTION 'GIS_LDD_REPORT_INVALID'; END IF;
 PERFORM gis.keys(p_audit,ARRAY['policy_version','outcome','field_profile','field_mapping','declared_area_units','feature_outcomes','boundary','unknown_samples','repairs','repairs_total']);
 IF NOT p_audit ?& ARRAY['policy_version','outcome','field_profile','field_mapping','declared_area_units','feature_outcomes','boundary','unknown_samples','repairs','repairs_total']
   OR jsonb_typeof(p_audit->'policy_version') IS DISTINCT FROM 'string' OR p_audit->>'policy_version' !~ '^[a-z0-9-]{1,40}$'
   OR COALESCE(p_audit->>'outcome','') NOT IN ('accepted','accepted_with_warnings','review_required','rejected')
   OR (p_audit->'field_profile'<>'null'::jsonb AND COALESCE(p_audit->>'field_profile','') !~ '^[a-z0-9-]{1,40}$')
   OR (p_audit->'declared_area_units'<>'null'::jsonb AND p_audit->>'declared_area_units' IS DISTINCT FROM 'm2') THEN RAISE EXCEPTION 'GIS_LDD_REPORT_INVALID'; END IF;
 IF p_audit->'field_mapping'<>'null'::jsonb THEN
   IF jsonb_typeof(p_audit->'field_mapping') IS DISTINCT FROM 'object' THEN RAISE EXCEPTION 'GIS_LDD_REPORT_INVALID'; END IF;
   PERFORM gis.keys(p_audit->'field_mapping',ARRAY['main_code','lu_code','declared_area']);
   FOR k,v IN SELECT key,value FROM jsonb_each(p_audit->'field_mapping') LOOP
     IF jsonb_typeof(v) IS DISTINCT FROM 'string' OR length(v#>>'{}') NOT BETWEEN 1 AND 40 THEN RAISE EXCEPTION 'GIS_LDD_REPORT_INVALID'; END IF;
   END LOOP;
 END IF;
 IF jsonb_typeof(p_audit->'feature_outcomes') IS DISTINCT FROM 'object' OR jsonb_typeof(p_audit->'boundary') IS DISTINCT FROM 'object'
   OR jsonb_typeof(p_audit->'unknown_samples') IS DISTINCT FROM 'array' OR jsonb_array_length(p_audit->'unknown_samples')>10
   OR jsonb_typeof(p_audit->'repairs') IS DISTINCT FROM 'array' OR jsonb_array_length(p_audit->'repairs')>20
   OR jsonb_typeof(p_audit->'repairs_total') IS DISTINCT FROM 'number' OR COALESCE(p_audit->>'repairs_total','') !~ '^[0-9]{1,9}$'
   OR (p_audit->>'repairs_total')::numeric<jsonb_array_length(p_audit->'repairs') THEN RAISE EXCEPTION 'GIS_LDD_REPORT_INVALID'; END IF;
 PERFORM gis.keys(p_audit->'feature_outcomes',ARRAY['accepted','accepted_with_warnings','review_required','rejected']);
 IF NOT (p_audit->'feature_outcomes') ?& ARRAY['accepted','accepted_with_warnings','review_required','rejected'] THEN RAISE EXCEPTION 'GIS_LDD_REPORT_INVALID'; END IF;
 FOR k,v IN SELECT key,value FROM jsonb_each(p_audit->'feature_outcomes') LOOP
   IF jsonb_typeof(v) IS DISTINCT FROM 'number' OR COALESCE(v#>>'{}','') !~ '^[0-9]{1,9}$' THEN RAISE EXCEPTION 'GIS_LDD_REPORT_INVALID'; END IF;
   total:=total+(v#>>'{}')::numeric;
 END LOOP;
 PERFORM gis.keys(p_audit->'boundary',ARRAY['minor','review','fatal','outside_area_m2']);
 IF NOT (p_audit->'boundary') ?& ARRAY['minor','review','fatal','outside_area_m2'] THEN RAISE EXCEPTION 'GIS_LDD_REPORT_INVALID'; END IF;
 FOR k,v IN SELECT key,value FROM jsonb_each(p_audit->'boundary') LOOP
   IF jsonb_typeof(v) IS DISTINCT FROM 'number' OR (v#>>'{}')::numeric NOT BETWEEN 0 AND 1e12
     OR (k<>'outside_area_m2' AND v#>>'{}' !~ '^[0-9]{1,9}$') THEN RAISE EXCEPTION 'GIS_LDD_REPORT_INVALID'; END IF;
 END LOOP;
 FOR item IN SELECT x FROM jsonb_array_elements(p_audit->'unknown_samples') x LOOP
   IF jsonb_typeof(item) IS DISTINCT FROM 'object' THEN RAISE EXCEPTION 'GIS_LDD_REPORT_INVALID'; END IF;
   PERFORM gis.keys(item,ARRAY['value','main','reason','count','area_m2']);
   IF NOT item ?& ARRAY['value','main','reason','count','area_m2']
     OR jsonb_typeof(item->'value') IS DISTINCT FROM 'string' OR length(item->>'value')>40
     OR jsonb_typeof(item->'main') IS DISTINCT FROM 'string' OR length(item->>'main')>40
     OR jsonb_typeof(item->'reason') IS DISTINCT FROM 'string' OR item->>'reason' !~ '^[A-Z][A-Z0-9_]{0,59}$'
     OR jsonb_typeof(item->'count') IS DISTINCT FROM 'number' OR COALESCE(item->>'count','') !~ '^[1-9][0-9]{0,8}$'
     OR jsonb_typeof(item->'area_m2') IS DISTINCT FROM 'number' OR (item->>'area_m2')::numeric NOT BETWEEN 0 AND 1e12 THEN RAISE EXCEPTION 'GIS_LDD_REPORT_INVALID'; END IF;
 END LOOP;
 FOR item IN SELECT x FROM jsonb_array_elements(p_audit->'repairs') x LOOP
   IF jsonb_typeof(item) IS DISTINCT FROM 'object' THEN RAISE EXCEPTION 'GIS_LDD_REPORT_INVALID'; END IF;
   PERFORM gis.keys(item,ARRAY['feature','reason','area_before_m2','area_after_m2','type_before','type_after']);
   IF NOT item ?& ARRAY['feature','reason','area_before_m2','area_after_m2','type_before','type_after']
     OR jsonb_typeof(item->'feature') IS DISTINCT FROM 'number' OR COALESCE(item->>'feature','') !~ '^[0-9]{1,9}$'
     OR jsonb_typeof(item->'reason') IS DISTINCT FROM 'string' OR length(item->>'reason')>40
     OR jsonb_typeof(item->'area_before_m2') IS DISTINCT FROM 'number' OR (item->>'area_before_m2')::numeric NOT BETWEEN 0 AND 1e12
     OR jsonb_typeof(item->'area_after_m2') IS DISTINCT FROM 'number' OR (item->>'area_after_m2')::numeric NOT BETWEEN 0 AND 1e12
     OR COALESCE(item->>'type_before','') !~ '^[A-Za-z]{1,40}$' OR COALESCE(item->>'type_after','') !~ '^[A-Za-z]{1,40}$' THEN RAISE EXCEPTION 'GIS_LDD_REPORT_INVALID'; END IF;
 END LOOP;
 -- The outcome must agree with the report it describes.
 outcome:=p_audit->>'outcome';
 IF p_report->'valid'='true'::jsonb THEN
   IF outcome NOT IN ('accepted','accepted_with_warnings') OR p_audit->'field_mapping'='null'::jsonb
     OR total<>(p_report->'statistics'->>'feature_count')::numeric THEN RAISE EXCEPTION 'GIS_LDD_REPORT_INVALID'; END IF;
 ELSE
   IF outcome NOT IN ('review_required','rejected') OR total>(p_report->'statistics'->>'feature_count')::numeric
     OR (outcome='review_required' AND (jsonb_array_length(p_report->'errors')=0
       OR EXISTS(SELECT 1 FROM jsonb_array_elements(p_report->'errors') x WHERE NOT (x->>'code')=ANY(review_codes)))) THEN
     RAISE EXCEPTION 'GIS_LDD_REPORT_INVALID'; END IF;
 END IF;
END $f$;

ALTER FUNCTION gis.validate_ldd_report(jsonb,gis.editions,gis.jobs) RENAME TO u050_previous_validate_ldd_report;
-- Every existing rule still applies to the report without its audit object.
CREATE FUNCTION gis.validate_ldd_report(p_report jsonb,p_edition gis.editions,p_job gis.jobs) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
BEGIN
 PERFORM gis.u050_previous_validate_ldd_report(CASE WHEN jsonb_typeof(p_report)='object' THEN p_report-'audit' ELSE p_report END,p_edition,p_job);
 IF p_report ? 'audit' THEN PERFORM gis.validate_ldd_audit(p_report->'audit',p_report); END IF;
END $f$;

DO $acl$ DECLARE f record;BEGIN
 FOR f IN SELECT p.oid::regprocedure AS sig FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
 WHERE n.nspname='gis' AND p.proname IN ('validate_ldd_audit','validate_ldd_report','u050_previous_validate_ldd_report') LOOP
 EXECUTE format('REVOKE ALL ON FUNCTION %s FROM PUBLIC,anon,authenticated,service_role,gis_worker,gis_native_worker,gis_gee_mock_worker,gis_gee_live_worker,gis_gee_safety_worker,gis_gee_transport_recorder,gis_gee_https_worker,gis_gee_https_recorder',f.sig);
 END LOOP;
END $acl$;
RESET ROLE;
NOTIFY pgrst,'reload schema';
