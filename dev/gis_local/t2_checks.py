"""Controlled unit/regression execution with no original dotenv or GEE startup."""
import argparse
import json
import os
from pathlib import Path
import socket
import sys
from unittest.mock import patch
import uuid


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('group',choices=('unit','regression'))
    parser.add_argument('--runtime-dir',type=Path,required=True)
    args=parser.parse_args()
    runtime=args.runtime_dir.resolve()
    owner=json.loads((runtime/'owner.json').read_text(encoding='utf-8'))
    if owner.get('scope')!='gis-foundation-t0' or owner.get('project')!='green-area-gis-t0':
        raise RuntimeError('EXPLICIT_LOCAL_RUNTIME_REQUIRED')
    repo=Path(__file__).resolve().parents[2]
    target=runtime/'t2';target.mkdir(exist_ok=True)
    # Retain only OS execution variables; do not read ambient service values.
    allowed={'PATH','SYSTEMROOT','SYSTEMDRIVE','COMSPEC','TEMP','TMP','WINDIR','PATHEXT','LANG','LC_ALL'}
    clean={k:v for k,v in os.environ.items() if k.upper() in allowed}
    os.environ.clear();os.environ.update(clean)
    os.environ['PYTEST_DISABLE_PLUGIN_AUTOLOAD']='1'
    os.environ['TEMP']=os.environ['TMP']=str(target)
    sys.path.insert(0,str(repo/'green-area-backend'))
    import pytest
    class Results:
        def __init__(self):self.rows=[]
        def pytest_runtest_logreport(self,report):
            if report.when=='call' or (report.failed and report.when=='setup'):
                self.rows.append({'case':report.nodeid,'outcome':report.outcome})
    collected=Results()
    tests=['test_gis_api_unit.py','test_gis_runtime_unit.py'] if args.group=='unit' else ['test_auth_dependencies.py','test_endpoints.py','test_gis_legacy_mount.py']
    original_connect=socket.socket.connect
    def only_loopback(sock,address):
        if isinstance(address,tuple) and address[0] not in ('127.0.0.1','::1'):
            raise RuntimeError('NONLOCAL_NETWORK_DENIED_IN_UNIT_REGRESSION')
        return original_connect(sock,address)
    with patch('dotenv.load_dotenv',return_value=False),patch.object(socket.socket,'connect',only_loopback):
        result=pytest.main(['-q','-p','no:cacheprovider','--basetemp',str(target/('temp-'+uuid.uuid4().hex)),
            *[str(repo/'green-area-backend/tests'/name) for name in tests]],plugins=[collected])
    output={'group':args.group,'type':'mock_unit_or_regression_not_real_supabase_integration',
        'counts':{key:sum(r['outcome']==key for r in collected.rows) for key in ('passed','failed','skipped')},
        'cases':collected.rows,'dotenv_suppressed':True,'nonlocal_network_denied':True}
    (target/(args.group+'-tests.json')).write_text(json.dumps(output,indent=2)+'\n',encoding='utf-8',newline='\n')
    return int(result)


if __name__=='__main__':sys.exit(main())
