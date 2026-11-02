"""GIS management HTTP namespace; no GEE, cache, upload or worker endpoints."""
from __future__ import annotations

from typing import Annotated
from uuid import UUID, uuid5

from fastapi import APIRouter, Depends, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from starlette.responses import JSONResponse

from gis_runtime import require_gis_user
from gis_schemas import (
    Activation, DatasetCreate, DatasetQuery, DatasetUpdate, EditionCreate, EditionQuery,
    EditionUpdate, ExpectedRevision, JobQuery, JobRetry, OfficerGrant, OfficerRevoke,
    PageQuery, Withdrawal, LddUploadQuery, GeoTiffUploadQuery, ProcessingCreate, ProcessingQuery, ProcessingOptions,
)
from gis_service import GisService, decode_cursor, gis_error


class GisRoute(APIRoute):
    """Only GIS errors omit raw input, including non-finite JSON values/secrets."""
    def get_route_handler(self):
        original = super().get_route_handler()

        async def guarded(request: Request):
            try:
                return await original(request)
            except RequestValidationError as error:
                fields = [{"loc": list(item.get("loc", ())), "type": item.get("type", "invalid"),
                    "message": "ข้อมูลไม่ตรงตามรูปแบบที่กำหนด"} for item in error.errors()[:30]]
                return JSONResponse(status_code=422, content={"detail": {"code": "GIS_INVALID_INPUT",
                    "message": "ข้อมูลคำขอ GIS ไม่ถูกต้อง", "fields": fields}})
        return guarded


router = APIRouter(prefix="/gis", tags=["gis"], route_class=GisRoute)


def get_gis_service(request: Request) -> GisService:
    service = getattr(request.app.state, "gis_service", None)
    if service is None:
        raise gis_error(503, "GIS_DISABLED", "ระบบ GIS ยังไม่เปิดใช้งาน")
    return service


def idempotency_key(request: Request) -> UUID:
    values = request.headers.getlist("idempotency-key")
    try:
        if len(values) != 1:
            raise ValueError("exactly one key required")
        return UUID(values[0])
    except (ValueError, TypeError, AttributeError):
        raise gis_error(422, "GIS_IDEMPOTENCY_KEY_REQUIRED", "ต้องระบุ Idempotency-Key แบบ UUID เพียงค่าเดียว") from None


Actor = Annotated[str, Depends(require_gis_user)]
Service = Annotated[GisService, Depends(get_gis_service)]
Key = Annotated[UUID, Depends(idempotency_key)]


def page_payload(query: PageQuery, **extra) -> dict:
    payload = query.model_dump(mode="json", exclude_none=True)
    cursor = decode_cursor(payload.pop("cursor", None))
    if cursor is not None:
        payload["cursor"] = cursor
    return {**payload, **extra}


@router.get("/me")
def get_me(request: Request, actor: Actor, service: Service):
    result = service.read(actor, "me")
    result['ldd_upload_enabled'] = getattr(request.app.state, 'gis_ldd_store', None) is not None
    ready = service.runtime.require_ready()
    result['processing_enabled'] = isinstance(ready, dict) and 35 in ready.get('migration_versions', [])
    result['gee_live_enabled'] = False
    result['geotiff_upload_enabled'] = getattr(request.app.state, 'gis_geotiff_store', None) is not None and 36 in ready.get('migration_versions', [])
    return result


@router.get("/provinces")
def provinces(actor: Actor, service: Service):
    return service.read(actor, "provinces")


@router.get("/datasets")
def datasets(actor: Actor, service: Service, query: Annotated[DatasetQuery, Query()]):
    return service.read(actor, "datasets", page_payload(query))


@router.post("/datasets", status_code=201)
def create_dataset(body: DatasetCreate, actor: Actor, service: Service, key: Key):
    return service.command(actor, key, "create_dataset", body.model_dump(mode="json"))


@router.get("/datasets/{dataset_id}")
def dataset(dataset_id: UUID, actor: Actor, service: Service):
    return service.read(actor, "dataset", {"id": str(dataset_id)})


