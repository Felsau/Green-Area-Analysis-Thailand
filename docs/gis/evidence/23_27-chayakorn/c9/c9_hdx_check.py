"""C9 (week 4): check the OCHA cod-ab-tha boundaries from HDX against the system. Read-only on every input.

Sub-commands (run from anywhere with the C10 venv, python -I -B):

  names    ADM1/ADM2 of OCHA vs green-area-backend/data/thailand.json and thailand_districts.json, using the C5
           rules (make_norms/match imported from the C5 script taken with `git show C5:...`), default and --strict.
  angthong the boundary check of gis_worker/ldd_provider.py replayed on the Ang Thong package, importing the system's
           own functions (ldd_policy.metric_crs, boundary_tier, BOUNDARY_MINOR_M, BOUNDARY_REVIEW_M,
           DATASET_OUTSIDE_SHARE_MAX, DATASET_OUTSIDE_MIN_M2, REVIEW; ldd_provider._repair) - once with the system
           asset province_boundaries_ldd.json (must reproduce C3) and once with the OCHA ADM1 polygon of Ang Thong.
  compare  OCHA and GADM vs the LDD outline for the 41 LDD provinces of C7 (symmetric difference / LDD area and
           Hausdorff distance, in the province's UTM zone), and vertex counts of OCHA vs GADM for the other 36.

Nothing from HDX is written by this script except the CSV/JSON results named on the command line.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import io
import json
import sys
import time
import zipfile
from collections import Counter
from pathlib import Path, PurePosixPath

sys.stdout.reconfigure(encoding='utf-8')


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def read_layer(shp: Path):
    import fiona
    with fiona.open(shp) as src:
        crs = src.crs.to_string()
        epsg = src.crs.to_epsg(confidence_threshold=20)
        fields = list(src.schema['properties'])
        rows = [(dict(f['properties']), f['geometry']) for f in src]
    return {'crs': crs, 'epsg': epsg, 'fields': fields, 'rows': rows}


# ---------------------------------------------------------------- names
def cmd_names(a) -> int:
    c5 = load_module(a.c5_script, 'c5_name_map')
    backend = a.code / 'green-area-backend'
    sysprov = [f['properties'] for f in json.load(open(backend / 'data/thailand.json', encoding='utf-8'))['features']]
    sysdist = [f['properties'] for f in json.load(open(backend / 'data/thailand_districts.json', encoding='utf-8'))['features']]
    adm1 = read_layer(a.adm1)
    adm2 = read_layer(a.adm2)
    f1, f2 = a.adm1_fields.split(','), a.adm2_fields.split(',')   # pcode,th,en (+ parent pcode for adm2)
    out, stats = [], {}
    for strict in (False, True):
        rule = 'strict' if strict else 'default'
        norm_th, norm_en = c5.make_norms(strict)
        st = Counter()
        prov_map = {}
        used_sys = Counter()
        for p, _ in adm1['rows']:
            code, th, en = (p.get(k) or '' for k in f1)
            hit, how, why = c5.match(th, en, sysprov, lambda c: c.get('NL_NAME_1', ''), lambda c: c['name'], norm_th, norm_en)
            st[f'adm1_{how}'] += 1
            if hit:
                prov_map[code] = hit
                used_sys[hit['name']] += 1
            out.append({'rule': rule, 'level': 'ADM1', 'pcode': code, 'ocha_th': th, 'ocha_en': en,
                        'system_th': hit.get('NL_NAME_1', '') if hit else '', 'system_en': hit['name'] if hit else '',
                        'match_by': {'th': 'ไทย', 'en': 'อังกฤษ'}.get(how, 'ไม่ได้'), 'note': why})
        for s in sysprov:
            if s['name'] not in used_sys:
                st['adm1_system_only'] += 1
                out.append({'rule': rule, 'level': 'ADM1', 'pcode': '', 'ocha_th': '', 'ocha_en': '',
                            'system_th': s.get('NL_NAME_1', ''), 'system_en': s['name'], 'match_by': 'ไม่ได้',
                            'note': 'system_only'})
        dup_sys = [k for k, v in used_sys.items() if v > 1]
        if dup_sys:
            st['adm1_system_matched_twice'] = len(dup_sys)
        used_d = Counter()
        for p, _ in adm2['rows']:
            code, th, en, parent = (p.get(k) or '' for k in f2)
            prov = prov_map.get(parent)
            if prov is None:
                st['adm2_province_unmatched'] += 1
                out.append({'rule': rule, 'level': 'ADM2', 'pcode': code, 'ocha_th': th, 'ocha_en': en, 'system_th': '',
                            'system_en': '', 'match_by': 'ไม่ได้', 'note': f'province_unmatched ({parent})'})
                continue
            cands = [d for d in sysdist if d['province'] == prov['name']]
            hit, how, why = c5.match(th, en, cands, lambda c: c.get('name_th', ''), lambda c: c['name'], norm_th, norm_en)
            st[f'adm2_{how}'] += 1
            if hit:
                used_d[(hit['province'], hit['name'])] += 1
            out.append({'rule': rule, 'level': 'ADM2', 'pcode': code, 'ocha_th': th, 'ocha_en': en,
                        'system_th': hit.get('name_th', '') if hit else '', 'system_en': hit['name'] if hit else '',
                        'match_by': {'th': 'ไทย', 'en': 'อังกฤษ'}.get(how, 'ไม่ได้'),
                        'note': (why + ' · ' if why else '') + f'system province {prov["name"]}' if not hit else why})
        matched_provs = {v['name'] for v in prov_map.values()}
        for d in sysdist:
            if d['province'] in matched_provs and (d['province'], d['name']) not in used_d:
                st['adm2_system_only'] += 1
                out.append({'rule': rule, 'level': 'ADM2', 'pcode': '', 'ocha_th': '', 'ocha_en': '',
                            'system_th': d.get('name_th', ''), 'system_en': d['name'], 'match_by': 'ไม่ได้',
                            'note': f'system_only (province {d["province"]})'})
        st['adm2_system_matched_twice'] = sum(1 for v in used_d.values() if v > 1)
        stats[rule] = dict(st)
    stats['counts'] = {
        'adm1_rows': len(adm1['rows']), 'adm1_unique_pcode': len({p.get(f1[0]) for p, _ in adm1['rows']}),
        'adm2_rows': len(adm2['rows']), 'adm2_unique_pcode': len({p.get(f2[0]) for p, _ in adm2['rows']}),
        'system_provinces': len(sysprov), 'system_districts': len(sysdist),
        'adm1_crs': adm1['crs'], 'adm2_crs': adm2['crs'], 'adm1_fields': adm1['fields'], 'adm2_fields': adm2['fields']}
    cols = ['rule', 'level', 'pcode', 'ocha_th', 'ocha_en', 'system_th', 'system_en', 'match_by', 'note']
    with open(a.out, 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(out)
    a.stats.write_text(json.dumps(stats, ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps(stats, ensure_ascii=False, indent=1))
    return 0


# ---------------------------------------------------------------- Ang Thong
def member_name(info):
    if info.flag_bits & 0x800:
        return info.filename
    try:
        return info.filename.encode('cp437').decode('cp874')
    except UnicodeError:
        return info.filename


def land_use_layer(zip_path: Path, policy):
    """The land-use layer's components as a single-layer in-memory ZIP named layer.* (what ldd_provider opens)."""
    z = zipfile.ZipFile(zip_path)
    infos = [i for i in z.infolist() if not i.is_dir()]
    names = {member_name(i): i for i in infos}
    layer = policy.select_land_use_layer(list(names))
    if layer is None:
        raise SystemExit('no single land-use layer')
    stem = str(PurePosixPath(layer).with_suffix('')).casefold()
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_STORED) as dst:
        for n, i in names.items():
            p = PurePosixPath(n)
            if str(p.with_suffix('')).casefold() == stem and p.suffix.lower() in policy.LAYER_SUFFIXES:
                dst.writestr('layer' + p.suffix.lower(), z.read(i))
    return layer, out.getvalue()


