import { buildRecommendReport } from './recommend';
import { renderSegmentsToPdf } from './layout';

// The section labels become the per-page PDF header, drawn by jsPDF's default
// font, which can only encode Latin-1 — Thai turns into garbage ("Top 8%9").
vi.mock('./layout', () => ({ renderSegmentsToPdf: vi.fn() }));

const baseData = {
  selectedProvince: 'กรุงเทพมหานคร',
  selectedProvinceEN: 'Bangkok Metropolis',
  selectedDistrict: '',
  recommendData: {
    weights: { ndvi: 0.4, lst: 0.3, population: 0.3 },
    top_locations: [
      { lat: 13.75, lng: 100.5, score: 0.8 },
      { lat: 13.76, lng: 100.51, score: 0.6 },
    ],
  },
};

describe('buildRecommendReport — PDF page header labels', () => {
  beforeEach(() => renderSegmentsToPdf.mockClear());

  test('the top-locations page header reads "Top Locations"', async () => {
    await buildRecommendReport(baseData);
    const sections = renderSegmentsToPdf.mock.calls[0][0];
    const top = sections.find((s) => s.html.includes('จุดที่ควรปลูกต้นไม้'));
    expect(top.label).toBe('Top Locations');
  });

  test('every section label is printable ASCII (safe for the jsPDF header font)', async () => {
    await buildRecommendReport(baseData);
    const sections = renderSegmentsToPdf.mock.calls[0][0];
    for (const s of sections) expect(s.label).toMatch(/^[\x20-\x7E]+$/);
  });
});
