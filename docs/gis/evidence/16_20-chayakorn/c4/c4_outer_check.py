"""Compare per-province ZIPs on disk with the members of a region ZIP, using size and CRC32 from the region ZIP's
central directory (nothing is extracted). Read-only.

Usage: python -I c4_outer_check.py <region.zip> <folder with the per-province ZIPs of that region>
Prints: region ZIP size and sha256, then one line per .zip member (match / size differs / CRC differs / not on disk)
and the per-province ZIPs on disk that are not in the region ZIP.
"""
import hashlib
import sys
import zipfile
import zlib
from pathlib import Path, PurePosixPath

sys.stdout.reconfigure(encoding='utf-8')
outer, folder = Path(sys.argv[1]), Path(sys.argv[2])


def name(info):
    if info.flag_bits & 0x800:
        return info.filename
    try:
        return info.filename.encode('cp437').decode('cp874')
    except UnicodeError:
        return info.filename


def file_crc_sha(p):
    crc, h = 0, hashlib.sha256()
    with open(p, 'rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            crc = zlib.crc32(block, crc)
            h.update(block)
    return crc & 0xFFFFFFFF, h.hexdigest()


_, sha = file_crc_sha(outer)
print(f'region ZIP: {outer.name} · {outer.stat().st_size} bytes · sha256 {sha}')
on_disk = {p.name: p for p in folder.glob('*.zip')}
seen = set()
counts = {'match': 0, 'differs': 0, 'missing': 0}
with zipfile.ZipFile(outer) as z:
    utf8 = sum(1 for i in z.infolist() if i.flag_bits & 0x800)
    print(f'members {len(z.infolist())} · UTF-8 flag on {utf8} · others decoded as cp874')
    for i in z.infolist():
        n = name(i)
        base = PurePosixPath(n).name
        if i.is_dir() or not base.lower().endswith('.zip'):
            if not i.is_dir():
                print(f'  (not a .zip) {n} {i.file_size} B')
            continue
        p = on_disk.get(base)
        if p is None:
            counts['missing'] += 1
            print(f'  NOT ON DISK  {n}  {i.file_size} B crc {i.CRC:08x}')
            continue
        seen.add(base)
        crc, _ = file_crc_sha(p)
        size_ok, crc_ok = p.stat().st_size == i.file_size, crc == i.CRC
        status = 'match' if size_ok and crc_ok else ('size differs' if not size_ok else 'CRC differs')
        counts['match' if status == 'match' else 'differs'] += 1
        print(f'  {status:<12} {base}  size {i.file_size} / {p.stat().st_size}  crc {i.CRC:08x} / {crc:08x}')
for base in sorted(set(on_disk) - seen):
    print(f'  ONLY ON DISK {base}')
print('summary', counts, 'only on disk:', len(set(on_disk) - seen))
