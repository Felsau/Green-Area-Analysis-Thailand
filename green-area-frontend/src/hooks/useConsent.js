import { useCallback, useSyncExternalStore } from 'react';
import { getConsent, subscribe, isAllowed } from '../utils/consent';

// อ่านสถานะความยินยอมคุกกี้แบบ reactive — ทุกที่ที่ผูกกับ hook นี้จะอัปเดตพร้อมกัน
// ทันทีที่ผู้ใช้กดยอมรับ/ถอน (เช่น ธีมหยุดถูกบันทึก แบนเนอร์หายไป) โดยไม่ต้อง reload
//
// useSyncExternalStore เพราะแหล่งความจริงคือ localStorage ซึ่งอยู่นอก React —
// getConsent() คืน object เดิม (cache ใน consent.js) จนกว่าจะมีการเปลี่ยนจริง
// จึงไม่เกิด re-render วนซ้ำจากการเทียบ reference
export function useConsent() {
  const consent = useSyncExternalStore(subscribe, getConsent, () => null);
  const allows = useCallback((categoryId) => isAllowed(categoryId), [consent]); // eslint-disable-line react-hooks/exhaustive-deps
  return { consent, decided: consent !== null, allows };
}
