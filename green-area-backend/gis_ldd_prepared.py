"""Local prepared artifact storage. Only a trusted app factory supplies verifier.

Prepare workers write staging only. This host-side verifier adapter alone promotes
objects and invokes service-only certification; user JSON cannot supply a proof.
"""
from __future__ import annotations

import hashlib
import json
import os
from uuid import uuid4

from gis_ldd_storage import LocalLddStore, unsafe_link, DISK_QUOTA
from gis_service import gis_error
from gis_worker.ldd_prepare_provider import NAMES, check_request, descriptors, stage_key, read_regular, VERIFIER


class LocalPreparedStore(LocalLddStore):
    STORAGE_NAME = 'ldd-prepared'
    OWNER_SCOPE = 'gis-ldd-prepared-v1'
    REQUIRED_MIGRATION = 38
    OBJECT_SUFFIX = '.json'

    def __init__(self, runtime, runtime_dir, source_store, verifier):
        if not callable(verifier):
            raise ValueError('TRUSTED_LOCAL_VERIFIER_REQUIRED')
        self.source_store, self.verifier = source_store, verifier
        super().__init__(runtime, runtime_dir)

    def _usage(self):
        total, count = 0, 0
        for directory in (self.objects, self.staging):
            for path in directory.rglob('*'):
                count += 1
                if count > 4096 or unsafe_link(path):
                    raise gis_error(507, 'GIS_PREPARE_STORAGE_LIMIT', 'พื้นที่เตรียมข้อมูลถึงขีดจำกัด')
                if path.is_file():
                    if path.stat().st_nlink != 1:
                        raise gis_error(503, 'GIS_PREPARE_STORAGE_UNSAFE', 'พื้นที่จัดเก็บไม่ปลอดภัย')
                    total += path.stat().st_size
        return total

    def _safe_read(self, path):
        if any(unsafe_link(p) for p in (path, *path.parents)):
            raise ValueError('PREPARE_UNSAFE_PATH')
        return read_regular(path)

    def _source(self, request):
        self.source_store.attest()
        source_hash = request['validation']['manifest']['sha256']
        raw = self._safe_read(self.source_store.objects / (source_hash + '.zip'))
        if len(raw) != request['validation']['manifest']['byte_size'] or hashlib.sha256(raw).hexdigest() != source_hash:
            raise ValueError('PREPARE_SOURCE_CHANGED')

    def certify_files(self, request, candidate):
        """No client proof or ready flag; native verifier rereads original+outputs."""
        self.attest();check_request(request);self._source(request)
        with self._lock():
            if self._usage() > DISK_QUOTA:
                raise gis_error(507, 'GIS_PREPARE_STORAGE_LIMIT', 'พื้นที่เตรียมข้อมูลถึงขีดจำกัด')
            proof = self.verifier(request)
            if not isinstance(proof, dict) or proof.get('verifier_version') != VERIFIER or {k: v for k, v in proof.items() if k != 'verifier_version'} != candidate:
                raise gis_error(409, 'GIS_PREPARE_VERIFICATION_FAILED', 'ผลลัพธ์ไม่ผ่าน Trusted Verification')
            directory = self.staging / stage_key(request)
            data = {kind: self._safe_read(directory / name) for kind, name in NAMES.items()}
            if descriptors(data) != proof['artifacts']:
                raise gis_error(409, 'GIS_PREPARE_VERIFICATION_FAILED', 'ไฟล์เปลี่ยนระหว่างตรวจสอบ')
            if self._usage() + sum(len(raw) for raw in data.values()) > DISK_QUOTA:
                raise gis_error(507, 'GIS_PREPARE_STORAGE_LIMIT', 'พื้นที่เตรียมข้อมูลถึงขีดจำกัด')
            for kind, raw in data.items():
                path = self.objects / (proof['artifacts'][kind]['sha256'] + '.json')
                if path.exists():
                    if self._safe_read(path) != raw:
                        raise gis_error(409, 'GIS_PREPARE_IMMUTABLE_CONFLICT', 'ไฟล์ผลลัพธ์เดิมไม่ตรงกับ Hash')
                    continue
                temporary = self.objects / ('.pending-' + uuid4().hex)
                with temporary.open('xb') as stream:
                    stream.write(raw);stream.flush();os.fsync(stream.fileno())
                try:
                    os.link(temporary, path)
                except FileExistsError:
                    if self._safe_read(path) != raw:
                        raise gis_error(409, 'GIS_PREPARE_IMMUTABLE_CONFLICT', 'ไฟล์ผลลัพธ์เดิมไม่ตรงกับ Hash')
                finally:
                    temporary.unlink()
            self.read_files(request, proof['artifacts'])
            return proof

    def read_files(self, request, artifacts):
        """Required on every readiness/preview read, even with a DB certificate."""
        self.attest();check_request(request);self._source(request)
        if not isinstance(artifacts, dict) or set(artifacts) != set(NAMES):
            raise ValueError('PREPARE_ARTIFACT_INVALID')
        raw = {}
        for kind, item in artifacts.items():
            if not isinstance(item, dict) or set(item) != {'sha256', 'byte_size'}:
                raise ValueError('PREPARE_ARTIFACT_INVALID')
            import re
            if not isinstance(item['sha256'], str) or not re.fullmatch('[0-9a-f]{64}', item['sha256']):
                raise ValueError('PREPARE_ARTIFACT_INVALID')
            raw[kind] = self._safe_read(self.objects / (item['sha256'] + '.json'))
        if descriptors(raw) != artifacts:
            raise ValueError('PREPARE_ARTIFACT_CHANGED')
        return {kind: json.loads(value) for kind, value in raw.items()}
