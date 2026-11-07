"""Build gis_worker/province_boundaries_ldd.json from real LDD province packages.

The LDD validator checks every parcel against a province boundary. The first asset
(province_boundaries.json, GADM level 1) is coarse: Bangkok has 161 vertices and differs from
the official outline by 3.3 % of its area, which made 133 of 11,073 real parcels "outside the
province". Each LDD package ships the producer's own province layer (<name>_Pro.shp or
prov_<name>.shp). This tool copies the base asset and replaces the geometry of every province
for which a package supplies that layer. Other provinces keep their GADM geometry unchanged.

  * The output is deterministic: features keep the base order, keys are sorted, coordinates are
    snapped to 1e-8 degrees (about 1 mm). Run it twice and the bytes are the same.
  * A package is matched to a province by overlap with the GADM outline, never by file name. It
    must overlap one province by at least 80 % (IoU) and no other by more than 20 %.
  * Each replaced feature records the SHA256 of the ZIP and of the layer's .shp it came from.
  * The boundary comes from the data producer, not from an independent source.

Untrusted input: run inside the pinned GIS worker image with no network and read-only mounts, see
run_build_ldd_boundaries.ps1. Nothing is written except --out and --report.

  python3 -I -B build_ldd_boundaries.py --base /app/gis_worker/province_boundaries.json \
      --packages /data --out /out/province_boundaries_ldd.json [--report /out/report.json] [--verify]

--verify also reads each package's land-use layer and counts the parcels outside the new
boundary (inside / within 225 m / beyond), as a check that the layer and its CRS are the right ones.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import sys
import zipfile

sys.path.insert(0, '/app')

import shapely  # noqa: E402
from fiona.io import ZipMemoryFile  # noqa: E402
from fiona.transform import transform_geom  # noqa: E402
from shapely.geometry import mapping, shape  # noqa: E402
from shapely.ops import unary_union  # noqa: E402

from gis_worker import ldd_policy as policy  # noqa: E402

DECIMALS = 8                  # about 1 mm; the default the committed asset was built with, see --decimals
GRID = 10.0 ** -DECIMALS
SOURCE_LDD = 'ldd-package'
SOURCE_GADM = 'gadm-approx'
MIN_IOU, MAX_OTHER_IOU = 0.80, 0.20
VERSION = 'ldd-boundaries-v1'


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def is_province_layer(name):
    base = PurePosixPath(name).name.casefold()
    return base.endswith('.shp') and (base.endswith('_pro.shp') or base.startswith('prov_'))


def flat_archive(archive, infos, shp_name):
    """The layer's components alone, under fixed ASCII names (member names in these ZIPs are legacy-encoded Thai)."""
    stem = str(PurePosixPath(shp_name).with_suffix('')).casefold()
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_STORED) as z:
        for info in infos:
            p = PurePosixPath(info.filename)
            if p.suffix.lower() in policy.LAYER_SUFFIXES and str(p.with_suffix('')).casefold() == stem:
                z.writestr(zipfile.ZipInfo('layer' + p.suffix.lower(), date_time=(1980, 1, 1, 0, 0, 0)), archive.read(info))
    return out.getvalue()


def read_layer(blob):
    """(crs string, iterator of shapely geometries) of an in-memory single-layer ZIP; attributes are not decoded."""
    memory = ZipMemoryFile(blob)
    collection = memory.open('layer.shp', encoding='latin-1')
    crs = collection.crs.to_string() if collection.crs else None
    return memory, collection, crs


def official_outline(blob):
    memory, collection, crs = read_layer(blob)
    try:
        parts = [shape(transform_geom(crs, 'EPSG:4326', f['geometry'])) for f in collection if f['geometry']]
    finally:
        collection.close()
        memory.close()
    outline = unary_union(parts)
    if not outline.is_valid:
        outline = shapely.make_valid(outline)
    outline = shapely.set_precision(outline, GRID)
    polygons = [g for g in getattr(outline, 'geoms', [outline]) if g.geom_type in ('Polygon', 'MultiPolygon') and not g.is_empty]
    outline = unary_union(polygons)
    if outline.is_empty or outline.geom_type not in ('Polygon', 'MultiPolygon') or not outline.is_valid:
        raise ValueError('boundary is not a valid polygon after snapping')
    return crs, outline


def rounded(geometry):
    """GeoJSON-style dict with coordinates rounded to DECIMALS, lists not tuples."""
    def walk(value):
        if isinstance(value, (list, tuple)):
            return [walk(v) for v in value]
        return round(float(value), DECIMALS)
    data = mapping(geometry)
    return {'type': data['type'], 'coordinates': walk(data['coordinates'])}


def vertices(geometry):
    return int(len(shapely.get_coordinates(geometry)))


def iou(a, b):
    union = a.union(b).area
    return a.intersection(b).area / union if union else 0.0


def verify_land_use(archive, infos, outline_4326):
    layer = policy.select_land_use_layer([i.filename for i in infos])
    if layer is None:
        return {'error': 'no single land-use layer'}
    blob = flat_archive(archive, infos, layer)
    memory, collection, crs = read_layer(blob)
    try:
        boundary = shape(transform_geom('EPSG:4326', crs, mapping(outline_4326)))
        minor = boundary.buffer(policy.BOUNDARY_MINOR_M)
        for g in (boundary, minor):
            shapely.prepare(g)
        counts = {'parcels': 0, 'inside': 0, 'within_minor': 0, 'beyond_minor': 0}
        total = outside = 0.0
        for feature in collection:
            if not feature['geometry']:
                continue
            g = shape(feature['geometry'])
            if not g.is_valid:
                g = shapely.make_valid(g)
            counts['parcels'] += 1
            total += g.area
            if boundary.covers(g):
                counts['inside'] += 1
            else:
                outside += g.difference(boundary).area
                counts['within_minor' if minor.covers(g) else 'beyond_minor'] += 1
        counts['layer_crs'] = crs
        counts['outside_area_share'] = round(outside / total, 8) if total else None
        return counts
    finally:
        collection.close()
        memory.close()


