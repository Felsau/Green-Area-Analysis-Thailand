"""Compute NDVI or LST from uploaded source bands, clipped to the province boundary.

NDVI = (B8 - B4) / (B8 + B4) from surface reflectance. LST = ST_B10 Digital Number
* 0.00341802 + 149.0 Kelvin (Landsat Collection 2 Level-2), reported in Celsius. The
statistics are for pixels inside an approximate boundary. Declared dates are not verified.
"""
from __future__ import annotations

import math

PROFILES = {
    'ndvi_bands': {'metric': 'ndvi', 'bands': ('B4', 'B8'), 'units': 'reflectance', 'output': 'unitless',
                   'dtypes': ('int16', 'uint16', 'float32', 'float64'), 'low': -1.0, 'high': 1.0},
    'lst_st_b10': {'metric': 'lst', 'bands': ('ST_B10',), 'units': 'landsat_c2_l2_dn', 'output': 'celsius',
                   'dtypes': ('uint16',), 'low': -100.0, 'high': 100.0},
}
ST_SCALE = 0.00341802
ST_OFFSET = 149.0
KELVIN = 273.15
BLOCK = 256
# Below this share of the province the result describes only part of it.
FULL_COVERAGE = 0.99


def _indicator(np, profile, arrays, scales, offsets, nodata):
    """Return (values in output units, usable mask) for one block."""
    usable = np.ones(arrays[0].shape, dtype=bool)
    for array in arrays:
        usable &= array != nodata
    if profile == 'lst_st_b10':
        kelvin = arrays[0].astype('float64') * ST_SCALE + ST_OFFSET
        return kelvin - KELVIN, usable
    red = arrays[0].astype('float64') * scales[0] + offsets[0]
    nir = arrays[1].astype('float64') * scales[1] + offsets[1]
    # Negative reflectance is sensor noise and would push the ratio out of range.
    usable &= (red >= 0) & (nir >= 0) & (red + nir > 0)
    values = np.zeros(red.shape, dtype='float64')
    values[usable] = (nir[usable] - red[usable]) / (nir[usable] + red[usable])
    return values, usable


