"""Separate offline processing protocol; reuses the existing Linux queue daemon."""
from pathlib import Path
import re
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from gis_worker.worker import GisWorker, LocalWorkerClient, WorkerError, event, main
from gis_worker.processing_provider import check_request, report_failure

class ProcessingClient(LocalWorkerClient):
    RPC_NAMES = ('gis_processing_worker','gis_processing_readiness')

class ProcessingWorker(GisWorker):
    CHILD_SCRIPT = 'processing_child.py'

    def readiness(self):
        result = self.client.call('gis_processing_readiness', {})
        if (not isinstance(result, dict) or result.get('status') != 'ready'
            or result.get('worker_role') != 'gis_native_worker' or result.get('subject') != self.client.subject
            or result.get('database_name') != 'postgres' or result.get('cluster_name') != 'green-area-gis-t0'
            or result.get('mode') != 'local_synthetic' or result.get('contract_version') != '1.0.0-processing-offline'
            or not set(range(27,36)) <= set(result.get('migration_versions', []))
            or any(result.get(k) != value for k, value in self.client.expected.items())):
            raise WorkerError('WORKER_TARGET_REJECTED')
        return result

    def call(self, action, payload=None):
        self.readiness()
        return self.client.call('gis_processing_worker', {'p_action':action, 'p_payload':payload or {}})

    def build_native_request(self, job):
        return check_request({k:job[k] for k in ('processing_id','manifest','input_hash','input_revision','attempt_number')})

    def failure_report(self, request, code):
        return report_failure(request, code)

if __name__ == '__main__':
    try:
        main(ProcessingClient,ProcessingWorker)
    except Exception as error:
        code = str(error) if isinstance(error,WorkerError) else ''
        event('fatal', error_code=code if re.fullmatch('(?:GIS|WORKER)_[A-Z0-9_]+',code) else 'WORKER_STARTUP_FAILED')
        raise SystemExit(1)
