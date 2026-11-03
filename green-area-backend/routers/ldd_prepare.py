"""Local-only Prepare/Preview routes; no Dashboard reader or activation paths."""
from uuid import UUID
from fastapi import APIRouter, Request, HTTPException
from fastapi.encoders import jsonable_encoder
from pydantic import Field
from typing import Annotated
from starlette.responses import JSONResponse
from gis_schemas import GisInput, Revision, Hash, Province, Reason
from gis_service import gis_error, safe_output
from routers.gis import Actor, Service, Key, GisRoute

router = APIRouter(prefix='/gis', route_class=GisRoute)


class PrepareInput(GisInput):
    expected_dataset_revision: Revision
    expected_input_revision: Revision
    input_hash: Hash
    province: Province
    data_year: Annotated[int, Field(strict=True, ge=1980, le=2200)]


class PrepareRetry(PrepareInput):
    job_id: UUID
    reason: Reason


class VerifyInput(GisInput):
    job_id: UUID


def store_for(request, actor, service):
    me = service.read(actor, 'me')
    if 'enqueue_validation' not in me.get('capabilities', []):
        raise gis_error(403, 'GIS_FORBIDDEN', 'ไม่มีสิทธิ์จัดการข้อมูล GIS')
    store = getattr(request.app.state, 'gis_prepared_store', None)
    if store is None:
        raise gis_error(503, 'GIS_PREPARE_NOT_READY', 'ยังไม่ได้เตรียม Local Artifact Store')
    store.attest()
    return store


def current(service, actor, edition_id):
    return service._rpc('gis_ldd_prepare_read', {'p_actor': actor, 'p_edition': str(edition_id)})


def public_preview(service, actor, edition_id, store, *, geometry=False):
    info = current(service, actor, edition_id)
    value = {k: info.get(k) for k in ('status','job','attempts','preview_only','complete_province_inventory')}
    value.update(ready_for_publication=False, prepared=bool(info.get('candidate', {}).get('valid')) if info.get('candidate') else False,
        method_version='ldd-source-area-v1', local_only=True)
    if info.get('certificate') and info.get('ready_for_publication') is True:
        try:
            files = store.read_files(info['prepare_request'], info['candidate']['artifacts'])
        except HTTPException:
            raise
        except (OSError, ValueError):
            service._rpc('gis_ldd_verify_revoke', {'p_actor': actor, 'p_certificate': info['certificate']['id'], 'p_reason': 'artifact_corrupt'})
            value.update(error_code='GIS_PREPARE_ARTIFACT_UNAVAILABLE', status='verification_revoked')
        else:
            value.update(ready_for_publication=True, status='verified_for_local_review', summary=files['ldd_summary'],
                certificate_id=info['certificate']['id'])
            if geometry:
                full = files['ldd_geometry']
                # Bound UI work; stored/verified geometry is complete and unchanged.
                selected, coordinates = [], 0
                for feature in full['features'][:200]:
                    pending = [feature['geometry']['coordinates']]
                    count = 0
                    while pending:
                        node = pending.pop()
                        if node and isinstance(node[0], (int, float)):
                            count += 1
                        else:
                            pending.extend(node)
                    if coordinates + count > 20000:
                        break
                    coordinates += count
                    selected.append(feature)
                value['geometry'] = {**full, 'features': selected}
                value['preview_feature_limit'] = 200
                value['preview_coordinate_limit'] = 20000
                value['preview_truncated'] = len(selected) < len(full['features'])
    return safe_output(value)


@router.post('/editions/{edition_id}/prepare-jobs')
def enqueue(edition_id: UUID, body: PrepareInput, request: Request, actor: Actor, service: Service, key: Key):
    store = store_for(request, actor, service)
    if store._usage() >= 256*1024**2:
        raise gis_error(507, 'GIS_PREPARE_STORAGE_LIMIT', 'พื้นที่เตรียมข้อมูลถึงขีดจำกัด')
    result = service._rpc('gis_ldd_prepare_command', {'p_actor': actor, 'p_request_id': str(key), 'p_operation': 'enqueue',
        'p_payload': {**jsonable_encoder(body), 'edition_id': str(edition_id)}})
    return JSONResponse(safe_output(result['body']), status_code=result['status'])


@router.post('/editions/{edition_id}/prepare-retry')
def retry(edition_id: UUID, body: PrepareRetry, request: Request, actor: Actor, service: Service, key: Key):
    store_for(request, actor, service)
    result = service._rpc('gis_ldd_prepare_command', {'p_actor': actor, 'p_request_id': str(key), 'p_operation': 'retry',
        'p_payload': {**jsonable_encoder(body), 'edition_id': str(edition_id)}})
    return JSONResponse(safe_output(result['body']), status_code=result['status'])


@router.get('/editions/{edition_id}/prepared')
def prepared(edition_id: UUID, request: Request, actor: Actor, service: Service):
    store = store_for(request, actor, service)
    return public_preview(service, actor, edition_id, store, geometry=True)


@router.post('/editions/{edition_id}/prepare-verification')
def verify(edition_id: UUID, body: VerifyInput, request: Request, actor: Actor, service: Service, key: Key):
    store = store_for(request, actor, service)
    info = current(service, actor, edition_id)
    if not info.get('job') or info['job']['id'] != str(body.job_id) or info.get('status') != 'succeeded' or not info.get('candidate', {}).get('valid'):
        raise gis_error(409, 'GIS_PREPARE_NOT_READY', 'งานเตรียมข้อมูลยังไม่สำเร็จหรือไม่ใช่งานล่าสุด')
    try:
        proof = store.certify_files(info['prepare_request'], info['candidate'])
    except HTTPException:
        raise
    except (OSError, ValueError):
        raise gis_error(409, 'GIS_PREPARE_VERIFICATION_FAILED', 'ไฟล์ไม่ครบหรือไม่ผ่านการตรวจสอบ') from None
    service._rpc('gis_ldd_verify_complete', {'p_actor': actor, 'p_request_id': str(key), 'p_job': str(body.job_id), 'p_proof': proof})
    return public_preview(service, actor, edition_id, store, geometry=True)
