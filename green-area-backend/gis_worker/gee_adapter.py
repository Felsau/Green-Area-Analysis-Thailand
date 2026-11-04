"""Mock-only A6.1 bridge. Does not import EE, legacy endpoints, cache or settings.

An injected bridge delegates to the legacy helper and returns its unchanged
payload plus raw observation evidence from that same computation. Stock legacy
helpers lose nulls/lineage; supplying only their summary is deliberately refused.
Real SDK/auth/network binding belongs to a separately approved later task.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import date
from typing import Callable

from pydantic import ValidationError

from gis_worker.gee_contracts import (ComputeOutput, LiveRequest, Observation, OutputContent,
                                    Statistics, digest, geometry_digest, method_for, observation_status)


class AdapterError(ValueError):
    """Fixed safe codes only; never propagate provider diagnostics or inputs."""


class ComputeFailure(Exception):
    def __init__(self, *, transient: bool = False):
        self.transient = transient
        super().__init__('GEE_TRANSIENT' if transient else 'GEE_REJECTED')


@dataclass(frozen=True)
class LegacyReturn:
    payload: object
    observation: Observation


@dataclass(frozen=True)
class LegacyBindings:
    # Each callable accepts (geometry_geojson, year, scale), as existing helpers
    # do. Monthly helpers still compute all 12 months; this wrapper selects one.
    ndvi_annual: Callable
    ndvi_monthly: Callable
    lst_annual: Callable
    lst_monthly: Callable


class SafeComputeAdapter:
    def __init__(self, bindings: LegacyBindings, *, as_of: date, execution: str = 'mock'):
        if execution != 'mock':
            raise AdapterError('GEE_LIVE_NOT_APPROVED')
        if (not isinstance(bindings, LegacyBindings) or type(as_of) is not date
            or not all(callable(getattr(bindings, name)) for name in LegacyBindings.__dataclass_fields__)):
            raise AdapterError('GEE_BINDINGS_INVALID')
        self.bindings, self.as_of = bindings, as_of

    def compute(self, request: LiveRequest, geometry: dict, *, expected_request_hash: str) -> ComputeOutput:
        try:
            if not isinstance(request, LiveRequest):
                raise ValueError()
            request = LiveRequest.model_validate(request.model_dump(mode='json'))
            if request.request_hash() != expected_request_hash:
                raise ValueError()
            # Snapshot before calling a bridge: it cannot mutate caller geometry.
            geometry = deepcopy(geometry)
            if geometry_digest(geometry) != request.boundary.geometry_sha256:
                raise ValueError()
        except (ValueError, TypeError, ValidationError):
            raise AdapterError('GEE_REQUEST_IDENTITY_MISMATCH') from None
        method = method_for(request.product, request.period.month)

        def finish(status, error=None, statistics=None, observation=None):
            content = OutputContent(request_hash=request.request_hash(), input_revision=request.input_revision,
                boundary=request.boundary, period=request.period, as_of=self.as_of, method=method, status=status,
                error_code=error, statistics=statistics or Statistics(), observation=observation)
            return ComputeOutput(content=content, output_sha256=digest(content.model_dump(mode='json')))

        helper = getattr(self.bindings, f'{request.product}_{method.frequency}')
        try:
            value = helper(geometry, request.period.year, method.reduction_scale_m)
        except ComputeFailure as error:
            return finish('failed', 'GEE_TRANSIENT' if error.transient else 'GEE_REJECTED')
        except Exception:
            return finish('failed', 'COMPUTE_FAILED')
        try:
            if not isinstance(value, LegacyReturn) or not isinstance(value.observation, Observation):
                raise ValueError()
            if geometry_digest(geometry) != request.boundary.geometry_sha256:
                raise ValueError()
            observation = Observation.model_validate(value.observation.model_dump(mode='json'))
            if (observation.request_hash != request.request_hash()
                or observation.geometry_sha256 != request.boundary.geometry_sha256
                or observation.product != request.product or observation.method_version != request.method_version
                or observation.period != request.period or observation.collections != method.collections):
                raise ValueError()
            raw = observation.raw_statistics
        except (ValueError, TypeError, ValidationError):
            raise AdapterError('GEE_OBSERVATION_IDENTITY_MISMATCH') from None

        status, error = observation_status(observation, self.as_of)
        if status != 'candidate':
            return finish(status, error, observation=observation)
        digits = 4 if request.product == 'ndvi' else 2
        statistics = Statistics(mean=round(raw.mean, digits), min=round(raw.min, digits) if raw.min is not None else None,
                                max=round(raw.max, digits) if raw.max is not None else None)
        try:
            payload = value.payload
            if method.frequency == 'monthly':
                if (not isinstance(payload, list) or len(payload) != 12
                    or any(not isinstance(row, dict) or type(row.get('month_num')) is not int for row in payload)
                    or sorted(row['month_num'] for row in payload) != list(range(1, 13))):
                    raise ValueError()
                row = next(row for row in payload if row['month_num'] == request.period.month)
                if type(row.get('image_count')) is not int or row['image_count'] != len(observation.scenes):
                    raise ValueError()
                actual, expected = (row.get(request.product),), (statistics.mean,)
            elif request.product == 'ndvi':
                actual = tuple(payload[k] for k in ('ndvi_mean', 'ndvi_min', 'ndvi_max'))
                expected = (statistics.mean, statistics.min, statistics.max)
            else:
                actual, expected = tuple(payload), (statistics.mean, statistics.min, statistics.max)
            if len(actual) != len(expected) or any(type(v) not in (int, float) for v in actual) or actual != expected:
                raise ValueError()
        except (KeyError, TypeError, ValueError, StopIteration):
            raise AdapterError('GEE_LEGACY_SUMMARY_MISMATCH') from None
        # Preserve monthly mean-only semantics: no invented monthly extrema.
        if method.frequency == 'monthly':
            statistics = Statistics(mean=statistics.mean)
        return finish('candidate', statistics=statistics, observation=observation)
