"""Private immutable Local LDD objects; no dotenv, cloud SDK or native GIS import."""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import struct
import time
import unicodedata
from uuid import uuid4
import zipfile

from gis_service import gis_error

MAX_UPLOAD = 20 * 1024**2
DISK_QUOTA = 256 * 1024**2
MAX_EXPANDED = 80 * 1024**2
MAX_MEMBERS = 64
MAX_RATIO = 100
HASH = re.compile(r'^[0-9a-f]{64}$')
UPLOAD_PATH = re.compile(r'^/gis/datasets/[0-9a-fA-F-]{36}/ldd-uploads$')


def unsafe_link(path):
    return path.is_symlink() or (path.exists() and bool(getattr(path.lstat(), 'st_file_attributes', 0)
        & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0)))


def storage_error(code='GIS_LDD_STORAGE_UNAVAILABLE', status=503):
    return gis_error(status, code, {
        'GIS_LDD_SIZE_LIMIT': 'ไฟล์ ZIP ต้องมีขนาดไม่เกิน 20 MiB',
        'GIS_LDD_QUOTA': 'พื้นที่ Local สำหรับข้อมูล LDD เต็ม กรุณาติดต่อผู้ดูแลระบบ',
        'GIS_LDD_ZIP_UNSAFE': 'ZIP ไม่ปลอดภัย มี Path, Link หรือขนาดขยายที่ไม่อนุญาต',
        'GIS_LDD_ZIP_INVALID': 'ไฟล์ไม่ใช่ ZIP ที่อ่านได้ หรือข้อมูล ZIP ไม่สมบูรณ์',
        'GIS_LDD_UPLOAD_BUSY': 'มีการอัปโหลดอยู่ กรุณารอสักครู่แล้วลองคำสั่งเดิม',
        'GIS_LDD_UPLOAD_TIMEOUT': 'อัปโหลดนานเกินกำหนด กรุณาลองคำสั่งเดิมอีกครั้ง',
        'GIS_LDD_INTEGRITY': 'ไฟล์ในพื้นที่ Local มี Hash ไม่ตรง ระบบหยุดเพื่อป้องกันข้อมูลเสียหาย',
    }.get(code, 'พื้นที่ Local สำหรับ LDD ยังไม่พร้อมใช้งาน'))


def preflight_zip(path):
    """Metadata-only checks before publishing. Native child validates contents."""
    seen = set()
    try:
        # ZipFile eagerly materializes the complete central directory. Bound its
        # raw bytes and actual record count BEFORE constructing that parser.
        with path.open('rb') as source:
            size = path.stat().st_size
            source.seek(max(0, size - 65557))
            tail = source.read(65557)
            pos = tail.rfind(b'PK\x05\x06')
            if pos < 0 or pos + 22 > len(tail):
                raise storage_error('GIS_LDD_ZIP_INVALID', 422)
            _, disk, cd_disk, disk_count, count, cd_size, cd_offset, comment = struct.unpack_from('<4s4H2LH', tail, pos)
            eocd = max(0, size - 65557) + pos
            if (disk or cd_disk or disk_count != count or not 1 <= count <= MAX_MEMBERS
                or cd_size > 128 * 1024 or cd_offset + cd_size != eocd or pos + 22 + comment != len(tail)
                or cd_size == 0xffffffff or cd_offset == 0xffffffff):
                raise storage_error('GIS_LDD_ZIP_UNSAFE', 422)
            source.seek(cd_offset)
            directory = source.read(cd_size)
            cursor = 0
            actual = 0
            while cursor < len(directory):
                actual += 1
                if actual > MAX_MEMBERS or cursor + 46 > len(directory) or directory[cursor:cursor + 4] != b'PK\x01\x02':
                    raise storage_error('GIS_LDD_ZIP_UNSAFE', 422)
                name, extra, note, start_disk = struct.unpack_from('<4H', directory, cursor + 28)
                local_offset = struct.unpack_from('<L', directory, cursor + 42)[0]
                if name > 512 or start_disk or local_offset >= cd_offset:
                    raise storage_error('GIS_LDD_ZIP_UNSAFE', 422)
                cursor += 46 + name + extra + note
            if cursor != len(directory) or actual != count:
                raise storage_error('GIS_LDD_ZIP_UNSAFE', 422)
        with zipfile.ZipFile(path) as archive:
            items = archive.infolist()
            if not items or len(items) > MAX_MEMBERS:
                raise storage_error('GIS_LDD_ZIP_UNSAFE', 422)
            total = 0
            for item in items:
                # ZipInfo normalizes backslashes on Windows; inspect the raw
                # original name so Linux and Windows reject the same archive.
                name = item.orig_filename
                normalized = unicodedata.normalize('NFC', name).casefold()
                parts = name.split('/')
                mode = item.external_attr >> 16
                if (len(name.encode('utf-8')) > 512 or name.startswith('/') or '\\' in name or ':' in name
                    or '\x00' in name or any(p in ('.', '..') for p in parts) or normalized in seen
                    or stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR)
                    or item.flag_bits & 1 or item.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)):
                    raise storage_error('GIS_LDD_ZIP_UNSAFE', 422)
                seen.add(normalized)
                total += item.file_size
                if (item.file_size > MAX_UPLOAD or total > MAX_EXPANDED
                    or (item.file_size and (not item.compress_size or item.file_size / item.compress_size > MAX_RATIO))):
                    raise storage_error('GIS_LDD_ZIP_UNSAFE', 422)
                if not item.is_dir() and PurePosixPath(name).suffix.lower() not in ('.shp', '.shx', '.dbf', '.prj', '.cpg', '.sbn', '.sbx', '.qix'):
                    raise storage_error('GIS_LDD_ZIP_UNSAFE', 422)
    except (zipfile.BadZipFile, OSError, ValueError, NotImplementedError):
        raise storage_error('GIS_LDD_ZIP_INVALID', 422) from None


