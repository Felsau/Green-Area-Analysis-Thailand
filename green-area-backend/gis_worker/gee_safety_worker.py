"""Reuse the existing lifecycle with an injected-only accounted compute port."""
from gis_worker.worker import GisWorker, LocalWorkerClient, WorkerError
from gis_worker.gee_execution_safety import AccountedTransport, JOB_TIMEOUT, report, require_real_transport
from gis_worker.gee_live_contracts import queue_report
from gis_worker.gee_live_contracts import Output


class _IsolatedCompute(GisWorker):
    CHILD_SCRIPT = 'gee_safety_child.py'

    def failure_report(self, request, code):
        return {'native_error':code}


class InjectedChildPort:
    """Fixed credential-free Linux child; no arbitrary path/command from jobs."""
    OFFLINE_INJECTED = True

    def __init__(self, job, *, scenario='candidate', owner=None):
        if scenario not in ('candidate','zero','no_data','incomplete','hang'):
            raise WorkerError('GEE_INJECTED_SCENARIO_REJECTED')
        self.packet={'request':job['request'],'geometry':job['geometry'],'scenario':scenario}
        self.isolated=_IsolatedCompute(None)
        if owner is not None:
            self.isolated._stop_event=owner._stop_event
            self.isolated._lease_lost=owner._lease_lost

    def evaluate(self, *, timeout_seconds):
        if not 0<timeout_seconds<=120:
            raise WorkerError('GEE_TIMEOUT_POLICY_REJECTED')
        value=GisWorker._execute_native(self.isolated,self.packet,timeout=timeout_seconds)
        if 'native_error' in value:
            raise WorkerError(value['native_error'])
        return Output.model_validate(value)


class SafetyClient(LocalWorkerClient):
    JWT_ROLE = 'gis_gee_safety_worker'
    RPC_NAMES = ('gis_gee_safety_worker','gis_gee_safety_readiness')


class RehearsalWorker(GisWorker):
    def __init__(self, client, *, injected_port=None, clock=None):
        super().__init__(client)
        self.injected_port, self.clock = injected_port, clock

    def readiness(self):
        value=self.client.call('gis_gee_safety_readiness',{})
        expected={'subject':self.client.subject,'worker_role':'gis_gee_safety_worker',
            'database_name':'postgres','cluster_name':'green-area-gis-t0','protocol':'gee_safety_rehearsal',
            'live_enabled':False,'contract_version':'1.0.0-a6.4d1',**self.client.expected}
        if not isinstance(value,dict) or any(value.get(k)!=v for k,v in expected.items()):
            raise WorkerError('WORKER_TARGET_REJECTED')
        return value

    def call(self, action, payload=None):
        self.readiness()
        return self.client.call('gis_gee_safety_worker',{'p_action':action,'p_payload':payload or {}})

    def build_native_request(self, job):
        # Non-secret metadata only. Queue JWT/lease stays with the parent.
        self._job=dict(job)
        return {k:job[k] for k in ('request','geometry','semantic_request_sha256','input_hash','input_revision')}

    def _execute_native(self, request, timeout=JOB_TIMEOUT):
        if self.injected_port is None:
            require_real_transport()
        kwargs={} if self.clock is None else {'clock':self.clock}
        transport=AccountedTransport(self.call,self._job,**kwargs)
        try:
            port=self.injected_port(self._job)
            if isinstance(port,InjectedChildPort):
                port.isolated._stop_event=self._stop_event
                port.isolated._lease_lost=self._lease_lost
            output,receipt=transport.execute(port)
            return transport.report(output,[receipt])
        except Exception as error:
            # Safe fixed infrastructure report; all raw provider errors discarded.
            text=str(error)
            if text in ('GEE_JOB_TIMEOUT','GIS_SAFETY_JOB_TIMEOUT') or (
                text=='NATIVE_TIMEOUT' and transport.clock()-transport.started>=transport.job_seconds):
                kind='job_timeout'
            elif text in ('GEE_REQUEST_TIMEOUT','NATIVE_TIMEOUT') or isinstance(error,TimeoutError):kind='request_timeout'
            elif text=='GIS_STALE_LEASE':kind='lease_expired'
            elif text=='GEE_REQUEST_BUDGET_EXHAUSTED':kind='budget_exhausted'
            elif text=='GIS_SAFETY_SESSION_CLOSED':kind='session_stopped'
            elif text in ('WORKER_SHUTDOWN','NATIVE_MEMORY_LIMIT','NATIVE_OUTPUT_LIMIT'):kind='transient'
            else:kind='accounting_uncertain'
            code=('NATIVE_TIMEOUT' if kind in ('request_timeout','job_timeout') else
                text if text in ('WORKER_SHUTDOWN','NATIVE_MEMORY_LIMIT','NATIVE_OUTPUT_LIMIT') else 'NATIVE_PROCESS_FAILED')
            return report(self._job,queue_report(request,infrastructure_error=code),failure_kind=kind)

    def failure_report(self, request, code):
        return report(self._job,queue_report(request,infrastructure_error=code),failure_kind='transient')


if __name__=='__main__':
    # No real daemon, SDK/auth startup or network approval in A6.4d-1.
    require_real_transport()
