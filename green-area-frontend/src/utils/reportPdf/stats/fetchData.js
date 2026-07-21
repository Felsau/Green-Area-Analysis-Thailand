// ดึงรูป (mini-map + NDVI/LST thumb) + context + district summary + timeseries + urban subset แบบขนาน.
import { API_BASE } from '../../../constants';
import { fetchImageDataUrl } from '../helpers';
import { apiFetch } from '../../apiClient';

export const fetchStatsData = async ({ selectedProvinceEN, selectedDistrict, districtEN, year }) => {
  // ดึง district summary เฉพาะตอนรายงานระดับจังหวัด (ไม่ได้ลึกถึงอำเภอแล้ว)
  const districtSummaryUrl = !selectedDistrict
    ? `${API_BASE}/analysis/districts/${encodeURIComponent(selectedProvinceEN)}?year=${year}`
    : null;

  // Time-series window: 4 ปีย้อนหลังจากปีรายงาน → รวมทั้งหมด 5 ปี
  const tsStart = Number(year) - 4;
  const tsEnd = Number(year);
  const tsUrl = `${API_BASE}/analysis/timeseries/${encodeURIComponent(selectedProvinceEN)}?start_year=${tsStart}&end_year=${tsEnd}${districtEN ? `&district_name=${encodeURIComponent(districtEN)}` : ''}`;

  // Urban subset (Phase B-3) — ESA WorldCover Built-up clip; first call อาจช้า (GEE compute)
  const urbanUrl = `${API_BASE}/analysis/urban-subset/${encodeURIComponent(selectedProvinceEN)}?year=${year}${districtEN ? `&district_name=${encodeURIComponent(districtEN)}` : ''}`;

  const [miniMap, ndviThumb, lstThumb, contextResp, districtSummary, timeseriesResp, urbanResp] = await Promise.all([
    fetchImageDataUrl(`${API_BASE}/maps/thailand-thumb?province=${encodeURIComponent(selectedProvinceEN)}`),
    fetchImageDataUrl(`${API_BASE}/maps/${encodeURIComponent(selectedProvinceEN)}/ndvi-thumb?year=${year}${districtEN ? `&district_name=${encodeURIComponent(districtEN)}` : ''}`),
    fetchImageDataUrl(`${API_BASE}/maps/${encodeURIComponent(selectedProvinceEN)}/lst-thumb?year=${year}${districtEN ? `&district_name=${encodeURIComponent(districtEN)}` : ''}`),
    apiFetch(`${API_BASE}/analysis/context/${encodeURIComponent(selectedProvinceEN)}?year=${year}`).then(r => r.ok ? r.json() : null).catch(() => null),
    districtSummaryUrl
      ? apiFetch(districtSummaryUrl).then(r => r.ok ? r.json() : null).catch(() => null)
      : Promise.resolve(null),
    apiFetch(tsUrl).then(r => r.ok ? r.json() : null).catch(() => null),
    apiFetch(urbanUrl).then(r => r.ok ? r.json() : null).catch(() => null),
  ]);

  return { miniMap, ndviThumb, lstThumb, contextResp, districtSummary, timeseriesResp, urbanResp };
};
