import { render, screen, fireEvent } from '@testing-library/react';
import CompareTab from './CompareTab';
import { exportCompareCsv } from '../../utils/exportUtils';

vi.mock('../../utils/exportUtils', () => ({ exportCompareCsv: vi.fn() }));

const handlers = new Proxy({}, { get: () => () => {} });
const renderCompare = (compareLoading) => render(<CompareTab data={{
  compareList: ['Bangkok Metropolis', 'Chiang Mai'],
  compareYear: 2026,
  compareMetric: 'ndvi_mean',
  compareData: [
    { province: 'Bangkok Metropolis', ndvi_mean: 0.3 },
    { province: 'Chiang Mai', ndvi_mean: 0.5 },
  ],
  compareLoading,
}} handlers={handlers} />);

beforeEach(() => vi.clearAllMocks());

// B2: compareData ของรอบก่อนยังค้างระหว่างโหลดรอบใหม่ — ส่งออกตอนนี้ได้ผลเก่า
test('while the comparison is loading, export is disabled and CSV exports nothing', () => {
  renderCompare(true);
  const csv = screen.getByRole('button', { name: 'CSV' });
  expect(csv).toBeDisabled();
  fireEvent.click(csv);
  expect(exportCompareCsv).not.toHaveBeenCalled();
});

test('after the comparison has loaded, CSV export works', () => {
  renderCompare(false);
  const csv = screen.getByRole('button', { name: 'CSV' });
  expect(csv).toBeEnabled();
  fireEvent.click(csv);
  expect(exportCompareCsv).toHaveBeenCalledTimes(1);
});
