"""Credential-free network-disabled verification of immutable publication bytes."""
import json
import os
from pathlib import Path
import sys

VERSION='ldd-publication-bytes-v1'

def verify(packet,*,source_root=Path('/data/ldd'),objects=Path('/data/ldd-artifacts')):
    from gis_worker.ldd_prepare_provider import build,descriptors,read_regular,failure
    if not isinstance(packet,dict) or set(packet)!={'prepare_request','candidate'}:raise ValueError('PUBLICATION_REQUEST_INVALID')
    request=packet['prepare_request'];expected=build(request,source_root=source_root)
    report=failure(request,'PREPARE_UNVERIFIED');report.update(valid=True,error_code=None,artifacts=descriptors(expected))
    if report!=packet['candidate']:raise ValueError('PUBLICATION_CANDIDATE_CHANGED')
    actual={kind:read_regular(objects/(item['sha256']+'.json')) for kind,item in report['artifacts'].items()}
    if actual!=expected:raise ValueError('PUBLICATION_OBJECT_CHANGED')
    return {**report,'verifier_version':VERSION}

def main():
    if sys.platform!='linux':return 70
    import resource
    for kind,value in ((resource.RLIMIT_CORE,0),(resource.RLIMIT_AS,512*1024**2),(resource.RLIMIT_CPU,20),
        (resource.RLIMIT_NOFILE,64),(resource.RLIMIT_FSIZE,16384)):resource.setrlimit(kind,(value,value))
    os.environ.update(PROJ_NETWORK='OFF',GDAL_HTTP_TIMEOUT='1',CPL_VSIL_CURL_ALLOWED_EXTENSIONS='',
        OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',GDAL_NUM_THREADS='1')
    sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
    raw=sys.stdin.buffer.read(65537)
    if len(raw)>65536:return 65
    try:result=verify(json.loads(raw))
    except Exception:result={'valid':False,'error_code':'PUBLICATION_BYTE_VERIFICATION_FAILED'}
    output=json.dumps(result,allow_nan=False,separators=(',',':'))
    if len(output.encode())>16384:return 65
    sys.stdout.write(output);return 0

if __name__=='__main__':raise SystemExit(main())
