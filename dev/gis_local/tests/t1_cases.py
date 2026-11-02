"""Executable T1 SQL boundary tests against the attested, local T0 sandbox only.

No application config, credentials, HTTP, cloud or scientific worker is loaded.
Most cases roll back all fixtures. Committed concurrency fixtures are retained.
SET ROLE tests database ACL/RLS behavior, not a real JWT or worker login.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("gis_t1_database_tests", HERE.parent / "t1_database.py")
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
literal = module.literal


def quoted(value):
    return literal(json.dumps(value, ensure_ascii=False)) + "::jsonb"


def assertion(expression: str, label="assertion"):
    return f"DO $test$ BEGIN IF NOT COALESCE(({expression}),false) THEN RAISE EXCEPTION 'TEST_ASSERTION:{label}'; END IF; END $test$;"


def role(name: str, body: str):
    if name not in {"gis_owner", "gis_worker", "service_role", "anon", "authenticated"}:
        raise ValueError("TEST_ROLE_REJECTED")
    return f"SET LOCAL ROLE {name};\n{body}\nRESET ROLE;\n"


class Suite:
    def __init__(self, runtime: Path, database: str):
        self.db = module.LocalDatabase(runtime)
        self.database = database
        self.results = []
        self.ids = {name: str(uuid.uuid4()) for name in ("admin", "officer", "user", "worker", "worker2")}
        self.run_id = str(uuid.uuid4())

    def rpc(self, operation, payload="'{}'::jsonb", actor="officer", request="gen_random_uuid()", sandbox="false"):
        return (f"public.gis_command('{self.ids[actor]}'::uuid,{request},{literal(operation)},"
                f"{payload},{sandbox})")

    def worker(self, action, payload="'{}'::jsonb"):
        return f"public.gis_worker({literal(action)},{payload})"

    def setup(self, fixture="ndvi-valid-v1"):
        statements = []
        for name in ("admin", "officer", "user"):
            statements.append("INSERT INTO auth.users(id,email,raw_user_meta_data) VALUES ("
                + literal(self.ids[name]) + "," + literal(name + "-" + self.run_id + "@example.invalid")
                + ",'{}'::jsonb);")
        statements.append(f"UPDATE public.profiles SET role='admin' WHERE id='{self.ids['admin']}';")
        statements.append(role("gis_owner", f"SELECT set_config('t1.manifest',(SELECT manifest::text FROM gis.synthetic_fixtures WHERE id={literal(fixture)}),true);"))
        statements.append(role("service_role", "SELECT " + self.rpc("grant_officer",
            f"jsonb_build_object('user_id','{self.ids['officer']}','reason','synthetic test grant')", actor="admin") + ";"))
        return "\n".join(statements)

    def create_catalog(self, *, fixture="ndvi-valid-v1", year=2025, month=0):
        purpose = "lst" if fixture == "lst-valid-v1" else "landuse" if fixture == "ldd-valid-v1" else "ndvi"
        kind = "ldd_shapefile" if purpose == "landuse" else "geotiff"
        data = quoted({"province": "Bangkok Metropolis", "data_year": year, "month": month,
                       "kind": kind, "purpose": purpose, "title": "T1 ข้อมูลจำลอง"})
        create = self.rpc("create_dataset", data)
        edition = self.rpc("create_edition", "jsonb_build_object('dataset_id',current_setting('t1.dataset'),'manifest',current_setting('t1.manifest')::jsonb)")
        return role("service_role", f"""
DO $test$ DECLARE r jsonb; BEGIN
 r:={create};
 IF (r->>'status')::int<>201 THEN RAISE EXCEPTION 'TEST_DATASET_CREATE'; END IF;
 PERFORM set_config('t1.dataset',r->'body'->>'id',true);
 r:={edition};
 IF (r->>'status')::int<>201 THEN RAISE EXCEPTION 'TEST_EDITION_CREATE'; END IF;
 PERFORM set_config('t1.edition',r->'body'->>'id',true);
END $test$;
""")

    def enqueue(self):
        call = self.rpc("enqueue", "jsonb_build_object('edition_id',current_setting('t1.edition'),'expected_revision',1)")
        return role("service_role", f"""
DO $test$ DECLARE r jsonb; BEGIN r:={call};
 IF (r->>'status')::int<>202 THEN RAISE EXCEPTION 'TEST_ENQUEUE'; END IF;
 PERFORM set_config('t1.job',r->'body'->>'id',true);
END $test$;
""")

    def claim(self, worker="worker"):
        call = self.worker("claim", f"jsonb_build_object('worker_id','{self.ids[worker]}')")
        return role("gis_worker", f"""
DO $test$ DECLARE r jsonb; BEGIN r:={call};
 IF r IS NULL OR r->>'job_id' IS DISTINCT FROM current_setting('t1.job') THEN RAISE EXCEPTION 'TEST_CLAIM'; END IF;
 PERFORM set_config('t1.token',r->>'lease_token',true);
