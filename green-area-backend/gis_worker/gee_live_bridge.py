"""Explicit SDK-expression boundary. Only injected SDK/transport runs in A6.4b.

No ee import, Initialize, ADC, endpoint, cache, filesystem or network discovery.
The graph uses the legacy summary method, not legacy endpoint side effects.
"""
from datetime import date, datetime, timezone

from gis_worker.gee_contracts import Statistics
from gis_worker.gee_live_contracts import Content, Evidence, MAX_SCENES, Output, Request, digest, geometry_digest


class BridgeError(ValueError):
    pass


def require_offline(sdk, transport, request, approved_project):
    if (request.execution != 'injected' or getattr(sdk, 'OFFLINE_INJECTED', None) is not True
        or getattr(transport, 'OFFLINE_INJECTED', None) is not True):
        raise BridgeError('GEE_LIVE_NOT_APPROVED')
    if approved_project != request.project:
        raise BridgeError('GEE_LIVE_PROJECT_MISMATCH')


def build_graph(sdk, request, geometry):
    if request.execution != 'injected' or getattr(sdk, 'OFFLINE_INJECTED', None) is not True:
        raise BridgeError('GEE_LIVE_NOT_APPROVED')
    if geometry_digest(geometry) != request.scope.geometry_sha256:
        raise BridgeError('GEE_LIVE_GEOMETRY_MISMATCH')
    return _build_expression(sdk, request, geometry)


def _build_expression(sdk, request, geometry):
    """Pure shared expression; grants no transport/result authority."""
    ee, method = sdk, request.method
    geom = ee.Geometry(geometry)
    period = request.period

    def source(collection, cloud_field, threshold):
        return (ee.ImageCollection(collection).filterBounds(geom)
            .filterDate(period.start.isoformat(), period.end_exclusive.isoformat())
            .filter(ee.Filter.lt(cloud_field, threshold)))

    if request.product == 'ndvi':
        def clean(threshold):
            col = source(method.collections[0], 'CLOUDY_PIXEL_PERCENTAGE', threshold)
            col = col.linkCollection(ee.ImageCollection(method.collections[1]), ['cs'])
            return col.map(lambda image: image.updateMask(image.select('cs').gte(0.6))
                           .divide(10000).copyProperties(image, ['system:id', 'system:time_start']))
        col = clean(method.scene_cloud_lt)
        if not period.month:
            col = ee.ImageCollection(ee.Algorithms.If(col.size().gt(0), col, clean(80)))
        median = col.median()
        if not period.month:
            median = median.clip(geom)
        if period.month:
            median = median.addBands(ee.Image.constant([0, 0]).rename(['B8', 'B4']).selfMask(), overwrite=False)
        image = median.normalizedDifference(['B8', 'B4']).rename('NDVI')
        if not period.month:
            image = image.updateMask(image.gte(0))
        band = 'NDVI'
    else:
        def scale(image):
            qa = image.select('QA_PIXEL')
            mask = qa.bitwiseAnd(1 << 4).eq(0).And(qa.bitwiseAnd(1 << 3).eq(0))
            masked = image.updateMask(mask)
            return masked.addBands(masked.select('ST_B10').multiply(0.00341802)
                .add(149.0).subtract(273.15).rename('LST'))
        col = (source(method.collections[0], 'CLOUD_COVER', 40).map(scale).select('LST')
               .merge(source(method.collections[1], 'CLOUD_COVER', 40).map(scale).select('LST')))
        image = col.median()
        if period.month:
            image = image.addBands(ee.Image.constant(0).rename('LST').selfMask(), overwrite=False)
        band = 'LST'
    reducer = ee.Reducer.mean()
    if not period.month:
        reducer = reducer.combine(ee.Reducer.min(), '', True).combine(ee.Reducer.max(), '', True)
    params = {'geometry': geom, 'scale': 500, 'maxPixels': 10**10, 'bestEffort': True}
    if request.product == 'ndvi' and not period.month:
        params['tileScale'] = 4
    stats = image.reduceRegion(reducer=reducer, **params)
    count = image.reduceRegion(reducer=ee.Reducer.count(), **params).get(band)
    # Collect at most limit+1, while separately counting the full collection.
    # An overflow is rejected by the parser rather than called complete.
    bounded = col.limit(MAX_SCENES + 1)
    return ee.Dictionary({'complete': True, 'scene_ids': bounded.aggregate_array('system:id'),
        'acquired_ms': bounded.aggregate_array('system:time_start'), 'scene_count': col.size(),
        'valid_pixels': count, 'mean': stats.get(band if period.month else band + '_mean'),
        'min': None if period.month else stats.get(band + '_min'),
        'max': None if period.month else stats.get(band + '_max')})


