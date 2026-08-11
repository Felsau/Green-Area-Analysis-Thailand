import { render, screen } from '@testing-library/react';
import OverviewPanel from './OverviewPanel';

const handlers = {
  onFetchRanking: () => {}, setSelectedYear: () => {},
  onComputeMissing: () => {}, onCancelCompute: () => {},
};

// ตัวชี้วัดนี้นับพืชพรรณทุกชนิดในเขต built-up ไม่ใช่พื้นที่สาธารณะตามนิยาม WHO
// จึงยังสูงกว่าค่าอ้างอิงแทบทุกจังหวัด — ต้องมีคำเตือนกำกับ ห้ามมีคำว่าผ่าน/ไม่ผ่าน
test('vegetation-per-capita summary carries the WHO caveat and avoids a pass verdict', () => {
  render(<OverviewPanel data={{
    rankingData: [
      { province: 'Bangkok Metropolis', rank: 1, m2_per_person_urban: 31.5 },
      { province: 'Mae Hong Son', rank: 77, m2_per_person_urban: 412.7 },
    ],
    rankingStats: { total: 77, whoPass: 77, whoFail: 0 },
    selectedYear: 2026,
    ndviCache: {},
    provinceList: [],
  }} handlers={handlers} />);

  expect(screen.getByText('77', { selector: '.kv__value' })).toBeInTheDocument();
  expect(screen.getByText(/ไม่ใช่เฉพาะสวนสาธารณะที่เข้าถึงได้/)).toBeInTheDocument();
  expect(screen.getByText('ห้าจังหวัดที่มีพื้นที่สีเขียวในเขตเมืองต่อคนน้อยที่สุด'))
    .toBeInTheDocument();

  // กันการถอยกลับไปใช้ถ้อยคำตัดสิน — ป้ายสรุปต้องพูดถึง "ค่าอ้างอิง" ไม่ใช่ "ผ่านเกณฑ์"
  expect(screen.getByText(/สูงกว่าค่าอ้างอิง WHO/)).toBeInTheDocument();
  expect(screen.queryByText(/^ผ่าน WHO$/)).not.toBeInTheDocument();
});

// แผงนี้คิดจาก urban subset แต่แท็บ "ข้อมูล" ของจังหวัดเดียวกันคิดทั้งจังหวัด
// ค่าจึงต่างกันหลายเท่า (สมุทรปราการ 38.2 กับ 354.7) — ถ้าไม่ติดป้ายบอกขอบเขต
// ผู้อ่านจะเห็นสองตัวเลขขัดกันเองโดยไม่มีคำอธิบาย
test('ranking states its scope is built-up area only, not the whole province', () => {
  render(<OverviewPanel data={{
    rankingData: [{ province: 'Bangkok Metropolis', rank: 1, m2_per_person_urban: 30.1 }],
    rankingStats: { total: 77, whoPass: 77, whoFail: 0 },
    selectedYear: 2026,
    ndviCache: {},
    provinceList: [],
  }} handlers={handlers} />);

  expect(screen.getByText(/พื้นที่สิ่งปลูกสร้าง \(เขตเมือง\)/)).toBeInTheDocument();
  expect(screen.getByText(/ไม่ใช่ทั้งจังหวัด/)).toBeInTheDocument();
});
