import { supabase, SUPABASE_URL } from '../lib/supabaseClient';
import { LOCAL_TARGET, gisTarget } from './gisTarget';

const messages = {
  401: 'เซสชันหมดอายุ กรุณาเข้าสู่ระบบใหม่',
  403: 'ไม่มีสิทธิ์ดำเนินการนี้ กรุณาตรวจสิทธิ์อีกครั้ง',
  404: 'ไม่พบข้อมูล กรุณาโหลดข้อมูลล่าสุด',
  409: 'ข้อมูลหรือสถานะเปลี่ยนแล้ว กรุณาโหลดข้อมูลล่าสุดก่อนทำรายการใหม่',
  422: 'ข้อมูลไม่ตรงตามรูปแบบ หรือ Manifest ไม่อยู่ในรายการที่อนุญาต',
  429: 'ส่งคำขอถี่เกินไป กรุณารอสักครู่ก่อนลองใหม่',
  413: 'ไฟล์ต้องมีขนาดไม่เกิน 20 MiB',
  415: 'รองรับเฉพาะไฟล์ Shapefile ZIP',
  507: 'พื้นที่จัดเก็บเต็ม กรุณาติดต่อผู้ดูแลระบบ',
};
const lddMessages = {
  GIS_LDD_ZIP_UNSAFE: 'ZIP ไม่ปลอดภัย มี Path, Link หรือขนาดขยายที่ไม่อนุญาต',
  GIS_LDD_ZIP_INVALID: 'ไฟล์ไม่ใช่ ZIP ที่อ่านได้ หรือ ZIP ไม่สมบูรณ์',
  GIS_LDD_ZIP_NESTED: 'ZIP นี้มี ZIP ซ้อนอยู่ข้างใน กรุณาแตกออกแล้วบีบอัดเฉพาะแพ็กเกจชั้นการใช้ที่ดินใหม่',
  GIS_LDD_UPLOAD_BUSY: 'มีการอัปโหลดอยู่ กรุณารอสักครู่แล้วลองคำสั่งเดิม',
  GIS_UPLOADED_EDITION_IMMUTABLE: 'ไฟล์ต้นฉบับแก้ไขไม่ได้ กรุณาอัปโหลดเป็นฉบับใหม่',
  GIS_LDD_DATASET_REQUIRED: 'ต้องเลือก Dataset LDD รายปี',
  GIS_LDD_INTEGRITY: 'Hash ของไฟล์ใน Local ไม่ตรง ระบบหยุดเพื่อป้องกันข้อมูลเสียหาย',
  GIS_GEE_LIVE_NOT_APPROVED: 'ยังไม่ได้อนุมัติการประมวลผล GEE จริง ใช้ได้เฉพาะ Offline Synthetic',
  GIS_PROCESSING_ROUTE_REQUIRED: 'งานประมวลผลต้องใช้หน้าประมวลผล NDVI/LST',
  GIS_PROCESSING_IMMUTABLE: 'ข้อมูลคำขอประมวลผลแก้ไม่ได้ กรุณาสร้างคำขอใหม่',
  GIS_GEOTIFF_INVALID: 'ไฟล์ไม่ใช่ TIFF ที่รองรับ หรือส่วนหัวไฟล์ไม่สมบูรณ์',
  GIS_GEOTIFF_QUOTA: 'พื้นที่ Local สำหรับ GeoTIFF เต็ม',
  GIS_GEOTIFF_IMMUTABLE: 'GeoTIFF ต้นฉบับแก้ไขไม่ได้ ให้อัปโหลดเป็นฉบับใหม่',
  GIS_GEOTIFF_DATASET_REQUIRED: 'Dataset NDVI/LST ไม่ตรงกับ Profile ของไฟล์',
};

export class GisError extends Error {
  constructor(status = 0, code = '') {
    super(lddMessages[code] || messages[status] || (status >= 500
      ? 'ระบบ GIS ยังไม่พร้อม กรุณาตรวจบริการ GIS แล้วลองใหม่'
      : 'เชื่อมต่อไม่สำเร็จ ผลคำสั่งอาจยังไม่ทราบ กรุณารีเฟรชหรือลองคำสั่งเดิม'));
    this.status = status;
  }
}

