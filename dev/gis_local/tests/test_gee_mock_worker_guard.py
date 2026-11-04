"""The dedicated mock image never relaxes Native/Offline worker policy."""
import importlib.util
import json
from pathlib import Path
import sys

import pytest

spec = importlib.util.spec_from_file_location('a63_guard_base', Path(__file__).with_name('test_processing_worker_guard.py'))
base = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = base
spec.loader.exec_module(base)
manager = base.manager


@pytest.fixture
def setup():
    item = base.setup.__wrapped__()
    name = 'gis-gee-mock-worker-' + item.run_id[:12]
    item.approval[item.cid] = {'name': name, 'run_id': item.run_id, 'mock_adapter': True}
    item.worker.update(name='/' + name, image=manager.GEE_MOCK_WORKER_IMAGE, image_id=manager.GEE_MOCK_WORKER_IMAGE,
        command=['python3', '-I', '-B', '/app/gis_worker/gee_mock_worker.py'],
        labels={'gis.a6.3.scope': 'gee-mock-worker', 'gis.a6.3.instance': 'a' * 32,
                'gis.a6.3.run': item.run_id, 'com.docker.compose.project': manager.guard.PROJECT})
    return item


def test_exact_approved_mock_worker_and_default_strict_gate(setup):
    assert set(setup.verify()) == set(manager.SERVICES)
    with pytest.raises(manager.guard.SafetyError): setup.runtime.verify_containers()


@pytest.mark.parametrize('key,value', [('Memory', 0), ('MemorySwap', -1), ('NanoCpus', 0), ('PidsLimit', 0),
    ('Privileged', True), ('ReadonlyRootfs', False), ('NetworkMode', 'host'), ('CapAdd', ['SYS_ADMIN']),
    ('PortBindings', {'8000/tcp': [{'HostPort': '8000'}]})])
def test_mock_resource_and_network_limits_fail_closed(setup, key, value):
    setup.worker['host'][key] = value
    with pytest.raises(manager.guard.SafetyError): setup.verify()


@pytest.mark.parametrize('key,value', [('Source', '/unknown/gee_utils.py'), ('Destination', '/app/main.py'),
                                    ('RW', True), ('Propagation', 'rshared')])
def test_mock_mount_sources_are_exact_readonly(setup, key, value):
    setup.worker['mounts'][1][key] = value
    with pytest.raises(manager.guard.SafetyError): setup.verify()


@pytest.mark.parametrize('key,value', [('image', manager.WORKER_IMAGE), ('image_id', manager.WORKER_IMAGE),
    ('user', '0:0'), ('command', ['python3', '-c', 'anything'])])
def test_mock_image_identity_and_command_are_pinned(setup, key, value):
    setup.worker[key] = value
    with pytest.raises(manager.guard.SafetyError): setup.verify()


def test_opt_in_and_environment_cannot_be_forged(setup):
    setup.approval[setup.cid]['mock_adapter'] = False
    with pytest.raises(manager.guard.SafetyError): setup.verify()
    setup.approval[setup.cid]['mock_adapter'] = True
    setup.env_names += 'GOOGLE_APPLICATION_CREDENTIALS\n'
    with pytest.raises(manager.guard.SafetyError): setup.verify()


def test_image_lock_matches_policy_and_existing_requirements():
    import hashlib
    root = Path(__file__).resolve().parents[1]
    lock = json.loads((root / 'gee-mock-image.lock.json').read_text(encoding='utf-8'))
    assert lock['image_id'] == manager.GEE_MOCK_WORKER_IMAGE
    assert lock['base_image'] == manager.WORKER_IMAGE
    assert lock['dockerfile_sha256_lf'] == hashlib.sha256((root / 'gee_mock.Dockerfile').read_text(encoding='utf-8').encode()).hexdigest()
    requirements = (root.parents[1] / 'green-area-backend/requirements.txt').read_text(encoding='utf-8')
    assert lock['requirements_sha256_lf'] == hashlib.sha256(requirements.encode()).hexdigest()
    for wheel in lock['wheels']:
        assert wheel['package'] + '==' + wheel['version'] in requirements
        assert '--hash=sha256:' + wheel['sha256'] in requirements
