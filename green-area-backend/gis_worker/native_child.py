"""Fixed Linux native subprocess entrypoint: bounded stdin, no inherited secrets.

Invoke absolute script with Python -I -B. Parent supplies clean env/closed FDs,
wall timeout and aggregate cgroup limits; this child adds per-process rlimits.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys


def main() -> int:
    if sys.platform != "linux":
        return 70
    import resource
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_AS, (512 * 1024**2, 512 * 1024**2))
    resource.setrlimit(resource.RLIMIT_CPU, (20, 20))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    # stdout is a parent-owned temporary file, never an unbounded PIPE buffer.
    resource.setrlimit(resource.RLIMIT_FSIZE, (16384, 16384))
    os.environ["OPENBLAS_NUM_THREADS"] = "1"
    os.environ["OMP_NUM_THREADS"] = "1"
    os.environ["GDAL_NUM_THREADS"] = "1"
    root = Path(__file__).resolve().parent
    sys.path.insert(0, str(root.parent))
    from gis_worker.provider import load_registry, _check_request, validate, report_failure
    raw = sys.stdin.buffer.read(65537)
    if len(raw) > 65536:
        return 65
    try:
        request = json.loads(raw)
        entry = _check_request(request, load_registry())
    except (ValueError, KeyError, TypeError):
        return 65
    try:
        if entry["behavior"] == "timeout":
            import time
            time.sleep(3600)
        if entry["behavior"] == "oom":
            bytearray(1024 * 1024**2)
        if entry["behavior"] == "transient" and request["attempt_number"] == 1:
            result = report_failure(request, "TRANSIENT_SYNTHETIC")
        else:
            result = validate(request)
    except MemoryError:
        result = report_failure(request, "NATIVE_MEMORY_LIMIT")
    except Exception:
        # No raw exception, path, environment, input or native stderr in reports.
        result = report_failure(request, "NATIVE_PROCESS_FAILED")
    sys.stdout.write(json.dumps(result, allow_nan=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
