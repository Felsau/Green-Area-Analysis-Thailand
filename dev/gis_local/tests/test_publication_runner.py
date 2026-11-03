import importlib.util
import json
from pathlib import Path
import sys

import pytest

spec = importlib.util.spec_from_file_location('a1_runner_test', Path(__file__).resolve().parents[1] / 'publication_local.py')
runner = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = runner
spec.loader.exec_module(runner)


def test_machine_contract_cannot_confuse_registration_with_readiness():
    contract = json.loads((runner.HERE / 'contracts.json').read_text(encoding='utf-8'))['publication']
    assert contract['scope'] == 'province'
    assert contract['source_namespaces'] == ['legacy', 'published']
    assert contract['active_pointer'] == 'gis.datasets.active_edition_id'
    assert contract['declarations_are_verification'] is False
    assert contract['verification_available'] is False
    assert contract['ready_for_publication'] is False


def test_checksum_mismatch_is_fail_closed():
    with pytest.raises(RuntimeError, match='FORWARD_MIGRATION_REQUIRED'):
        runner.ledger_action('a'*64, 'b'*64)


def test_existing_checksum_is_not_reapplied():
    assert runner.ledger_action('a'*64, 'a'*64) == 'already_applied'
    assert runner.ledger_action(None, 'a'*64) == 'apply'


@pytest.mark.parametrize('state', [dict(activation_enabled=True, latest=36),
    dict(activation_enabled='false', latest=36),dict(activation_enabled=False,latest=38),
    dict(activation_enabled=False,latest=37,applied_sha='b'*64),dict(activation_enabled=False,latest=37)])
def test_proof_and_read_only_checks_also_reject_drift_or_open_gate(state):
    with pytest.raises(RuntimeError):
        runner.verify_publication_state(state, 'a'*64)


@pytest.mark.parametrize('state', [dict(activation_enabled=False,latest=36),
    dict(activation_enabled=False,latest=37,applied_sha='a'*64)])
def test_proof_accepts_only_frozen_pre_or_post_migration_state(state):
    runner.verify_publication_state(state, 'a'*64)


@pytest.mark.parametrize('review', [{}, {'independent_review':False},
    {'independent_review':True,'unresolved_high_critical':1},
    {'independent_review':True,'unresolved_high_critical':0,'files':{'wrong.sql':'a'*64}}])
def test_exact_review_is_required_before_any_transport(tmp_path, review):
    path = tmp_path / '037.sql'
    path.write_bytes(b'-- synthetic no-op\n')
    with pytest.raises(RuntimeError, match='EXACT_INDEPENDENT_REVIEW_REQUIRED'):
        runner.reviewed_sql(path, review)
