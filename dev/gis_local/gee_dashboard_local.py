"""Operator for GEE Dashboard processing (scope 2.1.15, migration 048) on the local T0.

  probe   048 + rolled-back lifecycle on both local databases; ledger stays at 47.
  migrate 048 for real, only after a matching probe and an approval file you write.
  worker  start the host worker (real Google Earth Engine via the Dashboard backend).

Uses the existing attested local operator (gee_genuine_local -> ... -> T0 runtime) for
runtime proof, SQL transport and local Auth keys. Never reads green-area-backend/.env:
the worker process loads it itself through the unchanged backend modules. Output lives
outside the repository under <runtime root>/a6-dashboard/.
"""
import argparse
import hashlib
import importlib.util
import json
import logging
import os
from pathlib import Path
import secrets
import signal
import subprocess
import sys
import threading
import time
from uuid import uuid4

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
spec = importlib.util.spec_from_file_location('a6_dashboard_genuine', HERE / 'gee_genuine_local.py')
g = importlib.util.module_from_spec(spec); sys.modules[spec.name] = g; spec.loader.exec_module(g)
REPO = g.REPO
DATABASES = g.DATABASES
MIGRATION = REPO / 'green-area-backend/migrations/048_gis_gee_dashboard_processing.sql'
LIFECYCLE = HERE / 'gee_dashboard_lifecycle.sql'
WORKER = REPO / 'green-area-backend/gis_worker/gee_dashboard_worker.py'
APPROVAL = 'local_apply_048_after_rollback_probe'
HOST_URL = 'http://127.0.0.1:55421'
ENV_KEYS = {'PATH', 'SYSTEMROOT', 'SYSTEMDRIVE', 'TEMP', 'TMP', 'LOCALAPPDATA', 'APPDATA', 'USERPROFILE',
    'HOMEDRIVE', 'HOMEPATH', 'COMSPEC', 'PATHEXT', 'PROGRAMFILES', 'PROGRAMFILES(X86)', 'PROGRAMW6432',
    'WINDIR', 'NUMBER_OF_PROCESSORS', 'PROCESSOR_ARCHITECTURE', 'HOME'}


def worker_env(service_key, source=None):
    """Worker environment: the Dashboard backend's Supabase client must be the local T0.

    The backend's load_dotenv() does not override variables that are already set, so
    these two values keep the Cloud project named in green-area-backend/.env out of reach
    while GEE_PROJECT still comes from that file.
    """
    if not isinstance(service_key, str) or not service_key:
        raise RuntimeError('WORKER_LOCAL_KEY_REQUIRED')
    env = {k: v for k, v in (os.environ if source is None else source).items() if k.upper() in ENV_KEYS}
    env['SUPABASE_URL'] = HOST_URL
    env['SUPABASE_KEY'] = service_key
    return env


def _t1():
    return g.p.p.p.p.p.m.t2.t1


