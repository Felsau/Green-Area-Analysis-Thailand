// District summary table (Phase B-1) — รายละเอียดรายอำเภอ เฉพาะรายงานระดับจังหวัด.
import { fmt, fmtInt, formatEnName } from '../helpers';
import { COLOR, sectionTitle, table, calloutBox, note } from '../components';

export const districtSummarySections = (ctx) => {
  const { districtSummary, selectedDistrict, selectedProvince, year } = ctx;
  if (!(!selectedDistrict && districtSummary?.data?.length > 0)) return [];

  let dsHtml = sectionTitle(
    `รายละเอียดรายอำเภอ · ${selectedProvince}`,
    { color: COLOR.primary }
  );
  const cached = districtSummary.districts_in_cache;
  const total = districtSummary.districts_total;
  dsHtml += note(
    `แสดง ${cached} อำเภอจากทั้งหมด ${total} อำเภอที่มีข้อมูล cached ปี ${year} · ` +
    `เรียงตาม NDVI Mean จากมากไปน้อย — เปิดเข้าแต่ละอำเภอใน UI เพื่อ trigger compute สำหรับอำเภอที่ยังไม่มี cache`
  );

  const rows = districtSummary.data.map((d, i) => [
    String(i + 1),
    formatEnName(d.district),
    fmt(d.ndvi_mean, 3),
    d.green_area_pct != null ? `${fmt(d.green_area_pct, 1)}%` : '—',
    d.green_area_km2 != null ? fmtInt(d.green_area_km2) : '—',
    // FR-17 · เกณฑ์ 3-30-300 เป็นเกณฑ์ระดับย่าน ตารางรายอำเภอจึงเป็นที่ที่อ่านมีความหมาย
    // ที่สุด — ติด ✓/✗ ไว้ให้กวาดตาหาอำเภอที่ไม่ผ่านได้ทันทีโดยไม่ต้องเทียบเลขเอง
    d.canopy_pct != null
      ? `${fmt(d.canopy_pct, 1)}% ${d.canopy_meets_target ? '✓' : '✗'}`
      : '—',
    d.lst_mean != null ? `${fmt(d.lst_mean, 1)}°C` : '—',
  ]);
  dsHtml += table(
    ['#', 'อำเภอ', 'NDVI Mean', 'Green %', 'Green km²', 'Canopy % (≥30)', 'LST'],
    rows,
    { firstColWidth: 36 }
  );

  // สรุปเกณฑ์ 30% ระดับจังหวัด — ตัวหารคืออำเภอที่มีค่า canopy จริง ไม่ใช่อำเภอทั้งหมด
  const cs = districtSummary.canopy_summary;
  if (cs?.districts_with_canopy > 0) {
    const failing = cs.districts_with_canopy - cs.districts_meeting_target;
    dsHtml += calloutBox(
      `🌳 <b>เกณฑ์เรือนยอด 30% (3-30-300):</b> ผ่าน ${cs.districts_meeting_target} ` +
      `จาก ${cs.districts_with_canopy} อำเภอที่มีข้อมูล` +
      (failing > 0 ? ` — อีก ${failing} อำเภอยังต่ำกว่าเกณฑ์` : ' — ผ่านครบทุกอำเภอ') +
      `<br/>ค่าเฉลี่ยเรือนยอดของอำเภอที่มีข้อมูล: <b>${fmt(cs.canopy_pct_avg, 1)}%</b> ` +
      '· ค่าเรือนยอดมาจาก ESA WorldCover (ข้อมูลปี 2564) จึงไม่เปลี่ยนตามปีที่เลือก',
      failing > 0 ? COLOR.orange : COLOR.green
    );
  }

  // insight: top/bottom 3 + spread
  const ranked = districtSummary.data.filter(d => d.ndvi_mean != null);
  if (ranked.length >= 3) {
    const top3 = ranked.slice(0, 3).map(d => formatEnName(d.district)).join(', ');
    const bot3 = ranked.slice(-3).reverse().map(d => formatEnName(d.district)).join(', ');
    const spread = ranked[0].ndvi_mean - ranked[ranked.length - 1].ndvi_mean;
    dsHtml += calloutBox(
      `🌳 NDVI สูงสุด 3 อำเภอ: <b>${top3}</b><br/>` +
      `🏙️ NDVI ต่ำสุด 3 อำเภอ: <b>${bot3}</b><br/>` +
      `ส่วนต่างสูงสุด-ต่ำสุด: <b>${spread.toFixed(3)}</b> — ${spread >= 0.2 ? 'ความหลากหลายสูงในจังหวัด ควรวิเคราะห์เป็นรายอำเภอเพื่อกำหนดมาตรการเฉพาะพื้นที่' : 'อำเภอใกล้เคียงกัน อาจใช้นโยบายระดับจังหวัดร่วมได้'}`,
      COLOR.primary
    );
  }

  return [{ label: 'Districts', html: dsHtml }];
};
