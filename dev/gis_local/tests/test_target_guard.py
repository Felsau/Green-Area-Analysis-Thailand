import copy
from dataclasses import replace
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("t0_target_guard", ROOT / "target_guard.py")
guard = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = guard
spec.loader.exec_module(guard)


class TargetGuardTests(unittest.TestCase):
    def setUp(self):
        self.raw = {**copy.deepcopy(guard.EXPECTED), "GIS_ENABLED": False}
        self.target = guard.validate_config(self.raw)
        self.proof = guard.LocalProof(guard.PROJECT, guard.API_URL, "a" * 32, True, True, True, True)

    def test_default_disabled(self):
        del self.raw["GIS_ENABLED"]
        self.assertFalse(guard.validate_config(self.raw).gis_enabled)

    def test_checked_in_config_disabled(self):
        self.assertFalse(guard.load_config(ROOT / "local.example.json").gis_enabled)

    def test_remote_and_confusing_urls_rejected_without_echo(self):
        for uri in ("https://epeicbpccczctxfpaqhu.supabase.co", "https://unknown.supabase.co",
                    "http://localhost:55421", "http://127.0.0.1:8000", "http://127.0.0.1:55421/",
                    "http://127.0.0.1:55421@evil.invalid", "http://user:sensitive@127.0.0.1:55421",
                    "http://127.0.0.1:55421?token=sensitive", "http://127.0.0.1:55421#x",
                    "http://2130706433:55421", "http://[::ffff:127.0.0.1]:55421"):
            with self.subTest(uri=uri):
                self.raw["api_url"] = uri
                with self.assertRaises(guard.SafetyError) as caught:
                    guard.validate_config(self.raw)
                self.assertNotIn("sensitive", str(caught.exception))

    def test_database_allowlist(self):
        for key, value in (("host", "db.example.invalid"), ("port", 55422), ("name", "production"),
                           ("port", "55422"), ("password", "not-a-real-password")):
            with self.subTest(field=key):
                raw = copy.deepcopy(self.raw)
                raw["database"][key] = value
                with self.assertRaises(guard.SafetyError):
                    guard.validate_config(raw)

    def test_unknown_and_credential_fields_rejected(self):
        for field in ("SUPABASE_KEY", "credentials_path", "GEE_PROJECT", "extra"):
            raw = copy.deepcopy(self.raw)
            raw[field] = "not-read"
            with self.assertRaises(guard.SafetyError):
                guard.validate_config(raw)

    def test_strict_types_and_project(self):
        for field, value in (("version", True), ("version", 2), ("mode", "sandbox"),
                             ("project", "other-project"), ("GIS_ENABLED", "false"),
                             ("GIS_ENABLED", 0)):
            raw = copy.deepcopy(self.raw)
            raw[field] = value
            with self.assertRaises(guard.SafetyError):
                guard.validate_config(raw)

    def test_proof_fields_fail_closed(self):
        for field, value in (("containers_verified", False), ("internal_network", False),
                             ("postgres_verified", False), ("no_application_schema", False),
                             ("project", "production"), ("api_url", "https://example.invalid"),
                             ("instance", "not-a-trusted-instance"), ("internal_network", 1)):
            with self.subTest(field=field):
                with self.assertRaises(guard.SafetyError):
                    guard.require_ready(self.target, replace(self.proof, **{field: value}))

    def test_no_proof_no_mutation(self):
        spy = Mock()
        with self.assertRaises(guard.SafetyError):
            guard.guarded_test_mutation(self.target, None, spy)
        spy.assert_not_called()

    def test_disabled_no_mutation(self):
        spy = Mock()
        with self.assertRaisesRegex(guard.SafetyError, "GIS_FEATURE_DISABLED"):
            guard.guarded_test_mutation(self.target, self.proof, spy)
        spy.assert_not_called()

    def test_remote_constructed_target_no_mutation(self):
        spy = Mock()
        with self.assertRaises(guard.SafetyError):
            guard.guarded_test_mutation(replace(self.target, api_url="https://example.invalid",
                                                gis_enabled=True), self.proof, spy)
        spy.assert_not_called()

    def test_local_enabled_fake_mutation_only(self):
        spy = Mock(return_value="synthetic-only")
        self.assertEqual(guard.guarded_test_mutation(replace(self.target, gis_enabled=True),
                                                    self.proof, spy), "synthetic-only")
        spy.assert_called_once_with()

    def test_ambient_names_rejected_without_accessing_values(self):
        class NamesOnly(dict):
            def __getitem__(self, key):
                raise AssertionError("must not read secret value")
        for name in ("SUPABASE_KEY", "GEE_PROJECT", "EE_CREDENTIALS_JSON", "DATABASE_URL",
                     "GOOGLE_APPLICATION_CREDENTIALS", "PGPASSWORD", "VITE_SUPABASE_URL"):
            with self.assertRaises(guard.SafetyError):
                guard.reject_ambient_service_config(NamesOnly({name: "not-read"}))

    def test_child_environment_does_not_inherit_service_or_compose_overrides(self):
        env = guard.isolated_process_environment({"PATH": "safe", "SystemRoot": "safe",
             "GIS_LOCAL_DB_PASSWORD": "not-real", "COMPOSE_FILE": "other.yaml",
             "DOCKER_HOST": "tcp://remote.invalid", "SUPABASE_KEY": "not-real"})
        self.assertEqual(env, {"PATH": "safe", "SystemRoot": "safe"})

    def test_dotenv_never_loaded_by_guard_import_or_cli(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / ".env").write_text("SUPABASE_KEY=sentinel-do-not-read\nGIS_ENABLED=true\n")
            config = root / "local.json"
            config.write_text(json.dumps(self.raw))
            env = guard.isolated_process_environment(os.environ)
            proc = subprocess.run([sys.executable, "-I", "-B", str(ROOT / "target_guard.py"),
                                   "--config", str(config)], cwd=root, env=env,
                                  capture_output=True, text=True, timeout=10)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            result = json.loads(proc.stdout)
            self.assertFalse(result["GIS_ENABLED"])
            self.assertFalse(result["connected"])
            self.assertNotIn("sentinel", proc.stdout + proc.stderr)

    def test_nonlocal_config_filename_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "credentials.json"
            path.write_text("deliberately-not-json")
            with self.assertRaisesRegex(guard.SafetyError, "EXPLICIT_LOCAL_CONFIG_REQUIRED"):
                guard.load_config(path)


if __name__ == "__main__":
    unittest.main()
