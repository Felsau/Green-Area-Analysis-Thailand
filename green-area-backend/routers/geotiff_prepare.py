"""Officer/Admin GeoTIFF preparation/preview only. No activation or raster URLs."""
from typing import Annotated
from uuid import UUID
from fastapi import APIRouter,Request,HTTPException
from fastapi.encoders import jsonable_encoder
from pydantic import Field
from starlette.responses import JSONResponse
from gis_schemas import Reason
from gis_service import gis_error,safe_output
from routers.gis import Actor,Service,Key,GisRoute
from routers.ldd_prepare import PrepareInput,VerifyInput

router=APIRouter(prefix='/gis',route_class=GisRoute)
class GeoPrepareInput(PrepareInput):
    month:Annotated[int,Field(strict=True,ge=0,le=12)]
    validation_result_id:UUID
class GeoPrepareRetry(GeoPrepareInput):
    job_id:UUID
    reason:Reason

def store_for(request,actor,service):
    if 'enqueue_validation' not in service.read(actor,'me').get('capabilities',[]):raise gis_error(403,'GIS_FORBIDDEN','ไม่มีสิทธิ์จัดการข้อมูล GIS')
    store=getattr(request.app.state,'gis_geotiff_prepared_store',None)
    if store is None:raise gis_error(503,'GIS_PREPARE_NOT_READY','ยังไม่เปิด GeoTIFF Prepare ใน Local')
    store.attest();return store

def current(service,actor,edition_id):return service._rpc('gis_geotiff_prepare_read',{'p_actor':actor,'p_edition':str(edition_id)})

def preview(service,actor,edition_id,store):
    info=current(service,actor,edition_id)
    value={k:info.get(k) for k in ('status','job','attempts','validation_result_id')}
    value.update(prepared=bool((info.get('candidate') or {}).get('valid')),ready_for_review=False,ready_for_publication=False,
        preview_only=True,local_only=True,complete_province_inventory=False,method_version='geotiff-grid-celsius-v1')
    if info.get('certificate') and info.get('ready_for_review') is True:
        try:files=store.read_files(info['prepare_request'],info['candidate']['artifacts'])
        except HTTPException:raise
        except (OSError,ValueError,KeyError):
            service._rpc('gis_geotiff_verify_revoke',{'p_actor':actor,'p_certificate':info['certificate']['id'],'p_reason':'artifact_corrupt'})
            value.update(status='verification_revoked',error_code='GIS_PREPARE_ARTIFACT_UNAVAILABLE')
        else:
            latest=current(service,actor,edition_id)
            if latest.get('ready_for_review') is not True or latest.get('certificate',{}).get('id')!=info['certificate']['id']:
                raise gis_error(409,'GIS_SOURCE_CHANGED','ฉบับข้อมูลเปลี่ยนระหว่างอ่าน')
            value.update(status='verified_for_local_review',ready_for_review=True,summary=files['summary'],certificate_id=info['certificate']['id'])
    return JSONResponse(safe_output(value),headers={'Cache-Control':'no-store'})

def command(edition_id,operation,body,request,actor,service,key):
    store=store_for(request,actor,service)
    if store._usage()>=256*1024**2:raise gis_error(507,'GIS_PREPARE_STORAGE_LIMIT','พื้นที่เตรียมข้อมูลเต็ม')
    result=service._rpc('gis_geotiff_prepare_command',{'p_actor':actor,'p_request_id':str(key),'p_operation':operation,'p_payload':{'edition_id':str(edition_id),**jsonable_encoder(body)}})
    return JSONResponse(safe_output(result['body']),status_code=result['status'],headers={'Cache-Control':'no-store'})

@router.post('/editions/{edition_id}/geotiff-prepare-jobs')
def enqueue(edition_id:UUID,body:GeoPrepareInput,request:Request,actor:Actor,service:Service,key:Key):return command(edition_id,'enqueue',body,request,actor,service,key)
@router.post('/editions/{edition_id}/geotiff-prepare-retry')
def retry(edition_id:UUID,body:GeoPrepareRetry,request:Request,actor:Actor,service:Service,key:Key):return command(edition_id,'retry',body,request,actor,service,key)
@router.get('/editions/{edition_id}/geotiff-prepared')
def prepared(edition_id:UUID,request:Request,actor:Actor,service:Service):return preview(service,actor,edition_id,store_for(request,actor,service))
@router.post('/editions/{edition_id}/geotiff-prepare-verification')
def verify(edition_id:UUID,body:VerifyInput,request:Request,actor:Actor,service:Service,key:Key):
    store=store_for(request,actor,service);info=current(service,actor,edition_id)
    if (info.get('job') or {}).get('id')!=str(body.job_id) or info.get('status')!='succeeded' or not (info.get('candidate') or {}).get('valid'):
        raise gis_error(409,'GIS_PREPARE_NOT_READY','งานยังไม่สำเร็จหรือไม่ใช่งานปัจจุบัน')
    try:proof=store.certify_files(info['prepare_request'],info['candidate'])
    except HTTPException:raise
    except (OSError,ValueError):raise gis_error(409,'GIS_PREPARE_VERIFICATION_FAILED','ไฟล์จริงไม่ผ่านการตรวจสอบ') from None
    service._rpc('gis_geotiff_verify_complete',{'p_actor':actor,'p_request_id':str(key),'p_job':str(body.job_id),'p_proof':proof})
    return preview(service,actor,edition_id,store)
