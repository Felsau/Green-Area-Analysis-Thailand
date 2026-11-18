"""Read-only inventory of LDD province land-use ZIPs (C4, week 3).

Reads every per-province ZIP through Python's zipfile only: nothing is extracted, written back or modified.
Uses the system's own rules from the repository instead of re-implementing them:
  gis_worker.ldd_policy.select_land_use_layer, resolve_profile, horizontal_wkt
  gis_ldd_storage.preflight_zip
and also computes the caps itself (ZIP > 20 MiB, any member > 20 MiB, expanded total > 80 MiB, > 64 members,
any member ratio > 100). EPSG of the .prj is found with pyproj when installed, else rasterio.crs.CRS.

Usage:
  python -I c4_inventory.py --code <repo-root> --zips <folder with one sub-folder per region> \
      [--bangkok <Bangkok ZIP>] --out <inventory.csv> [--missing "<region>=<province_th>=<note>" ...]

Region folder names are taken as the region, with a small spelling fix table (see REGION_FIX). No machine
path is written to the CSV: only file names.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import re
import struct
import sys
import zipfile
from pathlib import Path, PurePosixPath

sys.stdout.reconfigure(encoding='utf-8')

COLUMNS = ['region', 'province_th', 'zip_name', 'zip_bytes', 'zip_sha256', 'data_year_be', 'lu_layer', 'feature_count',
           'lu_fields', 'field_profile', 'cpg', 'prj_epsg', 'has_pro', 'has_amp', 'has_tam', 'amp_count',
           'largest_member', 'largest_bytes', 'largest_ratio', 'expanded_total', 'member_count', 'preflight', 'note']
REGION_FIX = {'ภาคตะวันตะวันออกเฉียงเหนือ': 'ภาคตะวันออกเฉียงเหนือ'}
REGION_ORDER = ['กรุงเทพฯ', 'ภาคกลาง', 'ภาคตะวันออกเฉียงเหนือ', 'ภาคเหนือ', 'ภาคใต้']
NAME_EN_TH = {'Sing Buri': 'สิงห์บุรี', 'Bangkok': 'กรุงเทพมหานคร'}
MIB = 1024 ** 2
CAP_ZIP, CAP_MEMBER, CAP_TOTAL, CAP_MEMBERS, CAP_RATIO = 20 * MIB, 20 * MIB, 80 * MIB, 64, 100


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def member_name(info):
    """Decoded member name and the encoding used (UTF-8 flag, else the cp437 bytes read as cp874)."""
    if info.flag_bits & 0x800:
        return info.filename, 'utf-8'
    try:
        return info.filename.encode('cp437').decode('cp874'), 'cp874'
    except UnicodeError:
        return info.filename, 'cp437'


def read_dbf_header(z, info):
    with z.open(info) as f:
        head = f.read(32)
        if len(head) < 32:
            raise ValueError('DBF_HEADER_SHORT')
        nrec, hlen, _rlen = struct.unpack('<IHH', head[4:12])
        raw = f.read(max(0, hlen - 32))
    names = []
    for i in range(0, len(raw), 32):
        d = raw[i:i + 32]
        if not d or d[0] == 0x0D or len(d) < 32:
            break
        b = d[:11].split(b'\x00')[0]
        try:
            names.append(b.decode('ascii'))
        except UnicodeDecodeError:
            names.append(b.decode('cp874', 'replace'))
    return nrec, names


def read_text(z, info):
    data = z.read(info)
    for enc in ('utf-8', 'cp874', 'latin-1'):
        try:
            return data.decode(enc).strip()
        except UnicodeDecodeError:
            continue
    return ''


def epsg_of(wkt):
    try:
        import pyproj  # noqa: F401
        crs = pyproj.CRS.from_wkt(wkt)
        return crs.to_epsg(), 'pyproj'
    except ImportError:
        from rasterio.crs import CRS
        return CRS.from_wkt(wkt).to_epsg(), 'rasterio'


def projcs_name(wkt):
    m = re.match(r'\s*(?:PROJCS|GEOGCS)\["([^"]*)"', wkt or '')
    return m.group(1) if m else ''


def boundary_kind(fields):
    up = [f.upper() for f in fields]
    if any(f.startswith(('TAMBON_', 'TAM_')) for f in up):
        return 'tam'
    if any(f.startswith('AMPHOE_') for f in up):
        return 'amp'
    if any(f.startswith('PROV_') for f in up):
        return 'pro'
    return None


def kind_from_name(name):
    n = PurePosixPath(name).stem.casefold()
    if re.search(r'(^|[_\s])(tam|tambon)', n) or 'ตำบล' in n:
        return 'tam'
    if re.search(r'(^|[_\s])(amp|amphoe)', n) or 'อำเภอ' in n:
        return 'amp'
    if re.search(r'(^|[_\s])(pro|prov|province)', n) or 'จังหวัด' in n:
        return 'pro'
    return None


def province_and_year(zip_name, layer):
    stem = Path(zip_name).stem
    thai = [t for t in re.findall(r'[฀-๿]+', stem) if t not in ('ปีล่าสุด', 'ปี', 'ล่าสุด')]
    thai = [t.replace('ปีล่าสุด', '') for t in thai]
    name = next((t for t in thai if t), '')
    notes = []
    if not name:
        for en, th in NAME_EN_TH.items():
            if en.casefold() in stem.casefold():
                name = th
                notes.append(f'province name from English "{en}" in file name')
    years_file = [int(y) for y in re.findall(r'25[0-9]{2}', stem)]
    years_layer = [int(y) for y in re.findall(r'25[0-9]{2}', PurePosixPath(layer or '').name)]
    year = ''
    if years_layer:
        year = max(years_layer)
    if years_file:
        if len(set(years_file)) > 1:
            notes.append(f'file name names several years {sorted(set(years_file))}; used the latest')
        if year and max(years_file) != year:
            notes.append(f'year in file name {max(years_file)} differs from layer name {year}; used the layer')
        year = year or max(years_file)
    elif year:
        notes.append('no year in file name; year from the land-use layer name')
    else:
        notes.append('no year in file name or layer name')
    if 'ปีล่าสุด' in stem:
        notes.append('file marked "ปีล่าสุด"')
    return name, year, notes


def system_preflight(storage, storage_err, path, data=None):
    if storage is None:
        return f'not run ({storage_err})'
    try:
        if data is None:
            storage.preflight_zip(path)
        else:  # a ZIP held in memory: the system function reads it through its open_read hook
            storage.preflight_zip(path, open_read=lambda _p: io.BytesIO(data))
        return 'pass'
    except Exception as exc:
        detail = getattr(exc, 'detail', None)
        return detail.get('code') if isinstance(detail, dict) else type(exc).__name__


def inventory(path, region, policy, storage, storage_err):
    """Inventory one province ZIP. A wrapper ZIP that holds no shapefile but nested ZIPs is opened one level
    down, in memory only: the largest nested ZIP is read as the province package."""
    with zipfile.ZipFile(path) as z:
        names = [member_name(i)[0] for i in z.infolist() if not i.is_dir()]
        nested = [i for i in z.infolist() if not i.is_dir() and member_name(i)[0].lower().endswith('.zip')]
        if policy.select_land_use_layer(names) is None and nested:
            inner = max(nested, key=lambda i: i.file_size)
            iname = PurePosixPath(member_name(inner)[0]).name
            data = z.read(inner)
            # content columns from the nested ZIP (read in memory with zipfile + io.BytesIO, nothing on disk)
            row = analyse(io.BytesIO(data), iname, len(data), hashlib.sha256(data).hexdigest(), region, policy,
                          system_preflight(storage, storage_err, Path(iname), data))
            inner_note = (f'data is in a nested ZIP: {path.name} holds '
                          f'{", ".join(PurePosixPath(member_name(i)[0]).name for i in nested)}; lu_layer..amp_count read from '
                          f'{iname} ({len(data)} bytes, sha256 {row["zip_sha256"]}) in memory, not extracted; '
                          f'{iname} alone would give preflight "{row["preflight"]}" and largest {row["largest_member"]} '
                          f'{row["largest_bytes"]} B, expanded {row["expanded_total"]} B, {row["member_count"]} members')
            # the uploaded file is the wrapper: name, size, sha256, sizes and preflight come from it
            row.update(zip_name=path.name, zip_bytes=path.stat().st_size, zip_sha256=sha256(path))
            caps, size_notes = size_caps(z.infolist(), row['zip_bytes'], row)
            system = system_preflight(storage, storage_err, path)
            row['preflight'] = f'{system}; caps={"+".join(caps) if caps else "ok"}'
            row['note'] = ' | '.join([inner_note, f'the system preflight refuses the uploaded ZIP ({system})']
                                     + size_notes + [row['note']])
            return row
    return analyse(path, path.name, path.stat().st_size, sha256(path), region, policy,
                   system_preflight(storage, storage_err, path))


def analyse(source, display_name, zip_bytes, zip_sha, region, policy, system):
    row = dict.fromkeys(COLUMNS, '')
    notes = []
    row.update(region=region, zip_name=display_name, zip_bytes=zip_bytes, zip_sha256=zip_sha)
    with zipfile.ZipFile(source) as z:
        infos = z.infolist()
        decoded = [(member_name(i), i) for i in infos]
        encs = sorted({enc for (_, enc), _ in decoded})
        notes.append(f'member names: {"/".join(encs)}')
        files = [(n, i) for (n, _), i in decoded if not i.is_dir()]
        names = [n for n, _ in files]
        by_name = {n: i for n, i in files}
        layer = policy.select_land_use_layer(names)
        row['lu_layer'] = PurePosixPath(layer).name if layer else ''
        if not layer:
            notes.append(f'select_land_use_layer -> None ({sum(1 for n in names if n.lower().endswith(".shp"))} .shp)')
        province, year, more = province_and_year(display_name.split(' > ')[-1], layer)
        row['province_th'], row['data_year_be'] = province, year
        notes += more
        # land-use layer parts
        if layer:
            stem = layer[:-4]
            part = {s: next((i for n, i in files if n.casefold() == (stem + s).casefold()), None)
                    for s in ('.dbf', '.prj', '.cpg')}
            if part['.dbf'] is not None:
                n, fields = read_dbf_header(z, part['.dbf'])
                row['feature_count'], row['lu_fields'] = n, ';'.join(fields)
                try:
                    pid, roles = policy.resolve_profile(fields)
                    row['field_profile'] = pid
                except policy.PolicyError as exc:
                    row['field_profile'] = str(exc)
                    have = {f.casefold() for f in fields}
                    why = []
                    for pid, prof in policy.FIELD_PROFILES.items():
                        miss = [f for f in prof['roles'].values() if f.casefold() not in have]
                        extra = [f for f in prof.get('absent', ()) if f.casefold() in have]
                        why.append(f'{pid}: missing {"/".join(miss) or "-"}'
                                   + (f', must not have {"/".join(extra)}' if extra else ''))
                    notes.append(f'{exc} -> ' + '; '.join(why))
            else:
                notes.append('land-use .dbf missing')
            row['cpg'] = read_text(z, part['.cpg']) if part['.cpg'] is not None else 'none'
            if part['.prj'] is not None:
                text = read_text(z, part['.prj'])
                wkt = policy.horizontal_wkt(text) or text
                if policy.horizontal_wkt(text):
                    notes.append('.prj has a VERTCS part; EPSG from the horizontal part')
                try:
                    code, lib = epsg_of(wkt)
                except Exception as exc:  # unreadable WKT
                    code, lib = None, f'error {type(exc).__name__}'
                row['prj_epsg'] = f'EPSG:{code}' if code else 'unknown'
                if not code:
                    notes.append(f'PROJCS "{projcs_name(wkt)}" ({lib})')
            else:
                row['prj_epsg'] = 'unknown'
                notes.append('land-use .prj missing')
        # boundary layers
        kinds, amp_count, seen = {'pro': [], 'amp': [], 'tam': []}, '', []
        for n, i in files:
            if not n.lower().endswith('.shp') or (layer and n == layer):
                continue
            dbf = next((j for m, j in files if m.casefold() == (n[:-4] + '.dbf').casefold()), None)
            kind, how, count = None, '', ''
            if dbf is not None:
                cnt, fields = read_dbf_header(z, dbf)
                kind, how, count = boundary_kind(fields), 'fields', cnt
            if kind is None:
                kind, how = kind_from_name(n), 'file name'
            seen.append(f'{PurePosixPath(n).name}={kind or "?"}({how})')
            if kind:
                kinds[kind].append(n)
                if kind == 'amp' and amp_count == '':
                    amp_count = count
        row['has_pro'], row['has_amp'], row['has_tam'] = (('yes' if kinds[k] else 'no') for k in ('pro', 'amp', 'tam'))
        row['amp_count'] = amp_count
        if seen:
            notes.append('other layers: ' + ', '.join(seen))
        # .shp header bounding box, checked against the declared EPSG
        if layer and row['prj_epsg'].startswith('EPSG:'):
            shp = next((i for n, i in files if n == layer), None)
            if shp is not None:
                notes.append(bbox_check(z, shp, int(row['prj_epsg'][5:]), row['province_th']))
        # sizes from the central directory
        caps, size_notes = size_caps(infos, row['zip_bytes'], row)
        notes += size_notes
    # system = gis_ldd_storage.preflight_zip result (metadata checks; the 20 MiB upload size is checked at upload)
    row['preflight'] = f'{system}; caps={"+".join(caps) if caps else "ok"}'
    row['note'] = ' | '.join(notes)
    return row


def size_caps(infos, zip_bytes, row):
    """Fill largest_member/bytes/ratio, expanded_total, member_count from a central directory; return the caps."""
    notes = []
    members = [i for i in infos if not i.is_dir()]
    total = sum(i.file_size for i in infos)
    big = max(members, key=lambda i: i.file_size) if members else None
    ratio = lambda i: (i.file_size / i.compress_size) if i.compress_size else (float('inf') if i.file_size else 0.0)
    if big:
        row['largest_member'] = PurePosixPath(member_name(big)[0]).name
        row['largest_bytes'] = big.file_size
        row['largest_ratio'] = f'{ratio(big):.2f}'
    row['expanded_total'], row['member_count'] = total, len(infos)
    caps = []
    if zip_bytes > CAP_ZIP:
        caps.append('zip>20MiB')
    if any(i.file_size > CAP_MEMBER for i in infos):
        caps.append('member>20MiB')
    if total > CAP_TOTAL:
        caps.append('expanded>80MiB')
    if len(infos) > CAP_MEMBERS:
        caps.append('members>64')
    worst = max(infos, key=ratio) if infos else None
    if worst and ratio(worst) > CAP_RATIO:
        caps.append('ratio>100')
        if worst is not big:
            notes.append(f'max ratio {ratio(worst):.2f} in {PurePosixPath(member_name(worst)[0]).name}')
    return caps, notes


SYSTEM_BOXES = {}  # Thai province name (C4 province_th) -> lon/lat box of the same province in data/thailand.json


def load_system_boxes(backend):
    """Lon/lat boxes of the system provinces, keyed by the Thai name of the GADM feature (NL_NAME_1 without the
    "จังหวัด" prefix). Five NL_NAME_1 values are wrong in that file, so a box is only used when the name is unique and
    names that province; the English name is kept to report which feature was used."""
    import json
    feats = json.load(open(backend / 'data/thailand.json', encoding='utf-8'))['features']
    seen = {}
    for f in feats:
        th = (f['properties'].get('NL_NAME_1') or '').removeprefix('จังหวัด')
        xs, ys = [], []

        def walk(c):
            if isinstance(c[0], (int, float)):
                xs.append(c[0]); ys.append(c[1])
            else:
                for k in c:
                    walk(k)
        walk(f['geometry']['coordinates'])
        seen.setdefault(th, []).append((f['properties']['name'], min(xs), max(xs), min(ys), max(ys)))
    SYSTEM_BOXES.update({k: v[0] for k, v in seen.items() if len(v) == 1})


def bbox_check(z, shp_info, epsg, province_th=''):
    """Read the .shp header (first 100 bytes) bounding box and test it against the declared EPSG.

    The box is converted to longitude/latitude with the declared CRS and compared with the box of the same province
    in data/thailand.json: 'consistent' when the two boxes overlap and their centres are within 0.5 degree. The note
    also says whether the centre lies inside the standard 6-degree band of the declared UTM zone (LDD layers may run a
    zone past its edge, which is not an error in itself).
    """
    with z.open(shp_info) as f:
        head = f.read(100)
    if len(head) < 100 or struct.unpack('>i', head[:4])[0] != 9994:
        return 'bbox: .shp header not readable'
    xmin, ymin, xmax, ymax = struct.unpack('<4d', head[36:68])
    text = f'bbox x {xmin:.0f}..{xmax:.0f} y {ymin:.0f}..{ymax:.0f}'
    if not 32601 <= epsg <= 32660:
        return text + f' (EPSG:{epsg} not UTM north; not checked)'
    from rasterio.crs import CRS
    from rasterio.warp import transform
    lons, lats = transform(CRS.from_epsg(epsg), CRS.from_epsg(4326), [xmin, xmax], [ymin, ymax])
    lo0, lo1, la0, la1 = min(lons), max(lons), min(lats), max(lats)
    zone = epsg - 32600
    west, east = -180 + 6 * (zone - 1), -180 + 6 * zone
    clon, clat = (lo0 + lo1) / 2, (la0 + la1) / 2
    band = 'inside' if west <= clon <= east else 'outside'
    text += (f' -> lon {lo0:.2f}..{lo1:.2f} lat {la0:.2f}..{la1:.2f} with EPSG:{epsg}; centre {band} the zone {zone} '
             f'band {west}..{east} E')
    box = SYSTEM_BOXES.get(province_th)
    if not box:
        return text + '; system box: none (no unique NL_NAME_1 for this province), not compared'
    name, sx0, sx1, sy0, sy1 = box
    overlap = lo0 <= sx1 and sx0 <= lo1 and la0 <= sy1 and sy0 <= la1
    near = abs(clon - (sx0 + sx1) / 2) <= 0.5 and abs(clat - (sy0 + sy1) / 2) <= 0.5
    verdict = 'consistent' if overlap and near else 'NOT consistent'
    return text + f'; system {name} lon {sx0:.2f}..{sx1:.2f} lat {sy0:.2f}..{sy1:.2f}: {verdict}'


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--code', required=True, type=Path, help='repository root (green-area-backend inside)')
    ap.add_argument('--zips', required=True, type=Path, help='folder with one sub-folder of ZIPs per region')
    ap.add_argument('--bangkok', type=Path, help='Bangkok ZIP (region กรุงเทพฯ)')
    ap.add_argument('--out', required=True, type=Path)
    ap.add_argument('--missing', action='append', default=[], help='"<region>=<province_th>=<note>" for a row with no file')
    args = ap.parse_args()
    backend = args.code / 'green-area-backend'
    sys.path.insert(0, str(backend))
    from gis_worker import ldd_policy as policy
    load_system_boxes(backend)
    try:
        import gis_ldd_storage as storage
        storage_err = ''
    except Exception as exc:  # report, then fall back to the computed caps only
        storage, storage_err = None, f'import gis_ldd_storage failed: {type(exc).__name__}: {exc}'
        print(storage_err)
    jobs = []
    if args.bangkok:
        jobs.append(('กรุงเทพฯ', args.bangkok))
    for d in sorted(p for p in args.zips.iterdir() if p.is_dir()):
        region = REGION_FIX.get(d.name, d.name)
        for z in sorted(d.glob('*.zip')):
            jobs.append((region, z))
    rows = []
    for region, path in jobs:
        try:
            rows.append(inventory(path, region, policy, storage, storage_err))
        except Exception as exc:
            row = dict.fromkeys(COLUMNS, '')
            row.update(region=region, zip_name=path.name, note=f'READ FAILED: {type(exc).__name__}: {exc}')
            rows.append(row)
        r = rows[-1]
        print(f'{r["region"]:<24} {r["province_th"]:<16} {r["feature_count"]!s:>7} {r["field_profile"]:<26} {r["preflight"]}')
    for m in args.missing:
        region, prov, note = m.split('=', 2)
        row = dict.fromkeys(COLUMNS, '')
        row.update(region=region, province_th=prov, note=note)
        rows.append(row)
    rows.sort(key=lambda r: (REGION_ORDER.index(r['region']) if r['region'] in REGION_ORDER else 99, r['province_th']))
    with open(args.out, 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)
    from collections import Counter
    print('rows:', len(rows), dict(Counter(r['region'] for r in rows)))


if __name__ == '__main__':
    main()
