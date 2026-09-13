// Simple pub/sub toast — hook ไหน catch error ก็เรียก pushError(msg)
// Toast.js subscribe เพื่อแสดงผล
//
// key = ตัวยุบข้อความซ้ำ · แดชบอร์ดยิงหลายคำขอพร้อมกัน เวลา backend ล่มหรือหลับ
// มันล้มพร้อมกันทั้งชุด ถ้าไม่ยุบผู้ใช้จะโดน toast เด้งซ้อน 4-5 อันที่บอกเรื่องเดียวกัน
// ค่าเริ่มต้นใช้ตัวข้อความเอง — ข้อความเหมือนกันถือว่าเป็นเรื่องเดียวกัน
// ส่วนผู้เรียกที่อยากยุบข้ามข้อความ (เช่น timeout/network ของทุกคำขอ) ส่ง key มาเอง
// ดู apiErrorToastKey ใน utils/apiErrors.js
const subscribers = new Set();

export function subscribeToast(fn) {
  subscribers.add(fn);
  return () => subscribers.delete(fn);
}

function push(toast) {
  subscribers.forEach(fn => fn(toast));
}

export function pushError(message, opts = {}) {
  push({
    id: Date.now() + Math.random(),
    type: 'error',
    message,
    duration: opts.duration ?? 5000,
    key: opts.key ?? `error:${message}`,
  });
}

export function pushInfo(message, opts = {}) {
  push({
    id: Date.now() + Math.random(),
    type: 'info',
    message,
    duration: opts.duration ?? 3000,
    key: opts.key ?? `info:${message}`,
  });
}