def compute(request, raw, report, *, require, tags, limits):
    """Fill report for a band profile. require(condition, code) raises the public error."""
    import numpy as np
    import rasterio
    from rasterio.enums import MaskFlags
    from rasterio.features import geometry_mask
    from rasterio.io import MemoryFile
    from rasterio.warp import transform, transform_geom
    from rasterio.windows import Window
    from shapely.geometry import Polygon, mapping, shape
    from . import ldd_provider as ldd

    m, stats, metadata = request['manifest'], report['statistics'], report['metadata']
    profile = PROFILES[m['profile']]
    count = len(profile['bands'])
    with rasterio.Env(GDAL_PAM_ENABLED='NO', GDAL_DISABLE_READDIR_ON_OPEN='EMPTY_DIR',
            GDAL_GEOREF_SOURCES='INTERNAL', GDAL_NUM_THREADS='1', PROJ_NETWORK='OFF',
            GDAL_HTTP_TIMEOUT='1', GDAL_CACHEMAX=16 * 1024**2):
        with MemoryFile(raw) as memory, memory.open(driver='GTiff') as dataset:
            require(dataset.driver == 'GTiff' and not dataset.subdatasets and dataset.files == [memory.name],
                    'GEOTIFF_TIFF_STRUCTURE')
            report['checks'].append('tiff_structure')
            require(0 < dataset.width <= limits['dimension'] and 0 < dataset.height <= limits['dimension']
                    and dataset.width * dataset.height <= limits['pixels'], 'GEOTIFF_DIMENSIONS_LIMIT')
            stats.update(width=dataset.width, height=dataset.height, total_pixels=dataset.width * dataset.height)
            report['checks'].append('dimensions')

            epsg = dataset.crs.to_epsg() if dataset.crs else None
            metadata['crs'] = 'EPSG:' + str(epsg) if epsg in (32647, 32648, 4326) else None
            require(metadata['crs'] == m['crs'], 'GEOTIFF_CRS_MISMATCH')
            report['checks'].append('crs')

            require(dataset.count == count and dataset.descriptions == profile['bands'], 'GEOTIFF_BANDS_MISMATCH')
            stats['band_count'] = count
            metadata['bands'] = list(dataset.descriptions)
            report['checks'].append('bands')

            grid = dataset.transform
            require(all(math.isfinite(v) for v in tuple(grid)) and grid.b == 0 and grid.d == 0
                    and grid.a > 0 and grid.e < 0, 'GEOTIFF_RESOLUTION_INVALID')
            resolution = [float(v) for v in dataset.res]
            lower, upper = (0.000001, 1) if epsg == 4326 else (0.01, 1000)
            require(all(lower <= v <= upper for v in resolution), 'GEOTIFF_RESOLUTION_INVALID')
            metadata['resolution'] = resolution
            report['checks'].append('resolution')

            require(len(set(dataset.dtypes)) == 1 and dataset.dtypes[0] in profile['dtypes'], 'GEOTIFF_DTYPE_UNSUPPORTED')
            metadata['dtype'] = dataset.dtypes[0]
            report['checks'].append('dtype')

            nodata = dataset.nodata
            require(nodata is not None and math.isfinite(nodata) and abs(nodata) <= 1e30
                    and len(set(dataset.nodatavals)) == 1, 'GEOTIFF_NODATA_INVALID')
            metadata['nodata'] = float(nodata)
            require(dataset.mask_flag_enums == tuple([MaskFlags.nodata] for _ in range(count)), 'GEOTIFF_MASK_UNSUPPORTED')
            report['checks'].append('nodata')

            scales, offsets = [float(v) for v in dataset.scales], [float(v) for v in dataset.offsets]
            require(all(math.isfinite(v) for v in scales + offsets) and all(v > 0 for v in scales)
                    and len(set(scales)) == 1 and len(set(offsets)) == 1, 'GEOTIFF_SCALE_OFFSET_UNSUPPORTED')
            if m['profile'] == 'lst_st_b10':
                # Either the raw product (no scale in the file) or the published factors.
                require((scales, offsets) in (([1.0], [0.0]), ([ST_SCALE], [ST_OFFSET])), 'GEOTIFF_SCALE_OFFSET_UNSUPPORTED')
            metadata.update(scales=scales, offsets=offsets)
            report['checks'].append('scale_offset')

            metadata.update(units=profile['units'], output_units=profile['output'])
            report['checks'].append('units')

            declared = tags(dataset).get('GIS_PROFILE')
            require(declared is None or declared == m['profile'], 'GEOTIFF_PROFILE_MISMATCH')
            metadata['profile'] = m['profile']
            report['checks'].append('metadata_consistency')

            boundaries = ldd._asset('province_boundaries.json', ldd.BOUNDARY_SHA256)
            boundary = next((shape(f['geometry']) for f in boundaries['features']
                             if f['properties']['name'] == request['province']), None)
            require(boundary is not None and boundary.is_valid, 'GEOTIFF_PROVINCE_UNKNOWN')
            edge = dataset.bounds
            xs, ys = transform(dataset.crs, 'EPSG:4326', [edge.left, edge.right, edge.right, edge.left],
                               [edge.bottom, edge.bottom, edge.top, edge.top])
            footprint = Polygon(zip(xs, ys))
            require(footprint.is_valid and footprint.area > 0, 'GEOTIFF_BOUNDS_INVALID')
            outside = geometry_mask([transform_geom('EPSG:4326', dataset.crs, mapping(boundary))],
                                    out_shape=(dataset.height, dataset.width), transform=grid)
            inside_pixels = int(np.count_nonzero(~outside))
            require(inside_pixels > 0, 'GEOTIFF_OUTSIDE_PROVINCE')
            stats['outside_area_pixels'] = stats['total_pixels'] - inside_pixels
            province_fraction = min(1.0, footprint.intersection(boundary).area / boundary.area)
            report['coverage'] = {'mode': 'province_boundary_clip', 'boundary_sha256': ldd.BOUNDARY_SHA256,
                                  'boundary_approximate': True, 'fraction_of_province': province_fraction,
                                  'fraction_of_file': inside_pixels / stats['total_pixels']}
            report['checks'].append('coverage')

            total, low, high = 0.0, math.inf, -math.inf
            for row in range(0, dataset.height, BLOCK):
                for column in range(0, dataset.width, BLOCK):
                    window = Window(column, row, min(BLOCK, dataset.width - column), min(BLOCK, dataset.height - row))
                    arrays = [dataset.read(b + 1, window=window, masked=False) for b in range(count)]
                    stats['nonfinite_pixels'] += sum(int(np.count_nonzero(~np.isfinite(a))) for a in arrays)
                    require(stats['nonfinite_pixels'] == 0, 'GEOTIFF_NONFINITE_PIXELS')
                    inside = ~outside[row:row + int(window.height), column:column + int(window.width)]
                    values, usable = _indicator(np, m['profile'], arrays, scales, offsets, nodata)
                    usable &= inside
                    stats['nodata_pixels'] += int(np.count_nonzero(inside & ~usable))
                    selected = values[usable]
                    if selected.size:
                        require(bool(np.all(selected >= profile['low']) and np.all(selected <= profile['high'])),
                                'GEOTIFF_SCIENTIFIC_RANGE')
                        stats['valid_pixels'] += int(selected.size)
                        total += float(np.sum(selected, dtype='float64'))
                        low, high = min(low, float(selected.min())), max(high, float(selected.max()))
            require(stats['valid_pixels'] > 0, 'GEOTIFF_NO_VALID_PIXELS')
            # A rounded sum can put the mean just outside the extrema of near-uniform pixels.
            stats.update(mean=min(high, max(low, total / stats['valid_pixels'])), min=low, max=high)
            report['checks'].append('scientific_range')

    warnings = [{'code': 'BOUNDARY_APPROXIMATE', 'count': 1}, {'code': 'ACQUISITION_DATE_DECLARED_NOT_VERIFIED', 'count': 1}]
    if province_fraction < FULL_COVERAGE:
        warnings.append({'code': 'GEOTIFF_PARTIAL_PROVINCE_COVERAGE', 'count': 1})
    report.update(valid=True, errors=[], error_code=None, warnings=warnings)
