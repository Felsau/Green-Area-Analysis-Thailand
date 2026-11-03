"""Linux scientific preparation tests using synthetic Shapefile bytes only."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest
from gis_worker import ldd_prepare_provider as prep
from gis_worker import ldd_provider as ldd

ROOT = Path(__file__).resolve().parents[1]/'gis_worker/fixtures'
ID = '11111111-1111-4111-8111-111111111111'


def request(raw=None, **changes):
    raw = raw or (ROOT/'ldd_valid.zip').read_bytes()
    validation={'upload_id':ID,'manifest':{'schema_version':1,'provider':'real','sha256':hashlib.sha256(raw).hexdigest(),
        'byte_size':len(raw),'provenance':'local-ldd-upload-v1','crs':'EPSG:32647','data_kind':'polygon','attributes':list(ldd.REQUIRED_FIELDS)},
        'input_hash':'a'*64,'input_revision':1,'attempt_number':1,'province':'Bangkok Metropolis','data_year':2026,'encoding':'auto'}
    return {'validation':validation,'dataset_id':ID,'edition_id':ID,'validation_result_id':ID,'job_id':ID,'method_version':prep.METHOD,**changes}


def setup(tmp_path, raw=None):
    raw=raw or (ROOT/'ldd_valid.zip').read_bytes();packet=request(raw)
    source=tmp_path/'source';stage=tmp_path/'stage';source.mkdir();stage.mkdir()
    (source/(packet['validation']['manifest']['sha256']+'.zip')).write_bytes(raw)
    return packet,source,stage


def test_actual_geometry_and_summary_known_source_area(tmp_path):
    packet,source,stage=setup(tmp_path)
    before=hashlib.sha256(next(source.iterdir()).read_bytes()).hexdigest()
    candidate=prep.prepare(packet,source_root=source,staging_root=stage)
    verified=prep.verify(packet,source_root=source,staging_root=stage)
    assert candidate['valid'] is True and verified['verifier_version']==prep.VERIFIER
    assert {k:v for k,v in verified.items() if k!='verifier_version'}==candidate
    outputs=prep.build(packet,source_root=source)
    geometry=json.loads(outputs['ldd_geometry']);summary=json.loads(outputs['ldd_summary'])
    assert geometry['type']=='FeatureCollection' and len(geometry['features'])==3
    assert summary['feature_count']==3 and summary['total_area_m2']==6400
    assert sum(summary['area_by_code_m2'].values())==6400
    assert sum(summary['area_by_main_m2'].values())==6400
    assert geometry['metadata']['display_crs']=='EPSG:4326'
    assert geometry['metadata']['complete_province_inventory'] is False
    assert all(100<f['geometry']['coordinates'][0][0][0]<102 for f in geometry['features'])
    assert before==hashlib.sha256(next(source.iterdir()).read_bytes()).hexdigest()
    assert prep.prepare(packet,source_root=source,staging_root=stage)==candidate


@pytest.mark.parametrize('field,value',[('dataset_id','22222222-2222-4222-8222-222222222222'),
 ('edition_id','22222222-2222-4222-8222-222222222222'),('validation_result_id','22222222-2222-4222-8222-222222222222')])
def test_artifact_lineage_is_checked_against_bytes(tmp_path,field,value):
    packet,source,stage=setup(tmp_path);prep.prepare(packet,source_root=source,staging_root=stage)
    packet[field]=value
    with pytest.raises(ldd.LddError,match='ARTIFACT_MISMATCH'):prep.verify(packet,source_root=source,staging_root=stage)


@pytest.mark.parametrize('field,value',[('data_year',2025),('input_revision',2),('input_hash','b'*64)])
def test_year_revision_hash_mismatch_cannot_verify(tmp_path,field,value):
    packet,source,stage=setup(tmp_path);prep.prepare(packet,source_root=source,staging_root=stage)
    packet['validation'][field]=value
    with pytest.raises(ldd.LddError,match='ARTIFACT_MISMATCH'):prep.verify(packet,source_root=source,staging_root=stage)


def test_wrong_province_cannot_prepare(tmp_path):
    packet,source,stage=setup(tmp_path);packet['validation']['province']='Chiang Mai'
    with pytest.raises(ldd.LddError):prep.prepare(packet,source_root=source,staging_root=stage)


@pytest.mark.parametrize('filename',['ldd_unknown.zip','ldd_missing_dbf.zip','zip_traversal.zip','zip_symlink.zip'])
def test_invalid_and_unsafe_source_cannot_prepare(tmp_path,filename):
    packet,source,stage=setup(tmp_path,(ROOT/filename).read_bytes())
    with pytest.raises(ldd.LddError):prep.prepare(packet,source_root=source,staging_root=stage)


@pytest.mark.parametrize('kind',['ldd_geometry','ldd_summary'])
def test_missing_or_corrupt_output_cannot_verify(tmp_path,kind):
    packet,source,stage=setup(tmp_path);prep.prepare(packet,source_root=source,staging_root=stage)
    path=stage/prep.stage_key(packet)/prep.NAMES[kind]
    raw=path.read_bytes();path.write_bytes(raw+b' ')
    with pytest.raises(ldd.LddError,match='ARTIFACT_MISMATCH'):prep.verify(packet,source_root=source,staging_root=stage)
    path.unlink()
    with pytest.raises(OSError):prep.verify(packet,source_root=source,staging_root=stage)


@pytest.mark.parametrize('filename',['ldd_cp874.zip','ldd_composite_a.zip'])
def test_encoding_and_composite_codes_not_lost(tmp_path,filename):
    packet,source,stage=setup(tmp_path,(ROOT/filename).read_bytes())
    candidate=prep.prepare(packet,source_root=source,staging_root=stage)
    assert prep.verify(packet,source_root=source,staging_root=stage)['valid']
    summary=json.loads((stage/prep.stage_key(packet)/'summary.json').read_bytes())
    if 'composite' in filename:assert any('/' in key for key in summary['area_by_code_m2'])
    assert candidate['valid']


@pytest.mark.parametrize('change',[{'path':'/tmp/x'},{'method_version':'unknown'},{'ready':True},{'job_id':'../x'}])
def test_arbitrary_requests_rejected(change):
    with pytest.raises(ldd.LddError):prep.check_request(request(**change))