@router.patch("/datasets/{dataset_id}")
def update_dataset(dataset_id: UUID, body: DatasetUpdate, actor: Actor, service: Service, key: Key):
    return service.command(actor, key, "edit_dataset", {"dataset_id": str(dataset_id), **body.model_dump(mode="json")})


@router.get("/datasets/{dataset_id}/editions")
def editions(dataset_id: UUID, actor: Actor, service: Service, query: Annotated[EditionQuery, Query()]):
    return service.read(actor, "editions", page_payload(query, dataset_id=str(dataset_id)))


@router.post("/datasets/{dataset_id}/editions", status_code=201)
def create_edition(dataset_id: UUID, body: EditionCreate, actor: Actor, service: Service, key: Key):
    return service.command(actor, key, "create_edition", {"dataset_id": str(dataset_id), **body.model_dump(mode="json", exclude_none=True)})


@router.get("/editions/{edition_id}")
def edition(edition_id: UUID, actor: Actor, service: Service):
    return service.read(actor, "edition", {"id": str(edition_id)})


@router.patch("/editions/{edition_id}")
def update_edition(edition_id: UUID, body: EditionUpdate, actor: Actor, service: Service, key: Key):
    return service.command(actor, key, "edit_edition", {"edition_id": str(edition_id), **body.model_dump(mode="json", exclude_none=True)})


@router.post("/editions/{edition_id}/clone", status_code=201)
def clone_edition(edition_id: UUID, body: ExpectedRevision, actor: Actor, service: Service, key: Key):
    return service.command(actor, key, "clone_edition", {"edition_id": str(edition_id), **body.model_dump(mode="json")})


@router.post("/editions/{edition_id}/validation-jobs", status_code=202)
def enqueue(edition_id: UUID, body: ExpectedRevision, actor: Actor, service: Service, key: Key):
    return service.command(actor, key, "enqueue", {"edition_id": str(edition_id), **body.model_dump(mode="json")})


@router.get("/editions/{edition_id}/history")
def history(edition_id: UUID, actor: Actor, service: Service, query: Annotated[PageQuery, Query()]):
    return service.read(actor, "history", page_payload(query, edition_id=str(edition_id)))


@router.post("/datasets/{dataset_id}/activation")
def activate(dataset_id: UUID, body: Activation, actor: Actor, service: Service, key: Key):
    return service.command(actor, key, "activate", {"dataset_id": str(dataset_id), **body.model_dump(mode="json")})


@router.post("/datasets/{dataset_id}/rollback")
def rollback(dataset_id: UUID, body: Activation, actor: Actor, service: Service, key: Key):
    return service.command(actor, key, "rollback", {"dataset_id": str(dataset_id), **body.model_dump(mode="json")})


@router.post("/editions/{edition_id}/withdrawal")
def withdraw(edition_id: UUID, body: Withdrawal, actor: Actor, service: Service, key: Key):
    return service.command(actor, key, "withdraw", {"edition_id": str(edition_id), **body.model_dump(mode="json")})


@router.get("/jobs")
def jobs(actor: Actor, service: Service, query: Annotated[JobQuery, Query()]):
    return service.read(actor, "jobs", page_payload(query))


@router.get("/jobs/{job_id}")
def job(job_id: UUID, actor: Actor, service: Service):
    return service.read(actor, "job", {"id": str(job_id)})


@router.get("/jobs/{job_id}/attempts")
def attempts(job_id: UUID, actor: Actor, service: Service, query: Annotated[PageQuery, Query()]):
    return service.read(actor, "attempts", page_payload(query, job_id=str(job_id)))


@router.get("/jobs/{job_id}/result")
def result(job_id: UUID, actor: Actor, service: Service):
    return service.read(actor, "result", {"id": str(job_id)})


@router.post("/jobs/{job_id}/retry", status_code=202)
def retry(job_id: UUID, body: JobRetry, actor: Actor, service: Service, key: Key):
    return service.command(actor, key, "retry", {"job_id": str(job_id), **body.model_dump(mode="json")})


