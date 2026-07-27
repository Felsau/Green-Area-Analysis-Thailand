import { useCallback, useEffect, useState } from 'react';
import { isAllowed } from '../utils/consent';
import { useConsent } from './useConsent';

// Colour theme (light/dark) — applied to the <html> element. Defaults to light;
// deep-links never depend on theme so this is purely a UI preference.
//
// การ *จำ* ธีมข้ามการเปิดเว็บเป็นหมวด "เพื่อการทำงาน" ตาม PDPA จึงเขียนลง
// localStorage ได้ต่อเมื่อผู้ใช้ยินยอมแล้วเท่านั้น (utils/consent.js) — ยังไม่ยินยอม
// ก็สลับธีมได้ตามปกติ แค่ไม่ถูกจำไว้รอบหน้า · ตอนถอนความยินยอม consent.js ลบคีย์
// 'theme' ให้แล้ว ที่นี่จึงแค่หยุดเขียนต่อ
export function useTheme() {
  const { allows } = useConsent();
  const functional = allows('functional');

  const [theme, setTheme] = useState(() => {
    // อ่านค่าเดิมเฉพาะเมื่อยินยอมแล้ว — ยังไม่ตัดสินใจ/ปฏิเสธ ให้เริ่มที่ค่าเริ่มต้นเสมอ
    if (!isAllowed('functional')) return 'light';
    const saved = typeof localStorage !== 'undefined' && localStorage.getItem('theme');
    if (saved === 'light' || saved === 'dark') return saved;
    return 'light';
  });

  // Apply the colour theme on the root element — เป็นการแสดงผล ไม่ใช่การเก็บข้อมูล
  // จึงทำเสมอไม่ว่าจะยินยอมหรือไม่
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    document.documentElement.style.colorScheme = theme;
  }, [theme]);

  // Persist เฉพาะเมื่อได้รับความยินยอม · effect ผูกกับ functional ด้วย เพื่อให้ธีมที่
  // ผู้ใช้สลับไว้ก่อนกดยอมรับถูกบันทึกทันทีที่ยอมรับ โดยไม่ต้องสลับซ้ำอีกรอบ
  useEffect(() => {
    if (!functional) return;
    try { localStorage.setItem('theme', theme); } catch { /* storage blocked — ignore */ }
  }, [theme, functional]);

  const toggleTheme = useCallback(
    () => setTheme(t => (t === 'dark' ? 'light' : 'dark')), []);

  return { theme, toggleTheme };
}
