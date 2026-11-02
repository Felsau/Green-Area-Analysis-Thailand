"""T3 E2E Integration Suite: API -> Queue -> Worker -> Native Validation -> Database.

Tests actual Supabase Auth, FastAPI, PostgREST, and Native GIS Worker with
V2 synthetic fixtures, recovery, fencing, and permission boundaries.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
from pathlib import Path
import sys
import time
from uuid import UUID, uuid4

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
spec = importlib_spec = None
import importlib.util
spec = importlib.util.spec_from_file_location("t3_e2e_t2", HERE / "t2_local.py")
t2 = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = t2
spec.loader.exec_module(t2)
t1 = t2.t1

spec_id = importlib.util.spec_from_file_location("t3_id_mod", REPO / "dev/gis_worker/t3_identity.py")
t3_id = importlib.util.module_from_spec(spec_id)
sys.modules[spec_id.name] = t3_id
spec_id.loader.exec_module(t3_id)

BACKEND = REPO / "green-area-backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from gis_worker import provider
from gis_worker.worker import GisWorker
from starlette.testclient import TestClient


class T3Suite:
    def __init__(self, root: Path):
        self.local = t2.LocalT2(root)
        self.results = []
        self.users = {}
        self.tokens = {}

    def record(self, name: str, passed: bool, **safe):
        row = {"name": name, "status": "Pass" if passed else "Fail", **safe}
        self.results.append(row)
        print(json.dumps(row), flush=True)
        return passed

    def sql(self, body: str, role: str = "gis_owner"):
        switch = "" if role == "postgres" else f"SET LOCAL ROLE {role};"
        output = self.local.db.query(
            "postgres",
            f"BEGIN;SET LOCAL lock_timeout='5s';SET LOCAL statement_timeout='30s';{switch}{body};COMMIT;"
        ).stdout.strip()
        lines = [line for line in output.splitlines() if line.strip()]
        return json.loads(lines[-1]) if lines else None

    def setup(self):
        self.local.attest()
        anon, service = self.local.local_keys()
        operator = self.local.client(service)
        run = uuid4().hex[:8]

        # 1. Create Officer user
        officer_email = f"gis-t3-officer-{run}@example.invalid"
        officer_pw = "T3OfficerSecretPass!2026"
        created_officer = operator.auth.admin.create_user({
            "email": officer_email,
            "password": officer_pw,
            "email_confirm": True,
            "user_metadata": {"role": "user"}
        })
        officer_id = str(created_officer.user.id)
        # Grant GIS officer in DB
        self.sql(f"INSERT INTO gis.officers(user_id) VALUES('{officer_id}') ON CONFLICT (user_id) DO NOTHING;")

        # Sign in officer
        c_officer = self.local.client(anon)
        res_off = c_officer.auth.sign_in_with_password({"email": officer_email, "password": officer_pw})
        self.tokens["officer"] = res_off.session.access_token
        self.users["officer"] = officer_id

        # 2. Provision Native Worker Identity via t3_identity
        worker_id_obj = t3_id.provision(self.local)
        self.worker_identity = worker_id_obj
        self.worker = GisWorker(worker_id_obj.client, worker_id=UUID(worker_id_obj.subject), docker_base=self.local.db.runtime.base)

        # 3. FastAPI TestClient
        runtime = self.local.runtime(activation=True)
        from gis_app import create_app
        app = create_app(runtime)
        self.client = TestClient(app, base_url="http://127.0.0.1:55422")

    def free_dataset(self, kind: str, purpose: str, month: int | None = None):
        months_series = "0" if month == 0 else "generate_series(1, 12)"
        value = self.sql(f"""SELECT jsonb_build_object('province',p.name_en,'data_year',y,'month',m,'kind','{kind}','purpose','{purpose}')