class InjectedBridge:
    """Trusted dependencies are explicit; no arbitrary callbacks from API jobs."""
    def __init__(self, *, sdk, transport, authorization, as_of: date):
        if type(as_of) is not date:
            raise BridgeError('GEE_LIVE_DATE_REQUIRED')
        self.sdk, self.transport, self.authorization, self.as_of = sdk, transport, authorization, as_of

    def compute(self, request, geometry):
        request = Request.model_validate(request.model_dump(mode='json'))
        # Reject before authorization/evaluation, including an injected SDK.
        if request.execution != 'injected':
            raise BridgeError('GEE_LIVE_NOT_APPROVED')
        approved_project = self.authorization()
        require_offline(self.sdk, self.transport, request, approved_project)
        graph = build_graph(self.sdk, request, geometry)
        raw = self.transport.evaluate(graph, project=approved_project)
        return observation_output(request, raw, as_of=self.as_of)


def observation_output(request, raw, *, as_of):
    """Pure scientific validation. A valid document/hash is NOT origin proof."""
    allowed = {'scene_ids', 'acquired_ms', 'scene_count', 'valid_pixels', 'mean', 'min', 'max', 'complete'}
    if (not isinstance(raw, dict) or set(raw) != allowed or not isinstance(raw['scene_ids'], list)
        or not isinstance(raw['acquired_ms'], list) or len(raw['scene_ids']) != len(raw['acquired_ms'])
        or len(raw['scene_ids']) > MAX_SCENES):
        raise BridgeError('GEE_LIVE_RESPONSE_REJECTED')
    scenes = []
    for image_id, millis in zip(raw['scene_ids'], raw['acquired_ms']):
        if not isinstance(image_id, str) or type(millis) is not int:
            raise BridgeError('GEE_LIVE_SCENE_REJECTED')
        scenes.append({'collection': image_id.rsplit('/', 1)[0], 'image_id': image_id,
            'acquired': datetime.fromtimestamp(millis / 1000, timezone.utc).date()})
    evidence = Evidence(request_sha256=request.request_hash(), geometry_sha256=request.scope.geometry_sha256,
        project=request.project, method=request.method, period=request.period, scenes=scenes,
        scene_count=raw['scene_count'], complete=raw['complete'], valid_pixels=raw['valid_pixels'],
        raw_statistics=Statistics(mean=raw['mean'], min=raw['min'], max=raw['max']), units=request.method.units)
    status, statistics = evidence.status(as_of), Statistics()
    if status == 'candidate':
        digits = 4 if request.product == 'ndvi' else 2
        statistics = Statistics(mean=round(raw['mean'], digits),
            min=round(raw['min'], digits) if not request.period.month else None,
            max=round(raw['max'], digits) if not request.period.month else None)
    content = Content(request=request, request_sha256=request.request_hash(), geometry_sha256=request.scope.geometry_sha256,
        execution=request.execution, synthetic=request.execution == 'injected', as_of=as_of, status=status, evidence=evidence,
        evidence_sha256=digest(evidence.model_dump(mode='json')), statistics=statistics)
    return Output(content=content, output_sha256=digest(content.model_dump(mode='json')))
