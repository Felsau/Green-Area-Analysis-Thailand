import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import AdminModal from './AdminModal';

// mock ชั้น fetch กลางของแอป — AdminModal → useAdmin → fetchWithRetry
const fetchWithRetry = vi.fn();
vi.mock('../utils/fetchRetry', () => ({
  fetchWithRetry: (...args) => fetchWithRetry(...args),
}));

const jsonRes = (body, ok = true, status = 200) => ({
  ok, status, json: async () => body,
});

const USERS = [
  { id: 'admin-1', email: 'admin@example.com', display_name: 'แอดมิน',
    organization: 'เทศบาล', role: 'admin', role_label: 'ผู้ดูแลระบบ',
    created_at: '2026-01-01T00:00:00Z', is_me: true },
  { id: 'u-2', email: 'gis@example.com', display_name: 'เจ้าหน้าที่ภูมิสารสนเทศ',
    organization: null, role: 'user', role_label: 'เจ้าหน้าที่ GIS',
    created_at: '2026-02-01T00:00:00Z', is_me: false },
];

beforeEach(() => {
  fetchWithRetry.mockReset();
  fetchWithRetry.mockResolvedValue(jsonRes(USERS));
});

describe('AdminModal — หน้าจัดการระบบ', () => {
  it('ปิดอยู่ = ไม่เรียก API และไม่เรนเดอร์อะไร', () => {
    const { container } = render(<AdminModal open={false} onClose={() => {}} />);
    expect(container).toBeEmptyDOMElement();
    expect(fetchWithRetry).not.toHaveBeenCalled();
  });

  it('เปิดแล้วโหลดรายชื่อผู้ใช้มาแสดง พร้อมป้าย "คุณ" ที่แถวของตัวเอง', async () => {
    render(<AdminModal open onClose={() => {}} />);
    expect(await screen.findByText('เจ้าหน้าที่ภูมิสารสนเทศ')).toBeInTheDocument();
    expect(screen.getByText('admin@example.com')).toBeInTheDocument();
    expect(screen.getByText('คุณ')).toBeInTheDocument();
  });

  it('เปลี่ยนบทบาทสำเร็จ → ยิง PATCH และขึ้นข้อความยืนยัน', async () => {
    const user = userEvent.setup();
    render(<AdminModal open onClose={() => {}} />);
    const select = await screen.findByLabelText('บทบาทของ เจ้าหน้าที่ภูมิสารสนเทศ');

    fetchWithRetry.mockResolvedValueOnce(jsonRes({ ...USERS[1], role: 'admin' }));
    await user.selectOptions(select, 'admin');

    await waitFor(() => {
      const [url, opts] = fetchWithRetry.mock.calls.at(-1);
      expect(url).toMatch(/\/admin\/users\/u-2\/role$/);
      expect(opts.method).toBe('PATCH');
      expect(JSON.parse(opts.body)).toEqual({ role: 'admin' });
    });
    expect(await screen.findByText(/เปลี่ยนบทบาทของ เจ้าหน้าที่ภูมิสารสนเทศ แล้ว/))
      .toBeInTheDocument();
  });

  it('backend ปฏิเสธ → แสดงเหตุผลจาก backend ตรง ๆ ไม่กลืนเป็นข้อความทั่วไป', async () => {
    const user = userEvent.setup();
    render(<AdminModal open onClose={() => {}} />);
    const select = await screen.findByLabelText('บทบาทของ แอดมิน');

    fetchWithRetry.mockResolvedValueOnce(
      jsonRes({ detail: 'ต้องเหลือผู้ดูแลระบบอย่างน้อย 1 คน' }, false, 400));
    await user.selectOptions(select, 'user');

    expect(await screen.findByText('ต้องเหลือผู้ดูแลระบบอย่างน้อย 1 คน')).toBeInTheDocument();
  });

  it('ล้างแคชต้องกดยืนยันก่อน — กดปุ่มแรกยังไม่ยิง DELETE', async () => {
    const user = userEvent.setup();
    render(<AdminModal open onClose={() => {}} />);
    await screen.findByText('เจ้าหน้าที่ภูมิสารสนเทศ');

    await user.click(screen.getByRole('button', { name: 'ล้างข้อมูลที่จัดเก็บชั่วคราว' }));
    expect(fetchWithRetry.mock.calls.some(([, o]) => o?.method === 'DELETE')).toBe(false);

    fetchWithRetry.mockResolvedValueOnce(jsonRes({ message: '✅ Cache cleared' }));
    await user.click(screen.getByRole('button', { name: 'ยืนยัน' }));

    await waitFor(() => {
      const [url, opts] = fetchWithRetry.mock.calls.at(-1);
      expect(url).toMatch(/\/cache$/);
      expect(opts.method).toBe('DELETE');
    });
  });

  it('โหลดรายชื่อไม่สำเร็จ → แสดงข้อความผิดพลาด ไม่ค้างหน้าเปล่า', async () => {
    fetchWithRetry.mockResolvedValue(jsonRes({ detail: 'Unauthorized' }, false, 401));
    render(<AdminModal open onClose={() => {}} />);
    expect(await screen.findByText('Unauthorized')).toBeInTheDocument();
  });
});
