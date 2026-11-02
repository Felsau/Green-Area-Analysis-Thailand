"""Fixed isolated native entrypoint for immutable local LDD ZIP validation."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys


def main():
    if sys.platform != 'linux':
        return 70
    import resource
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_AS, (512 * 1024**2, 512 * 1024**2))
    resource.setrlimit(resource.RLIMIT_CPU, (20, 20))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    resource.setrlimit(resource.RLIMIT_FSIZE, (16384, 16384))
    os.environ['OPENBLAS_NUM_THREADS'] = '1'
    os.environ['OMP_NUM_THREADS'] = '1'
    os.environ['GDAL_NUM_THREADS'] = '1'
    os.environ['PROJ_NETWORK'] = 'OFF'
    os.environ['GDAL_HTTP_TIMEOUT'] = '1'
    os.environ['CPL_VSIL_CURL_ALLOWED_EXTENSIONS'] = ''
    root = Path(__file__).resolve().parent
    sys.path.insert(0, str(root.parent))
    from gis_worker.ldd_provider import check_request, validate, report_failure
    raw = sys.stdin.buffer.read(65537)
    if len(raw) > 65536:
        return 65
    try:
        request = check_request(json.loads(raw))
    except (ValueError, KeyError, TypeError):
        return 65
    try:
        result = validate(request)
    except MemoryError:
        result = report_failure(request, 'NATIVE_MEMORY_LIMIT')
    except Exception:
        result = report_failure(request, 'NATIVE_PROCESS_FAILED')
    sys.stdout.write(json.dumps(result, allow_nan=False, separators=(',', ':')))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
