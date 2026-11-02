"""T0-only safety scaffolding. Stdlib only; no dotenv, app, DB or GEE imports.

This does not implement a GIS API or database authorization. T1 must add a
database identity check; T2 must wire the guard into the actual write boundary.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import Callable, Mapping, TypeVar
from urllib.parse import urlsplit

PROJECT = "green-area-gis-t0"
SCOPE = "gis-foundation-t0"
API_URL = "http://127.0.0.1:55421"
DATABASE = {"host": "db", "port": 5432, "name": "postgres"}
EXPECTED = {"version": 1, "mode": "local", "project": PROJECT,
            "api_url": API_URL, "database": DATABASE}
CONFIG_KEYS = set(EXPECTED) | {"GIS_ENABLED"}
UNSAFE_EXACT = {"DATABASE_URL", "GOOGLE_APPLICATION_CREDENTIALS", "ADMIN_TOKEN",
                "PGPASSWORD", "PGSERVICE", "PGSERVICEFILE", "PGPASSFILE"}
UNSAFE_PREFIXES = ("SUPABASE_", "VITE_SUPABASE_", "GEE_", "EE_CREDENTIALS", "PGHOST", "PGPORT")


class SafetyError(ValueError):
    """Safe diagnostic code: never include rejected input values or secrets."""


@dataclass(frozen=True)
class LocalTarget:
    project: str
    api_url: str
    database_host: str
    database_port: int
    database_name: str
    gis_enabled: bool = False


@dataclass(frozen=True)
class LocalProof:
    """Trusted preflight, never client input. Internal network = data backplane.

    The loopback gateway also has a dedicated ingress bridge, not zero egress.
    DB DNS 'db' is valid only in this verified Docker network, not on the host.
    """
    project: str
    api_url: str
    instance: str
    containers_verified: bool
    internal_network: bool
    postgres_verified: bool
    no_application_schema: bool


def validate_config(raw: object) -> LocalTarget:
    if not isinstance(raw, dict) or set(raw) - CONFIG_KEYS:
        raise SafetyError("CONFIG_FIELDS_REJECTED")
    for key, value in EXPECTED.items():
        if key not in raw or type(raw[key]) is not type(value) or raw[key] != value:
            raise SafetyError("LOCAL_ALLOWLIST_MISMATCH")
    db = raw["database"]
    if set(db) != set(DATABASE) or type(db["port"]) is not int:
        raise SafetyError("DATABASE_TARGET_REJECTED")
    enabled = raw.get("GIS_ENABLED", False)
    if type(enabled) is not bool:
        raise SafetyError("FEATURE_FLAG_MUST_BE_BOOLEAN")
    parsed = urlsplit(raw["api_url"])
    if (parsed.scheme != "http" or parsed.hostname != "127.0.0.1"
            or parsed.port != 55421 or parsed.username is not None
            or parsed.password is not None or parsed.path or parsed.query or parsed.fragment):
        raise SafetyError("LOCAL_URL_REJECTED")
    return LocalTarget(PROJECT, API_URL, db["host"], db["port"], db["name"], enabled)


def load_config(path: Path) -> LocalTarget:
    resolved = path.resolve(strict=True)
    if resolved.name not in {"local.example.json", "local.json"} or resolved.stat().st_size > 8192:
        raise SafetyError("EXPLICIT_LOCAL_CONFIG_REQUIRED")
    try:
        return validate_config(json.loads(resolved.read_text(encoding="utf-8-sig")))
    except (UnicodeError, json.JSONDecodeError):
        raise SafetyError("INVALID_LOCAL_CONFIG") from None


def reject_ambient_service_config(environment: Mapping[str, str]) -> None:
    # Inspect names only, not values. Do not echo even the rejected variable.
    if any(key.upper() in UNSAFE_EXACT or key.upper().startswith(UNSAFE_PREFIXES)
           for key in environment):
        raise SafetyError("AMBIENT_SERVICE_CONFIG_REJECTED")


def isolated_process_environment(environment: Mapping[str, str]) -> dict[str, str]:
    # Compose must not inherit variables which override its explicit env file.
    names = {"PATH", "SYSTEMROOT", "SYSTEMDRIVE", "COMSPEC", "TEMP", "TMP",
             "WINDIR", "PATHEXT", "LANG", "LC_ALL"}
    return {key: environment[key] for key in environment if key.upper() in names}


def require_ready(target: LocalTarget, proof: LocalProof | None) -> None:
    # Revalidate a constructed dataclass too, not just JSON input.
    validate_config({**EXPECTED, "api_url": target.api_url, "project": target.project,
                     "database": {"host": target.database_host, "port": target.database_port,
                                  "name": target.database_name}, "GIS_ENABLED": target.gis_enabled})
    if proof is None or not isinstance(proof, LocalProof):
        raise SafetyError("TRUSTED_LOCAL_PROOF_REQUIRED")
    if (proof.project != target.project or proof.api_url != target.api_url
            or not isinstance(proof.instance, str) or len(proof.instance) != 32
            or any(c not in "0123456789abcdef" for c in proof.instance)
            or any(value is not True for value in (proof.containers_verified,
                proof.internal_network, proof.postgres_verified, proof.no_application_schema))):
        raise SafetyError("LOCAL_PROOF_REJECTED")


T = TypeVar("T")


def guarded_test_mutation(target: LocalTarget, proof: LocalProof | None,
                          mutation: Callable[[], T]) -> T:
    """Test seam only: no SQL or production operation is provided by T0."""
    require_ready(target, proof)
    if not target.gis_enabled:
        raise SafetyError("GIS_FEATURE_DISABLED")
    return mutation()


def main() -> int:
    parser = argparse.ArgumentParser(description="Check explicit local config without connecting.")
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    try:
        reject_ambient_service_config(os.environ)
        target = load_config(args.config)
        print(json.dumps({"config_valid": True, "GIS_ENABLED": target.gis_enabled,
                          "connected": False, "mutation_ready": False}))
        return 0
    except (SafetyError, OSError) as error:
        print(json.dumps({"config_valid": False,
                          "code": str(error) if isinstance(error, SafetyError) else "CONFIG_IO_ERROR"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
