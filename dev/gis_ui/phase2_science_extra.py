"""Additional known-invalid synthetic Shapefile scientific checks, Linux only."""
from io import BytesIO
import hashlib
import struct
import zipfile
from pathlib import Path
from gis_worker import ldd_provider as ldd

def modified(tmp_path, mutate):
    raw = (Path(ldd.__file__).parent / 'fixtures/ldd_valid.zip').read_bytes()
    with zipfile.ZipFile(BytesIO(raw)) as archive:
        parts = {n: archive.read(n) for n in archive.namelist()}
    mutate(parts)
    out = BytesIO()
    with zipfile.ZipFile(out, 'w', compression=zipfile.ZIP_STORED) as archive:
        for n, value in parts.items():
            archive.writestr(n, value)
    raw = out.getvalue()
    sha = hashlib.sha256(raw).hexdigest()
    (tmp_path / (sha + '.zip')).write_bytes(raw)
    return {'upload_id': '11111111-1111-4111-8111-111111111111',
        'manifest': {'schema_version': 1, 'provider': 'real', 'provenance': 'local-ldd-upload-v1',
            'sha256': sha, 'byte_size': len(raw), 'crs': 'EPSG:32647', 'data_kind': 'polygon',
            'attributes': list(ldd.REQUIRED_FIELDS)}, 'input_hash': 'a' * 64, 'input_revision': 1,
        'attempt_number': 1, 'province': 'Bangkok Metropolis', 'data_year': 2026, 'encoding': 'auto'}

def test_missing_required_attribute_rejected(tmp_path):
    def change(parts):
        name = next(n for n in parts if n.endswith('.dbf'))
        data = bytearray(parts[name])
        header = struct.unpack_from('<H', data, 8)[0]
        for offset in range(32, header - 1, 32):
            if bytes(data[offset:offset+11]).split(b'\0')[0] == b'LU_CODE':
                data[offset:offset+11] = b'BADCODE\0\0\0\0'
                break
        parts[name] = bytes(data)
    report = ldd.validate(modified(tmp_path, change), storage_root=tmp_path)
    assert not report['valid'] and report['error_code'] == 'ATTRIBUTES_MISSING'

def test_nonpolygon_header_rejected(tmp_path):
    def change(parts):
        for name in parts:
            if name.endswith(('.shp', '.shx')):
                data = bytearray(parts[name])
                struct.pack_into('<i', data, 32, 3)
                parts[name] = bytes(data)
    report = ldd.validate(modified(tmp_path, change), storage_root=tmp_path)
    assert not report['valid'] and report['error_code'] == 'GEOMETRY_TYPE'

def test_self_intersection_rejected_without_success_result(tmp_path):
    def change(parts):
        name = next(n for n in parts if n.endswith('.shp'))
        data = bytearray(parts[name])
        content = 108
        num_parts = struct.unpack_from('<i', data, content + 36)[0]
        start = content + 44 + num_parts * 4
        a, b = start + 16, start + 32
        data[a:a+16], data[b:b+16] = bytes(data[b:b+16]), bytes(data[a:a+16])
        parts[name] = bytes(data)
    report = ldd.validate(modified(tmp_path, change), storage_root=tmp_path)
    assert not report['valid'] and report['error_code'] == 'GEOMETRY_INVALID'
    assert report['statistics']['geometry_error_count'] > 0
