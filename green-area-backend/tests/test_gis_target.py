"""The declared target must be exactly what was configured, or nothing."""
import pytest

from gis_runtime import LOCAL_ISSUER, LOCAL_URL, LocalGISSettings
from gis_target import (CLOUD_MODE, LOCAL_T0, TargetError, TargetProfile,
                        cloud_profile, profile_from_env)

REF = "abcdefghijklmnopqrst"
CLOUD_URL = f"https://{REF}.supabase.co"


def test_local_profile_keeps_the_sandbox_identity_unchanged():
    assert (LOCAL_T0.api_url, LOCAL_T0.database, LOCAL_T0.cluster, LOCAL_T0.mode) == (
        "http://127.0.0.1:55421", "postgres", "green-area-gis-t0", "local_synthetic")
    assert LOCAL_T0.issuer == "http://127.0.0.1:55421/auth/v1"
    assert LOCAL_T0.is_local is True
    # gis_runtime re-exports these for the storage, worker and mock layers.
    assert (LOCAL_URL, LOCAL_ISSUER) == (LOCAL_T0.api_url, LOCAL_T0.issuer)


def test_cloud_profile_takes_its_cluster_from_the_url_it_names():
    profile = cloud_profile(CLOUD_URL)
    assert (profile.name, profile.cluster, profile.mode) == ("cloud", REF, CLOUD_MODE)
    assert profile.issuer == CLOUD_URL + "/auth/v1"
    assert profile.is_local is False
    assert cloud_profile(CLOUD_URL + "/") == profile


@pytest.mark.parametrize("url", [
    f"http://{REF}.supabase.co",                 # plaintext
    f"https://{REF}.supabase.co:8443",           # explicit port
    f"https://{REF}.supabase.co/rest/v1",        # path
    f"https://{REF}.supabase.co?x=1",            # query
    f"https://user:pw@{REF}.supabase.co",        # credentials
    f"https://{REF}.evil.co",                    # lookalike host
    f"https://{REF[:19]}.supabase.co",           # ref too short
    "https://.supabase.co", "", "   ", LOCAL_URL,
])
def test_cloud_profile_rejects_anything_but_a_clean_project_url(url):
    with pytest.raises(TargetError):
        cloud_profile(url)


def test_a_profile_cannot_name_one_project_and_claim_another():
    with pytest.raises(TargetError):
        TargetProfile(name="cloud", api_url=CLOUD_URL, database="postgres",
                      cluster="u" * 20, mode=CLOUD_MODE)


@pytest.mark.parametrize("field,value", [
    ("api_url", "http://127.0.0.1:9999"), ("cluster", "other-cluster"),
    ("mode", CLOUD_MODE), ("database", "gis_t1_upgrade"),
])
def test_the_local_profile_cannot_be_rebuilt_with_different_values(field, value):
    values = dict(name="local-t0", api_url=LOCAL_URL, database="postgres",
                  cluster="green-area-gis-t0", mode="local_synthetic")
    with pytest.raises(TargetError):
        TargetProfile(**{**values, field: value})


@pytest.mark.parametrize("environ", [
    {}, {"GIS_TARGET": ""}, {"GIS_TARGET": "local"}, {"GIS_TARGET": "local-t0"},
    # A hosted URL alone is not a selection; the target has to be asked for.
    {"GIS_API_URL": CLOUD_URL},
])
def test_an_unselected_target_is_the_local_sandbox(environ):
    assert profile_from_env(environ) is LOCAL_T0


def test_selecting_the_hosted_target_needs_a_usable_url():
    assert profile_from_env({"GIS_TARGET": "cloud", "GIS_API_URL": CLOUD_URL}).cluster == REF
    # Asking for cloud and getting local instead would be the dangerous failure.
    for environ in ({"GIS_TARGET": "cloud"}, {"GIS_TARGET": "cloud", "GIS_API_URL": LOCAL_URL}):
        with pytest.raises(TargetError):
            profile_from_env(environ)


def test_an_unknown_target_name_is_refused_rather_than_guessed():
    with pytest.raises(TargetError):
        profile_from_env({"GIS_TARGET": "staging"})


def test_settings_must_agree_with_the_profile_they_declare():
    good = LocalGISSettings.for_profile(LOCAL_T0, enabled=True,
                                        runtime_instance="a" * 32, baseline_fingerprint="b" * 64)
    good.validate()
    assert good.issuer == LOCAL_T0.issuer
    # Target fields that contradict the profile are a refusal, not a preference.
    from dataclasses import replace
    for field, value in (("api_url", "http://127.0.0.1:9999"), ("cluster", "elsewhere"),
                         ("mode", CLOUD_MODE), ("database", "other")):
        with pytest.raises(Exception):
            replace(good, **{field: value}).validate()


def test_settings_for_a_hosted_profile_validate_against_that_profile():
    profile = cloud_profile(CLOUD_URL)
    settings = LocalGISSettings.for_profile(profile, enabled=True,
                                            runtime_instance="c" * 32, baseline_fingerprint="d" * 64)
    settings.validate()
    assert (settings.cluster, settings.mode, settings.issuer) == (REF, CLOUD_MODE, profile.issuer)
