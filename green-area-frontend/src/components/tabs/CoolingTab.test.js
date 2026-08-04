import { render, screen } from '@testing-library/react';
import CoolingTab from './CoolingTab';

const baseData = {
  selectedProvince: 'ตาก',
  selectedProvinceEN: 'Tak',
  coolingLoading: false,
  coolingYear: 2026,
};
const handlers = { onFetchCooling: () => {}, setCoolingYear: () => {} };

// n=2 — ฟิตเส้นตรง 2 จุดได้ R²=1.0 เสมอโดยนิยาม ไม่ใช่หลักฐานความสัมพันธ์แน่น
// (ดู routers/maps/analysis/cooling.py::_interpret) ต้องเตือนแทนที่จะโชว์ "ความกระชับของเส้น"
test('flags low confidence when n < 5 districts', () => {
  render(<CoolingTab data={{
    ...baseData,
    coolingData: {
      n_districts: 2,
      regression: { slope: -13.3, r2: 1.0 },
      points: [{ district: 'A', ndvi: 0.6, lst: 28 }, { district: 'B', ndvi: 0.2, lst: 34 }],
      interpretation: 'พบแนวโน้มเชิงลบ (ยิ่งเขียวยิ่งเย็น ตามที่คาด) จากอำเภอที่มีข้อมูลครบเพียง 2 แห่ง — ยังน้อยเกินกว่าจะสรุปได้ชัดเจนว่าความสัมพันธ์นี้แน่นแค่ไหน',
    },
  }} handlers={handlers} />);
  expect(screen.getByText(/n=2 — ยังน้อยเกินสรุปนัยสำคัญ/)).toBeInTheDocument();
  expect(screen.queryByText(/ความกระชับของเส้น/)).not.toBeInTheDocument();
});

test('shows the normal hint once enough districts are cached', () => {
  render(<CoolingTab data={{
    ...baseData,
    coolingData: {
      n_districts: 5,
      regression: { slope: -13.3, r2: 0.86 },
      points: [
        { district: 'A', ndvi: 0.2, lst: 34 }, { district: 'B', ndvi: 0.3, lst: 33 },
        { district: 'C', ndvi: 0.4, lst: 32 }, { district: 'D', ndvi: 0.5, lst: 31 },
        { district: 'E', ndvi: 0.6, lst: 30 },
      ],
      interpretation: 'พบความสัมพันธ์เชิงลบ (ชัดเจน, R²=0.86, n=5 อำเภอ)',
    },
  }} handlers={handlers} />);
  expect(screen.getByText('ความกระชับของเส้น')).toBeInTheDocument();
  expect(screen.queryByText(/ยังน้อยเกินสรุปนัยสำคัญ/)).not.toBeInTheDocument();
});
