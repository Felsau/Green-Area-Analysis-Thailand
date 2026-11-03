"""Private Local Published provider. No legacy/GEE reads or cache mutations."""
from copy import deepcopy
import json
from fastapi import HTTPException
from gis_publication import SourceIdentity
from gis_service import gis_error,safe_output
from ttl_cache import TTLCache

VERSION='ldd-publication-bytes-v1'
MAIN=[('U','ชุมชนและสิ่งปลูกสร้าง','e5534b'),('A','พื้นที่เกษตรกรรม','f2c94c'),
 ('F','พื้นที่ป่าไม้','1a9850'),('W','พื้นที่น้ำ','3d85c6'),('M','พื้นที่เบ็ดเตล็ด','9aa0a6')]

class LocalLddPublication:
    def __init__(self,runtime,store,verifier):
        if store.runtime is not runtime or not callable(verifier):raise ValueError('PRIVATE_LOCAL_VERIFIER_REQUIRED')
        self.runtime,self.store,self.verifier=runtime,store,verifier
        # Small projections only. Never cache pointer lookups or geometry. All
        # hits still follow fresh source/object SHA/size/lineage checks.
        self.summary_cache=TTLCache(60,32)

    def attest(self):
        if (getattr(self.runtime,'ldd_publication_enabled',False) is not True
            or self.runtime.sandbox_activation_enabled is not False
            or 39 not in self.runtime.require_ready().get('migration_versions',[])):
            raise gis_error(503,'GIS_LDD_PUBLICATION_DISABLED','ยังไม่เปิด Local LDD Publication')
        self.store.attest()

    def fresh_proof(self,info):
        """Caller holds immutable-store lock until the SQL mutation returns."""
        self.attest();candidate=info.get('candidate')
        if not info.get('ready_for_publication') or not info.get('certificate') or not candidate:
            raise gis_error(409,'GIS_PUBLICATION_NOT_READY','ฉบับข้อมูลยังไม่พร้อมเปิดใช้')
        files=self.store.read_files(info['prepare_request'],candidate['artifacts'])
        try:report=self.verifier({'prepare_request':info['prepare_request'],'candidate':candidate})
        except Exception:raise gis_error(409,'GIS_LDD_VERIFICATION_FAILED','ตรวจไฟล์จริงก่อนเปิดใช้ไม่สำเร็จ') from None
        if report!={**candidate,'verifier_version':VERSION}:
            raise gis_error(409,'GIS_LDD_VERIFICATION_FAILED','ไฟล์จริงไม่ตรงกับผลที่ตรวจไว้')
        self.store.read_files(info['prepare_request'],candidate['artifacts'])
        meta=files['ldd_summary']['metadata']
        identity=SourceIdentity(namespace='published',product='landuse',**{k:meta[k] for k in (
            'dataset_id','edition_id','validation_result_id','input_hash','source_sha256','province','data_year','month','method_version')})
        # Admission checks the same complete DTO shape used by the Dashboard.
        # A verified but unsupported-size artifact must not replace a good pointer.
        self.display_bundle(files,identity,'0'*64,2147483647)
        return {'certificate_id':info['certificate']['id'],'report':report}

    def display_bundle(self,files,identity,snapshot,revision):
        bundle={'snapshot_id':snapshot,'dataset_revision':revision,'source_identity':identity.model_dump(mode='json'),
            'cache_namespace':identity.cache_namespace(),'coverage_mode':'validated_source_footprint',
            'complete_province_inventory':False,'local_only':True,'geometry':deepcopy(files['ldd_geometry']),
            'summary':files['ldd_summary'],'legend':[{'code':c,'name_th':n,'color':color} for c,n,color in MAIN]}
        if len(json.dumps(bundle,ensure_ascii=False).encode())>2*1024**2:
            raise gis_error(413,'GIS_LDD_DISPLAY_LIMIT','Published เกินขนาด Local MVP ไม่มีการตัด Geometry เงียบ ๆ')
        return bundle

    def bundle(self,service,actor,province,year):
        self.attest();args={'p_actor':actor,'p_province':province,'p_year':year,'p_expected':None}
        info=service._rpc('gis_ldd_published_read',args)
        try:
            files=self.store.read_files(info['prepare_request'],info['candidate']['artifacts'])
            identity=SourceIdentity.model_validate(info['source_identity'])
            meta=files['ldd_summary']['metadata']
            for key in ('dataset_id','edition_id','validation_result_id','input_hash','source_sha256','province','data_year','month','method_version'):
                if meta[key]!=identity.model_dump(mode='json')[key]:raise ValueError('SOURCE_LINEAGE_CHANGED')
            if files['ldd_geometry']['metadata']!=meta or meta['complete_province_inventory'] is not False:
                raise ValueError('SOURCE_COVERAGE_CHANGED')
        except HTTPException:raise
        except (OSError,ValueError,KeyError,TypeError):
            service._rpc('gis_ldd_published_unavailable',{'p_actor':actor,'p_province':province,'p_year':year,
                'p_snapshot':info['snapshot_id'],'p_certificate':info['certificate_id']})
            raise gis_error(409,'GIS_LDD_PUBLISHED_UNAVAILABLE','ไฟล์ Published หายหรือเสียหาย ไม่มีการใช้ Legacy แทน') from None
        cache_key=(identity.cache_namespace(),info['snapshot_id'],meta['input_revision'],
            *(info['candidate']['artifacts'][k]['sha256'] for k in ('ldd_geometry','ldd_summary')))
        cached=self.summary_cache.get(cache_key)
        if cached is None:
            cached=json.dumps({'summary':files['ldd_summary'],'legend':[{'code':c,'name_th':n,'color':color} for c,n,color in MAIN]},ensure_ascii=False)
            self.summary_cache.set(cache_key,cached)
        projection=json.loads(cached)
        bundle=self.display_bundle({**files,'ldd_summary':projection['summary']},identity,info['snapshot_id'],info['dataset']['revision'])
        service._rpc('gis_ldd_published_read',{**args,'p_expected':info['snapshot_id']})
        return safe_output(bundle)
