"""Local ready-profile preparation; original grid, no resampling or GEE claims."""
import base64
import hashlib
import math
import os
from pathlib import Path
import struct
import zlib
from gis_worker import geotiff_provider as geo
from gis_worker import ldd_provider as ldd
from gis_worker.ldd_prepare_provider import canonical, descriptors, read_regular, require

METHOD='geotiff-grid-celsius-v1'
VERIFIER='geotiff-trusted-bytes-v1'
MAX_PIXELS=1000000
MAX_ARTIFACT=20*1024**2
ROOT=Path('/data/geotiff/objects')

def check_request(value):
    from uuid import UUID
    require(isinstance(value,dict) and set(value)=={'validation','dataset_id','edition_id','validation_result_id','job_id','method_version','month'},'PREPARE_REQUEST_INVALID')
    geo.check_request(value['validation'])
    for k in ('dataset_id','edition_id','validation_result_id','job_id'):
        require(isinstance(value[k],str) and str(UUID(value[k]))==value[k],'PREPARE_REQUEST_INVALID')
    require(value['method_version']==METHOD and type(value['month']) is int and 0<=value['month']<=12,'PREPARE_REQUEST_INVALID')
    return value

def names(request):
    metric=request['validation']['manifest']['metric']
    return {metric+'_raster':'raster.tif',metric+'_summary':'summary.json'}

def stage_key(request):
    check_request(request)
    return request['job_id']+'-'+str(request['validation']['attempt_number'])

def failure(request,code):
    check_request(request)
    value={k:request[k] for k in ('dataset_id','edition_id','job_id','validation_result_id')}
    value.update(schema_version=1,method_version=METHOD,valid=False,error_code=code,
        source_sha256=request['validation']['manifest']['sha256'],input_hash=request['validation']['input_hash'],
        input_revision=request['validation']['input_revision'],artifacts={})
    return value

def _png(array,valid,metric):
    """Bounded nearest-neighbour visual sample only; never used for statistics."""
    import numpy as np
    y=np.linspace(0,array.shape[0]-1,min(64,array.shape[0])).astype(int)
    x=np.linspace(0,array.shape[1]-1,min(64,array.shape[1])).astype(int)
    a=array[np.ix_(y,x)];mask=valid[np.ix_(y,x)]
    value=np.clip((a+1)/2 if metric=='ndvi' else (a+100)/200,0,1)
    value=np.where(mask,value,0)
    rgba=np.zeros((*a.shape,4),dtype='uint8')
    rgba[:,:,0]=(255*(1-value)).astype('uint8');rgba[:,:,1]=(220*value).astype('uint8');rgba[:,:,2]=60
    rgba[:,:,3]=np.where(mask,255,0)
    def chunk(kind,data):return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
    h,w=a.shape;raw=b''.join(b'\0'+row.tobytes() for row in rgba)
    png=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>2I5B',w,h,8,6,0,0,0))+chunk(b'IDAT',zlib.compress(raw))+chunk(b'IEND',b'')
    return {'width':w,'height':h,'sampling':'nearest_visual_only','png_base64':base64.b64encode(png).decode()}