END $test$;
""")

    def lease_payload(self, suffix="", worker="worker", token="current_setting('t1.token')"):
        return ("jsonb_build_object('job_id',current_setting('t1.job'),'worker_id','"
                + self.ids[worker] + "','lease_token'," + token + suffix + ")")

    def complete(self, fixture="ndvi-valid-v1"):
        payload = self.lease_payload(", 'report',jsonb_build_object('valid',true,'fixture_id'," + literal(fixture)
            + ",'checks',jsonb_build_array('synthetic_fixture_match'))")
        return role("gis_worker", "SELECT " + self.worker("complete", payload) + ";")

    def expire(self):
        return role("gis_owner", "UPDATE gis.jobs SET lease_until=clock_timestamp()-interval '1 second' WHERE id=current_setting('t1.job')::uuid;")

    def ready(self):
        return role("gis_owner", "UPDATE gis.jobs SET available_at=clock_timestamp()-interval '1 second' WHERE id=current_setting('t1.job')::uuid;")

    def run_case(self, name, body, *, fixture="ndvi-valid-v1", expected_error=None, setup=True):
        sql = "BEGIN; SET LOCAL lock_timeout='3s'; SET LOCAL statement_timeout='15s';\n"
        if setup:
            sql += self.setup(fixture) + "\n"
        sql += body + "\nSET CONSTRAINTS ALL IMMEDIATE; ROLLBACK;"
        started = time.monotonic()
        try:
            result = self.db.query(self.database, sql, check=False, timeout=45)
            state = re.search(r"ERROR:\s+([0-9A-Z]{5}):", result.stderr)
            actual_error = state.group(1) if state else None
            passed = (result.returncode == 0 if expected_error is None else
                result.returncode != 0 and (actual_error == expected_error or expected_error in result.stderr))
            item = {"name": name, "status": "Pass" if passed else "Fail",
                    "expected_error": expected_error, "actual_sqlstate": actual_error,
                    "duration_seconds": round(time.monotonic()-started, 3)}
            if not passed:
                # Only bounded error lines; never print full SQL, user metadata or lease values.
                item["diagnostic"] = "\n".join(line for line in result.stderr.splitlines()
                    if "ERROR:" in line or "HINT:" in line)[:800]
        except Exception as error:
            item = {"name": name, "status": "Fail", "diagnostic": type(error).__name__ + ": " + str(error)[:500]}
        self.results.append(item)
        print(json.dumps(item, ensure_ascii=False), flush=True)

    def tests(self):
        a = assertion
        cat = self.create_catalog
        job = lambda: cat() + self.enqueue()
        running = lambda: job() + self.claim()
        validated = lambda: running() + self.complete()
        # Catalog checks examine effective ACL/RLS as well as performing rejected calls.
        self.run_case("all_private_tables_force_rls", role("gis_owner", a("NOT EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='gis' AND c.relkind='r' AND (NOT c.relrowsecurity OR NOT c.relforcerowsecurity))")), setup=False)
        self.run_case("private_functions_owner_and_search_path", a("NOT EXISTS(SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace JOIN pg_roles r ON r.oid=p.proowner WHERE n.nspname='gis' AND (r.rolname<>'gis_owner' OR NOT p.prosecdef OR p.proconfig IS NULL))"), setup=False)
        self.run_case("worker_nologin_nonprivileged", a("EXISTS(SELECT 1 FROM pg_roles WHERE rolname='gis_worker' AND NOT rolcanlogin AND NOT rolsuper AND NOT rolbypassrls AND NOT rolcreatedb AND NOT rolcreaterole)"), setup=False)
        for client in ("anon", "authenticated", "service_role", "gis_worker"):
            self.run_case(client + "_private_select_denied", role(client, "SELECT * FROM gis.datasets;"), expected_error="42501", setup=False)
            self.run_case(client + "_private_write_denied", role(client, "UPDATE gis.datasets SET title='forbidden';"), expected_error="42501", setup=False)
        for client in ("anon", "authenticated", "gis_worker"):
            self.run_case(client + "_command_rpc_denied", role(client, "SELECT " + self.rpc("create_dataset") + ";"), expected_error="42501", setup=False)
        for client in ("anon", "authenticated", "service_role"):
            self.run_case(client + "_worker_rpc_denied", role(client, "SELECT " + self.worker("claim", quoted({"worker_id": self.ids["worker"]})) + ";"), expected_error="42501", setup=False)
        self.run_case("worker_legacy_cache_write_denied", role("gis_worker", "UPDATE public.ndvi_annual SET ndvi_mean=0;"), expected_error="42501", setup=False)
        read = lambda actor, kind, payload="'{}'::jsonb": f"public.gis_read('{self.ids[actor]}',{literal(kind)},{payload})"
        self.run_case("normal_user_me_has_no_gis_grant", role("service_role", a("NOT (" + read("user", "me") + "->>'admin')::boolean AND NOT (" + read("user", "me") + "->>'officer')::boolean")))
        self.run_case("normal_user_catalog_read_forbidden", role("service_role", "SELECT " + read("user", "datasets") + ";"), expected_error="42501")
        self.run_case("officer_catalog_read_allowed", cat() + role("service_role", a("jsonb_array_length(" + read("officer", "datasets") + "->'data')>=1")))
        self.run_case("officer_user_directory_forbidden", role("service_role", "SELECT " + read("officer", "officers") + ";"), expected_error="42501")
        # Retained synthetic grants from earlier runs must not invalidate this
        # authorization check; assert the exact current fixture, not global size.
        self.run_case("admin_officer_list_allowed", role("service_role", a(
            "(SELECT count(*) FROM jsonb_array_elements(" + read("admin", "officers")
            + "->'data') entry WHERE entry->>'user_id'=" + literal(self.ids["officer"]) + ")=1")))
        self.run_case("read_limit_bounded", role("service_role", "SELECT " + read("officer", "datasets", quoted({"limit": 101})) + ";"), expected_error="GIS_INVALID_LIMIT")
        # Temporary grants isolate RLS itself from the usual schema/ACL rejection.
        self.run_case("rls_authenticated_select_hides_rows_even_with_acl", cat()
            + role("gis_owner", "GRANT USAGE ON SCHEMA gis TO authenticated;GRANT SELECT ON gis.datasets TO authenticated;")
            + role("authenticated", a("(SELECT count(*)=0 FROM gis.datasets)")))
        self.run_case("rls_authenticated_insert_denied_even_with_acl", cat()
            + role("gis_owner", "GRANT USAGE ON SCHEMA gis TO authenticated;GRANT INSERT ON gis.datasets TO authenticated;")
            + role("authenticated", "INSERT INTO gis.datasets(province,data_year,month,kind,purpose,title) VALUES('Bangkok Metropolis',2024,0,'geotiff','ndvi','forbidden');"), expected_error="42501")
        self.run_case("normal_user_mutation_forbidden", role("service_role", "SELECT " + self.rpc("create_dataset", actor="user") + ";"), expected_error="42501")
        self.run_case("officer_cannot_self_grant", role("service_role", "SELECT " + self.rpc("grant_officer", quoted({"user_id": self.ids["user"], "reason": "test"})) + ";"), expected_error="42501")
        self.run_case("officer_create_dataset_edition", cat() + role("gis_owner", a("EXISTS(SELECT 1 FROM gis.editions WHERE id=current_setting('t1.edition')::uuid AND state='draft' AND input_revision=1)")))
        self.run_case("dataset_identity_unique", cat() + cat(), expected_error="23505")
        self.run_case("unknown_payload_field_rejected", role("service_role", "SELECT " + self.rpc("create_dataset", quoted({"actor_id": self.ids["admin"]})) + ";"), expected_error="GIS_INVALID_PAYLOAD")
        self.run_case("future_dataset_year_rejected", cat(year=2199), expected_error="GIS_INVALID")
        # Receipt replay is checked before stale-revision checks, but after authorization.
        create_payload = quoted({"province": "Bangkok Metropolis", "data_year": 2025, "month": 0, "kind": "geotiff", "purpose": "ndvi", "title": "Replay"})
        request = str(uuid.uuid4())
        call = self.rpc("create_dataset", create_payload, request=literal(request) + "::uuid")
        self.run_case("idempotency_same_payload_one_effect", role("service_role", f"DO $test$ DECLARE x jsonb;y jsonb;BEGIN x:={call};y:={call}; IF x IS DISTINCT FROM y THEN RAISE EXCEPTION 'TEST_RECEIPT_REPLAY';END IF;END $test$;") + role("gis_owner", a("(SELECT count(*)=1 FROM gis.datasets WHERE title='Replay') AND (SELECT count(*)=1 FROM gis.receipts WHERE request_id=" + literal(request) + "::uuid)")))
        conflict_call = self.rpc("create_dataset", create_payload.replace("Replay", "Changed"), request=literal(request) + "::uuid")
        self.run_case("idempotency_different_payload_conflict", role("service_role", "SELECT " + call + ";SELECT " + conflict_call + ";"), expected_error="GIS_IDEMPOTENCY")
        revoke = self.rpc("revoke_officer", quoted({"user_id": self.ids["officer"], "reason": "revoked"}), actor="admin")
        self.run_case("revoked_actor_cannot_replay_receipt", role("service_role", "SELECT " + call + ";SELECT " + revoke + ";SELECT " + call + ";"), expected_error="42501")
        self.run_case("legacy_profile_roles_preserved", a("(SELECT array_agg(DISTINCT role ORDER BY role) FROM public.profiles WHERE id IN ('" + self.ids["admin"] + "','" + self.ids["officer"] + "','" + self.ids["user"] + "'))=ARRAY['admin','user']::text[]"))
        self.run_case("enqueue_sets_validating_and_queued", job() + role("gis_owner", a("EXISTS(SELECT 1 FROM gis.jobs j JOIN gis.editions e ON e.id=j.edition_id WHERE j.id=current_setting('t1.job')::uuid AND j.state='queued' AND e.state='validating' AND j.input_revision=e.input_revision AND j.input_hash=e.input_hash)")))
        self.run_case("draft_edit_revision_increments", cat() + role("service_role", "SELECT " + self.rpc("edit_edition", "jsonb_build_object('edition_id',current_setting('t1.edition'),'expected_revision',1,'manifest',current_setting('t1.manifest')::jsonb)") + ";")
            + role("gis_owner", a("(SELECT input_revision=2 FROM gis.editions WHERE id=current_setting('t1.edition')::uuid)")))
        self.run_case("stale_edition_revision_rejected", cat() + role("service_role", "SELECT " + self.rpc("edit_edition", "jsonb_build_object('edition_id',current_setting('t1.edition'),'expected_revision',99,'manifest',current_setting('t1.manifest')::jsonb)") + ";"), expected_error="GIS_REVISION_CONFLICT")
        self.run_case("remote_url_manifest_rejected", cat() + role("service_role", "SELECT " + self.rpc("edit_edition", "jsonb_build_object('edition_id',current_setting('t1.edition'),'expected_revision',1,'manifest',(current_setting('t1.manifest')::jsonb)||jsonb_build_object('url','https://example.invalid/a.tif'))") + ";"), expected_error="GIS_INVALID_PAYLOAD")
        self.run_case("enqueue_semantic_dedup", job() + self.enqueue() + role("gis_owner", a("(SELECT count(*)=1 FROM gis.jobs WHERE edition_id=current_setting('t1.edition')::uuid)")))
        self.run_case("claim_records_attempt", running() + role("gis_owner", a("EXISTS(SELECT 1 FROM gis.jobs j JOIN gis.attempts t ON t.job_id=j.id WHERE j.id=current_setting('t1.job')::uuid AND j.state='running' AND j.attempt_count=1 AND t.state='running' AND t.lease_token=j.lease_token)")))
        self.run_case("second_claim_running_returns_null", running() + role("gis_worker", a(self.worker("claim", quoted({"worker_id": self.ids["worker2"]})) + " IS NULL")))
        heartbeat = lambda progress: role("gis_worker", "SELECT " + self.worker("heartbeat", self.lease_payload(",'progress'," + str(progress))) + ";")
        self.run_case("heartbeat_updates_progress", running() + heartbeat(35) + role("gis_owner", a("(SELECT progress=35 AND lease_until>clock_timestamp() FROM gis.jobs WHERE id=current_setting('t1.job')::uuid)")))
        self.run_case("progress_regression_rejected", running() + heartbeat(35) + heartbeat(34), expected_error="GIS_INVALID_PROGRESS")
        self.run_case("progress_100_before_completion_rejected", running() + heartbeat(100), expected_error="GIS_INVALID_PROGRESS")
        self.run_case("wrong_worker_fenced", running() + role("gis_worker", "SELECT " + self.worker("heartbeat", self.lease_payload(",'progress',1", worker="worker2")) + ";"), expected_error="GIS_STALE_LEASE")
        self.run_case("wrong_token_fenced", running() + role("gis_worker", "SELECT " + self.worker("heartbeat", self.lease_payload(",'progress',1", token="gen_random_uuid()")) + ";"), expected_error="GIS_STALE_LEASE")
        self.run_case("expired_heartbeat_fenced", running() + self.expire() + heartbeat(1), expected_error="GIS_STALE_LEASE")
        self.run_case("expired_completion_fenced", running() + self.expire() + self.complete(), expected_error="GIS_STALE_LEASE")
        self.run_case("completion_atomic_result_job_edition_audit", validated() + role("gis_owner", a("EXISTS(SELECT 1 FROM gis.editions e JOIN gis.results r ON r.id=e.validated_result_id JOIN gis.jobs j ON j.id=r.job_id WHERE e.id=current_setting('t1.edition')::uuid AND e.state='validated' AND j.state='succeeded' AND j.progress=100 AND r.input_hash=e.input_hash) AND EXISTS(SELECT 1 FROM gis.audit WHERE job_id=current_setting('t1.job')::uuid AND operation='worker.complete') AND (SELECT active_edition_id IS NULL FROM gis.datasets WHERE id=current_setting('t1.dataset')::uuid)")))
        self.run_case("duplicate_completion_fenced", validated() + self.complete(), expected_error="GIS_STALE_LEASE")
        fail = lambda code: role("gis_worker", "SELECT " + self.worker("fail", self.lease_payload(",'error_code'," + literal(code))) + ";")
        self.run_case("invalid_failure_returns_draft_atomically", running() + fail("invalid_data") + role("gis_owner", a("EXISTS(SELECT 1 FROM gis.jobs j JOIN gis.editions e ON e.id=j.edition_id WHERE j.id=current_setting('t1.job')::uuid AND j.state='failed' AND e.state='draft') AND NOT EXISTS(SELECT 1 FROM gis.results WHERE job_id=current_setting('t1.job')::uuid)")))
        self.run_case("transient_failure_requeues_with_backoff", running() + fail("transient") + role("gis_owner", a("EXISTS(SELECT 1 FROM gis.jobs j JOIN gis.editions e ON e.id=j.edition_id WHERE j.id=current_setting('t1.job')::uuid AND j.state='queued' AND j.available_at>clock_timestamp() AND e.state='validating')")))
        recover = role("gis_worker", "SELECT " + self.worker("recover") + ";")
        self.run_case("recovery_marks_expired_attempt", running() + self.expire() + recover + role("gis_owner", a("EXISTS(SELECT 1 FROM gis.jobs j JOIN gis.attempts t ON t.job_id=j.id WHERE j.id=current_setting('t1.job')::uuid AND j.state='queued' AND t.state='expired')")))
        self.run_case("recovery_is_idempotent", running() + self.expire() + recover + role("gis_worker", a("(" + self.worker("recover") + "->>'recovered')::int=0")))
        exhausted = running() + fail("transient") + self.ready() + self.claim() + fail("transient") + self.ready() + self.claim() + fail("transient")
        self.run_case("three_attempts_exhaust_to_draft", exhausted + role("gis_owner", a("EXISTS(SELECT 1 FROM gis.jobs j JOIN gis.editions e ON e.id=j.edition_id WHERE j.id=current_setting('t1.job')::uuid AND j.state='failed' AND j.attempt_count=3 AND e.state='draft') AND (SELECT count(*)=3 FROM gis.attempts WHERE job_id=current_setting('t1.job')::uuid)")))
        # Terminal lease recovery uses a genuine third claim, not counter fabrication.
        recovery_final = running() + fail("transient") + self.ready() + self.claim() + fail("transient") + self.ready() + self.claim() + self.expire() + recover
        self.run_case("terminal_recovery_returns_draft", recovery_final + role("gis_owner", a("EXISTS(SELECT 1 FROM gis.jobs j JOIN gis.editions e ON e.id=j.edition_id WHERE j.id=current_setting('t1.job')::uuid AND j.state='failed' AND j.error_code='attempts_exhausted' AND e.state='draft')")))
        self.run_case("old_token_cannot_overwrite_new_attempt", running() + role("gis_owner", "SELECT set_config('t1.old_token',current_setting('t1.token'),true);") + self.expire() + recover + self.ready() + self.claim() + role("gis_worker", "SELECT " + self.worker("complete", self.lease_payload(",'report',jsonb_build_object('valid',true,'fixture_id','ndvi-valid-v1','checks',jsonb_build_array('synthetic_fixture_match'))", token="current_setting('t1.old_token')")) + ";"), expected_error="GIS_STALE_LEASE")
        retry = role("gis_owner", "SELECT set_config('t1.root_job',current_setting('t1.job'),true);SELECT set_config('t1.hash',(SELECT input_hash FROM gis.jobs WHERE id=current_setting('t1.job')::uuid),true);")
        retry_call = self.rpc("retry", "jsonb_build_object('job_id',current_setting('t1.job'),'expected_revision',1,'input_hash',current_setting('t1.hash'),'reason','synthetic technical retry')")
        retry += role("service_role", "DO $test$ DECLARE r jsonb;BEGIN r:=" + retry_call + ";IF (r->>'status')::int<>202 THEN RAISE EXCEPTION 'TEST_RETRY';END IF;PERFORM set_config('t1.job',r->'body'->>'id',true);END $test$;")
        self.run_case("explicit_retry_creates_one_child", exhausted + retry + role("gis_owner", a("EXISTS(SELECT 1 FROM gis.jobs WHERE id=current_setting('t1.job')::uuid AND parent_job_id=current_setting('t1.root_job')::uuid AND state='queued' AND attempt_count=0)")))
        child_failed = exhausted + retry + self.claim() + fail("transient") + self.ready() + self.claim() + fail("transient") + self.ready() + self.claim() + fail("transient")
        self.run_case("explicit_retry_chain_rejected", child_failed + role("service_role", "SELECT " + retry_call + ";"), expected_error="GIS_RETRY_INELIGIBLE")
        self.run_case("one_explicit_retry_per_original", child_failed + role("gis_owner", "SELECT set_config('t1.job',current_setting('t1.root_job'),true);") + role("service_role", "SELECT " + retry_call + ";"), expected_error="GIS_RETRY_ALREADY_USED")
        self.run_case("invalid_fixture_cannot_complete_successfully", cat(fixture="invalid-v1") + self.enqueue() + self.claim() + self.complete("invalid-v1"), fixture="invalid-v1", expected_error="GIS_INVALID_RESULT")
        self.run_case("db_identity_cannot_change", cat() + role("gis_owner", "UPDATE gis.datasets SET data_year=2024 WHERE id=current_setting('t1.dataset')::uuid;"), expected_error="GIS_DATASET_IDENTITY_IMMUTABLE")
        self.run_case("db_validated_inputs_immutable", validated() + role("gis_owner", "UPDATE gis.editions SET input_revision=2 WHERE id=current_setting('t1.edition')::uuid;"), expected_error="GIS_INPUT_IMMUTABLE")
        self.run_case("db_unvalidated_active_pointer_rejected", cat() + role("gis_owner", "UPDATE gis.environment SET activation_enabled=true;UPDATE gis.datasets SET active_edition_id=current_setting('t1.edition')::uuid,revision=2 WHERE id=current_setting('t1.dataset')::uuid;"), expected_error="GIS_ACTIVE_INVARIANT")
        self.run_case("db_edition_without_active_job_rejected", cat() + role("gis_owner", "UPDATE gis.editions SET state='validating' WHERE id=current_setting('t1.edition')::uuid;"), expected_error="GIS_QUEUE_EDITION_INVARIANT")
        self.run_case("db_audit_append_only", cat() + role("gis_owner", "UPDATE gis.audit SET reason='rewritten';"), expected_error="GIS_HISTORY_IMMUTABLE")
        self.run_case("db_result_append_only", validated() + role("gis_owner", "UPDATE gis.results SET report='{}';"), expected_error="GIS_HISTORY_IMMUTABLE")
        self.run_case("db_terminal_job_immutable", validated() + role("gis_owner", "UPDATE gis.jobs SET state='queued' WHERE id=current_setting('t1.job')::uuid;"), expected_error="GIS_JOB_TERMINAL_IMMUTABLE")
        self.run_case("receipt_body_contains_no_actor_copy", validated() + role("gis_owner", a("NOT EXISTS(SELECT 1 FROM gis.receipts WHERE body::text LIKE '%" + self.ids['officer'] + "%')")))
        # SQL validation reports are synthetic metadata; no GIS computation occurs.
        self.activation_cases(validated)
        self.concurrency_case()

    def activation_cases(self, validated):
        gate_on = role("gis_owner", "UPDATE gis.environment SET activation_enabled=true;")
        payload = "jsonb_build_object('dataset_id',current_setting('t1.dataset'),'edition_id',current_setting('t1.edition'),'expected_revision',1,'expected_active_edition_id',NULL,'reason','synthetic activation test')"
        activate = lambda actor="admin", sandbox="true": role("service_role", "SELECT " + self.rpc("activate", payload, actor=actor, sandbox=sandbox) + ";")
        self.run_case("activation_database_gate_off", validated() + activate(), expected_error="GIS_ACTIVATION_DISABLED")
        self.run_case("activation_backend_gate_off", validated() + gate_on + activate(sandbox="false"), expected_error="GIS_ACTIVATION_DISABLED")
        self.run_case("officer_cannot_activate", validated() + gate_on + activate(actor="officer"), expected_error="42501")
        self.run_case("activation_success_preserves_edition", validated() + gate_on + activate() + role("gis_owner", assertion("EXISTS(SELECT 1 FROM gis.datasets d JOIN gis.editions e ON e.id=d.active_edition_id WHERE d.id=current_setting('t1.dataset')::uuid AND d.revision=2 AND e.state='validated')")))
        self.run_case("activation_stale_revision_rejected", validated() + gate_on + activate() + activate(), expected_error="GIS_REVISION")
        clone = self.rpc("clone_edition", "jsonb_build_object('edition_id',current_setting('t1.edition'),'expected_revision',1)")
        self.run_case("validated_edition_clone_is_new_draft", validated() + role("service_role", "SELECT " + clone + ";") + role("gis_owner", assertion("(SELECT count(*)=2 FROM gis.editions WHERE dataset_id=current_setting('t1.dataset')::uuid) AND EXISTS(SELECT 1 FROM gis.editions WHERE cloned_from_id=current_setting('t1.edition')::uuid AND state='draft')")))
        edit = self.rpc("edit_edition", "jsonb_build_object('edition_id',current_setting('t1.edition'),'expected_revision',1,'manifest',current_setting('t1.manifest')::jsonb)")
        self.run_case("validated_inputs_cannot_edit", validated() + role("service_role", "SELECT " + edit + ";"), expected_error="GIS_REVISION_CONFLICT")
        withdraw_payload = "jsonb_build_object('edition_id',current_setting('t1.edition'),'expected_revision',1,'expected_dataset_revision',2,'expected_active_edition_id',current_setting('t1.edition'),'replacement_edition_id',NULL,'reason','explicitly clear synthetic pointer')"
        self.run_case("active_withdrawal_explicitly_clears_pointer", validated() + gate_on + activate()
            + role("service_role", "SELECT " + self.rpc("withdraw", withdraw_payload, actor="admin", sandbox="true") + ";")
            + role("gis_owner", assertion("(SELECT active_edition_id IS NULL AND revision=3 FROM gis.datasets WHERE id=current_setting('t1.dataset')::uuid) AND (SELECT state='withdrawn' FROM gis.editions WHERE id=current_setting('t1.edition')::uuid)")))
        second_edition = role("gis_owner", "SELECT set_config('t1.old_edition',current_setting('t1.edition'),true);")
        second_call = self.rpc("create_edition", "jsonb_build_object('dataset_id',current_setting('t1.dataset'),'manifest',current_setting('t1.manifest')::jsonb)")
        second_edition += role("service_role", "DO $test$ DECLARE r jsonb;BEGIN r:=" + second_call + ";PERFORM set_config('t1.edition',r->'body'->>'id',true);END $test$;")
        second_edition += self.enqueue() + self.claim() + self.complete()
        second_payload = "jsonb_build_object('dataset_id',current_setting('t1.dataset'),'edition_id',current_setting('t1.edition'),'expected_revision',2,'expected_active_edition_id',current_setting('t1.old_edition'),'reason','synthetic new edition')"
        rollback_payload = "jsonb_build_object('dataset_id',current_setting('t1.dataset'),'edition_id',current_setting('t1.old_edition'),'expected_revision',3,'expected_active_edition_id',current_setting('t1.edition'),'reason','synthetic rollback')"
        self.run_case("transactional_rollback_preserves_both_results", validated() + gate_on + activate() + second_edition
            + role("service_role", "SELECT " + self.rpc("activate", second_payload, actor="admin", sandbox="true") + ";SELECT " + self.rpc("rollback", rollback_payload, actor="admin", sandbox="true") + ";")
            + role("gis_owner", assertion("(SELECT active_edition_id=current_setting('t1.old_edition')::uuid AND revision=4 FROM gis.datasets WHERE id=current_setting('t1.dataset')::uuid) AND (SELECT count(*)=2 FROM gis.results WHERE edition_id IN (current_setting('t1.edition')::uuid,current_setting('t1.old_edition')::uuid))")))
        # FK account deletion on test users is rolled back, never an existing account.
        self.run_case("requester_deletion_preserves_shared_catalog", validated() + "DELETE FROM auth.users WHERE id='" + self.ids["officer"] + "';" + role("gis_owner", assertion("EXISTS(SELECT 1 FROM gis.datasets WHERE id=current_setting('t1.dataset')::uuid AND created_by IS NULL) AND EXISTS(SELECT 1 FROM gis.editions WHERE id=current_setting('t1.edition')::uuid AND created_by IS NULL AND state='validated') AND EXISTS(SELECT 1 FROM gis.jobs WHERE id=current_setting('t1.job')::uuid AND requested_by IS NULL) AND NOT EXISTS(SELECT 1 FROM gis.officers WHERE user_id='" + self.ids["officer"] + "')")))

    def concurrency_case(self):
        """Independent transactions prove claim/client-disconnect durability, not process recovery."""
        name = "concurrent_claim_one_job_and_client_disconnect"
        try:
            self.db.proof(self.database, stage="gis")
            # Commit synthetic data, then close the submitting SQL client entirely.
            available = self.db.query(self.database, "BEGIN;SET LOCAL ROLE gis_owner;SELECT min(y) FROM generate_series(1980,2024) y WHERE NOT EXISTS(SELECT 1 FROM gis.datasets WHERE province='Bangkok Metropolis' AND data_year=y AND month=1 AND kind='geotiff' AND purpose='ndvi');ROLLBACK;").stdout.strip()
            if not available:
                raise ValueError("NO_FREE_CONCURRENCY_SYNTHETIC_DATASET_IDENTITY")
            create_sql = "BEGIN;" + self.setup() + self.create_catalog(year=int(available), month=1) + self.enqueue()
            create_sql += "SELECT jsonb_build_object('job_id',current_setting('t1.job'));COMMIT;"
            out = self.db.transport(self.database, create_sql).stdout.splitlines()
            job_id = next(json.loads(line)["job_id"] for line in reversed(out) if line.startswith('{') and '"job_id"' in line)
            def claim(worker):
                sql = "BEGIN;SET LOCAL ROLE gis_worker;SELECT " + self.worker("claim", quoted({"worker_id": self.ids[worker]})) + ";COMMIT;"
                result = self.db.transport(self.database, sql)
                lines = [line for line in result.stdout.splitlines() if line.strip()]
                return json.loads(lines[-1]) if lines else None
            with ThreadPoolExecutor(max_workers=2) as pool:
                values = list(pool.map(claim, ("worker", "worker2")))
            claims = [value for value in values if value is not None]
            passed = len(claims) == 1 and claims[0]["job_id"] == job_id
            self.results.append({"name": name, "status": "Pass" if passed else "Fail",
                "claim_count": len(claims), "submitted_client_closed": True,
                "retained_synthetic_fixture": True, "job_id": job_id})
            # Finish committed synthetic job through the winner's lease, retaining history.
            if passed:
                lease = claims[0]
                payload = {key: lease[key] for key in ("job_id", "worker_id", "lease_token")}
                payload["report"] = {"valid": True, "fixture_id": "ndvi-valid-v1", "checks": ["synthetic_fixture_match"]}
                self.db.query(self.database, "BEGIN;SET LOCAL ROLE gis_worker;SELECT " + self.worker("complete", quoted(payload)) + ";COMMIT;")
                self.results.append({"name": "committed_concurrent_job_completion", "status": "Pass"})
        except Exception as error:
            self.results.append({"name": name, "status": "Fail", "diagnostic": type(error).__name__ + ": " + str(error)[:600]})
        print(json.dumps(self.results[-1], ensure_ascii=False), flush=True)

    def supplemental(self):
        # Late failure is injected only in this rollback fixture, after the mutation
        # would otherwise have written its row. The SQL statement's subtransaction
        # must undo both the effect and receipt when audit insertion fails.
        create_payload = quoted({"province": "Bangkok Metropolis", "data_year": 2025,
            "month": 0, "kind": "geotiff", "purpose": "ndvi", "title": "atomic audit fixture"})
        command = self.rpc("create_dataset", create_payload)
        injector = role("gis_owner", """
