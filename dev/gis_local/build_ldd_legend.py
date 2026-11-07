"""Build gis_worker/ldd_codes_v2.json from the official LDD code table (LUCODE.xls) shipped in the real packages.

The first legend (ldd_codes.json, 96 codes) came from the Bangkok 2566 data alone. Every province package carries
the producer's own table of Level-3 land-use codes ("Land Use Classification", sheet 1 of LUCODE.xls). The 24
tables found so far are identical. This tool turns that table into the second legend:

  * every code of the official table, with its Thai and English description and its class (U A F W M -> 1..5);
  * every entry of the first legend that is not in the table is carried over unchanged (composites such as
    U201/A401, and A800, which the table does not list) so nothing accepted before is refused now;
  * where a code is in both, the classes must agree and the first legend's text is kept; otherwise the build stops.

The output is deterministic (sorted keys, ASCII, no newline), so a hash-pinned asset does not change when Git
converts line endings. Packages are untrusted input: run in the pinned GIS image with no network and read-only
mounts, see run_build_ldd_legend.ps1. The .xls is read by a small bounded BIFF8 parser (no library is installed).

  python3 -I -B build_ldd_legend.py --base /app/gis_worker/ldd_codes.json --packages /data --out /out/ldd_codes_v2.json
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import struct
import sys
import zipfile

CODE = re.compile(r'^[UAFWM][0-9]{3}$')
CLASS = {'U': 1, 'A': 2, 'F': 3, 'W': 4, 'M': 5}
VERSION = 'ldd-codes-v2'
MAX_SECTORS, MAX_RECORDS = 1 << 16, 400000


# ---------------------------------------------------------------- minimal BIFF8 (.xls) reader
def ole_stream(data):
    if len(data) < 512 or data[:8] != bytes.fromhex('D0CF11E0A1B11AE1'):
        raise ValueError('not an OLE2 file')
    shift, mini_shift = struct.unpack_from('<HH', data, 30)
    if shift not in (9, 12) or mini_shift != 6:
        raise ValueError('unsupported sector size')
    size, mini_size = 1 << shift, 1 << mini_shift
    fat_count, dir_start = struct.unpack_from('<II', data, 44)[0], struct.unpack_from('<I', data, 48)[0]
    cutoff = struct.unpack_from('<I', data, 56)[0]
    minifat_start = struct.unpack_from('<I', data, 60)[0]
    difat_start, difat_count = struct.unpack_from('<II', data, 68)
    difat = list(struct.unpack_from('<109I', data, 76))
    sector = difat_start
    for _ in range(min(difat_count, 64)):
        if sector >= 0xFFFFFFFA:
            break
        block = struct.unpack_from('<%dI' % (size // 4), data, (sector + 1) * size)
        difat.extend(block[:-1])
        sector = block[-1]
    fat = []
    for index in difat[:fat_count]:
        if index < 0xFFFFFFFA:
            fat.extend(struct.unpack_from('<%dI' % (size // 4), data, (index + 1) * size))

    def chain(start, table=fat):
        out, seen = [], set()
        while start < 0xFFFFFFFA:
            if start in seen or len(out) > MAX_SECTORS or start >= len(table):
                raise ValueError('bad sector chain')
            seen.add(start)
            out.append(start)
            start = table[start]
        return out

    def read_chain(start, length=None):
        raw = b''.join(data[(s + 1) * size:(s + 2) * size] for s in chain(start))
        return raw if length is None else raw[:length]

    directory = read_chain(dir_start)
    entries = []
    for offset in range(0, len(directory) - 127, 128):
        name_len = struct.unpack_from('<H', directory, offset + 64)[0]
        entries.append((directory[offset:offset + max(0, name_len - 2)].decode('utf-16-le', 'replace'), directory[offset + 66],
                        struct.unpack_from('<I', directory, offset + 116)[0], struct.unpack_from('<Q', directory, offset + 120)[0]))
    target = next((e for e in entries if e[1] == 2 and e[0] in ('Workbook', 'Book')), None)
    if target is None:
        raise ValueError('no Workbook stream')
    if target[3] >= cutoff:
        return read_chain(target[2], target[3])
    root = next(e for e in entries if e[1] == 5)
    minifat = []
    for s in chain(minifat_start):
        minifat.extend(struct.unpack_from('<%dI' % (size // 4), data, (s + 1) * size))
    mini_stream = read_chain(root[2], root[3])
    return b''.join(mini_stream[s * mini_size:(s + 1) * mini_size] for s in chain(target[2], minifat))[:target[3]]


def records(stream):
    pos, count = 0, 0
    while pos + 4 <= len(stream):
        rid, length = struct.unpack_from('<HH', stream, pos)
        count += 1
        if count > MAX_RECORDS or pos + 4 + length > len(stream):
            raise ValueError('bad record stream')
        yield pos, rid, stream[pos + 4:pos + 4 + length]
        pos += 4 + length


def shared_strings(parts):
    """The SST record body followed by its CONTINUE bodies -> list of strings."""
    total_unique = struct.unpack_from('<II', parts[0], 0)[1]
    strings, index, offset = [], 0, 8

    def advance():
        nonlocal index, offset
        index += 1
        offset = 0
        if index >= len(parts):
            raise ValueError('SST truncated')

    def take(n):
        nonlocal offset
        chunk = parts[index][offset:offset + n]
        offset += n
        return chunk

    while len(strings) < total_unique:
        if offset >= len(parts[index]):
            advance()
        chars = struct.unpack('<H', take(2))[0]
        flags = take(1)[0]
        runs = struct.unpack('<H', take(2))[0] if flags & 0x08 else 0
        ext = struct.unpack('<I', take(4))[0] if flags & 0x04 else 0
        wide, text, remaining = bool(flags & 0x01), [], chars
        while remaining:
            if offset >= len(parts[index]):
                advance()
                wide = bool(parts[index][0] & 0x01)       # a CONTINUE restarts with its own encoding flag
                offset = 1
            width = 2 if wide else 1
            n = min(remaining, (len(parts[index]) - offset) // width)
            text.append(parts[index][offset:offset + n * width].decode('utf-16-le' if wide else 'latin-1'))
            offset += n * width
            remaining -= n
        skip = runs * 4 + ext
        while skip:
            if offset >= len(parts[index]):
                advance()
            n = min(skip, len(parts[index]) - offset)
            offset += n
            skip -= n
        strings.append(''.join(text))
    return strings


def first_sheet_text_cells(data):
    """{(row, col): text} of the first worksheet (numbers are ignored: the code table is text)."""
    stream = ole_stream(data)
    sheets, sst_parts, in_sst, strings = [], [], False, []
    for _, rid, body in records(stream):
        if rid == 0x00FC:
            sst_parts, in_sst = [body], True
        elif in_sst and rid == 0x003C:
            sst_parts.append(body)
        else:
            if in_sst:
                strings, in_sst = shared_strings(sst_parts), False
            if rid == 0x0085 and body[5] == 0:
                sheets.append(struct.unpack_from('<I', body, 0)[0])
    if not sheets:
        raise ValueError('no worksheet')
    cells, depth = {}, 0
    for _, rid, body in records(stream[sheets[0]:]):
        if rid == 0x0809:
            depth += 1
        elif rid == 0x000A:
            depth -= 1
            if depth <= 0:
                break
        elif rid == 0x00FD:
            row, col, _, isst = struct.unpack_from('<HHHI', body, 0)
            cells[(row, col)] = strings[isst]
        elif rid == 0x0204:
            row, col, _, chars = struct.unpack_from('<HHHH', body, 0)
            wide = body[8] & 1
            cells[(row, col)] = body[9:9 + chars * (2 if wide else 1)].decode('utf-16-le' if wide else 'latin-1')
    return cells


# ---------------------------------------------------------------- the official table
def clean(value):
    return re.sub(r'\s+', ' ', value.replace('\xa0', ' ')).strip() if isinstance(value, str) else ''


def official_table(cells):
    """code -> (Thai, English). Column 3 holds the Level-3 code (a leading * is a footnote marker)."""
    codes, last = {}, None
    for row in sorted({r for r, _ in cells}):
        code = re.sub(r'^[*\s]+', '', clean(cells.get((row, 3))))
        thai, english = clean(cells.get((row, 4))), clean(cells.get((row, 5)))
        if CODE.fullmatch(code):
            codes.setdefault(code, [thai, english])
            last = code
        elif last and not code and (thai or english) and not clean(cells.get((row, 0))) and not clean(cells.get((row, 1))):
            codes[last] = [(codes[last][0] + ' ' + thai).strip(), (codes[last][1] + ' ' + english).strip()]
        elif code:
            last = None
    return codes


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--base', type=Path, required=True)
    parser.add_argument('--packages', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(argv)

    base_bytes = args.base.read_bytes()
    base = json.loads(base_bytes)['codes']
    tables = {}
    for path in sorted(args.packages.glob('*.zip'), key=lambda p: p.name):
        try:
            archive = zipfile.ZipFile(path)
            member = next((i for i in archive.infolist() if PurePosixPath(i.filename).name.lower() == 'lucode.xls'), None)
            if member is None or member.file_size > 4 * 1024 ** 2:
                continue
            tables[path.name] = official_table(first_sheet_text_cells(archive.read(member)))
        except (zipfile.BadZipFile, ValueError, struct.error, KeyError, IndexError):
            continue
    if not tables:
        raise SystemExit('no readable LUCODE.xls in the packages')
    reference = next(iter(tables.values()))
    different = sorted(name for name, table in tables.items() if table != reference)
    if different:
        raise SystemExit('the official tables differ between packages: %d of %d' % (len(different), len(tables)))
    if len(reference) < 100:
        raise SystemExit('the official table looks incomplete: %d codes' % len(reference))

    codes, carried = {}, []
    for code, (thai, english) in reference.items():
        codes[code] = [CLASS[code[0]], thai, english]
    for code, entry in base.items():
        if code in codes:
            if codes[code][0] != entry[0]:
                raise SystemExit('class disagreement for ' + code)
            codes[code] = entry                         # the first legend's text is kept for a code in both
        else:
            codes[code] = entry
            carried.append(code)
    pairs = {}
    for code, entry in codes.items():
        if '/' not in code and pairs.setdefault(code[0], entry[0]) != entry[0]:
            raise SystemExit('inconsistent class for letter ' + code[0])
    if pairs != CLASS:
        raise SystemExit('class pairing differs from U=1 A=2 F=3 W=4 M=5')
    table_digest = hashlib.sha256(json.dumps(reference, ensure_ascii=True, sort_keys=True, separators=(',', ':')).encode('ascii')).hexdigest()
    asset = {'codes': codes, 'version': VERSION, 'base_asset': 'ldd_codes.json',
             'base_asset_sha256': hashlib.sha256(base_bytes).hexdigest(),
             'legend_source': 'LDD LUCODE.xls, sheet 1 (Land Use Classification, Level 3), plus the first legend (Bangkok 2566) unchanged',
             'official_table': {'codes': len(reference), 'identical_in_packages': len(tables), 'table_sha256': table_digest},
             'carried_from_first_legend': sorted(c for c in carried if '/' not in c),
             'carried_composites': sorted(c for c in carried if '/' in c)}
    data = json.dumps(asset, ensure_ascii=True, separators=(',', ':'), sort_keys=True).encode('ascii')
    args.out.write_bytes(data)
    print(json.dumps({'asset_sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data), 'codes': len(codes),
                      'official': len(reference), 'carried_single': asset['carried_from_first_legend'],
                      'carried_composites': len(asset['carried_composites']), 'packages_with_table': len(tables)}))


if __name__ == '__main__':
    sys.exit(main())
