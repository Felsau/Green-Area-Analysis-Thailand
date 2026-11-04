"""Known-answer immutable GeoTIFF publication bytes on the pinned Linux image."""
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import zlib
import pytest
pytest.importorskip('rasterio')
from gis_worker import geotiff_prepare_provider as p
from gis_worker.geotiff_publication_child import verify
s=importlib.util.spec_from_file_location('a42_native_fixture',Path(__file__).with_name('test_geotiff_prepare_native.py'))
f=importlib.util.module_from_spec(s);s.loader.exec_module(f)

def prepared(tmp_path,profile='ndvi_ready',**kw):
    request,source,stage=f.fixture(tmp_path,profile,**kw);candidate=p.prepare(request,source_root=source,staging_root=stage)
    objects=tmp_path/'objects';objects.mkdir();outputs=p.build(request,source_root=source)
    for k,raw in outputs.items():
        name=hashlib.sha256(raw).hexdigest()+('.tif' if k.endswith('_raster') else '.json');(objects/name).write_bytes(raw)
    return {'prepare_request':request,'candidate':candidate},source,objects

@pytest.mark.parametrize('profile,mean,conversions',[('ndvi_ready',0,0),('lst_celsius_ready',20,0),('lst_kelvin_ready',20,1)])
def test_actual_raster_summary_png_and_once_conversion(tmp_path,profile,mean,conversions):
    packet,source,objects=prepared(tmp_path,profile);v=verify(packet,source_root=source,objects=objects)
    assert v['report']['verifier_version']=='geotiff-publication-bytes-v1'
    assert v['summary']['statistics']['mean']==pytest.approx(mean)
    assert v['summary']['metadata']['kelvin_to_celsius_count']==conversions
    assert v['raster']['bounds']==pytest.approx([100.5,13.698,100.502,13.7])
    assert v['raster']['render_crs']=='EPSG:3857' and v['raster']['render_method_version']=='geotiff-mercator-nearest-v1'
    assert v['raster']['nodata_transparent'] and v['raster']['width']==v['raster']['height']==2
    import base64
    png=base64.b64decode(v['raster']['png_base64']);pos=8;compressed=b''
    while pos<len(png):
        n=struct.unpack('>I',png[pos:pos+4])[0];kind=png[pos+4:pos+8];raw=png[pos+8:pos+8+n];pos+=12+n
        if kind==b'IDAT':compressed+=raw
    rows=zlib.decompress(compressed);assert [rows[n] for n in (4,8,13,17)]==[255,255,255,0]
    assert len(json.dumps(v).encode())<256*1024
    assert verify(packet,source_root=source,objects=objects)==v

@pytest.mark.parametrize('case',['raster_missing','summary_corrupt','source_missing','source_corrupt','candidate_hash','input_revision','substitution','arbitrary_path'])
def test_actual_byte_or_lineage_failure(tmp_path,case):
    packet,source,objects=prepared(tmp_path)
    raster=next(objects.glob('*.tif'));summary=next(objects.glob('*.json'))
    if case=='raster_missing':raster.unlink()
    if case=='summary_corrupt':summary.write_bytes(b'{}')
    if case=='source_missing':next(source.iterdir()).unlink()
    if case=='source_corrupt':next(source.iterdir()).write_bytes(b'corrupt')
    if case=='candidate_hash':packet['candidate']['artifacts']['ndvi_raster']['sha256']='0'*64
    if case=='input_revision':packet['prepare_request']['validation']['input_revision']=2
    if case=='substitution':raster.write_bytes(summary.read_bytes())
    if case=='arbitrary_path':packet['path']='/etc/passwd'
    with pytest.raises((ValueError,OSError)):verify(packet,source_root=source,objects=objects)

def test_explicit_matching_month_remains_unverified(tmp_path):
    packet,source,objects=prepared(tmp_path,month=5)
    v=verify(packet,source_root=source,objects=objects)
    assert v['summary']['metadata']['month']==5 and v['summary']['metadata']['period_verified'] is False

def test_display_mercator_asymmetric_grid_known_nearest_positions():
    import base64
    import numpy as np
    from rasterio.io import MemoryFile
    from rasterio.transform import from_bounds
    from gis_worker.geotiff_publication_child import render
    values=np.array([[-1,0,-9999],[.25,.5,.75],[1,-9999,-1],[0,1,.5]],dtype='float64')
    with MemoryFile() as memory:
        with memory.open(driver='GTiff',width=3,height=4,count=1,dtype='float64',crs='EPSG:4326',
                transform=from_bounds(100,0,103,80,3,4),nodata=-9999) as dst:dst.write(values,1)
        scientific=memory.read();sha=hashlib.sha256(scientific).hexdigest()
        with memory.open() as src:
            image=render(src,'ndvi',p)
            # Mercator target row centres correspond to latitudes 76.50,
            # 65.93,46.39,17.19 degrees: source rows 0,0,1,3 (nearest).
            expected=values[[0,0,1,3],:]
            assert image['png_base64']==p._png(expected,expected!=-9999,'ndvi')['png_base64']
            assert image['width']==3 and image['height']==4
            assert image['render_bounds'][3]==pytest.approx(15538711.0963,abs=.001)
            assert image['image_sha256']==hashlib.sha256(base64.b64decode(image['png_base64'])).hexdigest()
            assert np.array_equal(src.read(1),values)
        memory.seek(0)
        assert hashlib.sha256(memory.read()).hexdigest()==sha
