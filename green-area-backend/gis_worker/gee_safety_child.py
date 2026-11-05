"""Fixed offline scientific rehearsal. Never credentials or network."""
import json
import os
from pathlib import Path
import sys


def main():
    if sys.platform!='linux':return 70
    import resource
    resource.setrlimit(resource.RLIMIT_CORE,(0,0))
    resource.setrlimit(resource.RLIMIT_AS,(512*1024**2,512*1024**2))
    resource.setrlimit(resource.RLIMIT_CPU,(20,20))
    resource.setrlimit(resource.RLIMIT_NOFILE,(64,64))
    resource.setrlimit(resource.RLIMIT_FSIZE,(16384,16384))
    os.environ['PYDANTIC_DISABLE_PLUGINS']='__all__'
    sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
    from gis_worker.gee_mock_child import install_guards
    install_guards()
    from datetime import date,datetime,timezone
    from gis_worker.gee_live_contracts import Request
    from gis_worker.gee_live_bridge import InjectedBridge
    from gis_worker.gee_live_injected import InjectedSDK,InjectedTransport
    raw=sys.stdin.buffer.read(65537)
    if len(raw)>65536:return 65
    value=json.loads(raw)
    if set(value)!={'request','geometry','scenario'} or value['scenario'] not in ('candidate','zero','no_data','incomplete','hang'):return 65
    request=Request.model_validate(value['request'])
    if request.execution!='injected':return 65
    if value['scenario']=='hang':
        import time
        time.sleep(240)
    empty=value['scenario']=='no_data'
    number=0.0 if value['scenario']=='zero' else .25 if request.product=='ndvi' else 30.0
    response={'scene_ids':[] if empty else [request.method.collections[0]+'/INJECTED_ONLY'],
        'acquired_ms':[] if empty else [int(datetime.combine(request.period.start,datetime.min.time(),tzinfo=timezone.utc).timestamp()*1000)],
        'scene_count':0 if empty else 1,'valid_pixels':0 if empty else 2,
        'mean':None if empty else number,'min':None if empty or request.period.month else number,
        'max':None if empty or request.period.month else number,'complete':value['scenario']!='incomplete'}
    output=InjectedBridge(sdk=InjectedSDK(),transport=InjectedTransport(response),authorization=lambda:request.project,as_of=date(2026,1,1)).compute(request,value['geometry'])
    encoded=json.dumps(output.model_dump(mode='json'),allow_nan=False,separators=(',',':'))
    if len(encoded.encode())>16384:return 65
    sys.stdout.write(encoded);return 0


if __name__=='__main__':raise SystemExit(main())
