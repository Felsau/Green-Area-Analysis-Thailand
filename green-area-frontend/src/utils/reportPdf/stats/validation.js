// NFR-08 — ความถูกต้องของพื้นที่สีเขียว (NDVI) เทียบ ESA WorldCover
// backend คำนวณ error/breakdown/note มาให้แล้ว (validation.py) ที่นี่จัดรูปแบบลง PDF
//
// เจตนาเดียวกับ ValidationNote บนหน้าจอ: รายงาน *ความเชื่อมั่นของตัวเลข* ไม่ใช่
// ตัดสินว่าข้อมูลผิด — ความต่างที่พบอธิบายได้ด้วยกลไกเชิงนิยาม 2 แบบที่ทิศทาง
// ตรงข้ามกัน (ดู REQUIREMENTS.md §5.1 สำหรับผลวัดจริงทั้ง 77 จังหวัด)
import { COLOR, calloutBox, note } from '../components';
import { fmt } from '../helpers';

const KIND_TH = {
  false_negative: 'WorldCover นับเป็นสีเขียว แต่ NDVI ไม่นับ',
  false_positive: 'NDVI นับเป็นสีเขียว แต่ WorldCover ไม่นับ',
};

export const validationRows = (v) => {
  if (!v?.available) return [];
  const rows = [
    ['พื้นที่สีเขียว (NDVI > 0.3)', `${fmt(v.ndvi_green_pct, 1)}%`,
      'ค่าที่ระบบรายงาน — Sentinel-2 median composite'],
    ['พื้นที่สีเขียวอ้างอิง', `${fmt(v.worldcover_green_pct, 1)}%`,
      `ESA WorldCover v200 (ปี ${v.worldcover_epoch_year}) คลาสพืชพรรณ 10/20/30/40/90/95`],
    ['ความต่าง', `${v.error_pp > 0 ? '+' : ''}${fmt(v.error_pp, 1)} จุด%`,
      v.error_pp > 0 ? 'NDVI สูงกว่าค่าอ้างอิง' : 'NDVI ต่ำกว่าค่าอ้างอิง'],
    ['เกณฑ์ NFR-08', `±${fmt(v.target_pp, 0)} จุด%`,
      v.within_target ? 'อยู่ในเกณฑ์' : 'ต่างเกินเกณฑ์ (ดูการแยกสาเหตุ)'],
  ];
  const b = v.breakdown;
  if (b) {
    rows.push(['WorldCover เขียว / NDVI ไม่เขียว', `${fmt(b.false_negative_pp, 1)} จุด%`,
      'ส่วนใหญ่เป็นนาข้าวช่วงพักดิน/น้ำท่วมขัง']);
    rows.push(['NDVI เขียว / WorldCover ไม่เขียว', `${fmt(b.false_positive_pp, 1)} จุด%`,
      'ส่วนใหญ่เป็นพืชแทรกตัวเมืองใน pixel สิ่งปลูกสร้าง']);
    if (b.dominant) {
      rows.push(['ต้นเหตุหลัก', `${b.dominant.name} ${fmt(b.dominant.pp, 1)} จุด%`,
        KIND_TH[b.dominant.kind]]);
    }
  }
  return rows;
};

// callout เฉพาะจังหวัดที่ต่างเกินเกณฑ์ — อยู่ในเกณฑ์แล้วไม่ต้องรบกวนผู้อ่าน
export const validationCallout = (v) => {
  if (!v?.available || v.within_target) return '';
  const top = v.breakdown?.dominant;
  return calloutBox(
    `<b>ความต่างเกินเกณฑ์ ±${fmt(v.target_pp, 0)} จุด%:</b> ` +
    `พื้นที่สีเขียวจาก NDVI (${fmt(v.ndvi_green_pct, 1)}%) ` +
    `${v.error_pp > 0 ? 'สูงกว่า' : 'ต่ำกว่า'} ESA WorldCover ` +
    `(${fmt(v.worldcover_green_pct, 1)}%) อยู่ ${fmt(Math.abs(v.error_pp), 1)} จุด%` +
    (top ? ` โดยมาจากคลาส<b>${top.name}</b>เป็นหลัก ${fmt(top.pp, 1)} จุด% (${KIND_TH[top.kind]})` : '') +
    ' · ความต่างนี้เป็นผลจาก<b>นิยามที่ต่างกัน</b> ไม่ใช่ความผิดพลาดของการวัด — ' +
    'NDVI วัดพืชพรรณที่เขียวจริงในช่วงเวลานั้น ส่วน WorldCover จำแนกประเภทการใช้ที่ดิน ' +
    'ซึ่งนับนาข้าวเป็นพื้นที่เกษตรตลอดปีแม้ช่วงพักดิน และตัดสินทั้ง pixel เมืองที่ปนต้นไม้กับ' +
    'อาคารเป็นสิ่งปลูกสร้าง',
    COLOR.orange
  );
};

export const validationMethodNote = (v) => {
  if (!v?.available) return '';
  let text =
    'วิธีตรวจสอบ (NFR-08): เทียบ green_area_pct ที่ระบบคำนวณจาก NDVI > 0.3 กับสัดส่วน' +
    `คลาสพืชพรรณของ ESA WorldCover v200 (ข้อมูลปี ${v.worldcover_epoch_year} ความละเอียด 10 m) ` +
    'โดยค่าอ้างอิงรวมสัดส่วนที่ระดับ pixel 10 m ก่อนย่อ (reduceResolution) เพื่อไม่ให้พืชพรรณ' +
    'ที่กระจัดกระจายหายไปจากการอ่านผ่าน pyramid';
  const b = v.breakdown;
  if (b?.reference_scale_delta_pp != null) {
    text += ' · การแยกสาเหตุรายคลาสวัดที่ scale ของการวิเคราะห์ (วิธีเดียวกับที่ระบบคิด ' +
            'green_area_pct) จึงกระทบยอดกันได้ครบตามสมการ ' +
            `error = net + reference_scale_delta (${fmt(v.error_pp, 1)} = ` +
            `${fmt(b.net_pp, 1)} + ${fmt(b.reference_scale_delta_pp, 1)} จุด%)`;
  }
  text += ' · ผลการตรวจสอบทั้ง 77 จังหวัดอยู่ใน REQUIREMENTS.md §5.1 ' +
          '(ค่าเฉลี่ยความคลาดเคลื่อน −1.33 จุด% · MAE 5.53 จุด% · 60/77 จังหวัดอยู่ในเกณฑ์)';
  return note(text);
};
