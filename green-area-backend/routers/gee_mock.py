"""Opt-in mock endpoints; current live/offline processing routes are unchanged."""
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict

from gis_service import gis_error
from routers.gis import Actor, GisRoute, Key


class MockCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    mode: Literal['gee_contract_mock']
    case_key: Literal['ndvi-annual', 'ndvi-monthly', 'lst-annual', 'lst-monthly',
                      'no-data', 'all-masked', 'partial', 'retry-once', 'retry-exhausted', 'long-running']


def provider(request: Request):
    value = getattr(request.app.state, 'gis_gee_mock', None)
    if value is None:
        raise gis_error(503, 'GIS_GEE_MOCK_DISABLED', 'ยังไม่เปิด Local Mock Processing')
    return value


Provider = Annotated[object, Depends(provider)]
router = APIRouter(prefix='/gis/mock-gee', tags=['gis-mock'], route_class=GisRoute)


@router.get('/options')
def options(actor: Actor, mock: Provider):
    return mock.options(actor)


@router.post('/jobs', status_code=202)
def create(body: MockCreate, actor: Actor, key: Key, mock: Provider):
    return mock.create(actor, key, body.case_key)


@router.get('/jobs/{job_id}')
def job(job_id: UUID, actor: Actor, mock: Provider):
    return mock.read(actor, job_id)


@router.get('/jobs/{job_id}/history')
def history(job_id: UUID, actor: Actor, mock: Provider):
    return mock.history(actor, job_id)
