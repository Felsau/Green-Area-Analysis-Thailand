"""A6.3 specialization of the existing daemon; no second polling architecture."""
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from gis_worker.worker import GisWorker, LocalWorkerClient, WorkerError, event, main


class MockClient(LocalWorkerClient):
    JWT_ROLE = 'gis_gee_mock_worker'
    RPC_NAMES = ('gis_gee_mock_worker', 'gis_gee_mock_readiness')


class MockWorker(GisWorker):
    CHILD_SCRIPT = 'gee_mock_child.py'

    def readiness(self):
        value = self.client.call('gis_gee_mock_readiness', {})
        expected = {'subject': self.client.subject, 'worker_role': 'gis_gee_mock_worker',
            'database_name': 'postgres', 'cluster_name': 'green-area-gis-t0', 'protocol': 'gee_contract_mock',
            'live_enabled': False, 'contract_version': '1.0.0-a6.2', **self.client.expected}
        if not isinstance(value, dict) or any(value.get(k) != v for k, v in expected.items()):
            raise WorkerError('WORKER_TARGET_REJECTED')
        return value

    def call(self, action, payload=None):
        self.readiness()
        return self.client.call('gis_gee_mock_worker', {'p_action': action, 'p_payload': payload or {}})

    def build_native_request(self, job):
        # No worker JWT, subject, lease token or transport configuration crosses
        # into the child; it receives only frozen scientific/mock inputs.
        return {k: job[k] for k in ('request', 'geometry', 'input_hash', 'input_revision',
                                   'semantic_request_sha256', 'attempt_number')}

    def failure_report(self, request, code):
        if code not in {'NATIVE_TIMEOUT', 'NATIVE_MEMORY_LIMIT', 'NATIVE_PROCESS_FAILED',
                        'WORKER_SHUTDOWN', 'NATIVE_OUTPUT_LIMIT'}:
            raise WorkerError('WORKER_FAILURE_REJECTED')
        return {'schema_version': 1, 'protocol': 'gee_contract_mock', 'input_hash': request['input_hash'],
            'input_revision': request['input_revision'], 'semantic_request_sha256': request['semantic_request_sha256'],
            'valid': False, 'error_code': code, 'output': None}


if __name__ == '__main__':
    try:
        main(MockClient, MockWorker)
    except Exception as error:
        code = str(error) if isinstance(error, WorkerError) else ''
        event('fatal', error_code=code if re.fullmatch('(?:GIS|WORKER)_[A-Z0-9_]+', code) else 'WORKER_STARTUP_FAILED')
        raise SystemExit(1)
