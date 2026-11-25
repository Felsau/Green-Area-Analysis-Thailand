"""C12 (week 4): simplify the OCHA ADM1 outline of the 36 provinces the C7 asset still takes from GADM, then measure
what each outline does to the system's boundary check. Read-only on every input; writes only the paths given.

  simplify  for each of the 36 (source == gadm-approx in the C7 asset, OCHA polygon by the PCODE C9 paired):
            UTM by ldd_policy.metric_crs('EPSG:4326', GADM centroid lon) (the C9 section 5 rule), simplify(t,
            preserve_topology=True) for t in 10/25/50 m, back to EPSG:4326, rounded with build_ldd_boundaries.rounded
            (DECIMALS). Every outline is checked valid and non-empty after rounding and again after the EPSG:4326 ->
            UTM transform the validator's zone() does (both UTM zones). Nothing is repaired; failures are listed.
            Writes c12-compare.csv and four assets shaped like province_boundaries_ldd.json (raw/10/25/50).
  verify    for given provinces: reads the land-use layer of the package once and replays the boundary part of
            ldd_provider.assess (same code path as c9_hdx_check.replay, system functions) against several outlines
            in one pass. One JSON line per province.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import sys
import time
import zipfile
from collections import Counter
from pathlib import Path, PurePosixPath

sys.stdout.reconfigure(encoding='utf-8')
TOLERANCES = (10, 25, 50)
SOURCE_OCHA = 'ocha-cod-ab'


def setup(code: Path, c9_dir: Path):
    sys.path.insert(0, str(code / 'green-area-backend'))
    sys.path.insert(0, str(code / 'dev' / 'gis_local'))
    sys.path.insert(0, str(c9_dir))


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def vertex_count(g) -> int:
    import shapely
    return int(len(shapely.get_coordinates(g)))


# ---------------------------------------------------------------- simplify
def cmd_simplify(a) -> int:
    setup(a.code, a.c9_dir)
    import shapely
    from fiona.transform import transform_geom
    from shapely.geometry import shape
    from gis_worker import ldd_policy as policy
    import build_ldd_boundaries as builder
    import c9_hdx_check as c9
    raw_c7 = a.c7_asset.read_bytes()
    asset = json.loads(raw_c7)
    feats = asset['features']
    gadm36 = [f for f in feats if f['properties']['source'] == 'gadm-approx']
    pcode = {r['province']: r['ocha_pcode'] for r in csv.DictReader(open(a.c9_compare, encoding='utf-8-sig'))}
    adm1 = c9.read_layer(a.adm1)
    assert adm1['epsg'] == 4326, adm1['crs']
    by_code = {p.get('adm1_pcode'): g for p, g in adm1['rows']}
    other_zone = {'EPSG:32647': 'EPSG:32648', 'EPSG:32648': 'EPSG:32647'}

    def checks(gj, utm):
        g = shape(gj)
        u = shape(transform_geom('EPSG:4326', utm, gj))
        o = shape(transform_geom('EPSG:4326', other_zone[utm], gj))
        return {'valid_4326': bool(g.is_valid and not g.is_empty), 'valid_utm': bool(u.is_valid and not u.is_empty),
                'valid_other_utm': bool(o.is_valid and not o.is_empty), 'reason': '' if g.is_valid else shapely.is_valid_reason(g)}

    rows, variants, invalid = [], {v: {} for v in ('raw', *TOLERANCES)}, []
    for f in gadm36:
        name = f['properties']['name']
        code = pcode.get(name)
        og = by_code.get(code)
        if og is None:
            raise SystemExit(f'STOP: no OCHA polygon for {name} ({code})')
        gadm = shape(f['geometry'])
        utm = policy.metric_crs('EPSG:4326', gadm.centroid.x)
        src = shape(og)
        src_note = '' if src.is_valid else 'OCHA source polygon not valid: ' + shapely.is_valid_reason(src)
        to_m = lambda gj: shape(transform_geom('EPSG:4326', utm, gj))
        mv = lambda g: g if g.is_valid else shapely.make_valid(g)   # measurement only, never written
        ref_json = builder.rounded(src)                                 # OCHA raw, rounded like the builder
        ref_m = mv(to_m(ref_json))
        cand = {'gadm': f['geometry'], 'raw': ref_json}
        t_src = shape(transform_geom('EPSG:4326', utm, og))
        for t in TOLERANCES:
            simp = t_src.simplify(t, preserve_topology=True)
            back = shape(transform_geom(utm, 'EPSG:4326', shapely.geometry.mapping(simp)))
            cand[t] = builder.rounded(back)
        for kind, gj in cand.items():
            ck = checks(gj, utm)
            gm = mv(to_m(gj))
            row = {'province': name, 'ocha_pcode': code, 'utm': utm,
                   'variant': {'gadm': 'gadm (C7)', 'raw': 'ocha raw'}.get(kind, f'ocha {kind} m'),
                   'vertices': vertex_count(shape(gj)), 'parts': len(getattr(shape(gj), 'geoms', [0])),
                   'symdiff_vs_ocha_raw_pct': round(100 * gm.symmetric_difference(ref_m).area / ref_m.area, 4),
                   'area_km2': round(gm.area / 1e6, 3), **ck,
                   'note': src_note if kind != 'gadm' else ''}
            rows.append(row)
            if kind != 'gadm':
                variants[kind][name] = gj
                if not (ck['valid_4326'] and ck['valid_utm'] and ck['valid_other_utm']):
                    invalid.append({'province': name, 'variant': row['variant'], **ck})
        print(f'{name}: ' + ' · '.join(f"{r['variant']} {r['vertices']}" for r in rows[-5:]), flush=True)
    cols = ['province', 'ocha_pcode', 'utm', 'variant', 'vertices', 'parts', 'symdiff_vs_ocha_raw_pct', 'area_km2',
            'valid_4326', 'valid_utm', 'valid_other_utm', 'reason', 'note']
    with open(a.out_csv, 'w', encoding='utf-8', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    files = {'c7': {'bytes': len(raw_c7), 'sha256': sha256_bytes(raw_c7)}}
    for kind, geoms in variants.items():
        out = json.loads(raw_c7)
        for feat in out['features']:
            n = feat['properties']['name']
            if feat['properties']['source'] == 'gadm-approx':
                feat['properties'] = {'name': n, 'source': SOURCE_OCHA, 'adm1_pcode': pcode[n]}
                feat['geometry'] = geoms[n]
        md = out['metadata']
        md['generator'] = 'c12_ocha_simplify.py (C7 asset with the 36 gadm-approx outlines replaced)'
        md['sources'][SOURCE_OCHA] = ('OCHA cod-ab-tha ADM1 (HDX tha_admin_boundaries.shp.zip, CC BY-IGO); '
                                      + ('not simplified' if kind == 'raw' else f'simplified {kind} m in UTM, preserve_topology'))
        md['ocha_simplify_m'] = None if kind == 'raw' else kind
        data = json.dumps(out, ensure_ascii=True, separators=(',', ':'), sort_keys=True).encode('ascii')
        p = a.out_dir / f'province_boundaries_ocha_{kind}.json'
        p.write_bytes(data)
        files[str(kind)] = {'file': p.name, 'bytes': len(data), 'sha256': sha256_bytes(data),
                            'vs_c7_bytes': len(data) - len(raw_c7),
                            'ocha36_vertices': sum(vertex_count(shape(g)) for g in geoms.values())}
    summary = {'decimals': builder.DECIMALS, 'provinces': len(gadm36), 'files': files, 'invalid': invalid,
               'gadm36_vertices': sum(vertex_count(shape(f['geometry'])) for f in gadm36)}
    a.out_json.write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0


# ---------------------------------------------------------------- verify
def package_layer(zip_path: Path, inner: str | None, policy, c9):
    """(member chain, land-use layer name, single-layer in-memory ZIP, .prj bytes). Lop Buri: inner ZIP by name, as C10."""
    chain = [zip_path.name]
    src = zip_path
    if inner:
        z = zipfile.ZipFile(zip_path)
        hits = [i for i in z.infolist() if c9.member_name(i) == inner]
        if len(hits) != 1:
            raise SystemExit(f'STOP: inner zip {inner!r} not found once in {zip_path.name}')
        src = io.BytesIO(z.read(hits[0]))
        chain.append(inner)
    layer_name, blob = c9.land_use_layer(src, policy)
    prj = zipfile.ZipFile(io.BytesIO(blob)).read('layer.prj')
    return chain, layer_name, blob, prj


def source_crs_of(prj: bytes, policy):
    """The CRS string ldd_provider.assess accepts for this .prj (lines 436-448), else an error code."""
    from rasterio.crs import CRS
    try:
        text = prj.decode('utf-8-sig', errors='strict')
        crs = CRS.from_wkt(text)
    except Exception:
        return None, 'CRS_INVALID'
    horizontal = policy.horizontal_wkt(text) if crs.to_epsg() is None else None
    if horizontal is not None:
        try:
            crs = CRS.from_wkt(horizontal)
        except Exception:
            return None, 'CRS_INVALID'
    if crs.to_epsg() not in (32647, 32648, 4326):
        return None, 'CRS_MISMATCH'
    return crs.to_string(), None


def replay_many(layer_bytes: bytes, source_crs: str, outlines: dict, policy, repair_fn) -> dict:
    """c9_hdx_check.replay (ldd_provider.py lines 466-551, 601-604) with the parcel read and projected once and the
    zone tests run per outline. An outline whose zone is not valid stops that outline with VALIDATION_ASSET_INVALID,
    as assess would."""
    from fiona.io import ZipMemoryFile
    from fiona.transform import transform_geom
    from shapely import prepare
    from shapely.geometry import shape
    zones = {k: {} for k in outlines}
    stopped = {}
    res = {k: {'c': Counter(), 'outside': 0.0, 'secs': 0.0} for k in outlines}

    def zone(k, name_):
        z = zones[k]
        if name_ not in z:
            exact = shape(transform_geom('EPSG:4326', name_, outlines[k]))
            if exact.is_empty or not exact.is_valid:
                z[name_] = None
            else:
                minor, review = exact.buffer(policy.BOUNDARY_MINOR_M), exact.buffer(policy.BOUNDARY_REVIEW_M)
                for g in (exact, minor, review):
                    prepare(g)
                z[name_] = (exact, minor, review)
        return z[name_]

    shared = Counter()
    total = 0.0
    t_read = time.perf_counter()
    check_secs = 0.0
    with ZipMemoryFile(layer_bytes) as memory:
        with memory.open('layer.shp', enabled_drivers=['ESRI Shapefile']) as collection:
            for feature in collection:
                shared['parcels'] += 1
                geom_json = feature['geometry']
                issues, area = [], 0.0
                if geom_json is None or geom_json['type'] not in ('Polygon', 'MultiPolygon'):
                    issues.append('GEOMETRY_TYPE')
                else:
                    geom = shape(geom_json)
                    if geom.is_empty:
                        issues.append('GEOMETRY_EMPTY')
                    else:
                        minx, _, maxx, _ = geom.bounds
                        metric = policy.metric_crs(source_crs, (minx + maxx) / 2)
                        projected = geom if metric == source_crs else shape(transform_geom(source_crs, metric, geom_json))
                        if not geom.is_valid or not projected.is_valid:
                            fixed = repair_fn(projected)
                            code = policy.repair_accepted(projected.area, fixed.area, fixed.geom_type,
                                                          fixed.is_valid, fixed.is_empty)
                            if code:
                                issues.append(code)
                            else:
                                shared['repaired'] += 1
                                projected = fixed
                        if not issues:
                            area = projected.area
                        if not issues:
                            for k in outlines:
                                if k in stopped:
                                    continue
                                t = time.perf_counter()
                                zz = zone(k, metric)
                                if zz is None:
                                    stopped[k] = f'VALIDATION_ASSET_INVALID ({metric})'
                                    continue
                                exact, minor, review = zz
                                r = res[k]
                                if exact.covers(projected):
                                    r['c']['inside'] += 1
                                else:
                                    within_minor = minor.covers(projected)
                                    within_review = within_minor or review.covers(projected)
                                    beyond = 0.0 if within_minor else projected.difference(minor).area / area
                                    tier = policy.boundary_tier(False, within_minor, within_review, beyond)
                                    r['outside'] += projected.difference(exact).area
                                    r['c'][tier] += 1
                                dt = time.perf_counter() - t
                                r['secs'] += dt
                                check_secs += dt
                for code in issues:
                    shared['issue_' + code] += 1
                total += area
    read_secs = time.perf_counter() - t_read - check_secs
    out = {}
    for k, r in res.items():
        c, outside = r['c'], r['outside']
        flag = total > 0 and outside > total * policy.DATASET_OUTSIDE_SHARE_MAX and outside > policy.DATASET_OUTSIDE_MIN_M2
        out[k] = {'parcels': shared['parcels'], 'inside': c['inside'], 'outside_minor': c['BOUNDARY_OUTSIDE_MINOR'],
                  'review_required': c['BOUNDARY_OUTSIDE_REVIEW_REQUIRED'], 'outside_province': c['OUTSIDE_PROVINCE'],
                  'repaired': shared['repaired'],
                  'other_issues': {kk: v for kk, v in shared.items() if kk.startswith('issue_')},
                  'total_area_m2': round(total, 3), 'outside_area_m2': round(outside, 3),
                  'outside_share_pct': round(100 * outside / total, 4) if total else None,
                  'flag_BOUNDARY_OUTSIDE_AREA_REVIEW_REQUIRED': bool(flag) if k not in stopped else None,
                  'stopped': stopped.get(k, ''), 'check_seconds': round(r['secs'], 2),
                  'shared_read_seconds': round(read_secs, 2),
                  'seconds': round(read_secs + r['secs'], 2)}
    return out


def find_zip(ldd77: Path, th: str) -> Path:
    hits = [p for p in ldd77.iterdir() if re.match(r'(?:Landuse_)?' + re.escape(th) + r'(?![฀-๿])', p.name)]
    if len(hits) != 1:
        raise SystemExit(f'STOP: {len(hits)} packages for {th}: {[h.name for h in hits]}')
    return hits[0]


def cmd_verify(a) -> int:
    setup(a.code, a.c9_dir)
    from gis_worker import ldd_policy as policy
    from gis_worker import ldd_provider
    import c9_hdx_check as c9
    th_of = {r['province_en']: r['province_th'] for r in csv.DictReader(open(a.c10_csv, encoding='utf-8-sig'))}
    rounds = {}
    for spec in a.round:
        label, path = spec.split('=', 1)
        rounds[label] = {f['properties']['name']: f for f in json.load(open(path, encoding='utf-8'))['features']}
    for name in a.province:
        t0 = time.perf_counter()
        zp = find_zip(a.ldd77, th_of[name])
        inner = a.inner if name == 'Lop Buri' else None
        chain, layer_name, blob, prj = package_layer(zp, inner, policy, c9)
        crs, err = source_crs_of(prj, policy)
        rec = {'province': name, 'package': ' > '.join(chain), 'layer': PurePosixPath(layer_name).name,
               'source_crs': crs, 'crs_error': err}
        if err is None:
            outlines, srcs = {}, {}
            for label, feats in rounds.items():
                f = feats[name]
                outlines[label] = f['geometry']
                srcs[label] = f['properties']['source']
            res = replay_many(blob, crs, outlines, policy, ldd_provider._repair)
            for label in res:
                res[label]['boundary_source'] = srcs[label]
            rec['rounds'] = res
        rec['wall_seconds'] = round(time.perf_counter() - t0, 1)
        print(json.dumps(rec, ensure_ascii=False), flush=True)
    return 0


def cmd_collect(a) -> int:
    recs = []
    for p in a.jsonl:
        for line in Path(p).read_text(encoding='utf-8').splitlines():
            if line.startswith('{'):
                recs.append(json.loads(line))
    recs.sort(key=lambda r: r['province'])
    simp = json.loads(a.simplify_json.read_text(encoding='utf-8'))
    size = {'gadm': simp['files']['c7'], 'ocha_raw': simp['files']['raw'], 'ocha_25': simp['files']['25'],
            'ocha_50': simp['files']['50']}
    rows, summ = [], {}
    for r in recs:
        if r.get('crs_error'):
            rows.append({'province': r['province'], 'round': '', 'note': r['crs_error']})
            continue
        for label, x in r['rounds'].items():
            rows.append({'province': r['province'], 'round': label, 'boundary_source': x['boundary_source'],
                         'package': r['package'], 'source_crs': r['source_crs'], 'parcels': x['parcels'],
                         'inside': x['inside'], 'outside_minor': x['outside_minor'],
                         'review_required': x['review_required'], 'outside_province': x['outside_province'],
                         'repaired': x['repaired'], 'other_issues': json.dumps(x['other_issues']) if x['other_issues'] else '',
                         'outside_area_m2': x['outside_area_m2'], 'outside_share_pct': x['outside_share_pct'],
                         'flag_BOUNDARY_OUTSIDE_AREA_REVIEW_REQUIRED': x['flag_BOUNDARY_OUTSIDE_AREA_REVIEW_REQUIRED'],
                         'stopped': x['stopped'], 'seconds': x['seconds'], 'check_seconds': x['check_seconds'],
                         'shared_read_seconds': x['shared_read_seconds'], 'note': ''})
            s = summ.setdefault(label, Counter())
            s['provinces'] += 1
            s['not_flagged'] += x['flag_BOUNDARY_OUTSIDE_AREA_REVIEW_REQUIRED'] is False
            s['not_flagged_and_outside_province_0'] += (x['flag_BOUNDARY_OUTSIDE_AREA_REVIEW_REQUIRED'] is False
                                                       and x['outside_province'] == 0)
            s['outside_province_0'] += x['outside_province'] == 0
            s['outside_province_total'] += x['outside_province']
            s['review_required_total'] += x['review_required']
            s['outside_minor_total'] += x['outside_minor']
            s['parcels_total'] += x['parcels']
            s['stopped'] += bool(x['stopped'])
            s['seconds_total'] = round(s['seconds_total'] + x['seconds'], 1)
    cols = ['province', 'round', 'boundary_source', 'package', 'source_crs', 'parcels', 'inside', 'outside_minor',
            'review_required', 'outside_province', 'repaired', 'other_issues', 'outside_area_m2', 'outside_share_pct',
            'flag_BOUNDARY_OUTSIDE_AREA_REVIEW_REQUIRED', 'stopped', 'seconds', 'check_seconds', 'shared_read_seconds', 'note']
    with open(a.out_csv, 'w', encoding='utf-8', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    out = {k: {**dict(v), 'asset_bytes': size[k]['bytes'], 'asset_sha256': size[k]['sha256']} for k, v in summ.items()}
    a.out_json.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    c = sub.add_parser('collect')
    c.add_argument('--jsonl', action='append', required=True)
    c.add_argument('--simplify-json', type=Path, required=True)
    c.add_argument('--out-csv', type=Path, required=True)
    c.add_argument('--out-json', type=Path, required=True)
    s = sub.add_parser('simplify')
    s.add_argument('--code', type=Path, required=True)
    s.add_argument('--c9-dir', type=Path, required=True)
    s.add_argument('--c7-asset', type=Path, required=True)
    s.add_argument('--c9-compare', type=Path, required=True)
    s.add_argument('--adm1', type=Path, required=True)
    s.add_argument('--out-csv', type=Path, required=True)
    s.add_argument('--out-json', type=Path, required=True)
    s.add_argument('--out-dir', type=Path, required=True)
    v = sub.add_parser('verify')
    v.add_argument('--code', type=Path, required=True)
    v.add_argument('--c9-dir', type=Path, required=True)
    v.add_argument('--ldd77', type=Path, required=True)
    v.add_argument('--c10-csv', type=Path, required=True)
    v.add_argument('--inner', default='Landuse_ลพบุรี_2566(ปีล่าสุด).zip')
    v.add_argument('--round', action='append', required=True, help='label=asset.json')
    v.add_argument('--province', action='append', required=True)
    a = ap.parse_args()
    return {'simplify': cmd_simplify, 'verify': cmd_verify, 'collect': cmd_collect}[a.cmd](a)


if __name__ == '__main__':
    raise SystemExit(main())
