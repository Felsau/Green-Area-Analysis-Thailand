import { render, screen, fireEvent } from '@testing-library/react';
import TrendTab from './TrendTab';
import { exportTrendCsv } from '../../utils/exportUtils';

vi.mock('../../utils/exportUtils', () => ({ exportTrendCsv: vi.fn() }));

const handlers = { onFetchTrend: () => {}, setTrendYears: () => {}, setTrendMetric: () => {} };
const renderTrend = (trendLoading) => render(<TrendTab data={{
  selectedProvinceEN: 'Bangkok Metropolis',
  trendYears: [2020, 2021, 2022],
  trendData: [{ year: 2020, ndvi_mean: 0.3, green_area_pct: 20 }],
  trendLoading,
  trendProgress: 'กำลังโหลดปี 2021 (2/3)...',
  trendMetric: 'ndvi_mean',
}} handlers={handlers} />);

beforeEach(() => vi.clearAllMocks());

// B2: trendData เติมทีละปีระหว่างโหลด — ส่งออกตอนนี้ได้แนวโน้มไม่ครบปี
test('while the trend is loading, export is disabled and CSV exports nothing', () => {
  renderTrend(true);
  const csv = screen.getByRole('button', { name: 'CSV' });
  expect(csv).toBeDisabled();
  fireEvent.click(csv);
  expect(exportTrendCsv).not.toHaveBeenCalled();
});

test('after the trend has loaded, CSV export works', () => {
  renderTrend(false);
  const csv = screen.getByRole('button', { name: 'CSV' });
  expect(csv).toBeEnabled();
  fireEvent.click(csv);
  expect(exportTrendCsv).toHaveBeenCalledTimes(1);
});
