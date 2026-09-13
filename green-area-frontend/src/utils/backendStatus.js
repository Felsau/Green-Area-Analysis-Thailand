// ติดตามคำขอที่ยังค้างอยู่ เพื่อบอกผู้ใช้ว่าเกิดอะไรขึ้น ไม่ใช่ปล่อยให้เดาว่าเว็บค้าง
//
// ⚠️ บทเรียนสำคัญ (13 ก.ย. 2569): เวอร์ชันแรกของไฟล์นี้เหมาว่า "คำขอช้า = เซิร์ฟเวอร์
// กำลังตื่น" เสมอ ผลคือหน้า "AI แนะนำ" ที่กดตอนเซิร์ฟเวอร์ตื่นอยู่แล้ว ก็ยังขึ้นป้าย
// "กำลังปลุกเซิร์ฟเวอร์" ทั้งที่ความจริงคือกำลังคำนวณจาก Google Earth Engine อยู่
// — ป้ายไปสรุปสาเหตุที่ตัวเองไม่รู้จริง
//
// ตอนนี้แยกสองกรณีด้วยหลักฐาน ไม่ใช่การเดา:
//   'waking'   ไม่มี response จาก backend เลยในช่วงที่ผ่านมา → น่าจะหลับอยู่จริง
//   'working'  เพิ่งได้ response มาหมาด ๆ → เครื่องตื่นแน่นอน ที่ช้าคือกำลังคำนวณ
//
// หลักฐานที่ใช้คือ markServerAlive() ซึ่ง fetchRetry เรียกทุกครั้งที่ได้ response
// กลับมา **ไม่ว่าสถานะจะเป็นอะไร** — 200, 404 หรือ 500 ก็พิสูจน์เหมือนกันว่าเครื่องตื่น
// (เครื่องที่หลับอยู่ตอบอะไรไม่ได้เลย)
//
// นับที่ชั้น fetchWithRetry ไม่ใช่ที่ hook เพราะ hook แต่ละตัวมี loading flag ของ
// ตัวเองอยู่แล้วซึ่งบอกแค่ "คำขอของฉันยังไม่เสร็จ" ไม่รู้ว่าช้าผิดปกติหรือไม่ และ
// คำขอหลายตัวยิงพร้อมกัน ป้ายควรขึ้นครั้งเดียวไม่ใช่ตัวละป้าย
import { API_COLD_START_HINT_MS, API_SERVER_ALIVE_TTL_MS } from '../constants';

let inFlight = 0;
let hint = null;          // null | 'waking' | 'working'
let hintTimer = null;
let lastAliveAt = 0;      // เวลาที่ได้ response จาก backend ครั้งล่าสุด
const subscribers = new Set();

function emit() {
  subscribers.forEach((fn) => fn(hint));
}

function clearHintTimer() {
  if (hintTimer !== null) {
    clearTimeout(hintTimer);
    hintTimer = null;
  }
}

// เรียกทุกครั้งที่ได้ response จาก backend (สถานะใดก็ได้) — เป็นหลักฐานว่าเครื่องตื่น
export function markServerAlive() {
  lastAliveAt = Date.now();
  // ถ้าป้าย "กำลังปลุกเซิร์ฟเวอร์" ขึ้นอยู่ แต่เพิ่งพิสูจน์ได้ว่าเครื่องตื่นแล้ว
  // ให้เปลี่ยนข้อความทันทีระหว่างที่คำขออื่นยังค้างอยู่ ไม่ต้องรอให้จบก่อน
  if (hint === 'waking' && inFlight > 0) {
    hint = 'working';
    emit();
  }
}

const serverKnownAlive = () =>
  lastAliveAt > 0 && Date.now() - lastAliveAt < API_SERVER_ALIVE_TTL_MS;

export function subscribeBackendStatus(fn) {
  subscribers.add(fn);
  fn(hint);  // ส่งสถานะปัจจุบันทันที — กัน component ที่ mount ทีหลังพลาดป้ายที่ขึ้นไปแล้ว
  return () => subscribers.delete(fn);
}

export function beginRequest() {
  inFlight += 1;
  // ตั้งนาฬิกาเฉพาะตอนเริ่มจากศูนย์ — คำขอตัวที่ 2, 3, 4 ที่ตามมาไม่ต้องตั้งซ้ำ
  if (inFlight === 1 && hint === null) {
    clearHintTimer();
    hintTimer = setTimeout(() => {
      hintTimer = null;
      if (inFlight > 0) {
        hint = serverKnownAlive() ? 'working' : 'waking';
        emit();
      }
    }, API_COLD_START_HINT_MS);
  }
}

// เรียกใน finally ของ fetchWithRetry เสมอ ไม่ว่าจะสำเร็จ ล้มเหลว หรือถูกยกเลิก
// ป้ายจึงไม่มีทางค้าง
export function endRequest() {
  inFlight = Math.max(0, inFlight - 1);
  if (inFlight > 0) return;
  clearHintTimer();
  if (hint !== null) {
    hint = null;
    emit();
  }
}

export const backendHint = () => hint;
export const inFlightCount = () => inFlight;

// ใช้ในเทสต์เท่านั้น — โมดูลนี้เก็บ state ระดับ module ซึ่งข้ามเทสต์กันได้
export function resetBackendStatus() {
  clearHintTimer();
  inFlight = 0;
  hint = null;
  lastAliveAt = 0;
  subscribers.clear();
}