class LocalLddStore:
    """Operator supplies the attested T0 directory; API never accepts a root/path.

    A root owner marker and exact directory/file checks are repeated before writes.
    OS file locks serialize uploads across processes. A killed upload leaves an
    unreferenced staged object counted against quota, never a successful DB row.
    """

    STORAGE_NAME = 'ldd-storage'
    OWNER_SCOPE = 'gis-ldd-storage-v1'
    REQUIRED_MIGRATION = 34
    OBJECT_SUFFIX = '.zip'

    def preflight(self, path):
        preflight_zip(path)

    def __init__(self, runtime, runtime_dir: Path):
        self.runtime = runtime
        self.runtime_dir = Path(runtime_dir)
        self.root = self.runtime_dir / self.STORAGE_NAME
        self.objects = self.root / 'objects'
        self.staging = self.root / 'staging'
        self._owner = self._expected_owner()
        self.attest(parent_only=True)
        if not self.root.exists():
            self.root.mkdir(mode=0o700)
            with (self.root / 'owner.json').open('x', encoding='utf-8') as out:
                json.dump(self._owner, out)
            self.objects.mkdir(mode=0o700)
            self.staging.mkdir(mode=0o700)
        self.attest()

    def _expected_owner(self):
        s = self.runtime.settings
        return {'scope': self.OWNER_SCOPE, 'runtime_instance': s.runtime_instance,
            'baseline_fingerprint': s.baseline_fingerprint, 'database': s.database, 'cluster': s.cluster}

    def attest(self, *, parent_only=False):
        ready = self.runtime.require_ready()
        s = self.runtime.settings
        if (s.api_url != 'http://127.0.0.1:55421' or s.database != 'postgres' or s.cluster != 'green-area-gis-t0'
            or not isinstance(ready, dict) or self.REQUIRED_MIGRATION not in ready.get('migration_versions', [])):
            raise storage_error()
        try:
            if any(unsafe_link(p) for p in (self.runtime_dir, *self.runtime_dir.parents)):
                raise ValueError()
            owner_path = self.runtime_dir / 'owner.json'
            if owner_path.is_symlink():
                raise ValueError()
            owner = json.loads(owner_path.read_text(encoding='utf-8'))
            if owner.get('scope') != 'gis-foundation-t0' or owner.get('project') != s.cluster or owner.get('instance') != s.runtime_instance:
                raise ValueError()
            if not parent_only:
                for p in (self.root, self.objects, self.staging):
                    if unsafe_link(p) or not p.is_dir() or p.resolve().parent != p.parent.resolve():
                        raise ValueError()
                marker = self.root / 'owner.json'
                if marker.is_symlink() or json.loads(marker.read_text(encoding='utf-8')) != self._owner:
                    raise ValueError()
        except (OSError, ValueError, TypeError):
            raise storage_error() from None

    @contextmanager
    def _lock(self):
        path = self.root / 'upload.lock'
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise storage_error()
        fd = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        locked = False
        try:
            if os.fstat(fd).st_size == 0:
                os.write(fd, b'0')
            os.lseek(fd, 0, os.SEEK_SET)
            try:
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
            except OSError:
                raise storage_error('GIS_LDD_UPLOAD_BUSY', 429) from None
            yield
        finally:
            if locked:
                os.lseek(fd, 0, os.SEEK_SET)
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def _usage(self):
        total = 0
        count = 0
        for directory in (self.objects, self.staging):
            for p in directory.iterdir():
                if p.is_symlink() or not p.is_file() or p.stat().st_nlink > 1:
                    raise storage_error()
                total += p.stat().st_size
                count += 1
                if count > 4096:
                    raise storage_error('GIS_LDD_QUOTA', 507)
        return total

    @staticmethod
    def checksum(path):
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            while chunk := stream.read(65536):
                digest.update(chunk)
        return digest.hexdigest()

    async def receive(self, stream, *, declared_size=None):
        self.attest()
        if declared_size is not None and (declared_size < 1 or declared_size > MAX_UPLOAD):
            raise storage_error('GIS_LDD_SIZE_LIMIT', 413)
        with self._lock():
            used = self._usage()
            temp = self.staging / (uuid4().hex + '.part')
            size = 0
            digest = hashlib.sha256()
            started = time.monotonic()
            try:
                with temp.open('xb') as out:
                    iterator = stream.__aiter__()
                    while True:
                        if time.monotonic() - started >= 60:
                            raise storage_error('GIS_LDD_UPLOAD_TIMEOUT', 408)
                        try:
                            chunk = await asyncio.wait_for(iterator.__anext__(), timeout=min(10, max(.001, 60 - (time.monotonic() - started))))
                        except StopAsyncIteration:
                            break
                        except asyncio.TimeoutError:
                            raise storage_error('GIS_LDD_UPLOAD_TIMEOUT', 408) from None
                        if time.monotonic() - started >= 60:
                            raise storage_error('GIS_LDD_UPLOAD_TIMEOUT', 408)
                        size += len(chunk)
                        if size > MAX_UPLOAD:
                            raise storage_error('GIS_LDD_SIZE_LIMIT', 413)
                        if used + size > DISK_QUOTA:
                            raise storage_error('GIS_LDD_QUOTA', 507)
                        digest.update(chunk)
                        out.write(chunk)
                    out.flush()
                    os.fsync(out.fileno())
                if not size or (declared_size is not None and size != declared_size):
                    raise storage_error('GIS_LDD_ZIP_INVALID', 422)
                self.preflight(temp)
                checksum = digest.hexdigest()
                target = self.objects / (checksum + self.OBJECT_SUFFIX)
                self.attest()
                if target.exists():
                    if target.is_symlink() or not target.is_file() or target.stat().st_nlink > 1 or target.stat().st_size != size or self.checksum(target) != checksum:
                        raise storage_error('GIS_LDD_INTEGRITY')
                else:
                    # Hard link is atomic and refuses replacement. Only remove our
                    # private staging name, never any published/original object.
                    try:
                        os.link(temp, target)
                        temp.unlink()
                    except FileExistsError:
                        if target.is_symlink() or self.checksum(target) != checksum:
                            raise storage_error('GIS_LDD_INTEGRITY') from None
                    os.chmod(target, 0o444)
                return {'sha256': checksum, 'byte_size': size}
            finally:
                # This random file was created by this request; old/orphan staged
                # objects and published originals are never deleted automatically.
                if temp.exists():
                    if os.name == 'nt':
                        os.chmod(temp, 0o600)
                    temp.unlink()
