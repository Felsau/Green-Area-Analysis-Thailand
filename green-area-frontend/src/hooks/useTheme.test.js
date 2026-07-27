// ตัวจริงที่กฎหมายสนใจคือ "เขียนลงเบราว์เซอร์ตอนไหน" ไม่ใช่หน้าตาแบนเนอร์ —
// เทสต์ชุดนี้จึงพิสูจน์ว่า useTheme ไม่แตะ localStorage ก่อนได้รับความยินยอม
import { beforeEach, expect, test } from 'vitest';
import { act, renderHook } from '@testing-library/react';
import { useTheme } from './useTheme';
import { acceptAll, rejectOptional, resetConsent } from '../utils/consent';

beforeEach(() => {
  localStorage.clear();
  resetConsent();
  document.documentElement.removeAttribute('data-theme');
});

test('ยังไม่ตัดสินใจ: สลับธีมได้ แต่ไม่บันทึกลงเบราว์เซอร์', () => {
  const { result } = renderHook(() => useTheme());
  act(() => result.current.toggleTheme());
  expect(result.current.theme).toBe('dark');
  expect(document.documentElement.getAttribute('data-theme')).toBe('dark');
  expect(localStorage.getItem('theme')).toBeNull();
});

test('ปฏิเสธ: ยังไม่บันทึก', () => {
  rejectOptional();
  const { result } = renderHook(() => useTheme());
  act(() => result.current.toggleTheme());
  expect(result.current.theme).toBe('dark');
  expect(localStorage.getItem('theme')).toBeNull();
});

test('ยินยอมแล้ว: บันทึกธีมที่เลือก', () => {
  acceptAll();
  const { result } = renderHook(() => useTheme());
  act(() => result.current.toggleTheme());
  expect(localStorage.getItem('theme')).toBe('dark');
});

test('ยินยอมระหว่างใช้งาน: ธีมที่สลับไว้ก่อนหน้าถูกบันทึกทันที ไม่ต้องสลับซ้ำ', () => {
  const { result } = renderHook(() => useTheme());
  act(() => result.current.toggleTheme());
  expect(localStorage.getItem('theme')).toBeNull();
  act(() => { acceptAll(); });
  expect(localStorage.getItem('theme')).toBe('dark');
});

test('ยังไม่ยินยอม: ไม่อ่านค่าเก่าที่ค้างอยู่ในเบราว์เซอร์', () => {
  localStorage.setItem('theme', 'dark');
  const { result } = renderHook(() => useTheme());
  expect(result.current.theme).toBe('light');
});

test('ยินยอมแล้ว: อ่านค่าเดิมกลับมาใช้', () => {
  acceptAll();
  localStorage.setItem('theme', 'dark');
  const { result } = renderHook(() => useTheme());
  expect(result.current.theme).toBe('dark');
});

test('ถอนความยินยอม: คีย์ธีมถูกลบและไม่ถูกเขียนกลับ', () => {
  acceptAll();
  const { result } = renderHook(() => useTheme());
  act(() => result.current.toggleTheme());
  expect(localStorage.getItem('theme')).toBe('dark');
  act(() => { rejectOptional(); });
  expect(localStorage.getItem('theme')).toBeNull();
  act(() => result.current.toggleTheme());
  expect(localStorage.getItem('theme')).toBeNull();
});
