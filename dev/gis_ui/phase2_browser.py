"""T4 browser -> local Auth/API -> existing Linux worker smoke.

Uses only the already-attested T0 instance and in-memory synthetic credentials.
No host .env, signing secret, migration, cloud or pre-existing user modification.
Requires the bundled Playwright package and installed Chrome. Retains test rows.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import logging
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
from uuid import uuid4

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
spec = importlib.util.spec_from_file_location('t4_local_operator', HERE / 'phase2_local.py')
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)
sys.path.insert(0, str(REPO / 'green-area-backend'))
from gis_app import create_app
from gis_worker.provider import fixture_manifest
import uvicorn


def unused_port(port):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', port))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime-dir', type=Path, required=True)
    parser.add_argument('--node-modules', type=Path, required=True)
    parser.add_argument('--authorization-only', action='store_true')
    args = parser.parse_args()
    logging.disable(logging.CRITICAL)
    local = m.Phase2Local(args.runtime_dir).prepare()
    local.attest()
    if m.m.fingerprint()['branch'] != m.m.GIS_BRANCH:
        raise RuntimeError('WRONG_BRANCH')
    unused_port(3000)
    unused_port(55422)
    if local.sql("SELECT to_jsonb(count(*)) FROM gis.jobs WHERE state IN ('queued','running')", read_only=True) != 0:
        raise RuntimeError('REQUIRES_IDLE_SYNTHETIC_QUEUE')
    before = local.baseline()
    backend = m.m.fingerprint()
    run = uuid4().hex[:10]
    output = local.db.runtime.root / 'phase2-browser' / run
    output.mkdir(parents=True)
    anon, service = local.local_keys()  # existing attested local operator; never printed
    operator = local.client(service)
    users = {}
    for name in ('admin', 'officer', 'normal'):
        email = 'gis-p2-'  + name + '-' + run + '@example.invalid'
        password = secrets.token_urlsafe(30)
        created = operator.auth.admin.create_user({'email': email, 'password': password, 'email_confirm': True,
            'user_metadata': {'display_name': 'T4 ' + name}})
        users[name] = {'id': str(created.user.id), 'email': email, 'password': password, 'name': name}
    # Only this newly-created fixture is elevated; no existing account is changed.
    admin_id = m.m.t2.t1.literal(users['admin']['id'])
    local.sql("UPDATE public.profiles SET role='admin' WHERE id=" + admin_id + "::uuid AND role='user'", role='postgres')
    options = local.sql("SELECT jsonb_build_object('province','Bangkok Metropolis',"
        "'used',(SELECT COALESCE(jsonb_agg(data_year),'[]'::jsonb) FROM gis.datasets WHERE kind='ldd_shapefile' "
        "AND province='Bangkok Metropolis'))", read_only=True)
    year = next(y for y in range(1980, 2027) if y not in options['used'])
    worker = server = vite = None
    smoke_code = None
    try:
        if not args.authorization_only:
            worker = m.LddContainer(local)
            m.m.wait_for(lambda: worker.has('ready') or worker.has('fatal'), 30)
            if not worker.has('ready'):
                raise RuntimeError('WORKER_NOT_READY')
        server = uvicorn.Server(uvicorn.Config(create_app(local.gis_runtime, ldd_store=local.store), host='127.0.0.1', port=55422,
            log_level='critical', access_log=False))
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        m.m.wait_for(lambda: server.started, 15)
        env = {k: v for k, v in os.environ.items() if k.upper() in {'PATH','SYSTEMROOT','SYSTEMDRIVE','TEMP','TMP','LOCALAPPDATA','APPDATA','USERPROFILE','COMSPEC','PATHEXT','PROGRAMFILES','PROGRAMFILES(X86)','PROGRAMW6432'}}
        env.update(GIS_UI_LOCAL='true', GIS_UI_LOCAL_ANON_KEY=anon, GIS_TEST_NODE_MODULES=str(args.node_modules))
        node = shutil.which('node')
        if not node:
            raise RuntimeError('NODE_UNAVAILABLE')
        vite = subprocess.Popen([node, str(REPO / 'green-area-frontend/node_modules/vite/bin/vite.js'),
            '--config', str(HERE / 'vite.config.mjs')], cwd=REPO / 'green-area-frontend', env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        def frontend_ready():
            if vite.poll() is not None:
                raise RuntimeError('FRONTEND_START_FAILED')
            try:
                with socket.create_connection(('127.0.0.1', 3000), timeout=.5):
                    return True
            except OSError:
                return False
        m.m.wait_for(frontend_ready, 30)
        payload = {'users': users, 'title': 'Phase2 Synthetic Upload ' + run, 'year': year, 'province': 'Bangkok Metropolis',
            'authorizationOnly': args.authorization_only, 'fixture': str(REPO / 'green-area-backend/gis_worker/fixtures/ldd_valid.zip'), 'invalid_fixture': str(REPO / 'green-area-backend/gis_worker/fixtures/ldd_unknown.zip'), 'output': str(output)}
        proc = subprocess.Popen([node, str(HERE / 'phase2_browser.cjs')], cwd=REPO, env=env,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding='utf-8')
        try:
            stdout, _ = proc.communicate(json.dumps(payload) + '\n', timeout=480)
            smoke_code = proc.returncode
            # Runner emits fixed case names only, never browser exceptions/inputs.
            for line in stdout.splitlines():
                row = json.loads(line)
                if set(row) <= {'rows', 'code', 'step'}:
                    print(json.dumps(row), flush=True)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            smoke_code = 2
    finally:
        if vite is not None:
            vite.terminate()
            vite.wait(timeout=15)
        if server is not None:
            server.should_exit = True
            thread.join(timeout=15)
        if worker is not None:
            worker.close()
        after = local.baseline()
        checks = {}
        for database in before:
            a, b = before[database], after[database]
            checks[database] = {
                'ledger_unchanged': a['ledger'] == b['ledger'],
                'old_profiles_unchanged': all(b['profiles'].get(k) == v for k, v in a['profiles'].items()),
                'legacy_nonprofile_unchanged': all(b['tables'].get(k) == v for k, v in a['tables'].items() if k != 'profiles'),
            }
        checks['backend_source_unchanged'] = backend == m.m.fingerprint()
        checks['owned_worker_removed'] = not local.approved
        checks['queue_idle'] = local.sql("SELECT to_jsonb(count(*)) FROM gis.jobs WHERE state IN ('queued','running')", read_only=True) == 0
        source = {}
        for p in sorted((REPO / 'green-area-frontend/src').rglob('*')):
            if p.is_file() and (p.suffix in ('.js', '.css')):
                source[p.relative_to(REPO).as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
        for p in HERE.iterdir():
            if p.is_file():
                source[p.relative_to(REPO).as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
        report = {'run': run, 'smoke_exit': smoke_code, 'branch': backend['branch'], 'head': backend['head'],
            'checks': checks, 'source': source, 'source_sha256': hashlib.sha256(json.dumps(source, sort_keys=True).encode()).hexdigest(),
            'cleanup': 'owned worker/API/Vite stopped; four existing core containers left running; new synthetic rows retained'}
        (output / 'local-results.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(json.dumps({'evidence': str(output), 'smoke_exit': smoke_code, 'checks': checks}), flush=True)
    return smoke_code or 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception:
        print(json.dumps({'ok': False, 'code': 'T4_LOCAL_SMOKE_FAILED'}))
        sys.exit(1)
