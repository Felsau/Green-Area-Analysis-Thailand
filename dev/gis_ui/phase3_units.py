"""Isolated local Phase 2 unit checks; no dotenv or nonlocal sockets."""
import argparse
import json
import os
from pathlib import Path
import socket
import sys
from unittest.mock import patch
from uuid import uuid4

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--runtime-dir', type=Path, required=True)
    args = p.parse_args()
    repo = Path(__file__).resolve().parents[2]
    owner = json.loads((args.runtime_dir / 'owner.json').read_text())
    if owner.get('scope') != 'gis-foundation-t0':
        raise RuntimeError('LOCAL_OWNER_REQUIRED')
    output = args.runtime_dir / 'phase3'
    output.mkdir(exist_ok=True)
    clean = {k: v for k, v in os.environ.items() if k.upper() in {'PATH','SYSTEMROOT','SYSTEMDRIVE','TEMP','TMP','COMSPEC','WINDIR','PATHEXT'}}
    os.environ.clear()
    os.environ.update(clean, PYTEST_DISABLE_PLUGIN_AUTOLOAD='1')
    os.environ['USERPROFILE'] = str(output)
    sys.path.insert(0, str(repo / 'green-area-backend'))
    import pytest
    class Results:
        rows = []
        def pytest_runtest_logreport(self, report):
            if report.when == 'call' or report.failed:
                self.rows.append({'case': report.nodeid, 'outcome': report.outcome})
    results = Results()
    original = socket.socket.connect
    def loopback(sock, address):
        if isinstance(address, tuple) and address[0] not in ('127.0.0.1', '::1'):
            raise RuntimeError('NONLOCAL_NETWORK_DENIED')
        return original(sock, address)
    files = ['green-area-backend/tests/test_processing_api.py', 'green-area-backend/tests/test_processing_provider.py', 'dev/gis_local/tests/test_processing_worker_guard.py', 'green-area-backend/tests/test_gis_api_unit.py', 'green-area-backend/tests/test_gis_runtime_unit.py', 'green-area-backend/tests/test_ldd_upload_api.py', 'green-area-backend/tests/test_gis_worker_unit.py',
        'dev/gis_local/tests/test_ldd_worker_guard.py', 'dev/gis_local/tests/test_t3_worker_guard.py']
    with patch('dotenv.load_dotenv', return_value=False), patch.object(socket.socket, 'connect', loopback):
        result = pytest.main(['-q', '-p', 'no:cacheprovider', '--basetemp', str(output / ('unit-temp-' + uuid4().hex)),
            *[str(repo / f) for f in files]], plugins=[results])
    (output / 'unit-tests.json').write_text(json.dumps({'cases': results.rows,
        'counts': {k: sum(x['outcome'] == k for x in results.rows) for k in ('passed','failed','skipped')},
        'dotenv_suppressed': True, 'nonlocal_network_denied': True}, indent=2))
    return result

if __name__ == '__main__':
    sys.exit(main())
