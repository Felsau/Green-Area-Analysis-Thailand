import { render, screen } from '@testing-library/react';
import OverviewPanel from './OverviewPanel';

const handlers = {
  onFetchRanking: () => {}, setSelectedYear: () => {},
  onComputeMissing: () => {}, onCancelCompute: () => {},
};

// ตัวชี้วัดนี้นับพืชพรรณทุกชนิด (NDVI > 0.3) ไม่ใช่พื้นที่สาธารณะที่เข้าถึงได้ตามนิยาม WHO
// จึงสูงกว่าค่าอ้างอิงแทบทุกจังหวัด (ดู utils/greenMetric.js) — ต้องมีคำเตือนกำกับเสมอ
// และ **ต้องไม่มีคำว่า "ผ่าน/ไม่ผ่าน"** ซึ่งเป็นข้อสรุปที่ข้อมูลรองรับไม่ได้
test('vegetation-per-capita summary carries the WHO caveat and avoids a pass verdict', () => {
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
  expect(screen.getByText(/ไม่ใช่เฉพาะสวนสาธารณะที่เข้าถึงได้/)).toBeInTheDocument();
  expect(screen.getByText('ห้าจังหวัดที่มีพื้นที่สีเขียวต่อคนน้อยที่สุด')).toBeInTheDocument();

  // กันการถอยกลับไปใช้ถ้อยคำตัดสิน — ป้ายสรุปต้องพูดถึง "ค่าอ้างอิง" ไม่ใช่ "ผ่านเกณฑ์"
  expect(screen.getByText(/สูงกว่าค่าอ้างอิง WHO/)).toBeInTheDocument();
  expect(screen.queryByText(/^ผ่าน WHO$/)).not.toBeInTheDocument();
});
