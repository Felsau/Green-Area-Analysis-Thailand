import { render, screen } from '@testing-library/react';
import ValidationNote from './ValidationNote';

// ก้อนเดียวกับที่ backend ส่งมา (validation.py::build_validation)
// อำนาจเจริญ ปี 2021 ของจริง — เคสนาข้าว NDVI ต่ำกว่าค่าอ้างอิง
const AGRICULTURAL = {
  available: true,
  ndvi_green_pct: 82.8,
  worldcover_green_pct: 96.9,
  error_pp: -14.1,
  target_pp: 10.0,
  within_target: false,
  year: 2021,
  worldcover_epoch_year: 2021,
  breakdown: {
    false_negative_pp: 16.4,
    false_positive_pp: 1.4,
    net_pp: -14.9,
    reference_scale_delta_pp: 0.8,
    by_class: [
      { code: 40, name: 'พื้นที่เกษตร (Cropland)', kind: 'false_negative', pp: 15.7 },
      { code: 50, name: 'สิ่งปลูกสร้าง (Built-up)', kind: 'false_positive', pp: 1.2 },
      { code: 10, name: 'ไม้ยืนต้น (Tree cover)', kind: 'false_negative', pp: 0.7 },
    ],
    dominant: { code: 40, name: 'พื้นที่เกษตร (Cropland)', kind: 'false_negative', pp: 15.7 },
  },
  note: 'NDVI (green_area_pct 82.8%) ต่ำกว่า ESA WorldCover (96.9%) อยู่ 14.1 จุด%',
};

// กรุงเทพฯ ปี 2021 — เคสเมือง ทิศทางตรงข้าม
const URBAN = {
  ...AGRICULTURAL,
  ndvi_green_pct: 62.0,
  worldcover_green_pct: 45.1,
  error_pp: 16.9,
  breakdown: {
    false_negative_pp: 7.7,
    false_positive_pp: 32.0,
    net_pp: 24.3,
    reference_scale_delta_pp: -7.4,
    by_class: [
      { code: 50, name: 'สิ่งปลูกสร้าง (Built-up)', kind: 'false_positive', pp: 24.6 },
    ],
    dominant: { code: 50, name: 'สิ่งปลูกสร้าง (Built-up)', kind: 'false_positive', pp: 24.6 },
  },
};

test('renders nothing for cached rows without validation', () => {
  const { container } = render(<ValidationNote validation={null} />);
  expect(container).toBeEmptyDOMElement();
});

test('renders nothing when the province has no backfilled reference yet', () => {
  const { container } = render(
    <ValidationNote validation={{ ...AGRICULTURAL, available: false }} />);
  expect(container).toBeEmptyDOMElement();
});

test('shows both numbers being compared', () => {
  render(<ValidationNote validation={AGRICULTURAL} />);
  expect(screen.getByText(/82\.8% \/ 96\.9%/)).toBeInTheDocument();
});

test('reports the gap as a magnitude', () => {
  render(<ValidationNote validation={AGRICULTURAL} />);
  expect(screen.getByText('14.1 จุด%')).toBeInTheDocument();
});

test('names the dominant cause and its direction', () => {
  render(<ValidationNote validation={AGRICULTURAL} />);
  // ชื่อคลาสโผล่ทั้งบรรทัด "ต้นเหตุหลัก" และในรายการแยกตามประเภท — ตั้งใจให้ซ้ำ
  expect(screen.getAllByText(/พื้นที่เกษตร \(Cropland\)/).length).toBeGreaterThan(0);
  expect(screen.getByText('WorldCover นับเป็นสีเขียว แต่ NDVI ไม่นับ')).toBeInTheDocument();
});

test('flips the direction wording for the urban case', () => {
  render(<ValidationNote validation={URBAN} />);
  expect(screen.getByText('NDVI นับเป็นสีเขียว แต่ WorldCover ไม่นับ')).toBeInTheDocument();
});

test('never labels a province as failing — the difference is definitional', () => {
  // ตั้งใจไม่ใช้คำว่า "ไม่ผ่าน" กับจังหวัด เพราะความต่างมาจากนิยาม ไม่ใช่ข้อมูลผิด
  const { container } = render(<ValidationNote validation={AGRICULTURAL} />);
  expect(container.textContent).not.toMatch(/ไม่ผ่าน/);
  expect(screen.getByText(/ต่างมาก/)).toBeInTheDocument();
});

test('marks a within-target province as in range', () => {
  render(<ValidationNote validation={{ ...AGRICULTURAL, error_pp: -2.2, within_target: true }} />);
  expect(screen.getByText(/อยู่ในเกณฑ์/)).toBeInTheDocument();
});

test('lists the per-class breakdown with signed contributions', () => {
  render(<ValidationNote validation={AGRICULTURAL} />);
  expect(screen.getByText('−15.7')).toBeInTheDocument();   // false_negative = ลบ
  expect(screen.getByText('+1.2')).toBeInTheDocument();    // false_positive = บวก
});

test('compact mode drops the breakdown list and the explainer', () => {
  const { container } = render(<ValidationNote validation={AGRICULTURAL} compact />);
  expect(container.textContent).not.toMatch(/แยกตามประเภทพื้นที่/);
  expect(container.textContent).not.toMatch(/เป็นเรื่องของ/);
  expect(screen.getByText('14.1 จุด%')).toBeInTheDocument();  // ตัวเลขหลักยังอยู่
});

test('flags when the reference year differs from the selected year', () => {
  render(<ValidationNote validation={{ ...AGRICULTURAL, year: 2024 }} />);
  expect(screen.getByText(/ข้อมูล WorldCover ปี 2021/)).toBeInTheDocument();
});
