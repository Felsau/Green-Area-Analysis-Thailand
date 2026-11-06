"""Host worker for GIS processing requests in mode ``gee_dashboard`` (migration 048).

Runs on the operator's machine, not in the network=none containers: it must reach
Google Earth Engine and the Dashboard Supabase exactly like the Dashboard backend
does. It reuses the queue loop, heartbeat, lease fencing and shutdown handling of
``GisWorker``; only the transport target, RPC names and the compute step differ.

Bootstrap (one JSON line on stdin, from dev/gis_local/gee_dashboard_local.py): the
local GIS Auth worker JWT, as for every other worker. The Dashboard GEE project and
Supabase settings are read from green-area-backend/.env by the unchanged backend
modules (dependencies.load_dotenv / ee.Initialize); nothing here reads or prints them.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import re
import signal
import sys
import threading
import time
from urllib import error as http_error, request as http

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from gis_worker.worker import GisWorker, LocalWorkerClient, WorkerError, event  # noqa: E402
from gis_worker import gee_dashboard_provider as provider  # noqa: E402

HOST_URL = 'http://127.0.0.1:55421'
COMPUTE_TIMEOUT = 300


class HostClient(LocalWorkerClient):
    """Same identity/refresh checks as LocalWorkerClient, but the host gateway URL."""
    RPC_NAMES = ('gis_gee_dashboard_worker', 'gis_gee_dashboard_readiness')
    JWT_ROLE = 'gis_native_worker'

    def __init__(self, bootstrap):
        if not isinstance(bootstrap, dict) or bootstrap.get('api_url') != HOST_URL:
            raise WorkerError('WORKER_TARGET_REJECTED')
        # Reuse the parent's exact validation with its own expected URL, then retarget.
        super().__init__({**bootstrap, 'api_url': 'http://green-area-gis-t0-gateway:8000'})

    def _request(self, path, payload, access):
        allowed = tuple('/rest/v1/rpc/' + name for name in self.RPC_NAMES) + ('/auth/v1/token?grant_type=refresh_token',)
        if path not in allowed:
            raise WorkerError('WORKER_RPC_REJECTED')
        raw = json.dumps(payload, allow_nan=False, separators=(',', ':')).encode()
        if len(raw) > 65536:
            raise WorkerError('WORKER_REQUEST_LIMIT')
        req = http.Request(HOST_URL + path, data=raw, method='POST', headers={'apikey': self._anon,
            'Authorization': 'Bearer ' + access, 'Content-Type': 'application/json'})
        try:
            with self._opener.open(req, timeout=10) as r:
                value = r.read(65537)
            if len(value) > 65536:
                raise WorkerError('WORKER_RESPONSE_LIMIT')
            return json.loads(value)
        except http_error.HTTPError as e:
            try:
                code = json.loads(e.read(2048)).get('message', '')
            except Exception:
                code = ''
            raise WorkerError(code if re.fullmatch('GIS_[A-Z0-9_]+', code) else 'WORKER_HTTP_DENIED') from None
        except WorkerError:
            raise
        except (OSError, ValueError):
            raise WorkerError('WORKER_TRANSPORT_FAILED') from None


class GeeDashboardWorker(GisWorker):
    def __init__(self, client, *, endpoints):
        super().__init__(client)
        self.endpoints = endpoints

    def readiness(self):
        r = self.client.call('gis_gee_dashboard_readiness', {})
        if (not isinstance(r, dict) or r.get('status') != 'ready' or r.get('worker_role') != 'gis_native_worker'
            or r.get('protocol') != 'gee_dashboard' or r.get('contract_version') != '1.0.0-gee-dashboard'
            or r.get('subject') != self.client.subject or r.get('database_name') != 'postgres'
            or r.get('cluster_name') != 'green-area-gis-t0' or 48 not in r.get('migration_versions', [])
            or any(r.get(k) != v for k, v in self.client.expected.items())):
            raise WorkerError('WORKER_TARGET_REJECTED')
        return r

    def call(self, action, payload=None):
        self.readiness()
        return self.client.call('gis_gee_dashboard_worker', {'p_action': action, 'p_payload': payload or {}})

    def build_native_request(self, job):
        return provider.check_request({k: job[k] for k in provider.REQUEST_KEYS})

    def failure_report(self, request, code):
        return provider.report_failure(request, code)

    def _execute_native(self, request, timeout=COMPUTE_TIMEOUT):
        """In-process compute on a helper thread so lease loss/shutdown stay observable.

        A GEE call cannot be cancelled mid-flight; on timeout/shutdown the job is failed
        as transient and the daemon thread's eventual result is discarded.
        """
        box = {}

        def run():
            try:
                box['report'] = provider.compute(request, self.endpoints)
            except Exception:
                box['report'] = provider.report_failure(request, provider.TRANSIENT)
        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        deadline = time.monotonic() + timeout
        while thread.is_alive():
            if self._lease_lost.is_set():
                raise WorkerError('GIS_STALE_LEASE')
            if self._stop_event.is_set():
                return provider.report_failure(request, 'WORKER_SHUTDOWN')
            if time.monotonic() >= deadline:
                return provider.report_failure(request, 'NATIVE_TIMEOUT')
            thread.join(.2)
        return box['report']


def initialize_backend():
    """Load the unchanged Dashboard backend exactly as main.py does (no secrets echoed).

    Backend log lines go to stderr only; stdout carries the fixed JSON worker events.
    """
    import logging
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING, force=True)
    import dependencies  # noqa: F401  (load_dotenv + Supabase settings)
    import ee
    project = os.getenv('GEE_PROJECT')
    if not project:
        raise WorkerError('WORKER_GEE_PROJECT_MISSING')
    try:
        ee.Initialize(project=project)
    except Exception:
        raise WorkerError('WORKER_GEE_INIT_FAILED') from None
    return provider.LegacyEndpoints()


def main():
    raw = sys.stdin.buffer.readline(32769)
    if len(raw) > 32768 or not raw.endswith(b'\n'):
        raise WorkerError('WORKER_BOOTSTRAP_REJECTED')
    client = HostClient(json.loads(raw))
    del raw
    worker = GeeDashboardWorker(client, endpoints=initialize_backend())
    signal.signal(signal.SIGINT, worker.stop)
    if hasattr(signal, 'SIGTERM'):
        signal.signal(signal.SIGTERM, worker.stop)
    if hasattr(signal, 'SIGBREAK'):
        signal.signal(signal.SIGBREAK, worker.stop)
    worker.run()


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        code = str(error) if isinstance(error, WorkerError) else ''
        event('fatal', error_code=code if re.fullmatch('(?:GIS|WORKER)_[A-Z0-9_]+', code) else 'WORKER_STARTUP_FAILED')
        raise SystemExit(1)
