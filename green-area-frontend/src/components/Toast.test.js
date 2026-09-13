import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, act } from '@testing-library/react';
import Toast from './Toast';
import { pushError, pushInfo } from '../utils/toast';

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

const push = (fn, ...args) => act(() => { fn(...args); });

describe('Toast — การยุบข้อความซ้ำ', () => {
  it('ข้อความเดียวกันเด้งซ้ำ ต้องเห็นอันเดียว', () => {
    render(<Toast />);
    push(pushError, 'ติดต่อเซิร์ฟเวอร์ไม่ได้');
    push(pushError, 'ติดต่อเซิร์ฟเวอร์ไม่ได้');
    push(pushError, 'ติดต่อเซิร์ฟเวอร์ไม่ได้');
    expect(screen.getAllByText('ติดต่อเซิร์ฟเวอร์ไม่ได้')).toHaveLength(1);
  });

  it('คำขอหลายตัวล้มด้วยสาเหตุเดียวกัน (key ร่วม) ยุบเหลือข้อความเดียว', () => {
    render(<Toast />);
    // จำลอง useProvinceData / useDistrictData / useRankingData ล้มพร้อมกันตอน backend หลับ
    push(pushError, 'เซิร์ฟเวอร์ไม่ตอบ — จังหวัด', { key: 'api:unreachable' });
    push(pushError, 'เซิร์ฟเวอร์ไม่ตอบ — อำเภอ', { key: 'api:unreachable' });
    push(pushError, 'เซิร์ฟเวอร์ไม่ตอบ — อันดับ', { key: 'api:unreachable' });

    expect(screen.queryByText('เซิร์ฟเวอร์ไม่ตอบ — จังหวัด')).not.toBeInTheDocument();
    expect(screen.getByText('เซิร์ฟเวอร์ไม่ตอบ — อันดับ')).toBeInTheDocument();
    expect(screen.getAllByRole('alert')).toHaveLength(1);
  });

  it('ข้อความคนละเรื่องยังแสดงครบ', () => {
    render(<Toast />);
    push(pushError, 'โหลดข้อมูลจังหวัดไม่สำเร็จ', { key: 'api:จังหวัด' });
    push(pushError, 'โหลดข้อมูลอำเภอไม่สำเร็จ', { key: 'api:อำเภอ' });
    expect(screen.getAllByRole('alert')).toHaveLength(2);
  });

  it('เด้งซ้ำแล้วต้องนับเวลาถอยหลังใหม่ ไม่หายตามตัวเดิม', () => {
    render(<Toast />);
    push(pushError, 'เซิร์ฟเวอร์ไม่ตอบ', { duration: 5000 });
    act(() => { vi.advanceTimersByTime(4000); });
    push(pushError, 'เซิร์ฟเวอร์ไม่ตอบ', { duration: 5000 });

    // ถ้าไม่เคลียร์ตัวจับเวลาเดิม อันนี้จะหายไปตอน 5000 ของรอบแรก
    act(() => { vi.advanceTimersByTime(2000); });
    expect(screen.getByText('เซิร์ฟเวอร์ไม่ตอบ')).toBeInTheDocument();

    act(() => { vi.advanceTimersByTime(4000); });
    expect(screen.queryByText('เซิร์ฟเวอร์ไม่ตอบ')).not.toBeInTheDocument();
  });

  it('error กับ info ที่ข้อความเหมือนกัน ไม่ยุบรวมกัน', () => {
    render(<Toast />);
    push(pushError, 'บันทึกพื้นที่');
    push(pushInfo, 'บันทึกพื้นที่');
    expect(screen.getAllByText('บันทึกพื้นที่')).toHaveLength(2);
  });
});
