import { downloadCsv } from './shared';
import { exportRankingCsv, exportCompareCsv, exportRecommendCsv } from './csv';

// mock low-level shared เพื่อจับ rows ที่ส่งเข้า downloadCsv (ไม่แตะ DOM/Blob จริง)
// jest hoist vi.mock ขึ้นเหนือ import อัตโนมัติ → downloadCsv ที่ import มาเป็น mock
vi.mock('./shared', () => ({
  ts: () => '20260101_0000',
  downloadCsv: vi.fn(),
}));

const lastCall = () => downloadCsv.mock.calls[downloadCsv.mock.calls.length - 1];
const flat = (rows) => rows.flat();

beforeEach(() => downloadCsv.mockClear());

describe('exportRankingCsv', () => {
  it('map ชื่อจังหวัด EN → TH + ใส่ rank stats + ตั้งชื่อไฟล์ตามปี', () => {
    exportRankingCsv({
      rankingYear: 2023,
      rankingStats: { total: 77, whoPass: 10, whoFail: 67 },
      rankingData: [
        { rank: 1, province: 'Bangkok Metropolis', m2_per_person_urban: 31.5,
          ndvi_mean_urban: 0.27, green_share_in_urban_pct: 18 },
      ],
    });
    const [rows, filename] = lastCall();
    const cells = flat(rows);
    expect(cells).toContain('Bangkok Metropolis');
    expect(cells).toContain('กรุงเทพมหานคร');     // PROVINCE_TH mapping
    expect(cells).toContain(67);                   // whoFail stat
    expect(filename).toBe('ranking_2023_20260101_0000.csv');
  });
});

describe('exportCompareCsv', () => {
  it('จังหวัดที่ไม่มีใน PROVINCE_TH ใช้ชื่อเดิมเป็น fallback', () => {
    exportCompareCsv({
      compareYear: 2023,
      compareMetric: 'ndvi_mean',
      compareData: [
        { province: 'Chiang Mai', ndvi_mean: 0.6, green_area_pct: 70, green_area_km2: 100 },
        { province: 'Atlantis', ndvi_mean: 0.1, green_area_pct: 5, green_area_km2: 1 },
      ],
    });
    const cells = flat(lastCall()[0]);
    expect(cells).toContain('เชียงใหม่');          // mapped
    expect(cells.filter((c) => c === 'Atlantis').length).toBeGreaterThanOrEqual(2); // EN + fallback TH
  });
});

describe('exportRecommendCsv', () => {
  it('ไม่ทำอะไรถ้าไม่มี recommendData', () => {
    exportRecommendCsv({ recommendData: null });
    expect(downloadCsv).not.toHaveBeenCalled();
  });

  it('ใส่ top_locations + พันธุ์ไม้ลง CSV', () => {
    exportRecommendCsv({
      selectedProvinceEN: 'Tak',
      recommendData: {
        weights: { ndvi: 0.4, lst: 0.3, population: 0.3 },
        top_locations: [{ lat: 16.5, lng: 99.1, score: 0.8 }],
        recommended_species: {
          region: 'ตะวันตก',
          species: [{ name_th: 'ประดู่ป่า', scientific: 'Pterocarpus macrocarpus',
                      height_m: '15–25', purpose: 'ฟื้นฟูป่า', traits: ['ทนแล้ง'], reason: 'x' }],
        },
      },
    });
    const cells = flat(lastCall()[0]);
    expect(cells).toContain('ประดู่ป่า');
    expect(cells).toContain(16.5);                  // top location lat
    expect(lastCall()[1]).toBe('recommend_Tak_20260101_0000.csv');
  });
});
