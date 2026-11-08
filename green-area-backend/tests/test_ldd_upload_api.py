"""Mock Auth/RPC API contracts + real private temporary filesystem checks.

These tests do not establish real JWT, PostgreSQL, native GIS or browser E2E.
All keys/tokens below are explicit unit placeholders. No dotenv/network/credentials.
"""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import stat
import struct
from types import SimpleNamespace
from uuid import UUID, uuid4, uuid5
import zipfile

from gis_target import LOCAL_T0

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest

from gis_app import create_app
import gis_ldd_storage as storage
from gis_ldd_storage import LocalLddStore, preflight_zip
from gis_service import gis_error


ACTOR = '11111111-1111-4111-8111-111111111111'
DATASET = '22222222-2222-4222-8222-222222222222'
KEY = '33333333-3333-4333-8333-333333333333'
FIXTURES = Path(__file__).resolve().parents[1] / 'gis_worker/fixtures'


def zip_bytes(entries):
    output = BytesIO()
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_STORED) as archive:
        for name, data in entries:
            archive.writestr(name, data)
    return output.getvalue()


def archive_file(tmp_path, raw):
    path = tmp_path / (uuid4().hex + '.zip')
    path.write_bytes(raw)
    return path


def assert_code(error, status, code):
    assert isinstance(error.value, HTTPException)
    assert error.value.status_code == status
    assert error.value.detail['code'] == code


async def chunks(raw):
    for offset in range(0, len(raw), 65536):
        yield raw[offset:offset + 65536]


