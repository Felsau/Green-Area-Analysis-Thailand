"""Explicit synthetic SDK/transport for offline foundation tests, never Google."""
from copy import deepcopy
from datetime import date, datetime, timezone
from uuid import uuid4

from gis_worker.gee_live_contracts import Request, geometry_digest

GEOMETRY = {'type': 'Polygon', 'coordinates': [[[100, 13], [100.01, 13], [100.01, 13.01], [100, 13]]]}


class Node:
    def __init__(self, calls, name):
        self.calls, self.name = calls, name

    def __getattr__(self, key):
        return Node(self.calls, self.name + '.' + key)

    def __call__(self, *args, **kwargs):
        self.calls.append((self.name, args, kwargs))
        if self.name.endswith('.map'):
            args[0](Node(self.calls, 'image'))
        return Node(self.calls, self.name)


class InjectedSDK:
    OFFLINE_INJECTED = True

    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        return Node(self.calls, name)

    def Dictionary(self, value):
        self.calls.append(('Dictionary', (value,), {}))
        return value


class InjectedTransport:
    OFFLINE_INJECTED = True

    def __init__(self, response):
        self.response, self.calls = deepcopy(response), 0

    def evaluate(self, graph, *, project):
        self.calls += 1
        return deepcopy(self.response)


def fixture(seed, *, product='ndvi', month=0, scenario='candidate', scope='sandbox_roi'):
    geometry_hash = geometry_digest(GEOMETRY)
    request = Request(request_id=uuid4(), input_revision=1, execution='injected', product=product,
        period={'year': 2025, 'month': month, 'start': date(2025, month or 1, 1),
            'end_exclusive': date(2026, 1, 1) if month in (0, 12) else date(2025, month + 1, 1)},
        scope={'kind': scope, 'province': 'Bangkok Metropolis', 'boundary_version': 'a64b-' + seed,
            'province_geometry_sha256': geometry_hash if scope == 'province' else 'a' * 64,
            'geometry_sha256': geometry_hash},
        project={'project_id': 'synthetic-a64b-' + seed, 'project_number': '123456789012',
            'principal': 'worker@synthetic-a64b-' + seed + '.iam.gserviceaccount.com'},
        method_version=product + ('-monthly-legacy-v1' if month else '-annual-legacy-v1'))
    no_scene, masked, partial = scenario == 'no_data', scenario == 'all_masked', scenario == 'incomplete'
    zero = scenario == 'zero'
    value = 0.0 if zero else 0.25 if product == 'ndvi' else 30.0
    raw = {'scene_ids': [] if no_scene else [request.method.collections[0] + '/INJECTED_ONLY'],
        'acquired_ms': [] if no_scene else [int(datetime(2025, month or 1, 2, tzinfo=timezone.utc).timestamp() * 1000)],
        'scene_count': 0 if no_scene else 1, 'valid_pixels': 0 if no_scene or masked else 2,
        'mean': None if no_scene or masked else value,
        'min': None if month or no_scene or masked else value,
        'max': None if month or no_scene or masked else value, 'complete': not partial}
    return request, deepcopy(GEOMETRY), raw
