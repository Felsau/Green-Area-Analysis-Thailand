-- T3 forward-only correction for polymorphic trigger NEW record fields.
-- Migration 032 is applied/frozen. No rows, reports or prior ledger entries change.
SET LOCAL ROLE gis_owner;
SELECT gis.assert_environment();
DO $guard$
BEGIN
 IF current_database() NOT IN ('postgres','gis_t1_upgrade')
   OR NOT gis.target_ok()
   OR NOT EXISTS(SELECT 1 FROM gis.environment WHERE singleton
     AND runtime_instance=current_setting('gis.runtime_instance',true)
     AND baseline_fingerprint=current_setting('gis.baseline_fingerprint',true))
   OR NOT EXISTS(SELECT 1 FROM gis.schema_migrations WHERE version=32
     AND sha256='ef58eb7d864c0433f4393b0f52dbb6db00a91e8d3dd397742594d1d909660b7f')
   OR EXISTS(SELECT 1 FROM gis.schema_migrations WHERE version>=33) THEN
   RAISE EXCEPTION 'GIS_LOCAL_BASELINE_032_REQUIRED'; END IF;
END $guard$;

CREATE OR REPLACE FUNCTION gis.check_native_catalog() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE j gis.jobs%ROWTYPE; e gis.editions%ROWTYPE; a gis.attempts%ROWTYPE; r gis.results%ROWTYPE; jid uuid;
BEGIN
 IF TG_TABLE_NAME='editions' THEN
   FOR jid IN SELECT id FROM gis.jobs WHERE edition_id=NEW.id AND state='succeeded' LOOP
     SELECT * INTO j FROM gis.jobs WHERE id=jid;
     SELECT * INTO e FROM gis.editions WHERE id=j.edition_id;
     IF e.manifest->'schema_version'='2'::jsonb THEN
       SELECT * INTO a FROM gis.attempts WHERE job_id=j.id AND attempt_no=j.attempt_count;
       SELECT * INTO r FROM gis.results WHERE job_id=j.id;
       PERFORM gis.validate_native_report(a.validation_report,e.manifest,j.input_hash,j.input_revision);
       IF a.state<>'succeeded' OR r.report IS DISTINCT FROM a.validation_report OR a.validation_report->'valid'<>'true'::jsonb THEN
         RAISE EXCEPTION 'GIS_NATIVE_RESULT_INVARIANT'; END IF;
     END IF;
   END LOOP;
   RETURN NULL;
 END IF;
 -- Each statement references only fields available for its concrete relation.
 -- CASE/AND expressions can resolve missing fields before short-circuiting.
 IF TG_TABLE_NAME='jobs' THEN
   jid:=NEW.id;
 ELSE
   jid:=NEW.job_id;
 END IF;
 SELECT * INTO j FROM gis.jobs WHERE id=jid;
 SELECT * INTO e FROM gis.editions WHERE id=j.edition_id;
 IF e.manifest->'schema_version' IS DISTINCT FROM '2'::jsonb THEN RETURN NULL; END IF;
 IF j.state='succeeded' THEN
   SELECT * INTO a FROM gis.attempts WHERE job_id=j.id AND attempt_no=j.attempt_count;
   SELECT * INTO r FROM gis.results WHERE job_id=j.id;
   PERFORM gis.validate_native_report(a.validation_report,e.manifest,j.input_hash,j.input_revision);
   IF a.state<>'succeeded' OR r.report IS DISTINCT FROM a.validation_report OR a.validation_report->'valid'<>'true'::jsonb THEN
     RAISE EXCEPTION 'GIS_NATIVE_RESULT_INVARIANT'; END IF;
 ELSIF TG_TABLE_NAME='attempts' THEN
   IF NEW.state='failed' THEN
     PERFORM gis.validate_native_report(NEW.validation_report,e.manifest,j.input_hash,j.input_revision);
   END IF;
 END IF;
 RETURN NULL;
END $f$;
REVOKE ALL ON FUNCTION gis.check_native_catalog() FROM PUBLIC,anon,authenticated,service_role,gis_worker,gis_native_worker;
RESET ROLE;
NOTIFY pgrst,'reload schema';
