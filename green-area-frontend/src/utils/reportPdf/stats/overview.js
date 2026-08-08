// Cover + Overview sections.
import { COLOR, cover, sectionTitle, paragraph, table } from '../components';

export const overviewSections = (ctx) => {
  const {
    subtitle, year, miniMap,
    selectedProvince, selectedProvinceEN, selectedDistrict, districtPretty,
    provinceArea, districtArea,
  } = ctx;

  const coverSection = {
    label: 'Cover',
    html: cover({
      kicker: 'GREEN AREA REPORT',
      heading: subtitle,
      subheading: 'รายงานพื้นที่สีเขียว · NDVI · LST · WHO',
      accent: COLOR.green,
      year,
      miniMapDataUrl: miniMap,
    }),
  };

  let overviewHtml = sectionTitle('ภาพรวม (Overview)');
  overviewHtml += paragraph(
    'รายงานนี้สรุปข้อมูลพื้นที่สีเขียวจากดัชนี <b>NDVI</b> (Sentinel-2) และอุณหภูมิผิวพื้น <b>LST</b> (Landsat 8/9) พร้อมเทียบกับ<b>ค่าอ้างอิง</b> WHO 9 m²/คน (ดูข้อจำกัดของการเทียบในส่วนท้ายรายงาน)'
  );
  const overviewRows = [
    ['จังหวัด', selectedProvince || '—'],
    ['ชื่อทางการ (EN)', selectedProvinceEN || '—'],
  ];
  if (selectedDistrict) overviewRows.push(['อำเภอ', districtPretty]);
  overviewRows.push(['ปีที่วิเคราะห์', String(year)]);
  if (provinceArea) overviewRows.push(['พื้นที่จังหวัด', `${Number(provinceArea).toLocaleString()} km²`]);
  if (districtArea) overviewRows.push(['พื้นที่อำเภอ', `${Number(districtArea).toLocaleString()} km²`]);
  overviewHtml += table(['รายการ', 'ค่า'], overviewRows, { firstColWidth: 200 });

  return [coverSection, { label: 'Overview', html: overviewHtml }];
};
