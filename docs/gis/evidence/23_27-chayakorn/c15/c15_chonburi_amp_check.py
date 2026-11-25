"""C15 follow-up (read-only): is Bang Lamung incomplete in the Chon Buri _Amp layer? Compares _Amp and _Amp_D
of the Chon Buri package (read with the C5 functions) with the OCHA and GADM outlines of Bang Lamung, and draws
both layers. Usage: python -I -B c15_chonburi_amp_check.py <backend> <c5_name_map.py> <ldd-77> <tha_admin2.shp> <out.png> <out.json>
"""
import importlib.util
import io
import json
import sys
import zipfile
from collections import defaultdict
from pathlib import Path, PurePosixPath

sys.stdout.reconfigure(encoding='utf-8')
backend, c5p, ldd77, adm2p, out_png, out_json = map(Path, sys.argv[1:7])
sys.path.insert(0, str(backend))
from gis_worker import ldd_policy as policy  # noqa: E402
spec = importlib.util.spec_from_file_location('c5', c5p); c5 = importlib.util.module_from_spec(spec); spec.loader.exec_module(c5)
import fiona  # noqa: E402
from fiona.io import ZipMemoryFile  # noqa: E402
from fiona.transform import transform_geom  # noqa: E402
from shapely.geometry import mapping, shape  # noqa: E402
from shapely.ops import unary_union  # noqa: E402

zp = next(p for p in ldd77.iterdir() if p.name.startswith('ชลบุรี'))
z = zipfile.ZipFile(zp)
files = [(c5.member_name(i), i) for i in z.infolist() if not i.is_dir()]
layer = policy.select_land_use_layer([n for n, _ in files])
res = {'package': zp.name, 'layers': {}}
shapes = {}
for n, i in files:
    if not n.lower().endswith('.shp') or n == layer:
        continue
    dbf = next((j for m, j in files if m.casefold() == (n[:-4] + '.dbf').casefold()), None)
    if dbf is None or c5.layer_kind([x[0] for x in c5.dbf_fields(z.read(dbf))[3]]) != 'amp':
        continue
    codec, _ = c5.codec_for(z, files, n, policy)
    widths, recs = c5.dbf_records(z.read(dbf), codec or 'utf-8')
    fi, ft = c5.pick(widths, 'AMPHOE_IDN'), c5.pick(widths, 'AMPHOE_T')
    stem = str(PurePosixPath(n).with_suffix('')).casefold()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zz:
        for m, j in files:
            p = PurePosixPath(m)
            if str(p.with_suffix('')).casefold() == stem and p.suffix.lower() in policy.LAYER_SUFFIXES:
                zz.writestr('a' + p.suffix.lower(), z.read(j))
    with ZipMemoryFile(buf.getvalue()) as mem, mem.open('a.shp', encoding='latin-1') as col:
        crs = col.crs.to_string()
        geoms = [f['geometry'] for f in col]
    groups = defaultdict(list)
    for r, g in zip(recs, geoms):
        if g is not None:
            groups[(r.get(fi, ''), r.get(ft, ''))].append(shape(g))
    name = PurePosixPath(n).name
    shapes[name] = {k: unary_union(v) for k, v in groups.items()}
    total = unary_union(list(shapes[name].values()))
    res['layers'][name] = {'crs': crs, 'records': len(recs), 'districts': len(groups),
                           'fields': list(widths)[:12], 'total_area_km2': round(total.area / 1e6, 1),
                           'districts_km2': {f'{k[0]} {k[1]}': round(v.area / 1e6, 1) for k, v in sorted(shapes[name].items())}}
adm2 = fiona.open(adm2p)
ocha = next(f for f in adm2 if f['properties']['adm2_pcode'] == 'TH2004')   # Bang Lamung
o = shape(transform_geom('EPSG:4326', crs, ocha['geometry']))
gadm = next(f for f in json.load(open(backend / 'data/thailand_districts.json', encoding='utf-8'))['features']
            if f['properties']['province'] == 'Chon Buri' and f['properties']['name'] == 'BangLamung')
g = shape(transform_geom('EPSG:4326', crs, gadm['geometry']))
res['bang_lamung'] = {'ocha_TH2004_km2': round(o.area / 1e6, 1), 'ocha_name': ocha['properties']['adm2_name1'],
                      'gadm_km2': round(g.area / 1e6, 1)}
for name, d in shapes.items():
    bl = [v for k, v in d.items() if 'บางละมุง' in k[1]]
    if bl:
        u = unary_union(bl)
        res['bang_lamung'][name] = {'area_km2': round(u.area / 1e6, 1), 'share_of_ocha_pct': round(100 * u.intersection(o).area / o.area, 1),
                                    'parts': len(getattr(u, 'geoms', [u]))}
import matplotlib  # noqa: E402
matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402
fig, axes = plt.subplots(1, len(shapes), figsize=(7 * len(shapes), 7))
for ax, (name, d) in zip(axes if len(shapes) > 1 else [axes], shapes.items()):
    for k, v in d.items():
        for p in getattr(v, 'geoms', [v]):
            x, y = p.exterior.xy
            ax.fill(x, y, alpha=0.6 if 'บางละมุง' in k[1] else 0.25, color='tab:red' if 'บางละมุง' in k[1] else 'tab:green')
    for p in getattr(o, 'geoms', [o]):
        x, y = p.exterior.xy
        ax.plot(x, y, color='black', linewidth=1)
    ax.set_title(f'{name.encode("ascii", "replace").decode()}  ({res["layers"][name]["districts"]} districts)\nred = Bang Lamung rows, black = OCHA TH2004', fontsize=9)
    ax.set_aspect('equal'); ax.tick_params(labelsize=6)
fig.tight_layout(); fig.savefig(out_png, dpi=110)
out_json.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding='utf-8')
print(json.dumps(res, ensure_ascii=False, indent=1))
