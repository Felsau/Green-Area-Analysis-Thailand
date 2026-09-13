import { beforeEach, describe, expect, it } from 'vitest';
import {
  API_ERROR,
  ApiError,
  apiErrorMessage,
  apiErrorToastKey,
  createAbortError,
  isAbortError,
  isApiError,
  pushApiError,
} from './apiErrors';
import { subscribeToast } from './toast';

describe('การจำแนก error', () => {
  it('ApiError ถูกจำแนกได้ และ AbortError ไม่ใช่ ApiError', () => {
    const api = new ApiError(API_ERROR.TIMEOUT, 'หมดเวลา');
    expect(isApiError(api)).toBe(true);
    expect(isAbortError(api)).toBe(false);

    const abort = createAbortError();
    expect(abort.name).toBe('AbortError');
    expect(isAbortError(abort)).toBe(true);
    expect(isApiError(abort)).toBe(false);
  });
});

describe('ข้อความภาษาไทยตามชนิดของปัญหา', () => {
  it('timeout บอกว่าเซิร์ฟเวอร์อาจกำลังตื่น ไม่ใช่บอกว่าพัง', () => {
    const msg = apiErrorMessage(new ApiError(API_ERROR.TIMEOUT, 'x'), 'ข้อมูลจังหวัด');
    expect(msg).toContain('ไม่ตอบภายใน');
    expect(msg).toContain('ตื่นจากโหมดพัก');
  });

  it('network บอกให้เช็คอินเทอร์เน็ต', () => {
    const msg = apiErrorMessage(new ApiError(API_ERROR.NETWORK, 'x'));
    expect(msg).toContain('ติดต่อเซิร์ฟเวอร์ไม่ได้');
  });

  it('5xx ระบุ subject และ status', () => {
    const msg = apiErrorMessage(
      new ApiError(API_ERROR.SERVER, 'x', { status: 502 }), 'ข้อมูลอำเภอเมือง');
    expect(msg).toContain('ข้อมูลอำเภอเมือง');
    expect(msg).toContain('502');
  });

  it('error ที่ไม่รู้จักยังได้ข้อความที่อ่านรู้เรื่อง', () => {
    expect(apiErrorMessage(new Error('boom'), 'อันดับจังหวัด'))
      .toBe('โหลดอันดับจังหวัดไม่สำเร็จ — ลองอีกครั้ง');
  });
});

describe('การยุบข้อความซ้ำ', () => {
  it('timeout กับ network ของทุกคำขอใช้กุญแจร่วมกัน (สาเหตุเดียวกัน)', () => {
    const t = apiErrorToastKey(new ApiError(API_ERROR.TIMEOUT, 'x'), 'ข้อมูลจังหวัด A');
    const n = apiErrorToastKey(new ApiError(API_ERROR.NETWORK, 'x'), 'ข้อมูลอำเภอ B');
    expect(t).toBe('api:unreachable');
    expect(n).toBe('api:unreachable');
  });

  it('4xx/5xx แยกกุญแจตาม subject — คนละคำขอคนละเรื่อง', () => {
    const a = apiErrorToastKey(new ApiError(API_ERROR.SERVER, 'x', { status: 500 }), 'ข้อมูลจังหวัด A');
    const b = apiErrorToastKey(new ApiError(API_ERROR.SERVER, 'x', { status: 500 }), 'ข้อมูลจังหวัด B');
    expect(a).not.toBe(b);
  });
});

describe('pushApiError', () => {
  let received;
  beforeEach(() => { received = []; });

  it('ส่ง toast พร้อมกุญแจที่ถูกต้อง', () => {
    const unsub = subscribeToast(t => received.push(t));
    pushApiError(new ApiError(API_ERROR.TIMEOUT, 'x'), 'ข้อมูลจังหวัด');
    unsub();
    expect(received).toHaveLength(1);
    expect(received[0].key).toBe('api:unreachable');
    expect(received[0].type).toBe('error');
  });

  it('AbortError ต้องเงียบสนิท — ผู้ใช้เปลี่ยนใจ ไม่ใช่ความผิดพลาด', () => {
    const unsub = subscribeToast(t => received.push(t));
    pushApiError(createAbortError(), 'ข้อมูลจังหวัด');
    unsub();
    expect(received).toHaveLength(0);
  });
});
