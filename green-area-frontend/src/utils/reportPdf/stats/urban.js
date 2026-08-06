// Urban Subset (Phase B-3) — พืชพรรณต่อประชากรเฉพาะในเขต Built-up.
// ไม่ตัดสินผ่าน/ไม่ผ่าน WHO — เหตุผลอยู่ใน utils/greenMetric.js
import { fmt, fmtInt } from '../helpers';
import { COLOR, sectionTitle, table, calloutBox, note } from '../components';
import {
  WHO_REFERENCE_M2, WHO_CAVEAT_FULL, describeVsWhoReference,
} from '../../greenMetric';

export const urbanSections = (ctx) => {
  const { urbanResp, ndviStats } = ctx;
  // ตอบโจทย์ "WHO 9 m²/คน เปรียบกับอะไรกันแน่?" โดย clip ด้วย ESA WorldCover Built-up
  if (!(urbanResp && urbanResp.urban_area_km2 != null && urbanResp.urban_area_km2 > 0)) return [];

  const u = urbanResp;
  // wrap ทั้ง section ใน no-split เพื่อกัน heading หลุดท้ายหน้าก่อน (section นี้ ~430px เข้าหน้าเดียวได้)
  let uHtml = '<div class="no-split" style="page-break-inside:avoid;break-inside:avoid;">';
  uHtml += sectionTitle(
    `พืชพรรณในเขตเมือง (Urban Subset)`,
    { color: COLOR.greenDeep }
  );
  uHtml += note(
    `วิเคราะห์เฉพาะภายในเขต <b>Built-up</b> (ESA WorldCover v200, class 50, ปี ${u.worldcover_year}) ` +
    `— เป็น proxy ของ "เขตชุมชน/เทศบาล" จึงสะท้อนสภาพพื้นที่ที่ประชากรอาศัยอยู่จริง ` +
    `ได้ดีกว่าค่ารวมระดับจังหวัดที่นับรวมป่าและเกษตรนอกเมือง<br/><br/>${WHO_CAVEAT_FULL}`
  );

  const urbanRows = [
    ['พื้นที่ Built-up', `${fmt(u.urban_area_km2, 2)} km²`,
     `${fmt(u.urban_share_pct, 2)}% ของจังหวัด`],
    ['NDVI Mean (ในเขต Built-up)',
     u.ndvi_mean_urban != null ? fmt(u.ndvi_mean_urban, 3) : '—',
     u.ndvi_mean_urban != null && u.ndvi_mean_urban < 0.3
       ? 'ต่ำ — สอดคล้องกับเขตชุมชนทั่วไป'
       : 'พืชพรรณในเขตเมืองดี'],
    ['พืชพรรณในเขต Built-up',
     `${fmt(u.green_in_urban_km2, 2)} km²`,
     `${fmt(u.green_share_in_urban_pct, 1)}% ของ Built-up`],
    ['ประชากรในเขต Built-up', fmtInt(u.population_urban),
     'จาก WorldPop ' + u.worldpop_year + ' (mask ด้วย Built-up)'],
    ['พืชพรรณ/คน (Urban)',
     u.m2_per_person_urban != null ? `${fmt(u.m2_per_person_urban, 2)} m²` : '—',
     describeVsWhoReference(u.m2_per_person_urban, WHO_REFERENCE_M2)],
  ];
  uHtml += table(
    ['ตัวชี้วัด', 'ค่า', 'การตีความ'],
    urbanRows,
    { firstColWidth: 200, keepTogether: true }
  );

  // Comparison callout — ระดับจังหวัด vs Urban
  if (ndviStats?.green_area_m2_per_person != null && u.m2_per_person_urban != null) {
    const provVal = ndviStats.green_area_m2_per_person;
    const urbanVal = u.m2_per_person_urban;
    const ratio = provVal > 0 ? (urbanVal / provVal) : 0;
    // ไม่สรุปผ่าน/ไม่ผ่าน — บอกว่าการจำกัดขอบเขตให้แคบลงทำให้ค่าเปลี่ยนไปเท่าไร
    // ซึ่งเป็นข้อสรุปที่ข้อมูลรองรับได้จริง (ดู WHO_CAVEAT_FULL ด้านบนของ section)
    const interpretation =
      `การจำกัดขอบเขตเหลือเฉพาะเขตเมืองทำให้ค่าลดลง <b>${(provVal / urbanVal).toFixed(1)} เท่า</b> ` +
      `— ส่วนต่างคือพืชพรรณนอกเขตชุมชน (ป่า/เกษตร) ที่ประชากรในเมืองไม่ได้ใช้ประโยชน์โดยตรง · ` +
      `ค่าที่เหลือ <b>${fmt(urbanVal, 2)} m²/คน</b> ${describeVsWhoReference(urbanVal, WHO_REFERENCE_M2)} ` +
      `แต่ยัง<b>ไม่ใช่</b>ปริมาณพื้นที่สาธารณะที่เข้าถึงได้ตามนิยามของ WHO`;
    uHtml += calloutBox(
      `<b>เปรียบเทียบ:</b><br/>` +
      `• ระดับจังหวัด (รวมป่า+เกษตร): <b>${fmt(provVal, 2)} m²/คน</b><br/>` +
      `• ในเขต Built-up เท่านั้น: <b>${fmt(urbanVal, 2)} m²/คน</b> (${(ratio * 100).toFixed(1)}% ของค่ารวม)<br/>` +
      `<br/>${interpretation}`,
      COLOR.greenDeep
    );
  }

  uHtml += note(
    `* ESA WorldCover v200 อัปเดตล่าสุดปี 2021 — ใช้เป็น proxy ของ urban extent ในทุกปีที่วิเคราะห์ ` +
    `(สิ่งปลูกสร้างเปลี่ยนแปลงน้อยใน timescale 2-5 ปี) · WorldPop ใช้ปี ${u.worldpop_year}`
  );
  uHtml += '</div>';

  return [{ label: 'Urban', html: uHtml }];
};