@router.get("/officers")
def officers(actor: Actor, service: Service, query: Annotated[PageQuery, Query()]):
    return service.read(actor, "officers", page_payload(query))


@router.post("/officers")
def grant_officer(body: OfficerGrant, actor: Actor, service: Service, key: Key):
    return service.command(actor, key, "grant_officer", body.model_dump(mode="json"))


@router.post("/officers/{user_id}/revocation")
def revoke_officer(user_id: UUID, body: OfficerRevoke, actor: Actor, service: Service, key: Key):
    return service.command(actor, key, "revoke_officer", {"user_id": str(user_id), **body.model_dump(mode="json")})


@router.post('/datasets/{dataset_id}/ldd-uploads', status_code=201)
async def upload_ldd(dataset_id: UUID, request: Request, actor: Actor, service: Service, key: Key,
                     query: Annotated[LddUploadQuery, Query()]):
    from gis_ldd_storage import MAX_UPLOAD, storage_error
    # This read authorizes GIS access before consuming the raw upload stream.
    dataset = service.read(actor, 'dataset', {'id': str(dataset_id)})
    if dataset.get('kind') != 'ldd_shapefile' or dataset.get('purpose') != 'landuse' or dataset.get('month') != 0:
        raise gis_error(422, 'GIS_LDD_DATASET_REQUIRED', 'ต้องเลือก Dataset LDD รายปี')
    if dataset.get('revision') != query.expected_revision:
        raise gis_error(409, 'GIS_REVISION_CONFLICT', 'Dataset เปลี่ยนแล้ว กรุณาโหลดข้อมูลล่าสุด')
    store = getattr(request.app.state, 'gis_ldd_store', None)
    if store is None or store.runtime is not service.runtime:
        raise storage_error()
    if request.headers.get('content-type', '').split(';')[0].strip().lower() not in ('application/zip', 'application/octet-stream'):
        raise gis_error(415, 'GIS_LDD_CONTENT_TYPE', 'ต้องส่งไฟล์ ZIP ด้วย Content-Type application/zip')
    values = request.headers.getlist('content-length')
    try:
        if len(values) > 1 or (values and (not values[0].isdigit() or len(values[0]) > 12)):
            raise ValueError()
        length = int(values[0]) if values else None
    except ValueError:
        raise gis_error(422, 'GIS_LDD_CONTENT_LENGTH', 'ขนาดคำขอไม่ถูกต้อง') from None
    if length is not None and length > MAX_UPLOAD:
        raise storage_error('GIS_LDD_SIZE_LIMIT', 413)
    stored = await store.receive(request.stream(), declared_size=length)
    # Stable, server-generated identity for a retried upload; no client path or
    # arbitrary object name ever enters storage or the native worker.
    upload_id = uuid5(UUID('3ab9bdd7-4f76-42d8-a092-b3bb55154187'), f'{actor}:{dataset_id}:{key}')
    return service.ldd_command(actor, key, 'upload', {'dataset_id': str(dataset_id), 'expected_revision': query.expected_revision,
        'upload_id': str(upload_id), **stored, 'crs': query.crs, 'encoding': query.encoding})


@router.get('/ldd-uploads/{upload_id}')
def ldd_upload_metadata(upload_id: UUID, actor: Actor, service: Service):
    return service.ldd_read(actor, upload_id)


