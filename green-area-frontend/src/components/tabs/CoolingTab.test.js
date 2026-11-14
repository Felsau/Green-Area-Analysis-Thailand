import { expect, test, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import CoolingTab from './CoolingTab';

const baseData = {
  selectedProvince: 'กรุงเทพมหานคร',
  selectedProvinceEN: 'Bangkok Metropolis',
  coolingLoading: false,
  coolingYear: 2026,
};
const noop = { onFetchCooling: () => {}, setCoolingYear: () => {} };

const fivePoints = [
  { district: 'A', ndvi: 0.2, lst: 30 }, { district: 'B', ndvi: 0.3, lst: 31 },
  { district: 'C', ndvi: 0.4, lst: 32 }, { district: 'D', ndvi: 0.5, lst: 33 },
  { district: 'E', ndvi: 0.6, lst: 34 },
];

// กรณีจริง 13 ก.ย. 2569: กทม. ปี 2026 มี 5 จาก 50 อำเภอ ได้ความชัน +11.3 (กลับทิศ)
// backend คืน regression=null เมื่อไม่ถึงเกณฑ์ (cooling.py::required_districts)
// หน้าจอต้องไม่โชว์ความชัน แต่ยังบอกว่ามีกี่จากกี่อำเภอ และพาไปปีที่ข้อมูลพอ
const thinYear = {
  year: 2026,
  n_districts: 5,
  total_districts: 50,
  required_districts: 25,
  sufficient: false,
  latest_sufficient_year: 2025,
  points: fivePoints,
  regression: null,
  interpretation: 'ปี 2026 มีอำเภอที่มีข้อมูลครบทั้ง NDVI และ LST 5 จาก 50 อำเภอ ต้องมีอย่างน้อย 25 อำเภอจึงจะคำนวณความชันได้',
};

test('hides the slope when too few districts have data', () => {
  render(<CoolingTab data={{ ...baseData, coolingData: thinYear }} handlers={noop} />);
  expect(screen.queryByText('ความชัน')).not.toBeInTheDocument();
  expect(screen.queryByText('R²')).not.toBeInTheDocument();
  expect(screen.getByText('5 จาก 50 อำเภอ')).toBeInTheDocument();
  expect(screen.getByText(/ต้องมีอย่างน้อย 25 อำเภอ/)).toBeInTheDocument();
});

test('offers the latest year that has enough data', () => {
  const setCoolingYear = vi.fn();
  const onFetchCooling = vi.fn();
  render(<CoolingTab data={{ ...baseData, coolingData: thinYear }}
                     handlers={{ setCoolingYear, onFetchCooling }} />);
  fireEvent.click(screen.getByRole('button', { name: 'ดูปี 2025' }));
  expect(setCoolingYear).toHaveBeenCalledWith(2025);
  expect(onFetchCooling).toHaveBeenCalledWith('Bangkok Metropolis', 2025);
});

test('no year button when no year has enough data', () => {
  render(<CoolingTab data={{
    ...baseData,
    coolingData: { ...thinYear, latest_sufficient_year: null },
  }} handlers={noop} />);
  expect(screen.queryByRole('button', { name: /ดูปี/ })).not.toBeInTheDocument();
});

test('shows slope and R² once the backend returns a regression', () => {
  render(<CoolingTab data={{
    ...baseData,
    coolingYear: 2025,
    coolingData: {
      ...thinYear,
      year: 2025,
      n_districts: 50,
      sufficient: true,
      regression: { slope: -7.47, intercept: 36, r2: 0.62 },
      interpretation: 'พบความสัมพันธ์เชิงลบ (ชัดเจน, R²=0.62, n=50 อำเภอ)',
    },
  }} handlers={noop} />);
  expect(screen.getByText('-7.5')).toBeInTheDocument();
  expect(screen.getByText('0.62')).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /ดูปี/ })).not.toBeInTheDocument();
});

test('year selector defaults to "latest year with enough data"', () => {
  const setCoolingYear = vi.fn();
  render(<CoolingTab data={{ ...baseData, coolingYear: null, coolingData: null }}
                     handlers={{ ...noop, setCoolingYear }} />);
  const select = screen.getByRole('combobox');
  expect(select.value).toBe('');
  fireEvent.change(select, { target: { value: '2024' } });
  expect(setCoolingYear).toHaveBeenCalledWith(2024);
});
