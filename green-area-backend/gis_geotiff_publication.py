"""Explicit Local uploaded-raster source. No legacy/GEE/cache writes."""
from copy import deepcopy
import json
import hashlib
from fastapi import HTTPException
from gis_publication import SourceIdentity
from gis_service import gis_error,safe_output
from gis_ldd_publication import LocalLddPublication

VERSION='geotiff-publication-bytes-v1'
POLICY='local-declared-period-footprint-v1'
RENDER_VERSION='geotiff-mercator-nearest-v1'


class LocalGeoTiffPublication(LocalLddPublication):
    def attest(self):
        if (getattr(self.runtime,'geotiff_publication_enabled',False) is not True
            or self.runtime.sandbox_activation_enabled is not False
            or 42 not in self.runtime.require_ready().get('migration_versions',[])):
            raise gis_error(503,'GIS_GEOTIFF_PUBLICATION_DISABLED','ยังไม่เปิด Local GeoTIFF Publication')
        self.store.attest()

    def fresh_files(self,info):
        self.attest();request=info['prepare_request'];candidate=info['candidate']
        files=self.store.read_files(request,candidate['artifacts'])
        try:verified=self.verifier({'prepare_request':request,'candidate':candidate})
        except Exception:raise gis_error(503,'GIS_GEOTIFF_VERIFIER_UNAVAILABLE','ระบบตรวจไฟล์ไม่พร้อมชั่วคราว กรุณาลองใหม่ โดยไม่เพิกถอนฉบับข้อมูล') from None
        if (not isinstance(verified,dict) or set(verified)!={'report','summary','raster'}
            or verified.get('report')!={**candidate,'verifier_version':VERSION}
            or verified.get('summary')!=files['summary']):
            raise gis_error(503,'GIS_GEOTIFF_VERIFIER_UNAVAILABLE','ยังยืนยันผลตรวจไฟล์ไม่ได้ กรุณาลองใหม่ โดยไม่เพิกถอนฉบับข้อมูล')
        self.store.read_files(request,candidate['artifacts'])
        meta=verified['summary']['metadata'];identity=info['identity']
        for key in ('dataset_id','edition_id','validation_result_id','input_revision','input_hash','source_sha256','province','data_year','month','method_version','coverage_mode'):
            if meta[key]!=identity[key]:raise ValueError('PUBLICATION_LINEAGE_CHANGED')
        metric=request['validation']['manifest']['metric'];raster=verified['raster']
        if (identity['policy_version']!=POLICY or identity['product']!=metric or identity['profile']!=meta['source_profile']
            or identity['artifacts']!=candidate['artifacts'] or identity['crs']!='EPSG:4326' or meta['crs']!='EPSG:4326'
            or identity['output_units']!=meta['output_units'] or meta['period_verified'] is not False
            or meta['complete_province_inventory'] is not False or raster['artifact_sha256']!=candidate['artifacts'][metric+'_raster']['sha256']):
            raise ValueError('PUBLICATION_SCOPE_CHANGED')
        return verified

    def display_bundle(self,files,identity,snapshot,revision):
        source=SourceIdentity(namespace='published',product=identity['product'],**{k:identity[k] for k in (
            'dataset_id','edition_id','validation_result_id','input_hash','source_sha256','province','data_year','month','method_version')})
        summary=deepcopy(files['summary']);summary.pop('preview',None)
        r=files['raster']
        render_identity={k:r[k] for k in ('render_crs','render_method_version','render_bounds','render_transform','image_sha256','width','height','bounds')}
        if r['render_crs']!='EPSG:3857' or r['render_method_version']!=RENDER_VERSION:raise ValueError('PUBLICATION_RENDER_UNSUPPORTED')
        rendered=hashlib.sha256(json.dumps([snapshot,render_identity],sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
        bundle={'snapshot_id':rendered,'catalog_snapshot_id':snapshot,'dataset_revision':revision,'source_identity':source.model_dump(mode='json'),
            'cache_namespace':source.cache_namespace(),'publication_identity':identity,'certificate_id':identity['certificate_id'],
            'local_only':True,'provenance':'local_uploaded_ready_profile','period_verified':False,'complete_province_inventory':False,
            'coverage_mode':'source_footprint_intersection','summary':summary,'raster':files['raster'],
            'legend':{'min':-1 if identity['product']=='ndvi' else -100,'max':1 if identity['product']=='ndvi' else 100,
                'units':identity['output_units'],'palette':['ff003c','7f6e3c','00dc3c']},
            'warnings':['UPLOADED_NOT_GEE','PERIOD_DECLARED_NOT_VERIFIED','SOURCE_FOOTPRINT_NOT_PROVINCE','BOUNDARY_APPROXIMATE','NEAREST_VISUAL_SAMPLE_MAX64']}
        if len(json.dumps(bundle,ensure_ascii=False,allow_nan=False).encode())>256*1024:
            raise gis_error(413,'GIS_GEOTIFF_DISPLAY_LIMIT','Published Raster เกินขนาด Local Display')
        return bundle

    def fresh_proof(self,info):
        if not info.get('catalog_prepared') or not info.get('identity'):raise gis_error(409,'GIS_PUBLICATION_NOT_READY','ฉบับข้อมูลยังไม่พร้อมเปิดใช้')
        verified=self.fresh_files(info)
        self.display_bundle(verified,info['identity'],'0'*64,1)
        return {'certificate_id':info['identity']['certificate_id'],'identity':info['identity'],'report':verified['report']}

    def bundle(self,service,actor,province,year,month,product):
        self.attest();args={'p_actor':actor,'p_province':province,'p_year':year,'p_month':month,'p_product':product,'p_expected':None}
        info=service._rpc('gis_geotiff_published_read',args)
        try:verified=self.fresh_files(info)
        except HTTPException:raise
        except (OSError,ValueError,KeyError,TypeError):
            service._rpc('gis_geotiff_published_unavailable',{k:v for k,v in args.items() if k!='p_expected'}|{'p_snapshot':info['snapshot_id'],'p_certificate':info['certificate_id']})
            raise gis_error(409,'GIS_GEOTIFF_PUBLISHED_UNAVAILABLE','ไฟล์ Published หาย เสียหาย หรือเปลี่ยนฉบับ ไม่มีการใช้ Legacy แทน') from None
        # Cache only a tiny projection, and only AFTER original/artifact bytes
        # have been freshly recomputed. Identity binds certificate and hashes.
        key=(info['snapshot_id'],RENDER_VERSION,json.dumps(info['identity'],sort_keys=True))
        cached=self.summary_cache.get(key)
        if cached is None:
            cached=json.dumps(verified['summary'],allow_nan=False);self.summary_cache.set(key,cached)
        verified={**verified,'summary':json.loads(cached)}
        result=self.display_bundle(verified,info['identity'],info['snapshot_id'],info['dataset']['revision'])
        service._rpc('gis_geotiff_published_read',{**args,'p_expected':info['snapshot_id']})
        return safe_output(result)
