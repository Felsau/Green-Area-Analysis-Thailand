"""Credential-free Linux mock child; resource guards precede adapter imports."""
import json
import os
from pathlib import Path
import sys
import time


def install_guards():
    def guard(event, args):
        if event in ('socket.__new__', 'socket.connect', 'socket.connect_ex', 'socket.getaddrinfo',
                     'socket.sendto', 'socket.sendmsg', 'socket.gethostbyname', 'socket.gethostbyaddr'):
            raise RuntimeError('GEE_MOCK_CHILD_NETWORK_FORBIDDEN')
        if event in ('subprocess.Popen', 'os.system', 'os.exec', 'os.posix_spawn', 'os.posix_spawnp'):
            raise RuntimeError('GEE_MOCK_CHILD_PROCESS_FORBIDDEN')
        if event == 'open' and isinstance(args[0], (str, bytes)):
            name = os.path.basename(os.fsdecode(args[0])).lower()
            if name.startswith('.env') or name in ('credentials', 'credentials.json', 'private-key.json'):
                raise RuntimeError('GEE_MOCK_CHILD_CREDENTIAL_FORBIDDEN')
    sys.addaudithook(guard)
    import importlib.abc
    class NoCloud(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, *_):
            if fullname.split('.')[0] in ('ee', 'google', 'dotenv', 'supabase', 'main', 'dependencies', 'routers'):
                raise RuntimeError('GEE_MOCK_CHILD_IMPORT_FORBIDDEN')
    sys.meta_path.insert(0, NoCloud())


def main():
    if sys.platform != 'linux':
        return 70
    import resource
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_AS, (512 * 1024**2, 512 * 1024**2))
    resource.setrlimit(resource.RLIMIT_CPU, (20, 20))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    resource.setrlimit(resource.RLIMIT_FSIZE, (16384, 16384))
    os.environ['PYDANTIC_DISABLE_PLUGINS'] = '__all__'
    install_guards()
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from gis_worker.gee_mock_fixtures import execute
    raw = sys.stdin.buffer.read(65537)
    if len(raw) > 65536:
        return 65
    try:
        result = execute(json.loads(raw), legacy_root=Path('/app/legacy'), sleep=time.sleep)
        encoded = json.dumps(result, allow_nan=False, separators=(',', ':'))
        if len(encoded.encode()) > 16384:
            return 65
        sys.stdout.write(encoded)
        return 0
    except (ValueError, TypeError, KeyError):
        return 65


if __name__ == '__main__':
    raise SystemExit(main())
