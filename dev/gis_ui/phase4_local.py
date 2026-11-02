"""Attested Local GeoTIFF operator; no dotenv, live GEE or Cloud configuration."""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import logging
from pathlib import Path
import sys
from uuid import uuid4

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
spec = importlib.util.spec_from_file_location('phase4_base', HERE / 'phase3_local.py')
p = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = p
spec.loader.exec_module(p)
m = p.m.m


class Phase4Local(p.Phase3Local):
    def __init__(self, root):
        super().__init__(root)
        self.directory = self.db.runtime.root / 'phase4'
        self.directory.mkdir(exist_ok=True)

    def check_frozen(self):
        super().check_frozen()
        applied = self.db.runtime.root / 'phase4/migration-036.json'
        if applied.exists():
            expected = json.loads(applied.read_text(encoding='utf-8'))['sha256']
            if hashlib.sha256((REPO / 'green-area-backend/migrations/036_gis_geotiff_upload.sql').read_bytes()).hexdigest() != expected:
                raise m.t2.t1.SafetyError('APPLIED_MIGRATION_FILE_CHANGED')

    def migrate(self, review_path):
        self.check_frozen()
        self.attest()
        path = REPO / 'green-area-backend/migrations/036_gis_geotiff_upload.sql'
        content = path.read_bytes()
        checksum = hashlib.sha256(content).hexdigest()
        review = json.loads(Path(review_path).read_text(encoding='utf-8'))
        if (review.get('independent_review') is not True or review.get('unresolved_high_critical') != 0
            or review.get('files') != {path.name: checksum}):
            raise m.t2.t1.SafetyError('EXACT_INDEPENDENT_REVIEW_REQUIRED')
        for database in ('postgres', 'gis_t1_upgrade'):
            self.db.proof(database, stage='gis')
            existing = self.sql('SELECT to_jsonb(sha256) FROM gis.schema_migrations WHERE version=36', database, read_only=True)
            if existing:
                if existing != checksum:
                    raise m.t2.t1.SafetyError('APPLIED_CHECKSUM_DRIFT_FORWARD_MIGRATION_REQUIRED')
                continue
            body = ("BEGIN;SET LOCAL lock_timeout='5s';SET LOCAL statement_timeout='60s';"
                + "SELECT set_config('gis.runtime_instance'," + m.t2.t1.literal(self.db.instance) + ',true);'
                + "SELECT set_config('gis.baseline_fingerprint'," + m.t2.t1.literal(m.t2.t1.legacy_fingerprint()) + ',true);'
                + content.decode('utf-8-sig')
                + "\nSET LOCAL ROLE gis_owner;INSERT INTO gis.schema_migrations(version,sha256) VALUES(36,"
                + m.t2.t1.literal(checksum) + ');RESET ROLE;COMMIT;')
            self.db.transport(database, body)
        self.write('migration-036.json', {'sha256': checksum, 'databases': ['postgres', 'gis_t1_upgrade'],
            'reviewer': review.get('reviewer'), 'forward_only': True})

    def prepare(self):
        super().prepare()
        from gis_geotiff_storage import LocalGeoTiffStore
        self.geotiff_store = LocalGeoTiffStore(self.gis_runtime, self.db.runtime.root)
        return self

    def api(self):
        from fastapi.testclient import TestClient
        from gis_app import create_app
        return TestClient(create_app(self.gis_runtime, ldd_store=self.store, geotiff_store=self.geotiff_store), base_url='http://127.0.0.1:55422')


class GeoTiffContainer(m.ContainerWorker):
    def __init__(self, local, identity=None):
        self.local = local
        self.identity = identity or m.identity_module.provision(local)
        self.events, self.errors = [], []
        run = uuid4().hex
        name = 'gis-geotiff-worker-' + run[:12]
        local.attest()
        args = ['create', '-i', '--init', '--name', name, '--entrypoint', '', '--network', 'green-area-gis-t0-internal',
            '--memory=1g', '--memory-swap=1g', '--cpus=1', '--pids-limit=64', '--read-only', '--cap-drop=ALL',
            '--security-opt=no-new-privileges:true', '--user=65534:65534',
            '--tmpfs=/tmp:rw,nosuid,noexec,size=32m,mode=1777',
            '--mount', 'type=bind,src=' + str(REPO / 'green-area-backend/gis_worker') + ',dst=/app/gis_worker,readonly',
            '--mount', 'type=bind,src=' + str(local.geotiff_store.objects) + ',dst=/data/geotiff/objects,readonly',
            '--workdir=/app/gis_worker', '--label', 'gis.phase4.scope=geotiff-worker',
            '--label', 'gis.phase4.instance=' + local.db.instance, '--label', 'gis.phase4.run=' + run,
            '--label', 'com.docker.compose.project=green-area-gis-t0',
            m.IMAGE, 'python3', '-I', '-B', '/app/gis_worker/geotiff_worker.py']
        self.cid = local.db.runtime.docker(args).strip()
        canonical = m.t2.t1.runtime_module.canonical_bind_path
        self.policy = {'name': name, 'run_id': run, 'geotiff_storage': canonical(str(local.geotiff_store.objects))}
        local.db.runtime.verify_worker(self.cid, self.policy)
        local.approved[self.cid] = self.policy
        local.attest()
        self.proc = m.subprocess.Popen(local.db.runtime.base + ['start', '-a', '-i', self.cid], stdin=m.subprocess.PIPE,
            stdout=m.subprocess.PIPE, stderr=m.subprocess.DEVNULL, cwd=local.db.runtime.root, env=local.db.runtime.env)
        i = self.identity
        bootstrap = {'api_url': 'http://green-area-gis-t0-gateway:8000', 'subject': i.subject,
            'anon_key': i.anon_key, 'access_token': i.access_token, 'refresh_token': i.refresh_token,
            'runtime_instance': local.db.instance, 'baseline_fingerprint': m.t2.t1.legacy_fingerprint()}
        self.proc.stdin.write((json.dumps(bootstrap) + '\n').encode())
        self.proc.stdin.close()
        def collect():
            while True:
                line = self.proc.stdout.readline(4097)
                if not line:
                    break
                try:
                    item = json.loads(line)
                    if set(item) - {'event','job_id','state','error_code'} or len(line) > 4096:
                        raise ValueError()
                    if len(self.events) < 512:
                        self.events.append(item)
                except Exception:
                    if len(self.errors) < 512:
                        self.errors.append('WORKER_EVENT_REJECTED')
        self.reader = m.threading.Thread(target=collect, daemon=True)
        self.reader.start()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('proof','migrate','serve'))
    parser.add_argument('--runtime-dir', type=Path, required=True)
    parser.add_argument('--review', type=Path)
    args = parser.parse_args()
    logging.disable(logging.CRITICAL)
    try:
        local = Phase4Local(args.runtime_dir)
        if args.action == 'migrate':
            local.migrate(args.review)
            print(json.dumps({'migration':36,'local_only':True}))
        elif args.action == 'proof':
            print(json.dumps(local.attest()))
        else:
            local.prepare()
            import uvicorn
            from gis_app import create_app
            uvicorn.run(create_app(local.gis_runtime, ldd_store=local.store, geotiff_store=local.geotiff_store),
                host='127.0.0.1',port=55422,access_log=False)
    except Exception:
        print(json.dumps({'ok':False,'code':'PHASE4_LOCAL_OPERATION_FAILED'}))
        raise SystemExit(1)