FROM public.provinces p CROSS JOIN generate_series(1980, extract(year FROM clock_timestamp())::int) y
CROSS JOIN {months_series} m
WHERE NOT EXISTS(SELECT 1 FROM gis.datasets d
 WHERE d.province=p.name_en AND d.data_year=y AND d.month=m AND d.kind='{kind}' AND d.purpose='{purpose}')
ORDER BY (p.name_en='Bangkok Metropolis') DESC, p.name_en, y, m LIMIT 1""")
        if value is None:
            raise RuntimeError("NO_FREE_DATASET")
        return value

    def run_tests(self):
        # Test 1: Worker readiness
        try:
            ready = self.worker.readiness()
            self.record("worker_readiness_rpc_succeeds", ready.get("status") == "ready" and ready.get("worker_role") == "gis_native_worker")
        except Exception as exc:
            self.record("worker_readiness_rpc_succeeds", False, error=str(exc))

        # Test 2: Worker cannot perform admin or backend actions
        def denied_check(name, fn):
            try:
                fn()
                self.record(name, False)
            except Exception as e:
                code = getattr(e, "code", "")
                self.record(name, str(code) in ("42501", "PGRST202", "PGRST106", "PGRST205"))

        denied_check("worker_cannot_call_gis_command", lambda: self.worker.client.rpc("gis_command", {"p_actor": str(self.worker.worker_id), "p_request_id": str(uuid4()), "p_operation": "create_dataset", "p_payload": {}}).execute())
        denied_check("worker_cannot_call_gis_read", lambda: self.worker.client.rpc("gis_read", {"p_actor": str(self.worker.worker_id), "p_kind": "me", "p_payload": {}}).execute())
        denied_check("worker_cannot_write_gis_datasets", lambda: self.worker.client.schema("gis").table("datasets").insert({"province": "Bangkok Metropolis"}).execute())

        # Test 3: API -> Queue -> Worker -> Native Validation (Valid LDD Shapefile)
        headers = {"Authorization": f"Bearer {self.tokens['officer']}", "Idempotency-Key": str(uuid4())}
        ds_info = self.free_dataset("ldd_shapefile", "landuse", month=0)
        ds_body = {
            **ds_info,
            "title": "Synthetic Bangkok LDD 2024 V2",
        }
        r_ds = self.client.post("/gis/datasets", json=ds_body, headers=headers)
        self.record("officer_creates_dataset_v2", r_ds.status_code == 201)
        ds_id = r_ds.json().get("id")

        # Create Edition with V2 manifest
        m_valid = provider.fixture_manifest("t3-ldd-valid-v2")
        headers["Idempotency-Key"] = str(uuid4())
        r_ed = self.client.post(f"/gis/datasets/{ds_id}/editions", json={"manifest": m_valid}, headers=headers)
        self.record("officer_creates_edition_v2", r_ed.status_code == 201)
        ed_id = r_ed.json().get("id")

        # Enqueue Job
        headers["Idempotency-Key"] = str(uuid4())
        r_q = self.client.post(f"/gis/editions/{ed_id}/validation-jobs", json={"expected_revision": 1}, headers=headers)
        self.record("officer_enqueues_validation_job", r_q.status_code == 202)
        job_id = r_q.json().get("id")

        # Verify job is queued in DB
        j_state = self.sql(f"SELECT jsonb_build_object('state',state,'worker_id',worker_id) FROM gis.jobs WHERE id='{job_id}'")
        self.record("job_queued_in_db_initially", j_state.get("state") == "queued" and j_state.get("worker_id") is None)

        # Worker processes job
        process_res = self.worker.run_once()
        self.record("worker_processes_job_successfully", isinstance(process_res, dict) and process_res.get("state") == "succeeded")

        # Verify DB final state
        j_after = self.sql(f"SELECT jsonb_build_object('state',state,'progress',progress) FROM gis.jobs WHERE id='{job_id}'")
        e_after = self.sql(f"SELECT jsonb_build_object('state',state,'validated_result_id',validated_result_id) FROM gis.editions WHERE id='{ed_id}'")
        ds_after = self.sql(f"SELECT jsonb_build_object('active_edition_id',active_edition_id) FROM gis.datasets WHERE id='{ds_id}'")
        attempt = self.sql(f"SELECT jsonb_build_object('state',state,'report',validation_report) FROM gis.attempts WHERE job_id='{job_id}' AND attempt_no=1")

        self.record("job_marked_succeeded_in_db", j_after.get("state") == "succeeded" and j_after.get("progress") == 100)
        self.record("edition_marked_validated_in_db", e_after.get("state") == "validated" and e_after.get("validated_result_id") is not None)
        self.record("dataset_not_auto_activated_by_worker", ds_after.get("active_edition_id") is None)
        self.record("attempt_has_structured_validation_report", isinstance(attempt.get("report"), dict) and attempt["report"].get("valid") is True and attempt["report"].get("statistics", {}).get("total_area_m2") == 6400)

        # Test 4: API read returns validation_report in attempts
        r_att = self.client.get(f"/gis/jobs/{job_id}/attempts", headers={"Authorization": f"Bearer {self.tokens['officer']}"})
        self.record("api_attempts_endpoint_projects_validation_report", r_att.status_code == 200 and len(r_att.json().get("data", [])) > 0 and r_att.json()["data"][0].get("validation_report") is not None)

        # Test 5: Negative Validation - Unknown land-use code (Safe Failure & Revert to Draft)
        headers["Idempotency-Key"] = str(uuid4())
        m_unknown = provider.fixture_manifest("t3-unknown-v2")
        r_ed_u = self.client.post(f"/gis/datasets/{ds_id}/editions", json={"manifest": m_unknown}, headers=headers)
        ed_u_id = r_ed_u.json().get("id")

        headers["Idempotency-Key"] = str(uuid4())
        r_q_u = self.client.post(f"/gis/editions/{ed_u_id}/validation-jobs", json={"expected_revision": 1}, headers=headers)
        job_u_id = r_q_u.json().get("id")

        process_res_u = self.worker.run_once()
        self.record("worker_processes_unknown_code_job_safely", isinstance(process_res_u, dict) and process_res_u.get("state") == "failed" and process_res_u.get("error_code") == "UNKNOWN_CODE_REVIEW_REQUIRED")

        e_u_after = self.sql(f"SELECT jsonb_build_object('state',state) FROM gis.editions WHERE id='{ed_u_id}'")
        j_u_after = self.sql(f"SELECT jsonb_build_object('state',state,'error_code',error_code) FROM gis.jobs WHERE id='{job_u_id}'")
        self.record("unknown_code_reverts_edition_to_draft", e_u_after.get("state") == "draft")
        self.record("unknown_code_marks_job_failed", j_u_after.get("state") == "failed" and j_u_after.get("error_code") == "UNKNOWN_CODE_REVIEW_REQUIRED")

        # Test 6: Negative Validation - Unsafe zip traversal fixture rejected
        headers["Idempotency-Key"] = str(uuid4())
        m_unsafe = provider.fixture_manifest("t3-zip-unsafe-v2")
        r_ed_bad = self.client.post(f"/gis/datasets/{ds_id}/editions", json={"manifest": m_unsafe}, headers=headers)
        ed_bad_id = r_ed_bad.json().get("id")

        headers["Idempotency-Key"] = str(uuid4())
        r_q_bad = self.client.post(f"/gis/editions/{ed_bad_id}/validation-jobs", json={"expected_revision": 1}, headers=headers)
        job_bad_id = r_q_bad.json().get("id")

        process_res_bad = self.worker.run_once()
        self.record("worker_rejects_unsafe_zip_traversal", isinstance(process_res_bad, dict) and process_res_bad.get("state") == "failed" and process_res_bad.get("error_code") == "ZIP_PATH_UNSAFE")

        # Test 7: Concurrency & Fencing
        # Claim with worker A, attempt heartbeat with wrong token
        m_s2 = provider.fixture_manifest("t3-s2-v2")
        ds_s2_info = self.free_dataset("geotiff", "ndvi", month=1)
        ds_s2 = self.client.post("/gis/datasets", json={**ds_s2_info, "title": "S2 NDVI 2024"}, headers={"Authorization": f"Bearer {self.tokens['officer']}", "Idempotency-Key": str(uuid4())}).json()["id"]
        ed_s2 = self.client.post(f"/gis/datasets/{ds_s2}/editions", json={"manifest": m_s2}, headers={"Authorization": f"Bearer {self.tokens['officer']}", "Idempotency-Key": str(uuid4())}).json()["id"]
        job_s2 = self.client.post(f"/gis/editions/{ed_s2}/validation-jobs", json={"expected_revision": 1}, headers={"Authorization": f"Bearer {self.tokens['officer']}", "Idempotency-Key": str(uuid4())}).json()["id"]

        claimed_job = self.worker.claim()
        self.record("worker_claims_s2_job", claimed_job is not None and claimed_job["id"] == job_s2)

        # Fencing: wrong token heartbeat fails
        fake_token = str(uuid4())
        try:
            self.worker.heartbeat(job_s2, fake_token, 50)
            self.record("wrong_lease_token_heartbeat_fenced", False)
        except Exception:
            self.record("wrong_lease_token_heartbeat_fenced", True)

        # Complete the S2 job
        res_s2 = self.worker.process_job(claimed_job)
        self.record("worker_completes_s2_raster_validation", res_s2.get("state") == "succeeded")

        # Test 8: Recovery of expired lease
        m_lst = provider.fixture_manifest("t3-lst-ready-v2")
        ds_lst_info = self.free_dataset("geotiff", "lst", month=2)
        ds_lst = self.client.post("/gis/datasets", json={**ds_lst_info, "title": "LST Ready 2024"}, headers={"Authorization": f"Bearer {self.tokens['officer']}", "Idempotency-Key": str(uuid4())}).json()["id"]
        ed_lst = self.client.post(f"/gis/datasets/{ds_lst}/editions", json={"manifest": m_lst}, headers={"Authorization": f"Bearer {self.tokens['officer']}", "Idempotency-Key": str(uuid4())}).json()["id"]
        job_lst = self.client.post(f"/gis/editions/{ed_lst}/validation-jobs", json={"expected_revision": 1}, headers={"Authorization": f"Bearer {self.tokens['officer']}", "Idempotency-Key": str(uuid4())}).json()["id"]

        c_job = self.worker.claim()
        # Backdate lease_until to 10 minutes ago
        self.sql(f"UPDATE gis.jobs SET lease_until=clock_timestamp() - interval '10 minutes' WHERE id='{c_job['id']}'")
        recovered_count = self.worker.recover()
        self.record("expired_lease_recovered_by_worker", recovered_count >= 1)

        j_rec = self.sql(f"SELECT jsonb_build_object('state',state,'attempt_count',attempt_count) FROM gis.jobs WHERE id='{c_job['id']}'")
        self.record("recovered_job_returned_to_queued_for_retry", j_rec.get("state") == "queued" and j_rec.get("attempt_count") == 1)

        # Now clean up / finish that job so queue is idle
        self.sql(f"UPDATE gis.jobs SET available_at=clock_timestamp() - interval '1 second' WHERE id='{c_job['id']}'")
        self.worker.run_once()

        counts = {s: sum(r["status"] == s for r in self.results) for s in ("Pass", "Fail")}
        report = {
            "type": "t3_e2e_integration_results",
            "counts": counts,
            "results": self.results,
        }
        (self.local.directory / "t3-integration-report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        return counts["Fail"] == 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-dir", type=Path, required=True)
    args = parser.parse_args()
    for name in ("httpx", "httpcore", "supabase_auth", "postgrest"):
        logging.getLogger(name).setLevel(logging.CRITICAL)
    suite = T3Suite(args.runtime_dir)
    suite.setup()
    success = suite.run_tests()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
