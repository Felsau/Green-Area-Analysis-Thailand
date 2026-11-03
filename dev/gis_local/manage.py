"""Isolated local infrastructure scaffolding. No application migrations.

Never print resolved Compose config, complete inspect output, logs or local
keys. Generated development-only values are not copied from host credentials.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid

# -I removes the script directory. Load only this explicit sibling, not the app.
import importlib.util
HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
spec = importlib.util.spec_from_file_location("gis_t0_guard", HERE / "target_guard.py")
guard = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = guard
spec.loader.exec_module(guard)

SERVICES = ("db", "auth", "rest", "gateway")
LIMITS = {"db": (2147483648, 2000000000, 256), "auth": (268435456, 500000000, 128),
          "rest": (268435456, 500000000, 128), "gateway": (536870912, 1000000000, 256)}
UPSTREAM = "https://raw.githubusercontent.com/supabase/supabase/refs/tags/self-hosted/v0.8.3/docker/volumes/db/"
INSPECT = ('{"id":{{json .Id}},"name":{{json .Name}},"image":{{json .Config.Image}},'
           '"labels":{{json .Config.Labels}},"host":{{json .HostConfig}},'
           '"mounts":{{json .Mounts}},"networks":{{json .NetworkSettings.Networks}},'
           '"status":{{json .State.Status}},"health":{{if index .State "Health"}}{{json (index .State "Health" "Status")}}{{else}}null{{end}}}')

# This is an explicit opt-in for the trusted T3 launcher, never API input. The
# default T0/T2 policy still rejects every additional network member.
WORKER_IMAGE = "sha256:fca4560d8a0d0198c0eb75fbf6598314cd8ed4a5e8bafa00e1d7298126aa04c9"
WORKER_COMMAND = ["python3", "-I", "-B", "/app/gis_worker/worker.py"]
WORKER_SOURCE = REPO / "green-area-backend/gis_worker"
WORKER_TMPFS = {"/tmp": "rw,nosuid,noexec,size=32m,mode=1777"}
WORKER_INSPECT = ('{"id":{{json .Id}},"name":{{json .Name}},"image_id":{{json .Image}},'
    '"image":{{json .Config.Image}},"labels":{{json .Config.Labels}},'
    '"user":{{json .Config.User}},"command":{{json .Config.Cmd}},'
    '"entrypoint":{{json .Config.Entrypoint}},"workdir":{{json .Config.WorkingDir}},'
    '"host":{{json .HostConfig}},"mounts":{{json .Mounts}},'
    '"networks":{{json .NetworkSettings.Networks}}}')
WORKER_ENV_NAMES = ('{{range .Config.Env}}{{println (index (split . "=") 0)}}{{end}}')
WORKER_ALLOWED_ENV_NAMES = {"PATH", "LANG", "GPG_KEY", "PYTHON_VERSION", "PYTHON_SHA256",
    "PYTHONDONTWRITEBYTECODE", "PYTHONUNBUFFERED",
    "PYTHON_PIP_VERSION", "PYTHON_SETUPTOOLS_VERSION", "PYTHON_GET_PIP_URL",
    "PYTHON_GET_PIP_SHA256", "OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "GDAL_NUM_THREADS"}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_bind_path(source: str) -> str:
    # Docker Desktop may report the same Windows bind via its Linux VM path.
    match = re.fullmatch(r"/run/desktop/mnt/host/([a-zA-Z])/(.+)", source)
    if os.name == "nt" and match:
        source = match[1] + ":/" + match[2]
    return str(Path(source).resolve()).casefold()


def fingerprint() -> str:
    return digest(b"".join((HERE / name).read_bytes() for name in
                         ("compose.yaml", "local.example.json", "images.lock.json")))


def write_private(path: Path, content: str | bytes) -> None:
    data = content.encode("utf-8") if isinstance(content, str) else content
    with open(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as stream:
        stream.write(data)


class LocalRuntime:
    def __init__(self, root: Path):
        self.root = root.resolve()
        if (self.root == Path(self.root.anchor) or self.root == Path.home()
                or self.root.is_relative_to(REPO) or REPO.is_relative_to(self.root)):
            raise guard.SafetyError("RUNTIME_MUST_BE_SEPARATE_FROM_REPOSITORY")
        self.target = guard.load_config(HERE / "local.example.json")
        if self.target.gis_enabled:
            raise guard.SafetyError("T0_REQUIRES_GIS_DISABLED")
        self.lock = json.loads((HERE / "images.lock.json").read_text(encoding="utf-8"))
        repos = {"db": "supabase/postgres", "auth": "supabase/gotrue",
                 "rest": "postgrest/postgrest", "gateway": "kong/kong"}
        if set(self.lock["images"]) != set(SERVICES) or any(
                not re.fullmatch(re.escape(repos[s]) + r"@sha256:[0-9a-f]{64}", self.lock["images"][s])
                for s in SERVICES):
            raise guard.SafetyError("IMAGE_LOCK_REJECTED")
        self.env = guard.isolated_process_environment(os.environ)
        executable = shutil.which("docker", path=self.env.get("PATH"))
        if not executable:
            raise guard.SafetyError("DOCKER_NOT_FOUND")
        self.base = [executable, "--config", str(self.root / "docker-config"), "--host",
                     "npipe:////./pipe/dockerDesktopLinuxEngine" if os.name == "nt"
                     else "unix:///var/run/docker.sock"]

    def docker(self, args: list[str], *, quiet=False, optional=False, timeout=180) -> str:
        completed = subprocess.run(self.base + args, env=self.env, cwd=self.root,
            stdout=subprocess.DEVNULL if quiet else subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, encoding="utf-8", timeout=timeout)
        if completed.returncode and not optional:
            raise guard.SafetyError("LOCAL_DOCKER_COMMAND_FAILED")
        return "" if quiet or completed.returncode else completed.stdout.strip()

    def owner(self, *, check_fingerprint=True) -> dict:
        owner = json.loads((self.root / "owner.json").read_text(encoding="utf-8"))
        if (owner.get("scope") != guard.SCOPE or owner.get("project") != guard.PROJECT
                or (check_fingerprint and owner.get("fingerprint") != fingerprint())
                or not re.fullmatch(r"[0-9a-f]{32}", owner.get("instance", ""))):
            raise guard.SafetyError("RUNTIME_OWNERSHIP_OR_CONFIG_MISMATCH")
        return owner

    def check_labels(self, labels: dict, *, check_fingerprint=True) -> None:
        if (labels.get("gis.t0.scope") != guard.SCOPE
                or labels.get("gis.t0.instance") != self.owner(check_fingerprint=check_fingerprint)["instance"]
                or labels.get("com.docker.compose.project") != guard.PROJECT):
            raise guard.SafetyError("RESOURCE_OWNERSHIP_REJECTED")

    def compose(self, *args: str) -> None:
        # --env-file plus clean process environment prevents inherited/.env values.
        self.owner()
        self.docker(["compose", "--project-name", guard.PROJECT,
            "--project-directory", str(self.root), "--env-file", str(self.root / "runtime.env"),
            "--file", str(HERE / "compose.yaml"), *args], quiet=True)

    def prepare(self) -> dict:
        if (self.root / "owner.json").exists():
            self.owner()
            return {"prepared": True, "reused": True, "GIS_ENABLED": False}
        if self.root.exists() and any(self.root.iterdir()):
            raise guard.SafetyError("REFUSE_TO_OVERWRITE_EXISTING_RUNTIME")
        self.root.mkdir(parents=True, exist_ok=True)
        config_dir = self.root / "docker-config"
        config_dir.mkdir(exist_ok=True)
        config = {"auths": {}}
        plugin_dir = Path(self.base[0]).parent.parent / "cli-plugins"
        if plugin_dir.is_dir():
            config["cliPluginsExtraDirs"] = [str(plugin_dir)]
        # Only this new empty credential store, never the user's Docker config.
        (config_dir / "config.json").write_text(json.dumps(config), encoding="utf-8")
        vendor = self.root / "vendor"
        vendor.mkdir()
        for name, expected in self.lock["bootstrap"].items():
            if name not in {"roles.sql", "jwt.sql", "webhooks.sql"}:
                raise guard.SafetyError("BOOTSTRAP_FILE_REJECTED")
            with urllib.request.urlopen(UPSTREAM + name, timeout=30) as response:
                data = response.read(65537)
            if len(data) > 65536 or digest(data) != expected:
                raise guard.SafetyError("UPSTREAM_BOOTSTRAP_HASH_MISMATCH")
            write_private(vendor / name, data)
        instance = uuid.uuid4().hex
        password, jwt_secret = secrets.token_hex(24), secrets.token_hex(32)
        def token(role):
            def b64(value):
                return base64.urlsafe_b64encode(json.dumps(value, separators=(",", ":")).encode()).rstrip(b"=")
            payload = b64({"iss": "supabase", "role": role, "iat": int(time.time()),
                           "exp": int(time.time()) + 7 * 86400})
            unsigned = b64({"alg": "HS256", "typ": "JWT"}) + b"." + payload
            signature = base64.urlsafe_b64encode(hmac.new(jwt_secret.encode(), unsigned, hashlib.sha256).digest()).rstrip(b"=")
            return (unsigned + b"." + signature).decode()
        anon, service = token("anon"), token("service_role")
        gateway = """_format_version: '3.0'
