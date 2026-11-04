"""Internal A6.2 hooks, not an HTTP route, daemon, SDK or credential provider.

Cases are installed by the attested local operator into a private immutable
registry. Workers cannot register cases or decide the expected result. Mock
output hashes address JSON summaries, never satellite/raster files.
"""
from __future__ import annotations

from copy import deepcopy
import json
from uuid import UUID

from gis_worker.gee_contracts import ComputeOutput, LiveRequest, digest, geometry_digest, method_for

PROTOCOL = 'gee_contract_mock'
ROLE = 'gis_gee_mock_worker'
INFRA = {'NATIVE_TIMEOUT', 'NATIVE_MEMORY_LIMIT', 'NATIVE_PROCESS_FAILED', 'WORKER_SHUTDOWN', 'NATIVE_OUTPUT_LIMIT'}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False)


def mock_case(request: LiveRequest, geometry: dict, output: ComputeOutput) -> dict:
    """Pure operator-side validation before private fixture registration."""
    request = LiveRequest.model_validate(request.model_dump(mode='json'))
    output = ComputeOutput.model_validate(output.model_dump(mode='json'))
    content = output.content
    if (geometry_digest(geometry) != request.boundary.geometry_sha256
        or content.request_hash != request.request_hash() or content.input_revision != request.input_revision
        or content.boundary != request.boundary or content.period != request.period
        or content.method != method_for(request.product, request.period.month)):
        raise ValueError('GEE_MOCK_CASE_IDENTITY_MISMATCH')
    value = {'request': request.model_dump(mode='json'),
        'request_canonical': canonical({'request': request.model_dump(mode='json', exclude={'request_id'}),
                                      'method': content.method.model_dump(mode='json')}),
        'request_sha256': request.request_hash(), 'geometry': deepcopy(geometry),
        'geometry_canonical': canonical(geometry), 'geometry_sha256': geometry_digest(geometry),
        'output': output.model_dump(mode='json'), 'output_canonical': canonical(content.model_dump(mode='json')),
        'output_sha256': output.output_sha256}
    if len(canonical(value).encode()) > 32768:
        raise ValueError('GEE_MOCK_CASE_LIMIT')
    return value


def report(job: dict, output: ComputeOutput | None = None, *, infrastructure_error: str | None = None) -> dict:
    """No actor, worker ID, path, URL, command, SQL, project or publication flag."""
    request = LiveRequest.model_validate(job['request'])
    if (request.request_hash() != job['semantic_request_sha256']
        or request.input_revision != job['input_revision']
        or geometry_digest(job['geometry']) != request.boundary.geometry_sha256):
        raise ValueError('GEE_MOCK_CLAIM_MISMATCH')
    body = {'schema_version': 1, 'protocol': PROTOCOL, 'input_hash': job['input_hash'],
            'input_revision': job['input_revision'], 'semantic_request_sha256': request.request_hash()}
    if infrastructure_error is not None:
        if infrastructure_error not in INFRA or output is not None:
            raise ValueError('GEE_MOCK_FAILURE_INVALID')
        return body | {'valid': False, 'error_code': infrastructure_error, 'output': None}
    if output is None:
        raise ValueError('GEE_MOCK_OUTPUT_REQUIRED')
    validated = mock_case(request, job['geometry'], output)['output']
    valid = output.content.status == 'candidate'
    code = None if valid else 'TRANSIENT_SYNTHETIC' if output.content.error_code == 'GEE_TRANSIENT' else 'invalid_data'
    return body | {'valid': valid, 'error_code': code, 'output': validated}


class MockQueueHooks:
    """RPC transport is injected; the SQL role/subject remains authoritative.

    A6.2 supplies claim/heartbeat/complete/recovery hooks only. No poll loop,
    process/container spawning, real compute binding or Google auth is added.
    """
    def __init__(self, rpc, *, subject: str, runtime_instance: str, baseline_fingerprint: str):
        self.rpc, self.subject = rpc, str(UUID(subject))
        self.expected = {'subject': self.subject, 'runtime_instance': runtime_instance,
                         'baseline_fingerprint': baseline_fingerprint, 'database_name': 'postgres',
                         'cluster_name': 'green-area-gis-t0', 'worker_role': ROLE,
                         'protocol': PROTOCOL, 'live_enabled': False, 'contract_version': '1.0.0-a6.2'}

    def readiness(self):
        value = self.rpc('gis_gee_mock_readiness', {})
        if not isinstance(value, dict) or any(value.get(k) != v for k, v in self.expected.items()):
            raise ValueError('GEE_MOCK_TARGET_REJECTED')
        return value

    def call(self, action, payload=None):
        if action not in ('claim', 'recover', 'heartbeat', 'complete', 'fail'):
            raise ValueError('GEE_MOCK_ACTION_REJECTED')
        self.readiness()
        return self.rpc('gis_gee_mock_worker', {'p_action': action, 'p_payload': payload or {}})

    def complete(self, job, output):
        value = report(job, output)
        payload = {'job_id': str(UUID(job['id'])), 'lease_token': str(UUID(job['lease_token'])), 'report': value}
        if value['error_code'] == 'TRANSIENT_SYNTHETIC':
            return self.call('fail', payload | {'error_code': 'transient'})
        return self.call('complete', payload)
