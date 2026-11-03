"""A1 SQL/ACL integration, rollback-only fixtures, no credentials or gate changes.

SET ROLE tests SQL privileges, not live JWT issuance. Existing upload validation
reports are reused; no file preparation, worker or new scientific run is claimed.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('a1_checks_operator', HERE / 'publication_local.py')
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)

HELPERS = r"""
CREATE TEMP TABLE a1_checks(name text,passed boolean);
GRANT SELECT,INSERT ON a1_checks TO gis_owner;
CREATE FUNCTION pg_temp.assert_ok(n text,v boolean) RETURNS void LANGUAGE plpgsql AS $t$
BEGIN IF v IS DISTINCT FROM true THEN RAISE EXCEPTION 'A1_ASSERT:%',n; END IF;
 INSERT INTO a1_checks VALUES(n,true); END $t$;
CREATE FUNCTION pg_temp.reject(n text,statement text,expected text) RETURNS void LANGUAGE plpgsql AS $t$
BEGIN
 BEGIN EXECUTE statement;
 EXCEPTION WHEN OTHERS THEN
   IF SQLERRM !~ expected THEN RAISE EXCEPTION 'A1_WRONG_REJECTION:%:%',n,SQLERRM; END IF;
   INSERT INTO a1_checks VALUES(n,true); RETURN;
 END;
 RAISE EXCEPTION 'A1_EXPECTED_REJECTION:%',n;
END $t$;
CREATE FUNCTION pg_temp.register(actor uuid,request uuid,payload jsonb) RETURNS jsonb LANGUAGE plpgsql AS $t$
DECLARE r jsonb; previous_role text:=current_setting('role');
BEGIN SET LOCAL ROLE service_role;
 r:=public.gis_publication_register(actor,request,payload); PERFORM set_config('role',previous_role,true); RETURN r; END $t$;
CREATE FUNCTION pg_temp.read_status(actor uuid,edition uuid,method text) RETURNS jsonb LANGUAGE plpgsql AS $t$
DECLARE r jsonb; previous_role text:=current_setting('role');
BEGIN SET LOCAL ROLE service_role;
 r:=public.gis_publication_read(actor,edition,method); PERFORM set_config('role',previous_role,true); RETURN r; END $t$;
CREATE TEMP TABLE a1_context(admin_id uuid,officer_id uuid,user_id uuid);
INSERT INTO a1_context VALUES(gen_random_uuid(),gen_random_uuid(),gen_random_uuid());
GRANT SELECT ON a1_context TO gis_owner;
INSERT INTO auth.users(id,email,raw_user_meta_data)
 SELECT id,'a1-'||id::text||'@example.invalid','{}'::jsonb FROM a1_context,
 LATERAL unnest(ARRAY[admin_id,officer_id,user_id]) id;
UPDATE public.profiles SET role='admin' WHERE id=(SELECT admin_id FROM a1_context);
SET LOCAL ROLE gis_owner;
INSERT INTO gis.officers(user_id,granted_by) SELECT officer_id,admin_id FROM a1_context;
"""

COMMON = r"""
SELECT pg_temp.assert_ok('gate_stays_closed',NOT (SELECT activation_enabled FROM gis.environment));
SELECT pg_temp.assert_ok('registry_owner_force_rls',EXISTS(SELECT 1 FROM pg_class c JOIN pg_roles r ON r.oid=c.relowner
 WHERE c.oid='gis.publication_artifacts'::regclass AND r.rolname='gis_owner' AND c.relrowsecurity AND c.relforcerowsecurity));
SELECT pg_temp.assert_ok('owner_only_policy',(SELECT count(*)=1 AND bool_and(roles=ARRAY['gis_owner']::name[] AND cmd='ALL'
 AND qual='true' AND with_check='true') FROM pg_policies WHERE schemaname='gis' AND tablename='publication_artifacts'));
