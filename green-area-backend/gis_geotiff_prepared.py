"""Minimal binary adapter over the existing owned immutable prepared store."""
import hashlib
import json
import os
from uuid import uuid4
from gis_ldd_prepared import LocalPreparedStore
from gis_ldd_storage import DISK_QUOTA
from gis_service import gis_error
from gis_worker.geotiff_prepare_provider import check_request,names,stage_key,descriptors,VERIFIER

class LocalPreparedGeoTiffStore(LocalPreparedStore):
    STORAGE_NAME='geotiff-prepared'
    OWNER_SCOPE='gis-geotiff-prepared-v1'
    REQUIRED_MIGRATION=41

    def _source(self,request):
        self.source_store.attest();m=request['validation']['manifest']
        raw=self._safe_read(self.source_store.objects/(m['sha256']+'.tif'))
        if len(raw)!=m['byte_size'] or hashlib.sha256(raw).hexdigest()!=m['sha256']:raise ValueError('PREPARE_SOURCE_CHANGED')

    def object_path(self,kind,descriptor):
        import re
        if kind not in ('ndvi_raster','lst_raster','ndvi_summary','lst_summary') or not isinstance(descriptor,dict) or set(descriptor)!={'sha256','byte_size'}:
            raise ValueError('PREPARE_ARTIFACT_INVALID')
        if not isinstance(descriptor['sha256'],str) or not re.fullmatch('[a-f0-9]{64}',descriptor['sha256']):raise ValueError('PREPARE_ARTIFACT_INVALID')
        return self.objects/(descriptor['sha256']+('.tif' if kind.endswith('_raster') else '.json'))

    def certify_files(self,request,candidate):
        self.attest();check_request(request);self._source(request)
        with self._lock():
            if self._usage()>DISK_QUOTA:raise gis_error(507,'GIS_PREPARE_STORAGE_LIMIT','พื้นที่เตรียมข้อมูลเต็ม')
            proof=self.verifier(request)
            if not isinstance(proof,dict) or proof.get('verifier_version')!=VERIFIER or {k:v for k,v in proof.items() if k!='verifier_version'}!=candidate:
                raise gis_error(409,'GIS_PREPARE_VERIFICATION_FAILED','ผลไม่ตรง Trusted Verification')
            directory=self.staging/stage_key(request)
            outputs={k:self._safe_read(directory/n) for k,n in names(request).items()}
            if descriptors(outputs)!=proof['artifacts']:raise ValueError('PREPARE_ARTIFACT_CHANGED')
            if self._usage()+sum(map(len,outputs.values()))>DISK_QUOTA:raise gis_error(507,'GIS_PREPARE_STORAGE_LIMIT','พื้นที่เตรียมข้อมูลเต็ม')
            for kind,raw in outputs.items():
                path=self.object_path(kind,proof['artifacts'][kind])
                if path.exists():
                    if self._safe_read(path)!=raw:raise ValueError('PREPARE_IMMUTABLE_CONFLICT')
                    continue
                pending=self.objects/('.pending-'+uuid4().hex)
                with pending.open('xb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
                try:
                    try:os.link(pending,path)
                    except FileExistsError:
                        if self._safe_read(path)!=raw:raise ValueError('PREPARE_IMMUTABLE_CONFLICT')
                finally:pending.unlink()
            self.read_files(request,proof['artifacts']);return proof

    def read_files(self,request,artifacts):
        self.attest();check_request(request);self._source(request)
        if not isinstance(artifacts,dict) or set(artifacts)!=set(names(request)):raise ValueError('PREPARE_ARTIFACT_INVALID')
        raw={k:self._safe_read(self.object_path(k,v)) for k,v in artifacts.items()}
        if descriptors(raw)!=artifacts:raise ValueError('PREPARE_ARTIFACT_CHANGED')
        metric=request['validation']['manifest']['metric'];summary=json.loads(raw[metric+'_summary'])
        meta=summary['metadata'];v=request['validation']
        for key in ('dataset_id','edition_id','validation_result_id','method_version','month'):
            if meta[key]!=request[key]:raise ValueError('PREPARE_LINEAGE_CHANGED')
        for key in ('input_hash','input_revision','province','data_year'):
            if meta[key]!=v[key]:raise ValueError('PREPARE_LINEAGE_CHANGED')
        if meta['source_sha256']!=v['manifest']['sha256'] or summary['raster_sha256']!=artifacts[metric+'_raster']['sha256']:
            raise ValueError('PREPARE_LINEAGE_CHANGED')
        if meta['complete_province_inventory'] is not False or meta['period_verified'] is not False:raise ValueError('PREPARE_SCOPE_CHANGED')
        return {'summary':summary}
