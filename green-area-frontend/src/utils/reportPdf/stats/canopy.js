// Tree canopy cover เทียบเกณฑ์ 30% ของกฎ 3-30-300 (FR-17) — ใช้ร่วมกันระหว่าง
// section NDVI (จังหวัด) และ section อำเภอ · backend คำนวณ meets_target/gap/note
// มาให้แล้ว (canopy.py) ที่นี่จัดรูปแบบลง PDF อย่างเดียว ไม่ตัดสินซ้ำ
import { COLOR, calloutBox, note } from '../components';
import { fmt } from '../helpers';

const DIRECTION_TH = { increase: 'เพิ่มขึ้น', decrease: 'ลดลง', stable: 'ทรงตัว' };

// แถวตารางตัวชี้วัด — แยกตารางจาก NDVI เพราะเป็นคนละนิยามของ "พื้นที่สีเขียว"
// (NDVI = พืชพรรณทุกชนิด · canopy = เฉพาะเรือนยอดไม้ยืนต้น) ปนกันแล้วอ่านผิด
export const canopyRows = (canopy) => {
  if (!canopy?.available) return [];
  const rows = [
    ['เรือนยอดไม้ปกคลุม',
      `${fmt(canopy.canopy_pct, 1)}% (${fmt(canopy.canopy_km2, 2)} km²)`,
      'ESA WorldCover class 10 (Tree cover)'],
    ['เกณฑ์ 3-30-300', `≥ ${fmt(canopy.target_pct, 0)}%`,
      'เกณฑ์ระดับย่านตาม Konijnendijk (2023)'],
    ['สถานะ', canopy.meets_target ? 'ผ่านเกณฑ์' : 'ต่ำกว่าเกณฑ์',
      canopy.meets_target
        ? `เกินเกณฑ์ ${fmt(canopy.canopy_pct - canopy.target_pct, 1)} จุด%`
        : `ขาดอีก ${fmt(canopy.gap_pct, 1)} จุด%`],
    ['ปีของข้อมูล', `${canopy.epoch_year}`,
      canopy.epoch_offset_years > 0
        ? `epoch เดียว ไม่ใช่รายปี — ห่างจากปีที่เลือก ${canopy.epoch_offset_years} ปี`
        : 'ตรงกับปีที่เลือก'],
  ];
  if (canopy.trend) {
    const t = canopy.trend;
    rows.push([
      'แนวโน้ม (Dynamic World)',
      `${DIRECTION_TH[t.direction]}${t.direction === 'stable' ? '' : ` ${fmt(Math.abs(t.change_pp), 1)} จุด%`}`,
      `ปี ${t.year} เทียบปีฐาน ${t.baseline_year} · ${fmt(t.canopy_pct, 1)}% vs ${fmt(t.baseline_pct, 1)}%`,
    ]);
  }
  return rows;
};

// ที่มาของเกณฑ์ + ข้อจำกัดของชุดข้อมูล — ใส่ท้ายตารางเสมอ ให้ผู้อ่านตรวจย้อนได้
export const canopyMethodNote = (canopy) => {
  if (!canopy?.available) return '';
  let text =
    'เกณฑ์ 30%: กฎ 3-30-300 (Konijnendijk, C.C. 2023, Journal of Forestry Research 34:821–830) ' +
    'ระบุว่าทุกย่านควรมีเรือนยอดไม้ปกคลุมอย่างน้อย 30% ของพื้นที่ · ' +
    `ค่าที่รายงานวัดจาก ESA WorldCover v200 (ข้อมูลปี ${canopy.epoch_year} ความละเอียด 10 m) ` +
    'โดยรวมสัดส่วนเรือนยอดในระดับ pixel 10 m ก่อนย่อลงมาที่ scale ของการวิเคราะห์ ' +
    '(reduceResolution) เพื่อไม่ให้เรือนยอดที่กระจัดกระจายในเขตเมืองหายไปจากการอ่านข้อมูลผ่าน pyramid';
  if (canopy.trend) {
    text += ' · แนวโน้มรายปีวัดจาก Dynamic World V1 ซึ่งจำแนก pixel เมืองที่ปนอาคาร' +
            'เป็นสิ่งปลูกสร้าง ทำให้ระดับเรือนยอดที่วัดได้ต่ำกว่าความจริงในเขตเมือง ' +
            'จึงใช้เปรียบเทียบได้เฉพาะทิศทางการเปลี่ยนแปลงระหว่างปี ไม่ใช่ระดับสัมบูรณ์';
  }
  return note(text);
};

// callout เตือนเฉพาะพื้นที่ที่ยังไม่ผ่านเกณฑ์ — ผ่านแล้วไม่ต้องรบกวนผู้อ่าน
export const canopyCallout = (canopy, { areaKm2 } = {}) => {
  if (!canopy?.available || canopy.meets_target) return '';
  const total = areaKm2 ?? (canopy.canopy_pct > 0
    ? canopy.canopy_km2 / (canopy.canopy_pct / 100) : null);
  const needKm2 = total != null ? (canopy.gap_pct / 100) * total : null;
  return calloutBox(
    `<b>เรือนยอดต่ำกว่าเกณฑ์ 3-30-300:</b> ปัจจุบัน ${fmt(canopy.canopy_pct, 1)}% ` +
    `ขาดอีก ${fmt(canopy.gap_pct, 1)} จุด% จึงจะถึงเกณฑ์ ${fmt(canopy.target_pct, 0)}%` +
    (needKm2 != null ? ` — คิดเป็นพื้นที่เรือนยอดที่ต้องเพิ่ม ${fmt(needKm2, 1)} km²` : '') +
    ' · เกณฑ์นี้แยกจากมาตรฐาน WHO 9 m²/คน: WHO วัดว่าพื้นที่สีเขียวพอต่อจำนวนประชากรหรือไม่ ' +
    'ส่วน 3-30-300 วัดว่าร่มไม้ปกคลุมย่านเพียงพอหรือไม่ พื้นที่หนึ่งอาจผ่านเกณฑ์หนึ่งแต่ไม่ผ่านอีกเกณฑ์',
    canopy.gap_pct >= 15 ? COLOR.red : COLOR.orange
  );
};
