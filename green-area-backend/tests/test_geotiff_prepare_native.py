"""Synthetic, known-answer Linux GeoTIFF artifact tests; no database or cloud."""
import hashlib
import json
from uuid import uuid4
import pytest
np=pytest.importorskip('numpy');rasterio=pytest.importorskip('rasterio')
from rasterio.io import MemoryFile
from rasterio.transform import from_origin
from gis_worker import geotiff_prepare_provider as p

def fixture(tmp_path,profile='ndvi_ready',*,values=None,nodata=None,crs='EPSG:4326',transform=None,dtype='float64',count=1,tags=None,month=0):
    metric='ndvi' if profile=='ndvi_ready' else 'lst';units={'ndvi_ready':'unitless','lst_celsius_ready':'celsius','lst_kelvin_ready':'kelvin'}[profile]
    if values is None:values=[[-1,0],[1,-9999]] if metric=='ndvi' else [[0,20],[40,-9999]] if units=='celsius' else [[273.15,293.15],[313.15,0]]
    if nodata is None:nodata=0 if units=='kelvin' else -9999
    array=np.array(values,dtype=dtype);root=tmp_path/uuid4().hex;source=root/'source';stage=root/'stage';source.mkdir(parents=True);stage.mkdir()
    with MemoryFile() as memory:
        with memory.open(driver='GTiff',width=array.shape[1],height=array.shape[0],count=count,dtype=dtype,crs=crs,
                transform=transform or from_origin(100.5,13.7,.001,.001),nodata=nodata) as dst:
            for n in range(1,count+1):dst.write(array,n);dst.set_band_description(n,'NDVI' if metric=='ndvi' else 'LST');dst.set_band_unit(n,units)
            dst.update_tags(**({'GIS_PROFILE':profile,'GIS_PROVINCE':'Bangkok Metropolis','GIS_YEAR':'2026','GIS_MONTH':str(month)} if tags is None else tags))
        raw=memory.read()
    sha=hashlib.sha256(raw).hexdigest();(source/(sha+'.tif')).write_bytes(raw)
    manifest={'schema_version':4,'provider':'local_geotiff','provenance':'local-geotiff-upload-v1','data_kind':'raster','sha256':sha,'byte_size':len(raw),'crs':'EPSG:4326','profile':profile,'metric':metric,'bands':['NDVI' if metric=='ndvi' else 'LST'],'units':units}
    packet={k:str(uuid4()) for k in ('dataset_id','edition_id','validation_result_id','job_id')}
    packet.update(method_version=p.METHOD,month=month,validation={'upload_id':str(uuid4()),'manifest':manifest,'input_hash':'a'*64,'input_revision':1,'attempt_number':1,'province':'Bangkok Metropolis','data_year':2026})
    return packet,source,stage

@pytest.mark.parametrize('profile,expected',[('ndvi_ready',0),('lst_celsius_ready',20),('lst_kelvin_ready',20)])
def test_ready_profiles_actual_bytes_once_conversion_and_grid(tmp_path,profile,expected):
    packet,source,stage=fixture(tmp_path,profile);out=p.build(packet,source_root=source);metric=packet['validation']['manifest']['metric'];summary=json.loads(out[metric+'_summary'])
    assert summary['statistics']['mean']==pytest.approx(expected,abs=1e-12)
    assert summary['statistics']['valid_pixels']==3 and summary['statistics']['nodata_pixels']==1
    assert summary['metadata']['kelvin_to_celsius_count']==int(profile=='lst_kelvin_ready')
    assert summary['metadata']['grid_preserved'] and not summary['metadata']['reprojection'] and not summary['metadata']['period_verified']
    assert not summary['metadata']['complete_province_inventory'] and summary['metadata']['intersection_fraction_of_footprint']>0
    assert out==p.build(packet,source_root=source)
    with MemoryFile(out[metric+'_raster']) as memory,memory.open() as dst:
        assert dst.units==('unitless' if metric=='ndvi' else 'celsius',) and dst.transform==from_origin(100.5,13.7,.001,.001)
        if profile=='lst_kelvin_ready':assert dst.read(1)[0,0]==pytest.approx(0) and dst.nodata==-9999 and dst.read_masks(1)[0,0]==255
    report=p.prepare(packet,source_root=source,staging_root=stage);proof=p.verify(packet,source_root=source,staging_root=stage)
    assert proof=={**report,'verifier_version':p.VERIFIER}

