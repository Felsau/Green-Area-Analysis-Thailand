// CSV exports สำหรับแต่ละแท็บ (stats / trend / compare / ranking / recommend).
import { PROVINCE_TH } from '../../constants';
import { ts, downloadCsv } from './shared';

// คุณภาพ composite ที่ backend ส่งมากับค่า NDVI (NFR-07) — แนบท้ายบล็อก NDVI ทุกครั้ง
// เพื่อให้ไฟล์ที่เอาไปวิเคราะห์ต่อมีความไม่แน่นอนติดไปด้วย ไม่ใช่แค่ค่ากลาง
const dataQualityRows = (dq) => {
  if (!dq) return [];
  return [
    ['ภาพที่ใช้ทำ composite', dq.image_count],
    ['เกณฑ์เมฆของภาพ (%)', dq.cloud_filter_pct],
    ['ภาพปลอดเมฆต่อ pixel (เฉลี่ย)', dq.clear_obs_mean],
    ['ภาพปลอดเมฆต่อ pixel (ต่ำสุด)', dq.clear_obs_min],
    ['NDVI σ ในปี', dq.ndvi_sd_mean],
    ['ความไม่แน่นอน u (1σ, NDVI)', dq.uncertainty],
    ['ความไม่แน่นอน 2σ (% ของค่า)', dq.uncertainty_2sigma_pct],
    ['เดือนที่มีภาพ', `${dq.months_covered}/12`],
    ['ฤดูที่ไม่มีภาพ (นิยาม TMD)', (dq.seasons_missing || []).join(' / ') || 'ครบทั้ง 3 ฤดู'],
    ['ช่วงวันที่ของภาพ', dq.first_date && dq.last_date ? `${dq.first_date} – ${dq.last_date}` : ''],
    ['ระดับเทียบเกณฑ์ GCOS-245', dq.label || dq.level || ''],
  ];
};

export const exportStatsCsv = (data) => {
  const {
    selectedProvince, selectedProvinceEN, selectedDistrict,
    provinceArea, districtArea,
    ndviStats, ndviMonthly, lstStats, lstMonthly,
    districtNdviStats, districtNdviMonthly, districtLstStats, districtLstMonthly,
  } = data;

  const rows = [];
  rows.push(['รายงานข้อมูลพื้นที่สีเขียว']);
  rows.push(['จังหวัด', selectedProvince || '-', selectedProvinceEN || '']);
  if (selectedDistrict) rows.push(['อำเภอ', selectedDistrict]);
  rows.push(['พื้นที่จังหวัด (km²)', provinceArea ?? '']);
  if (districtArea) rows.push(['พื้นที่อำเภอ (km²)', districtArea]);
  rows.push([]);

  if (ndviStats) {
    rows.push(['— NDVI จังหวัด —']);
    rows.push(['NDVI Mean', ndviStats.ndvi_mean]);
    rows.push(['NDVI Min', ndviStats.ndvi_min]);
    rows.push(['NDVI Max', ndviStats.ndvi_max]);
    rows.push(['Green Area (%)', ndviStats.green_area_pct]);
    rows.push(['Green Area (km²)', ndviStats.green_area_km2]);
    if (ndviStats.green_area_m2_per_person != null)
      rows.push(['Green Area m²/คน', ndviStats.green_area_m2_per_person]);
    if (ndviStats.population) rows.push(['ประชากร', ndviStats.population]);
    if (ndviStats.who_status) rows.push(['สถานะ WHO', ndviStats.who_status]);
    dataQualityRows(ndviStats.data_quality).forEach(r => rows.push(r));
    rows.push([]);
  }

  if (lstStats) {
    rows.push(['— LST จังหวัด (°C) —']);
    rows.push(['LST Mean', lstStats.lst_mean]);
    rows.push(['LST Min', lstStats.lst_min]);
    rows.push(['LST Max', lstStats.lst_max]);
    rows.push([]);
  }

  if (ndviMonthly?.length) {
    rows.push(['— NDVI รายเดือน (จังหวัด) —']);
    rows.push(['เดือน', 'NDVI']);
    ndviMonthly.forEach(m => rows.push([m.month, m.ndvi]));
    rows.push([]);
  }

  if (lstMonthly?.length) {
    rows.push(['— LST รายเดือน (จังหวัด, °C) —']);
    rows.push(['เดือน', 'LST']);
    lstMonthly.forEach(m => rows.push([m.month, m.lst]));
    rows.push([]);
  }

  if (districtNdviStats) {
    rows.push(['— NDVI อำเภอ —']);
    rows.push(['NDVI Mean', districtNdviStats.ndvi_mean]);
    rows.push(['NDVI Min', districtNdviStats.ndvi_min]);
    rows.push(['NDVI Max', districtNdviStats.ndvi_max]);
    rows.push(['Green Area (%)', districtNdviStats.green_area_pct]);
    rows.push(['Green Area (km²)', districtNdviStats.green_area_km2]);
    dataQualityRows(districtNdviStats.data_quality).forEach(r => rows.push(r));
    rows.push([]);
  }

  if (districtLstStats) {
    rows.push(['— LST อำเภอ (°C) —']);
    rows.push(['LST Mean', districtLstStats.lst_mean]);
    rows.push(['LST Min', districtLstStats.lst_min]);
    rows.push(['LST Max', districtLstStats.lst_max]);
    rows.push([]);
  }

  if (districtNdviMonthly?.length) {
    rows.push(['— NDVI รายเดือน (อำเภอ) —']);
    rows.push(['เดือน', 'NDVI']);
    districtNdviMonthly.forEach(m => rows.push([m.month, m.ndvi]));
    rows.push([]);
  }

  if (districtLstMonthly?.length) {
    rows.push(['— LST รายเดือน (อำเภอ, °C) —']);
    rows.push(['เดือน', 'LST']);
    districtLstMonthly.forEach(m => rows.push([m.month, m.lst]));
  }

  const slug = (data.selectedDistrictEN || selectedProvinceEN || 'thailand').replace(/\s+/g, '_');
  downloadCsv(rows, `stats_${slug}_${ts()}.csv`);
};

