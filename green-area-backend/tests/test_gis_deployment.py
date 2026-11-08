"""A deployment may only reach a target it declared and the project attested.

These cover the seam between configuration and the runtime: an unconfigured
deployment stays exactly as it was, a half-configured one refuses to start
rather than answering 503 forever, and a configured one cannot be talked into
contacting anything other than the project it named.
"""
import re

import pytest
from fastapi import HTTPException

import gis_deployment as dep
from gis_runtime import GISRuntime
from gis_target import TargetError

REF = "abcdefghijklmnopqrst"
API = f"https://{REF}.supabase.co"
HEALTH = API + dep.HEALTH_PATH
INSTANCE = "a" * 32
FINGERPRINT = "b" * 64

COMPLETE = {"GIS_TARGET": "cloud", "GIS_API_URL": API,
            "GIS_RUNTIME_INSTANCE": INSTANCE, "GIS_BASELINE_FINGERPRINT": FINGERPRINT,
            "GIS_ANON_KEY": "anon." + "a" * 40, "GIS_SERVICE_KEY": "service." + "s" * 40}


class FakeResponse:
    def __init__(self, status_code=200, url=HEALTH):
        self.status_code, self.url = status_code, url


class FakeTransport:
    """Records how the attestation client was built and what it was asked for."""

    def __init__(self, response=None, raises=None):
        self.response, self.raises = response or FakeResponse(), raises
        self.options, self.calls = [], []

    def factory(self, **kwargs):
        self.options.append(kwargs)
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get(self, url, headers=None):
        self.calls.append((url, dict(headers or {})))
        if self.raises is not None:
            raise self.raises
        return self.response


def build(environ=None, transport=None, **overrides):
    transport = transport or FakeTransport()
    values = {**COMPLETE, **(environ or {}), **overrides}
    runtime = dep.runtime_from_env(values, client_factory=transport.factory,
                                   create_client=lambda key: ("client", key))
    return runtime, transport


def test_a_deployment_that_declares_nothing_keeps_todays_behaviour():
    # No GIS_TARGET means no runtime, which is what /gis answering 503 means.
    assert dep.runtime_from_env({}) is None
    assert dep.runtime_from_env({"GIS_TARGET": "   "}) is None
    assert dep.runtime_from_env({"OTHER": "cloud"}) is None


def test_the_sandbox_is_never_served_by_a_deployment():
    # dev/gis_local is the only thing that can attest its own containers.
    for value in ("local", "local-t0", "LOCAL"):
        with pytest.raises(dep.DeploymentError, match="GIS_TARGET_LOCAL_NOT_DEPLOYABLE"):
            dep.runtime_from_env({"GIS_TARGET": value})


def test_asking_for_cloud_with_an_unusable_url_raises_instead_of_falling_back():
    for url in ("", "http://" + REF + ".supabase.co", API + "/rest",
                f"https://{REF}.supabase.co.example.invalid", "https://short.supabase.co"):
        with pytest.raises(TargetError):
            dep.runtime_from_env({"GIS_TARGET": "cloud", "GIS_API_URL": url})


@pytest.mark.parametrize("name", ["GIS_RUNTIME_INSTANCE", "GIS_BASELINE_FINGERPRINT",
                                  "GIS_ANON_KEY", "GIS_SERVICE_KEY"])
def test_a_half_configured_deployment_refuses_to_start(name):
    with pytest.raises(dep.DeploymentError, match="GIS_DEPLOYMENT_INCOMPLETE"):
        build(**{name: ""})


@pytest.mark.parametrize("value", [INSTANCE[:-1], INSTANCE + "a", INSTANCE.upper(),
                                   "g" * 32, INSTANCE[:16] + " " + INSTANCE[17:]])
def test_the_database_identity_must_be_the_shape_the_database_reports(value):
    # gis_readiness() returns exactly 32 lowercase hex; anything else could
    # never match, so it is a configuration error, not a runtime one.
    with pytest.raises(dep.DeploymentError, match="GIS_DEPLOYMENT_INCOMPLETE"):
        build(GIS_RUNTIME_INSTANCE=value)


def test_a_value_pasted_with_stray_whitespace_still_works():
    # Deployment consoles add trailing newlines; that is not a misconfiguration.
    runtime, _ = build(GIS_RUNTIME_INSTANCE=f"  {INSTANCE}\n",
                       GIS_BASELINE_FINGERPRINT=f"{FINGERPRINT} ")
    assert runtime.settings.runtime_instance == INSTANCE
    assert runtime.settings.baseline_fingerprint == FINGERPRINT


def test_one_key_cannot_do_both_jobs():
    # Sharing them means either the browser-facing key writes as service_role,
    # or user tokens are verified by a key that bypasses RLS.
    with pytest.raises(dep.DeploymentError, match="GIS_DEPLOYMENT_INCOMPLETE"):
        build(GIS_SERVICE_KEY=COMPLETE["GIS_ANON_KEY"])


def test_a_configured_deployment_is_bound_to_the_project_it_named():
    runtime, transport = build()
    assert isinstance(runtime, GISRuntime)
    settings = runtime.settings
    assert settings.enabled is True
    assert (settings.api_url, settings.cluster, settings.mode, settings.database) == (
        API, REF, "cloud", "postgres")
    assert settings.profile.issuer == API + "/auth/v1"
    assert settings.runtime_instance == INSTANCE and settings.baseline_fingerprint == FINGERPRINT
    # Nothing is switched on that the sandbox does not switch on by default.
    assert settings.sandbox_activation_enabled is False
    assert settings.ldd_publication_enabled is False


