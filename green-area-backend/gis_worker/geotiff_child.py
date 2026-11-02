"""Credential-free, resource-limited Linux GeoTIFF validation entrypoint."""
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
    os.environ.update(OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1', GDAL_NUM_THREADS='1',
        PROJ_NETWORK='OFF', GDAL_HTTP_TIMEOUT='1', CPL_VSIL_CURL_ALLOWED_EXTENSIONS='',
        GDAL_PAM_ENABLED='NO', GDAL_DISABLE_READDIR_ON_OPEN='EMPTY_DIR')
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from gis_worker.geotiff_provider import check_request, report_failure, validate
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
