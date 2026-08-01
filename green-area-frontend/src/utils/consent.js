// ความยินยอมการใช้คุกกี้และเทคโนโลยีที่คล้ายกัน (PDPA พ.ศ. 2562)
//
// ⚠️ ข้อเท็จจริงที่ต้องยึด: GreenLens **ไม่ได้ตั้งคุกกี้เลยสักตัว** — ที่เก็บทั้งหมด
// อยู่ใน localStorage ของเบราว์เซอร์ผู้ใช้เอง · แนวปฏิบัติของสำนักงานคณะกรรมการ
// คุ้มครองข้อมูลส่วนบุคคลใช้คำว่า "คุกกี้และเทคโนโลยีที่คล้ายกัน" ซึ่งครอบคลุม
// localStorage ด้วย จึงต้องขอความยินยอมเช่นกัน — แต่ห้ามเขียนข้อความให้ผู้ใช้เข้าใจว่า
// มีคุกกี้ติดตามทั้งที่ไม่มี (ดู COOKIE_SECTIONS ใน legalContent.js ที่ระบุรายการจริง)
//
// หลักที่โค้ดนี้บังคับ:
//   1. ประเภท "จำเป็นอย่างยิ่ง" ไม่ต้องขอความยินยอม แต่ต้องแจ้ง — ได้แก่ session
//      ล็อกอินของ Supabase และตัวบันทึกความยินยอมนี้เอง
//   2. ประเภท "เพื่อการทำงาน" ต้องได้รับความยินยอมก่อน *เขียน* ไม่ใช่ขอทีหลัง
//      (useTheme เรียก isAllowed('functional') ก่อนทุกครั้งที่จะเขียน)
//   3. ถอนความยินยอมต้องง่ายเท่าการให้ (มาตรา 19 วรรคห้า) — ถอนแล้วต้อง *ลบ*
//      ของที่เก็บไว้ทันที ไม่ใช่แค่หยุดเขียนเพิ่ม
//
// ไม่มีหมวด analytics/marketing โดยตั้งใจ — ระบบไม่มีสองอย่างนี้จริง การใส่ช่องไว้
// เฉย ๆ จะเป็นการแจ้งข้อมูลเท็จ ถ้าวันหนึ่งเพิ่ม analytics ต้องเพิ่มหมวดที่นี่และ
// bump CONSENT_VERSION เพื่อถามผู้ใช้ใหม่

export const CONSENT_KEY = 'greenlens-consent';

// เพิ่มเลขนี้เมื่อ "ขอบเขตของสิ่งที่ขอความยินยอม" เปลี่ยน (เพิ่มหมวด/เพิ่มรายการที่เก็บ)
// — ค่าเก่าที่เวอร์ชันไม่ตรงถือว่ายังไม่เคยยินยอม แล้วถามใหม่ · ไม่ต้อง bump เมื่อแก้
// ถ้อยคำอธิบายเฉย ๆ เพราะจะรบกวนผู้ใช้โดยไม่จำเป็น
export const CONSENT_VERSION = 1;

// รายการที่ระบบเขียนลง localStorage จริง แยกตามหมวด — ใช้ทั้งแสดงในหน้าตั้งค่า
// และใช้ลบตอนถอนความยินยอม จึงไม่มีทางที่ UI กับพฤติกรรมจริงจะหลุดจากกัน
export const CATEGORIES = [
  {
    id: 'necessary',
    required: true,
    title: 'จำเป็นอย่างยิ่ง',
    summary: 'ทำให้เข้าสู่ระบบและใช้งานพื้นฐานได้ ปิดไม่ได้',
    items: [
      { key: 'sb-*-auth-token', label: 'สถานะการเข้าสู่ระบบ (Supabase)',
        purpose: 'จำว่าผู้ใช้ล็อกอินอยู่ ไม่ต้องกรอกรหัสผ่านใหม่ทุกครั้งที่เปลี่ยนหน้า',
        keep: 'จนกว่าจะออกจากระบบหรือ session หมดอายุ' },
      { key: CONSENT_KEY, label: 'บันทึกตัวเลือกความยินยอมนี้',
        purpose: 'จำว่าผู้ใช้เลือกอะไรไว้ จะได้ไม่ถามซ้ำทุกครั้งที่เปิดเว็บ',
        keep: '1 ปี (หรือจนกว่าจะล้างข้อมูลเบราว์เซอร์)' },
    ],
  },
  {
    id: 'functional',
    required: false,
    title: 'เพื่อการทำงาน',
    summary: 'จำการตั้งค่าที่ผู้ใช้เลือกไว้ ปฏิเสธได้ — ระบบยังใช้งานได้ครบ',
    items: [
      { key: 'theme', label: 'ธีมสว่าง/มืดที่เลือกไว้',
        purpose: 'เปิดเว็บครั้งถัดไปแล้วได้ธีมเดิม',
        keep: 'จนกว่าจะล้างข้อมูลเบราว์เซอร์' },
    ],
  },
];

