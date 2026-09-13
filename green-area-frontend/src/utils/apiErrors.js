// ชนิดความล้มเหลวของการเรียก backend — แยกให้ชัดเพราะแต่ละชนิด "ต้องทำต่อ" ไม่เหมือนกัน
//
//   timeout  เซิร์ฟเวอร์ไม่ตอบภายในเวลาที่กำหนด (ส่วนใหญ่คือ Render กำลังตื่นจากโหมดพัก)
//            → retry ได้ และควรบอกผู้ใช้ว่ารอได้ ไม่ใช่พัง
//   network  fetch reject — ออฟไลน์ / DNS / CORS / เครื่องดับ
//            → retry ได้ แต่ถ้าซ้ำแปลว่าปลายทางไปไม่ถึงจริง
//   server   5xx — ฝั่งเซิร์ฟเวอร์สะดุด
//            → retry ได้
//   client   4xx — คำขอเราเองผิด (ปีไม่มีข้อมูล, ไม่ได้ล็อกอิน, ไม่มีอำเภอนี้)
//            → retry ไม่ช่วย ห้าม retry
//
// การยกเลิกโดยผู้เรียก (เปลี่ยนจังหวัด / component unmount) **ไม่ใช่** ความล้มเหลว
// จึงไม่มีชนิดของมันที่นี่ — มันโยน DOMException ชื่อ AbortError ออกไปตามเดิม
// และทุก call site เช็ค `err?.name === 'AbortError'` เพื่อเงียบอยู่แล้ว
import { pushError } from './toast';
import { API_TIMEOUT_MS } from '../constants';

export const API_ERROR = {
  TIMEOUT: 'timeout',
  NETWORK: 'network',
  SERVER: 'server',
  CLIENT: 'client',
};

export class ApiError extends Error {
  constructor(kind, message, { status = null, url = null, cause = null } = {}) {
    super(message);
    this.name = 'ApiError';
    this.kind = kind;
    this.status = status;
    this.url = url;
    if (cause) this.cause = cause;
  }
}

export const isApiError = (err) => err instanceof ApiError;

// เช็คด้วย name ไม่ใช่ instanceof — AbortError มาได้ทั้งจาก DOMException ของเบราว์เซอร์
// และจาก Error ธรรมดาที่เราสร้างเองตอน DOMException ไม่มี (ดู abortError ใน fetchRetry)
export const isAbortError = (err) => err?.name === 'AbortError';

export const createAbortError = () => {
  if (typeof DOMException !== 'undefined') return new DOMException('Aborted', 'AbortError');
  const err = new Error('Aborted');
  err.name = 'AbortError';
  return err;
};

const timeoutSeconds = () => Math.round(API_TIMEOUT_MS / 1000);

// ข้อความภาษาไทยสำหรับผู้ใช้ — ไม่ใช่ข้อความ debug
//
// subject = สิ่งที่โหลดไม่สำเร็จ เช่น 'ข้อมูลจังหวัดเชียงใหม่' ใช้เฉพาะกรณีที่ปัญหา
// ผูกกับคำขอนั้นจริง ๆ (4xx/5xx) · ส่วน timeout กับ network เป็นอาการของ "ทั้งระบบ"
// ไม่ใช่ของคำขอใดคำขอหนึ่ง จึงตั้งใจไม่ใส่ subject — เพื่อให้ 4 คำขอที่ล้มพร้อมกัน
// ยุบเหลือข้อความเดียว (ดู toastKey ข้างล่าง)
export function apiErrorMessage(err, subject = 'ข้อมูล') {
  if (isApiError(err)) {
    switch (err.kind) {
      case API_ERROR.TIMEOUT:
        return `เซิร์ฟเวอร์ไม่ตอบภายใน ${timeoutSeconds()} วินาที — อาจกำลังตื่นจากโหมดพัก ลองอีกครั้งได้เลย`;
      case API_ERROR.NETWORK:
        return 'ติดต่อเซิร์ฟเวอร์ไม่ได้ — ตรวจสอบการเชื่อมต่ออินเทอร์เน็ตแล้วลองใหม่';
      case API_ERROR.SERVER:
        return `โหลด${subject}ไม่สำเร็จ — เซิร์ฟเวอร์ขัดข้อง (HTTP ${err.status}) ลองอีกครั้งในอีกสักครู่`;
      case API_ERROR.CLIENT:
        return `โหลด${subject}ไม่สำเร็จ — คำขอไม่ถูกต้อง (HTTP ${err.status})`;
      default:
        break;
    }
  }
  return `โหลด${subject}ไม่สำเร็จ — ลองอีกครั้ง`;
}

// กุญแจสำหรับยุบ toast ซ้ำ
//
// timeout/network มีสาเหตุร่วมอันเดียว (เซิร์ฟเวอร์ไปไม่ถึง) — หน้าแดชบอร์ดยิงหลาย
// คำขอพร้อมกัน (useProvinceData, useDistrictData, useRankingData, useLanduseData…)
// ถ้าไม่ยุบ ผู้ใช้จะโดน toast เด้งซ้อนกัน 4-5 อันที่บอกเรื่องเดียวกัน
// ส่วน 4xx/5xx ผูกกับคำขอนั้นจริง จึงแยกกุญแจตาม subject ให้เห็นครบ
export function apiErrorToastKey(err, subject = 'ข้อมูล') {
  if (isApiError(err) && (err.kind === API_ERROR.TIMEOUT || err.kind === API_ERROR.NETWORK)) {
    return 'api:unreachable';
  }
  return `api:${subject}`;
}

// ตัวช่วยที่ call site ควรเรียก แทนที่จะประกอบ pushError เองทุกที่
export function pushApiError(err, subject = 'ข้อมูล') {
  if (isAbortError(err)) return;  // ผู้ใช้เปลี่ยนใจ ไม่ใช่ความผิดพลาด
  pushError(apiErrorMessage(err, subject), { key: apiErrorToastKey(err, subject) });
}
