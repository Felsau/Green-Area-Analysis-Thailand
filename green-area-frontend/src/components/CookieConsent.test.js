import { beforeEach, expect, test, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import CookieConsent from './CookieConsent';
import { acceptAll, isAllowed, resetConsent } from '../utils/consent';

beforeEach(() => {
  localStorage.clear();
  resetConsent();
});

const setup = (props = {}) => render(
  <CookieConsent settingsOpen={false} onSettingsOpenChange={() => {}}
                 onOpenPolicy={() => {}} {...props} />);

test('แบนเนอร์ขึ้นเมื่อยังไม่เคยตัดสินใจ', () => {
  setup();
  expect(screen.getByRole('region', { name: 'การตั้งค่าคุกกี้' })).toBeInTheDocument();
});

test('ตัดสินใจแล้วแบนเนอร์ไม่ขึ้นอีก', () => {
  acceptAll();
  const { container } = setup();
  expect(container).toBeEmptyDOMElement();
});

test('ปุ่มยอมรับและปฏิเสธมีน้ำหนักเท่ากัน (ไม่ใช่ dark pattern)', () => {
  setup();
  const accept = screen.getByRole('button', { name: 'ยอมรับทั้งหมด' });
  const reject = screen.getByRole('button', { name: 'ใช้เฉพาะที่จำเป็น' });
  // ทั้งคู่เป็นปุ่มจริงระดับเดียวกัน — ปฏิเสธต้องไม่ถูกลดเป็นลิงก์ตัวเล็ก
  expect(reject.className).toContain('btn');
  expect(reject.className).not.toContain('btn--text');
  expect(accept.className).toContain('btn');
});

test('ไม่มีปุ่มปิดแบนเนอร์ทิ้ง — "ไม่ตอบ" ต้องไม่ถูกนับว่ายินยอม', () => {
  setup();
  const bar = screen.getByRole('region', { name: 'การตั้งค่าคุกกี้' });
  expect(within(bar).queryByRole('button', { name: /ปิด|×/ })).toBeNull();
});

test('กดยอมรับทั้งหมดแล้วหมวดที่เลือกได้ถูกเปิด', async () => {
  const user = userEvent.setup();
  setup();
  await user.click(screen.getByRole('button', { name: 'ยอมรับทั้งหมด' }));
  expect(isAllowed('functional')).toBe(true);
});

test('กดใช้เฉพาะที่จำเป็นแล้วหมวดที่เลือกได้ยังปิด', async () => {
  const user = userEvent.setup();
  setup();
  await user.click(screen.getByRole('button', { name: 'ใช้เฉพาะที่จำเป็น' }));
  expect(isAllowed('functional')).toBe(false);
});

test('แบนเนอร์บอกตรง ๆ ว่าไม่มีคุกกี้ติดตาม', () => {
  setup();
  expect(screen.getByText(/ไม่มีคุกกี้ติดตาม ไม่มี analytics ไม่มีโฆษณา/)).toBeInTheDocument();
});

test('เปิดหน้าตั้งค่าจากแบนเนอร์ได้', async () => {
  const user = userEvent.setup();
  const onSettingsOpenChange = vi.fn();
  setup({ onSettingsOpenChange });
  await user.click(screen.getByRole('button', { name: 'ตั้งค่า' }));
  expect(onSettingsOpenChange).toHaveBeenCalledWith(true);
});

// ── หน้าตั้งค่ารายหมวด ─────────────────────────────────────────────────────
test('สวิตช์เริ่มที่ปิดเสมอเมื่อยังไม่เคยเลือก (opt-in)', () => {
  setup({ settingsOpen: true });
  expect(screen.getByRole('checkbox', { name: 'คุกกี้หมวดเพื่อการทำงาน' })).not.toBeChecked();
});

test('หมวดจำเป็นอย่างยิ่งปิดไม่ได้', () => {
  setup({ settingsOpen: true });
  expect(screen.getByRole('checkbox', { name: 'คุกกี้หมวดจำเป็นอย่างยิ่ง' })).toBeDisabled();
});

test('แสดงชื่อคีย์ วัตถุประสงค์ และระยะเวลาของทุกรายการที่เก็บ', () => {
  setup({ settingsOpen: true });
  expect(screen.getByText('theme')).toBeInTheDocument();
  expect(screen.getByText('green-area-owner')).toBeInTheDocument();
  expect(screen.getByText(/จำว่าผู้ใช้ล็อกอินอยู่/)).toBeInTheDocument();
  expect(screen.getAllByText(/เก็บไว้:/).length).toBeGreaterThanOrEqual(4);
});

test('เปิดสวิตช์แล้วกดบันทึกจึงมีผล', async () => {
  const user = userEvent.setup();
  const onSettingsOpenChange = vi.fn();
  setup({ settingsOpen: true, onSettingsOpenChange });
  await user.click(screen.getByRole('checkbox', { name: 'คุกกี้หมวดเพื่อการทำงาน' }));
  expect(isAllowed('functional')).toBe(false);      // ยังไม่บันทึก = ยังไม่มีผล
  await user.click(screen.getByRole('button', { name: 'บันทึกตัวเลือก' }));
  expect(isAllowed('functional')).toBe(true);
  expect(onSettingsOpenChange).toHaveBeenCalledWith(false);
});

test('สวิตช์สะท้อนตัวเลือกเดิมเมื่อเปิดหน้าตั้งค่าซ้ำ', () => {
  acceptAll();
  setup({ settingsOpen: true });
  expect(screen.getByRole('checkbox', { name: 'คุกกี้หมวดเพื่อการทำงาน' })).toBeChecked();
});

test('ถอนความยินยอมจากหน้าตั้งค่าได้ในคลิกเดียว', async () => {
  const user = userEvent.setup();
  acceptAll();
  setup({ settingsOpen: true });
  await user.click(screen.getByRole('button', { name: 'ปฏิเสธทั้งหมดที่เลือกได้' }));
  expect(isAllowed('functional')).toBe(false);
});