@router.post('/datasets/{dataset_id}/geotiff-uploads', status_code=201)
async def upload_geotiff(dataset_id: UUID, request: Request, actor: Actor, service: Service, key: Key,
                         query: Annotated[GeoTiffUploadQuery, Query()]):
    from gis_geotiff_storage import MAX_UPLOAD, storage_error
    dataset = service.read(actor, 'dataset', {'id': str(dataset_id)})
    metric = 'ndvi' if query.profile == 'ndvi_ready' else 'lst'
    if dataset.get('kind') != 'geotiff' or dataset.get('purpose') != metric:
        raise gis_error(422, 'GIS_GEOTIFF_DATASET_REQUIRED', 'ต้องเลือก Dataset NDVI/LST ให้ตรงกับ Profile')
    if dataset.get('revision') != query.expected_revision:
        raise gis_error(409, 'GIS_REVISION_CONFLICT', 'Dataset เปลี่ยนแล้ว กรุณาโหลดข้อมูลล่าสุด')
    store = getattr(request.app.state, 'gis_geotiff_store', None)
    if store is None or store.runtime is not service.runtime:
        raise storage_error()
    # SQL preflight enforces current authorization/dataset identity before bytes.
    service.geotiff_command(actor, key, 'preflight', {'dataset_id': str(dataset_id),
        'expected_revision': query.expected_revision, 'profile': query.profile, 'crs': query.crs})
    if request.headers.get('content-type', '').split(';')[0].strip().lower() not in ('image/tiff','application/octet-stream'):
        raise gis_error(415, 'GIS_GEOTIFF_CONTENT_TYPE', 'ต้องส่ง GeoTIFF ด้วย Content-Type image/tiff')
    lengths = request.headers.getlist('content-length')
    if len(lengths) > 1 or (lengths and (not lengths[0].isdigit() or len(lengths[0]) > 12)):
        raise gis_error(422, 'GIS_GEOTIFF_CONTENT_LENGTH', 'ขนาดคำขอไม่ถูกต้อง')
    size = int(lengths[0]) if lengths else None
    if size is not None and size > MAX_UPLOAD:
        raise storage_error('GIS_GEOTIFF_SIZE_LIMIT', 413)
    stored = await store.receive(request.stream(), declared_size=size)
    upload_id = uuid5(UUID('552c32ce-226a-4306-99d3-d940a8234f8a'), f'{actor}:{dataset_id}:{key}')
    return service.geotiff_command(actor, key, 'upload', {'dataset_id': str(dataset_id),
        'expected_revision': query.expected_revision, 'upload_id': str(upload_id), **stored,
        'crs': query.crs, 'profile': query.profile})


@router.get('/geotiff-uploads/{upload_id}')
def geotiff_upload_metadata(upload_id: UUID, actor: Actor, service: Service):
    return service.geotiff_read(actor, upload_id)


@router.get('/processing-options')
def processing_options(actor: Actor, service: Service, query: Annotated[ProcessingOptions, Query()]):
    return service.processing_read(actor, 'options', query.model_dump(mode='json', exclude_none=True))


@router.post('/processing-jobs', status_code=202)
def create_processing(body: ProcessingCreate, actor: Actor, service: Service, key: Key):
    return service.processing_command(actor, key, 'create', body.model_dump(mode='json'))


@router.get('/processing-jobs')
def processing_jobs(actor: Actor, service: Service, query: Annotated[ProcessingQuery, Query()]):
    return service.processing_read(actor, 'jobs', page_payload(query))


@router.get('/processing-jobs/{job_id}')
def processing_job(job_id: UUID, actor: Actor, service: Service):
    return service.processing_read(actor, 'job', {'id': str(job_id)})


@router.get('/processing-jobs/{job_id}/attempts')
def processing_attempts(job_id: UUID, actor: Actor, service: Service, query: Annotated[PageQuery, Query()]):
    return service.processing_read(actor, 'attempts', page_payload(query, job_id=str(job_id)))


@router.get('/processing-jobs/{job_id}/result')
def processing_result(job_id: UUID, actor: Actor, service: Service):
    return service.processing_read(actor, 'result', {'id': str(job_id)})


@router.get('/processing-jobs/{job_id}/history')
def processing_history(job_id: UUID, actor: Actor, service: Service, query: Annotated[PageQuery, Query()]):
    return service.processing_read(actor, 'history', page_payload(query, job_id=str(job_id)))


@router.post('/processing-jobs/{job_id}/retry', status_code=202)
def processing_retry(job_id: UUID, body: JobRetry, actor: Actor, service: Service, key: Key):
    return service.processing_command(actor, key, 'retry', {'job_id': str(job_id), **body.model_dump(mode='json')})