def test_the_project_itself_has_to_answer_before_anything_is_trusted():
    runtime, transport = build()
    url, headers = transport.calls[0]
    assert url == HEALTH
    # The anon key, never the service key: this request happens before any
    # credential has been attested.
    assert headers == {"apikey": COMPLETE["GIS_ANON_KEY"]}
    options = transport.options[0]
    assert options["verify"] is True            # the certificate names the project
    assert options["trust_env"] is False        # no proxy from the environment
    assert options["follow_redirects"] is False  # cannot be bounced elsewhere
    assert options["timeout"] == dep.HEALTH_TIMEOUT


@pytest.mark.parametrize("response,raises", [
    (FakeResponse(status_code=401), None),
    (FakeResponse(status_code=404), None),
    (FakeResponse(status_code=500), None),
    (FakeResponse(url="https://example.invalid/auth/v1/health"), None),  # redirected away
    (None, OSError("name or service not known")),
    (None, RuntimeError("proxy failure carrying the url")),
])
def test_a_target_that_does_not_answer_as_itself_never_becomes_a_runtime(response, raises):
    transport = FakeTransport(response=response, raises=raises)
    # GISRuntime turns a failed attestation into the 503 the routes already use.
    with pytest.raises(HTTPException) as caught:
        build(transport=transport)
    assert caught.value.status_code == 503
    assert caught.value.detail["code"] == "GIS_NOT_READY"


def test_the_failure_never_carries_the_configuration():
    transport = FakeTransport(raises=RuntimeError(f"connect to {API} via proxy http://user:pw@host"))
    attest = dep.transport_attestation(
        dep.profile_from_env(COMPLETE), COMPLETE["GIS_ANON_KEY"],
        {"instance": INSTANCE, "baseline_fingerprint": FINGERPRINT},
        client_factory=transport.factory)
    with pytest.raises(dep.DeploymentError) as caught:
        attest()
    assert str(caught.value) == "GIS_TARGET_UNREACHABLE"
    assert caught.value.__cause__ is None


def test_the_attestation_states_the_identity_the_runtime_checks():
    profile = dep.profile_from_env(COMPLETE)
    transport = FakeTransport()
    attest = dep.transport_attestation(profile, "key",
                                       {"instance": INSTANCE, "baseline_fingerprint": FINGERPRINT},
                                       client_factory=transport.factory)
    assert attest() == {"database": "postgres", "cluster": REF, "instance": INSTANCE,
                        "baseline_fingerprint": FINGERPRINT, "containers_healthy": True}
    # A caller cannot keep the dict and edit what the next attestation says.
    proof = attest()
    proof["cluster"] = "green-area-gis-t0"
    assert attest()["cluster"] == REF


def test_clients_are_only_built_for_the_attested_url():
    profile = dep.profile_from_env(COMPLETE)
    build_clients = dep.supabase_clients(profile, "anon-key", "service-key",
                                         create=lambda key: ("client", key))
    assert build_clients(API) == (("client", "anon-key"), ("client", "service-key"))
    for other in ("http://127.0.0.1:55421", API + "/", "https://other.supabase.co"):
        with pytest.raises(dep.DeploymentError, match="GIS_TARGET_INVALID"):
            build_clients(other)


class FakeRpc:
    def __init__(self, data):
        self.data = data

    def execute(self):
        return self


class FakeService:
    """Stands in for the project's PostgREST client."""

    def __init__(self, readiness):
        self.readiness, self.seen = readiness, []

    def rpc(self, name, params):
        self.seen.append((name, params))
        return FakeRpc(self.readiness)


READY = {"runtime_instance": INSTANCE, "database_name": "postgres", "cluster_name": REF,
         "mode": "cloud", "baseline_fingerprint": FINGERPRINT,
         "migration_versions": [27, 28, 29, 30, 31], "contract_version": "1.1.0-t2"}


def runtime_against(readiness):
    service = FakeService(readiness)
    transport = FakeTransport()
    runtime = dep.runtime_from_env(COMPLETE, client_factory=transport.factory,
                                   create_client=lambda key: service)
    return runtime, service


def test_a_hosted_project_that_reports_the_declared_identity_is_ready():
    # This is the whole point of the change: before it, a database that could
    # not set the postmaster's cluster_name could never answer this at all.
    runtime, service = runtime_against(READY)
    assert runtime.require_ready() == READY
    assert service.seen[-1] == ("gis_readiness", {})


@pytest.mark.parametrize("field,value", [
    ("cluster_name", "green-area-gis-t0"),   # a different project answered
    ("mode", "local_synthetic"),             # the sandbox answered
    ("runtime_instance", "c" * 32),          # migrated under another identity
    ("baseline_fingerprint", "d" * 64),
    ("database_name", "gis_t1_upgrade"),
    ("contract_version", "1.0.0-t1"),
])
def test_a_project_that_reports_anything_else_is_refused(field, value):
    runtime, _ = runtime_against({**READY, field: value})
    with pytest.raises(HTTPException) as caught:
        runtime.require_ready()
    assert caught.value.status_code == 503


def test_a_project_missing_the_gis_schema_is_refused():
    runtime, _ = runtime_against({**READY, "migration_versions": [27, 28, 29]})
    with pytest.raises(HTTPException):
        runtime.require_ready()


def test_the_runtime_still_only_calls_rpcs_it_knows():
    runtime, service = runtime_against(READY)
    with pytest.raises(HTTPException):
        runtime.rpc("gis_readiness", {})        # not a command/read entry point
    with pytest.raises(HTTPException):
        runtime.rpc("pg_sleep", {})
    assert runtime.rpc("gis_read", {"q": 1}) == READY


def test_the_health_path_is_stated_once_and_is_a_path():
    # If Supabase ever moves it, one constant is the whole change.
    assert dep.HEALTH_PATH.startswith("/") and re.fullmatch(r"/[a-z0-9/_-]+", dep.HEALTH_PATH)
