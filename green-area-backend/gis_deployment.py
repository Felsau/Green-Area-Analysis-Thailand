"""Build a GIS runtime for a deployment, or decline to build one.

`gis_runtime` never reads the environment: a runtime is handed its target and
its credentials by whoever starts it. The local sandbox is started by
`dev/gis_local/t2_local.py`, which can attest the Docker stack it brought up
itself. A hosted deployment has no containers to look at, so this module
supplies the equivalent proof for one -- a TLS connection to exactly the project
that the declared profile names, with certificate verification on, the
environment's proxy settings ignored, and redirects refused.

That proof is deliberately narrow, and it is only the first of three. It shows
the deployment is talking to the named project over a channel nobody else can
stand in the middle of; it says nothing about what is inside that database. The
database still has to identify itself through `gis_readiness()` before any call
is made, and every RPC proves the target again, exactly as the sandbox does.

Nothing here runs unless a deployment asks for it. With `GIS_TARGET` unset,
`runtime_from_env` returns None and /gis answers 503 as it always has.
"""
from __future__ import annotations

import os
import re

import httpx

from gis_runtime import GISRuntime, LocalGISSettings
from gis_target import TargetProfile, profile_from_env

# Supabase Auth's liveness endpoint, reached through the project's own gateway.
# It is the one request made before any credential is trusted, so if a future
# Supabase release moves it, this constant is the only thing that has to change.
HEALTH_PATH = "/auth/v1/health"
HEALTH_TIMEOUT = 8.0
RPC_TIMEOUT = 15.0

# The identity the database was migrated with. Whoever applied migrations 027+
# to the project chose these values; the backend has to be told the same ones,
# and gis_readiness() refuses the connection if they disagree.
INSTANCE = re.compile(r"[0-9a-f]{32}")
FINGERPRINT = re.compile(r"[0-9a-f]{64}")
# A Supabase API key is a JWT or a publishable/secret key. Only the shape is
# checked here: whether it is the right key is settled by the project itself.
API_KEY = re.compile(r"[A-Za-z0-9._-]{20,512}")


class DeploymentError(RuntimeError):
    """Fixed public code only; never carries a key, a URL or any other value."""


def _require(condition, code):
    if not condition:
        raise DeploymentError(code)


def _setting(environ, name, pattern):
    value = (environ.get(name) or "").strip()
    _require(pattern.fullmatch(value) is not None, "GIS_DEPLOYMENT_INCOMPLETE")
    return value


def transport_attestation(profile: TargetProfile, api_key: str, identity: dict,
                          *, client_factory=httpx.Client):
    """Return an attest() that proves the transport reaches this project.

    The declared identity is only returned once the project itself has answered
    on a verified connection, so a deployment pointed at something that is not
    this Supabase project cannot get past it.
    """
    url = profile.api_url + HEALTH_PATH
    proof = {"database": profile.database, "cluster": profile.cluster,
             "instance": identity["instance"],
             "baseline_fingerprint": identity["baseline_fingerprint"],
             "containers_healthy": True}

    def attest():
        try:
            with client_factory(trust_env=False, follow_redirects=False,
                                timeout=HEALTH_TIMEOUT, verify=True) as client:
                response = client.get(url, headers={"apikey": api_key})
        except Exception:
            # Never surface the transport error: it can name the URL and, in a
            # proxy failure, parts of the environment.
            raise DeploymentError("GIS_TARGET_UNREACHABLE") from None
        _require(response.status_code == 200 and str(response.url) == url,
                 "GIS_TARGET_UNREACHABLE")
        return dict(proof)

    return attest


def _supabase_client(api_url: str, key: str):
    from supabase import ClientOptions, create_client

    transport = httpx.Client(trust_env=False, follow_redirects=False, timeout=RPC_TIMEOUT)
    return create_client(api_url, key, ClientOptions(
        auto_refresh_token=False, persist_session=False,
        httpx_client=transport, postgrest_client_timeout=RPC_TIMEOUT))


def supabase_clients(profile: TargetProfile, anon_key: str, service_key: str, *, create=None):
    """Return a clients(url) that builds the two clients the runtime needs.

    The runtime passes back the URL it attested; building a client for anything
    else is refused rather than quietly followed.
    """
    build_one = create or (lambda key: _supabase_client(profile.api_url, key))

    def build(url):
        _require(url == profile.api_url, "GIS_TARGET_INVALID")
        # Anonymous key first: it is the one that verifies a user's token.
        return build_one(anon_key), build_one(service_key)

    return build


def runtime_from_env(environ=None, *, client_factory=httpx.Client, create_client=None):
    """Build the runtime a deployment declared, or None if it declared none.

    Returning None is the unconfigured case and keeps today's behaviour. Every
    other failure raises, because a deployment that asked for GIS and got the
    configuration wrong should say so at startup instead of answering 503 for
    the rest of its life.
    """
    environ = os.environ if environ is None else environ
    if not (environ.get("GIS_TARGET") or "").strip():
        return None
    profile = profile_from_env(environ)
    # The sandbox can only be attested by the process that started its
    # containers. A deployment asking for it has misconfigured something.
    _require(not profile.is_local, "GIS_TARGET_LOCAL_NOT_DEPLOYABLE")

    instance = _setting(environ, "GIS_RUNTIME_INSTANCE", INSTANCE)
    fingerprint = _setting(environ, "GIS_BASELINE_FINGERPRINT", FINGERPRINT)
    anon_key = _setting(environ, "GIS_ANON_KEY", API_KEY)
    service_key = _setting(environ, "GIS_SERVICE_KEY", API_KEY)
    # One key doing both jobs would mean either the browser-facing key can write
    # as the service role, or user tokens are verified by a key that bypasses RLS.
    _require(anon_key != service_key, "GIS_DEPLOYMENT_INCOMPLETE")

    attest = transport_attestation(profile, anon_key,
                                   {"instance": instance, "baseline_fingerprint": fingerprint},
                                   client_factory=client_factory)
    settings = LocalGISSettings.for_profile(profile, enabled=True,
                                            runtime_instance=instance,
                                            baseline_fingerprint=fingerprint)
    return GISRuntime(settings, attest=attest,
                      clients=supabase_clients(profile, anon_key, service_key, create=create_client))
