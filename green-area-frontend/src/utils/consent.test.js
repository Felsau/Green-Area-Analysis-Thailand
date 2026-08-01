import { beforeEach, describe, expect, test, vi } from 'vitest';
import {
  CATEGORIES, CONSENT_KEY, CONSENT_VERSION,
  acceptAll, getConsent, isAllowed, rejectOptional, resetConsent, setConsent, subscribe,
} from './consent';

beforeEach(() => {
  localStorage.clear();
  resetConsent();
});

describe('ค่าเริ่มต้นก่อนผู้ใช้ตัดสินใจ', () => {
  test('ยังไม่เคยเลือก = ยังไม่ยินยอม (ไม่ใช่ยินยอมโดยปริยาย)', () => {
    expect(getConsent()).toBeNull();
    expect(isAllowed('functional')).toBe(false);
  });

  test('หมวดจำเป็นอย่างยิ่งใช้ได้เสมอ ไม่ต้องรอความยินยอม', () => {
    expect(isAllowed('necessary')).toBe(true);
  });

  test('ไม่มีหมวด analytics/marketing — ระบบไม่มีจริง จะโชว์ให้ติ๊กไม่ได้', () => {
    const ids = CATEGORIES.map(c => c.id);
    expect(ids).toEqual(['necessary', 'functional']);
  });
});

describe('บันทึกตัวเลือก', () => {
  test('ยอมรับทั้งหมดเปิดหมวดที่เลือกได้', () => {
    acceptAll();
    expect(isAllowed('functional')).toBe(true);
    expect(getConsent().version).toBe(CONSENT_VERSION);
    expect(getConsent().decidedAt).toEqual(expect.any(String));
  });

  test('ใช้เฉพาะที่จำเป็นปิดหมวดที่เลือกได้', () => {
    rejectOptional();
    expect(isAllowed('functional')).toBe(false);
    expect(isAllowed('necessary')).toBe(true);
  });

  test('หมวดที่ไม่ได้ระบุถือว่าไม่ยินยอม — ไม่ใช่ opt-out', () => {
    setConsent({});
    expect(getConsent().categories.functional).toBe(false);
  });

  test('บันทึกลง localStorage เพื่อไม่ถามซ้ำทุกครั้งที่เปิดเว็บ', () => {
    acceptAll();
    expect(JSON.parse(localStorage.getItem(CONSENT_KEY)).categories.functional).toBe(true);
  });
});

describe('ถอนความยินยอมต้องลบของที่เก็บไว้จริง', () => {
  test('ปฏิเสธแล้วคีย์ในหมวดนั้นถูกลบทันที ไม่ใช่แค่หยุดเขียนเพิ่ม', () => {
    localStorage.setItem('theme', 'dark');
    rejectOptional();
    expect(localStorage.getItem('theme')).toBeNull();
  });

  test('ถอนหลังเคยยอมรับก็ลบเช่นกัน', () => {
    acceptAll();
    localStorage.setItem('theme', 'dark');
    rejectOptional();
    expect(localStorage.getItem('theme')).toBeNull();
  });

  test('ไม่แตะคีย์ของหมวดจำเป็นอย่างยิ่ง', () => {
    localStorage.setItem('sb-x-auth-token', 'session');
    rejectOptional();
    expect(localStorage.getItem('sb-x-auth-token')).toBe('session');
  });

  test('ยอมรับแล้วไม่ลบอะไร', () => {
    localStorage.setItem('theme', 'dark');
    acceptAll();
    expect(localStorage.getItem('theme')).toBe('dark');
  });
});

describe('เวอร์ชันของความยินยอม', () => {
  test('เวอร์ชันเก่า = ยังไม่เคยยินยอมในขอบเขตปัจจุบัน จึงต้องถามใหม่', () => {
    localStorage.setItem(CONSENT_KEY, JSON.stringify({
      version: CONSENT_VERSION - 1, categories: { functional: true },
    }));
    resetConsent();          // ล้าง cache ในหน่วยความจำ ให้บังคับอ่านใหม่
    localStorage.setItem(CONSENT_KEY, JSON.stringify({
      version: CONSENT_VERSION - 1, categories: { functional: true },
    }));
    expect(getConsent()).toBeNull();
    expect(isAllowed('functional')).toBe(false);
  });

  test('ค่าที่เสียหายไม่ทำให้พัง และถือว่ายังไม่ยินยอม', () => {
    localStorage.setItem(CONSENT_KEY, 'ไม่ใช่ JSON');
    resetConsent();
    localStorage.setItem(CONSENT_KEY, 'ไม่ใช่ JSON');
    expect(getConsent()).toBeNull();
    expect(isAllowed('functional')).toBe(false);
  });
});

describe('localStorage ถูกบล็อก', () => {
  test('อ่านไม่ได้ = ถือว่ายังไม่ยินยอม ไม่ throw', () => {
    const spy = vi.spyOn(Storage.prototype, 'getItem')
      .mockImplementation(() => { throw new Error('blocked'); });
    resetConsent();
    expect(() => getConsent()).not.toThrow();
    expect(isAllowed('functional')).toBe(false);
    spy.mockRestore();
  });

  test('เขียนไม่ได้ ตัวเลือกยังมีผลใน session นี้', () => {
    const spy = vi.spyOn(Storage.prototype, 'setItem')
      .mockImplementation(() => { throw new Error('blocked'); });
    expect(() => acceptAll()).not.toThrow();
    expect(isAllowed('functional')).toBe(true);
    spy.mockRestore();
  });
});

describe('แจ้งผู้ที่ subscribe', () => {
  test('ทุกที่ที่ผูกไว้รู้ทันทีที่ตัวเลือกเปลี่ยน', () => {
    const seen = [];
    const off = subscribe(() => seen.push(isAllowed('functional')));
    acceptAll();
    rejectOptional();
    off();
    acceptAll();
    expect(seen).toEqual([true, false]);   // หลัง unsubscribe ต้องไม่ถูกเรียกอีก
  });
});

describe('รายการที่ประกาศไว้ตรงกับที่โค้ดใช้จริง', () => {
  test('ทุกรายการมีข้อมูลครบตามที่ต้องแจ้ง (ชื่อคีย์ วัตถุประสงค์ ระยะเวลา)', () => {
    for (const cat of CATEGORIES) {
      expect(cat.items.length).toBeGreaterThan(0);
      for (const it of cat.items) {
        expect(it.key).toBeTruthy();
        expect(it.label).toBeTruthy();
        expect(it.purpose).toBeTruthy();
        expect(it.keep).toBeTruthy();
      }
    }
  });

  test('คีย์ที่ useTheme เขียนจริง ถูกประกาศไว้ในหมวดที่เลือกได้', () => {
    const functionalKeys = CATEGORIES.find(c => c.id === 'functional').items.map(i => i.key);
    expect(functionalKeys).toContain('theme');
  });

  test('ไม่ประกาศ green-area-owner แล้ว — ตัดทิ้งพร้อม migration 019', () => {
    // เอกสารความยินยอมต้องตรงกับของที่เก็บจริง · ประกาศของที่ไม่ได้เก็บแล้ว = แจ้งเกินจริง
    const allKeys = CATEGORIES.flatMap(c => c.items.map(i => i.key));
    expect(allKeys).not.toContain('green-area-owner');
  });
});