// คีย์ที่ระบบ *เคย* เขียนแต่เลิกใช้แล้ว — ลบทิ้งครั้งเดียวตอนโหลดโมดูล
//
// จำเป็นเพราะ CATEGORIES ทำหน้าที่สองอย่างพร้อมกัน (แสดงในหน้าตั้งค่า + เป็นรายการที่
// purgeDenied ใช้ลบตอนถอนความยินยอม) พอถอดรายการออกจึงไม่เหลืออะไรไปลบของเดิมให้
// ผู้ใช้ที่เคยยินยอมไว้แล้ว — คีย์จะค้างในเบราว์เซอร์ตลอดไปทั้งที่ไม่มีอะไรอ่านมันแล้ว
//
//   green-area-owner : owner token ยุคก่อนมี login · ตัดทิ้งพร้อม migration 019
//
// ไม่ bump CONSENT_VERSION เพราะขอบเขตที่ขอความยินยอม *แคบลง* ไม่ได้กว้างขึ้น —
// ความยินยอมเดิมยังครอบคลุมของที่เหลืออยู่ครบ การถามใหม่จะรบกวนผู้ใช้โดยไม่ได้อะไร
const LEGACY_KEYS = ['green-area-owner'];
for (const k of LEGACY_KEYS) {
  try { localStorage.removeItem(k); } catch { /* ถูกบล็อก — ข้าม */ }
}

const OPTIONAL_IDS = CATEGORIES.filter(c => !c.required).map(c => c.id);

const listeners = new Set();
let _state = null;      // cache ในหน่วยความจำ — กันอ่าน localStorage ทุก render

function read() {
  try {
    const raw = localStorage.getItem(CONSENT_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    // เวอร์ชันไม่ตรง = ขอบเขตที่เคยยินยอมไม่ครอบคลุมของที่เก็บตอนนี้ → ถือว่ายังไม่ตัดสินใจ
    if (parsed?.version !== CONSENT_VERSION) return null;
    return parsed;
  } catch {
    // localStorage ถูกบล็อก หรือ JSON เสีย → ปฏิบัติเหมือนยังไม่เคยยินยอม (ปลอดภัยกว่า)
    return null;
  }
}

/** สถานะความยินยอมปัจจุบัน — null = ยังไม่เคยตัดสินใจ (ต้องแสดงแบนเนอร์) */
export function getConsent() {
  if (_state === null) _state = read();
  return _state;
}

/** หมวดนี้ได้รับความยินยอมแล้วหรือยัง — หมวดที่ required คืน true เสมอ */
export function isAllowed(categoryId) {
  const cat = CATEGORIES.find(c => c.id === categoryId);
  if (cat?.required) return true;
  return getConsent()?.categories?.[categoryId] === true;
}

/** ลบของที่เก็บไว้ของหมวดที่ถูกปฏิเสธ — ถอนความยินยอมต้องลบจริง ไม่ใช่แค่หยุดเขียน */
function purgeDenied(categories) {
  for (const cat of CATEGORIES) {
    if (cat.required || categories[cat.id]) continue;
    for (const item of cat.items) {
      try { localStorage.removeItem(item.key); } catch { /* ถูกบล็อก — ข้าม */ }
    }
  }
}

/**
 * บันทึกตัวเลือกของผู้ใช้ · `choices` = { functional: boolean, … }
 * หมวดที่ไม่ได้ระบุถือว่า "ไม่ยินยอม" — ค่าเริ่มต้นต้องเป็นการปฏิเสธเสมอ ห้าม opt-out
 */
export function setConsent(choices = {}) {
  const categories = Object.fromEntries(
    OPTIONAL_IDS.map(id => [id, choices[id] === true]));
  const record = {
    version: CONSENT_VERSION,
    decidedAt: new Date().toISOString(),
    categories,
  };
  purgeDenied(categories);
  try {
    localStorage.setItem(CONSENT_KEY, JSON.stringify(record));
  } catch { /* ถูกบล็อก → ตัวเลือกอยู่แค่ session นี้ ยังบังคับใช้ได้จาก _state */ }
  _state = record;
  listeners.forEach(fn => fn(record));
  return record;
}

export const acceptAll = () => setConsent(
  Object.fromEntries(OPTIONAL_IDS.map(id => [id, true])));

export const rejectOptional = () => setConsent({});

/** ล้างการตัดสินใจทั้งหมด (ใช้ในเทสต์) — ผู้ใช้ทั่วไปถอนผ่าน rejectOptional */
export function resetConsent() {
  try { localStorage.removeItem(CONSENT_KEY); } catch { /* ถูกบล็อก — ข้าม */ }
  _state = null;
  listeners.forEach(fn => fn(null));
}

/** subscribe สำหรับ useSyncExternalStore — คืนฟังก์ชัน unsubscribe */
export function subscribe(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}