def replay(layer_bytes: bytes, source_crs: str, boundary_geojson: dict, policy, repair_fn) -> dict:
    """ldd_provider.py lines 466-551 and 601-604, geometry part only, with the system's own functions."""
    from fiona.io import ZipMemoryFile
    from fiona.transform import transform_geom
    from shapely import prepare
    from shapely.geometry import shape
    zones = {}

    def zone(name_):
        if name_ not in zones:
            exact = shape(transform_geom('EPSG:4326', name_, boundary_geojson))
            assert not exact.is_empty and exact.is_valid
            minor, review = exact.buffer(policy.BOUNDARY_MINOR_M), exact.buffer(policy.BOUNDARY_REVIEW_M)
            for g in (exact, minor, review):
                prepare(g)
            zones[name_] = (exact, minor, review)
        return zones[name_]

    c = Counter()
    total = outside = 0.0
    with ZipMemoryFile(layer_bytes) as memory:
        with memory.open('layer.shp', enabled_drivers=['ESRI Shapefile']) as collection:
            for feature in collection:
                c['parcels'] += 1
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
                                c['repaired'] += 1
                                projected = fixed
                        if not issues:
                            area = projected.area
                        if not issues:
                            exact, minor, review = zone(metric)
                            if exact.covers(projected):
                                c['inside'] += 1
                            else:
                                within_minor = minor.covers(projected)
                                within_review = within_minor or review.covers(projected)
                                beyond = 0.0 if within_minor else projected.difference(minor).area / area
                                tier = policy.boundary_tier(False, within_minor, within_review, beyond)
                                outside += projected.difference(exact).area
                                c[tier] += 1
                for code in issues:
                    c['issue_' + code] += 1
                total += area
    flag = total > 0 and outside > total * policy.DATASET_OUTSIDE_SHARE_MAX and outside > policy.DATASET_OUTSIDE_MIN_M2
    return {'parcels': c['parcels'], 'inside': c['inside'],
            'outside_minor': c['BOUNDARY_OUTSIDE_MINOR'], 'review_required': c['BOUNDARY_OUTSIDE_REVIEW_REQUIRED'],
            'outside_province': c['OUTSIDE_PROVINCE'], 'repaired': c['repaired'],
            'other_issues': {k: v for k, v in c.items() if k.startswith('issue_')},
            'total_area_m2': round(total, 3), 'outside_area_m2': round(outside, 3),
            'outside_share_pct': round(100 * outside / total, 4) if total else None,
            'dataset_flag_BOUNDARY_OUTSIDE_AREA_REVIEW_REQUIRED': bool(flag)}