@pytest.mark.parametrize('case',['nan','inf','all_nodata','bad_crs','bad_transform','bad_dtype','bad_bands','bad_province','bad_year','bad_month','outside'])
def test_invalid_scientific_spatial_period_inputs(tmp_path,case):
    kw={}
    if case in ('nan','inf'):kw['values']=[[float(case),0],[1,-9999]]
    if case=='all_nodata':kw['values']=[[-9999,-9999],[-9999,-9999]]
    if case=='bad_crs':kw['crs']=None
    if case=='bad_transform':kw['transform']=from_origin(100.5,13.7,0,.001)
    if case=='bad_dtype':kw.update(dtype='uint16',nodata=65535,values=[[0,1],[1,65535]])
    if case=='bad_bands':kw['count']=2
    if case=='outside':kw['transform']=from_origin(0,1,.001,.001)
    if case in ('bad_province','bad_year','bad_month'):
        kw['tags']={'GIS_PROFILE':'ndvi_ready','GIS_PROVINCE':'Bangkok Metropolis','GIS_YEAR':'2026','GIS_MONTH':'0'}
        kw['tags'][{'bad_province':'GIS_PROVINCE','bad_year':'GIS_YEAR','bad_month':'GIS_MONTH'}[case]]={'bad_province':'Chiang Mai','bad_year':'2025','bad_month':'1'}[case]
    packet,source,_=fixture(tmp_path,**kw)
    with pytest.raises(ValueError):p.build(packet,source_root=source)

def test_annual_declarations_unverified_monthly_requires_tags(tmp_path):
    packet,source,_=fixture(tmp_path,tags={'GIS_PROFILE':'ndvi_ready'})
    summary=json.loads(p.build(packet,source_root=source)['ndvi_summary']);assert summary['metadata']['period_status']=='declared_unverified'
    packet['month']=1
    with pytest.raises(ValueError,match='MONTH_METADATA'):p.build(packet,source_root=source)

@pytest.mark.parametrize('case',['missing','corrupt','source_missing','source_corrupt','stale_input','substituted'])
def test_trusted_verifier_rejects_actual_bad_bytes(tmp_path,case):
    packet,source,stage=fixture(tmp_path);p.prepare(packet,source_root=source,staging_root=stage);directory=stage/p.stage_key(packet)
    if case=='missing':(directory/'raster.tif').unlink()
    elif case=='corrupt':(directory/'summary.json').write_bytes(b'{}')
    elif case=='source_missing':next(source.iterdir()).unlink()
    elif case=='source_corrupt':next(source.iterdir()).write_bytes(b'invalid')
    elif case=='stale_input':packet['validation']['input_hash']='b'*64
    else:
        other,other_source,_=fixture(tmp_path);(directory/'raster.tif').write_bytes(p.build(other,source_root=other_source)['ndvi_raster'])
    with pytest.raises((ValueError,OSError)):p.verify(packet,source_root=source,staging_root=stage)

def test_preview_and_capacity_limits(tmp_path):
    packet,source,_=fixture(tmp_path,values=np.full((100,100),.5))
    summary=json.loads(p.build(packet,source_root=source)['ndvi_summary'])
    assert summary['preview']['width']==64 and summary['preview']['height']==64
    packet,source,_=fixture(tmp_path,values=np.full((1001,1000),.5))
    with pytest.raises(ValueError,match='PIXEL_LIMIT'):p.build(packet,source_root=source)

def test_unknown_payload_and_profile(tmp_path):
    packet,source,_=fixture(tmp_path);packet['path']='/etc/passwd'
    with pytest.raises(ValueError):p.build(packet,source_root=source)
