"""Admin mutation and signed-in Dashboard read, explicitly Local LDD only."""
import gzip
import json
from typing import Annotated,Literal
from uuid import UUID
from fastapi import APIRouter,Request,Query,HTTPException
from fastapi.encoders import jsonable_encoder
from pydantic import Field
from starlette.responses import JSONResponse,Response
from gis_schemas import GisInput,Revision,Hash,Province,Reason
from gis_service import gis_error,safe_output
from routers.gis import Actor,Service,Key,GisRoute

router=APIRouter(prefix='/gis',route_class=GisRoute)

class LddPublicationInput(GisInput):
    edition_id:UUID
    expected_dataset_revision:Revision
    expected_active_edition_id:UUID|None
    expected_input_revision:Revision
    input_hash:Hash
    validation_result_id:UUID|None
    source_sha256:Hash
    province:Province
    data_year:Annotated[int,Field(strict=True,ge=1980,le=2200)]
    method_version:Literal['ldd-source-area-v1','ldd-geometry-area-v2']
    coverage_mode:Literal['validated_source_footprint']
    reason:Reason

class LddWithdrawalInput(LddPublicationInput):
    replacement_edition_id:UUID|None

class PublishedQuery(GisInput):
    province:Province
    data_year:Annotated[int,Field(ge=1980,le=2200)]

class PublishedGeometryQuery(PublishedQuery):
    snapshot_id:Annotated[str,Field(pattern='^[0-9a-f]{64}$')]

def publication(request):
    provider=getattr(request.app.state,'gis_ldd_publication',None)
    if provider is None:raise gis_error(503,'GIS_LDD_PUBLICATION_DISABLED','ยังไม่เปิด Local LDD Publication')
    provider.attest();return provider

def mutate(dataset_id,operation,body,request,actor,service,key):
    if service.read(actor,'me').get('admin') is not True:raise gis_error(403,'GIS_FORBIDDEN','เฉพาะ Admin เปิดใช้หรือถอนฉบับได้')
    provider=publication(request)
    # The method is the Edition's own (the method of its preparation request, chosen by migration 052 from the
    # validation); the client's value is used only when the Edition has no preparation. SQL rechecks it.
    own=service._rpc('gis_ldd_prepare_read',{'p_actor':actor,'p_edition':str(body.edition_id)})
    method=((own or {}).get('prepare_request') or {}).get('method_version') or body.method_version
    payload={'dataset_id':str(dataset_id),**jsonable_encoder(body),'method_version':method}
    params={'p_actor':actor,'p_request_id':str(key),'p_operation':operation,'p_payload':payload,
        'p_proof':None,'p_backend_local':True,'p_probe':True}
    probe=service._rpc('gis_ldd_publication_command',params)
    if probe['body'].get('receipt_exists'):
        return JSONResponse(safe_output(probe['body']),headers={'Cache-Control':'no-store'})
    target=body.replacement_edition_id if operation=='withdraw' else body.edition_id
    with provider.store._lock():
        proof=None
        if target is not None:
            info=service._rpc('gis_ldd_prepare_read',{'p_actor':actor,'p_edition':str(target)})
            try:proof=provider.fresh_proof(info)
            except HTTPException:raise
            except (OSError,ValueError):raise gis_error(409,'GIS_LDD_VERIFICATION_FAILED','ไฟล์จริงไม่พร้อมเปิดใช้') from None
        result=service._rpc('gis_ldd_publication_command',{**params,'p_probe':False,'p_proof':proof})
    return JSONResponse(safe_output(result['body']),status_code=result['status'],headers={'Cache-Control':'no-store'})

@router.post('/datasets/{dataset_id}/ldd-publication/activation')
def activate(dataset_id:UUID,body:LddPublicationInput,request:Request,actor:Actor,service:Service,key:Key):
    return mutate(dataset_id,'activate',body,request,actor,service,key)

@router.post('/datasets/{dataset_id}/ldd-publication/rollback')
def rollback(dataset_id:UUID,body:LddPublicationInput,request:Request,actor:Actor,service:Service,key:Key):
    return mutate(dataset_id,'rollback',body,request,actor,service,key)

@router.post('/datasets/{dataset_id}/ldd-publication/withdrawal')
def withdraw(dataset_id:UUID,body:LddWithdrawalInput,request:Request,actor:Actor,service:Service,key:Key):
    return mutate(dataset_id,'withdraw',body,request,actor,service,key)

@router.get('/published-ldd')
def read_published(request:Request,actor:Actor,service:Service,query:Annotated[PublishedQuery,Query()]):
    bundle=publication(request).bundle(service,actor,query.province,query.data_year)
    return JSONResponse(bundle,headers={'Cache-Control':'no-store','Pragma':'no-cache'})

@router.get('/published-ldd/geometry')
def read_published_geometry(request:Request,actor:Actor,service:Service,query:Annotated[PublishedGeometryQuery,Query()]):
    """Geometry of exactly one snapshot, fetched once by the Dashboard; gzip when the client accepts it."""
    geometry,sha=publication(request).geometry(service,actor,query.province,query.data_year,query.snapshot_id)
    raw=json.dumps(geometry,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()
    headers={'Cache-Control':'no-store','Pragma':'no-cache','X-Artifact-SHA256':sha,'Vary':'Accept-Encoding'}
    if 'gzip' in request.headers.get('accept-encoding','').lower():
        raw=gzip.compress(raw,6);headers['Content-Encoding']='gzip'
    return Response(content=raw,media_type='application/json',headers=headers)
