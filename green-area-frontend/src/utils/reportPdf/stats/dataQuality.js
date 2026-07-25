// NDVI composite quality (NFR-07) — ใช้ร่วมกันระหว่าง section NDVI (จังหวัด) และ
// section อำเภอ · backend คำนวณ level/label/note มาให้แล้ว (routers/ndvi/compute.py)
// ที่นี่ทำหน้าที่จัดรูปแบบลง PDF อย่างเดียว ไม่ตัดสินคุณภาพซ้ำ
import { COLOR, calloutBox, note } from '../components';
import { esc } from '../helpers';

const MONTHS_TH = ['ม.ค.', 'ก.พ.', 'มี.ค.', 'เม.ย.', 'พ.ค.', 'มิ.ย.',
                   'ก.ค.', 'ส.ค.', 'ก.ย.', 'ต.ค.', 'พ.ย.', 'ธ.ค.'];

const LEVEL_COLOR = {
  goal: COLOR.green,
  threshold: COLOR.primary,
  below: COLOR.orange,
  none: COLOR.red,
};

// แถวตารางตัวชี้วัด — ต่อท้ายตาราง NDVI เดิม เพื่อให้ค่าและความไม่แน่นอนอยู่ด้วยกัน
export const dataQualityRows = (dq) => {
  if (!dq) return [];
  const missingMonths = dq.months_missing?.length
    ? `ขาด: ${dq.months_missing.map(m => MONTHS_TH[m - 1]).join(', ')}`
    : 'ครบทุกเดือน';
  const seasons = dq.seasonally_representative
    ? 'ครบทั้ง 3 ฤดู'
    : `ไม่มีภาพฤดู${(dq.seasons_missing || []).join(', ')}`;
  return [
    ['ภาพที่ใช้ทำ composite', `${(dq.image_count ?? 0).toLocaleString('th')} ภาพ`,
      `Sentinel-2 ที่เมฆทั้งภาพ < ${dq.cloud_filter_pct}%`],
    ['ภาพปลอดเมฆต่อ pixel', `เฉลี่ย ${dq.clear_obs_mean} (ต่ำสุด ${dq.clear_obs_min})`,
      'จำนวนตัวอย่างที่ median ใช้จริง'],
    ['การกระจายของ NDVI ในปี (σ)', dq.ndvi_sd_mean ?? '—',
      'รวมการแปรผันตามฤดูกาลและ noise ของเซนเซอร์'],
    ['ความไม่แน่นอนของค่ากลางรายปี',
      dq.uncertainty != null ? `±${(2 * dq.uncertainty).toFixed(3)} NDVI (2σ)` : '—',
      dq.uncertainty_2sigma_pct != null ? `${dq.uncertainty_2sigma_pct}% ของค่าที่รายงาน` : ''],
    ['ความเป็นตัวแทนของฤดูกาล', seasons, 'ฤดูตามนิยามกรมอุตุนิยมวิทยา'],
    ['เดือนที่มีภาพ', `${dq.months_covered}/12 เดือน`, missingMonths],
    ['ช่วงวันที่ของภาพ', dq.first_date && dq.last_date ? `${dq.first_date} – ${dq.last_date}` : '—', ''],
    ['ระดับเทียบเกณฑ์ GCOS', dq.label || '—', 'Goal ≤ 5% · Threshold ≤ 10% (2σ)'],
  ];
};

// ที่มาของเกณฑ์ — ใส่ท้ายตารางเสมอ เพื่อให้ผู้อ่านตรวจสอบย้อนได้ว่าไม่ใช่เกณฑ์ที่ตั้งเอง
export const dataQualityMethodNote = () => note(
  'เกณฑ์คุณภาพ: ความไม่แน่นอนคำนวณเป็น standard error ของค่ามัธยฐาน ' +
  '(u = 1.2533·σ/√n · σ มีพื้นขั้นต่ำ 0.06 NDVI จาก RMSE การ validate Sentinel-2 ' +
  'กับเซนเซอร์ภาคพื้นดิน — Lee et al. 2024) แล้วเทียบเกณฑ์ required measurement ' +
  'uncertainty ของ GCOS-245 (2022 GCOS ECVs Requirements) สำหรับ FAPAR ซึ่งเป็น ECV ' +
  'ด้านพืชพรรณที่ใกล้ NDVI ที่สุด — Goal 5% · Threshold 10% ที่ 2σ · ' +
  'การรายงานตัวชี้วัดคุณภาพคู่กับค่าเป็นหลักการของ QA4EO (CEOS/GEO) · ' +
  'หมายเหตุ: NDVI ไม่ได้เป็น ECV ในตัวเอง เกณฑ์นี้จึงเป็นการเทียบเคียงกับมาตรฐาน ' +
  'climate record ซึ่งเข้มกว่าที่งานจัดอันดับพื้นที่สีเขียวต้องการ'
);

// callout เตือนเฉพาะกรณีที่ค่าอาจตีความผิดได้ — ผ่านเกณฑ์แล้วไม่ต้องรบกวนผู้อ่าน
export const dataQualityCallout = (dq) => {
  if (!dq || dq.level === 'goal' || dq.level === 'threshold') return '';
  return calloutBox(
    `<b>ความไม่แน่นอนของข้อมูล:</b> ${esc(dq.note || '')}`,
    LEVEL_COLOR[dq.level] || COLOR.orange
  );
};
