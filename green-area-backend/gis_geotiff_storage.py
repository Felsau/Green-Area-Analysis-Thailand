"""Private Local TIFF objects using the existing bounded immutable upload store."""
from pathlib import Path
import re
import struct
from fastapi import HTTPException
from gis_ldd_storage import LocalLddStore, MAX_UPLOAD, DISK_QUOTA
from gis_service import gis_error

UPLOAD_PATH = re.compile(r'^/gis/datasets/[0-9a-fA-F-]{36}/geotiff-uploads$')


def storage_error(code='GIS_GEOTIFF_STORAGE_UNAVAILABLE', status=503):
    messages = {
        'GIS_GEOTIFF_SIZE_LIMIT': 'GeoTIFF ต้องมีขนาดไม่เกิน 20 MiB',
        'GIS_GEOTIFF_QUOTA': 'พื้นที่ Local สำหรับ GeoTIFF เต็ม',
        'GIS_GEOTIFF_INVALID': 'ไฟล์ต้องเป็น TIFF แบบ Classic ที่มีโครงสร้างส่วนหัวครบ',
        'GIS_GEOTIFF_INTEGRITY': 'SHA256 ของไฟล์ต้นฉบับไม่ตรง ระบบหยุดการทำงาน',
        'GIS_GEOTIFF_UPLOAD_BUSY': 'มีการอัปโหลดอยู่ กรุณาลองคำสั่งเดิมอีกครั้ง',
        'GIS_GEOTIFF_UPLOAD_TIMEOUT': 'อัปโหลดเกินเวลาที่กำหนด',
    }
    return gis_error(status, code, messages.get(code, 'พื้นที่ Local สำหรับ GeoTIFF ยังไม่พร้อม'))


class LocalGeoTiffStore(LocalLddStore):
    STORAGE_NAME = 'geotiff-storage'
    OWNER_SCOPE = 'gis-geotiff-storage-v1'
    REQUIRED_MIGRATION = 36
    OBJECT_SUFFIX = '.tif'

    @staticmethod
    def preflight(path: Path):
        # Only a bounded signature/first-IFD check in HTTP. GDAL stays in child.
        with path.open('rb') as source:
            header = source.read(8)
        if len(header) != 8 or header[:4] not in (b'II*\x00', b'MM\x00*'):
            raise storage_error('GIS_GEOTIFF_INVALID', 422)
        offset = struct.unpack('<I' if header[:2] == b'II' else '>I', header[4:])[0]
        if not 8 <= offset <= path.stat().st_size - 2:
            raise storage_error('GIS_GEOTIFF_INVALID', 422)

    async def receive(self, *args, **kwargs):
        try:
            return await super().receive(*args, **kwargs)
        except HTTPException as error:
            code = error.detail.get('code', '') if isinstance(error.detail, dict) else ''
            if code.startswith('GIS_LDD_'):
                replacement = code.replace('GIS_LDD_', 'GIS_GEOTIFF_', 1)
                if code in ('GIS_LDD_ZIP_INVALID', 'GIS_LDD_ZIP_UNSAFE'):
                    replacement = 'GIS_GEOTIFF_INVALID'
                raise storage_error(replacement, error.status_code) from None
            raise
