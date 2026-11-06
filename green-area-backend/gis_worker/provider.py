"""Frozen synthetic provider. Importing this module never loads GIS or credentials.

Only the native child calls validate(); the queue parent uses fixture_manifest().
The local original PoC is preserved byte-for-byte as poc_validation.py.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re

from gis_worker import source_integrity as si

ROOT = Path(__file__).resolve().parent
# registry.json and poc_validation.py are reviewed *text*: verified under
# source-text-lf-sha256-v1 so a CRLF (Windows) and LF (Linux) checkout agree.
# The fixtures they list are raw artifacts and stay raw-bytes-sha256.
REGISTRY_HASH_SCHEME = si.SOURCE_TEXT_SCHEME
REGISTRY_SHA256 = "a314c72775ade5806c1cc9e53faeacd6ab5f308ac8bce1984b9e5921e1da6490"
# Historical value reviewed on the Windows CRLF checkout (raw-crlf-sha256-v0).
REGISTRY_LEGACY_CRLF_SHA256 = "a03a1fade69c0ca4df8d7ac7ad63c3b3c6af31444ef65f5773e5de7f56715cb9"
SOURCE_HASH_SCHEME = si.SOURCE_TEXT_SCHEME
PROVIDER_BUILD = "t3-native-v1"
MAX_REPORT_BYTES = 16384
HASH = re.compile(r"^[0-9a-f]{64}$")
CHECKS = ["synthetic_fixture_match", "metadata_shape", "source_hash_match", "bounded_input"]


class ProviderError(ValueError):
    """Fixed public error code; never wraps a native exception or path."""


def _require(condition: bool, code: str):
    if not condition:
        raise ProviderError(code)


def _safe_file(path: Path, root: Path) -> Path:
    _require(not path.is_symlink(), "ARTIFACT_INTEGRITY")
    _require(path.resolve().is_relative_to(root.resolve()) and path.is_file(), "ARTIFACT_INTEGRITY")
    cursor = path
    while cursor != root:
        _require(not cursor.is_symlink(), "ARTIFACT_INTEGRITY")
        cursor = cursor.parent
    return path


def load_registry() -> dict:
    _require(not ROOT.is_symlink(), "ARTIFACT_INTEGRITY")
    raw = _safe_file(ROOT / "registry.json", ROOT).read_bytes()
    _require(si.verify(raw, REGISTRY_SHA256, REGISTRY_HASH_SCHEME)
             and si.verify(raw, REGISTRY_LEGACY_CRLF_SHA256, si.LEGACY_CRLF_SCHEME), "REGISTRY_INTEGRITY")
    result = json.loads(raw)
    _require(result["provider_build"] == PROVIDER_BUILD, "REGISTRY_INTEGRITY")
    source = _safe_file(ROOT / "poc_validation.py", ROOT).read_bytes()
    _require(si.verify(source, result["source_code_sha256"], SOURCE_HASH_SCHEME), "REGISTRY_INTEGRITY")
    fixtures = ROOT / "fixtures"
    _require(fixtures.is_dir() and not fixtures.is_symlink(), "ARTIFACT_INTEGRITY")
    expected = {entry["path"] for entry in result["entries"].values()}
    _require({p.name for p in fixtures.iterdir()} == expected, "ARTIFACT_INTEGRITY")
    for name in expected:
        _require(Path(name).name == name and "/" not in name and "\\" not in name, "REGISTRY_INTEGRITY")
        _safe_file(fixtures / name, fixtures)
    return result


def fixture_manifest(fixture_id: str) -> dict:
    registry = load_registry()
    _require(isinstance(fixture_id, str) and fixture_id in registry["entries"], "FIXTURE_NOT_ALLOWLISTED")
    return registry["entries"][fixture_id]["manifest"]


def _same(actual, expected, *, abs_tol=0.00005):
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(k in actual and _same(actual[k], v, abs_tol=abs_tol) for k, v in expected.items())
    if isinstance(expected, list):
        return isinstance(actual, list) and len(actual) == len(expected) and all(_same(a, e, abs_tol=abs_tol) for a, e in zip(actual, expected))
    if expected is None or isinstance(expected, (str, bool)):
        return actual == expected
    return isinstance(actual, (int, float)) and math.isfinite(actual) and math.isclose(actual, expected, rel_tol=1e-7, abs_tol=abs_tol)


def _check_request(request: dict, registry: dict) -> dict:
    _require(isinstance(request, dict) and set(request) == {"fixture_id", "manifest", "input_hash", "input_revision", "attempt_number"}, "REQUEST_INVALID")
    fid = request["fixture_id"]
    _require(isinstance(fid, str) and fid in registry["entries"], "FIXTURE_NOT_ALLOWLISTED")
    _require(isinstance(request["input_hash"], str) and bool(HASH.fullmatch(request["input_hash"])), "REQUEST_INVALID")
    _require(type(request["input_revision"]) is int and 1 <= request["input_revision"] <= 2147483647, "REQUEST_INVALID")
    _require(type(request["attempt_number"]) is int and 1 <= request["attempt_number"] <= 3, "REQUEST_INVALID")
    entry = registry["entries"][fid]
    # Python's True == 1 must not bypass the frozen numeric calibration contract.
    def no_boolean(value):
        if isinstance(value, dict):
            return all(no_boolean(v) for v in value.values())
        if isinstance(value, list):
            return all(no_boolean(v) for v in value)
        return type(value) is not bool
    _require(no_boolean(request["manifest"]), "MANIFEST_MISMATCH")
    _require(request["manifest"] == entry["manifest"], "MANIFEST_MISMATCH")
    path = _safe_file(ROOT / "fixtures" / entry["path"], ROOT / "fixtures")
    _require(path.stat().st_size == entry["manifest"]["byte_size"], "ARTIFACT_INTEGRITY")
    _require(hashlib.sha256(path.read_bytes()).hexdigest() == entry["manifest"]["sha256"], "ARTIFACT_INTEGRITY")
    return entry


def report_failure(request: dict, error_code: str) -> dict:
    """Use only for already validated requests and fixed internal error enums."""
    return bounded_report(dict(schema_version=2, fixture_id=request["fixture_id"],
        artifact_sha256=request["manifest"]["sha256"], input_hash=request["input_hash"],
        input_revision=request["input_revision"], provider_build=PROVIDER_BUILD,
        valid=False, checks=CHECKS.copy(), warnings=[], statistics={}, error_code=error_code))


def bounded_report(report: dict) -> dict:
    _require(len(json.dumps(report, allow_nan=False, separators=(",", ":")).encode()) <= MAX_REPORT_BYTES, "REPORT_LIMIT")
    return report


def validate(request: dict) -> dict:
    """Read allowlisted local artifact and compare actual science to frozen answers."""
    registry = load_registry()
    entry = _check_request(request, registry)
    # Imports happen after the native child has set memory/CPU limits.
    from . import poc_validation as poc
    from shapely.geometry import box
    path = ROOT / "fixtures" / entry["path"]
    manifest, expected = entry["manifest"], entry["expected"]
    report = report_failure(request, "VALIDATION_FAILED")
    try:
        if manifest["data_kind"] == "polygon":
            native = poc.validate_ldd_zip(path, aoi=box(*registry["aoi"]))
            _require(native["crs_epsg"] == 32647, "METADATA_MISMATCH")
            _require(all(set(row) == set(manifest["attributes"]) for row in native["records"]), "METADATA_MISMATCH")
            stats = dict(feature_count=native["feature_count"], total_area_m2=native["total_area_m2"],
                unknown_area_m2=native["unknown_area_m2"], area_U_m2=native["area_by_main_m2"]["U"],
                area_A_m2=native["area_by_main_m2"]["A"], unknown_code_count=len(native["unknown_codes"]))
            wanted = {key: expected[key] for key in ("feature_count", "total_area_m2", "unknown_area_m2", "area_U_m2", "area_A_m2")}
            _require(_same(stats, wanted) and native["valid"] == expected["valid"], "SCIENTIFIC_MISMATCH")
            _require(native["records"][0]["LU_DES_TH"] == expected["thai"], "SCIENTIFIC_MISMATCH")
            _require(any(row["LU_CODE"] == expected["composite"] for row in native["records"]), "SCIENTIFIC_MISMATCH")
            if native["unknown_codes"]:
                codes = [item["code"] for item in native["unknown_codes"]]
                _require(codes == [expected["unknown_code"]], "SCIENTIFIC_MISMATCH")
                report["warnings"] = [dict(code="UNKNOWN_CODE_REVIEW_REQUIRED", count=len(codes), codes=codes)]
            report["statistics"] = stats
            report["error_code"] = None if native["valid"] else "UNKNOWN_CODE_REVIEW_REQUIRED"
        else:
            native = poc.inspect_and_process_raster(path)
            metadata = native["metadata"]
            _require(_same(metadata, dict(crs_epsg=32647, bands=manifest["bands"],
                resolution=[manifest["resolution"]]*2, nodata=manifest["nodata"],
                source_units=manifest["units"], scales=manifest["scales"], offsets=manifest["offsets"],
                data_kind=manifest["profile"]), abs_tol=1e-9), "METADATA_MISMATCH")
            _require(_same(native["values"], expected["values"]) and native["stats"]["valid_pixels"] == expected["valid_pixels"]
                and native["valid"] == expected["valid"], "SCIENTIFIC_MISMATCH")
            report["statistics"] = native["stats"]
            report["values"] = native["values"]
            report["error_code"] = None if native["valid"] else "ALL_NODATA"
        report["checks"] += ["native_validation", "scientific_expected_results"]
        report["valid"] = native["valid"]
    except poc.PocError as exc:
        # Only allow the precise expected error from the frozen synthetic fixture.
        _require(exc.code == expected.get("error_code"), "UNEXPECTED_NATIVE_ERROR")
        report["error_code"] = exc.code
        report["checks"] += ["native_validation", "scientific_expected_results"]
    return bounded_report(report)
