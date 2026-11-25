"""C15 (week 4): district outlines of the 41 LDD packages that carry an amphoe layer, compared with OCHA tha_admin2
and with the system's GADM districts (green-area-backend/data/thailand_districts.json). Read-only on every input.

Pairing, never guessed:
  * LDD district -> system district: the C5 result (c5-name-map.csv from tag C5, rows matched by th or en).
  * system district -> OCHA district: the C9 rule (C5 make_norms(False)/match, OCHA adm2_name1/adm2_name against
    system name_th/name inside the paired province). One system row pairs with one OCHA row; on a collision the
    pair whose Thai name matches is kept. Bangkok's province is paired by PCODE TH10 (the rule cannot pair it);
    its rows carry group=bangkok so they are reported apart.
  * rows that cannot be paired are written with a note and no measurement.
Measurement as C9 section 5: in the UTM zone of the province (47N if the GADM province centroid < 102 E, else 48N),
make_valid only when a shape is not valid (measurement only); symmetric difference / LDD area and Hausdorff (m).
LDD district = union of the amphoe-layer rows with the same AMPHOE_IDN and AMPHOE_T (C5 grouping).
Vertex counts: shapely.get_coordinates of each source (LDD: sum over its rows).
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import io
import json
import statistics
import sys
import time
import zipfile
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath

sys.stdout.reconfigure(encoding='utf-8')


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--backend', type=Path, required=True)
    ap.add_argument('--c5-script', type=Path, required=True)
    ap.add_argument('--c5-map', type=Path, required=True)
    ap.add_argument('--c5-provinces', type=Path, required=True)
    ap.add_argument('--c4-inventory', type=Path, required=True)
    ap.add_argument('--c9-dir', type=Path, required=True)
    ap.add_argument('--ldd77', type=Path, required=True)
    ap.add_argument('--adm1', type=Path, required=True)
    ap.add_argument('--adm2', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--stats', type=Path, required=True)
    a = ap.parse_args()
    sys.path[:0] = [str(a.backend), str(a.c9_dir)]
    import shapely
    from fiona.io import ZipMemoryFile
    from fiona.transform import transform_geom
    from shapely import hausdorff_distance, make_valid
    from shapely.geometry import mapping, shape
    from shapely.ops import unary_union
    from gis_worker import ldd_policy as policy
    import c9_hdx_check as c9
    c5 = load_module(a.c5_script, 'c5_name_map')
    norm_th, norm_en = c5.make_norms(False)
    t0 = time.perf_counter()
    provs = [f['properties'] for f in json.load(open(a.backend / 'data/thailand.json', encoding='utf-8'))['features']]
    gadm_prov = {f['properties']['name']: f['geometry'] for f in json.load(open(a.backend / 'data/thailand.json', encoding='utf-8'))['features']}
    dfeat = json.load(open(a.backend / 'data/thailand_districts.json', encoding='utf-8'))['features']
    dists = [f['properties'] for f in dfeat]
    dgeom = {(f['properties']['province'], f['properties']['name']): f['geometry'] for f in dfeat}
    adm1 = [p for p, _ in c9.read_layer(a.adm1)['rows']]
    adm2_rows = c9.read_layer(a.adm2)['rows']
    ogeom = {p['adm2_pcode']: g for p, g in adm2_rows}
    adm2 = [p for p, _ in adm2_rows]
    # system province <- OCHA ADM1 (C9 rule; Bangkok by PCODE TH10)
    pmap = {}
    for o in adm1:
        hit, how, _ = c5.match(o['adm1_name1'], o['adm1_name'], provs, lambda c: c.get('NL_NAME_1', ''), lambda c: c['name'], norm_th, norm_en)
        if hit is None and o['adm1_pcode'] == 'TH10':
            hit, how = next(p for p in provs if p['name'] == 'Bangkok Metropolis'), 'pcode'
        if hit is not None:
            pmap[o['adm1_pcode']] = (hit['name'], how)
    # system district -> OCHA district (C9 rule, collision: keep the Thai pair)
    hits = defaultdict(list)
    for o in adm2:
        pr = pmap.get(o['adm1_pcode'])
        if pr is None:
            continue
        cands = [d for d in dists if d['province'] == pr[0]]
        hit, how, why = c5.match(o['adm2_name1'], o['adm2_name'], cands, lambda c: c.get('name_th', ''), lambda c: c['name'], norm_th, norm_en)
        if hit is not None:
            hits[(hit['province'], hit['name'])].append((o, how))
    sys2ocha = {}
    for key, pairs in hits.items():
        if len(pairs) > 1:
            th = [x for x in pairs if x[1] == 'th']
            if len(th) != 1:
                continue
            pairs = th
        sys2ocha[key] = pairs[0]
    # LDD -> system (C5)
    c5rows = list(csv.DictReader(open(a.c5_map, encoding='utf-8-sig')))
    inv = {r['province_th']: r for r in csv.DictReader(open(a.c4_inventory, encoding='utf-8-sig'))}
    pv = {r['province_th']: r['system_province'] for r in csv.DictReader(open(a.c5_provinces, encoding='utf-8-sig'))}
    amp_provinces = sorted(p for p, r in inv.items() if r['has_amp'] == 'yes')
    out, st = [], Counter()
    for pth in amp_provinces:
        sysprov = pv.get(pth, '')
        src, _ = c5.open_package(a.ldd77, inv[pth]['zip_name'], policy)
        z = zipfile.ZipFile(src)
        files = [(c5.member_name(i), i) for i in z.infolist() if not i.is_dir()]
        layer = policy.select_land_use_layer([n for n, _ in files])
        amp = []
        for n, i in files:
            if not n.lower().endswith('.shp') or n == layer:
                continue
            dbf = next((j for m, j in files if m.casefold() == (n[:-4] + '.dbf').casefold()), None)
            if dbf is not None and c5.layer_kind([x[0] for x in c5.dbf_fields(z.read(dbf))[3]]) == 'amp':
                amp.append(n)
        assert amp, pth
        if len(amp) > 1:   # C5 read_layers uses layers['amp'][0], the first in member order
            st['provinces_with_several_amp_layers'] += 1
            st.setdefault('several_amp_layers', [])
            print(f'{pth}: {len(amp)} amphoe layers, used the first (as C5): {PurePosixPath(amp[0]).name}; '
                  f'skipped {[PurePosixPath(x).name for x in amp[1:]]}', flush=True)
        stem = str(PurePosixPath(amp[0]).with_suffix('')).casefold()
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w') as zz:
            for n, i in files:
                p = PurePosixPath(n)
                if str(p.with_suffix('')).casefold() == stem and p.suffix.lower() in policy.LAYER_SUFFIXES:
                    zz.writestr('amp' + p.suffix.lower(), z.read(i))
        # keys read exactly as C5 read them (c5.dbf_records with the C5 codec choice), geometry by record order
        codec, _ = c5.codec_for(z, files, amp[0], policy)
        raw_dbf = z.read(next(j for m, j in files if m.casefold() == (amp[0][:-4] + '.dbf').casefold()))
        recs = None
        for cdc in ([codec] if codec else ['utf-8', 'cp874']):
            try:
                widths, recs = c5.dbf_records(raw_dbf, cdc)
                break
            except UnicodeDecodeError:
                continue
        fi, ft = c5.pick(widths, 'AMPHOE_IDN'), c5.pick(widths, 'AMPHOE_T')
        groups, verts = defaultdict(list), Counter()
        with ZipMemoryFile(buf.getvalue()) as mem:
            with mem.open('amp.shp', encoding='latin-1') as col:
                lcrs = col.crs.to_string()
                geoms = [f['geometry'] for f in col]
        assert len(geoms) == len(recs), (pth, len(geoms), len(recs))
        for rec, gj in zip(recs, geoms):
            if gj is None:
                continue
            k = (rec.get(fi, '') if fi else '', rec.get(ft, '') if ft else '')
            groups[k].append(shape(gj))
            verts[k] += int(len(shapely.get_coordinates(shape(gj))))
        cx = shape(gadm_prov[sysprov]).centroid.x if sysprov else 100.0
        utm = policy.metric_crs('EPSG:4326', cx)
        mv = lambda g: g if g.is_valid else make_valid(g)
        to_m = lambda g, crs: mv(shape(transform_geom(crs, utm, mapping(g) if not isinstance(g, dict) else g)))
        for r in [x for x in c5rows if x['province_th'] == pth and x['ldd_amphoe_t']]:
            row = {'province_th': pth, 'system_province': sysprov, 'group': 'bangkok' if sysprov == 'Bangkok Metropolis' else 'other',
                   'ldd_amphoe_idn': r['ldd_amphoe_idn'], 'ldd_amphoe_t': r['ldd_amphoe_t'], 'c5_match_by': r['match_by'],
                   'system_district': '', 'ocha_pcode': '', 'ocha_match_by': '', 'utm': utm, 'ldd_crs': lcrs, 'note': ''}
            st['ldd_districts'] += 1
            if r['match_by'] not in ('th', 'en'):
                row['note'] = 'C5 ไม่ได้จับคู่ (' + r['note'][:80] + ')'
                st['skip_c5_unmatched'] += 1
                out.append(row)
                continue
            sname = r['system_district'].rsplit(' (', 1)[0]
            row['system_district'] = sname
            k = (r['ldd_amphoe_idn'], r['ldd_amphoe_t'])
            if k not in groups:
                row['note'] = 'ไม่พบรูปในชั้นอำเภอ'
                st['skip_no_geometry'] += 1
                out.append(row)
                continue
            pair = sys2ocha.get((sysprov, sname))
            L = mv(unary_union([to_m(g, lcrs) for g in groups[k]]))
            G = to_m(dgeom[(sysprov, sname)], 'EPSG:4326')
            row.update(vertices_ldd=verts[k], vertices_gadm=int(len(shapely.get_coordinates(shape(dgeom[(sysprov, sname)])))),
                       gadm_vs_ldd_symdiff_pct=round(100 * G.symmetric_difference(L).area / L.area, 3),
                       gadm_vs_ldd_hausdorff_m=round(hausdorff_distance(G, L), 1), ldd_area_km2=round(L.area / 1e6, 3))
            if pair is None:
                row['note'] = 'ระบบจับคู่กับ OCHA ไม่ได้ตามกฎ C9'
                st['skip_ocha_unmatched'] += 1
            else:
                o, how = pair
                O = to_m(ogeom[o['adm2_pcode']], 'EPSG:4326')
                row.update(ocha_pcode=o['adm2_pcode'], ocha_match_by=how,
                           vertices_ocha=int(len(shapely.get_coordinates(shape(ogeom[o['adm2_pcode']])))),
                           ocha_vs_ldd_symdiff_pct=round(100 * O.symmetric_difference(L).area / L.area, 3),
                           ocha_vs_ldd_hausdorff_m=round(hausdorff_distance(O, L), 1))
                st['measured'] += 1
            out.append(row)
        print(f'{pth}: {sum(1 for x in out if x["province_th"] == pth)} rows · {round(time.perf_counter() - t0)} s', flush=True)
    cols = ['province_th', 'system_province', 'group', 'ldd_amphoe_idn', 'ldd_amphoe_t', 'c5_match_by', 'system_district',
            'ocha_pcode', 'ocha_match_by', 'utm', 'ldd_crs', 'ldd_area_km2', 'vertices_ldd', 'vertices_ocha', 'vertices_gadm',
            'ocha_vs_ldd_symdiff_pct', 'ocha_vs_ldd_hausdorff_m', 'gadm_vs_ldd_symdiff_pct', 'gadm_vs_ldd_hausdorff_m', 'note']
    with open(a.out, 'w', encoding='utf-8-sig', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(out)
    res = {'counts': dict(st), 'provinces': len(amp_provinces), 'seconds': round(time.perf_counter() - t0, 1)}
    for grp in ('other', 'bangkok', 'all'):
        m = [x for x in out if 'ocha_vs_ldd_symdiff_pct' in x and (grp == 'all' or x['group'] == grp)]
        if not m:
            continue
        g = {}
        for key in ('ocha_vs_ldd_symdiff_pct', 'gadm_vs_ldd_symdiff_pct', 'ocha_vs_ldd_hausdorff_m', 'gadm_vs_ldd_hausdorff_m'):
            vals = [x[key] for x in m]
            mx = max(m, key=lambda x: x[key])
            g[key] = {'median': round(statistics.median(vals), 3), 'max': mx[key],
                      'max_at': f"{mx['system_province']} / {mx['system_district']}"}
        g['districts'] = len(m)
        g['ocha_closer_by_area'] = sum(1 for x in m if x['ocha_vs_ldd_symdiff_pct'] < x['gadm_vs_ldd_symdiff_pct'])
        g['ocha_closer_by_hausdorff'] = sum(1 for x in m if x['ocha_vs_ldd_hausdorff_m'] < x['gadm_vs_ldd_hausdorff_m'])
        g['vertices'] = {s: sum(x['vertices_' + s] for x in m) for s in ('ldd', 'ocha', 'gadm')}
        res[grp] = g
    a.stats.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps(res, ensure_ascii=False, indent=1))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
