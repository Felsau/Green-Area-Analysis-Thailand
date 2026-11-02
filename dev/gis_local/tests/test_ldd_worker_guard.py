"""Phase 2 exact worker/storage approval never relaxes default strict topology."""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import sys

import pytest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('phase2_existing_guard_fixtures', HERE / 'test_t3_worker_guard.py')
original = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = original
spec.loader.exec_module(original)
manager = original.manager


@pytest.fixture
def setup(tmp_path):
    fixture = original.T3WorkerGuardTests(methodName='runTest')
    fixture.setUp()
    old_root = fixture.runtime.root
    fixture.runtime.root = tmp_path
    for item in fixture.items.values():
        for mount in item['mounts']:
            if mount['Type'] == 'bind':
                mount['Source'] = str(tmp_path / Path(mount['Source']).relative_to(old_root))
    storage = tmp_path / 'ldd-storage'
    objects = storage / 'objects'
    objects.mkdir(parents=True)
    marker = {'scope': 'gis-ldd-storage-v1', 'runtime_instance': 'a' * 32,
              'baseline_fingerprint': 'e' * 64, 'database': 'postgres', 'cluster': 'green-area-gis-t0'}
    (storage / 'owner.json').write_text(json.dumps(marker), encoding='utf-8')
    name = 'gis-ldd-worker-' + fixture.run_id[:12]
    fixture.approval[fixture.cid] = {'name': name, 'run_id': fixture.run_id,
                                   'ldd_storage': manager.canonical_bind_path(str(objects))}
    fixture.worker.update(name='/' + name, command=['python3', '-I', '-B', '/app/gis_worker/ldd_worker.py'],
        labels={'gis.phase2.scope': 'ldd-worker', 'gis.phase2.instance': 'a' * 32,
                'gis.phase2.run': fixture.run_id, 'com.docker.compose.project': manager.guard.PROJECT})
    fixture.worker['mounts'].append({'Type': 'bind', 'Source': str(objects), 'Destination': '/data/ldd',
                                    'RW': False, 'Propagation': 'rprivate'})
    return fixture


def test_exact_ldd_worker_and_read_only_storage_is_allowed(setup):
    assert set(setup.verify()) == set(manager.SERVICES)
    assert not any(call.args[0][0] in {'exec', 'run', 'create', 'start', 'compose'}
                   for call in setup.runtime.docker.call_args_list)


def test_ldd_policy_does_not_weaken_default_strict_mode(setup):
    with pytest.raises(manager.guard.SafetyError, match='FOREIGN_NETWORK_MEMBER'):
        setup.runtime.verify_containers()


def test_unknown_container_beside_approved_ldd_worker_is_denied(setup):
    setup.foreign_members['d' * 64] = {}
    with pytest.raises(manager.guard.SafetyError, match='FOREIGN_NETWORK_MEMBER'):
        setup.verify()


@pytest.mark.parametrize('field,value', [
    ('ldd_storage', '/arbitrary/storage'), ('name', 'gis-t3-worker-' + 'c' * 12),
    ('run_id', 'short'), ('path', '/arbitrary'),
])
def test_policy_cannot_choose_other_source_or_command(setup, field, value):
    setup.approval[setup.cid][field] = value
    with pytest.raises(manager.guard.SafetyError):
        setup.verify()


@pytest.mark.parametrize('field,value', [
    ('Memory', 0), ('MemorySwap', -1), ('PidsLimit', 0), ('NanoCpus', 0),
    ('Privileged', True), ('ReadonlyRootfs', False), ('CapAdd', ['SYS_ADMIN']),
    ('CapDrop', []), ('NetworkMode', 'host'), ('SecurityOpt', []),
    ('PortBindings', {'80/tcp': [{'HostIp': '0.0.0.0', 'HostPort': '80'}]}),
])
def test_ldd_limits_capabilities_and_network_are_still_strict(setup, field, value):
    setup.worker['host'][field] = copy.deepcopy(value)
    with pytest.raises(manager.guard.SafetyError):
        setup.verify()


@pytest.mark.parametrize('field,value', [
    ('command', ['sh', '-c', 'anything']), ('user', '0:0'),
    ('image', 'python:latest'), ('image_id', 'sha256:' + '0' * 64),
    ('networks', {'green-area-gis-t0-internal': {}, 'external': {}}),
])
def test_ldd_container_identity_is_exact(setup, field, value):
    setup.worker[field] = value
    with pytest.raises(manager.guard.SafetyError):
        setup.verify()


@pytest.mark.parametrize('field,value', [
    ('RW', True), ('Source', '/other/files'), ('Destination', '/tmp/files'), ('Propagation', 'rshared'),
])
def test_ldd_storage_mount_cannot_be_substituted_or_mutable(setup, field, value):
    setup.worker['mounts'][1][field] = value
    with pytest.raises(manager.guard.SafetyError):
        setup.verify()


def test_additional_read_only_mount_is_denied(setup):
    setup.worker['mounts'].append({'Type': 'bind', 'Source': str(setup.runtime.root),
        'Destination': '/other', 'RW': False, 'Propagation': 'rprivate'})
    with pytest.raises(manager.guard.SafetyError, match='EXACT_MOUNTS'):
        setup.verify()


@pytest.mark.parametrize('relative', ['ldd-storage', 'ldd-storage/objects', 'ldd-storage/owner.json'])
def test_symlink_storage_or_marker_is_denied_without_following_it(setup, monkeypatch, relative):
    target = setup.runtime.root / relative
    previous = Path.is_symlink
    monkeypatch.setattr(Path, 'is_symlink', lambda p: p == target or previous(p))
    with pytest.raises(manager.guard.SafetyError, match='STORAGE_SOURCE'):
        setup.verify()


@pytest.mark.parametrize('relative', ['ldd-storage', 'ldd-storage/objects'])
def test_windows_directory_junction_is_denied(setup, monkeypatch, relative):
    target = setup.runtime.root / relative
    previous = getattr(Path, 'is_junction', lambda _p: False)
    monkeypatch.setattr(Path, 'is_junction', lambda p: p == target or previous(p), raising=False)
    with pytest.raises(manager.guard.SafetyError, match='STORAGE_SOURCE'):
        setup.verify()


@pytest.mark.parametrize('field,value', [
    ('scope', 'other'), ('runtime_instance', 'd' * 32), ('database', 'production'),
    ('cluster', 'other'), ('baseline_fingerprint', 'invalid'), ('extra', True),
])
def test_storage_marker_must_identify_owned_local_instance(setup, field, value):
    marker_path = setup.runtime.root / 'ldd-storage/owner.json'
    marker = json.loads(marker_path.read_text(encoding='utf-8'))
    marker[field] = value
    marker_path.write_text(json.dumps(marker), encoding='utf-8')
    with pytest.raises(manager.guard.SafetyError, match='STORAGE_SOURCE'):
        setup.verify()


def test_credential_environment_names_are_denied_without_reading_values(setup):
    setup.env_names += 'SUPABASE_SERVICE_ROLE_KEY\n'
    with pytest.raises(manager.guard.SafetyError, match='ENVIRONMENT'):
        setup.verify()
