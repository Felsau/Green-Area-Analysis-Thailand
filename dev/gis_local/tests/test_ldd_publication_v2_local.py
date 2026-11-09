"""No Docker/DB calls: the W5 operator accepts only the exact ledger 027..052 matching the repository files."""
import hashlib
import importlib.util
from pathlib import Path
import sys

import pytest

path = Path(__file__).resolve().parents[1] / 'ldd_publication_v2_local.py'
spec = importlib.util.spec_from_file_location('test_w5_operator', path)
m = importlib.util.module_from_spec(spec); sys.modules[spec.name] = m; spec.loader.exec_module(m)


def ledger(directory, top=52):
    rows = []
    for version in range(27, top + 1):
        body = f'-- {version}\n'.encode()
        (directory / f'{version:03d}_x.sql').write_bytes(body)
        rows.append({'version': version, 'sha256': hashlib.sha256(body).hexdigest()})
    return rows


def test_exact_ledger_with_matching_files_and_closed_gate_passes(tmp_path):
    assert m.ledger_problem(ledger(tmp_path), False, tmp_path) is None


@pytest.mark.parametrize('gate', [True, None, 0])
def test_open_or_unknown_gate_is_rejected(tmp_path, gate):
    assert m.ledger_problem(ledger(tmp_path), gate, tmp_path) == 'W5_LOCAL_TARGET_REJECTED'


@pytest.mark.parametrize('change', ['older', 'newer', 'gap', 'empty'])
def test_any_other_ledger_is_rejected(tmp_path, change):
    rows = ledger(tmp_path, 53)
    rows = {'older': rows[:-2], 'newer': rows, 'gap': rows[:10] + rows[11:-1], 'empty': []}[change]
    assert m.ledger_problem(rows, False, tmp_path) == 'W5_LOCAL_TARGET_REJECTED'


def test_checksum_drift_or_missing_or_duplicate_file_is_rejected(tmp_path):
    rows = ledger(tmp_path)
    (tmp_path / '040_x.sql').write_bytes(b'-- edited\n')
    assert m.ledger_problem(rows, False, tmp_path) == 'APPLIED_CHECKSUM_DRIFT_FORWARD_MIGRATION_REQUIRED'
    rows = ledger(tmp_path); (tmp_path / '041_x.sql').unlink()
    assert m.ledger_problem(rows, False, tmp_path) == 'APPLIED_CHECKSUM_DRIFT_FORWARD_MIGRATION_REQUIRED'
    rows = ledger(tmp_path); (tmp_path / '042_copy.sql').write_bytes(b'-- 42\n')
    assert m.ledger_problem(rows, False, tmp_path) == 'APPLIED_CHECKSUM_DRIFT_FORWARD_MIGRATION_REQUIRED'


def test_repository_ledger_files_are_unique_and_the_old_a3_proof_is_unchanged():
    files = sorted(m.REPO.glob('green-area-backend/migrations/0[2-5][0-9]_*.sql'))
    numbers = [int(p.name[:3]) for p in files if 27 <= int(p.name[:3]) <= 52]
    assert numbers == list(range(27, 53))
    assert 'latest\'] not in (38,39,40)' in (m.HERE / 'ldd_publication_local.py').read_text(encoding='utf-8')