def build(request,*,source_root=ROOT):
    check_request(request);v=request['validation'];m=v['manifest']
    result=geo.validate(v,storage_root=source_root)
    require(result['valid'],result['error_code'] or 'PREPARE_INVALID_SOURCE')
    raw=geo._source_bytes(v,source_root)
    require(hashlib.sha256(raw).hexdigest()==m['sha256'],'GEOTIFF_SHA256_MISMATCH')
    import numpy as np
    import rasterio
    from rasterio.io import MemoryFile
    from rasterio.warp import transform
    from shapely.geometry import shape,Polygon,mapping
    with rasterio.Env(GDAL_PAM_ENABLED='NO',GDAL_DISABLE_READDIR_ON_OPEN='EMPTY_DIR',PROJ_NETWORK='OFF',GDAL_NUM_THREADS='1',GDAL_CACHEMAX=16*1024**2):
        with MemoryFile(raw) as memory, memory.open(driver='GTiff') as src:
            require(src.width*src.height<=MAX_PIXELS,'PREPARE_PIXEL_LIMIT')
            tags=src.tags();expected={'GIS_PROVINCE':v['province'],'GIS_YEAR':str(v['data_year']),'GIS_MONTH':str(request['month'])}
            for k,value in expected.items():
                require(k not in tags or tags[k]==value,'PREPARE_PERIOD_SCOPE_MISMATCH')
            require(request['month']==0 or all(k in tags for k in expected),'PREPARE_MONTH_METADATA_REQUIRED')
            # Densified outer grid edges. No clipping; valid-pixel coverage is a
            # separate count and does not imply every footprint pixel is valid.
            b=src.bounds;t=np.linspace(0,1,22);points=[]
            for start,end in [((b.left,b.bottom),(b.right,b.bottom)),((b.right,b.bottom),(b.right,b.top)),((b.right,b.top),(b.left,b.top)),((b.left,b.top),(b.left,b.bottom))]:
                points.extend((start[0]+q*(end[0]-start[0]),start[1]+q*(end[1]-start[1])) for q in t[:-1])
            xs,ys=transform(src.crs,'EPSG:4326',[p[0] for p in points],[p[1] for p in points]);footprint=Polygon(zip(xs,ys))
            require(footprint.is_valid and not footprint.is_empty and footprint.area>0 and all(math.isfinite(x) for x in footprint.bounds),'PREPARE_FOOTPRINT_INVALID')
            boundaries=ldd._asset('province_boundaries.json',ldd.BOUNDARY_SHA256)
            boundary=next((shape(f['geometry']) for f in boundaries['features'] if f['properties']['name']==v['province']),None)
            require(boundary is not None and boundary.is_valid,'PREPARE_PROVINCE_UNKNOWN')
            overlap=footprint.intersection(boundary)
            require(not overlap.is_empty and overlap.area>0,'PREPARE_PROVINCE_NO_INTERSECTION')
            array=src.read(1);valid=src.read_masks(1)!=0
            require(bool(np.all(np.isfinite(array))) and bool(valid.any()),'PREPARE_INVALID_PIXELS')
            kelvin=m['profile']=='lst_kelvin_ready'
            # Only this step converts scientific values. Summary and PNG read
            # the prepared Celsius array and never subtract again.
            prepared=array.astype('float64') if kelvin else array.copy()
            if kelvin:prepared[valid]-=273.15
            values=prepared[valid].astype('float64');units='unitless' if m['metric']=='ndvi' else 'celsius'
            lower,upper=(-1,1) if m['metric']=='ndvi' else (-100,100)
            output_nodata=-9999.0 if lower<=src.nodata<=upper else float(src.nodata)
            prepared[~valid]=output_nodata
            stats={'total_pixels':int(prepared.size),'valid_pixels':int(valid.sum()),'nodata_pixels':int((~valid).sum()),
                'mean':float(values.mean()),'min':float(values.min()),'max':float(values.max()),'units':units}
            require(math.isclose(stats['mean'],result['statistics']['mean'],rel_tol=1e-12,abs_tol=1e-12),'PREPARE_STATISTICS_MISMATCH')
            meta={k:request[k] for k in ('dataset_id','edition_id','validation_result_id','method_version','month')}
            meta.update(schema_version=1,input_revision=v['input_revision'],input_hash=v['input_hash'],source_sha256=m['sha256'],
                province=v['province'],data_year=v['data_year'],source_profile=m['profile'],source_units=m['units'],output_units=units,
                kelvin_to_celsius_count=int(kelvin),output_profile='ndvi_ready' if m['metric']=='ndvi' else 'lst_celsius_ready',
                crs=m['crs'],transform=list(src.transform)[:6],resolution=list(src.res),width=src.width,height=src.height,
                dtype=str(prepared.dtype),nodata=output_nodata,source_nodata=float(src.nodata),nodata_normalized=output_nodata!=src.nodata,nodata_semantics='finite_sentinel_mask_no_external_mask',
                scale=1,offset=0,grid_preserved=True,reprojection=False,resampling=False,clipping=False,
                period_verified=False,period_status='matching_declared_tags_unverified' if all(k in tags for k in expected) else 'declared_unverified',
                coverage_mode='source_footprint_intersection',boundary_sha256=ldd.BOUNDARY_SHA256,boundary_approximate=True,
                complete_province_inventory=False,footprint=mapping(footprint),
                intersection_fraction_of_footprint=overlap.area/footprint.area,intersection_fraction_of_province=overlap.area/boundary.area,
                intersection_measure='approximate_geographic_area_ratio_not_geodesic',valid_pixel_fraction=stats['valid_pixels']/stats['total_pixels'])
            with MemoryFile() as target:
                with target.open(driver='GTiff',width=src.width,height=src.height,count=1,dtype=prepared.dtype,crs=src.crs,
                        transform=src.transform,nodata=output_nodata,compress='none') as dst:
                    dst.write(prepared,1);dst.set_band_description(1,m['bands'][0]);dst.set_band_unit(1,units)
                    dst.update_tags(GIS_PROFILE=meta['output_profile'],GIS_PREPARED_METADATA=canonical(meta).decode())
                raster=target.read()
            # Independently reopen the actual emitted TIFF before describing it.
            with MemoryFile(raster) as target, target.open(driver='GTiff') as dst:
                require(np.array_equal(dst.read(1),prepared) and np.array_equal(dst.read_masks(1)!=0,valid)
                    and dst.transform==src.transform and dst.crs==src.crs and dst.units==(units,),'PREPARE_RASTER_MISMATCH')
            summary={'schema_version':1,'metadata':meta,'statistics':stats,'preview':_png(prepared,valid,m['metric']),
                'raster_sha256':hashlib.sha256(raster).hexdigest(),'warnings':['BOUNDARY_APPROXIMATE','PERIOD_DECLARED_NOT_INDEPENDENTLY_VERIFIED','NOT_COMPLETE_PROVINCE_INVENTORY','NOT_EQUIVALENT_TO_GEE_PIPELINE']}
    outputs={m['metric']+'_raster':raster,m['metric']+'_summary':canonical(summary)}
    require(all(0<len(x)<=MAX_ARTIFACT for x in outputs.values()),'PREPARE_ARTIFACT_LIMIT')
    return outputs

