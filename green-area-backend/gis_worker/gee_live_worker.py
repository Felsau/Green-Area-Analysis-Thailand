"""Future Live specialization; executable credential/network boundary stays shut."""
from gis_worker.worker import GisWorker, LocalWorkerClient, WorkerError
from gis_worker.gee_live_contracts import queue_report

LIVE_RUNTIME_ENABLED = False
APPROVED_LIVE_IMAGE = None
LIVE_COMMAND = ('python3', '-I', '-B', '/app/gis_worker/gee_live_worker.py')


def require_live_runtime(*, image=None, command=(), restricted_egress=False, credential_channel=False):
    # All prerequisites require a separately reviewed source/policy change.
    # Caller booleans or environment variables can never authorize execution.
    if (not LIVE_RUNTIME_ENABLED or APPROVED_LIVE_IMAGE is None
        or image != APPROVED_LIVE_IMAGE or command != LIVE_COMMAND
        or not restricted_egress or not credential_channel):
        raise WorkerError('GEE_LIVE_RUNTIME_DISABLED')


class LiveClient(LocalWorkerClient):
    JWT_ROLE = 'gis_gee_live_worker'
    RPC_NAMES = ('gis_gee_live_worker', 'gis_gee_live_readiness')


class LiveWorker(GisWorker):
    """No new polling/queue architecture. Offline tests inject the compute port."""
    def readiness(self):
        value = self.client.call('gis_gee_live_readiness', {})
        expected = {'subject': self.client.subject, 'worker_role': 'gis_gee_live_worker',
            'database_name': 'postgres', 'cluster_name': 'green-area-gis-t0',
            'protocol': 'gee_live_v2', 'execution': 'injected', 'live_enabled': False,
            'contract_version': '2.0.0-a6.4b', **self.client.expected}
        if not isinstance(value, dict) or any(value.get(k) != v for k, v in expected.items()):
            raise WorkerError('WORKER_TARGET_REJECTED')
        return value

    def call(self, action, payload=None):
        self.readiness()
        return self.client.call('gis_gee_live_worker', {'p_action': action, 'p_payload': payload or {}})

    def build_native_request(self, job):
        return {key: job[key] for key in ('request', 'geometry', 'semantic_request_sha256', 'input_hash', 'input_revision')}

    def _execute_native(self, request, timeout=25):
        # A public daemon never receives an injected Python callable from a job.
        require_live_runtime()

    def failure_report(self, request, code):
        return queue_report(request, infrastructure_error=code)


if __name__ == '__main__':
    # Fail before reading stdin, credentials, config, importing SDK or networking.
    require_live_runtime()
