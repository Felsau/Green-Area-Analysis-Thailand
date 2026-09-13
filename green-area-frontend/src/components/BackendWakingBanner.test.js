import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, act } from '@testing-library/react';
import BackendWakingBanner from './BackendWakingBanner';
import { beginRequest, endRequest, markServerAlive, resetBackendStatus } from '../utils/backendStatus';
import { API_COLD_START_HINT_MS } from '../constants';

beforeEach(() => { vi.useFakeTimers(); resetBackendStatus(); });
afterEach(() => { vi.useRealTimers(); resetBackendStatus(); });

const tick = (ms) => act(() => { vi.advanceTimersByTime(ms); });

describe('BackendWakingBanner', () => {
  it('ไม่ขึ้นอะไรเลยตอนไม่มีคำขอค้าง', () => {
    render(<BackendWakingBanner />);
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });

  it('คำขอที่จบเร็วกว่าเกณฑ์ ไม่ขึ้นป้ายรบกวนผู้ใช้', () => {
    render(<BackendWakingBanner />);
    act(() => { beginRequest(); });
    tick(API_COLD_START_HINT_MS - 500);
    act(() => { endRequest(); });
    tick(API_COLD_START_HINT_MS * 2);
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });

  it('ยังไม่เคยได้ response → ขึ้นข้อความปลุกเซิร์ฟเวอร์', () => {
    render(<BackendWakingBanner />);
    act(() => { beginRequest(); });
    tick(API_COLD_START_HINT_MS + 100);
    expect(screen.getByText('กำลังปลุกเซิร์ฟเวอร์ อาจใช้เวลาประมาณ 1 นาที')).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveAttribute('aria-live', 'polite');
  });

  // อาการที่ผู้ใช้รายงาน: อยู่หน้า AI แนะนำที่เครื่องตื่นอยู่แล้ว แต่ป้ายบอกว่ากำลังปลุก
  it('เครื่องตื่นอยู่แล้วแต่งานช้า → ต้องบอกว่ากำลังประมวลผล ไม่ใช่กำลังปลุก', () => {
    render(<BackendWakingBanner />);
    act(() => { markServerAlive(); beginRequest(); });
    tick(API_COLD_START_HINT_MS + 100);

    expect(screen.getByText(/กำลังประมวลผลข้อมูลดาวเทียม/)).toBeInTheDocument();
    expect(screen.queryByText(/กำลังปลุกเซิร์ฟเวอร์/)).not.toBeInTheDocument();
  });

  it('ป้ายเปลี่ยนข้อความเองเมื่อพิสูจน์ได้ว่าเครื่องตื่นระหว่างที่ยังรออยู่', () => {
    render(<BackendWakingBanner />);
    act(() => { beginRequest(); beginRequest(); });
    tick(API_COLD_START_HINT_MS + 100);
    expect(screen.getByText(/กำลังปลุกเซิร์ฟเวอร์/)).toBeInTheDocument();

    // คำขอตัวหนึ่งตอบกลับมา → อีกตัวที่ยังค้างไม่ใช่ cold start อีกต่อไป
    act(() => { markServerAlive(); endRequest(); });
    expect(screen.getByText(/กำลังประมวลผลข้อมูลดาวเทียม/)).toBeInTheDocument();
    expect(screen.queryByText(/กำลังปลุกเซิร์ฟเวอร์/)).not.toBeInTheDocument();
  });

  it('เมื่อคำขอจบ ป้ายต้องหาย ไม่ค้าง', () => {
    render(<BackendWakingBanner />);
    act(() => { beginRequest(); });
    tick(API_COLD_START_HINT_MS + 100);
    expect(screen.getByRole('status')).toBeInTheDocument();

    act(() => { endRequest(); });
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });

  it('หลายคำขอซ้อนกัน ป้ายหายเมื่อตัวสุดท้ายจบเท่านั้น', () => {
    render(<BackendWakingBanner />);
    act(() => { beginRequest(); beginRequest(); beginRequest(); });
    tick(API_COLD_START_HINT_MS + 100);
    expect(screen.getByRole('status')).toBeInTheDocument();

    act(() => { endRequest(); endRequest(); });
    expect(screen.getByRole('status')).toBeInTheDocument();

    act(() => { endRequest(); });
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });

  it('เลิก subscribe ตอน unmount — ไม่ setState หลัง unmount', () => {
    const { unmount } = render(<BackendWakingBanner />);
    unmount();
    expect(() => {
      act(() => { beginRequest(); });
      tick(API_COLD_START_HINT_MS + 100);
    }).not.toThrow();
  });
});
