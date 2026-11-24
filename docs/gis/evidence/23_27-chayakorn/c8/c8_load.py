"""C8 (week 4): measure the load of large LDD packages outside the system. Read-only on every input.

For each chosen province, in this order:
  1. extract   copy the land-use layer's .shp/.shx/.dbf/.prj/.cpg out of the ZIP (Python zipfile, streamed)
               into <work>/<slug>/ under ASCII names; the ZIP itself is never modified
  2. read      a fresh child process opens the layer with fiona and reads every parcel: feature count,
               coordinate count (every coordinate pair, as gis_worker/ldd_provider.py _coordinates counts
               them) and psutil.Process().memory_info().peak_wset at the end
  3. geojson   a fresh child process writes three EPSG:4326 GeoJSON files shaped like the system's v2
               ldd_geometry (properties LU_CODE, LUL1_CODE, declared_area, area_m2, classification,
               repaired; coordinates rounded to 6 decimals; sorted keys, no spaces): raw, simplified at 5 m
               and at 20 m. Simplification runs in the layer's metric CRS before reprojection
               (shapely simplify, preserve_topology=True, per parcel). One pass per variant, timed.

The caps are read as text from <provider> (MAX_FEATURES, MAX_COORDINATES); nothing is imported from it.

    python c8_load.py run --zips <ldd-77> --c10-log <c10>/c10-run.log --provider <clone-c6>/.../ldd_provider.py \
        --work <c8-work> --out-json <c8>/c8-results.json --provinces "Bangkok Metropolis" "Nakhon Ratchasima" ...
"""
from __future__ import annotations

import argparse
import io
import json
import re
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

SIDECARS = ('.shp', '.shx', '.dbf', '.prj', '.cpg')
SIMPLIFY_M = {'raw': None, '5m': 5.0, '20m': 20.0}
DISPLAY_DECIMALS = 6


def read_caps(provider: Path) -> dict:
    text = provider.read_text(encoding='utf-8')
    caps = {}
    for name in ('MAX_FEATURES', 'MAX_COORDINATES'):
        m = re.search(rf'^{name}\s*=\s*([0-9_]+)\s*$', text, re.M)
        caps[name] = int(m.group(1).replace('_', '')) if m else None
    return caps


def count_coords(value) -> int:
    if value and isinstance(value[0], (float, int)):
        return 1
    return sum(count_coords(v) for v in value)


def rounded(value, digits=DISPLAY_DECIMALS):
    if isinstance(value, float):
        return round(value, digits)
    if isinstance(value, (list, tuple)):
        return [rounded(v, digits) for v in value]
    return value


def peak_mb() -> float:
    import psutil
    info = psutil.Process().memory_info()
    return round(getattr(info, 'peak_wset', info.rss) / 1024 ** 2, 1)


# ---------- child: read ----------
def child_read(shp: str, encoding: str) -> dict:
    import fiona
    base = peak_mb()
    t = time.perf_counter()
    n = coords = 0
    with fiona.open(shp, encoding=encoding) as src:
        crs = src.crs.to_epsg(confidence_threshold=20)
        for f in src:
            n += 1
            g = f['geometry']
            if g is not None:
                coords += count_coords(g['coordinates'])
    return {'features': n, 'vertices': coords, 'epsg': crs, 'read_s': round(time.perf_counter() - t, 2),
            'peak_wset_mb': peak_mb(), 'peak_wset_after_import_mb': base}


# ---------- child: geojson ----------
def child_geojson(shp: str, encoding: str, out_dir: str, slug: str) -> dict:
    import fiona
    from fiona.model import to_dict
    from fiona.transform import transform_geom
    from shapely.geometry import mapping, shape
    res = {}
    for variant, tol in SIMPLIFY_M.items():
        out = Path(out_dir) / f'{slug}_{variant}.geojson'
        t = time.perf_counter()
        n = coords = 0
        with fiona.open(shp, encoding=encoding) as src, open(out, 'wb') as fh:
            crs = src.crs
            keys = {k.upper(): k for k in src.schema['properties']}
            code_k, l1_k = keys.get('LU_CODE'), keys.get('LUL1_CODE')
            fh.write(b'{"features":[')
            first = True
            for i, f in enumerate(src):
                g = f['geometry']
                if g is None:
                    continue
                metric = shape(g)
                area = metric.area
                if tol is not None:
                    metric = metric.simplify(tol, preserve_topology=True)
                geo = to_dict(transform_geom(crs, 'EPSG:4326', mapping(metric)))
                geo = {'type': geo['type'], 'coordinates': rounded(geo['coordinates'])}
                coords += count_coords(geo['coordinates'])
                p = f['properties']
                code = str(p.get(code_k) or '').strip()
                main = str(p.get(l1_k) or '').strip() if l1_k else ''
                feat = {'type': 'Feature', 'id': i,
                        'properties': {'LU_CODE': code, 'LUL1_CODE': main or code[:1], 'declared_area': None,
                                       'area_m2': area, 'classification': main or code[:1], 'repaired': False},
                        'geometry': geo}
                fh.write((b'' if first else b',') + json.dumps(feat, ensure_ascii=False, sort_keys=True,
                                                                separators=(',', ':')).encode('utf-8'))
                first = False
                n += 1
            fh.write(b'],"type":"FeatureCollection"}')
        res[variant] = {'features': n, 'vertices': coords, 'bytes': out.stat().st_size,
                        'mb': round(out.stat().st_size / 1024 ** 2, 2), 'build_s': round(time.perf_counter() - t, 2),
                        'file': out.name}
    res['peak_wset_mb'] = peak_mb()
    return res


