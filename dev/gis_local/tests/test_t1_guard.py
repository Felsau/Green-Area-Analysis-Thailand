"""Negative boundary checks for the stage-aware local migration harness."""
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

spec = importlib.util.spec_from_file_location("t1_guard_under_test", Path(__file__).parents[1] / "t1_database.py")
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class TargetChecks(unittest.TestCase):
    def target(self, **overrides):
        db = object.__new__(module.LocalDatabase)
        db.instance = "a" * 32
        db.evidence_dir = Path("deliberately-absent-t1-test-evidence")
        db.runtime = Mock()
        db.runtime.verify_containers.return_value = {"db": {"id": "b" * 64, "status": "running", "health": "healthy"}}
        proof = {"database": "postgres", "cluster": "green-area-gis-t0", "version": 170006,
            "migrator": "postgres", "create_database": True, "create_role": True,
            "auth": True, "uid": True, "gis": False, "application_tables": 0,
            "auth_users": 0, "legacy_functions": False, "legacy_auth_trigger": False}
        proof.update(overrides)
        db.transport = Mock(return_value=SimpleNamespace(stdout=json.dumps(proof)))
        return db

    def test_unknown_target_rejected_before_docker(self):
        db = self.target()
        with self.assertRaisesRegex(module.SafetyError, "DATABASE_NOT_ALLOWLISTED"):
            db.proof("production")
        db.runtime.verify_containers.assert_not_called()
        db.transport.assert_not_called()

    def test_identity_rejections(self):
        for change in ({"cluster": "unknown"}, {"database": "production"}, {"version": 140000},
                       {"migrator": "unknown"}, {"auth": False}, {"uid": False},
                       {"create_database": False}, {"create_role": False}):
            with self.subTest(change=change), self.assertRaisesRegex(module.SafetyError, "IDENTITY_REJECTED"):
                self.target(**change).proof()

    def test_pristine_baseline_required(self):
        for field in ("gis", "application_tables", "auth_users", "legacy_functions", "legacy_auth_trigger"):
            with self.subTest(field=field), self.assertRaisesRegex(module.SafetyError, "NO_LEGACY_REPLAY"):
                self.target(**{field: True}).proof(stage="empty")

    def test_schema_stage_needs_baseline_checkpoint(self):
        with self.assertRaisesRegex(module.SafetyError, "CHECKPOINT_REQUIRED"):
            self.target().proof(stage="baseline")

    def test_stopped_engine_rejected_before_sql(self):
        db = self.target()
        db.runtime.verify_containers.return_value["db"]["status"] = "exited"
        with self.assertRaisesRegex(module.SafetyError, "NOT_HEALTHY"):
            db.proof()
        db.transport.assert_not_called()

    def test_transport_requires_exact_database_and_container(self):
        db = object.__new__(module.LocalDatabase)
        db.container = "unknown"
        with self.assertRaisesRegex(module.SafetyError, "NOT_PROVED"):
            db.transport("postgres", "SELECT 1")
        db.container = "a" * 64
        with self.assertRaisesRegex(module.SafetyError, "NOT_PROVED"):
            db.transport("production", "SELECT 1")

    def test_transaction_adapter_preserves_do_bodies(self):
        source = "BEGIN;\nDO $$\nBEGIN\n  PERFORM 1;\nEND $$;\nCOMMIT;\n"
        adapted = module.atomic_body(source)
        self.assertIn("DO $$\nBEGIN\n  PERFORM 1;\nEND $$;", adapted)
        self.assertNotIn("COMMIT;", adapted)


if __name__ == "__main__":
    unittest.main()
