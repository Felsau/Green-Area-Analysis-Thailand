// ติดตามคำขอที่ยังค้างอยู่ เพื่อบอกผู้ใช้ว่า "เซิร์ฟเวอร์กำลังตื่น" ไม่ใช่ "เว็บค้าง"
//
// ทำไมต้องมี: backend อยู่บน Render free plan ที่หลับเมื่อไม่มีคนใช้ ~15 นาที คำขอแรก
// หลังหลับรอปลุกเครื่องราว 45-60 วินาที (วัดจริง 47.2 วินาที) ระหว่างนั้นหน้าจอเดิม
// ไม่แสดงอะไรเลยนอกจาก spinner ผู้ใช้จึงแยกไม่ออกว่าเว็บพังหรือแค่ช้า
//
// ตั้งใจนับที่ชั้น fetchWithRetry ไม่ใช่ที่ hook เพราะ:
//   · hook แต่ละตัวมี loading flag ของตัวเองอยู่แล้ว (ndviLoading, lstLoading, …)
//     ซึ่งบอกแค่ "คำขอของฉันยังไม่เสร็จ" ไม่รู้ว่าช้าผิดปกติหรือไม่
//   · คำขอหลายตัวยิงพร้อมกัน ป้ายควรขึ้นครั้งเดียวไม่ใช่ตัวละป้าย
//
// นับเป็นตัวเลข (ไม่ใช่ boolean) เพราะคำขอซ้อนกันได้ — ป้ายจะหายก็ต่อเมื่อคำขอ
// **ทุกตัว** จบแล้วเท่านั้น และ fetchWithRetry เรียก endRequest() ใน finally เสมอ
// ไม่ว่าจะสำเร็จ ล้มเหลว หรือถูกยกเลิก ป้ายจึงไม่มีทางค้าง
import { API_COLD_START_HINT_MS } from '../constants';

let inFlight = 0;
let waking = false;
let hintTimer = null;
const subscribers = new Set();

function emit() {
  subscribers.forEach((fn) => fn(waking));
}

function clearHintTimer() {
  if (hintTimer !== null) {
    clearTimeout(hintTimer);
    hintTimer = null;
  }
}

export function subscribeBackendStatus(fn) {
  subscribers.add(fn);
  fn(waking);  // ส่งสถานะปัจจุบันทันที — กัน component ที่ mount ทีหลังพลาดป้ายที่ขึ้นไปแล้ว
  return () => subscribers.delete(fn);
}

export function beginRequest() {
  inFlight += 1;
  // ตั้งนาฬิกาเฉพาะตอนเริ่มจากศูนย์ — คำขอตัวที่ 2, 3, 4 ที่ตามมาไม่ต้องตั้งซ้ำ
  if (inFlight === 1 && !waking) {
    clearHintTimer();
    hintTimer = setTimeout(() => {
      hintTimer = null;
      if (inFlight > 0) {
        waking = true;
        emit();
      }
    }, API_COLD_START_HINT_MS);
  }
}

export function endRequest() {
  inFlight = Math.max(0, inFlight - 1);
  if (inFlight > 0) return;
  clearHintTimer();
  if (waking) {
    waking = false;
    emit();
  }
}

export const isBackendWaking = () => waking;
export const inFlightCount = () => inFlight;

// ใช้ในเทสต์เท่านั้น — โมดูลนี้เก็บ state ระดับ module ซึ่งข้ามเทสต์กันได้
export function resetBackendStatus() {
  clearHintTimer();
  inFlight = 0;
  waking = false;
  subscribers.clear();
}
