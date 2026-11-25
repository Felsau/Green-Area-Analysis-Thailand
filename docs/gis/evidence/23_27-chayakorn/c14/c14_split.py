"""C14 (week 4): split a real LDD land-use package into one package per district and measure each against the
upload/validator/prepare caps. Read-only on every input; writes only under --work and the result files.

* District = the OCHA tha_admin2 polygon (EPSG:4326, transformed to the package CRS) that the parcel's
  representative_point() falls in. Parcels are never cut. A point in no district is counted and written apart
  (NONE). A point in a district of another province keeps that district (flagged other_province).
* Each district is written as a single-layer shapefile by copying the original records byte for byte: the .shp
  geometry records and .dbf rows are the source bytes (record numbers, file lengths, bounding box and the .dbf
  record count are rewritten; the Z/M range in the header is kept from the source). .prj and .cpg are the source
  bytes. Names: <source LU_ stem>_<adm2_pcode>. Then ZIP (deflate).
* Every output is re-read with the system's own ldd_provider._record_count (structure) and
  ldd_provider.guarded_zip(package=True) with the system caps (first cap hit, else ok).
* Vertices: ldd_provider._coordinates per parcel, as the validator counts. GeoJSON size: the C8 "raw" writer
  (EPSG:4326, 6 decimals, sorted keys, no spaces), computed in memory.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import struct
import sys
import time
import zipfile
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath

sys.stdout.reconfigure(encoding='utf-8')
MiB = 1024**2
CAPS = {'zip': 20 * MiB, 'member': 20 * MiB, 'expanded': 80 * MiB, 'features': 100000, 'vertices': 1000000,
        'geojson': 20 * MiB, 'members': 64, 'ratio': 100}


def rounded6(value):
    if isinstance(value, float):
        return round(value, 6)
    if isinstance(value, (list, tuple)):
        return [rounded6(v) for v in value]
    return value


def shp_records(shp: bytes):
    out, cursor = [], 100
    while cursor < len(shp):
        words = struct.unpack_from('>i', shp, cursor + 4)[0]
        out.append((cursor + 8, words * 2))
        cursor += 8 + words * 2
    assert cursor == len(shp)
    return out


def subset(parts: dict, recs, header_len, record_len, idx):
    shp, shx, dbf = parts['.shp'], parts['.shx'], parts['.dbf']
    body, index, boxes = io.BytesIO(), io.BytesIO(), []
    offset_words = 50
    for n, i in enumerate(idx, 1):
        start, length = recs[i]
        content = shp[start:start + length]
        body.write(struct.pack('>ii', n, length // 2) + content)
        index.write(struct.pack('>ii', offset_words, length // 2))
        offset_words += 4 + length // 2
        if struct.unpack_from('<i', content, 0)[0] != 0:
            boxes.append(struct.unpack_from('<4d', content, 4))
    bbox = (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)) \
        if boxes else (0.0, 0.0, 0.0, 0.0)

    def header(src, total_bytes):
        h = bytearray(src[:100])
        struct.pack_into('>i', h, 24, total_bytes // 2)
        struct.pack_into('<4d', h, 36, *bbox)
        return bytes(h)
    new_shp = header(shp, 100 + body.tell()) + body.getvalue()
    new_shx = header(shx, 100 + index.tell()) + index.getvalue()
    h = bytearray(dbf[:header_len])
    struct.pack_into('<I', h, 4, len(idx))
    rows = b''.join(dbf[header_len + i * record_len:header_len + (i + 1) * record_len] for i in idx)
    new_dbf = bytes(h) + rows + b'\x1a'
    out = {'.shp': new_shp, '.shx': new_shx, '.dbf': new_dbf, '.prj': parts['.prj']}
    if '.cpg' in parts:
        out['.cpg'] = parts['.cpg']
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--backend', type=Path, required=True)
    ap.add_argument('--c12-dir', type=Path, required=True)
    ap.add_argument('--c9-dir', type=Path, required=True)
    ap.add_argument('--c9-compare', type=Path, required=True)
    ap.add_argument('--adm2', type=Path, required=True)
    ap.add_argument('--work', type=Path, required=True)
    ap.add_argument('--province', required=True)
    ap.add_argument('--zip', type=Path, required=True)
    ap.add_argument('--out-csv', type=Path, required=True)
    ap.add_argument('--out-json', type=Path, required=True)
    a = ap.parse_args()
    sys.path[:0] = [str(a.backend), str(a.c12_dir), str(a.c9_dir)]
    import shapely
    import fiona
    from fiona.io import ZipMemoryFile
    from fiona.model import to_dict
    from fiona.transform import transform_geom
    from shapely.geometry import mapping, shape
    from gis_worker import ldd_policy as policy
    from gis_worker import ldd_provider as ldd
    import c9_hdx_check as c9
    import c12_ocha_simplify as c12
    t0 = time.perf_counter()
    own_pcode = {r['province']: r['ocha_pcode'] for r in csv.DictReader(open(a.c9_compare, encoding='utf-8-sig'))}[a.province]
    chain, layer_name, blob, prj = c12.package_layer(a.zip, None, policy, c9)
    crs, err = c12.source_crs_of(prj, policy)
    if err:
        raise SystemExit(f'STOP: {err}')
    lz = zipfile.ZipFile(io.BytesIO(blob))
    parts = {PurePosixPath(n).suffix: lz.read(n) for n in lz.namelist()}
    stem = PurePosixPath(layer_name).stem
    # _record_count enforces MAX_FEATURES, so the source counts are read directly (outputs are checked below).
    count = struct.unpack_from('<I', parts['.dbf'], 4)[0]
    header_len, record_len = struct.unpack_from('<HH', parts['.dbf'], 8)
    recs = shp_records(parts['.shp'])
    assert len(recs) == count, (len(recs), count)
    enc = parts['.cpg'].decode('ascii').strip() if '.cpg' in parts else 'latin-1'
    enc = policy.cpg_alias(enc) or enc
    # districts in the package CRS
    adm2 = c9.read_layer(a.adm2)
    assert adm2['epsg'] == 4326
    d_props, d_geoms, d_invalid = [], [], 0
    for p, g in adm2['rows']:
        s = shape(transform_geom('EPSG:4326', crs, g))
        d_invalid += not s.is_valid
        d_props.append(p)
        d_geoms.append(s)
    tree = shapely.STRtree(d_geoms)
    t_adm = time.perf_counter() - t0
    points, verts, gbytes, kinds = [], [], [], Counter()
    with ZipMemoryFile(blob) as memory:
        with memory.open('layer.shp', enabled_drivers=['ESRI Shapefile'], encoding=enc) as src:
            keys = {k.upper(): k for k in src.schema['properties']}
            code_k, l1_k = keys.get('LU_CODE'), keys.get('LUL1_CODE')
            for i, f in enumerate(src):
                g = f['geometry']
                if g is None or g['type'] not in ('Polygon', 'MultiPolygon'):
                    points.append(None); verts.append(0); gbytes.append(0); kinds['no_polygon'] += 1
                    continue
                verts.append(ldd._coordinates(g['coordinates']))
                s = shape(g)
                points.append(None if s.is_empty else s.representative_point())
                geo = to_dict(transform_geom(crs, 'EPSG:4326', mapping(s)))
                geo = {'type': geo['type'], 'coordinates': rounded6(geo['coordinates'])}
                pr = f['properties']
                code = str(pr.get(code_k) or '').strip()
                main = str(pr.get(l1_k) or '').strip() if l1_k else ''
                feat = {'type': 'Feature', 'id': i,
                        'properties': {'LU_CODE': code, 'LUL1_CODE': main or code[:1], 'declared_area': None,
                                       'area_m2': s.area, 'classification': main or code[:1], 'repaired': False},
                        'geometry': geo}
                gbytes.append(len(json.dumps(feat, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')))
    assert len(points) == count
    t_read = time.perf_counter() - t0 - t_adm
    valid_idx = [i for i, p in enumerate(points) if p is not None]
    pi, di = tree.query(shapely.points([(points[i].x, points[i].y) for i in valid_idx]), predicate='intersects')
    hits = defaultdict(list)
    for k, d in zip(pi.tolist(), di.tolist()):
        hits[valid_idx[k]].append(d)
    groups, ties = defaultdict(list), 0
    for i in range(count):
        h = hits.get(i)
        if not h:
            groups['NONE'].append(i)
            continue
        if len(h) > 1:
            ties += 1
        d = min(h, key=lambda j: d_props[j]['adm2_pcode'])
        groups[d_props[d]['adm2_pcode']].append(i)
    by_pcode = {p['adm2_pcode']: p for p in d_props}
    out_dir = a.work / a.province.replace(' ', '_')
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    head, tail = len(b'{"features":['), len(b'],"type":"FeatureCollection"}')
    for pcode in sorted(groups):
        idx = groups[pcode]
        files = subset(parts, recs, header_len, record_len, idx)
        name = f'{stem}_{pcode}'
        zp = out_dir / f'{name}.zip'
        with zipfile.ZipFile(zp, 'w', zipfile.ZIP_DEFLATED) as z:
            for suf, data in files.items():
                z.writestr(name + suf, data)
        raw = zp.read_bytes()
        infos = zipfile.ZipFile(io.BytesIO(raw)).infolist()
        largest = max(infos, key=lambda x: x.file_size)
        expanded = sum(x.file_size for x in infos)
        ratio_max = max(x.file_size / x.compress_size for x in infos if x.file_size)
        try:
            ldd._record_count(files['.shp'], files['.shx'], files['.dbf'])
            rc = 'ok'
        except ldd.LddError as exc:
            rc = str(exc)
        try:
            ldd.guarded_zip(raw, package=True)
            gz = 'ok'
        except ldd.LddError as exc:
            gz = str(exc)
        v = sum(verts[i] for i in idx)
        gj = head + tail + sum(gbytes[i] for i in idx) + max(0, sum(1 for i in idx if gbytes[i]) - 1)
        dp = by_pcode.get(pcode, {})
        over = [k for k, bad in (('zip', len(raw) > CAPS['zip']), ('member', largest.file_size > CAPS['member']),
                                 ('expanded', expanded > CAPS['expanded']), ('features', len(idx) > CAPS['features']),
                                 ('vertices', v > CAPS['vertices']), ('geojson', gj > CAPS['geojson']),
                                 ('members', len(infos) > CAPS['members']), ('ratio', ratio_max > CAPS['ratio'])) if bad]
        rows.append({'province': a.province, 'district_pcode': pcode, 'district_th': dp.get('adm2_name1', ''),
                     'district_en': dp.get('adm2_name', ''), 'district_adm1_pcode': dp.get('adm1_pcode', ''),
                     'other_province': bool(dp) and dp.get('adm1_pcode') != own_pcode,
                     'parcels': len(idx), 'vertices': v, 'zip_bytes': len(raw), 'zip_mib': round(len(raw) / MiB, 2),
                     'largest_member': PurePosixPath(largest.filename).suffix, 'largest_member_bytes': largest.file_size,
                     'expanded_bytes': expanded, 'expanded_mib': round(expanded / MiB, 2), 'members': len(infos),
                     'max_member_ratio': round(ratio_max, 2), 'overall_ratio': round(expanded / len(raw), 2),
                     'geojson_bytes': gj, 'geojson_mib': round(gj / MiB, 2), 'record_count_check': rc,
                     'guarded_zip': gz, 'over_caps': ' '.join(over)})
    cols = list(rows[0])
    new = not a.out_csv.exists()
    with open(a.out_csv, 'a', encoding='utf-8', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        if new:
            w.writeheader()
        w.writerows(rows)
    real = [r for r in rows if r['district_pcode'] != 'NONE']
    summary = {'province': a.province, 'package': a.zip.name, 'layer': PurePosixPath(layer_name).name, 'crs': crs,
               'encoding': enc, 'parcels': count, 'vertices': sum(verts), 'no_polygon': kinds['no_polygon'],
               'districts': len(real), 'own_districts': sum(1 for r in real if not r['other_province']),
               'other_province_districts': [(r['district_pcode'], r['district_th'], r['parcels']) for r in real if r['other_province']],
               'parcels_in_no_district': len(groups.get('NONE', [])), 'point_on_shared_border_ties': ties,
               'adm2_invalid_in_package_crs': d_invalid,
               'districts_over_caps': sum(1 for r in real if r['over_caps']),
               'over_caps_by_kind': dict(Counter(k for r in real for k in r['over_caps'].split())),
               'largest_by_zip': max(real, key=lambda r: r['zip_bytes']) if real else None,
               'largest_by_parcels': max(real, key=lambda r: r['parcels'])['district_pcode'] if real else None,
               'record_count_not_ok': [r['district_pcode'] for r in rows if r['record_count_check'] != 'ok'],
               'guarded_zip_codes': dict(Counter(r['guarded_zip'] for r in rows)),
               'zip_total_bytes': sum(r['zip_bytes'] for r in rows), 'source_zip_bytes': a.zip.stat().st_size,
               'seconds': {'adm2': round(t_adm, 1), 'read': round(t_read, 1), 'total': round(time.perf_counter() - t0, 1)}}
    a.out_json.write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
