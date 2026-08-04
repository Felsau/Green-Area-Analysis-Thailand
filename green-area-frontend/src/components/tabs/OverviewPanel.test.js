import { render, screen } from '@testing-library/react';
import OverviewPanel from './OverviewPanel';

const handlers = {
  onFetchRanking: () => {}, setSelectedYear: () => {},
  onComputeMissing: () => {}, onCancelCompute: () => {},
};

// รวมป่า/เกษตรทั้งจังหวัดหารประชากรทั้งจังหวัด → เกือบทุกจังหวัด "ผ่าน WHO" เสมอ
// (ดู main.py::get_ranking) ต้องมีคำเตือนกำกับไม่ให้อ่านเป็นสถานะพื้นที่สีเขียวในเมืองจริง
test('WHO pass/fail summary carries the province-wide-vs-urban caveat', () => {
  render(<OverviewPanel data={{
    rankingData: [
      { province: 'Bangkok Metropolis', rank: 1, green_area_m2_per_person: 87.3 },
      { province: 'Mae Hong Son', rank: 77, green_area_m2_per_person: 44577.7 },
    ],
    rankingStats: { total: 77, whoPass: 77, whoFail: 0 },
    selectedYear: 2026,
    ndviCache: {},
    provinceList: [],
  }} handlers={handlers} />);

  expect(screen.getByText('77', { selector: '.kv__value' })).toBeInTheDocument();
  expect(screen.getByText(/ไม่ใช่พื้นที่สีเขียวที่เข้าถึงได้ในเขตเมือง/)).toBeInTheDocument();
  expect(screen.getByText('ห้าจังหวัดที่มีพื้นที่สีเขียวต่อคนน้อยที่สุด')).toBeInTheDocument();
});
