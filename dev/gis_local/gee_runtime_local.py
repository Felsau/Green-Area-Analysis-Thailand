"""Reviewed Local build/probe operator. No Live startup, pulls or SDK installs."""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import threading
import time
from uuid import uuid4

HERE = Path(__file__).resolve().parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


p = load('a64d2_previous_local', HERE / 'gee_safety_local.py')
policy = load('a64d2_runtime_policy', HERE / 'gee_runtime_policy.py')
REPO = p.REPO
DOCKERFILE = HERE / 'gee_live_runtime.Dockerfile'
LOCK = HERE / 'gee-runtime-image.lock.json'
SENSITIVE = ('green-area-backend/gis_worker/gee_runtime_identity.py',
    'green-area-backend/gis_worker/gee_runtime_transport.py',
    'green-area-backend/gis_worker/gee_runtime_probe.py',
    'dev/gis_local/gee_runtime_policy.py', 'dev/gis_local/gee_runtime_local.py',
    'dev/gis_local/gee_live_runtime.Dockerfile')
BASE_TAG = 'gis-gee-mock:20261104-a63'


def source_files():
    return {path.relative_to(REPO).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted((REPO / 'green-area-backend/gis_worker').glob('*.py'))}


class RuntimeLocal(p.SafetyLocal):
    def __init__(self, root):
        super().__init__(root)
        self.output = self.db.runtime.root / 'a6-4d2-runtime'
        self.output.mkdir(exist_ok=True)

    def proof(self):
        value = super().proof()
        for database in p.p.p.DATABASES:
            sha = self.sql('SELECT to_jsonb(sha256) FROM gis.schema_migrations WHERE version=45',
                database, read_only=True)
            if sha != 'fed94e4efaf6ed2d339e0bb36f44c0dcb8bc4ef34a8d6738087fe0e888f17be8':
                raise RuntimeError('A64D2_APPLIED_045_REQUIRED')
        return value

    def migrate(self, *args, **kwargs):
        raise RuntimeError('A64D2_SQL_DDL_NOT_AUTHORIZED')

    def reviewed(self, path):
        value = json.loads(Path(path).read_text(encoding='utf-8'))
        sources = {n: hashlib.sha256((REPO / n).read_bytes()).hexdigest() for n in SENSITIVE}
        if (value.get('independent_review') is not True or value.get('unresolved_high_critical') != 0
            or value.get('source_files') != sources):
            raise RuntimeError('A64D2_EXACT_SOURCE_REVIEW_REQUIRED')
        return sources

    def build(self, review):
        self.proof()
        reviewed = self.reviewed(review)
        runtime = self.db.runtime
        base = json.loads(runtime.docker(['image', 'inspect', policy.BASE_IMAGE]))[0]
        tagged = json.loads(runtime.docker(['image', 'inspect', BASE_TAG]))[0]
        if (tagged['Id'] != policy.BASE_IMAGE or base['Id'] != policy.BASE_IMAGE
            or base['Config'].get('OnBuild') not in (None, [])):
            raise RuntimeError('A64D2_APPROVED_LOCAL_BASE_REQUIRED')
        sources = source_files()
        tree = policy.fingerprint(sources)
        context = self.output / ('context-' + uuid4().hex[:12])
        (context / 'gis_worker').mkdir(parents=True)
        for name, sha in sources.items():
            if (REPO / name).is_symlink():
                raise RuntimeError('A64D2_SYMLINK_SOURCE_REJECTED')
            raw = (REPO / name).read_bytes()
            if hashlib.sha256(raw).hexdigest() != sha:
                raise RuntimeError('A64D2_SOURCE_CHANGED_DURING_BUILD')
            (context / 'gis_worker' / Path(name).name).write_bytes(raw)
        (context / 'Dockerfile').write_bytes(DOCKERFILE.read_bytes())
        (context / 'source-manifest.json').write_text(json.dumps(sources, sort_keys=True), encoding='utf-8')
        tag = 'gis-gee-runtime:offline-a64d2-' + policy.fingerprint({'sources': sources, 'reviewed': reviewed})[:12]
        existing = runtime.docker(['image', 'inspect', tag], optional=True)
        if existing:
            # Labels are not provenance. Use the saved reviewed probe for an
            # already built image; never relabel/trust a pre-existing tag here.
            raise RuntimeError('A64D2_IMAGE_TAG_COLLISION_USE_REVIEWED_PROBE')
        else:
            environment = runtime.env
            runtime.env = environment | {'DOCKER_BUILDKIT': '0'}
            try:
                log = runtime.docker(['build', '--pull=false', '--network=none',
                    '--build-arg', 'SOURCE_TREE_SHA256=' + tree, '--tag', tag, str(context)], timeout=120)
            finally:
                runtime.env = environment
            (self.output / 'build.log').write_text(log, encoding='utf-8')
            image = json.loads(runtime.docker(['image', 'inspect', tag]))[0]
        config = image['Config']
        labels = (base['Config'].get('Labels') or {}) | {
            'gis.a6.4d2.scope': 'offline-runtime-probe', 'gis.a6.4d2.source': tree,
            'gis.a6.4d2.egress': policy.POLICY}
        if (image['Os'] != 'linux' or image['Architecture'] != 'amd64'
            or image['RootFS']['Layers'][:len(base['RootFS']['Layers'])] != base['RootFS']['Layers']
            or config['Entrypoint'] != policy.ENTRYPOINT or config.get('Cmd') not in (None, [])
            or config['User'] != '65534:65534'
            or config.get('Labels') != labels or config.get('Env') != base['Config'].get('Env')
            or config.get('Volumes') != base['Config'].get('Volumes')
            or config.get('Healthcheck') != base['Config'].get('Healthcheck')
            or source_files() != sources or self.reviewed(review) != reviewed):
            raise RuntimeError('A64D2_BUILT_IMAGE_REJECTED')
        record = {'schema_version': 1, 'mode': 'offline-probe-only', 'live_enabled': False,
            'base_image': policy.BASE_IMAGE, 'image_id': image['Id'], 'tag': tag,
            'network_policy': policy.POLICY, 'source_tree_sha256': tree,
            'source_files': sources, 'reviewed_sources': reviewed,
            'image_labels': config['Labels'], 'environment_sha256': policy.fingerprint(config['Env']),
            'entrypoint': policy.ENTRYPOINT, 'command': policy.COMMAND,
            'actual_sdk_integration': 'blocked-not-tested-or-approved',
            'dependencies': json.loads((HERE / 'gee-mock-image.lock.json').read_text(encoding='utf-8'))['wheels']}
        LOCK.write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')
        (self.output / 'build-result.json').write_text(json.dumps(record, indent=2), encoding='utf-8')
        return {'image_id': image['Id'], 'source_tree_sha256': tree, 'network': 'none', 'live_enabled': False}

    def probe(self, review):
        self.proof()
        reviewed = self.reviewed(review)
        lock = json.loads(LOCK.read_text(encoding='utf-8'))
        if (lock.get('source_files') != source_files() or lock.get('reviewed_sources') != reviewed
            or lock.get('source_tree_sha256') != policy.fingerprint(source_files())
            or json.loads(Path(review).read_text(encoding='utf-8')).get('approved_probe_image_id') != lock.get('image_id')):
            raise RuntimeError('A64D2_STALE_IMAGE_SOURCE')
        runtime, run_id = self.db.runtime, uuid4().hex
        args = ['create', '--name', 'gis-a64d2-probe-' + run_id[:12], '--network=none',
            '--memory=1g', '--memory-swap=1g', '--cpus=1', '--pids-limit=64', '--read-only',
            '--cap-drop=ALL', '--security-opt=no-new-privileges:true', '--user=65534:65534', '--init',
            '--ulimit=core=0:0', '--ulimit=nofile=64:64', '--ulimit=fsize=16384:16384',
            '--tmpfs=/tmp:rw,nosuid,noexec,size=64m,mode=1777', '--log-driver=none',
            '--label', 'gis.a6.4d2.instance=' + self.db.instance,
            '--label', 'gis.a6.4d2.run=' + run_id, lock['image_id'], *policy.COMMAND]
        cid = runtime.docker(args)
        owned, process, record = False, None, None
        try:
            info = json.loads(runtime.docker(['inspect', cid]))[0]
            labels = info.get('Config', {}).get('Labels', {})
            if (info.get('Id') != cid or info.get('Name') != '/gis-a64d2-probe-' + run_id[:12]
                or labels.get('gis.a6.4d2.instance') != self.db.instance
                or labels.get('gis.a6.4d2.run') != run_id):
                raise RuntimeError('A64D2_PROBE_OWNERSHIP_REJECTED')
            owned = True
            checked = policy.verify_probe(info, lock, instance=self.db.instance, run_id=run_id, container_id=cid)
            # Bound stdout before retaining it, discard stderr, no stdin/credentials.
            process = subprocess.Popen(runtime.base + ['start', '-a', cid], env=runtime.env,
                cwd=runtime.root, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
            result = []
            def read():
                result.append(process.stdout.read(16385))
            thread = threading.Thread(target=read, daemon=True)
            thread.start()
            deadline = time.monotonic() + 30
            while process.poll() is None:
                if time.monotonic() >= deadline or result and len(result[0]) > 16384:
                    runtime.docker(['kill', cid], optional=True)
                    raise RuntimeError('A64D2_PROBE_TIME_OUTPUT_LIMIT')
                time.sleep(.1)
            thread.join(timeout=3)
            if process.returncode or thread.is_alive() or not result or len(result[0]) > 16384:
                raise RuntimeError('A64D2_PROBE_FAILED')
            info = json.loads(runtime.docker(['inspect', cid]))[0]
            policy.verify_probe(info, lock, instance=self.db.instance, run_id=run_id, container_id=cid)
            value = json.loads(result[0])
            if value.get('live_enabled') is not False or value.get('mode') != 'offline-probe':
                raise RuntimeError('A64D2_PROBE_RESULT_REJECTED')
            record = {'policy': checked, 'checks': value, 'live_enabled': False,
                'source_files': lock['source_files'], 'container_removed': True}
        finally:
            # Remove only our exact verified temporary probe, never an unknown ID.
            if owned:
                runtime.docker(['rm', '-f', cid])
                if runtime.docker(['inspect', cid], optional=True):
                    raise RuntimeError('A64D2_PROBE_CLEANUP_NOT_VERIFIED')
            if process is not None:
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.terminate()
                    process.wait(timeout=5)
        (self.output / 'probe-result.json').write_text(json.dumps(record, indent=2), encoding='utf-8')
        return record


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('proof', 'build', 'probe'))
    parser.add_argument('--runtime-dir', type=Path, required=True)
    parser.add_argument('--review', type=Path)
    args = parser.parse_args()
    local = RuntimeLocal(args.runtime_dir)
    value = local.proof() if args.action == 'proof' else getattr(local, args.action)(args.review)
    print(json.dumps(value))