def vertex_count(geojson_geom) -> int:
    import shapely
    from shapely.geometry import shape
    return int(len(shapely.get_coordinates(shape(geojson_geom))))


def cmd_angthong(a) -> int:
    sys.path.insert(0, str(a.code / 'green-area-backend'))
    from gis_worker import ldd_policy as policy
    from gis_worker import ldd_provider
    from fiona.transform import transform_geom
    from shapely.geometry import mapping, shape
    from shapely.ops import unary_union
    res = {'package': {'name': a.zip.name, 'bytes': a.zip.stat().st_size, 'sha256': sha256_file(a.zip)}}
    if res['package']['sha256'].upper() != a.expect_sha.upper() or res['package']['bytes'] != a.expect_bytes:
        print(json.dumps(res, ensure_ascii=False)); print('STOP: package sha/size mismatch'); return 3
    asset = a.code / 'green-area-backend/gis_worker/province_boundaries_ldd.json'
    asset_sha = sha256_file(asset)
    res['system_asset'] = {'file': 'green-area-backend/gis_worker/province_boundaries_ldd.json', 'sha256': asset_sha,
                           'BOUNDARY_LDD_SHA256': ldd_provider.BOUNDARY_LDD_SHA256,
                           'match': asset_sha == ldd_provider.BOUNDARY_LDD_SHA256}
    if not res['system_asset']['match']:
        print(json.dumps(res, ensure_ascii=False)); print('STOP: asset sha mismatch'); return 3
    feat = next(f for f in json.load(open(asset, encoding='utf-8'))['features'] if f['properties']['name'] == 'Ang Thong')
    res['system_asset']['ang_thong_source'] = feat['properties'].get('source')
    layer_name, layer = land_use_layer(a.zip, policy)
    res['package']['land_use_layer'] = PurePosixPath(layer_name).name
    res['source_crs'] = a.source_crs
    res['policy'] = {'BOUNDARY_MINOR_M': policy.BOUNDARY_MINOR_M, 'BOUNDARY_REVIEW_M': policy.BOUNDARY_REVIEW_M,
                     'BOUNDARY_REVIEW_PART_MAX': policy.BOUNDARY_REVIEW_PART_MAX,
                     'DATASET_OUTSIDE_SHARE_MAX': policy.DATASET_OUTSIDE_SHARE_MAX,
                     'DATASET_OUTSIDE_MIN_M2': policy.DATASET_OUTSIDE_MIN_M2}
    t = time.perf_counter()
    res['round_system'] = replay(layer, a.source_crs, feat['geometry'], policy, ldd_provider._repair)
    res['round_system']['boundary_vertices'] = vertex_count(feat['geometry'])
    res['round_system']['seconds'] = round(time.perf_counter() - t, 1)
    # OCHA ADM1 of Ang Thong
    adm1 = read_layer(a.adm1)
    pf, = [p for p in (a.adm1_pcode_field,)]
    rows = [(p, g) for p, g in adm1['rows'] if p.get(pf) == a.ocha_pcode]
    if len(rows) != 1:
        print(f'STOP: {len(rows)} OCHA ADM1 rows with {pf}={a.ocha_pcode}'); return 3
    geom = rows[0][1]
    if adm1['epsg'] != 4326:
        geom = transform_geom(adm1['crs'], 'EPSG:4326', geom)
    ocha = shape(geom)
    if not ocha.is_valid:
        res['ocha_boundary_note'] = 'OCHA polygon not valid; repaired with ldd_provider._repair before use'
        ocha = ldd_provider._repair(ocha)
    ocha_json = mapping(ocha)
    res['ocha_boundary'] = {'pcode': a.ocha_pcode, 'source_crs': adm1['crs'], 'vertices': vertex_count(ocha_json)}
    t = time.perf_counter()
    res['round_ocha'] = replay(layer, a.source_crs, ocha_json, policy, ldd_provider._repair)
    res['round_ocha']['boundary_vertices'] = res['ocha_boundary']['vertices']
    res['round_ocha']['seconds'] = round(time.perf_counter() - t, 1)
    a.out.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps(res, ensure_ascii=False, indent=1))
    return 0


