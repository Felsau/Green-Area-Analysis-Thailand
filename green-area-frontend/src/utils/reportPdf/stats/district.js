// District detail section (NDVI/LST tables + monthly charts) — เฉพาะตอนเลือกอำเภอ.
import { fmt, fmtInt } from '../helpers';
import { COLOR, sectionTitle, table } from '../components';
import { monthlyBarChart } from '../charts';
import { dataQualityRows, dataQualityCallout } from './dataQuality';

export const districtSections = (ctx) => {
  const {
    selectedDistrict, districtPretty, year,
    districtNdviStats, districtNdviMonthly, districtLstStats, districtLstMonthly,
  } = ctx;
  if (!(selectedDistrict && (districtNdviStats || districtLstStats))) return [];

  let dHtml = sectionTitle(`อำเภอ ${districtPretty} · รายละเอียด`, { color: COLOR.primary });
  if (districtNdviStats) {
    dHtml += table(
      ['NDVI · อำเภอ', 'ค่า'],
      [
        ['NDVI Mean', fmt(districtNdviStats.ndvi_mean, 3)],
        ['NDVI Min (mask น้ำ)', fmt(districtNdviStats.ndvi_min, 3)],
        ['NDVI Max', fmt(districtNdviStats.ndvi_max, 3)],
        ['พื้นที่สีเขียว (>0.3)', `${fmt(districtNdviStats.green_area_pct, 1)}%`],
        ['พื้นที่สีเขียว (km²)', fmtInt(districtNdviStats.green_area_km2)],
      ],
      { firstColWidth: 200 }
    );
    // ความไม่แน่นอนของ composite ระดับอำเภอ (NFR-07) — ตัดคอลัมน์ "หมายเหตุ" ออก
    // ให้เข้ากับตาราง 2 คอลัมน์ของ section นี้ · คำอธิบายเต็มอยู่ใน callout ด้านล่าง
    const qualityRows = dataQualityRows(districtNdviStats.data_quality);
    if (qualityRows.length) {
      dHtml += table(
        ['คุณภาพข้อมูล NDVI · อำเภอ', 'ค่า'],
        qualityRows.map(([k, v]) => [k, v]),
        { firstColWidth: 200, keepTogether: true }
      );
      dHtml += dataQualityCallout(districtNdviStats.data_quality);
    }
  }
  if (districtLstStats) {
    dHtml += table(
      ['LST · อำเภอ', 'ค่า'],
      [
        ['LST Mean', `${fmt(districtLstStats.lst_mean, 1)} °C`],
        ['LST Min', `${fmt(districtLstStats.lst_min, 1)} °C`],
        ['LST Max', `${fmt(districtLstStats.lst_max, 1)} °C`],
      ],
      { firstColWidth: 200 }
    );
  }

  if (districtNdviMonthly?.length) {
    dHtml += monthlyBarChart({
      title: `NDVI รายเดือน · อำเภอ ${districtPretty}`,
      year, unit: 'NDVI',
      data: districtNdviMonthly, valueKey: 'ndvi',
      color: COLOR.green, yMax: 1, yMin: 0,
      valueFmt: (v) => v != null ? v.toFixed(2) : '',
    });
  }
  if (districtLstMonthly?.length) {
    dHtml += monthlyBarChart({
      title: `LST รายเดือน · อำเภอ ${districtPretty}`,
      year, unit: '°C',
      data: districtLstMonthly, valueKey: 'lst',
      color: COLOR.orange,
      valueFmt: (v) => v != null ? v.toFixed(1) : '',
    });
  }

  return [{ label: 'District', html: dHtml }];
};