// One fully stated target, or nothing. A flag alone never authorizes a target.
export function gisConfigured(env = import.meta.env, location = window.location, authUrl = SUPABASE_URL) {
  return gisTarget(env, location, authUrl) !== null;
}

const id = '[0-9a-fA-F-]{36}';
const route = new RegExp(`^/(published-ldd(?:/geometry)?|published-geotiff|me|provinces|datasets|officers|processing-options|processing-jobs|processing-jobs/${id}(?:/attempts|/result|/history|/retry)?|ldd-uploads/${id}|geotiff-uploads/${id}|datasets/${id}(?:/geotiff-publication/(?:activation|rollback|withdrawal)|/ldd-publication/(?:activation|rollback|withdrawal)|/editions|/activation|/rollback|/ldd-uploads|/geotiff-uploads)?|editions/${id}(?:/geotiff-publication|/clone|/validation-jobs|/history|/withdrawal|/prepare-jobs|/prepare-retry|/prepare-verification|/prepared|/geotiff-prepare-jobs|/geotiff-prepare-retry|/geotiff-prepare-verification|/geotiff-prepared)?|jobs|jobs/${id}(?:/attempts|/result|/retry)?|officers/${id}/revocation)$`);

export function createGisClient({ target = gisTarget(import.meta.env, window.location, SUPABASE_URL),
  enabled = target !== null, getSession = () => supabase.auth.getSession(), fetcher = fetch } = {}) {
  // `enabled` is still the switch, so a caller that forces it on without a
  // configured target gets the sandbox it must already be running against.
  const { api, issuer } = target || LOCAL_TARGET;
  return async function request(path, { method = 'GET', body, key, query = {}, signal } = {}) {
    if (!enabled || !route.test(path) || !['GET', 'POST', 'PATCH'].includes(method)) throw new GisError(503);
    if (method !== 'GET' && !/^[0-9a-f-]{36}$/i.test(key || '')) throw new GisError(422);
    const binary = body instanceof Blob;
    if (binary && (method !== 'POST' || !/\/(ldd|geotiff)-uploads$/.test(path) || body.size < 1 || body.size > 20 * 1024**2)) throw new GisError(413);
    const controller = new AbortController();
    const abort = () => controller.abort();
    signal?.addEventListener('abort', abort, { once: true });
    const timer = setTimeout(abort, binary || path === '/published-ldd' || path === '/published-geotiff' || path.endsWith('/geotiff-prepared') || (path.endsWith('/prepare-verification') || path.endsWith('/geotiff-prepare-verification')) || path.includes('/ldd-publication/') || path.includes('/geotiff-publication/') ? 90000 : 20000);
    try {
      if (signal?.aborted) controller.abort();
      const { data, error } = await getSession();
      const session = data?.session;
      if (error || !session?.access_token) throw new GisError(401);
      // This is a routing check only; the backend verifies the JWT signature.
      let claims;
      try { claims = JSON.parse(atob(session.access_token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/'))); }
      catch { throw new GisError(401); }
      if (claims.iss !== issuer || claims.role !== 'authenticated'
          || claims.sub !== session.user?.id || !Number.isFinite(claims.exp) || claims.exp * 1000 <= Date.now()) throw new GisError(401);
      const url = new URL(`${api}/gis${path}`);
      Object.entries(query).forEach(([name, value]) => { if (value !== '' && value != null) url.searchParams.set(name, value); });
      const response = await fetcher(url.href, {
        method, signal: controller.signal, redirect: 'error', credentials: 'omit', cache: 'no-store',
        headers: { Authorization: `Bearer ${session.access_token}`, ...(body ? { 'Content-Type': binary ? (path.endsWith('/geotiff-uploads') ? 'image/tiff' : 'application/zip') : 'application/json' } : {}),
          ...(method !== 'GET' ? { 'Idempotency-Key': key } : {}) },
        ...(body ? { body: binary ? body : JSON.stringify(body) } : {}),
      });
      if (!response.ok) {
        let code = '';
        try { code = (await response.json())?.detail?.code; } catch { /* Never expose raw diagnostics. */ }
        throw new GisError(response.status, code);
      }
      return await response.json();
    } catch (error) {
      if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
      throw error instanceof GisError ? error : new GisError();
    } finally { clearTimeout(timer); signal?.removeEventListener('abort', abort); }
  };
}

export const gisRequest = createGisClient();
