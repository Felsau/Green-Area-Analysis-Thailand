"""Credential-free byte recomputation of immutable Local publication objects."""
import json
import os
from pathlib import Path
import sys

VERSION='geotiff-publication-bytes-v1'
RENDER_VERSION='geotiff-mercator-nearest-v1'
MAX_RESPONSE=256*1024


def render(src,metric,p):
    """Display-only Web Mercator sampling; scientific TIFF/statistics stay unchanged."""
    import hashlib
    import base64
    import numpy as np
    from rasterio.transform import from_bounds
    from rasterio.warp import reproject,transform_bounds,Resampling
    width,height=min(src.width,64),min(src.height,64)
    projected=transform_bounds(src.crs,'EPSG:3857',*src.bounds)
    transform=from_bounds(*projected,width,height)
    values=np.full((height,width),src.nodata,dtype='float64')
    valid=np.zeros((height,width),dtype='uint8')
    common=dict(src_transform=src.transform,src_crs=src.crs,dst_transform=transform,
        dst_crs='EPSG:3857',resampling=Resampling.nearest,num_threads=1,warp_mem_limit=16)
    reproject(src.read(1),values,src_nodata=src.nodata,dst_nodata=src.nodata,**common)
    reproject(src.read_masks(1),valid,src_nodata=0,dst_nodata=0,**common)
    image=p._png(values,valid!=0,metric)
    return {**image,'render_crs':'EPSG:3857','render_method_version':RENDER_VERSION,
        'render_bounds':list(projected),'render_transform':list(transform)[:6],
        'image_sha256':hashlib.sha256(base64.b64decode(image['png_base64'])).hexdigest()}


def verify(packet,*,source_root=Path('/data/geotiff/objects'),objects=Path('/data/geotiff-artifacts')):
    from gis_worker import geotiff_prepare_provider as p
    if not isinstance(packet,dict) or set(packet)!={'prepare_request','candidate'}:raise ValueError('PUBLICATION_REQUEST_INVALID')
    request=p.check_request(packet['prepare_request']);expected=p.build(request,source_root=source_root)
    report=p.failure(request,'PREPARE_UNVERIFIED');report.update(valid=True,error_code=None,artifacts=p.descriptors(expected))
    if report!=packet['candidate']:raise ValueError('PUBLICATION_CANDIDATE_CHANGED')
    actual={k:p.read_regular(objects/(item['sha256']+('.tif' if k.endswith('_raster') else '.json'))) for k,item in report['artifacts'].items()}
    if actual!=expected:raise ValueError('PUBLICATION_OBJECT_CHANGED')
    metric=request['validation']['manifest']['metric'];summary=json.loads(actual[metric+'_summary'])
    import rasterio
    from rasterio.io import MemoryFile
    with rasterio.Env(GDAL_PAM_ENABLED='NO',GDAL_DISABLE_READDIR_ON_OPEN='EMPTY_DIR',PROJ_NETWORK='OFF'):
        with MemoryFile(actual[metric+'_raster']) as memory,memory.open(driver='GTiff') as src:
            if src.crs.to_epsg()!=4326 or src.transform.b!=0 or src.transform.d!=0:raise ValueError('PUBLICATION_GRID_UNSUPPORTED')
            bounds=list(src.bounds)
            if not (-180<=bounds[0]<bounds[2]<=180 and -85<=bounds[1]<bounds[3]<=85):raise ValueError('PUBLICATION_BOUNDS_UNSUPPORTED')
            # Re-read actual prepared pixels. This image is a bounded nearest
            # visualization, never a replacement for full valid-pixel statistics.
            image=p._png(src.read(1),src.read_masks(1)!=0,metric)
            if image!=summary['preview']:raise ValueError('PUBLICATION_IMAGE_CHANGED')
            display=render(src,metric,p)
    return {'report':{**report,'verifier_version':VERSION},'summary':summary,
        'raster':{**display,'bounds':bounds,'artifact_sha256':report['artifacts'][metric+'_raster']['sha256'],'nodata_transparent':True}}


def main():
    if sys.platform!='linux':return 70
    import resource
    for kind,value in ((resource.RLIMIT_CORE,0),(resource.RLIMIT_AS,512*1024**2),(resource.RLIMIT_CPU,20),
            (resource.RLIMIT_NOFILE,64),(resource.RLIMIT_FSIZE,MAX_RESPONSE)):resource.setrlimit(kind,(value,value))
    os.environ.update(PROJ_NETWORK='OFF',GDAL_HTTP_TIMEOUT='1',CPL_VSIL_CURL_ALLOWED_EXTENSIONS='',
        OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',GDAL_NUM_THREADS='1')
    sys.path.insert(0,str(Path(__file__).resolve().parent.parent));raw=sys.stdin.buffer.read(65537)
    if len(raw)>65536:return 65
    try:result=verify(json.loads(raw))
    except Exception:result={'valid':False,'error_code':'PUBLICATION_BYTE_VERIFICATION_FAILED'}
    output=json.dumps(result,allow_nan=False,separators=(',',':'))
    if len(output.encode())>MAX_RESPONSE:return 65
    sys.stdout.write(output);return 0


if __name__=='__main__':raise SystemExit(main())
