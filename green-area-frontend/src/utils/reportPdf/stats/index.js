// buildStatsReport — flagship report orchestrator.
// ดึงข้อมูล → ประกอบ section (Cover / Overview / NDVI / LST / Urban / Access300 /
// District / Comparison / Districts / Time-series / Methodology / Conclusions /
// Limitations / References) → render PDF.
import { ts, formatEnName } from '../helpers';
import { renderSegmentsToPdf } from '../layout';
import { fetchStatsData } from './fetchData';
import { overviewSections } from './overview';
import { ndviSections } from './ndvi';
import { lstSections } from './lst';
import { urbanSections } from './urban';
import { access300Sections } from './access300';
import { districtSections } from './district';
import { comparisonSections } from './comparison';
import { districtSummarySections } from './districtSummary';
import { timeseriesSections } from './timeseries';
import { closingSections } from './conclusions';

export const buildStatsReport = async (data) => {
  const {
    selectedProvince, selectedProvinceEN, selectedDistrict,
    provinceArea, districtArea,
    ndviStats, ndviMonthly,
    lstStats, lstMonthly,
    districtNdviStats, districtNdviMonthly,
    districtLstStats, districtLstMonthly,
  } = data;
  // selectedDistrict may now be Thai (for display); selectedDistrictEN stays English (for API)
  const districtEN = data.selectedDistrictEN || selectedDistrict;

  const year = ndviStats?.year || lstStats?.year || data.year || new Date().getFullYear();
  const districtPretty = formatEnName(districtEN);
  // Cover heading: Thai for province + " — " + EN district to make script change explicit (no run-on like "MaeChaem")
  const subtitle = selectedDistrict
    ? `${selectedProvince} — ${districtPretty}`
    : selectedProvince;
  const docTitle = `Green Area Report — ${selectedProvinceEN}${selectedDistrict ? ` / ${districtPretty}` : ''}`;

  const fetched = await fetchStatsData({ selectedProvinceEN, selectedDistrict, districtEN, year });

  // Shared context ที่ section builder ทุกตัวรับเข้าไปใช้
  const ctx = {
    selectedProvince, selectedProvinceEN, selectedDistrict, districtEN, districtPretty,
    subtitle, year, provinceArea, districtArea,
    ndviStats, ndviMonthly, lstStats, lstMonthly,
    districtNdviStats, districtNdviMonthly, districtLstStats, districtLstMonthly,
    ...fetched,
  };

  const sections = [
    ...overviewSections(ctx),
    ...ndviSections(ctx),
    ...lstSections(ctx),
    ...urbanSections(ctx),
    ...access300Sections(ctx),
    ...districtSections(ctx),
    ...comparisonSections(ctx),
    ...districtSummarySections(ctx),
    ...timeseriesSections(ctx),
    ...closingSections(ctx),
  ];

  await renderSegmentsToPdf(
    sections,
    `stats_report_${(districtEN || selectedProvinceEN || 'province').replace(/\s+/g, '_')}_${ts()}.pdf`,
    { docTitle }
  );
};