SELECT pg_temp.assert_ok('readiness_independent_of_closed_gate',NOT gis.publication_ready(gen_random_uuid(),gen_random_uuid()));
SELECT pg_temp.assert_ok('old_eligible_not_redefined',pg_get_functiondef('gis.eligible(uuid,uuid)'::regprocedure) NOT LIKE '%publication%');
SELECT pg_temp.assert_ok('pointer_guard_after_existing_gate',
 (SELECT array_agg(tgname ORDER BY tgname)=ARRAY['immutable_row','publication_pointer_guard']::name[]
 FROM pg_trigger WHERE tgrelid='gis.datasets'::regclass AND NOT tgisinternal AND (tgtype & 2)=2));
DO $tests$
DECLARE role_name text; rpc text; f record;
BEGIN
 FOREACH role_name IN ARRAY ARRAY['anon','authenticated','service_role','gis_worker','gis_native_worker'] LOOP
  PERFORM pg_temp.assert_ok(role_name||'_no_direct_table',NOT has_table_privilege(role_name,'gis.publication_artifacts',
   'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER'));
  IF role_name<>'service_role' THEN
   FOREACH rpc IN ARRAY ARRAY['public.gis_publication_register(uuid,uuid,jsonb)','public.gis_publication_read(uuid,uuid,text)'] LOOP
    PERFORM pg_temp.assert_ok(role_name||'_no_rpc_'||rpc,NOT has_function_privilege(role_name,rpc,'EXECUTE'));
   END LOOP;
  END IF;
  PERFORM pg_temp.reject(role_name||'_actual_table_denied',format('SET LOCAL ROLE %I; SELECT count(*) FROM gis.publication_artifacts',role_name),'permission denied');
  IF role_name<>'service_role' THEN
   PERFORM pg_temp.reject(role_name||'_actual_rpc_denied',format('SET LOCAL ROLE %I; SELECT public.gis_publication_read(NULL,NULL,''v1'')',role_name),'permission denied');
  END IF;
 END LOOP;
 FOR f IN SELECT p.oid,p.proowner,p.prosecdef,p.proconfig FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
 WHERE n.nspname IN ('gis','public') AND p.proname LIKE '%publication%' LOOP
  PERFORM pg_temp.assert_ok('definer_boundary_'||f.oid,f.proowner='gis_owner'::regrole AND f.prosecdef
   AND f.proconfig=ARRAY['search_path=pg_catalog, gis']);
 END LOOP;
END $tests$;
SELECT pg_temp.reject('normal_user_denied',format('SELECT pg_temp.read_status(%L,NULL,''v1'')',user_id),'GIS_FORBIDDEN') FROM a1_context;
SELECT pg_temp.reject('officer_cannot_register',format('SELECT pg_temp.register(%L,gen_random_uuid(),''{}'')',officer_id),'GIS_FORBIDDEN') FROM a1_context;
SELECT pg_temp.reject('body_cannot_supply_authority',format('SELECT pg_temp.register(%L,gen_random_uuid(),''{"ready":true,"actor":"admin"}'')',admin_id),'GIS_INVALID_PAYLOAD') FROM a1_context;
SELECT pg_temp.reject('null_actor_denied','SELECT pg_temp.read_status(NULL,NULL,''v1'')','GIS_FORBIDDEN');
SELECT pg_temp.assert_ok('synthetic_not_publishable',NOT EXISTS(SELECT 1 FROM gis.editions e
 WHERE e.manifest->>'provider' IN ('synthetic','offline_synthetic') AND gis.publication_validation(e.id) IS NOT NULL));
"""

POSITIVE = r"""
CREATE TEMP TABLE a1_target AS
 SELECT e.id edition_id,e.dataset_id,d.revision dataset_revision,e.input_revision,
 gis.publication_validation(e.id) validation,gis.edition_protocol(e.id) protocol
 FROM gis.editions e JOIN gis.datasets d ON d.id=e.dataset_id
 WHERE gis.publication_validation(e.id) IS NOT NULL
 AND gis.edition_protocol(e.id) IN ('ldd','geotiff');