CREATE FUNCTION gis.t1_test_audit_failure() RETURNS trigger LANGUAGE plpgsql AS $test$
BEGIN RAISE EXCEPTION 'T1_AUDIT_FAILURE' USING ERRCODE='P9001'; END $test$;
CREATE TRIGGER t1_test_audit_failure BEFORE INSERT ON gis.audit
 FOR EACH ROW WHEN (NEW.operation='create_dataset') EXECUTE FUNCTION gis.t1_test_audit_failure();
""")
        caught = role("service_role", "DO $test$ DECLARE caught boolean:=false;BEGIN BEGIN PERFORM "
            + command + ";EXCEPTION WHEN SQLSTATE 'P9001' THEN caught:=true;END;"
            + "IF NOT caught THEN RAISE EXCEPTION 'TEST_EXPECTED_LATE_AUDIT_FAILURE';END IF;END $test$;")
        self.run_case("supplement_late_audit_failure_rolls_back_effect_receipt", injector + caught
            + role("gis_owner", assertion("NOT EXISTS(SELECT 1 FROM gis.datasets WHERE title='atomic audit fixture') AND NOT EXISTS(SELECT 1 FROM gis.receipts WHERE operation='create_dataset' AND actor_id='" + self.ids['officer'] + "'::uuid)")))
        edit_payload = "jsonb_build_object('dataset_id',current_setting('t1.dataset'),'expected_revision',1,'title','edited once')"
        replay_request = literal(str(uuid.uuid4())) + "::uuid"
        edit = self.rpc("edit_dataset", edit_payload, request=replay_request)
        self.run_case("supplement_receipt_replay_precedes_stale_revision", self.create_catalog()
            + role("service_role", "DO $test$ DECLARE x jsonb;y jsonb;BEGIN x:=" + edit + ";y:=" + edit
                + ";IF x IS DISTINCT FROM y THEN RAISE EXCEPTION 'TEST_REPLAY';END IF;END $test$;")
            + role("gis_owner", assertion("(SELECT revision=2 FROM gis.datasets WHERE id=current_setting('t1.dataset')::uuid)")))
        self.run_case("supplement_actor_nulling_leaves_no_json_uuid", self.create_catalog() + self.enqueue() + self.claim() + self.complete()
            + "DELETE FROM auth.users WHERE id='" + self.ids["officer"] + "';"
            + role("gis_owner", assertion("NOT EXISTS(SELECT 1 FROM gis.receipts WHERE body::text LIKE '%" + self.ids['officer'] + "%') AND NOT EXISTS(SELECT 1 FROM gis.audit WHERE detail::text LIKE '%" + self.ids['officer'] + "%')")))
        self.run_case("supplement_finished_attempt_append_only", self.create_catalog() + self.enqueue() + self.claim() + self.complete()
            + role("gis_owner", "UPDATE gis.attempts SET progress=99 WHERE job_id=current_setting('t1.job')::uuid;"), expected_error="GIS_ATTEMPT_IMMUTABLE")
        self.blocked_lease_case()

    def blocked_lease_case(self):
        name = "supplement_wall_clock_after_waiting_for_row_lock"
        locker = None
        try:
            self.db.proof(self.database, stage="gis")
            available = self.db.transport(self.database, "BEGIN;SET LOCAL ROLE gis_owner;SELECT min(y) FROM generate_series(1980,2024) y WHERE NOT EXISTS(SELECT 1 FROM gis.datasets WHERE province='Bangkok Metropolis' AND data_year=y AND month=1 AND kind='geotiff' AND purpose='ndvi');ROLLBACK;").stdout.strip()
            create_sql = "BEGIN;" + self.setup() + self.create_catalog(year=int(available), month=1) + self.enqueue()
            create_sql += "SELECT jsonb_build_object('job_id',current_setting('t1.job'));COMMIT;"
            output = self.db.transport(self.database, create_sql).stdout.splitlines()
            job = next(json.loads(line)["job_id"] for line in reversed(output) if line.startswith('{') and '"job_id"' in line)
            lease = json.loads(self.db.transport(self.database, "BEGIN;SET LOCAL ROLE gis_worker;SELECT "
                + self.worker("claim", quoted({"worker_id": self.ids['worker']})) + ";COMMIT;").stdout.strip())
            if lease['job_id'] != job:
                raise ValueError("WRONG_SYNTHETIC_LEASE")
            # Shorten only this owned synthetic lease; actual elapsed time expires it.
            self.db.transport(self.database, "BEGIN;SET LOCAL ROLE gis_owner;UPDATE gis.jobs SET lease_until=clock_timestamp()+interval '2 seconds' WHERE id=" + literal(job) + "::uuid;COMMIT;")
            locker_sql = "BEGIN;SET LOCAL statement_timeout='8s';SET LOCAL lock_timeout='3s';SET LOCAL ROLE gis_owner;SELECT id FROM gis.jobs WHERE id=" + literal(job) + "::uuid FOR UPDATE;SELECT 'T1_LOCK_READY';SELECT pg_sleep(3);COMMIT;"
            args = self.db.runtime.base + ['exec','-i',self.db.container,'psql','-X','-qAt','-U','postgres','-d',self.database,'-v','ON_ERROR_STOP=1']
            locker = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding='utf-8', cwd=self.db.runtime.root, env=self.db.runtime.env)
            locker.stdin.write(locker_sql)
            locker.stdin.close()
            while True:
                line = locker.stdout.readline()
                if not line:
                    raise ValueError("LOCK_HOLDER_EXITED_EARLY")
                if line.strip() == 'T1_LOCK_READY':
                    break
            payload = {key: lease[key] for key in ('job_id','worker_id','lease_token')}
            payload['progress'] = 10
            started = time.monotonic()
            heartbeat = self.db.transport(self.database, "BEGIN;SET LOCAL ROLE gis_worker;SELECT " + self.worker('heartbeat', quoted(payload)) + ";COMMIT;", check=False)
            waited = time.monotonic() - started
            locker.wait(timeout=10)
            passed = heartbeat.returncode != 0 and 'GIS_STALE_LEASE' in heartbeat.stderr and waited >= 2
            self.results.append({'name': name, 'status': 'Pass' if passed else 'Fail',
                'waited_seconds': round(waited,3), 'lease_expired_during_actual_lock_wait': True})
            # Recover the retained synthetic fixture via queue protocol and finish it.
            self.db.transport(self.database, "BEGIN;SET LOCAL ROLE gis_worker;SELECT " + self.worker('recover') + ";COMMIT;")
            self.db.transport(self.database, "BEGIN;SET LOCAL ROLE gis_owner;UPDATE gis.jobs SET available_at=clock_timestamp() WHERE id=" + literal(job) + "::uuid;COMMIT;")
            replacement = json.loads(self.db.transport(self.database, "BEGIN;SET LOCAL ROLE gis_worker;SELECT " + self.worker('claim',quoted({'worker_id': self.ids['worker2']})) + ";COMMIT;").stdout.strip())
            final = {key: replacement[key] for key in ('job_id','worker_id','lease_token')}
            final['report'] = {'valid':True,'fixture_id':'ndvi-valid-v1','checks':['synthetic_fixture_match']}
            self.db.transport(self.database, "BEGIN;SET LOCAL ROLE gis_worker;SELECT " + self.worker('complete',quoted(final)) + ";COMMIT;")
            self.results.append({'name':'supplement_recovered_disconnected_sql_worker_lease','status':'Pass', 'actual_python_worker':False})
        except Exception as error:
            self.results.append({'name':name,'status':'Fail','diagnostic':type(error).__name__+': '+str(error)[:600]})
        finally:
            if locker is not None:
                locker.wait(timeout=10)
        print(json.dumps(self.results[-1],ensure_ascii=False),flush=True)

    def run(self, supplemental_only=False):
        proof = self.db.proof(self.database, stage="gis")
        if supplemental_only:
            self.supplemental()
        else:
            self.tests()
        not_tested = [
            "Real JWT/Auth HTTP to RPC end-to-end (T2)",
            "Concrete worker LOGIN credentials and Python process SIGKILL recovery (T3)",
            "Actual native GIS/scientific validation in this T1 SQL suite",
            "Cloud/Supabase/GEE/production behavior",
        ]
        report = {"run_id": self.run_id, "database": self.database, "proof": proof,
            "counts": {state: sum(r["status"] == state for r in self.results) for state in ("Pass", "Fail")},
            "results": self.results, "not_tested": not_tested,
            "evidence_boundary": "Local PostgreSQL transactions and SET ROLE; no real user JWT or worker service"}
        self.db.write_json(f"{self.database}-t1-tests-{self.run_id}.json", report)
        print(json.dumps({"counts": report["counts"], "report": f"{self.database}-t1-tests-{self.run_id}.json"}))
        return 1 if report["counts"]["Fail"] else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-dir", required=True, type=Path)
    parser.add_argument("--database", choices=sorted(module.DATABASES), default="postgres")
    parser.add_argument("--supplemental-only", action="store_true")
    args = parser.parse_args()
    return Suite(args.runtime_dir, args.database).run(args.supplemental_only)


if __name__ == "__main__":
    sys.exit(main())
