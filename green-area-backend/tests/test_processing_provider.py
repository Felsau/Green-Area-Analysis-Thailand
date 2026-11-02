"""Known numeric synthetic scene expectations; never any Earth Engine calls."""
from copy import deepcopy
from datetime import date
import hashlib
import json
from pathlib import Path
import shutil
from types import SimpleNamespace
import pytest

from gis_worker import processing_provider as p
from gis_worker.processing_worker import ProcessingWorker, ProcessingClient
from gis_worker.worker import WorkerError

BACKEND = Path(__file__).resolve().parents[1]
ID = '11111111-1111-4111-8111-111111111111'

@pytest.fixture
def legacy(tmp_path):
    for name, source in {'gee_utils.py':BACKEND/'gee_utils.py', 'ndvi_compute.py':BACKEND/'routers/ndvi/compute.py',
            'lst.py':BACKEND/'routers/lst.py'}.items():
        shutil.copyfile(source,tmp_path/name)
    return tmp_path

def request(metric='ndvi', scenario='standard', month=0, district=None, attempt=1):
    start = date(2025,month or 1,1)
    end = date(2026,1,1) if month in (0,12) else date(2025,month+1,1)
    manifest = {'schema_version':3, 'provider':'offline_synthetic', 'mode':'offline_synthetic',
        'provenance':'gis-processing-offline-v1', 'data_kind':'raster', 'province':'Bangkok Metropolis',
        'district':district, 'metric':metric, 'data_year':2025, 'month':month, 'scenario':scenario,
        'start_date':start.isoformat(), 'end_date':end.isoformat(), 'scale_m':500 if district is None else 100,
        'processing_version':p.BUILD, **p.source_spec(metric,scenario)}
    return {'processing_id':ID,'manifest':manifest,'input_hash':'a'*64,'input_revision':1,'attempt_number':attempt}

def test_exact_legacy_specs_read_without_importing_or_executing(legacy):
    result = p.legacy_spec(legacy)
    assert result == {'ndvi_bands':['B8','B4'],'cs_threshold':0.6,'reflectance_divisor':10000,
        'annual_cloud':20,'annual_cloud_fallback':80,'monthly_cloud':80,'lst_cloud':40,
        'lst_mask_bits':[3,4], 'lst_operations':[('multiply',0.00341802),('add',149.0),('subtract',273.15)]}

@pytest.mark.parametrize('metric', ['ndvi','lst'])
@pytest.mark.parametrize('month', range(13))
def test_actual_numeric_scene_medians_and_legacy_scale_expected_results(legacy, metric, month):
    result = p.OfflineProcessingAdapter(legacy_root=legacy).compute(request(metric=metric,month=month))
    expected = ({'valid_pixels':2,'mean':0.4921,'min':0.4286,'max':0.5556} if month == 0 else
        {'valid_pixels':3,'mean':0.1614,'min':-0.5,'max':0.5556}) if metric == 'ndvi' else {
            'valid_pixels':2,'mean':29.66,'min':22.82,'max':36.5}
    assert result['valid'] is True and result['error_code'] is None
    assert result['statistics'] == expected
    assert result['mode'] == 'offline_synthetic' and result['synthetic'] is True
    assert result['artifact_sha256'] == p.source_spec(metric,'standard')['sha256']
    assert len(json.dumps(result).encode()) <= 16384

@pytest.mark.parametrize('metric', ['ndvi','lst'])
def test_all_masked_no_data_is_failed_not_zero_success(legacy, metric):
    result = p.OfflineProcessingAdapter(legacy_root=legacy).compute(request(metric,'no_data'))
    assert not result['valid'] and result['error_code'] == 'PROCESSING_NO_VALID_PIXELS'
    assert result['statistics'] == {'valid_pixels':0,'mean':None,'min':None,'max':None}

@pytest.mark.parametrize('metric', ['ndvi','lst'])
def test_simulated_transient_boundary_then_real_numeric_computation(legacy, metric):
    waits=[]
    adapter = p.OfflineProcessingAdapter(legacy_root=legacy,boundary_wait=waits.append)
    first = adapter.compute(request(metric,'transient_once'))
    assert not first['valid'] and first['error_code'] == 'TRANSIENT_SYNTHETIC'
    assert waits == [12]
    next_result = adapter.compute(request(metric,'transient_once',attempt=2))
    regular = adapter.compute(request(metric))
    assert next_result['valid'] and next_result['statistics'] == regular['statistics']
    assert waits == [12]

def test_scope_is_only_routing_not_fabricated_spatial_measurement(legacy):
    adapter = p.OfflineProcessingAdapter(legacy_root=legacy)
    province = request()
    district = request(district='BangKapi')
    a,b = adapter.compute(province),adapter.compute(district)
    assert a['statistics'] == b['statistics']
    assert a['metadata']['scale_m'] == 500 and b['metadata']['scale_m'] == 100
    for metric,scenario in p.CATALOG:
        raw=(p.FIXTURE_ROOT/f'processing_{metric}_{scenario}.json').read_bytes()
        source=json.loads(raw)
        assert source['synthetic_year_template'] is True and source['spatially_representative'] is False
        assert 'expected_results' not in source
        assert hashlib.sha256(raw).hexdigest()==p.CATALOG[(metric,scenario)][0]

