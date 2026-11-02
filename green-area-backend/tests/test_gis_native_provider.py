"""Synthetic only: frozen answers from L1-L4, integrity and request allowlist."""
from __future__ import annotations

from copy import deepcopy
import json
import shutil

import pytest

from gis_worker import provider


def request(fixture_id="t3-ldd-valid-v2"):
    return dict(fixture_id=fixture_id, manifest=provider.fixture_manifest(fixture_id),
                input_hash="a"*64, input_revision=1, attempt_number=1)


def test_registry_provenance_source_inventory_and_all_actual_hashes():
    registry = provider.load_registry()
    assert registry["synthetic_only"] is True
    assert registry["source_code_sha256"] == "91c8604115b8c5c08d362127ed5fd2ded8c8259d82f088ed259dba87cce81480"
    assert registry["source_manifest_sha256"] == "72a406b0291f3dcc553346def336c39f2a6f7e776c89e637c7e7372b3f86fcdf"
    for fixture_id, entry in registry["entries"].items():
        assert entry["manifest"]["fixture_id"] == fixture_id
        provider._check_request(request(fixture_id), registry)


@pytest.mark.parametrize("fixture_id", [
    "t3-ldd-valid-v2", "t3-ldd-cp874-v2", "t3-ldd-composite-v2", "t3-s2-v2",
    "t3-lst-v2", "t3-ndvi-ready-v2", "t3-lst-ready-v2", "t3-kelvin-v2",
])
def test_native_valid_expected_results(fixture_id):
    result = provider.validate(request(fixture_id))
    assert result["valid"] is True
    assert result["error_code"] is None
    assert "scientific_expected_results" in result["checks"]
    assert len(json.dumps(result).encode()) <= provider.MAX_REPORT_BYTES


@pytest.mark.parametrize("fixture_id,error", [
    ("t3-unknown-v2", "UNKNOWN_CODE_REVIEW_REQUIRED"),
    ("t3-zip-unsafe-v2", "ZIP_PATH_UNSAFE"),
    ("t3-zip-symlink-v2", "ZIP_SYMLINK"),
    ("t3-ldd-missing-v2", "MISSING_COMPONENT_DBF"),
    ("t3-nodata-v2", "ALL_NODATA"),
])
def test_native_failed_validation_reports_expected_safe_error(fixture_id, error):
    result = provider.validate(request(fixture_id))
    assert result["valid"] is False and result["error_code"] == error
    assert result["artifact_sha256"] == request(fixture_id)["manifest"]["sha256"]


def test_unknown_record_count_composite_area_and_code_are_preserved():
    result = provider.validate(request("t3-unknown-v2"))
    assert result["statistics"]["feature_count"] == 3
    assert result["statistics"]["total_area_m2"] == 6400
    assert result["statistics"]["unknown_area_m2"] == 1600
    assert result["warnings"] == [dict(code="UNKNOWN_CODE_REVIEW_REQUIRED", count=1, codes=["U9999_UNKNOWN"])]


def test_ready_raster_zero_celsius_and_kelvin_are_not_double_scaled():
    celsius = provider.validate(request("t3-lst-ready-v2"))
    kelvin = provider.validate(request("t3-kelvin-v2"))
    assert celsius["values"][0][1] == 0
    assert abs(kelvin["values"][0][1]) < 0.00005
    assert celsius["statistics"]["valid_pixels"] == kelvin["statistics"]["valid_pixels"] == 5


@pytest.mark.parametrize("field,value", [
    ("fixture_id", "../../secret"), ("input_hash", "invalid"),
    ("input_revision", True), ("input_revision", 0), ("attempt_number", 4),
    ("manifest", {}),
])
def test_request_rejects_unknown_identity_or_conflicting_metadata(field, value):
    payload = request()
    payload[field] = value
    with pytest.raises(provider.ProviderError):
        provider.validate(payload)


@pytest.mark.parametrize("key", ["path", "url", "command", "sql", "behavior"])
def test_request_cannot_supply_file_or_execution_instructions(key):
    payload = request()
    payload[key] = "untrusted"
    with pytest.raises(provider.ProviderError, match="REQUEST_INVALID"):
        provider.validate(payload)


def test_conflicting_manifest_hash_and_calibration_rejected_before_native():
    payload = deepcopy(request("t3-s2-v2"))
    payload["manifest"]["scales"] = [1, 1, 1]
    with pytest.raises(provider.ProviderError, match="MANIFEST_MISMATCH"):
        provider.validate(payload)


def test_registry_and_source_integrity_fail_closed(tmp_path, monkeypatch):
    (tmp_path / "registry.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(provider, "ROOT", tmp_path)
    with pytest.raises(provider.ProviderError, match="REGISTRY_INTEGRITY"):
        provider.load_registry()


@pytest.mark.parametrize("change", ["checksum", "size", "unexpected_member", "source"])
def test_actual_artifact_and_source_tamper_rejected(tmp_path, monkeypatch, change):
    fixture_id = "t3-ldd-valid-v2"
    payload = request(fixture_id)
    root = provider.ROOT
    shutil.copyfile(root / "registry.json", tmp_path / "registry.json")
    shutil.copyfile(root / "poc_validation.py", tmp_path / "poc_validation.py")
    shutil.copytree(root / "fixtures", tmp_path / "fixtures")
    path = tmp_path / "fixtures" / "ldd_valid.zip"
    if change == "checksum":
        value = bytearray(path.read_bytes())
        value[-1] ^= 1
        path.write_bytes(value)
    elif change == "size":
        path.write_bytes(path.read_bytes() + b"x")
    elif change == "source":
        (tmp_path / "poc_validation.py").write_bytes(b"changed")
    else:
        (tmp_path / "fixtures" / "unexpected.tif").write_bytes(b"extra")
    monkeypatch.setattr(provider, "ROOT", tmp_path)
    with pytest.raises(provider.ProviderError, match="INTEGRITY"):
        registry = provider.load_registry()
        provider._check_request(payload, registry)


def test_symlink_artifact_is_rejected(tmp_path):
    source = tmp_path / "source"
    source.write_bytes(b"fixture")
    link = tmp_path / "link"
    try:
        link.symlink_to(source)
    except (OSError, NotImplementedError):
        pytest.skip("Host does not permit symlink creation; Linux run required")
    with pytest.raises(provider.ProviderError, match="ARTIFACT_INTEGRITY"):
        provider._safe_file(link, tmp_path)


def test_report_never_accepts_nan_or_unbounded_output():
    with pytest.raises(ValueError):
        provider.bounded_report({"statistics": {"mean": float("nan")}})
    with pytest.raises(provider.ProviderError, match="REPORT_LIMIT"):
        provider.bounded_report({"error": "x" * (provider.MAX_REPORT_BYTES + 1)})
