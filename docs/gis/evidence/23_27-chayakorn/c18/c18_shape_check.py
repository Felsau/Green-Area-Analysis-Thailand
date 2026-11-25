"""C18 step 1: overlap of system district shapes with OCHA tha_admin2 (same file as C15).

For each system district S and OCHA district O: overlap % = area(S ∩ O) / area(S), computed in UTM
(ldd_policy.metric_crs rule: 47N if lon < 102 else 48N; Nakhon Sawan and Ayutthaya are both 47N).
Invalid shapes are repaired with shapely.make_valid before measuring (counted in the output).
Writes c18-shape-check.json and c18-shape-check.csv; exit 2 if a district overlaps its same-English-name
OCHA district by less than 50 %.

usage: python -I -B c18_shape_check.py --districts <thailand_districts.json> --adm2 <tha_admin2.shp>
                                       --policy <ldd_policy.py> --out <dir>
"""
import argparse, csv, importlib.util, json, sys
from pathlib import Path

import fiona
import shapely
from fiona.transform import transform_geom
from shapely.geometry import mapping, shape

sys.stdout.reconfigure(encoding='utf-8')

SYSTEM = [('Nakhon Sawan', 'Takhli'), ('Nakhon Sawan', 'ThaTako'), ('Nakhon Sawan', 'LatYao'),
          ('Nakhon Sawan', 'PhayuhaKhiri'), ('Phra Nakhon Si Ayutthaya', 'BangSai')]
OCHA = {'Nakhon Sawan': ['TH6007', 'TH6008', 'TH6010', 'TH6011'],
        'Phra Nakhon Si Ayutthaya': ['TH1404', 'TH1413']}
SAME_NAME = {'Takhli': 'TH6007', 'ThaTako': 'TH6008', 'PhayuhaKhiri': 'TH6010', 'LatYao': 'TH6011'}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--districts', type=Path, required=True)
    ap.add_argument('--adm2', type=Path, required=True)
    ap.add_argument('--policy', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    a = ap.parse_args()
    spec = importlib.util.spec_from_file_location('ldd_policy', a.policy)
    policy = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(policy)

    feats = json.load(open(a.districts, encoding='utf-8'))['features']
    sysg = {}
    for f in feats:
        k = (f['properties']['province'], f['properties']['name'])
        if k in SYSTEM:
            assert k not in sysg, f'duplicate {k}'
            sysg[k] = (f['properties'], f['geometry'])
    assert set(sysg) == set(SYSTEM), set(SYSTEM) - set(sysg)

    want = {p for v in OCHA.values() for p in v}
    ocha = {}
    with fiona.open(a.adm2) as src:
        crs = src.crs.to_string()
        for f in src:
            p = dict(f['properties'])
            if p['adm2_pcode'] in want:
                ocha[p['adm2_pcode']] = ({k: p[k] for k in ('adm2_pcode', 'adm2_name', 'adm2_name1', 'adm1_name')}, f['geometry'])
    assert set(ocha) == want, want - set(ocha)

    repaired = []

    def to_m(geom, src_crs, utm, label):
        g = shape(transform_geom(src_crs, utm, mapping(shape(geom)) if not isinstance(geom, dict) else geom))
        if not g.is_valid:
            repaired.append(label)
            g = shapely.make_valid(g)
        return g

    rows, stop = [], []
    for prov, name in SYSTEM:
        props, geom = sysg[(prov, name)]
        utm = policy.metric_crs('EPSG:4326', shape(geom).centroid.x)
        S = to_m(geom, 'EPSG:4326', utm, f'system {name}')
        for pc in OCHA[prov]:
            op, og = ocha[pc]
            O = to_m(og, crs, utm, f'ocha {pc}')
            inter = S.intersection(O).area
            row = {'province': prov, 'system_name': name, 'system_name_th': props['name_th'], 'ocha_pcode': pc,
                   'ocha_name_en': op['adm2_name'], 'ocha_name_th': op['adm2_name1'], 'utm': utm,
                   'system_area_km2': round(S.area / 1e6, 3), 'ocha_area_km2': round(O.area / 1e6, 3),
                   'overlap_km2': round(inter / 1e6, 3), 'pct_of_system': round(100 * inter / S.area, 2),
                   'pct_of_ocha': round(100 * inter / O.area, 2), 'same_english_name': SAME_NAME.get(name) == pc}
            rows.append(row)
            if row['same_english_name'] and row['pct_of_system'] < 50:
                stop.append(row)
    a.out.mkdir(parents=True, exist_ok=True)
    with open(a.out / 'c18-shape-check.csv', 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    res = {'ocha_crs': crs, 'repaired_with_make_valid': repaired, 'rows': rows, 'below_50_same_name': stop}
    (a.out / 'c18-shape-check.json').write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding='utf-8')
    for r in rows:
        print(f"{r['system_name']:>13} ({r['system_name_th']}) vs {r['ocha_pcode']} {r['ocha_name_en']} ({r['ocha_name_th']}): "
              f"{r['pct_of_system']:6.2f}% of system · {r['pct_of_ocha']:6.2f}% of OCHA{'  <- same name' if r['same_english_name'] else ''}")
    print('repaired:', repaired or 'none', '· below 50% same name:', len(stop))
    return 2 if stop else 0


if __name__ == '__main__':
    sys.exit(main())
