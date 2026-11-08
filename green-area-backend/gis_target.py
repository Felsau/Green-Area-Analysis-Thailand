"""The declared target a GIS runtime is allowed to talk to.

The GIS feature refuses to run unless it is pointed at a target that was
declared in advance and then attested at run time. Until now the only target
that could ever be declared was the local T0 sandbox, and its identity was
written into the code as literals in a dozen modules. That made the identity
impossible to get wrong, and also impossible to change.

The identity now lives in one profile object instead. The local sandbox keeps
exactly the values it had, as the default profile, so nothing about it moves.
A second profile describes a hosted Supabase project and takes its identity
from configuration. Selecting it is explicit: an unset or unknown selection is
the local sandbox, never the hosted project.

Declaring a target here does not grant access to it. Every caller still has to
pass the attestation and readiness checks in `gis_runtime`, which compare the
profile against what the database itself reports.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
import re

# The local T0 sandbox, unchanged. These two names are re-exported by
# gis_runtime because modules across the worker and storage layers import them.
LOCAL_URL = "http://127.0.0.1:55421"
LOCAL_CLUSTER = "green-area-gis-t0"
LOCAL_MODE = "local_synthetic"

CLOUD_MODE = "cloud"

# A Supabase project ref: twenty lowercase letters, used as both the API
# hostname label and the cluster identity stored in gis.environment.
PROJECT_REF = re.compile(r"^[a-z]{20}$")
CLOUD_API_URL = re.compile(r"^https://([a-z]{20})\.supabase\.co$")


class TargetError(ValueError):
    """Fixed public code only; never carries configuration values."""


def _require(condition, code):
    if not condition:
        raise TargetError(code)


@dataclass(frozen=True)
class TargetProfile:
    """One declared target. Frozen, self-checking, and never partially valid."""

    name: str
    api_url: str
    database: str
    cluster: str
    mode: str

    def __post_init__(self):
        _require(self.name in ("local-t0", "cloud"), "GIS_TARGET_UNKNOWN")
        _require(self.database == "postgres", "GIS_TARGET_INVALID")
        if self.name == "local-t0":
            _require(self.api_url == LOCAL_URL and self.cluster == LOCAL_CLUSTER
                     and self.mode == LOCAL_MODE, "GIS_TARGET_INVALID")
            return
        match = CLOUD_API_URL.fullmatch(self.api_url)
        # The cluster identity must be the project the API URL already names,
        # so a profile cannot point at one project and claim another.
        _require(match is not None and self.cluster == match.group(1)
                 and PROJECT_REF.fullmatch(self.cluster) is not None
                 and self.mode == CLOUD_MODE, "GIS_TARGET_INVALID")

    @property
    def issuer(self) -> str:
        return self.api_url + "/auth/v1"

    @property
    def is_local(self) -> bool:
        return self.name == "local-t0"


LOCAL_T0 = TargetProfile(name="local-t0", api_url=LOCAL_URL, database="postgres",
                         cluster=LOCAL_CLUSTER, mode=LOCAL_MODE)


def cloud_profile(api_url: str) -> TargetProfile:
    """Build the hosted profile from a Supabase API URL alone."""
    _require(isinstance(api_url, str), "GIS_TARGET_INVALID")
    match = CLOUD_API_URL.fullmatch(api_url.strip().rstrip("/"))
    _require(match is not None, "GIS_TARGET_INVALID")
    return TargetProfile(name="cloud", api_url=match.group(0), database="postgres",
                         cluster=match.group(1), mode=CLOUD_MODE)


def profile_from_env(environ=None) -> TargetProfile:
    """Select a profile from configuration.

    Anything other than an explicit `GIS_TARGET=cloud` with a usable
    `GIS_API_URL` is the local sandbox. Selecting the hosted profile with a
    malformed URL raises rather than silently falling back to local, because a
    deployment that meant to be hosted must not quietly become something else.
    """
    environ = os.environ if environ is None else environ
    selected = (environ.get("GIS_TARGET") or "").strip().lower()
    if selected in ("", "local", "local-t0"):
        return LOCAL_T0
    _require(selected == "cloud", "GIS_TARGET_UNKNOWN")
    return cloud_profile(environ.get("GIS_API_URL") or "")
