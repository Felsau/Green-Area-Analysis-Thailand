import { expect, test } from 'vitest';
import { render, screen } from '@testing-library/react';
import RecommendTab from './RecommendTab';
import { DEFAULT_WEIGHTS } from '../../hooks/useRecommendData';

const handlers = {
  onFetchRecommend: () => {}, onToggleRecommend: () => {}, onClearRecommend: () => {},
  setRecommendYear: () => {}, setRecommendWeights: () => {},
};
const W = { ndvi: 0.4, lst: 0.3, population: 0.3 };
const pt = (extra) => ({ lat: 13.7, lng: 100.5, score: 0.8, ...extra });
const renderTab = (recommendData) => render(
  <RecommendTab
    data={{
      selectedProvince: 'กรุงเทพมหานคร', selectedProvinceEN: 'Bangkok Metropolis',
      recommendData: { weights: W, ...recommendData }, recommendLoading: false, recommendVisible: true,
      recommendYear: 2026, recommendWeights: DEFAULT_WEIGHTS,
    }}
    handlers={handlers}
  />,
);

test('shows LDD name with edition year and the filter note', () => {
  renderTab({
    ldd_filter: { source: 'ldd', edition_year: 2566 },
    top_locations: [pt({ ldd: { code: 'A405', name_th: 'ไม้ยืนต้น', rule: 'neutral', edition_year: 2566 } })],
  });
  expect(screen.getByText(/การใช้ที่ดิน \(กรมพัฒนาที่ดิน ปี 2566\): ไม้ยืนต้น/)).toBeInTheDocument();
  expect(screen.getByText(/ตรวจจุดกับข้อมูลการใช้ที่ดินของกรมพัฒนาที่ดิน ปี 2566/)).toBeInTheDocument();
});

test('falls back to the LDD code when name is null', () => {
  renderTab({ top_locations: [pt({ ldd: { code: 'A405/A411', name_th: null, rule: 'neutral', edition_year: 2566 } })] });
  expect(screen.getByText(/ปี 2566\): A405\/A411/)).toBeInTheDocument();
});

test('adds the prefer tag', () => {
  renderTab({ top_locations: [pt({ ldd: { code: 'M1', name_th: 'ที่ว่าง', rule: 'prefer', edition_year: 2566 } })] });
  expect(screen.getByText(/ที่ว่าง\/ที่ร้าง เหมาะปลูก/)).toBeInTheDocument();
});

test('keeps the satellite rendering when ldd is absent', () => {
  renderTab({ top_locations: [pt({ landuse: { code: 'F', name_th: 'ป่าไม้' } })] });
  expect(screen.getByText(/การใช้ที่ดิน: ป่าไม้/)).toBeInTheDocument();
  expect(screen.queryByText(/กรมพัฒนาที่ดิน/)).not.toBeInTheDocument();
});
