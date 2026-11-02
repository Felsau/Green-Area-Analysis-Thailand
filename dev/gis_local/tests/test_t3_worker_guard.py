"""T3 topology opt-in never weakens the default T0/T2 trust boundary."""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("t3_existing_runtime_policy", HERE / "test_runtime_policy.py")
original = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = original
spec.loader.exec_module(original)
manager = original.manager


class T3WorkerGuardTests(unittest.TestCase):
    def setUp(self):
        original.RuntimePolicyTests.setUp(self)
        self.cid = "b" * 64
        self.run_id = "c" * 32
        self.approval = {self.cid: {"name": "gis-t3-worker-" + self.run_id[:12], "run_id": self.run_id}}
        self.worker = {
            "id": self.cid, "name": "/" + self.approval[self.cid]["name"],
            "image": manager.WORKER_IMAGE, "image_id": manager.WORKER_IMAGE,
            "labels": {"gis.t3.scope": "gis-worker-t3", "gis.t3.instance": "a" * 32,
                       "gis.t3.run": self.run_id, "com.docker.compose.project": manager.guard.PROJECT},
            "user": "65534:65534", "command": manager.WORKER_COMMAND.copy(),
            "entrypoint": None, "workdir": "/app/gis_worker",
            "host": {"Memory": 1073741824, "MemorySwap": 1073741824,
                     "NanoCpus": 1000000000, "PidsLimit": 64, "Privileged": False,
                     "ReadonlyRootfs": True, "Init": True,
                     "NetworkMode": "green-area-gis-t0-internal", "CapDrop": ["ALL"],
                     "CapAdd": None, "SecurityOpt": ["no-new-privileges:true"],
                     "PortBindings": {}, "Tmpfs": copy.deepcopy(manager.WORKER_TMPFS)},
            "networks": {"green-area-gis-t0-internal": {}},
            "mounts": [{"Type": "bind", "Source": str(manager.WORKER_SOURCE),
                        "Destination": "/app/gis_worker", "RW": False, "Propagation": "rprivate"}],
        }
        self.env_names = "PATH\nLANG\nPYTHON_VERSION\nPYTHON_SHA256\nGPG_KEY\nPYTHONDONTWRITEBYTECODE\nPYTHONUNBUFFERED\n"
        self.foreign_members = {self.cid: {}}
        self.internal_member = True
        fallback = self.runtime.docker.side_effect

        def docker(args):
            if args[0] == "inspect" and args[-1] == self.cid:
                if args[2] == manager.WORKER_ENV_NAMES:
                    return self.env_names
                return json.dumps(self.worker)
            if args[0] == "network":
                result = json.loads(fallback(args))
                if args[-1].endswith("-internal") == self.internal_member:
                    result["containers"] = self.foreign_members
                return json.dumps(result)
            return fallback(args)
        self.runtime.docker = Mock(side_effect=docker)

    def verify(self):
        return self.runtime.verify_containers(approved_workers=self.approval)

    def test_exact_approved_worker_is_accepted_only_with_explicit_policy(self):
        self.assertEqual(set(self.verify()), set(manager.SERVICES))
        self.assertFalse(any(c.args[0][0] in {"exec", "start", "run", "create"}
                             for c in self.runtime.docker.call_args_list))

    def test_default_strict_mode_rejects_even_correctly_labeled_worker(self):
        with self.assertRaisesRegex(manager.guard.SafetyError, "FOREIGN_NETWORK_MEMBER"):
            self.runtime.verify_containers()
        self.assertFalse(any(c.args[0][0] == "inspect" and c.args[0][-1] == self.cid
                             for c in self.runtime.docker.call_args_list))

    def test_empty_policy_also_preserves_strict_mode(self):
        with self.assertRaisesRegex(manager.guard.SafetyError, "FOREIGN_NETWORK_MEMBER"):
            self.runtime.verify_containers(approved_workers={})

    def test_unknown_member_is_denied_even_beside_approved_worker(self):
        self.foreign_members["d" * 64] = {}
        with self.assertRaisesRegex(manager.guard.SafetyError, "FOREIGN_NETWORK_MEMBER"):
            self.verify()

    def test_worker_may_not_join_ingress_bridge(self):
        self.internal_member = False
        with self.assertRaisesRegex(manager.guard.SafetyError, "FOREIGN_NETWORK_MEMBER"):
            self.verify()

    def test_approval_cannot_supply_mount_path_or_command(self):
        self.approval[self.cid]["path"] = "/arbitrary"
        with self.assertRaisesRegex(manager.guard.SafetyError, "EXPLICIT_APPROVAL"):
            self.verify()

    def test_approval_requires_full_exact_container_id(self):
        self.approval = {self.cid[:12]: self.approval[self.cid]}
        with self.assertRaisesRegex(manager.guard.SafetyError, "EXPLICIT_APPROVAL"):
            self.verify()

    def test_environment_credentials_rejected_without_reading_values(self):
        self.env_names += "SUPABASE_SERVICE_ROLE_KEY\n"
        with self.assertRaisesRegex(manager.guard.SafetyError, "ENVIRONMENT"):
            self.verify()

    def test_container_inspect_failure_is_fail_closed(self):
        self.runtime.docker = Mock(side_effect=ValueError("synthetic only"))
        with self.assertRaisesRegex(manager.guard.SafetyError, "INSPECTION"):
            self.verify()