export const exportTrendCsv = (data) => {
  const { selectedProvince, selectedProvinceEN, trendData, trendMetric } = data;
  const rows = [['แนวโน้มรายปี', selectedProvince || '']];
  rows.push(['Metric', trendMetric]);
  rows.push([]);
  rows.push(['ปี', 'NDVI Mean', 'พื้นที่สีเขียว %']);
  trendData.forEach(d => rows.push([d.year, d.ndvi_mean ?? '', d.green_area_pct ?? '']));
  downloadCsv(rows, `trend_${selectedProvinceEN || 'province'}_${ts()}.csv`);
};

export const exportCompareCsv = (data) => {
  const { compareData, compareYear, compareMetric } = data;
  const rows = [['เปรียบเทียบจังหวัด', `ปี ${compareYear}`]];
  rows.push(['Metric', compareMetric]);
  rows.push([]);
  rows.push(['จังหวัด (EN)', 'จังหวัด (TH)', 'NDVI Mean', 'พื้นที่สีเขียว %', 'Green Area km²']);
  compareData.forEach(d => rows.push([
    d.province,
    PROVINCE_TH[d.province] || d.province,
    d.ndvi_mean ?? '',
    d.green_area_pct ?? '',
    d.green_area_km2 ?? '',
  ]));
  downloadCsv(rows, `compare_${compareYear}_${ts()}.csv`);
};

export const exportRankingCsv = (data) => {
  const { rankingData, rankingYear, rankingStats } = data;
  const rows = [['อันดับจังหวัด', `ปี ${rankingYear}`]];
  if (rankingStats) {
    rows.push(['ทั้งหมด', rankingStats.total]);
    rows.push(['ผ่าน WHO', rankingStats.whoPass]);
    rows.push(['ต่ำกว่า WHO', rankingStats.whoFail]);
  }
  rows.push([]);
  rows.push(['อันดับ', 'จังหวัด (EN)', 'จังหวัด (TH)', 'm²/คน', 'NDVI Mean', 'Green Area %']);
  rankingData.forEach(r => rows.push([
    r.rank,
    r.province,
    PROVINCE_TH[r.province] || r.province,
    r.green_area_m2_per_person ?? '',
    r.ndvi_mean ?? '',
    r.green_area_pct ?? '',
  ]));
  downloadCsv(rows, `ranking_${rankingYear}_${ts()}.csv`);
};

export const exportRecommendCsv = (data) => {
  const { recommendData, selectedProvinceEN, selectedDistrict } = data;
  if (!recommendData) return;
  const rows = [['AI Planting Recommendation', selectedProvinceEN, selectedDistrict || '']];
  rows.push(['น้ำหนัก NDVI', recommendData.weights?.ndvi]);
  rows.push(['น้ำหนัก LST', recommendData.weights?.lst]);
  rows.push(['น้ำหนัก ประชากร', recommendData.weights?.population]);
  if (recommendData.weights?.access != null)
    rows.push(['น้ำหนัก เข้าถึงสีเขียว', recommendData.weights.access]);
  if (recommendData.worldpop_year)
    rows.push(['ปีข้อมูลประชากร (WorldPop)', recommendData.worldpop_year]);
  rows.push([]);

  rows.push(['Top Locations']);
  rows.push(['อันดับ', 'Latitude', 'Longitude', 'Score']);
  (recommendData.top_locations || []).forEach((p, i) =>
    rows.push([i + 1, p.lat, p.lng, p.score])
  );
  rows.push([]);

  const sp = recommendData.recommended_species;
  if (sp?.species?.length) {
    rows.push(['พันธุ์ไม้แนะนำ', `ภาค${sp.region || ''}`]);
    rows.push(['ชื่อไทย', 'Scientific', 'ความสูง (m)', 'จุดประสงค์', 'คุณสมบัติ', 'เหตุผล']);
    sp.species.forEach(s => rows.push([
      s.name_th, s.scientific, s.height_m, s.purpose,
      (s.traits || []).join(' / '),
      s.reason,
    ]));
  }

  const slug = (data.selectedDistrictEN || selectedProvinceEN || 'thailand').replace(/\s+/g, '_');
  downloadCsv(rows, `recommend_${slug}_${ts()}.csv`);
};
