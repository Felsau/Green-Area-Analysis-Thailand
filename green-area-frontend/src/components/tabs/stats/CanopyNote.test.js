import { render, screen } from '@testing-library/react';
import CanopyNote from './CanopyNote';

// ก้อนเดียวกับที่ backend ส่งมา (canopy.py::build_canopy) — ปทุมวัน ปี 2024 ของจริง
const CANOPY = {
  available: true,
  canopy_pct: 14.6,
  canopy_km2: 1.4,
  target_pct: 30.0,
  meets_target: false,
  gap_pct: 15.4,
  source: 'ESA WorldCover v200',
  epoch_year: 2021,
  epoch_offset_years: 3,
  trend: {
    source: 'Dynamic World V1',
    year: 2024, baseline_year: 2021,
    canopy_pct: 4.7, baseline_pct: 4.9,
    change_pp: -0.2, direction: 'stable',
    coverage_pct: 100.0,
    note: 'Dynamic World วัดเรือนยอดปี 2024 ได้ 4.7%',
  },
  label: 'ต่ำกว่าเกณฑ์ 30% ⚠️ (14.6% — ขาดอีก 15.4 จุด%)',
  note: 'เรือนยอดไม้ปกคลุม 14.6% ของพื้นที่',
};

test('renders nothing for cached rows without canopy', () => {
  const { container } = render(<CanopyNote canopy={null} />);
  expect(container).toBeEmptyDOMElement();
});

test('renders nothing when WorldCover had no data', () => {
  const { container } = render(<CanopyNote canopy={{ ...CANOPY, available: false }} />);
  expect(container).toBeEmptyDOMElement();
});

test('shows the gap against the 30% rule in both points and km²', () => {
  render(<CanopyNote canopy={CANOPY} areaKm2={9.6} />);
  expect(screen.getByText(/ต่ำกว่าเกณฑ์/)).toBeInTheDocument();
  expect(screen.getByText('14.6 / 30%')).toBeInTheDocument();
  expect(screen.getByText('15.4 จุด%')).toBeInTheDocument();
  expect(screen.getByText('1.5 km²')).toBeInTheDocument();   // 15.4% ของ 9.6 km²
});

test('derives the area from canopy_km2 when the caller has none', () => {
  render(<CanopyNote canopy={CANOPY} />);
  expect(screen.getByText('1.5 km²')).toBeInTheDocument();   // 1.4 / 0.146 ≈ 9.6 km²
});

test('passing areas are not styled as warnings', () => {
  const { container } = render(
    <CanopyNote canopy={{ ...CANOPY, canopy_pct: 97.4, meets_target: true, gap_pct: 0 }} />);
  expect(container.querySelector('.note--warn')).toBeNull();
  expect(container.querySelector('.note--crit')).toBeNull();
  expect(screen.getByText(/เกินเกณฑ์อยู่/)).toBeInTheDocument();
});

test('a large shortfall is escalated above a small one', () => {
  const near = render(<CanopyNote canopy={{ ...CANOPY, canopy_pct: 26, gap_pct: 4 }} />);
  expect(near.container.querySelector('.note--warn')).not.toBeNull();
  near.unmount();
  const far = render(<CanopyNote canopy={CANOPY} />);
  expect(far.container.querySelector('.note--crit')).not.toBeNull();
});

test('always states the data epoch — the headline number is not the selected year', () => {
  render(<CanopyNote canopy={CANOPY} />);
  expect(screen.getByText(/ESA WorldCover ปี 2021/)).toBeInTheDocument();
  expect(screen.getByText(/ห่างกัน 3 ปี/)).toBeInTheDocument();
});

test('trend is shown with its direction and the caveat about Dynamic World', () => {
  render(<CanopyNote canopy={{
    ...CANOPY, trend: { ...CANOPY.trend, change_pp: -2.0, direction: 'decrease' },
  }} />);
  expect(screen.getByText(/ลดลง 2\.0 จุด%/)).toBeInTheDocument();
  expect(screen.getByText(/ใช้อ่านได้เฉพาะทิศทาง/)).toBeInTheDocument();
});

test('compact mode keeps the headline only', () => {
  render(<CanopyNote canopy={CANOPY} compact />);
  expect(screen.getByText('14.6 / 30%')).toBeInTheDocument();
  expect(screen.queryByText(/ESA WorldCover ปี 2021/)).not.toBeInTheDocument();
});
