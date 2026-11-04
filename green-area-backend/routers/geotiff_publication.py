"""Admin Local publication and explicit signed-in source-footprint reader."""
from typing import Annotated,Literal
from uuid import UUID
from fastapi import APIRouter,Request,Query,HTTPException
from fastapi.encoders import jsonable_encoder
from pydantic import Field
from starlette.responses import JSONResponse
from gis_schemas import GisInput,Revision,Hash,Province,Reason
from gis_service import gis_error,safe_output
from routers.gis import Actor,Service,Key,GisRoute

router=APIRouter(prefix='/gis',route_class=GisRoute)

class GeoPublicationInput(GisInput):
    edition_id:UUID
    expected_dataset_revision:Revision
    expected_active_edition_id:UUID|None
    expected_input_revision:Revision
    input_hash:Hash
    validation_result_id:UUID
    certificate_id:UUID
    source_sha256:Hash
    province:Province
    data_year:Annotated[int,Field(strict=True,ge=1980,le=2200)]
    month:Annotated[int,Field(strict=True,ge=0,le=12)]
    product:Literal['ndvi','lst']
    profile:Literal['ndvi_ready','lst_celsius_ready','lst_kelvin_ready']
    method_version:Literal['geotiff-grid-celsius-v1']
    coverage_mode:Literal['source_footprint_intersection']
    policy_version:Literal['local-declared-period-footprint-v1']
    acknowledge_unverified_period:Literal[True]
    acknowledge_limited_coverage:Literal[True]
    reason:Reason

class GeoWithdrawalInput(GeoPublicationInput):
    replacement_edition_id:UUID|None

class PublishedQuery(GisInput):
    province:Province
    data_year:Annotated[int,Field(ge=1980,le=2200)]
    month:Annotated[int,Field(ge=0,le=12)]
    product:Literal['ndvi','lst']
    coverage_mode:Literal['source_footprint_intersection']

def publication(request):
    provider=getattr(request.app.state,'gis_geotiff_publication',None)
    if provider is None:raise gis_error(503,'GIS_GEOTIFF_PUBLICATION_DISABLED','ยังไม่เปิด Local GeoTIFF Publication')
    provider.attest();return provider

def mutate(dataset_id,operation,body,request,actor,service,key):
    if service.read(actor,'me').get('admin') is not True:raise gis_error(403,'GIS_FORBIDDEN','เฉพาะ Admin เปิดใช้หรือถอนฉบับได้')
    provider=publication(request);payload={'dataset_id':str(dataset_id),**jsonable_encoder(body)}
    params={'p_actor':actor,'p_request_id':str(key),'p_operation':operation,'p_payload':payload,'p_proof':None,'p_backend_local':True,'p_probe':True}
    probe=service._rpc('gis_geotiff_publication_command',params)
    if probe['body'].get('receipt_exists'):return JSONResponse(safe_output(probe['body']),headers={'Cache-Control':'no-store'})
    target=body.replacement_edition_id if operation=='withdraw' else body.edition_id
    with provider.store._lock():
        proof=None
        if target is not None:
            info=service._rpc('gis_geotiff_prepare_read',{'p_actor':actor,'p_edition':str(target)})
            status=service._rpc('gis_geotiff_publication_status',{'p_actor':actor,'p_edition':str(target)})
            try:proof=provider.fresh_proof({**info,**status})
            except HTTPException:raise
            except (OSError,ValueError,KeyError,TypeError):raise gis_error(409,'GIS_GEOTIFF_VERIFICATION_FAILED','ไฟล์จริงหรือ Scope ไม่พร้อมเปิดใช้') from None
        result=service._rpc('gis_geotiff_publication_command',{**params,'p_probe':False,'p_proof':proof})
    return JSONResponse(safe_output(result['body']),status_code=result['status'],headers={'Cache-Control':'no-store'})

@router.post('/datasets/{dataset_id}/geotiff-publication/activation')
def activate(dataset_id:UUID,body:GeoPublicationInput,request:Request,actor:Actor,service:Service,key:Key):return mutate(dataset_id,'activate',body,request,actor,service,key)
@router.post('/datasets/{dataset_id}/geotiff-publication/rollback')
def rollback(dataset_id:UUID,body:GeoPublicationInput,request:Request,actor:Actor,service:Service,key:Key):return mutate(dataset_id,'rollback',body,request,actor,service,key)
@router.post('/datasets/{dataset_id}/geotiff-publication/withdrawal')
def withdraw(dataset_id:UUID,body:GeoWithdrawalInput,request:Request,actor:Actor,service:Service,key:Key):return mutate(dataset_id,'withdraw',body,request,actor,service,key)
@router.get('/editions/{edition_id}/geotiff-publication')
def status(edition_id:UUID,request:Request,actor:Actor,service:Service):
    publication(request)
    return JSONResponse(safe_output(service._rpc('gis_geotiff_publication_status',{'p_actor':actor,'p_edition':str(edition_id)})),headers={'Cache-Control':'no-store'})
@router.get('/published-geotiff')
def published(request:Request,actor:Actor,service:Service,query:Annotated[PublishedQuery,Query()]):
    return JSONResponse(publication(request).bundle(service,actor,query.province,query.data_year,query.month,query.product),headers={'Cache-Control':'no-store','Pragma':'no-cache'})