def main(argv=None):
    global DECIMALS, GRID
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--base', type=Path, required=True)
    parser.add_argument('--packages', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--report', type=Path)
    parser.add_argument('--verify', action='store_true')
    parser.add_argument('--decimals', type=int, default=DECIMALS, help='coordinate precision in decimal places of a degree (8 = about 1 mm)')
    args = parser.parse_args(argv)
    DECIMALS, GRID = args.decimals, 10.0 ** -args.decimals

    base_bytes = args.base.read_bytes()
    base = json.loads(base_bytes)
    base_shapes = {f['properties']['name']: shape(f['geometry']) for f in base['features']}
    found, report = {}, []
    for path in sorted(args.packages.glob('*.zip'), key=lambda p: p.name):
        entry = {'package': ascii(path.name)}
        report.append(entry)
        raw = path.read_bytes()
        entry['package_sha256'] = sha256(raw)
        try:
            archive = zipfile.ZipFile(io.BytesIO(raw))
            infos = [i for i in archive.infolist() if not i.is_dir()]
        except zipfile.BadZipFile:
            entry['skipped'] = 'not a readable ZIP'
            continue
        layers = [i.filename for i in infos if is_province_layer(i.filename)]
        if len(layers) != 1:
            entry['skipped'] = 'province layers found: %d' % len(layers)
            continue
        blob = flat_archive(archive, infos, layers[0])
        try:
            crs, outline = official_outline(blob)
        except Exception as exc:  # noqa: BLE001 - report and continue
            entry['skipped'] = 'unreadable boundary: ' + type(exc).__name__
            continue
        scores = sorted(((iou(outline, g), name) for name, g in base_shapes.items() if outline.intersects(g)), reverse=True)
        if not scores or scores[0][0] < MIN_IOU or (len(scores) > 1 and scores[1][0] > MAX_OTHER_IOU):
            entry['skipped'] = 'no unique province match: %s' % [(round(s, 3), n) for s, n in scores[:2]]
            continue
        score, name = scores[0]
        if name in found:
            entry['skipped'] = 'second package for %s' % name
            continue
        member = next(i for i in infos if i.filename == layers[0])
        year = re.search(r'25\d\d', path.name)
        found[name] = {'geometry': rounded(outline), 'package_sha256': entry['package_sha256'],
                       'shp_sha256': sha256(archive.read(member)), 'data_year_be': int(year.group(0)) if year else None,
                       'source_crs': crs}
        entry.update(province=name, iou_with_gadm=round(score, 4), source_crs=crs, vertices_gadm=vertices(base_shapes[name]),
                     vertices_official=vertices(outline), area_ratio_official_to_gadm=round(outline.area / base_shapes[name].area, 4))
        if args.verify:
            entry['land_use_check'] = verify_land_use(archive, infos, outline)

    features = []
    for feature in base['features']:
        name = feature['properties']['name']
        if name in found:
            f = found[name]
            props = {'name': name, 'source': SOURCE_LDD, 'package_sha256': f['package_sha256'], 'shp_sha256': f['shp_sha256'],
                     'data_year_be': f['data_year_be'], 'source_crs': f['source_crs']}
            features.append({'type': 'Feature', 'properties': props, 'geometry': f['geometry']})
        else:
            features.append({'type': 'Feature', 'properties': {'name': name, 'source': SOURCE_GADM, 'gid_1': feature['properties'].get('GID_1')},
                             'geometry': feature['geometry']})
    asset = {'type': 'FeatureCollection', 'name': 'province_boundaries_ldd', 'crs': base['crs'],
             'metadata': {'version': VERSION, 'base_asset': 'province_boundaries.json', 'base_asset_sha256': sha256(base_bytes),
                          'generator': 'dev/gis_local/build_ldd_boundaries.py', 'coordinate_grid_degrees': GRID,
                          'sources': {SOURCE_GADM: 'GADM 4.1 level 1 as simplified in the base asset; approximate',
                                      SOURCE_LDD: 'province layer shipped inside the LDD land-use package of that province; '
                                                  'supplied by the data producer, not independently verified'}},
             'features': features}
    # No newline at all: a hash-pinned asset must not change when Git converts line endings on a Windows checkout.
    data = json.dumps(asset, ensure_ascii=True, separators=(',', ':'), sort_keys=True).encode('ascii')
    args.out.write_bytes(data)
    summary = {'asset_sha256': sha256(data), 'bytes': len(data), 'features': len(features),
               'replaced': sorted(found), 'kept_gadm': sorted(f['properties']['name'] for f in features if f['properties']['source'] == SOURCE_GADM),
               'packages': report}
    text = json.dumps(summary, ensure_ascii=True, indent=1)
    if args.report:
        args.report.write_text(text, encoding='ascii')
    print(json.dumps({k: summary[k] for k in ('asset_sha256', 'bytes', 'features')}), 'replaced=%d kept_gadm=%d' % (len(found), len(summary['kept_gadm'])))
    for entry in report:
        print(' ', entry.get('province') or '-', '|', entry.get('skipped') or ('iou %.3f vertices %d->%d area x%.3f crs %s' % (
            entry['iou_with_gadm'], entry['vertices_gadm'], entry['vertices_official'], entry['area_ratio_official_to_gadm'], entry['source_crs'])),
              '|', entry.get('land_use_check', ''))


if __name__ == '__main__':
    main()
