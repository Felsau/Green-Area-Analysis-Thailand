// Comparison context — เทียบจังหวัดกับค่าเฉลี่ย N จังหวัดที่มี cache + อันดับ NDVI.
import { PROVINCE_TH } from '../../../constants';
import { fmt, arrow } from '../helpers';
import { COLOR, sectionTitle, table, calloutBox, note } from '../components';
import { WHO_CAVEAT_SHORT } from '../../greenMetric';

export const comparisonSections = (ctx) => {
  const {
    contextResp, ndviStats,
    selectedProvince, selectedProvinceEN, selectedDistrict, districtPretty, year,
  } = ctx;
  if (!(contextResp?.national && ndviStats?.ndvi_mean != null)) return [];

  const nat = contextResp.national;
  const target = contextResp.target;
  const N = contextResp.provinces_in_cache;

  let cHtml = sectionTitle(
    `เทียบกับค่าเฉลี่ย ${N} จังหวัดที่มีข้อมูล · ระดับจังหวัด`,
    { color: COLOR.primary }
  );
  cHtml += note(
    `ข้อมูลในส่วนนี้เป็น <b>ระดับจังหวัด</b> (${selectedProvince}) ไม่ใช่ระดับอำเภอ — ` +
    `คำนวณจาก ${N} จังหวัดเท่านั้น <b>ไม่ใช่ค่าเฉลี่ยจริงทั้งประเทศ 77 จังหวัด</b>`
  );

  cHtml += table(
    ['ตัวชี้วัด', `${selectedProvince}`, `ค่าเฉลี่ย ${N} จังหวัด`, 'ส่วนต่าง'],
    [
      ['NDVI Mean',
        fmt(ndviStats.ndvi_mean, 3),
        fmt(nat.ndvi_mean_avg, 3),
        arrow(ndviStats.ndvi_mean, nat.ndvi_mean_avg, v => v.toFixed(3), 0.005)],
      ['พื้นที่สีเขียว %',
        `${fmt(ndviStats.green_area_pct, 1)}%`,
        nat.green_area_pct_avg != null ? `${fmt(nat.green_area_pct_avg, 1)}%` : '—',
        arrow(ndviStats.green_area_pct, nat.green_area_pct_avg, v => `${v.toFixed(1)}%`, 0.05)],
      ['Green m²/คน',
        fmt(ndviStats.green_area_m2_per_person, 2),
        fmt(nat.green_area_m2_per_person_avg, 2),
        arrow(ndviStats.green_area_m2_per_person, nat.green_area_m2_per_person_avg,
              v => v.toFixed(2), 0.005)],
    ],
    { firstColWidth: 160, keepTogether: true }
  );

  // อันดับจาก urban subset ให้ตรงกับ /analysis/ranking — คนละแหล่งข้อมูลกับ
  // ตารางเทียบค่าเฉลี่ยด้านบนที่ใช้ค่าทั้งจังหวัด
  if (contextResp.ranked_top?.length > 0) {
    const targetEN = selectedProvinceEN;
    cHtml += sectionTitle('อันดับพื้นที่สีเขียวต่อคน (Urban Subset, อันดับสูงสุด 10)', { color: COLOR.primary });
    cHtml += note(
      `อันดับนี้มาจาก <b>urban subset</b> (เฉพาะเขต Built-up — รายละเอียดดู section "Urban") ` +
      `คนละแหล่งข้อมูลกับตารางเทียบค่าเฉลี่ยด้านบนที่เป็นทั้งจังหวัด · ${WHO_CAVEAT_SHORT}`
    );
    cHtml += table(
      ['อันดับ', 'จังหวัด', 'm²/คน (Urban)'],
      contextResp.ranked_top.map(r => {
        const isTarget = r.province === targetEN;
        const provLabel = (PROVINCE_TH[r.province] || r.province) + (isTarget ? ' ◀' : '');
        return [
          String(r.rank),
          provLabel,
          r.m2_per_person_urban != null ? fmt(r.m2_per_person_urban, 2) : '—',
        ];
      }),
      { keepTogether: true }
    );
    cHtml += note('◀ = จังหวัดที่กำลังวิเคราะห์ในรายงานนี้ · อันดับ 1 = น้อยที่สุด');
  }
  if (target?.urban_rank) {
    cHtml += calloutBox(
      `อันดับพื้นที่สีเขียวต่อคน (Urban Subset): <b>#${target.urban_rank} จาก ${target.urban_total_ranked} จังหวัด</b> ที่มี cached ปี ${year} · อันดับนี้อาจเปลี่ยนเมื่อมีข้อมูลครบ 77 จังหวัด`,
      COLOR.primary
    );
  }
  if (selectedDistrict) {
    cHtml += note(
      `⚠ การเทียบนี้ใช้ตัวเลข <b>ระดับจังหวัด</b>เพื่อให้มีบริบท ส่วนข้อมูลรายอำเภอ (${districtPretty}) ดูใน section "อำเภอ" ด้านบน`
    );
  }

  return [{ label: 'Comparison', html: cHtml }];
};