# ---------------------------------------------------------------- compare
def cmd_compare(a) -> int:
    from fiona.transform import transform_geom
    from shapely import hausdorff_distance, make_valid
    from shapely.geometry import shape
    import shapely
    t0 = time.perf_counter()
    ldd = {f['properties']['name']: f for f in json.load(open(a.ldd_asset, encoding='utf-8'))['features']}
    gadm = {f['properties']['name']: f for f in json.load(open(a.gadm_asset, encoding='utf-8'))['features']}
    names = json.load(open(a.name_map, encoding='utf-8'))      # {system_name: ocha_pcode}
    adm1 = read_layer(a.adm1)
    by_code = {p.get(a.adm1_pcode_field): g for p, g in adm1['rows']}
    rows = []
    for name, feat in ldd.items():
        code = names.get(name)
        og = by_code.get(code)
        if og is None:
            rows.append({'province': name, 'group': '', 'note': 'no OCHA polygon matched'}); continue
        if adm1['epsg'] != 4326:
            og = transform_geom(adm1['crs'], 'EPSG:4326', og)
        g_gadm = gadm[name]['geometry']
        cx = shape(g_gadm).centroid.x
        utm = 'EPSG:32647' if cx < 102 else 'EPSG:32648'
        to_m = lambda g: (lambda s: s if s.is_valid else make_valid(s))(shape(transform_geom('EPSG:4326', utm, g)))
        row = {'province': name, 'ocha_pcode': code, 'utm': utm, 'vertices_ocha': int(len(shapely.get_coordinates(shape(og)))),
               'vertices_gadm': int(len(shapely.get_coordinates(shape(g_gadm))))}
        if feat['properties'].get('source') == 'ldd-package':
            L = to_m(feat['geometry']); O = to_m(og); G = to_m(g_gadm)
            row.update(group='ldd-41', vertices_ldd=int(len(shapely.get_coordinates(L))),
                       ocha_vs_ldd_symdiff_pct=round(100 * O.symmetric_difference(L).area / L.area, 3),
                       ocha_vs_ldd_hausdorff_m=round(hausdorff_distance(O, L), 1),
                       gadm_vs_ldd_symdiff_pct=round(100 * G.symmetric_difference(L).area / L.area, 3),
                       gadm_vs_ldd_hausdorff_m=round(hausdorff_distance(G, L), 1))
        else:
            row.update(group='gadm-36')
        rows.append(row)
        if time.perf_counter() - t0 > a.max_seconds:
            print('STOP: over time budget'); break
    cols = ['province', 'group', 'ocha_pcode', 'utm', 'vertices_ldd', 'vertices_ocha', 'vertices_gadm',
            'ocha_vs_ldd_symdiff_pct', 'ocha_vs_ldd_hausdorff_m', 'gadm_vs_ldd_symdiff_pct', 'gadm_vs_ldd_hausdorff_m', 'note']
    with open(a.out, 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    print(f'rows {len(rows)} · {round(time.perf_counter() - t0, 1)} s')
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    n = sub.add_parser('names')
    n.add_argument('--code', type=Path, required=True)
    n.add_argument('--c5-script', type=Path, required=True)
    n.add_argument('--adm1', type=Path, required=True)
    n.add_argument('--adm2', type=Path, required=True)
    n.add_argument('--adm1-fields', required=True, help='pcode,th,en')
    n.add_argument('--adm2-fields', required=True, help='pcode,th,en,adm1_pcode')
    n.add_argument('--out', type=Path, required=True)
    n.add_argument('--stats', type=Path, required=True)
    g = sub.add_parser('angthong')
    g.add_argument('--code', type=Path, required=True)
    g.add_argument('--zip', type=Path, required=True)
    g.add_argument('--expect-sha', required=True)
    g.add_argument('--expect-bytes', type=int, required=True)
    g.add_argument('--source-crs', default='EPSG:32647')
    g.add_argument('--adm1', type=Path, required=True)
    g.add_argument('--adm1-pcode-field', required=True)
    g.add_argument('--ocha-pcode', required=True)
    g.add_argument('--out', type=Path, required=True)
    c = sub.add_parser('compare')
    c.add_argument('--ldd-asset', type=Path, required=True)
    c.add_argument('--gadm-asset', type=Path, required=True)
    c.add_argument('--adm1', type=Path, required=True)
    c.add_argument('--adm1-pcode-field', required=True)
    c.add_argument('--name-map', type=Path, required=True)
    c.add_argument('--out', type=Path, required=True)
    c.add_argument('--max-seconds', type=float, default=1200)
    a = ap.parse_args()
    return {'names': cmd_names, 'angthong': cmd_angthong, 'compare': cmd_compare}[a.cmd](a)


if __name__ == '__main__':
    raise SystemExit(main())