def _mutation_case(path, value):
    def test(self):
        cursor = self.worker
        for key in path[:-1]:
            cursor = cursor[key]
        cursor[path[-1]] = copy.deepcopy(value)
        with self.assertRaises(manager.guard.SafetyError):
            self.verify()
    return test


# Every row is a separate unittest result rather than a summary-only claim.
MUTATIONS = {
    "unlimited_memory_zero": (("host", "Memory"), 0),
    "negative_memory": (("host", "Memory"), -1),
    "oversized_memory": (("host", "Memory"), 2147483648),
    "unlimited_swap": (("host", "MemorySwap"), -1),
    "unlimited_swap_zero": (("host", "MemorySwap"), 0),
    "unlimited_pids": (("host", "PidsLimit"), -1),
    "zero_pids": (("host", "PidsLimit"), 0),
    "oversized_pids": (("host", "PidsLimit"), 65),
    "unlimited_cpu": (("host", "NanoCpus"), 0),
    "oversized_cpu": (("host", "NanoCpus"), 2000000000),
    "privileged": (("host", "Privileged"), True),
    "writable_root": (("host", "ReadonlyRootfs"), False),
    "missing_init": (("host", "Init"), False),
    "added_sysadmin_capability": (("host", "CapAdd"), ["SYS_ADMIN"]),
    "no_cap_drop": (("host", "CapDrop"), []),
    "unconfined_seccomp": (("host", "SecurityOpt"), ["no-new-privileges:true", "seccomp=unconfined"]),
    "host_pid_namespace": (("host", "PidMode"), "host"),
    "host_ipc_namespace": (("host", "IpcMode"), "host"),
    "host_uts_namespace": (("host", "UTSMode"), "host"),
    "host_cgroup_namespace": (("host", "CgroupnsMode"), "host"),
    "host_device": (("host", "Devices"), [{"PathOnHost": "/dev/sda"}]),
    "gpu_device": (("host", "DeviceRequests"), [{"Count": -1}]),
    "extra_host_override": (("host", "ExtraHosts"), ["gateway:1.2.3.4"]),
    "dns_override": (("host", "Dns"), ["1.1.1.1"]),
    "published_port": (("host", "PortBindings"), {"1234/tcp": [{"HostIp": "0.0.0.0", "HostPort": "1234"}]}),
    "publish_all_ports": (("host", "PublishAllPorts"), True),
    "unbounded_tmpfs": (("host", "Tmpfs"), {"/tmp": "rw"}),
    "network_mode_host": (("host", "NetworkMode"), "host"),
    "additional_external_network": (("networks",), {"green-area-gis-t0-internal": {}, "external": {}}),
    "root_user": (("user",), "0:0"),
    "arbitrary_command": (("command",), ["sh", "-c", "anything"]),
    "custom_entrypoint": (("entrypoint",), ["sh"]),
    "unexpected_workdir": (("workdir",), "/tmp"),
    "wrong_exact_id": (("id",), "d" * 64),
    "wrong_name": (("name",), "/other-worker"),
    "wrong_actual_image": (("image_id",), "sha256:" + "0" * 64),
    "wrong_config_image": (("image",), "python:latest"),
    "wrong_instance_label": (("labels", "gis.t3.instance"), "d" * 32),
    "wrong_run_label": (("labels", "gis.t3.run"), "d" * 32),
    "read_only_home_mount": (("mounts",), [{"Type": "bind", "Source": str(Path.home()), "Destination": "/app/gis_worker", "RW": False}]),
    "read_only_socket_mount": (("mounts",), [{"Type": "bind", "Source": "/var/run/docker.sock", "Destination": "/socket", "RW": False}]),
    "writable_code_mount": (("mounts",), [{"Type": "bind", "Source": str(manager.WORKER_SOURCE), "Destination": "/app/gis_worker", "RW": True}]),
    "shared_bind_propagation": (("mounts",), [{"Type": "bind", "Source": str(manager.WORKER_SOURCE), "Destination": "/app/gis_worker", "RW": False, "Propagation": "rshared"}]),
}
for _name, (_path, _value) in MUTATIONS.items():
    setattr(T3WorkerGuardTests, "test_rejects_" + _name, _mutation_case(_path, _value))


if __name__ == "__main__":
    unittest.main()