_transform: true
consumers:
  - username: local-anon
    keyauth_credentials:
      - key: ANON_VALUE
  - username: local-service
    keyauth_credentials:
      - key: SERVICE_VALUE
plugins:
  - name: cors
    config:
      origins: ['http://127.0.0.1:3000', 'http://localhost:3000']
      methods: [GET, POST, PATCH, DELETE, OPTIONS]
      headers: [Authorization, apikey, Content-Type, Idempotency-Key, X-Client-Info, X-Supabase-Api-Version]
services:
  - name: auth-health
    url: http://auth:9999/health
    routes:
      - name: auth-health
        paths: ['/auth/v1/health']
        strip_path: true
  - name: auth
    url: http://auth:9999/
    routes:
      - name: auth
        paths: ['/auth/v1/']
        strip_path: true
    plugins:
      - name: key-auth
        config:
          key_names: [apikey]
          hide_credentials: false
  - name: rest
    url: http://rest:3000/
    routes:
      - name: rest
        paths: ['/rest/v1/']
        strip_path: true
    plugins:
      - name: key-auth
        config:
          key_names: [apikey]
          hide_credentials: false
""".replace("ANON_VALUE", json.dumps(anon)).replace("SERVICE_VALUE", json.dumps(service))
        write_private(self.root / "kong.yml", gateway)
        values = {"GIS_LOCAL_INSTANCE": instance, "GIS_LOCAL_RUNTIME": self.root.as_posix(),
                  "GIS_LOCAL_DB_PASSWORD": password, "GIS_LOCAL_JWT_SECRET": jwt_secret,
                  "GIS_ENABLED": "false"}
        values.update({f"GIS_LOCAL_{s.upper()}_IMAGE": image for s, image in self.lock["images"].items()})
        write_private(self.root / "runtime.env", "".join(f"{k}={v}\n" for k, v in values.items()))
        write_private(self.root / "owner.json", json.dumps({"scope": guard.SCOPE,
            "project": guard.PROJECT, "instance": instance, "fingerprint": fingerprint()}, indent=2))
        return {"prepared": True, "GIS_ENABLED": False, "local_values_generated": True,
                "credentials_printed": False, "repository_env_loaded": False}

    def metadata(self, service: str) -> dict:
        raw = self.docker(["inspect", "--format", INSPECT, f"{guard.PROJECT}-{service}"], optional=True)
        return json.loads(raw) if raw else {}

    def verify_worker(self, container_id: str, approval: dict) -> dict:
        """Inspect an exact launcher-approved container; never return its env.

        Approval is a process-local record made after docker create, not an
        allowlist inferred from labels supplied by the container itself.
        """
        preparing = isinstance(approval, dict) and set(approval) == {"name", "run_id", "ldd_storage", "prepare_staging"}
        verifying = isinstance(approval, dict) and set(approval) == {"name", "run_id", "ldd_storage", "prepare_staging", "verify_only"} and approval['verify_only'] is True
        ldd = preparing or verifying or isinstance(approval, dict) and set(approval) == {"name", "run_id", "ldd_storage"}
        processing = isinstance(approval, dict) and set(approval) == {"name", "run_id", "processing_legacy"}
        geotiff = isinstance(approval, dict) and set(approval) == {"name", "run_id", "geotiff_storage"}
        if (not isinstance(container_id, str) or not re.fullmatch(r"[0-9a-f]{64}", container_id)
                or not isinstance(approval, dict) or set(approval) != ({"name", "run_id", "ldd_storage", "prepare_staging", "verify_only"} if verifying else {"name", "run_id", "ldd_storage", "prepare_staging"} if preparing else {"name", "run_id", "ldd_storage"} if ldd else {"name", "run_id", "geotiff_storage"} if geotiff else {"name", "run_id", "processing_legacy"} if processing else {"name", "run_id"})
                or (processing and approval['processing_legacy'] is not True)
                or not isinstance(approval["run_id"], str)
                or not re.fullmatch(r"[0-9a-f]{32}", approval["run_id"])
                or approval["name"] != ("gis-ldd-verify-" if verifying else "gis-ldd-prepare-worker-" if preparing else "gis-ldd-worker-" if ldd else "gis-geotiff-worker-" if geotiff else "gis-processing-worker-" if processing else "gis-t3-worker-") + approval["run_id"][:12]):
            raise guard.SafetyError("WORKER_EXPLICIT_APPROVAL_REQUIRED")
        try:
            item = json.loads(self.docker(["inspect", "--format", WORKER_INSPECT, container_id]))
            if not isinstance(item, dict):
                raise ValueError()
            owner = self.owner()
            labels = {"gis.t3.scope": "gis-worker-t3", "gis.t3.instance": owner["instance"],
                "gis.t3.run": approval["run_id"], "com.docker.compose.project": guard.PROJECT}
            if preparing or verifying:
                labels = {"gis.a2.scope": "ldd-verify" if verifying else "ldd-prepare", "gis.a2.instance": owner["instance"],
                    "gis.a2.run": approval["run_id"], "com.docker.compose.project": guard.PROJECT}
            elif ldd:
                labels = {"gis.phase2.scope": "ldd-worker", "gis.phase2.instance": owner["instance"],
                    "gis.phase2.run": approval["run_id"], "com.docker.compose.project": guard.PROJECT}
            elif processing:
                labels = {"gis.phase3.scope": "processing-worker", "gis.phase3.instance": owner["instance"],
                    "gis.phase3.run": approval["run_id"], "com.docker.compose.project": guard.PROJECT}
            elif geotiff:
                labels = {"gis.phase4.scope": "geotiff-worker", "gis.phase4.instance": owner["instance"],
                    "gis.phase4.run": approval["run_id"], "com.docker.compose.project": guard.PROJECT}
            if (item["id"] != container_id or item["name"] != "/" + approval["name"]
                    or item["labels"] != labels or item["image"] != WORKER_IMAGE
                    or item["image_id"] != WORKER_IMAGE):
                raise guard.SafetyError("WORKER_IDENTITY_OR_IMAGE_REJECTED")
            command = ["python3", "-I", "-B", "/app/gis_worker/ldd_prepare_child.py", "--verify"] if verifying else ["python3", "-I", "-B", "/app/gis_worker/ldd_prepare_worker.py"] if preparing else ["python3", "-I", "-B", "/app/gis_worker/ldd_worker.py"] if ldd else ["python3", "-I", "-B", "/app/gis_worker/geotiff_worker.py"] if geotiff else ["python3", "-I", "-B", "/app/gis_worker/processing_worker.py"] if processing else WORKER_COMMAND
            if (item["user"] != "65534:65534" or item["command"] != command
                    or item["entrypoint"] not in (None, []) or item["workdir"] != "/app/gis_worker"):
                raise guard.SafetyError("WORKER_PROCESS_CONFIG_REJECTED")
            host = item["host"]
            expected = {"Memory": 1073741824, "MemorySwap": 1073741824,
                "NanoCpus": 1000000000, "PidsLimit": 64, "Privileged": False,
                "ReadonlyRootfs": True, "Init": True,
                "NetworkMode": "none" if verifying else f"{guard.PROJECT}-internal"}
            if any(type(host.get(key)) is not type(value) or host.get(key) != value
                    for key, value in expected.items()):
                raise guard.SafetyError("WORKER_LIMITS_REJECTED")
            if (set(host.get("CapDrop") or []) != {"ALL"} or host.get("CapAdd")
                    or set(host.get("SecurityOpt") or []) != {"no-new-privileges:true"}
                    or host.get("PidMode") or host.get("UTSMode")
                    or host.get("IpcMode") not in (None, "", "private")
                    or host.get("CgroupnsMode") not in (None, "", "private")
                    or host.get("Devices") or host.get("DeviceRequests")
                    or host.get("DeviceCgroupRules") or host.get("ExtraHosts")
                    or host.get("Dns") or host.get("DnsOptions") or host.get("DnsSearch")
                    or host.get("Links") or host.get("VolumesFrom")):
                raise guard.SafetyError("WORKER_PRIVILEGES_OR_NAMESPACE_REJECTED")
            if (set(item["networks"]) != ({"none"} if verifying else {f"{guard.PROJECT}-internal"})
                    or host.get("PortBindings") or host.get("PublishAllPorts")):
                raise guard.SafetyError("WORKER_NETWORK_OR_PORT_REJECTED")
            if host.get("Tmpfs") != WORKER_TMPFS:
                raise guard.SafetyError("WORKER_TMPFS_REJECTED")
            binds = []
            for mount in item["mounts"]:
                if mount["Type"] == "bind":
                    binds.append((canonical_bind_path(mount["Source"]), mount["Destination"], mount["RW"]))
                    if mount.get("Propagation", "rprivate") not in ("", "private", "rprivate"):
                        raise guard.SafetyError("WORKER_UNSAFE_MOUNT_REJECTED")
                elif mount["Type"] == "tmpfs" and mount["Destination"] == "/tmp":
                    continue
                else:
                    raise guard.SafetyError("WORKER_UNSAFE_MOUNT_REJECTED")
            expected_binds = [(canonical_bind_path(str(WORKER_SOURCE)), "/app/gis_worker", False)]
            if ldd or geotiff:
                storage = self.root / ("geotiff-storage" if geotiff else "ldd-storage")
                objects = storage / "objects"
                if (canonical_bind_path(str(objects)) != approval["geotiff_storage" if geotiff else "ldd_storage"]
                    or storage.is_symlink() or objects.is_symlink()
                    or not storage.is_dir() or not objects.is_dir()
                    or any(getattr(p, "is_junction", lambda: False)() or bool(getattr(p.lstat(), "st_file_attributes", 0)
                        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)) for p in (storage, objects))):
                    raise guard.SafetyError("WORKER_STORAGE_SOURCE_REJECTED")
                marker_path = storage / "owner.json"
                if marker_path.is_symlink():
                    raise guard.SafetyError("WORKER_STORAGE_SOURCE_REJECTED")
                marker = json.loads(marker_path.read_text(encoding="utf-8"))
                if (set(marker) != {"scope", "runtime_instance", "baseline_fingerprint", "database", "cluster"}
                    or marker["scope"] != ("gis-geotiff-storage-v1" if geotiff else "gis-ldd-storage-v1") or marker["runtime_instance"] != owner["instance"]
                    or marker["database"] != "postgres" or marker["cluster"] != guard.PROJECT
                    or not re.fullmatch(r"[a-f0-9]{64}", marker["baseline_fingerprint"])):
                    raise guard.SafetyError("WORKER_STORAGE_SOURCE_REJECTED")
                expected_binds.append((canonical_bind_path(str(objects)), "/data/geotiff/objects" if geotiff else "/data/ldd", False))
                if preparing or verifying:
                    prepared = self.root / 'ldd-prepared'
                    staging = prepared / 'staging'
                    for path in (prepared, staging, prepared / 'owner.json'):
                        if (path.is_symlink() or getattr(path, 'is_junction', lambda: False)()
                            or bool(getattr(path.lstat(), 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0))):
                            raise guard.SafetyError('WORKER_PREPARE_STORAGE_REJECTED')
                    prepared_owner = json.loads((prepared / 'owner.json').read_text(encoding='utf-8'))
                    if (not staging.is_dir() or canonical_bind_path(str(staging)) != approval['prepare_staging']
                        or prepared_owner != {**marker, 'scope': 'gis-ldd-prepared-v1'}):
                        raise guard.SafetyError('WORKER_PREPARE_STORAGE_REJECTED')
                    expected_binds.append((canonical_bind_path(str(staging)), '/data/prepare', not verifying))
            elif processing:
                legacy_sources = {'gee_utils.py': WORKER_SOURCE.parent / 'gee_utils.py',
                    'ndvi_compute.py': WORKER_SOURCE.parent / 'routers/ndvi/compute.py',
                    'lst.py': WORKER_SOURCE.parent / 'routers/lst.py'}
                for target, source in legacy_sources.items():
                    if (not source.is_file() or source.is_symlink() or any(p.is_symlink()
                        or bool(getattr(p.lstat(), 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0))
                        for p in (source, *source.parents))):
                        raise guard.SafetyError('WORKER_LEGACY_SOURCE_REJECTED')
                    expected_binds.append((canonical_bind_path(str(source)), '/app/legacy/' + target, False))
            if sorted(binds) != sorted(expected_binds):
                raise guard.SafetyError("WORKER_EXACT_MOUNTS_REJECTED")
            # Docker emits names only, so a rejected environment never exposes a
            # credential value to this process, logs or the reviewer report.
            names = self.docker(["inspect", "--format", WORKER_ENV_NAMES, container_id]).splitlines()
            if any(name not in WORKER_ALLOWED_ENV_NAMES for name in names):
                raise guard.SafetyError("WORKER_ENVIRONMENT_REJECTED")
            return {"id": container_id, "name": approval["name"], "run_id": approval["run_id"]}
        except guard.SafetyError:
            raise
        except Exception:
            raise guard.SafetyError("WORKER_INSPECTION_REJECTED") from None

    def verify_containers(self, *, approved_workers: dict | None = None) -> dict:
        self.owner()
        if approved_workers is None:
            approved_workers = {}
        if not isinstance(approved_workers, dict) or len(approved_workers) > 4:
            raise guard.SafetyError("WORKER_EXPLICIT_APPROVAL_REQUIRED")
        approved = {cid: self.verify_worker(cid, policy) for cid, policy in approved_workers.items()}
        verified = {}
        for service in SERVICES:
            item = self.metadata(service)
            if not item:
                raise guard.SafetyError("LOCAL_CONTAINER_MISSING")
            self.check_labels(item["labels"])
            host = item["host"]
            memory, cpu, pids = LIMITS[service]
            if (item["image"] != self.lock["images"][service] or host["Privileged"]
                    or host["Memory"] != memory or host["MemorySwap"] != memory
                    or host["NanoCpus"] != cpu or host["PidsLimit"] != pids
                    or host["NetworkMode"] not in ({f"{guard.PROJECT}-internal", f"{guard.PROJECT}-ingress"}
                         if service == "gateway" else {f"{guard.PROJECT}-internal"})
                    or "ALL" not in (host["CapDrop"] or [])
                    or "no-new-privileges:true" not in (host["SecurityOpt"] or [])
                    or (service != "db" and not host["ReadonlyRootfs"])):
                raise guard.SafetyError("CONTAINER_LIMITS_OR_IMAGE_REJECTED")
            expected_networks = {f"{guard.PROJECT}-internal"}
            if service == "gateway":
                expected_networks.add(f"{guard.PROJECT}-ingress")
            if set(item["networks"]) != expected_networks:
                raise guard.SafetyError("ADDITIONAL_NETWORK_REJECTED")
            added = {c.removeprefix("CAP_") for c in (host["CapAdd"] or [])}
            expected_caps = {"CHOWN", "DAC_OVERRIDE", "FOWNER", "SETGID", "SETUID"} if service == "db" else set()
            if added != expected_caps or host.get("PidMode", "") or host.get("IpcMode") == "host":
                raise guard.SafetyError("CAPABILITIES_OR_HOST_NAMESPACE_REJECTED")
            ports = host["PortBindings"] or {}
            expected_ports = {"gateway": {"8000/tcp": [{"HostIp": "127.0.0.1", "HostPort": "55421"}]}}
            if ports != expected_ports.get(service, {}):
                raise guard.SafetyError("PUBLISHED_PORTS_REJECTED")
            expected_mounts = set()
            if service == "db":
                expected_mounts = {
                    ("volume", f"{guard.PROJECT}-data", "/var/lib/postgresql/data", True),
                    ("volume", f"{guard.PROJECT}-db-config", "/etc/postgresql-custom", True),
                    ("bind", canonical_bind_path(str(self.root / "vendor/webhooks.sql")),
                     "/docker-entrypoint-initdb.d/init-scripts/98-webhooks.sql", False),
                    ("bind", canonical_bind_path(str(self.root / "vendor/roles.sql")),
                     "/docker-entrypoint-initdb.d/init-scripts/99-roles.sql", False),
                    ("bind", canonical_bind_path(str(self.root / "vendor/jwt.sql")),
                     "/docker-entrypoint-initdb.d/init-scripts/99-jwt.sql", False)}
            elif service == "gateway":
                expected_mounts = {("bind", canonical_bind_path(str(self.root / "kong.yml")),
                                    "/home/kong/kong.yml", False)}
            observed_mounts = set()
            for mount in item["mounts"]:
                if mount["Type"] == "bind":
                    observed_mounts.add(("bind", canonical_bind_path(mount["Source"]),
                                         mount["Destination"], mount["RW"]))
                elif mount["Type"] == "volume":
                    observed_mounts.add(("volume", mount["Name"], mount["Destination"], mount["RW"]))
                elif mount["Type"] != "tmpfs":
                    raise guard.SafetyError("MOUNT_TYPE_REJECTED")
            if observed_mounts != expected_mounts:
                raise guard.SafetyError("EXACT_MOUNTS_REJECTED")
            if service == "gateway":
                # Docker evaluates equality internally; return only a nonsecret
                # boolean, never the environment array or any other value.
                reports_off = self.docker(["inspect", "--format",
                    '{{range .Config.Env}}{{if eq . "KONG_ANONYMOUS_REPORTS=off"}}true{{end}}{{end}}', item["id"]])
                if reports_off != "true":
                    raise guard.SafetyError("GATEWAY_TELEMETRY_MUST_BE_DISABLED")
            verified[service] = item
        for suffix, internal in (("internal", True), ("ingress", False)):
            network = json.loads(self.docker(["network", "inspect", "--format",
                '{"internal":{{json .Internal}},"labels":{{json .Labels}},"driver":{{json .Driver}},"containers":{{json .Containers}}}',
                f"{guard.PROJECT}-{suffix}"]))
            self.check_labels(network["labels"])
            if network["internal"] is not internal or network["driver"] != "bridge":
                raise guard.SafetyError("EXTERNAL_NETWORK_REJECTED")
            permitted = {verified[s]["id"] for s in (SERVICES if internal else ("gateway",))}
            extra = set(network["containers"] or {}) - permitted
            if extra - (set(approved) if internal else set()):
                raise guard.SafetyError("FOREIGN_NETWORK_MEMBER_REJECTED")
        for name in ("data", "db-config"):
            labels = json.loads(self.docker(["volume", "inspect", "--format", "{{json .Labels}}",
                                            f"{guard.PROJECT}-{name}"]))
            self.check_labels(labels)
        return verified

    def wait_healthy(self, service: str) -> None:
        end = time.monotonic() + 180
        while time.monotonic() < end:
            item = self.metadata(service)
            if item.get("health") == "healthy":
                return
            if item.get("status") in {"exited", "dead"}:
                raise guard.SafetyError("LOCAL_SERVICE_EXITED_" + service.upper())
            time.sleep(2)
        raise guard.SafetyError("LOCAL_HEALTH_TIMEOUT_" + service.upper())

    def start(self) -> dict:
        self.owner()
        info = json.loads(self.docker(["info", "--format",
            '{"OSType":{{json .OSType}},"Architecture":{{json .Architecture}},"MemTotal":{{json .MemTotal}}}']))
        if info["OSType"] != "linux" or info["Architecture"] not in {"x86_64", "amd64"} or info["MemTotal"] < 4 * 1024**3:
            raise guard.SafetyError("LINUX_RUNTIME_NOT_READY")
        if shutil.disk_usage(self.root).free < 10 * 1024**3:
            raise guard.SafetyError("LOCAL_DISK_BUDGET_NOT_READY")
        for service in SERVICES:
            item = self.metadata(service)
            if item:
                self.check_labels(item["labels"])
        for service, port in (("gateway", 55421),):
            if self.metadata(service).get("status") != "running":
                try:
                    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                            probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                        probe.bind(("127.0.0.1", port))
                except OSError:
                    raise guard.SafetyError("LOCAL_PORT_ALREADY_IN_USE") from None
        for name in ("data", "db-config"):
            labels = self.docker(["volume", "inspect", "--format", "{{json .Labels}}", f"{guard.PROJECT}-{name}"], optional=True)
            if labels:
                self.check_labels(json.loads(labels))
        for suffix in ("internal", "ingress"):
            existing_network = self.docker(["network", "inspect", "--format", "{{json .Labels}}", f"{guard.PROJECT}-{suffix}"], optional=True)
            if existing_network:
                self.check_labels(json.loads(existing_network))
        for service in SERVICES:
            image = self.lock["images"][service]
            if not self.docker(["image", "inspect", "--format", "{{.Id}}", image], optional=True):
                self.docker(["pull", image], quiet=True, timeout=600)
        self.compose("config", "--quiet")
        self.compose("create")
        items = self.verify_containers()  # Inspect limits/mounts/ports BEFORE start.
        for service in SERVICES:
            self.docker(["start", items[service]["id"]], quiet=True)
            self.wait_healthy(service)
        return self.verify()

    def verify(self) -> dict:
        items = self.verify_containers()
        if any(i["status"] != "running" or i["health"] != "healthy" for i in items.values()):
            raise guard.SafetyError("LOCAL_SERVICES_NOT_HEALTHY")
        sql = """SELECT json_build_object('database',current_database(),
          'version',current_setting('server_version'),'cluster',current_setting('cluster_name'),
          'auth_schema',EXISTS(SELECT 1 FROM pg_namespace WHERE nspname='auth'),
          'gis_schema',EXISTS(SELECT 1 FROM pg_namespace WHERE nspname='gis'),
          'legacy_tables',(SELECT count(*) FROM information_schema.tables WHERE table_schema='public'
            AND table_name IN ('profiles','provinces','ndvi_annual','saved_areas','processing_jobs')),
          'auth_users',(SELECT count(*) FROM auth.users))::text;"""
        db = json.loads(self.docker(["exec", items["db"]["id"], "psql", "-X", "-U", "postgres",
             "-d", "postgres", "-At", "-v", "ON_ERROR_STOP=1", "-c", sql]))
        valid_db = db["database"] == "postgres" and db["cluster"] == guard.PROJECT and db["auth_schema"] is True
        no_app = db["gis_schema"] is False and db["legacy_tables"] == 0
        proof = guard.LocalProof(guard.PROJECT, guard.API_URL, self.owner()["instance"], True, True, valid_db, no_app)
        guard.require_ready(self.target, proof)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        codes = {}
        for path, expected in (("/auth/v1/health", 200), ("/rest/v1/", 401)):
            try:
                with opener.open(guard.API_URL + path, timeout=5) as response:
                    code = response.status
            except urllib.error.HTTPError as error:
                code = error.code
            if code != expected:
                raise guard.SafetyError("LOCAL_GATEWAY_HEALTH_REJECTED")
            codes[path] = code
        return {"ready": True, "GIS_ENABLED": False, "app_mutations_enabled": False,
                "services": {s: {"id": i["id"], "health": i["health"], "image": i["image"]}
                             for s, i in items.items()}, "postgres": db, "public_health": codes,
                "internal_network": True, "gateway_ingress_bridge": True,
                "gateway_has_potential_egress": True, "database_host_port_published": False,
                "gateway_telemetry_disabled_verified": True,
                "limits_verified_before_start": True,
                "repository_migrations_run": False, "manager_cloud_operations": False}

    def stop(self) -> dict:
        # Config edits must not prevent stopping exactly-owned old containers.
        self.owner(check_fingerprint=False)
        stopped = []
        for service in reversed(SERVICES):
            item = self.metadata(service)
            if item:
                self.check_labels(item["labels"], check_fingerprint=False)
                self.docker(["stop", "--time", "15", item["id"]], quiet=True)
                stopped.append(service)
        return {"stopped_owned_services": stopped, "volumes_preserved": True}

    def reconfigure(self) -> dict:
        """Explicit acknowledgement after a reviewed config edit; no DB actions."""
        owner = self.owner(check_fingerprint=False)
        for service in SERVICES:
            item = self.metadata(service)
            if item:
                self.check_labels(item["labels"], check_fingerprint=False)
                if item["status"] not in {"created", "exited"}:
                    raise guard.SafetyError("STOP_OWNED_SERVICES_BEFORE_RECONFIGURE")
        owner["fingerprint"] = fingerprint()
        (self.root / "owner.json").write_text(json.dumps(owner, indent=2), encoding="utf-8")
        return {"configuration_acknowledged": True, "database_changed": False}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise guard.SafetyError("LOCAL_HTTP_REDIRECT_REJECTED")


def main() -> int:
    parser = argparse.ArgumentParser(description="T0 local infrastructure only; never prints local keys.")
    parser.add_argument("action", choices=("prepare", "start", "verify", "stop", "reconfigure"))
    parser.add_argument("--runtime-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        runtime = LocalRuntime(args.runtime_dir)
        result = getattr(runtime, args.action)()
        print(json.dumps(result, ensure_ascii=True, indent=2))
        return 0
    except (guard.SafetyError, OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        code = str(error) if isinstance(error, guard.SafetyError) else "LOCAL_OPERATION_FAILED"
        print(json.dumps({"ok": False, "code": code, "raw_diagnostics_suppressed": True}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
