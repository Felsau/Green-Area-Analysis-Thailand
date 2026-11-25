"""C13 (week 4): memory and time of the real LDD validator (gis_worker.ldd_provider.assess) and of
ldd_prepare_provider.build on large real packages, one province per child process, measured with psutil.

Only these five caps are raised, and only inside the child process (module attributes, nothing on disk changes):
MAX_ZIP_BYTES, MAX_EXPANDED_BYTES, MAX_MEMBER_BYTES, MAX_FEATURES, MAX_COORDINATES. Any other limit the validator
hits is reported by its code. The package is hard-linked into a temporary storage_root as <sha256>.zip, the name
_source_bytes reads. The parent samples the child's working set every 0.1 s and kills it above half of the RAM.

ldd_provider._coordinates is wrapped (same function, same arguments) only to add up what the validator counted.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
RAISED = 4 * 1024**3


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def source_crs(zip_path: Path, backend: Path, c12_dir: Path, c9_dir: Path) -> str:
    sys.path[:0] = [str(backend), str(c12_dir), str(c9_dir)]
    from gis_worker import ldd_policy as policy
    import c9_hdx_check as c9
    import c12_ocha_simplify as c12
    _, _, _, prj = c12.package_layer(zip_path, None, policy, c9)
    crs, err = c12.source_crs_of(prj, policy)
    if err:
        raise SystemExit(f'STOP: {zip_path.name} {err}')
    return crs


def child(mode: str, request_path: str, store: str, backend: str) -> None:
    import psutil
    sys.path.insert(0, backend)
    from gis_worker import ldd_provider as ldd
    request = json.loads(Path(request_path).read_text(encoding='utf-8'))
    for k in ('MAX_EXPANDED_BYTES', 'MAX_MEMBER_BYTES', 'MAX_FEATURES', 'MAX_COORDINATES'):
        setattr(ldd, k, RAISED)
    # _source_bytes reads with stream.read(MAX_ZIP_BYTES + 1), which allocates that many bytes up front: the cap is
    # set to the package size exactly, so the measurement does not include a buffer the real 20 MiB cap would not make.
    ldd.MAX_ZIP_BYTES = request['manifest']['byte_size']
    counted = {'n': 0}
    orig = ldd._coordinates

    def counting(value, depth=0):
        r = orig(value, depth)
        if depth == 0:
            counted['n'] += r
        return r
    ldd._coordinates = counting
    me = psutil.Process()
    t = time.perf_counter()
    out = {'mode': mode}
    if mode == 'assess':
        report, details = ldd.assess(request, storage_root=Path(store), collect=True)
        errs = sorted(report['errors'], key=lambda e: -e['count'])
        out.update(valid=report['valid'], error_code=report.get('error_code'), errors_top5=errs[:5],
                   errors_total=len(errs), warnings=report['warnings'][:8], checks=report['checks'],
                   feature_count=report['statistics']['feature_count'], coordinates=counted['n'],
                   outcomes=details['feature_outcomes'], boundary=details['boundary'],
                   boundary_source=details['boundary_source'])
    else:
        from gis_worker import ldd_prepare_provider as prep
        prep.ldd = ldd
        req = {'validation': request, 'dataset_id': str(uuid.uuid4()), 'edition_id': str(uuid.uuid4()),
               'validation_result_id': str(uuid.uuid4()), 'job_id': str(uuid.uuid4()), 'method_version': prep.METHOD_V2}
        try:
            outputs = prep.build(req, source_root=Path(store))
            out.update(built=True, artifacts={k: len(v) for k, v in outputs.items()},
                       artifact_limit=prep.MAX_ARTIFACT, coordinates=counted['n'])
        except ldd.LddError as exc:
            out.update(built=False, error_code=str(exc), coordinates=counted['n'])
    wall = time.perf_counter() - t
    mi, ct = me.memory_info(), me.cpu_times()
    out.update(wall_s=round(wall, 2), cpu_user_s=round(ct.user, 2), cpu_system_s=round(ct.system, 2),
               cpu_s=round(ct.user + ct.system, 2), peak_wset_mb=round(mi.peak_wset / 1024**2, 1),
               peak_pagefile_mb=round(mi.peak_pagefile / 1024**2, 1))
    print('RESULT ' + json.dumps(out, ensure_ascii=False), flush=True)


def run_child(mode, request_path, store, backend, limit_bytes):
    import psutil
    cmd = [sys.executable, '-I', '-B', __file__, 'child', mode, str(request_path), str(store), str(backend)]
    t = time.perf_counter()
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    ps = psutil.Process(p.pid)   # a venv python.exe on Windows is a launcher: the work runs in its child
    max_seen, killed = 0, None
    while p.poll() is None:
        try:
            tree = [ps] + ps.children(recursive=True)
            ws = max(q.memory_info().wset for q in tree)
            max_seen = max(max_seen, ws)
            if ws > limit_bytes:
                killed = f'เกิน {limit_bytes / 1024**3:.1f} GB'
                for q in reversed(tree):
                    q.kill()
                break
        except psutil.NoSuchProcess:
            pass
        time.sleep(0.1)
    so, se = p.communicate()
    res = {'mode': mode, 'exit': p.returncode, 'parent_wall_s': round(time.perf_counter() - t, 2),
           'sampled_max_wset_mb': round(max_seen / 1024**2, 1)}
    if killed:
        res['killed'] = killed
    line = next((l for l in so.decode('utf-8', 'replace').splitlines() if l.startswith('RESULT ')), None)
    if line:
        res.update(json.loads(line[7:]))
    else:
        res['stderr_tail'] = se.decode('utf-8', 'replace')[-600:]
    return res


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == 'child':
        child(*sys.argv[2:6])
        return 0
    import psutil
    ap = argparse.ArgumentParser()
    ap.add_argument('--backend', type=Path, required=True)
    ap.add_argument('--c12-dir', type=Path, required=True)
    ap.add_argument('--c9-dir', type=Path, required=True)
    ap.add_argument('--work', type=Path, required=True)
    ap.add_argument('--pkg', action='append', required=True, help='province|data_year|zip path')
    ap.add_argument('--out', type=Path, required=True)
    a = ap.parse_args()
    ram = psutil.virtual_memory().total
    limit = ram // 2
    store = a.work / 'store'
    store.mkdir(parents=True, exist_ok=True)
    results = []
    print(json.dumps({'ram_gb': round(ram / 1024**3, 2), 'kill_above_gb': round(limit / 1024**3, 2),
                      'python': sys.version.split()[0], 'psutil': psutil.__version__}), flush=True)
    for spec in a.pkg:
        province, year, zp = spec.split('|', 2)
        zp = Path(zp)
        digest = sha256_file(zp)
        target = store / (digest + '.zip')
        if not target.exists():
            os.link(zp, target)
        crs = source_crs(zp, a.backend, a.c12_dir, a.c9_dir)
        request = {'upload_id': str(uuid.uuid4()),
                   'manifest': {'schema_version': 1, 'provider': 'real', 'sha256': digest, 'byte_size': zp.stat().st_size,
                                'provenance': 'local-ldd-upload-v1', 'crs': crs, 'data_kind': 'polygon',
                                'attributes': ['LUL1_CODE', 'LU_CODE', 'Shape_Area']},
                   'input_hash': digest, 'input_revision': 1, 'attempt_number': 1,
                   'province': province, 'data_year': int(year), 'encoding': 'auto'}
        rp = a.work / f'request_{digest[:12]}.json'
        rp.write_text(json.dumps(request), encoding='utf-8')
        row = {'province': province, 'package': zp.name, 'bytes': zp.stat().st_size, 'sha256': digest, 'crs': crs,
               'data_year': int(year)}
        row['assess'] = run_child('assess', rp, store, a.backend, limit)
        print(json.dumps(row, ensure_ascii=False), flush=True)
        a_res = row['assess']
        other_cap = a_res.get('error_code') in ('ZIP_MEMBER_LIMIT', 'ZIP_COMPRESSION_RATIO', 'METADATA_SIZE_LIMIT',
                                                'AREA_LIMIT', 'NATIVE_MEMORY_LIMIT')
        if 'killed' in a_res or other_cap:
            row['prepare'] = {'skipped': a_res.get('killed') or a_res.get('error_code')}
        else:
            row['prepare'] = run_child('prepare', rp, store, a.backend, limit)
        print(json.dumps({'province': province, 'prepare': row['prepare']}, ensure_ascii=False), flush=True)
        results.append(row)
        a.out.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding='utf-8')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