SELECT pg_temp.assert_ok('existing_ldd_validation_available',EXISTS(SELECT 1 FROM a1_target WHERE protocol='ldd'));
SELECT pg_temp.assert_ok('existing_geotiff_validation_available',EXISTS(SELECT 1 FROM a1_target WHERE protocol='geotiff'));
CREATE TEMP TABLE a1_payload AS SELECT t.*,gen_random_uuid() request_id,
 jsonb_build_object('edition_id',t.edition_id,'expected_dataset_revision',dataset_revision,
 'expected_input_revision',input_revision,'input_hash',validation->>'input_hash',
 'validation_result_id',validation->>'validation_result_id','source_sha256',validation->>'source_sha256',
 'artifact_kind',CASE protocol WHEN 'ldd' THEN 'ldd_summary' ELSE (validation->>'purpose')||'_summary' END,
 'artifact_sha256',repeat('a',64),'byte_size',100,'method_version','a1-test-v1','reason','Rollback-only synthetic declaration') payload
 FROM (SELECT DISTINCT ON(protocol) * FROM a1_target ORDER BY protocol,edition_id) t;
CREATE TEMP TABLE a1_registered(protocol text,reply jsonb);
INSERT INTO a1_registered SELECT protocol,pg_temp.register(admin_id,request_id,payload) FROM a1_payload CROSS JOIN a1_context;
DO $tests$
DECLARE x record; c a1_context%ROWTYPE; status jsonb; kind text; altered jsonb;
BEGIN
 SELECT * INTO c FROM a1_context;
 FOR x IN SELECT * FROM a1_payload LOOP
  status:=pg_temp.read_status(c.officer_id,x.edition_id,'a1-test-v1');
  PERFORM pg_temp.assert_ok(x.protocol||'_officer_can_read',status->'validation_valid'='true'::jsonb);
  PERFORM pg_temp.assert_ok(x.protocol||'_unprepared_not_ready',status->'ready_for_publication'='false'::jsonb
    AND status->'coverage_verified'='false'::jsonb AND status->'verification_available'='false'::jsonb
    AND status->'artifacts_complete'='false'::jsonb);
  PERFORM pg_temp.assert_ok(x.protocol||'_idempotent_replay',pg_temp.register(c.admin_id,x.request_id,x.payload)=
    (SELECT reply FROM a1_registered WHERE protocol=x.protocol));
  PERFORM pg_temp.reject(x.protocol||'_idempotency_conflict',format('SELECT pg_temp.register(%L,%L,%L)',c.admin_id,x.request_id,
    x.payload||'{"reason":"different request"}'),'GIS_IDEMPOTENCY_CONFLICT');
  PERFORM pg_temp.reject(x.protocol||'_duplicate_artifact',format('SELECT pg_temp.register(%L,gen_random_uuid(),%L)',c.admin_id,x.payload),'GIS_ARTIFACT_ALREADY_REGISTERED');
  PERFORM pg_temp.reject(x.protocol||'_stale_dataset_revision',format('SELECT pg_temp.register(%L,gen_random_uuid(),%L)',c.admin_id,
    x.payload||jsonb_build_object('expected_dataset_revision',x.dataset_revision+1)),'GIS_REVISION_CONFLICT');
  PERFORM pg_temp.reject(x.protocol||'_stale_input_revision',format('SELECT pg_temp.register(%L,gen_random_uuid(),%L)',c.admin_id,
    x.payload||jsonb_build_object('expected_input_revision',x.input_revision+1)),'GIS_REVISION_CONFLICT');
  PERFORM pg_temp.reject(x.protocol||'_wrong_input_hash',format('SELECT pg_temp.register(%L,gen_random_uuid(),%L)',c.admin_id,
    x.payload||jsonb_build_object('input_hash',repeat('0',64))),'GIS_ARTIFACT_INPUT_MISMATCH');
  PERFORM pg_temp.reject(x.protocol||'_wrong_source_hash',format('SELECT pg_temp.register(%L,gen_random_uuid(),%L)',c.admin_id,
    x.payload||jsonb_build_object('source_sha256',repeat('0',64))),'GIS_ARTIFACT_INPUT_MISMATCH');
  PERFORM pg_temp.reject(x.protocol||'_wrong_result',format('SELECT pg_temp.register(%L,gen_random_uuid(),%L)',c.admin_id,
    x.payload||jsonb_build_object('validation_result_id',gen_random_uuid())),'GIS_ARTIFACT_INPUT_MISMATCH');
  FOREACH kind IN ARRAY ARRAY['path','url','ready','coverage_verified','coverage_level','coverage_province'] LOOP
   PERFORM pg_temp.reject(x.protocol||'_rejects_'||kind,format('SELECT pg_temp.register(%L,gen_random_uuid(),%L)',c.admin_id,
    x.payload||jsonb_build_object(kind,'untrusted')),'GIS_INVALID_PAYLOAD');
  END LOOP;
  PERFORM pg_temp.reject(x.protocol||'_fractional_revision_rejected',format('SELECT pg_temp.register(%L,gen_random_uuid(),%L)',c.admin_id,
    x.payload||'{"expected_dataset_revision":1.5}'),'GIS_INVALID_PAYLOAD');
  PERFORM pg_temp.reject(x.protocol||'_wrong_artifact_kind',format('SELECT pg_temp.register(%L,gen_random_uuid(),%L)',c.admin_id,
    x.payload||'{"artifact_kind":"wrong"}'),'GIS_ARTIFACT_INPUT_MISMATCH');
  PERFORM pg_temp.reject(x.protocol||'_invalid_method',format('SELECT pg_temp.register(%L,gen_random_uuid(),%L)',c.admin_id,
    x.payload||'{"method_version":"../unsafe"}'),'check constraint');
  kind:=CASE x.protocol WHEN 'ldd' THEN 'ldd_geometry' ELSE (x.validation->>'purpose')||'_raster' END;
  PERFORM pg_temp.register(c.admin_id,gen_random_uuid(),x.payload||jsonb_build_object('artifact_kind',kind));
  status:=pg_temp.read_status(c.officer_id,x.edition_id,'a1-test-v1');
  PERFORM pg_temp.assert_ok(x.protocol||'_complete_declarations_still_unverified',status->'artifacts_complete'='true'::jsonb
    AND status->'ready_for_publication'='false'::jsonb AND status->>'status'='registered_unverified');
  PERFORM pg_temp.assert_ok(x.protocol||'_different_methods_not_combined',
    pg_temp.read_status(c.officer_id,x.edition_id,'another-method')->'artifacts_complete'='false'::jsonb);
  PERFORM pg_temp.assert_ok(x.protocol||'_published_identity_explicit',status#>>'{source_identity,namespace}'='published'
    AND status#>>'{source_identity,edition_id}'=x.edition_id::text);
 END LOOP;
END $tests$;
SELECT pg_temp.assert_ok('geotiff_validation_state_preserved',NOT EXISTS(SELECT 1 FROM a1_payload t
 JOIN gis.editions e ON e.id=t.edition_id WHERE t.protocol='geotiff' AND (e.state<>'draft' OR e.validated_result_id IS NOT NULL)));
SELECT pg_temp.assert_ok('audit_and_receipts_exactly_once',(SELECT count(*)=4 FROM gis.audit WHERE operation='publication.register'
 AND actor_id=(SELECT admin_id FROM a1_context)) AND (SELECT count(*)=4 FROM gis.receipts
 WHERE operation='publication.register' AND actor_id=(SELECT admin_id FROM a1_context)));
SELECT pg_temp.assert_ok('generated_keys_are_content_addresses',NOT EXISTS(SELECT 1 FROM gis.publication_artifacts
 WHERE registered_by=(SELECT admin_id FROM a1_context) AND object_key<>'sha256/'||artifact_sha256||'/'||artifact_kind));
SELECT pg_temp.reject('registry_update_forbidden','UPDATE gis.publication_artifacts SET byte_size=101','GIS_ARTIFACT_IMMUTABLE');
SELECT pg_temp.reject('registry_delete_forbidden','DELETE FROM gis.publication_artifacts','GIS_ARTIFACT_IMMUTABLE');
SELECT pg_temp.reject('cannot_self_verify','UPDATE gis.publication_artifacts SET verification_state=''verified''','GIS_ARTIFACT_IMMUTABLE');
SELECT pg_temp.reject('closed_gate_activation_stays_closed',format('SELECT public.gis_command(%L,gen_random_uuid(),''activate'',%L,false)',
 c.admin_id,jsonb_build_object('dataset_id',t.dataset_id,'edition_id',t.edition_id,'expected_revision',t.dataset_revision,
 'expected_active_edition_id',NULL,'reason','A1 closed gate test')),'GIS_ACTIVATION_DISABLED') FROM a1_context c,a1_payload t WHERE t.protocol='ldd';
SELECT pg_temp.assert_ok('unprepared_readiness_always_false',NOT EXISTS(SELECT 1 FROM gis.editions WHERE gis.publication_ready(id,dataset_id)));
-- Only the new rollback-only admin is deleted; no pre-existing account is touched.
RESET ROLE;
DELETE FROM auth.users WHERE id=(SELECT admin_id FROM a1_context);
SET LOCAL ROLE gis_owner;
SELECT pg_temp.assert_ok('account_delete_nulls_registry_actor',NOT EXISTS(SELECT 1 FROM gis.publication_artifacts
 WHERE method_version='a1-test-v1' AND registered_by IS NOT NULL));
SET CONSTRAINTS ALL IMMEDIATE;
SELECT pg_temp.assert_ok('legacy_deferred_invariants_compatible',true);
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime-dir', type=Path, required=True)
    args = parser.parse_args()
    local = m.PublicationLocal(args.runtime_dir)
    local.proof_a1()
    evidence = {}
    for db in m.DATABASES:
        local.db.proof(db, stage='gis')
        positive = db == 'postgres'
        sql = ("BEGIN;SET LOCAL lock_timeout='5s';SET LOCAL statement_timeout='60s';" + HELPERS + COMMON
            + (POSITIVE if positive else '')
            + "SELECT jsonb_agg(jsonb_build_object('name',name,'passed',passed)) FROM a1_checks;ROLLBACK;")
        result = local.db.transport(db, sql)
        rows = [json.loads(x) for x in result.stdout.splitlines() if x.startswith('[{')][-1]
        evidence[db] = {'rows': rows, 'passed': sum(v['passed'] for v in rows), 'fixture_writes_rolled_back': True,
            'positive_registration_tested': positive,
            'not_tested': [] if positive else ['Upgrade DB has no real-file validation results; positive registration exercised on primary only']}
        if positive:
            sys.path.insert(0, str(m.REPO / 'green-area-backend'))
            from gis_publication import SourceIdentity
            identity = local.sql("SELECT gis.publication_status(e.id,'a1-test-v1')->'source_identity' "
                "FROM gis.editions e WHERE gis.publication_validation(e.id) IS NOT NULL LIMIT 1", db, read_only=True)
            parsed = SourceIdentity.model_validate(identity)
            if not parsed.cache_namespace().startswith('gis-source-v1:published:'):
                raise AssertionError('SQL_MODEL_SOURCE_IDENTITY_MISMATCH')
            evidence[db]['sql_python_source_identity_contract'] = 'Pass'
        print(json.dumps({'database': db, 'passed': evidence[db]['passed']}), flush=True)
    (local.output / 'sql-tests.json').write_text(json.dumps(evidence, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
