"""Read-only inventory of real LDD Shapefile ZIPs under ldd-policy-v2.

Runs the same validator the worker uses (gis_worker.ldd_provider.assess) on
local files and prints, per file: filename, SHA256, size, CRS, schema and field
types, feature count, field profile, Accepted / Accepted with Warnings / Review
Required / Rejected counts with reasons, unknown-code samples and repairs.

Nothing is written to a database, cache, Storage or the source file; the ZIP is
copied to a temporary directory named by its SHA256 because the validator only
opens files by hash. No network, GEE or credentials. Run it inside the pinned GIS
worker image (fiona/shapely/rasterio), for example:

  docker run --rm --network=none --read-only --tmpfs /tmp \
    -v <repo>/green-area-backend/gis_worker:/app/gis_worker:ro \
    -v <repo>/dev/gis_local/ldd_inventory.py:/app/ldd_inventory.py:ro \
    -v <folder with zips>:/data:ro --entrypoint python3 <image> -I -B /app/ldd_inventory.py \
    --province "Bangkok Metropolis" --year 2023 --crs EPSG:32647 /data/bkk_2566.zip

See dev/gis_local/run_ldd_inventory.ps1 for the Windows wrapper.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
from uuid import uuid4

def source_roots(here):
    """Folders that may hold gis_worker. Mounted at /app (the Windows wrapper), `here` has no grandparent."""
    return [here, here.parent] + [p / 'green-area-backend' for p in here.parents[1:2]]


HERE = Path(__file__).resolve().parent
for candidate in source_roots(HERE):
    if (candidate / 'gis_worker' / 'ldd_provider.py').is_file():
        sys.path.insert(0, str(candidate))
        break

from gis_worker import ldd_provider as ldd  # noqa: E402


def schema_of(raw, encoding):
    import fiona
    from fiona.io import ZipMemoryFile
    name, parts = ldd._components(ldd.guarded_zip(raw, package=True))
    with ZipMemoryFile(ldd.layer_archive(parts)) as memory:
        with memory.open('layer.shp', enabled_drivers=['ESRI Shapefile'], encoding=encoding) as collection:
            return {'layer': name, 'crs': collection.crs.to_string() if collection.crs else None,
                    'fields': dict(collection.schema['properties']), 'geometry_type': collection.schema['geometry'],
                    'feature_count': len(collection), 'bounds': [round(v, 3) for v in collection.bounds]}


def inventory(path, province, year, crs, encoding):
    path = Path(path)
    raw = path.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    item = {'filename': path.name, 'sha256': sha, 'byte_size': len(raw), 'province': province, 'data_year': year,
            'declared_crs': crs, 'encoding_requested': encoding}
    folder = Path(tempfile.mkdtemp(prefix='ldd-inventory-'))
    try:
        (folder / (sha + '.zip')).write_bytes(raw)
        request = {'upload_id': str(uuid4()), 'manifest': {'schema_version': 1, 'provider': 'real', 'sha256': sha,
            'byte_size': len(raw), 'provenance': 'local-ldd-upload-v1', 'crs': crs, 'data_kind': 'polygon',
            'attributes': list(ldd.REQUIRED_FIELDS)}, 'input_hash': '0' * 64, 'input_revision': 1,
            'attempt_number': 1, 'province': province, 'data_year': year, 'encoding': encoding}
        report, details = ldd.assess(request, storage_root=folder)
        try:
            item['schema'] = schema_of(raw, report['encoding'] if report['encoding'] != 'auto' else 'utf-8')
        except Exception as exc:  # inventory only; the validator result above is authoritative
            item['schema'] = {'error': type(exc).__name__}
        item.update(outcome=details['outcome'], feature_outcomes=details['feature_outcomes'],
                    valid=report['valid'], error_code=report['error_code'], errors=report['errors'],
                    warnings=report['warnings'], statistics=report['statistics'], checks=report['checks'],
                    encoding=report['encoding'], field_profile=details['field_profile'],
                    field_mapping=details['field_mapping'], declared_area_units=details['declared_area_units'],
                    boundary=details['boundary'], boundary_source=details['boundary_source'],
                    boundary_sha256=report['boundary_sha256'], repairs=details['repairs'][:20],
                    unknown_samples=list(details['unknown_samples'].values()), policy=details['policy'])
        return item
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('zips', nargs='+', type=Path)
    parser.add_argument('--province', required=True, help='English name as in province_boundaries.json')
    parser.add_argument('--year', type=int, required=True)
    parser.add_argument('--crs', default='EPSG:32647', choices=('EPSG:32647', 'EPSG:32648', 'EPSG:4326'))
    parser.add_argument('--encoding', default='auto', choices=ldd.ENCODINGS)
    args = parser.parse_args(argv)
    results = [inventory(z, args.province, args.year, args.crs, args.encoding) for z in args.zips]
    json.dump({'tool': 'ldd-inventory-v1', 'real_data': True, 'results': results}, sys.stdout,
              ensure_ascii=False, indent=2, default=str)
    sys.stdout.write('\n')


if __name__ == '__main__':
    main()
