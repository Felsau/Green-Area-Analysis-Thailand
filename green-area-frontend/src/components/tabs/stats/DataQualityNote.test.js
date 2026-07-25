import { render, screen } from '@testing-library/react';
import DataQualityNote from './DataQualityNote';

// ก้อนเดียวกับที่ backend ส่งมา (routers/ndvi/compute.py::build_data_quality)
const DQ = {
  image_count: 65,
  cloud_filter_pct: 20,
  clear_obs_mean: 21.6,
  clear_obs_min: 14,
  ndvi_sd_mean: 0.06,
  uncertainty: 0.0162,
  uncertainty_2sigma_pct: 8.6,
  first_date: '2024-01-01',
  last_date: '2024-12-31',
  months_covered: 9,
  months_missing: [7, 8, 9],
  seasons_covered: ['ฤดูร้อน', 'ฤดูฝน', 'ฤดูหนาว'],
  seasons_missing: [],
  seasonally_representative: true,
  level: 'threshold',
  label: 'ผ่านเกณฑ์ Threshold (GCOS)',
  note: 'median composite จากภาพ Sentinel-2 65 ภาพ (เมฆทั้งภาพ < 20%)',
};

test('renders nothing for cached rows without data_quality', () => {
  const { container } = render(<DataQualityNote dataQuality={null} />);
  expect(container).toBeEmptyDOMElement();
});

test('shows the GCOS level with the measured uncertainty', () => {
  render(<DataQualityNote dataQuality={DQ} />);
  expect(screen.getByText(/ผ่านเกณฑ์ Threshold/)).toBeInTheDocument();
  expect(screen.getByText(/±0\.032 NDVI · 8\.6% \(2σ\)/)).toBeInTheDocument();
  expect(screen.getByText(/65 ภาพ · 21\.6 ภาพปลอดเมฆ\/pixel · 9\/12 เดือน/)).toBeInTheDocument();
  expect(screen.getByText(/median composite จากภาพ Sentinel-2/)).toBeInTheDocument();
});

test('passing levels are not styled as warnings', () => {
  const { container } = render(<DataQualityNote dataQuality={DQ} />);
  expect(container.querySelector('.note--warn')).toBeNull();
  expect(container.querySelector('.note--crit')).toBeNull();
});

test('below-threshold is flagged and names the missing season', () => {
  const { container } = render(
    <DataQualityNote dataQuality={{
      ...DQ, level: 'below', label: 'ต่ำกว่าเกณฑ์ GCOS',
      seasons_missing: ['ฤดูฝน'], seasonally_representative: false,
    }} />);
  expect(container.querySelector('.note--warn')).not.toBeNull();
  expect(screen.getByText(/ไม่มีภาพฤดูฤดูฝน/)).toBeInTheDocument();
});

test('compact mode keeps the headline only (ใช้ในการ์ดพื้นที่ที่วาดเอง)', () => {
  render(<DataQualityNote dataQuality={DQ} compact />);
  expect(screen.getByText(/65 ภาพ/)).toBeInTheDocument();
  expect(screen.queryByText(/median composite/)).not.toBeInTheDocument();
  expect(screen.queryByText(/2024-01-01/)).not.toBeInTheDocument();
});
