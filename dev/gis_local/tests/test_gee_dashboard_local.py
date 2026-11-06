"""No Docker/DB calls: the GEE Dashboard worker's backend must target the local T0."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

path = Path(__file__).resolve().parents[1] / 'gee_dashboard_local.py'
spec = importlib.util.spec_from_file_location('test_dashboard_operator', path)
m = importlib.util.module_from_spec(spec); sys.modules[spec.name] = m; spec.loader.exec_module(m)
BACKEND = m.REPO / 'green-area-backend'


def test_worker_env_replaces_inherited_supabase_values_and_drops_everything_else():
    env = m.worker_env('local-key', {'PATH': 'p', 'SUPABASE_URL': 'https://cloud.invalid', 'SUPABASE_KEY': 'cloud-key',
        'GOOGLE_APPLICATION_CREDENTIALS': 'x', 'OTHER': 'y'})
    assert env == {'PATH': 'p', 'SUPABASE_URL': m.HOST_URL, 'SUPABASE_KEY': 'local-key'}
    assert m.HOST_URL == 'http://127.0.0.1:55421'


@pytest.mark.parametrize('key', ['', None, 123])
def test_worker_env_refuses_a_missing_local_key(key):
    with pytest.raises(RuntimeError, match='WORKER_LOCAL_KEY_REQUIRED'):
        m.worker_env(key, {'PATH': 'p'})


def test_dotenv_does_not_override_the_local_target(tmp_path):
    # Same order as the backend: load_dotenv() reads a file naming Cloud, then os.getenv.
    (tmp_path / '.env').write_text('SUPABASE_URL=https://cloud.invalid\nSUPABASE_KEY=cloud-key\n', encoding='utf-8')
    code = ("import json,os;from dotenv import load_dotenv;load_dotenv(os.path.join(os.getcwd(),'.env'));"
        "print(json.dumps([os.getenv('SUPABASE_URL'),os.getenv('SUPABASE_KEY')]))")
    source = {k: v for k, v in os.environ.items() if k.upper() in m.ENV_KEYS}
    result = subprocess.run([sys.executable, '-I', '-B', '-c', code], cwd=tmp_path, env=m.worker_env('local-key', source),
        capture_output=True, text=True, encoding='utf-8', timeout=60)
    assert result.returncode == 0, result.stderr[-800:]
    assert json.loads(result.stdout) == [m.HOST_URL, 'local-key']
