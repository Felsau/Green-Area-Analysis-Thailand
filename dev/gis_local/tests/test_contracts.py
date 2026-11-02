import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ContractScaffoldingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = json.loads((ROOT / "contracts.json").read_text(encoding="utf-8"))

    def test_phase_boundary_and_flags(self):
        self.assertIs(self.contract["feature_defaults"]["GIS_ENABLED"], False)
        self.assertIs(self.contract["api"]["implemented_in_t0"], False)
        self.assertIn("gee_ingestion", self.contract["deferred"])
        self.assertIn("production_migrations", self.contract["deferred"])

    def test_single_active_source_and_legacy_roles(self):
        self.assertEqual(self.contract["edition"]["stored_review_states"],
                         ["draft", "validating", "validated", "withdrawn"])
        self.assertNotIn("active", self.contract["edition"]["stored_review_states"])
        self.assertEqual(self.contract["authorization"]["legacy_profile_roles_unchanged"], ["user", "admin"])

    def test_recovery_idempotency_and_retry_budget(self):
        jobs = self.contract["jobs"]
        self.assertEqual(jobs["states"], ["queued", "running", "succeeded", "failed"])
        self.assertGreater(jobs["lease_seconds"], 2 * jobs["heartbeat_seconds"])
        self.assertEqual(jobs["max_total_attempts_per_fingerprint"],
                         jobs["max_attempts_per_run"] * (1 + jobs["max_explicit_retry_runs_per_original_run"]))
        self.assertTrue(jobs["retry_requires_current_revision_and_hash"])
        self.assertFalse(jobs["auto_activate"])

    def test_nonsecret_lock_and_bootstrap_allowlist(self):
        lock = json.loads((ROOT / "images.lock.json").read_text(encoding="utf-8"))
        self.assertEqual(set(lock["images"]), {"db", "auth", "rest", "gateway"})
        self.assertEqual(set(lock["bootstrap"]), {"roles.sql", "jwt.sql", "webhooks.sql"})
        for image in lock["images"].values():
            self.assertRegex(image, r"^[a-z0-9/]+@sha256:[0-9a-f]{64}$")


if __name__ == "__main__":
    unittest.main()
