import { render, screen } from '@testing-library/react';
import ImpactSection from './ImpactSection';

// impact object เหมือนที่ backend estimate_impact คืน (รวม ecosystem_services)
const IMPACT = {
  trees_total: 40000,
  plantable_area_km2: 1,
  plantable_area_ha: 100,
  annual_co2_tonnes: 1120,
  annual_co2_tonnes_low: 600,
  annual_co2_tonnes_high: 1400,
  equivalent_cars_off_road: 195,
  expected_delta_lst_c: -1.5,
  maturity_years: 10,
  ecosystem_services: {
    air_pollution_removal_kg: { pm25: 800, o3: 2000, no2: 720, total: 3520 },
    stormwater_runoff_m3: 100000,
    annual_value_thb: { co2: 1680000, air_pollution: 3449600, stormwater: 2000000, total: 7129600 },
    annual_value_thb_expected: 5703680,
  },
  methodology: { sources: ['US Forest Service i-Tree Eco', 'Nowak D.J. et al. 2014'] },
};

test('renders nothing when there are no trees', () => {
  const { container } = render(<ImpactSection impact={{ trees_total: 0 }} />);
  expect(container).toBeEmptyDOMElement();
});

test('shows the i-Tree ecosystem-service value block', () => {
  render(<ImpactSection impact={IMPACT} />);
  expect(screen.getByText(/มูลค่าบริการระบบนิเวศรวม\/ปี/)).toBeInTheDocument();
  // ฿7,129,600 → ย่อเป็น "7.1 ล้านบาท"
  expect(screen.getByText(/7\.1 ล้านบาท/)).toBeInTheDocument();
  expect(screen.getByText(/ดูดซับมลพิษอากาศ/)).toBeInTheDocument();
  expect(screen.getByText(/ดักน้ำฝน/)).toBeInTheDocument();
});

test('degrades gracefully for cached impact without ecosystem_services', () => {
  const legacy = { ...IMPACT, ecosystem_services: undefined };
  render(<ImpactSection impact={legacy} />);
  // ยังโชว์ CO₂ เดิมได้ แต่ไม่มีบล็อกบริการนิเวศ
  expect(screen.getByText(/CO₂ ดูดซับ\/ปี/)).toBeInTheDocument();
  expect(screen.queryByText(/มูลค่าบริการระบบนิเวศรวม/)).not.toBeInTheDocument();
});

test('shows plantable-area land use breakdown, skipping zero-share classes', () => {
  const withLanduse = {
    ...IMPACT,
    plantable_landuse: {
      total_km2: 1,
      classes: [
        { code: 'A', name_th: 'พื้นที่เกษตรกรรม', color: 'f2c94c', area_km2: 0.62, share_pct: 62 },
        { code: 'M', name_th: 'พื้นที่เบ็ดเตล็ด', color: '9aa0a6', area_km2: 0.38, share_pct: 38 },
        { code: 'W', name_th: 'พื้นที่น้ำ', color: '3d85c6', area_km2: 0, share_pct: 0 },
      ],
    },
  };
  render(<ImpactSection impact={withLanduse} />);
  expect(screen.getByText(/พื้นที่ควรปลูก แยกตามการใช้ที่ดิน/)).toBeInTheDocument();
  expect(screen.getByText(/พื้นที่เกษตรกรรม 62%/)).toBeInTheDocument();
  // ประเภทที่พื้นที่เป็น 0 ต้องไม่ปรากฏ
  expect(screen.queryByText(/พื้นที่น้ำ/)).not.toBeInTheDocument();
});

test('impact without plantable_landuse (cache before v8) renders no breakdown', () => {
  render(<ImpactSection impact={IMPACT} />);
  expect(screen.queryByText(/แยกตามการใช้ที่ดิน/)).not.toBeInTheDocument();
});