@pytest.mark.parametrize('field,value', [('provider','gee_live'),('mode','gee_live'),('fixture_id','../../private'),
    ('sha256','0'*64),('byte_size',123),('data_year',True),('data_year',2010),('month',True),
    ('month',13),('scale_m',100),('end_date','2025-12-31'),('processing_version','other'),
    ('legacy_pipeline_sha256',{}),('source_collections',['https://example.invalid']),('bands',['B4','B8'])])
def test_closed_metadata_and_date_contract_rejects_tampering(field,value):
    value_request = request()
    value_request['manifest'][field]=value
    with pytest.raises(p.ProcessingError,match='PROCESSING_INPUT_INVALID'):
        p.check_request(value_request)

@pytest.mark.parametrize('extra', ['path','url','command','sql','expected_results'])
def test_arbitrary_payload_authority_rejected(extra):
    value=request()
    value[extra]='untrusted'
    with pytest.raises(p.ProcessingError):
        p.check_request(value)

def test_source_hash_drift_fails_before_ast_or_numeric_result(legacy):
    (legacy/'gee_utils.py').write_text('raise RuntimeError("MUST_NOT_EXECUTE")',encoding='utf-8')
    with pytest.raises(p.ProcessingError,match='PROCESSING_LEGACY_SOURCE_CHANGED'):
        p.OfflineProcessingAdapter(legacy_root=legacy).compute(request())

def test_fixture_hash_drift_is_rejected_before_computation(legacy,tmp_path):
    (tmp_path/'processing_ndvi_standard.json').write_text('{}',encoding='utf-8')
    with pytest.raises(p.ProcessingError,match='PROCESSING_FIXTURE_INVALID'):
        p.OfflineProcessingAdapter(fixture_root=tmp_path,legacy_root=legacy).compute(request())

def test_live_adapter_gate_precedes_all_source_reads(monkeypatch):
    def forbidden(*_a,**_k):
        raise AssertionError('Live gate read local data before approval')
    monkeypatch.setattr(Path,'read_bytes',forbidden)
    with pytest.raises(p.ProcessingError,match='GEE_LIVE_NOT_APPROVED'):
        p.LiveGeeAdapter().compute(request(),credentials='unused unit placeholder')

def test_report_metadata_copy_and_failure_safety():
    r=request()
    report=p.report_failure(r,'NATIVE_TIMEOUT')
    assert report['metadata']==r['manifest'] and report['valid'] is False
    assert not {'path','url','token','credentials'} & report.keys()
    report['metadata']['province']='different'
    assert r['manifest']['province']=='Bangkok Metropolis'

def test_native_source_drift_is_infrastructure_failure_not_invalid_gis(monkeypatch):
    class Drift:
        def compute(self, _request):
            raise p.ProcessingError('PROCESSING_LEGACY_SOURCE_CHANGED')
    monkeypatch.setattr(p,'OfflineProcessingAdapter',Drift)
    result=p.validate(request())
    assert not result['valid'] and result['error_code']=='NATIVE_PROCESS_FAILED'

def readiness():
    return {'status':'ready','worker_role':'gis_native_worker','subject':ID,'database_name':'postgres',
        'cluster_name':'green-area-gis-t0','mode':'local_synthetic','contract_version':'1.0.0-processing-offline',
        'migration_versions':list(range(27,36)),'runtime_instance':'a'*32,'baseline_fingerprint':'b'*64}

class Client:
    subject=ID
    expected={'runtime_instance':'a'*32,'baseline_fingerprint':'b'*64}
    def __init__(self,response=None):
        self.response=response or readiness()
        self.calls=[]
    def call(self,name,payload):
        self.calls.append((name,payload))
        return self.response if name=='gis_processing_readiness' else {'job':None}

def test_processing_rpc_separate_protocol_and_existing_daemon_hooks():
    client=Client()
    worker=ProcessingWorker(client)
    worker.call('claim')
    assert [x[0] for x in client.calls]==['gis_processing_readiness','gis_processing_worker']
    assert ProcessingClient.RPC_NAMES==('gis_processing_worker','gis_processing_readiness')
    assert worker.CHILD_SCRIPT=='processing_child.py'
    assert worker.build_native_request({**request(),'id':ID,'lease_token':ID})==request()

@pytest.mark.parametrize('field,value',[('mode','gee_live'),('subject','other'),('contract_version','wrong'),
    ('migration_versions',list(range(27,35))),('worker_role','service_role')])
def test_worker_target_guard_before_claim(field,value):
    response=readiness()
    response[field]=value
    client=Client(response)
    with pytest.raises(WorkerError,match='WORKER_TARGET_REJECTED'):
        ProcessingWorker(client).call('claim')
    assert len(client.calls)==1
