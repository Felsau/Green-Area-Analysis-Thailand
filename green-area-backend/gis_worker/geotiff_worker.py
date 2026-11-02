"""GeoTIFF protocol on the existing least-privilege Linux queue daemon."""
from pathlib import Path
import re
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from gis_worker.worker import GisWorker, LocalWorkerClient, WorkerError, event, main
from gis_worker.geotiff_provider import check_request, report_failure


class GeoTiffClient(LocalWorkerClient):
    RPC_NAMES = ('gis_geotiff_worker', 'gis_geotiff_readiness')


class GeoTiffWorker(GisWorker):
    CHILD_SCRIPT = 'geotiff_child.py'

    def readiness(self):
        value = self.client.call('gis_geotiff_readiness', {})
        if (not isinstance(value, dict) or value.get('status') != 'ready'
            or value.get('worker_role') != 'gis_native_worker' or value.get('subject') != self.client.subject
            or value.get('database_name') != 'postgres' or value.get('cluster_name') != 'green-area-gis-t0'
            or value.get('mode') != 'local_synthetic' or value.get('contract_version') != '1.0.0-geotiff-local'
            or not set(range(27, 37)) <= set(value.get('migration_versions', []))
            or any(value.get(k) != expected for k, expected in self.client.expected.items())):
            raise WorkerError('WORKER_TARGET_REJECTED')
        return value

    def call(self, action, payload=None):
        self.readiness()
        return self.client.call('gis_geotiff_worker', {'p_action': action, 'p_payload': payload or {}})

    def build_native_request(self, job):
        return check_request({k: job[k] for k in ('upload_id', 'manifest', 'input_hash', 'input_revision',
            'attempt_number', 'province', 'data_year')})

    def failure_report(self, request, code):
        return report_failure(request, code)


if __name__ == '__main__':
    try:
        main(GeoTiffClient, GeoTiffWorker)
    except Exception as error:
        code = str(error) if isinstance(error, WorkerError) else ''
        event('fatal', error_code=code if re.fullmatch('(?:GIS|WORKER)_[A-Z0-9_]+', code) else 'WORKER_STARTUP_FAILED')
        raise SystemExit(1)