class DashboardLocal(g.GenuineLocal):
    def __init__(self, root):
        super().__init__(root)
        self.output = self.db.runtime.root / 'a6-dashboard'
        self.output.mkdir(exist_ok=True)

    def proof(self, *, allow=(47, 48)):
        self.attest()
        for db in DATABASES:
            self.db.proof(db, stage='gis')
            state = self.sql("SELECT jsonb_build_object('gate',(SELECT activation_enabled FROM gis.environment),"
                "'ledger',(SELECT jsonb_agg(to_jsonb(t) ORDER BY version) FROM gis.schema_migrations t))", db, read_only=True)
            versions = [r['version'] for r in state['ledger']]
            if state['gate'] is not False or versions not in [list(range(27, top + 1)) for top in allow]:
                raise RuntimeError('GEE_DASHBOARD_LOCAL_BASELINE_REQUIRED')
            for row in state['ledger']:
                path = next((REPO / 'green-area-backend/migrations').glob(f"{row['version']:03d}_*.sql"))
                if hashlib.sha256(path.read_bytes()).hexdigest() != row['sha256']:
                    raise RuntimeError('APPLIED_CHECKSUM_DRIFT_FORWARD_MIGRATION_REQUIRED')
        return {'local_only': True, 'both_databases_verified': True, 'gate_closed': True, 'ledger_source_match': True}

    def _prelude(self, db):
        users = self.sql("SELECT jsonb_build_object('actor',(SELECT user_id FROM gis.officers ORDER BY user_id LIMIT 1),"
            "'worker',(SELECT id FROM public.profiles WHERE id NOT IN (SELECT user_id FROM gis.officers) ORDER BY id LIMIT 1),"
            "'province',(SELECT name_en FROM public.provinces ORDER BY name_en LIMIT 1),"
            "'busy',(SELECT count(*) FROM gis.jobs WHERE state IN ('queued','running')))", db, read_only=True)
        if not users['actor'] or not users['worker'] or not users['province']:
            raise RuntimeError('LOCAL_SYNTHETIC_USERS_REQUIRED')
        if users['busy']:
            raise RuntimeError('GEE_DASHBOARD_PROBE_REQUIRES_IDLE_QUEUE')
        q = _t1().literal
        return ("SELECT set_config('t.actor'," + q(users['actor']) + ",true),set_config('t.worker'," + q(users['worker'])
            + ",true),set_config('t.province'," + q(users['province']) + ",true);")

    def run_048(self, *, probe):
        self.proof(allow=(47,) if probe else (47, 48))
        sha = hashlib.sha256(MIGRATION.read_bytes()).hexdigest()
        q = _t1().literal
        prior = {db: self.sql('SELECT to_jsonb(sha256) FROM gis.schema_migrations WHERE version=48', db, read_only=True)
            for db in DATABASES}
        if any(old is not None and old != sha for old in prior.values()):
            raise RuntimeError('APPLIED_CHECKSUM_DRIFT_FORWARD_MIGRATION_REQUIRED')
        results = {}
        for db, old in prior.items():
            if old is not None:
                results[db] = 'already_applied'
                continue
            self.db.proof(db, stage='gis')
            body = "BEGIN;SET LOCAL lock_timeout='5s';SET LOCAL statement_timeout='60s';"
            body += "SELECT set_config('gis.runtime_instance'," + q(self.db.instance) + ",true);"
            body += "SELECT set_config('gis.baseline_fingerprint'," + q(_t1().legacy_fingerprint()) + ",true);"
            body += MIGRATION.read_text(encoding='utf-8')
            body += "\nSET LOCAL ROLE gis_owner;INSERT INTO gis.schema_migrations(version,sha256) VALUES(48," + q(sha) + ");RESET ROLE;"
            if probe:
                body += self._prelude(db) + LIFECYCLE.read_text(encoding='utf-8') + "\nSET CONSTRAINTS ALL IMMEDIATE;ROLLBACK;"
            else:
                body += "COMMIT;"
            self.db.transport(db, body)
            results[db] = 'rolled_back_lifecycle' if probe else 'applied'
        record = {'sha256': sha, 'lifecycle_sha256': hashlib.sha256(LIFECYCLE.read_bytes()).hexdigest(),
            'runtime_instance': self.db.instance, 'databases': results}
        (self.output / ('probe.json' if probe else 'migration-048.json')).write_text(json.dumps(record, indent=2), encoding='utf-8')
        return record

    def migrate(self, approval):
        sha = hashlib.sha256(MIGRATION.read_bytes()).hexdigest()
        value = json.loads(Path(approval).read_text(encoding='utf-8'))
        if value != {'approval': APPROVAL, 'migration_sha256': sha}:
            raise RuntimeError('GEE_DASHBOARD_APPROVAL_REQUIRED')
        probe = json.loads((self.output / 'probe.json').read_text(encoding='utf-8'))
        if (probe.get('sha256') != sha or probe.get('runtime_instance') != self.db.instance
            or probe.get('databases') != {db: 'rolled_back_lifecycle' for db in DATABASES}):
            raise RuntimeError('GEE_DASHBOARD_ROLLBACK_PROOF_REQUIRED')
        return self.run_048(probe=False)

    def provision_worker(self):
        """One new local Auth worker account (gis_native_worker); secrets stay in memory."""
        self.attest()
        anon, service = self.local_keys()
        admin = self.client(service)
        email = 'gis-gee-dashboard-worker-' + uuid4().hex + '@example.invalid'
        password = secrets.token_urlsafe(30)
        created = admin.auth.admin.create_user({'email': email, 'password': password, 'email_confirm': True,
            'role': 'gis_native_worker', 'user_metadata': {'display_name': 'GEE Dashboard worker'}})
        subject = str(created.user.id)
        session = self.client(anon).auth.sign_in_with_password({'email': email, 'password': password}).session
        if session is None:
            raise RuntimeError('WORKER_SIGNIN_FAILED')
        return {'api_url': HOST_URL, 'subject': subject, 'anon_key': anon, 'access_token': session.access_token,
            'refresh_token': session.refresh_token, 'runtime_instance': self.db.instance,
            'baseline_fingerprint': _t1().legacy_fingerprint()}

    def worker(self):
        self.proof(allow=(48, 49, 50, 51))
        bootstrap = self.provision_worker()
        env = worker_env(self.local_keys()[1])
        flags = getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)
        proc = subprocess.Popen([sys.executable, '-I', '-B', str(WORKER)], cwd=str(WORKER.parents[1]),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env, creationflags=flags)
        proc.stdin.write((json.dumps(bootstrap) + '\n').encode())
        proc.stdin.close()
        del bootstrap
        log = self.output / ('worker-' + time.strftime('%Y%m%d-%H%M%S') + '.jsonl')
        print(json.dumps({'worker_started': True, 'events_log': str(log), 'stop': 'Ctrl+C'}), flush=True)
        def pump():
            with log.open('a', encoding='utf-8') as out:
                for raw in proc.stdout:
                    line = raw.decode('utf-8', 'replace').strip()
                    try:
                        item = json.loads(line)
                        if not isinstance(item, dict) or set(item) - {'event', 'job_id', 'state', 'error_code'}:
                            raise ValueError()
                    except ValueError:
                        item = {'event': 'unrecognised_output'}
                    out.write(json.dumps(item) + '\n'); out.flush()
                    print(json.dumps(item), flush=True)
        reader = threading.Thread(target=pump, daemon=True)
        reader.start()
        try:
            while proc.poll() is None:
                time.sleep(.5)
        except KeyboardInterrupt:
            if hasattr(signal, 'CTRL_BREAK_EVENT'):
                proc.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                proc.send_signal(signal.SIGINT)
            try:
                proc.wait(timeout=60)
            except subprocess.TimeoutExpired:
                proc.kill()
        reader.join(5)
        return {'worker_exit': proc.returncode}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('proof', 'probe', 'migrate', 'worker'))
    parser.add_argument('--runtime-dir', type=Path, required=True)
    parser.add_argument('--approval', type=Path)
    args = parser.parse_args()
    for name in ('httpx', 'httpcore', 'postgrest', 'supabase_auth', 'gotrue'):
        logging.getLogger(name).setLevel(logging.CRITICAL)
    local = DashboardLocal(args.runtime_dir)
    if args.action == 'proof':
        value = local.proof()
    elif args.action == 'probe':
        value = local.run_048(probe=True)
    elif args.action == 'migrate':
        value = local.migrate(args.approval)
    else:
        value = local.worker()
    print(json.dumps(value))
