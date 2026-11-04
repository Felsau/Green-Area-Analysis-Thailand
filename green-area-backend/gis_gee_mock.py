"""Explicit Local-only mock API catalog; no oracle registration or live compute."""
from types import MappingProxyType
from uuid import UUID

from fastapi.responses import JSONResponse

from gis_runtime import LOCAL_URL
from gis_service import gis_error, safe_output

CASE_KEYS = ('ndvi-annual', 'ndvi-monthly', 'lst-annual', 'lst-monthly',
             'no-data', 'all-masked', 'partial', 'retry-once', 'retry-exhausted', 'long-running')


class LocalGeeMock:
    def __init__(self, service, catalog):
        if (not isinstance(catalog, dict) or not catalog or set(catalog) - set(CASE_KEYS)
            or len(set(catalog.values())) != len(catalog)):
            raise ValueError('GEE_MOCK_CATALOG_INVALID')
        self.service = service
        self.catalog = MappingProxyType({key: str(UUID(value)) for key, value in catalog.items()})

    def authorize(self, actor):
        runtime = self.service.runtime
        settings = runtime.settings
        ready = runtime.require_ready()
        if (settings.enabled is not True or settings.api_url != LOCAL_URL or settings.database != 'postgres'
            or settings.cluster != 'green-area-gis-t0' or settings.mode != 'local_synthetic'
            or runtime.sandbox_activation_enabled is not False or 43 not in ready.get('migration_versions', [])):
            raise gis_error(503, 'GIS_GEE_MOCK_DISABLED', 'Local Mock Processing ยังไม่พร้อม')
        me = self.service.read(actor, 'me')
        if me.get('database_activation_enabled') is not False or me.get('backend_activation_enabled') is not False:
            raise gis_error(503, 'GIS_GEE_MOCK_DISABLED', 'Local Mock ต้องปิด Activation Gate')
        if me.get('admin') is not True and me.get('officer') is not True:
            raise gis_error(403, 'GIS_FORBIDDEN', 'เฉพาะเจ้าหน้าที่ GIS หรือ Admin')
        return me

    def options(self, actor):
        self.authorize(actor)
        return {'protocol': 'gee_contract_mock', 'execution': 'mock', 'synthetic': True,
                'live_enabled': False, 'publishable': False, 'case_keys': sorted(self.catalog)}

    def create(self, actor, key, case_key):
        self.authorize(actor)
        if case_key not in self.catalog:
            raise gis_error(422, 'GIS_GEE_MOCK_CASE_UNAVAILABLE', 'ชุดข้อมูลจำลองนี้ไม่ได้เปิดใน Local Catalog')
        value = self.service._rpc('gis_gee_mock_command', {'p_actor': str(UUID(actor)),
            'p_request_id': str(key), 'p_operation': 'create', 'p_payload': {'case_id': self.catalog[case_key]},
            'p_backend_mock': True})
        if (not isinstance(value, dict) or value.get('status') != 202 or not isinstance(value.get('body'), dict)
            or value['body'].get('execution') != 'mock' or value['body'].get('live_enabled') is not False
            or value['body'].get('publishable') is not False):
            raise gis_error(503, 'GIS_INVALID_RESPONSE', 'ผลตอบกลับ Local Mock ไม่ตรง Contract')
        return JSONResponse(status_code=202, content=safe_output(value['body']))

    def read(self, actor, job_id):
        self.authorize(actor)
        value = self.service._rpc('gis_gee_mock_read', {'p_actor': str(UUID(actor)), 'p_job': str(job_id)})
        if (not isinstance(value, dict) or not isinstance(value.get('request'), dict)
            or value['request'].get('case_id') not in self.catalog.values()):
            raise gis_error(404, 'GIS_NOT_FOUND', 'ไม่พบงานใน Local Mock Catalog นี้')
        return safe_output(value) | {'protocol': 'gee_contract_mock', 'execution': 'mock',
                                    'live_enabled': False, 'publishable': False}

    def history(self, actor, job_id):
        value = self.read(actor, job_id)
        return self.service.read(actor, 'history', {'edition_id': value['request']['edition_id'], 'limit': 100})