def prepare(request,*,source_root=ROOT,staging_root=Path('/data/prepare')):
    outputs=build(request,source_root=source_root);root=Path(staging_root)
    require(root.is_dir() and not root.is_symlink() and root.resolve()==root.absolute(),'PREPARE_STORAGE_INVALID')
    used,count=0,0
    for p in root.rglob('*'):
        count+=1;require(count<=4096 and not p.is_symlink(),'PREPARE_STORAGE_LIMIT')
        if p.is_file():require(p.stat().st_nlink==1,'PREPARE_STORAGE_INVALID');used+=p.stat().st_size
    require(used+sum(map(len,outputs.values()))<=256*1024**2,'PREPARE_STORAGE_LIMIT')
    directory=root/stage_key(request)
    if not directory.exists():directory.mkdir(mode=0o700)
    require(not directory.is_symlink() and directory.resolve().parent==root.resolve(),'PREPARE_STORAGE_INVALID')
    for kind,name in names(request).items():
        p=directory/name
        if p.exists():require(read_regular(p)==outputs[kind],'PREPARE_IMMUTABLE_CONFLICT')
        else:
            with p.open('xb') as stream:stream.write(outputs[kind]);stream.flush();os.fsync(stream.fileno())
    report=failure(request,'PREPARE_UNVERIFIED');report.update(valid=True,error_code=None,artifacts=descriptors(outputs));return report

def verify(request,*,source_root=ROOT,staging_root=Path('/data/prepare')):
    expected=build(request,source_root=source_root);directory=Path(staging_root)/stage_key(request)
    actual={kind:read_regular(directory/name) for kind,name in names(request).items()}
    require(actual==expected,'PREPARE_ARTIFACT_MISMATCH')
    report=failure(request,'PREPARE_UNVERIFIED');report.update(valid=True,error_code=None,artifacts=descriptors(actual),verifier_version=VERIFIER);return report
