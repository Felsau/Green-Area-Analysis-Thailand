"""No Docker/DB calls: the T0 rebuild seed writes the frozen state the operators check and never overwrites."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1] / 't0-rebuild'
REPO = ROOT.parents[2]
spec = importlib.util.spec_from_file_location('t0_rebuild_seed_under_test', ROOT / 'seed_runtime.py')
seed = importlib.util.module_from_spec(spec); sys.modules[spec.name] = seed; spec.loader.exec_module(seed)
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()


def operator(branch='operators-branch'):
    files = {f'green-area-backend/migrations/{p.name}': sha(p)
             for p in sorted((REPO / 'green-area-backend/migrations').glob('0[0-3]*.sql'))}
    return SimpleNamespace(GIS_BRANCH='operators-branch', fingerprint=lambda: {'branch': branch, 'head': 'f' * 40, 'files': files})


def test_seed_writes_frozen_state_matching_current_migrations(tmp_path):
    written = seed.seed(tmp_path, operator())
    assert set(written) == {seed.STATE, *seed.COPIES}
    state = json.loads((tmp_path / seed.STATE).read_text(encoding='utf-8'))
    frozen = {r: h for r, h in state['files'].items() if int(Path(r).name[:3]) <= 31}
    assert len(frozen) == 32 and all(sha(REPO / r) == h for r, h in frozen.items())
    for rel, name in seed.COPIES.items():
        assert (tmp_path / rel).read_bytes() == (ROOT / name).read_bytes()


def test_seed_refuses_to_overwrite_and_writes_nothing(tmp_path):
    (tmp_path / 'phase2').mkdir()
    (tmp_path / 'phase2/evidence-index.json').write_text('{}', encoding='utf-8')
    with pytest.raises(RuntimeError, match='REFUSING_TO_OVERWRITE'):
        seed.seed(tmp_path, operator())
    assert not (tmp_path / seed.STATE).exists()


def test_seed_refuses_another_branch(tmp_path):
    with pytest.raises(RuntimeError, match='WRONG_BRANCH'):
        seed.seed(tmp_path, operator('another-branch'))
    assert not (tmp_path / seed.STATE).exists()


def test_seed_writes_geotiff_before_files_where_041_and_042_read_them(tmp_path):
    seed.seed(tmp_path, operator())
    for rel, name, top in [('a4-geotiff-prepare/before.json', 'a4-geotiff-prepare-before.json', 40),
                           ('a4-2-geotiff-publication/before.json', 'a4-2-geotiff-publication-before.json', 41)]:
        assert (tmp_path / rel).read_bytes() == (ROOT / name).read_bytes()
        pins = json.loads((tmp_path / rel).read_text(encoding='utf-8'))['sql']
        assert max(int(n[:3]) for n in pins) == top
        # 000-026 keep their checkout-dependent bytes (no -text); the GIS migrations must match the files exactly.
        for n, h in pins.items():
            if int(n[:3]) >= 27:
                assert sha(REPO / 'green-area-backend/migrations' / n) == h, n


def test_seed_refuses_to_overwrite_an_existing_before_file(tmp_path):
    (tmp_path / 'a4-geotiff-prepare').mkdir()
    (tmp_path / 'a4-geotiff-prepare/before.json').write_text('{}', encoding='utf-8')
    with pytest.raises(RuntimeError, match='REFUSING_TO_OVERWRITE'):
        seed.seed(tmp_path, operator())
    assert not (tmp_path / seed.STATE).exists()
    assert (tmp_path / 'a4-geotiff-prepare/before.json').read_text(encoding='utf-8') == '{}'


def test_committed_records_pin_the_current_migrations():
    for name, version in [('migration-032-independent-review.json', 32), ('migration-033-independent-review.json', 33),
                          ('review-034.json', 34), ('review-035.json', 35), ('review-036.json', 36)]:
        record = json.loads((ROOT / name).read_text(encoding='utf-8'))
        path = next((REPO / 'green-area-backend/migrations').glob(f'{version:03d}_*.sql'))
        assert record['independent_review'] is True and record['unresolved_high_critical'] == 0
        assert record['files'] == {path.name: sha(path)}
    index = json.loads((ROOT / 'phase2-evidence-index.json').read_text(encoding='utf-8'))
    for rel, value in index['source_files'].items():
        if rel.startswith('green-area-backend/migrations/') and 27 <= int(Path(rel).name[:3]) <= 34:
            assert sha(REPO / rel) == value, rel
