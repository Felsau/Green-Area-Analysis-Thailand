// NDVI section (map + indicator table + WHO caveat) + NDVI monthly chart.
import { fmt, fmtInt } from '../helpers';
import { COLOR, sectionTitle, table, calloutBox, note, imageBox } from '../components';
import { monthlyBarChart } from '../charts';
import { dataQualityRows, dataQualityCallout, dataQualityMethodNote } from './dataQuality';
import { canopyRows, canopyCallout, canopyMethodNote } from './canopy';
import { validationRows, validationCallout, validationMethodNote } from './validation';

export const ndviSections = (ctx) => {
  const {
    ndviStats, ndviMonthly, ndviThumb, year,
    selectedProvince, selectedDistrict, districtPretty,
  } = ctx;
  if (!ndviStats) return [];

  const out = [];

  // wrap heading + figure ใน .no-split → กัน heading หลุดอยู่ท้ายหน้าโดยรูปไปอีกหน้า
  let ndviHtml = '';
  const ndviTitle = sectionTitle(`NDVI · ดัชนีพืชพรรณ · ปี ${year}`);
  const ndviFig = ndviThumb
    ? imageBox(ndviThumb,
        `แผนที่ NDVI · ${selectedDistrict ? `อำเภอ ${districtPretty}, ${selectedProvince}` : `จังหวัด${selectedProvince}`} · Sentinel-2 median composite ปี ${year}<br/>` +
        `<span style="font-family:monospace;">Palette: NDVI -0.2 (แดง = ไม่มีพืช) → 0.8 (เขียวเข้ม = ป่าหนา)</span>`,
        { heightHint: '320px' })
    : '';
  ndviHtml += `<div class="no-split" style="page-break-inside:avoid;break-inside:avoid;">${ndviTitle}${ndviFig}</div>`;

  const ndviRows = [
    ['NDVI Mean', fmt(ndviStats.ndvi_mean, 3),
      ndviStats.ndvi_mean >= 0.5 ? 'พืชพรรณหนาแน่น (ป่า/เกษตรเข้มข้น)'
        : ndviStats.ndvi_mean >= 0.3 ? 'พืชพรรณปานกลาง (เกษตร/ทุ่งหญ้า)'
        : 'พืชพรรณน้อย (เมือง/พื้นที่เปิดโล่ง)'],
    ['NDVI Min (หลัง mask น้ำ)', fmt(ndviStats.ndvi_min, 3),
      ndviStats.ndvi_min >= 0.05 ? 'พืชพรรณบาง'
        : ndviStats.ndvi_min >= 0 ? 'พื้นดินเปิดโล่ง/อาคาร'
        : 'อาจมีน้ำ/เมฆเงาที่ mask ไม่ครบ'],
    ['NDVI Max', fmt(ndviStats.ndvi_max, 3), 'จุดเรือนยอดป่าหนาแน่นที่สุด'],
    ['พื้นที่สีเขียว (NDVI > 0.3)', `${fmt(ndviStats.green_area_pct, 1)}% (${fmtInt(ndviStats.green_area_km2)} km²)`,
      'รวมป่า + เกษตร + ทุ่งหญ้า'],
  ];
  // เพิ่มแถว dense forest เฉพาะเมื่อมีข้อมูล (หลัง re-compute) — ไม่งั้นซ่อนเพื่อไม่ให้มี TODO ใน PDF
  if (ndviStats.dense_area_pct != null) {
    ndviRows.push([
      'พื้นที่ป่าหนา (NDVI > 0.5)',
      `${fmt(ndviStats.dense_area_pct, 1)}% (${fmtInt(ndviStats.dense_area_km2)} km²)`,
      'ป่าเรือนยอดปิด',
    ]);
  }
  ndviRows.push(['ประชากร', fmtInt(ndviStats.population), 'จาก WorldPop 100m']);
  ndviRows.push(['พื้นที่สีเขียว/คน', `${fmt(ndviStats.green_area_m2_per_person, 2)} m²`,
    'เทียบเกณฑ์ WHO ≥ 9 (ดูข้อจำกัด)']);
  ndviRows.push(['สถานะตามเกณฑ์ตัวเลข', ndviStats.who_status || '—', '']);

  ndviHtml += table(
    ['ตัวชี้วัด', 'ค่า', 'การตีความ'],
    ndviRows,
    { firstColWidth: 180 }
  );

  // เรือนยอดเทียบเกณฑ์ 30% (FR-17) — แยกตารางเพราะเป็นคนละนิยามของพื้นที่สีเขียว
  // จาก NDVI ข้างบน (ดู canopy.js) และมาจากคนละชุดข้อมูล/คนละปี
  const canopy = ndviStats.canopy;
  const cRows = canopyRows(canopy);
  if (cRows.length) {
    ndviHtml += table(
      ['เรือนยอดไม้ (3-30-300)', 'ค่า', 'หมายเหตุ'],
      cRows,
      { firstColWidth: 180, keepTogether: true }
    );
    ndviHtml += canopyCallout(canopy, { areaKm2: ndviStats.total_area_km2 });
    ndviHtml += canopyMethodNote(canopy);
  }

  // คุณภาพ/ความไม่แน่นอนของ composite (NFR-07) — แยกตารางเพื่อไม่ปนกับค่าที่วัดได้
  const qualityRows = dataQualityRows(ndviStats.data_quality);
  if (qualityRows.length) {
    ndviHtml += table(
      ['คุณภาพข้อมูล NDVI', 'ค่า', 'หมายเหตุ'],
      qualityRows,
      { firstColWidth: 180, keepTogether: true }
    );
    ndviHtml += dataQualityCallout(ndviStats.data_quality);
    ndviHtml += dataQualityMethodNote();
  }

  // ความถูกต้องเทียบ ESA WorldCover (NFR-08) — ต่อจากคุณภาพข้อมูลเพราะเป็นข้อมูล
  // ชนิดเดียวกัน (ความเชื่อมั่นของค่าที่รายงาน) แค่คนละแหล่งอ้างอิง · ระดับจังหวัด
  const vRows = validationRows(ndviStats.validation);
  if (vRows.length) {
    ndviHtml += table(
      ['ความถูกต้องเทียบ WorldCover', 'ค่า', 'หมายเหตุ'],
      vRows,
      { firstColWidth: 180, keepTogether: true }
    );
    ndviHtml += validationCallout(ndviStats.validation);
    ndviHtml += validationMethodNote(ndviStats.validation);
  }

  // Note about WHO standard caveat — central interpretive issue
  ndviHtml += calloutBox(
    `<b>ข้อควรระวัง:</b> เกณฑ์ WHO 9 m²/คน อ้างอิงถึง <b>"พื้นที่สีเขียวที่ประชาชนเข้าถึงได้"</b> (สวนสาธารณะ สวนเมือง) ไม่ใช่พื้นที่ที่ NDVI &gt; 0.3 ทั้งหมด · รายงานนี้ใช้ NDVI &gt; 0.3 ซึ่งรวมป่าและพื้นที่เกษตรในชนบท จึงอาจประเมินสูงเกินจริงสำหรับพื้นที่ที่ประชาชนใช้พักผ่อนได้`,
    COLOR.orange
  );

  if (ndviStats.ndvi_min != null && ndviStats.ndvi_min < -0.05) {
    ndviHtml += note(
      `⚠ NDVI Min ที่ต่ำผิดปกติบ่งชี้ว่ายังมี pixel น้ำ/cloud-shadow หลงเหลือ — ลอง clear cache แล้วโหลดใหม่`
    );
  }

  out.push({ label: 'NDVI', html: ndviHtml });

  if (ndviMonthly?.length) {
    out.push({
      label: 'NDVI · Monthly',
      html: monthlyBarChart({
        title: 'NDVI รายเดือน',
        subtitle: 'ค่า median NDVI ของ pixel ทั้งหมดในแต่ละเดือน',
        year, unit: 'NDVI (0–1)',
        data: ndviMonthly, valueKey: 'ndvi',
        color: COLOR.green, yMax: 1, yMin: 0,
        valueFmt: (v) => v != null ? v.toFixed(2) : '',
      }),
    });
  }

  return out;
};
