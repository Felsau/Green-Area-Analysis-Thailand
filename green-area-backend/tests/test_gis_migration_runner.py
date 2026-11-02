"""Mock runner checks only; never provisions roles or connects to a database.

The review objects below are test fixtures bound to a Fake DB, not independent
review approvals. Actual migration execution needs the separate reviewer artifact.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import sys
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "migration_runner_unit_only", ROOT / "dev/gis_local/t3_local.py")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)
MIGRATION = ROOT / "green-area-backend/migrations/031_gis_native_v2.sql"
HASH = hashlib.sha256(MIGRATION.read_bytes()).hexdigest()


def fake_runner(*checksums):
    runner = object.__new__(MODULE.LocalT3)
    runner.attest = Mock(return_value={"test_only": True})
    runner.write = Mock()
    runner.db = SimpleNamespace(
        instance="a" * 32,
        proof=Mock(return_value={"test_only": True}),
        transport=Mock(side_effect=[SimpleNamespace(stdout=value) for value in checksums]),
    )
    return runner


def mock_review(tmp_path, *, approved=True, checksum=HASH, high=0):
    path = tmp_path / "mock-review-not-execution-approval.json"
    path.write_text(json.dumps({
        "independent_review": approved,
        "unresolved_high_critical": high,
        "review_kind": "mock_unit_test_fixture_never_use_for_execution",
        "files": {MIGRATION.name: checksum},
    }), encoding="utf-8")
    return path


def only_read_queries(runner):
    for call in runner.db.transport.call_args_list:
        sql = call.args[1].upper()
        assert "SELECT SHA256 FROM GIS.SCHEMA_MIGRATIONS WHERE VERSION=31" in sql
        assert "ROLLBACK" in sql
        assert all(word not in sql for word in ("UPDATE ", "INSERT ", "CREATE ", "ALTER "))


def test_applied_031_checksum_mismatch_fails_closed_before_any_write(tmp_path):
    runner = fake_runner("b" * 64)
    with pytest.raises(MODULE.t1.SafetyError, match="APPLIED_CHECKSUM_DRIFT"):
        runner.migrate_031(mock_review(tmp_path))
    assert runner.db.transport.call_count == 1
    runner.write.assert_not_called()
    only_read_queries(runner)


def test_second_database_checksum_mismatch_never_reapplies_first(tmp_path):
    runner = fake_runner(HASH, "c" * 64)
    with pytest.raises(MODULE.t1.SafetyError, match="APPLIED_CHECKSUM_DRIFT"):
        runner.migrate_031(mock_review(tmp_path))
    assert runner.db.transport.call_count == 2
    runner.write.assert_not_called()
    only_read_queries(runner)


def test_matching_applied_031_is_skipped_for_both_databases(tmp_path):
    runner = fake_runner(HASH, HASH)
    result = runner.migrate_031(mock_review(tmp_path))
    assert result["sha256"] == HASH
    assert result["databases"] == ["postgres", "gis_t1_upgrade"]
    assert runner.db.transport.call_count == 2
    only_read_queries(runner)


@pytest.mark.parametrize("changes", [
    {"approved": False}, {"checksum": "d" * 64}, {"high": 1},
])
def test_unreviewed_or_different_exact_bytes_never_execute(changes, tmp_path):
    runner = fake_runner()
    with pytest.raises(MODULE.t1.SafetyError, match="CHECKSUM_BOUND_REVIEW"):
        runner.migrate_031(mock_review(tmp_path, **changes))
    runner.db.transport.assert_not_called()
    runner.db.proof.assert_not_called()


def test_unknown_target_guard_stops_before_reading_review_or_db(tmp_path):
    runner = fake_runner()
    runner.attest.side_effect = MODULE.t1.SafetyError("UNKNOWN_TARGET")
    with pytest.raises(MODULE.t1.SafetyError, match="UNKNOWN_TARGET"):
        runner.migrate_031(tmp_path / "does-not-exist.json")
    runner.db.transport.assert_not_called()
    runner.db.proof.assert_not_called()


@pytest.mark.parametrize("name,checksum", [
    ("027_gis_foundation.sql", "bc879ca55e26a506e4b36c887dede928b07c619c42c94ddf69282362abd351e5"),
    ("028_gis_queue.sql", "fcf5d9530b516d93dda0fc2ea5b01158809aad237c1e90863d09bd324c9000d1"),
    ("029_gis_transactions.sql", "7faf7bf6abbd4e52ab8389423c3c1876c94af459fe9d7c5d2a7710ffc0f236a5"),
    ("030_gis_api_reads.sql", "0c6cd4b6fb3fe964dfcba848bf392a9b93cea87be7c15fd214cfe5e435b6f113"),
    ("031_gis_native_v2.sql", "85d345fa5b8dca615735618f7d9e689646dc4a286c285e0601b51f410192269c"),
])
def test_applied_gis_migration_bytes_are_frozen(name, checksum):
    assert hashlib.sha256((MIGRATION.parent / name).read_bytes()).hexdigest() == checksum