def test_total_deadline_rejects_slow_chunks_without_publishing(store, monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(storage, 'time', SimpleNamespace(monotonic=lambda: clock[0]))
    raw = (FIXTURES / 'ldd_valid.zip').read_bytes()
    async def slow():
        clock[0] = 61.0
        yield raw
    with pytest.raises(HTTPException) as error:
        asyncio.run(store.receive(slow()))
    assert_code(error, 408, 'GIS_LDD_UPLOAD_TIMEOUT')
    assert not list(store.objects.iterdir())
    assert not list(store.staging.iterdir())


class FakeRuntime:
    sandbox_activation_enabled = False

    def __init__(self):
        self.settings = SimpleNamespace(api_url='http://127.0.0.1:55421', database='postgres',
            cluster='green-area-gis-t0', mode='local_synthetic', profile=LOCAL_T0,
            runtime_instance='a' * 32, baseline_fingerprint='b' * 64)
        self.calls = []
        self.allowed = True
        self.revision = 3
        self.kind, self.purpose, self.month = 'ldd_shapefile', 'landuse', 0

    def require_ready(self):
        return {'migration_versions': list(range(27, 35))}

    def verify_user_token(self, token):
        if token != 'mock-user-token':
            raise gis_error(401, 'GIS_UNAUTHENTICATED', 'unit session required')
        return ACTOR

    def rpc(self, name, payload):
        self.calls.append((name, payload))
        if name == 'gis_read':
            if not self.allowed:
                raise gis_error(403, 'GIS_FORBIDDEN', 'unit GIS permission denied')
            if payload['p_kind'] == 'dataset':
                return {'id': DATASET, 'kind': self.kind, 'purpose': self.purpose,
                    'month': self.month, 'revision': self.revision}
            if payload['p_kind'] == 'me':
                return {'admin': False, 'officer': True, 'capabilities': ['read_catalog'], 'activation_enabled': False}
        if name == 'gis_ldd_command':
            return {'status': 201, 'body': payload['p_payload']}
        if name == 'gis_ldd_read':
            return {'upload_id': payload['p_upload_id'], 'sha256': 'a' * 64, 'lease_token': 'not-a-real-secret'}
        raise AssertionError('unexpected unit RPC')


@pytest.fixture
def runtime():
    return FakeRuntime()


@pytest.fixture
def store(tmp_path, runtime):
    owner = {'scope': 'gis-foundation-t0', 'project': 'green-area-gis-t0', 'instance': 'a' * 32}
    (tmp_path / 'owner.json').write_text(json.dumps(owner), encoding='utf-8')
    return LocalLddStore(runtime, tmp_path)


@pytest.fixture
def api(runtime, store):
    with TestClient(create_app(runtime, ldd_store=store, rate_limit='10000/minute')) as client:
        client.headers.update({'Authorization': 'Bearer mock-user-token', 'Idempotency-Key': KEY})
        yield client


def upload(api, raw, **kwargs):
    return api.post(f'/gis/datasets/{DATASET}/ldd-uploads?expected_revision=3', content=raw,
        headers={'Content-Type': 'application/zip', **kwargs.pop('headers', {})}, **kwargs)


@pytest.mark.parametrize('fixture', ['ldd_valid.zip', 'ldd_cp874.zip', 'ldd_composite_a.zip'])
def test_original_fixtures_pass_metadata_preflight_without_claiming_native_validity(tmp_path, fixture):
    raw = (FIXTURES / fixture).read_bytes()
    preflight_zip(archive_file(tmp_path, raw))


@pytest.mark.parametrize('attack', ['too_many_entries', 'forged_entry_count', 'oversized_cd', 'long_name'])
def test_central_directory_bounds_before_zipfile_parser(tmp_path, monkeypatch, attack):
    if attack in ('too_many_entries', 'forged_entry_count'):
        raw = bytearray(zip_bytes([(f'{i}.dbf', b'x') for i in range(65)]))
        if attack == 'forged_entry_count':
            end = raw.rfind(b'PK\x05\x06')
            struct.pack_into('<HH', raw, end + 8, 1, 1)
    elif attack == 'oversized_cd':
        output = BytesIO()
        with zipfile.ZipFile(output, 'w') as archive:
            for index in range(3):
                info = zipfile.ZipInfo(f'{index}.dbf')
                info.comment = b'x' * 50000
                archive.writestr(info, b'x')
        raw = output.getvalue()
    else:
        raw = zip_bytes([('x' * 513 + '.dbf', b'x')])
    path = archive_file(tmp_path, raw)
    def forbidden_parser(*_args, **_kwargs):
        raise AssertionError('ZipFile parsed unbounded central directory')
    monkeypatch.setattr(storage.zipfile, 'ZipFile', forbidden_parser)
    with pytest.raises(HTTPException) as error:
        preflight_zip(path)
    assert_code(error, 422, 'GIS_LDD_ZIP_UNSAFE')


@pytest.mark.parametrize('name', ['../evil.shp', '/evil.shp', 'C:/evil.shp', 'folder\\evil.shp', 'run.py'])
def test_zip_path_and_extension_safety(tmp_path, name):
    raw = zip_bytes([(name.replace('\\', '/'), b'x')])
    if '\\' in name:
        raw = raw.replace(name.replace('\\', '/').encode(), name.encode())
    with pytest.raises(HTTPException) as error:
        preflight_zip(archive_file(tmp_path, raw))
    assert_code(error, 422, 'GIS_LDD_ZIP_UNSAFE')


def test_duplicate_casefold_names_rejected(tmp_path):
    with pytest.raises(HTTPException) as error:
        preflight_zip(archive_file(tmp_path, zip_bytes([('layer.dbf', b'a'), ('LAYER.DBF', b'b')])))
    assert_code(error, 422, 'GIS_LDD_ZIP_UNSAFE')


def test_symlink_and_zip_bomb_metadata_rejected(tmp_path):
    output = BytesIO()
    info = zipfile.ZipInfo('layer.shp')
    info.create_system = 3
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(output, 'w') as archive:
        archive.writestr(info, b'/tmp/target')
    with pytest.raises(HTTPException) as error:
        preflight_zip(archive_file(tmp_path, output.getvalue()))
    assert_code(error, 422, 'GIS_LDD_ZIP_UNSAFE')
    bomb = BytesIO()
    with zipfile.ZipFile(bomb, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('layer.dbf', b'a' * 65536)
    with pytest.raises(HTTPException) as error:
        preflight_zip(archive_file(tmp_path, bomb.getvalue()))
    assert_code(error, 422, 'GIS_LDD_ZIP_UNSAFE')


@pytest.mark.parametrize('raw', [b'not a ZIP', b'PK\x03\x04truncated'])
def test_extension_alone_does_not_make_a_zip(tmp_path, raw):
    with pytest.raises(HTTPException) as error:
        preflight_zip(archive_file(tmp_path, raw))
    assert_code(error, 422, 'GIS_LDD_ZIP_INVALID')


def test_private_immutable_hash_object_dedup_and_tampering(store):
    raw = (FIXTURES / 'ldd_valid.zip').read_bytes()
    first = asyncio.run(store.receive(chunks(raw), declared_size=len(raw)))
    expected = hashlib.sha256(raw).hexdigest()
    assert first == {'sha256': expected, 'byte_size': len(raw)}
    target = store.objects / (expected + '.zip')
    original_stat = target.stat()
    assert target.read_bytes() == raw and not target.stat().st_mode & stat.S_IWRITE
    assert asyncio.run(store.receive(chunks(raw))) == first
    assert target.stat().st_mtime_ns == original_stat.st_mtime_ns
    assert len(list(store.objects.iterdir())) == 1 and not list(store.staging.iterdir())
    os.chmod(target, 0o600)
    tampered = raw[:-1] + bytes([raw[-1] ^ 1])
    target.write_bytes(tampered)
    with pytest.raises(HTTPException) as error:
        asyncio.run(store.receive(chunks(raw)))
    assert_code(error, 503, 'GIS_LDD_INTEGRITY')
    assert target.read_bytes() == tampered  # no silent repair or overwrite
    assert not list(store.staging.iterdir())


def test_actual_stream_limit_twenty_mib(store):
    async def oversized():
        yield b'x' * storage.MAX_UPLOAD
        yield b'x'
    with pytest.raises(HTTPException) as error:
        asyncio.run(store.receive(oversized()))
    assert_code(error, 413, 'GIS_LDD_SIZE_LIMIT')
    assert not list(store.objects.iterdir()) and not list(store.staging.iterdir())


@pytest.mark.parametrize('declared', [0, storage.MAX_UPLOAD + 1])
def test_declared_stream_size_rejected_before_consumption(store, declared):
    async def forbidden():
        raise AssertionError('stream consumed before declared length rejection')
        yield b''
    with pytest.raises(HTTPException) as error:
        asyncio.run(store.receive(forbidden(), declared_size=declared))
    assert_code(error, 413, 'GIS_LDD_SIZE_LIMIT')


def test_declared_size_mismatch_cleans_only_current_stage(store):
    raw = (FIXTURES / 'ldd_valid.zip').read_bytes()
    orphan = store.staging / 'prior-request.part'
    orphan.write_bytes(b'preserve me')
    with pytest.raises(HTTPException) as error:
        asyncio.run(store.receive(chunks(raw), declared_size=len(raw) + 1))
    assert_code(error, 422, 'GIS_LDD_ZIP_INVALID')
    assert orphan.read_bytes() == b'preserve me' and list(store.staging.iterdir()) == [orphan]


def test_disk_quota_includes_orphans_and_preserves_old_objects(store, monkeypatch):
    raw = (FIXTURES / 'ldd_valid.zip').read_bytes()
    orphan = store.staging / 'prior.part'
    orphan.write_bytes(b'preserved')
    monkeypatch.setattr(storage, 'DISK_QUOTA', len(raw))
    with pytest.raises(HTTPException) as error:
        asyncio.run(store.receive(chunks(raw)))
    assert_code(error, 507, 'GIS_LDD_QUOTA')
    assert orphan.read_bytes() == b'preserved' and not list(store.objects.iterdir())


def test_os_advisory_lock_rejects_concurrent_upload(store):
    raw = (FIXTURES / 'ldd_valid.zip').read_bytes()
    def second():
        with pytest.raises(HTTPException) as error:
            asyncio.run(store.receive(chunks(raw)))
        return error.value
    with store._lock(), ThreadPoolExecutor(max_workers=1) as pool:
        result = pool.submit(second).result(timeout=5)
    assert result.status_code == 429 and result.detail['code'] == 'GIS_LDD_UPLOAD_BUSY'


def test_unknown_owner_and_unattested_target_fail_closed(tmp_path, runtime):
    (tmp_path / 'owner.json').write_text(json.dumps({'scope': 'unknown'}), encoding='utf-8')
    with pytest.raises(HTTPException) as error:
        LocalLddStore(runtime, tmp_path)
    assert_code(error, 503, 'GIS_LDD_STORAGE_UNAVAILABLE')
    assert not (tmp_path / 'ldd-storage').exists()


def test_mock_link_guard_rejects_reparse_or_symlink_root(store, monkeypatch):
    original = storage.unsafe_link
    monkeypatch.setattr(storage, 'unsafe_link', lambda p: p == store.root or original(p))
    with pytest.raises(HTTPException) as error:
        store.attest()
    assert_code(error, 503, 'GIS_LDD_STORAGE_UNAVAILABLE')


def test_changed_storage_marker_is_rejected(store):
    marker = store.root / 'owner.json'
    old = marker.read_bytes()
    marker.write_text('{}', encoding='utf-8')
    with pytest.raises(HTTPException) as error:
        store.attest()
    assert_code(error, 503, 'GIS_LDD_STORAGE_UNAVAILABLE')
    marker.write_bytes(old)


def test_api_binary_upload_binds_server_actor_and_stable_file_id(api, store, runtime):
    raw = (FIXTURES / 'ldd_valid.zip').read_bytes()
    first = upload(api, raw)
    second = upload(api, raw)
    assert first.status_code == second.status_code == 201
    commands = [payload for name, payload in runtime.calls if name == 'gis_ldd_command']
    assert len(commands) == 2 and commands[0] == commands[1]
    payload = commands[0]
    assert payload['p_actor'] == ACTOR and payload['p_request_id'] == KEY
    expected = str(uuid5(UUID('3ab9bdd7-4f76-42d8-a092-b3bb55154187'), f'{ACTOR}:{DATASET}:{KEY}'))
    assert payload['p_payload']['upload_id'] == expected
    assert payload['p_payload']['sha256'] == hashlib.sha256(raw).hexdigest()
    assert payload['p_payload']['dataset_id'] == DATASET
    assert not any(key in payload['p_payload'] for key in ('path', 'url', 'filename', 'actor_id'))
    assert len(list(store.objects.iterdir())) == 1


@pytest.mark.parametrize('failure', ['missing_jwt', 'invalid_jwt', 'no_gis_role', 'revision', 'wrong_kind', 'wrong_month'])
def test_api_auth_dataset_revision_guards_before_store_consumes_stream(api, store, runtime, monkeypatch, failure):
    async def forbidden(*_args, **_kwargs):
        raise AssertionError('upload stream consumed before authorization/association guards')
    monkeypatch.setattr(store, 'receive', forbidden)
    expected = 401
    if failure == 'missing_jwt':
        api.headers.pop('Authorization')
    elif failure == 'invalid_jwt':
        api.headers['Authorization'] = 'Bearer invalid-unit-token'
    elif failure == 'no_gis_role':
        runtime.allowed = False
        expected = 403
    elif failure == 'revision':
        runtime.revision = 4
        expected = 409
    elif failure == 'wrong_kind':
        runtime.kind, runtime.purpose = 'geotiff', 'ndvi'
        expected = 422
    else:
        runtime.month = 1
        expected = 422
    assert upload(api, b'not consumed').status_code == expected
    assert not list(store.objects.iterdir())


def test_api_upload_disabled_by_default(runtime):
    with TestClient(create_app(runtime)) as client:
        response = client.post(f'/gis/datasets/{DATASET}/ldd-uploads?expected_revision=3', content=b'raw',
            headers={'Authorization': 'Bearer mock-user-token', 'Idempotency-Key': KEY, 'Content-Type': 'application/zip'})
    assert response.status_code == 503 and response.json()['detail']['code'] == 'GIS_LDD_STORAGE_UNAVAILABLE'


@pytest.mark.parametrize('headers,status', [({'Content-Type': 'text/plain'}, 415),
    ({'Content-Length': str(storage.MAX_UPLOAD + 1)}, 413), ({'Content-Length': '-1'}, 422), ({'Content-Length': 'not-a-number'}, 422)])
def test_api_header_limits_before_store(api, store, monkeypatch, headers, status):
    async def forbidden(*_args, **_kwargs):
        raise AssertionError('stream consumed before request-header rejection')
    monkeypatch.setattr(store, 'receive', forbidden)
    assert upload(api, b'raw', headers=headers).status_code == status


def test_upload_stream_bypasses_only_json_limit(api, store):
    # A metadata-safe archive >64KiB is stored, not claimed GIS-valid.
    raw = zip_bytes([('layer.shp', b'x' * 70000)])
    assert len(raw) > 65536
    response = upload(api, raw)
    assert response.status_code == 201 and response.json()['byte_size'] == len(raw)
    before = len(list(store.objects.iterdir()))
    response = api.post('/gis/datasets', content=b'x' * 65537, headers={'Content-Type': 'application/json'})
    assert response.status_code == 422 and response.json()['detail']['code'] == 'GIS_INVALID_PAYLOAD'
    assert len(list(store.objects.iterdir())) == before


def test_api_rejects_invalid_zip_and_unrecognized_query(api):
    response = upload(api, b'has zip extension but no structure')
    assert response.status_code == 422 and response.json()['detail']['code'] == 'GIS_LDD_ZIP_INVALID'
    response = api.post(f'/gis/datasets/{DATASET}/ldd-uploads?expected_revision=3&actor_id={ACTOR}',
        content=b'x', headers={'Content-Type': 'application/zip'})
    assert response.status_code == 422


def test_upload_metadata_uses_authorized_rpc_and_sanitizes_hidden_fields(api, runtime):
    response = api.get(f'/gis/ldd-uploads/{KEY}')
    assert response.status_code == 200 and response.json()['upload_id'] == KEY
    assert 'lease_token' not in response.json()
    assert runtime.calls[-1] == ('gis_ldd_read', {'p_actor': ACTOR, 'p_upload_id': KEY})
