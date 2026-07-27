// Per-browser owner token — ระบุว่า saved-area ไหน "ของฉัน" โดยไม่ต้อง login.
// ส่งทาง header X-Owner-Token ทุก save/delete.
//
// การ *จำ* token ข้ามการเปิดเว็บเป็นหมวด "เพื่อการทำงาน" ตาม PDPA จึงเขียนลง
// localStorage ได้ต่อเมื่อผู้ใช้ยินยอมแล้ว (utils/consent.js) — ยังไม่ยินยอม/ปฏิเสธ
// ก็ยังวาดและลบพื้นที่ของตัวเองได้ตามปกติ แต่เฉพาะภายใน session นี้ (รีเฟรชแล้วได้
// token ใหม่ จึงลบของเก่าไม่ได้) — พฤติกรรมเดียวกับตอน localStorage ถูกบล็อกอยู่แล้ว
import { isAllowed, subscribe } from './consent';

let _cached = null;

// ถอนความยินยอม → consent.js ลบคีย์ใน localStorage ไปแล้ว แต่ค่าที่ cache ไว้ในหน่วย
// ความจำยังอยู่ · ทิ้งด้วย ไม่งั้น token ที่ "ลบไปแล้ว" จะถูกส่งต่อไปทั้ง session
// (import ทางเดียว ownerToken → consent จึงไม่เกิด circular import)
subscribe(() => { if (!isAllowed('functional')) _cached = null; });

const randomToken = () =>
  (typeof crypto !== 'undefined' && crypto.randomUUID)
    ? crypto.randomUUID()
    : `o-${Date.now()}-${Math.random().toString(36).slice(2)}`;

export function getOwnerToken() {
  if (_cached) return _cached;
  if (!isAllowed('functional')) {
    _cached = randomToken();      // ชั่วคราวต่อ session — ไม่แตะ localStorage เลย
    return _cached;
  }
  try {
    let t = localStorage.getItem('green-area-owner');
    if (!t) {
      t = randomToken();
      localStorage.setItem('green-area-owner', t);
    }
    _cached = t;
    return t;
  } catch {
    // localStorage ถูกบล็อก → ใช้ token ชั่วคราวต่อ session (ลบเองไม่ได้ข้าม reload)
    _cached = _cached || randomToken();
    return _cached;
  }
}

/** ลืม token ที่ cache ไว้ — เรียกตอนถอนความยินยอม ไม่ให้ค่าที่มาจาก localStorage
 *  (ซึ่งถูกลบไปแล้ว) ถูกใช้ต่อทั้งที่ผู้ใช้ถอนความยินยอมแล้ว */
export function resetOwnerToken() {
  _cached = null;
}
