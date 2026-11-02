import copy
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("t0_manage", ROOT / "manage.py")
manager = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = manager
spec.loader.exec_module(manager)


class RuntimePolicyTests(unittest.TestCase):
    def setUp(self):
        self.runtime = object.__new__(manager.LocalRuntime)
        self.runtime.root = ROOT / "synthetic-runtime-only"
        self.runtime.lock = json.loads((ROOT / "images.lock.json").read_text(encoding="utf-8"))
        self.runtime.owner = lambda **kwargs: {"instance": "a" * 32}
        self.labels = {"gis.t0.scope": manager.guard.SCOPE, "gis.t0.instance": "a" * 32,
                       "com.docker.compose.project": manager.guard.PROJECT}
        self.items = {}
        for name, (memory, cpu, pids) in manager.LIMITS.items():
            host = {"Memory": memory, "MemorySwap": memory, "NanoCpus": cpu,
                    "PidsLimit": pids, "Privileged": False, "ReadonlyRootfs": name != "db",
                    "NetworkMode": "green-area-gis-t0-internal", "CapDrop": ["ALL"],
                    "CapAdd": ["CHOWN", "DAC_OVERRIDE", "FOWNER", "SETGID", "SETUID"] if name == "db" else None,
                    "SecurityOpt": ["no-new-privileges:true"], "PortBindings": {}}
            if name == "gateway":
                port, external = "8000/tcp", "55421"
                host["PortBindings"] = {port: [{"HostIp": "127.0.0.1", "HostPort": external}]}
            mounts = []
            if name == "db":
                mounts = [
                    {"Type": "volume", "Name": "green-area-gis-t0-data", "Destination": "/var/lib/postgresql/data", "RW": True},
                    {"Type": "volume", "Name": "green-area-gis-t0-db-config", "Destination": "/etc/postgresql-custom", "RW": True},
                    {"Type": "bind", "Source": str(self.runtime.root / "vendor/webhooks.sql"),
                     "Destination": "/docker-entrypoint-initdb.d/init-scripts/98-webhooks.sql", "RW": False},
                    {"Type": "bind", "Source": str(self.runtime.root / "vendor/roles.sql"),
                     "Destination": "/docker-entrypoint-initdb.d/init-scripts/99-roles.sql", "RW": False},
                    {"Type": "bind", "Source": str(self.runtime.root / "vendor/jwt.sql"),
                     "Destination": "/docker-entrypoint-initdb.d/init-scripts/99-jwt.sql", "RW": False}]
            elif name == "gateway":
                mounts = [{"Type": "bind", "Source": str(self.runtime.root / "kong.yml"),
                           "Destination": "/home/kong/kong.yml", "RW": False}]
            self.items[name] = {"id": name, "labels": copy.deepcopy(self.labels),
                "host": host, "image": self.runtime.lock["images"][name], "mounts": mounts,
                "networks": {"green-area-gis-t0-internal": {}}, "status": "created", "health": None}
            if name == "gateway":
                self.items[name]["networks"]["green-area-gis-t0-ingress"] = {}
        self.runtime.metadata = lambda name: self.items[name]
        self.network_internal = True
        self.runtime.docker = Mock(side_effect=lambda args: "true" if args[0] == "inspect" else json.dumps(
            {"internal": self.network_internal if args[-1].endswith("-internal") else False,
             "labels": self.labels, "driver": "bridge", "containers": {}}
            if args[0] == "network" else self.labels))

    def test_expected_stopped_containers_can_be_checked_before_start(self):
        self.assertEqual(set(self.runtime.verify_containers()), set(manager.SERVICES))
        self.assertFalse(any(call.args[0][0] in {"start", "exec", "compose"}
                             for call in self.runtime.docker.call_args_list))

    def test_extra_network_rejected(self):
        self.items["rest"]["networks"]["external-network"] = {}
        with self.assertRaisesRegex(manager.guard.SafetyError, "ADDITIONAL_NETWORK"):
            self.runtime.verify_containers()

    def test_extra_capability_rejected(self):
        self.items["db"]["host"]["CapAdd"].append("SYS_ADMIN")
        with self.assertRaisesRegex(manager.guard.SafetyError, "CAPABILITIES"):
            self.runtime.verify_containers()

    def test_allowed_source_at_wrong_destination_rejected(self):
        self.items["gateway"]["mounts"][0]["Destination"] = "/different-path"
        with self.assertRaisesRegex(manager.guard.SafetyError, "EXACT_MOUNTS"):
            self.runtime.verify_containers()

    @unittest.skipUnless(os.name == "nt", "Docker Desktop Windows translation only")
    def test_desktop_bind_translation_still_matches_exact_path(self):
        for mount in self.items["db"]["mounts"]:
            if mount["Type"] == "bind":
                windows = Path(mount["Source"]).as_posix()
                mount["Source"] = "/run/desktop/mnt/host/" + windows[0].lower() + "/" + windows[3:]
        self.runtime.verify_containers()

    def test_unexpected_credential_or_home_mount_rejected(self):
        self.items["auth"]["mounts"].append({"Type": "bind", "Source": str(ROOT),
                                             "Destination": "/host", "RW": False})
        with self.assertRaisesRegex(manager.guard.SafetyError, "EXACT_MOUNTS"):
            self.runtime.verify_containers()

    def test_external_bind_address_rejected(self):
        self.items["gateway"]["host"]["PortBindings"]["8000/tcp"][0]["HostIp"] = "0.0.0.0"
        with self.assertRaisesRegex(manager.guard.SafetyError, "PUBLISHED_PORTS"):
            self.runtime.verify_containers()

    def test_missing_memory_limit_rejected(self):
        self.items["auth"]["host"]["Memory"] = 0
        with self.assertRaisesRegex(manager.guard.SafetyError, "LIMITS"):
            self.runtime.verify_containers()

    def test_external_network_flag_rejected(self):
        self.network_internal = False
        with self.assertRaisesRegex(manager.guard.SafetyError, "EXTERNAL_NETWORK"):
            self.runtime.verify_containers()

    def test_foreign_member_on_owned_network_rejected(self):
        original = self.runtime.docker.side_effect
        def extra_member(args):
            output = original(args)
            if args[0] == "network":
                data = json.loads(output)
                data["containers"] = {"unrelated-container": {}}
                return json.dumps(data)
            return output
        self.runtime.docker.side_effect = extra_member
        with self.assertRaisesRegex(manager.guard.SafetyError, "FOREIGN_NETWORK_MEMBER"):
            self.runtime.verify_containers()

    def test_prepare_refuses_existing_docker_config_without_overwriting(self):
        with tempfile.TemporaryDirectory() as folder:
            self.runtime.root = Path(folder)
            config_dir = self.runtime.root / "docker-config"
            config_dir.mkdir()
            sentinel = config_dir / "config.json"
            sentinel.write_text("synthetic-do-not-overwrite")
            with self.assertRaisesRegex(manager.guard.SafetyError, "REFUSE_TO_OVERWRITE"):
                self.runtime.prepare()
            self.assertEqual(sentinel.read_text(), "synthetic-do-not-overwrite")
            self.runtime.docker.assert_not_called()

    def test_reconfigure_refuses_running_before_writing_metadata(self):
        self.items["db"]["status"] = "running"
        with self.assertRaisesRegex(manager.guard.SafetyError, "STOP_OWNED_SERVICES"):
            self.runtime.reconfigure()
        self.runtime.docker.assert_not_called()

    def test_gateway_telemetry_must_be_disabled(self):
        original = self.runtime.docker.side_effect
        self.runtime.docker.side_effect = lambda args: "false" if args[0] == "inspect" else original(args)
        with self.assertRaisesRegex(manager.guard.SafetyError, "TELEMETRY"):
            self.runtime.verify_containers()

    def test_stop_foreign_resources_is_rejected_before_action(self):
        for item in self.items.values():
            item["labels"]["gis.t0.instance"] = "b" * 32
        with self.assertRaisesRegex(manager.guard.SafetyError, "OWNERSHIP"):
            self.runtime.stop()
        self.runtime.docker.assert_not_called()


if __name__ == "__main__":
    unittest.main()
