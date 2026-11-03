"""Fixed Linux entrypoint; Native child never receives database credentials."""
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
    # New artifact files retain the existing 20MiB file limit; stdout stays16KiB.
    resource.setrlimit(resource.RLIMIT_FSIZE, (20 * 1024**2, 20 * 1024**2))
    os.environ.update(PROJ_NETWORK='OFF', GDAL_HTTP_TIMEOUT='1', CPL_VSIL_CURL_ALLOWED_EXTENSIONS='',
        OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1', GDAL_NUM_THREADS='1')
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from gis_worker.ldd_prepare_provider import check_request, prepare, verify, failure
    raw = sys.stdin.buffer.read(65537)
    if len(raw) > 65536:
        return 65
    try:
        request = check_request(json.loads(raw))
    except Exception:
        return 65
    try:
        result = verify(request) if sys.argv[1:] == ['--verify'] else prepare(request)
    except MemoryError:
        result = failure(request, 'NATIVE_MEMORY_LIMIT')
    except Exception as error:
        from gis_worker.ldd_provider import LddError
        code = str(error) if isinstance(error, LddError) else 'PREPARE_FILE_UNAVAILABLE' if isinstance(error, OSError) else 'NATIVE_PROCESS_FAILED'
        result = failure(request, code)
    output = json.dumps(result, allow_nan=False, separators=(',', ':'))
    if len(output.encode()) > 16384:
        return 65
    sys.stdout.write(output)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
