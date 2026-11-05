"""Gated Genuine specialization of the existing poll/heartbeat/lease worker.

No runnable Live launcher exists: an approved recorder process, memory channel
and enforceable network policy are still required. Queue JWT is NOT a Google
credential and is never handed to the SDK/HTTPS transport.
"""
from datetime import date

from gis_worker.worker import GisWorker, LocalWorkerClient, WorkerError
from gis_worker.gee_genuine_identity import GenuineBoundaryError
from gis_worker.gee_genuine_runtime import GenuineWorkerRuntime
from gis_worker.gee_live_contracts import Request
from gis_worker.gee_live_contracts import queue_report


class GenuineQueueClient(LocalWorkerClient):
    JWT_ROLE = 'gis_gee_https_worker'
    RPC_NAMES = ('gis_gee_https_worker', 'gis_gee_https_readiness')


class GenuineQueueWorker(GisWorker):
    def __init__(self, client, *, runtime):
        if type(runtime) is not GenuineWorkerRuntime:
            raise GenuineBoundaryError('GEE_GENUINE_RUNTIME_REQUIRED')
        super().__init__(client)
        self.runtime = runtime

    def readiness(self):
        value = self.client.call('gis_gee_https_readiness', {})
        expected = {'subject':self.client.subject,'worker_role':'gis_gee_https_worker',
            'database_name':'postgres','cluster_name':'green-area-gis-t0','protocol':'gee_genuine_https',
            'live_enabled':False,'contract_version':'1.0.0-a6-genuine',**self.client.expected}
        if not isinstance(value,dict) or any(value.get(k)!=v for k,v in expected.items()):
            raise WorkerError('WORKER_TARGET_REJECTED')
        return value

    def call(self, action, payload=None):
        self.readiness()
        return self.client.call('gis_gee_https_worker', {'p_action':action,'p_payload':payload or {}})

    def build_native_request(self, job):
        b = self.runtime.binding
        if (str(b.worker_subject) != self.client.subject or str(b.job_id) != job['id']
            or b.input_hash != job['input_hash'] or b.input_revision != job['input_revision']):
            raise GenuineBoundaryError('GEE_GENUINE_JOB_REJECTED')
        return job

    def _execute_native(self, request, timeout=180):
        if self._stop_event.is_set() or self._lease_lost.is_set():
            raise WorkerError('GIS_STALE_LEASE')
        try:
            result = self.runtime.compute(Request.model_validate(request['request']), request['geometry'], as_of=date.today())
        except Exception as error:
            # No exception bodies, tokens, URLs or credential metadata in logs.
            return self.failure_report(request, 'NATIVE_TIMEOUT' if isinstance(error,TimeoutError) else 'NATIVE_PROCESS_FAILED')
        if self._stop_event.is_set() or self._lease_lost.is_set():
            raise WorkerError('GIS_STALE_LEASE')
        return result

    def failure_report(self, request, code):
        base = queue_report(request, infrastructure_error=code)
        return {'schema_version':4,'protocol':'gee_genuine_https','execution':'live','live_enabled':False,
            'session_id':request['session_id'],'policy_sha256':request['policy_sha256'],
            'valid':False,'error_code':code,'base':base,'receipts':[],
            'failure_kind':'request_timeout' if code=='NATIVE_TIMEOUT' else 'accounting_uncertain'}


if __name__ == '__main__':
    # No stdin/environment/credential/CLI discovery before the closed boundary.
    raise GenuineBoundaryError('GEE_GENUINE_RUNTIME_DISABLED')