# ---------- driver ----------
def extract_layer(zip_path: Path, chain: list[str], layer_stem: str, dest: Path) -> dict:
    dest.mkdir(parents=True, exist_ok=True)
    t = time.perf_counter()
    z = zipfile.ZipFile(zip_path)
    for inner in chain:
        z = zipfile.ZipFile(io.BytesIO(z.read(next(i for i in z.infolist() if i.filename == inner))))
    sizes = {}
    for info in z.infolist():
        base = info.filename.rsplit('/', 1)[-1]
        stem, dot, ext = base.rpartition('.')
        if dot and stem.lower() == layer_stem.lower() and '.' + ext.lower() in SIDECARS:
            with z.open(info) as s, open(dest / ('layer.' + ext.lower()), 'wb') as d:
                shutil.copyfileobj(s, d, 1024 * 1024)
            sizes['.' + ext.lower()] = info.file_size
    return {'extract_s': round(time.perf_counter() - t, 2), 'member_bytes': sizes}


def run_child(mode: str, *args: str) -> dict:
    cmd = [sys.executable, '-I', str(Path(__file__).resolve()), mode, *args]
    cp = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8')
    if cp.returncode != 0:
        return {'error': (cp.stderr or cp.stdout).strip().splitlines()[-1][:300]}
    return json.loads(cp.stdout.strip().splitlines()[-1])


def driver(a) -> int:
    caps = read_caps(a.provider)
    print(json.dumps({'caps_from_provider': caps}), flush=True)
    log = a.c10_log.read_text(encoding='utf-8')
    entries = {en: (chain, layer) for en, chain, layer in
               re.findall(r'^\[([^\]]+)\] ldd-77 > (.+?) :: (.+)$', log, re.M)}
    slugs = {}
    results = {'caps': caps, 'provinces': []}
    for en in a.provinces:
        chain, layer = entries[en]
        parts = chain.split(' > ')
        stem = layer.rsplit('/', 1)[-1][:-4]
        slug = stem.split('_')[1]
        slugs[en] = slug
        work = a.work / '_layer' / slug
        row = {'province_en': en, 'slug': slug, 'layer': stem, 'zip': parts[0], 'chain': parts[1:]}
        print(f'\n[{en}] {stem}', flush=True)
        row.update(extract_layer(a.zips / parts[0], parts[1:], stem, work))
        print(f"  extract {row['extract_s']} s · dbf {row['member_bytes'].get('.dbf')} bytes", flush=True)
        enc = a.encoding.get(en, 'utf-8') if isinstance(a.encoding, dict) else 'utf-8'
        row['encoding'] = enc
        row['read'] = run_child('read', str(work / 'layer.shp'), enc)
        print(f"  read {row['read']}", flush=True)
        row['geojson'] = run_child('geojson', str(work / 'layer.shp'), enc, str(a.work), slug)
        print(f"  geojson {row['geojson']}", flush=True)
        r = row['read']
        if 'features' in r:
            row['over_feature_cap'] = r['features'] > caps['MAX_FEATURES']
            row['over_vertex_cap'] = r['vertices'] > caps['MAX_COORDINATES']
        shutil.rmtree(work, ignore_errors=True)
        results['provinces'].append(row)
    shutil.rmtree(a.work / '_layer', ignore_errors=True)
    a.out_json.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding='utf-8')
    print('\nresults written', flush=True)
    return 0


def main() -> int:
    sys.stdout.reconfigure(encoding='utf-8')
    if len(sys.argv) > 1 and sys.argv[1] == 'read':
        print(json.dumps(child_read(sys.argv[2], sys.argv[3])))
        return 0
    if len(sys.argv) > 1 and sys.argv[1] == 'geojson':
        print(json.dumps(child_geojson(*sys.argv[2:6])))
        return 0
    ap = argparse.ArgumentParser()
    ap.add_argument('mode', choices=['run'])
    ap.add_argument('--zips', type=Path, required=True)
    ap.add_argument('--c10-log', type=Path, required=True)
    ap.add_argument('--provider', type=Path, required=True)
    ap.add_argument('--work', type=Path, required=True)
    ap.add_argument('--out-json', type=Path, required=True)
    ap.add_argument('--provinces', nargs='+', required=True)
    ap.add_argument('--encoding', type=json.loads, default={}, help='JSON {province_en: encoding} from the C10 report')
    a = ap.parse_args()
    a.work.mkdir(parents=True, exist_ok=True)
    return driver(a)


if __name__ == '__main__':
    raise SystemExit(main())
