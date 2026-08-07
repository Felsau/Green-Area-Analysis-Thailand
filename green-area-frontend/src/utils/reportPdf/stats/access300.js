// FR-18 (เกณฑ์ "300" ของ 3-30-300) — % ประชากรในระยะเดิน 300 ม. จากพื้นที่สีเขียว
import { fmt, fmtInt } from '../helpers';
import { COLOR, sectionTitle, table, note } from '../components';

export const access300Sections = (ctx) => {
  const { access300Resp } = ctx;
  if (!(access300Resp && access300Resp.population_total != null
        && access300Resp.population_total > 0)) return [];

  const a = access300Resp;
  let html = '<div class="no-split" style="page-break-inside:avoid;break-inside:avoid;">';
  html += sectionTitle(
    `การเข้าถึงพื้นที่สีเขียว (ระยะ ${fmt(a.distance_m, 0)} ม.)`,
    { color: COLOR.greenDeep }
  );
  html += note(
    `เกณฑ์ "300" ของมาตรฐาน 3-30-300 — สัดส่วนประชากรที่อยู่ในระยะเดิน ${fmt(a.distance_m, 0)} ม. ` +
    `จากต้นไม้/พื้นที่สีเขียวที่ใกล้ที่สุด (ESA WorldCover class 10 = Tree cover) ` +
    `คำนวณจากระยะทางตรง (straight-line) ไม่ใช่ระยะทางเดินจริงบนถนน ` +
    `— ยังไม่แยกว่าเป็นพื้นที่สาธารณะที่เข้าถึงได้หรือไม่ (ดูข้อจำกัดด้านล่าง)`
  );

  const rows = [
    ['ประชากรทั้งหมด', fmtInt(a.population_total), `WorldPop ${a.worldpop_year}`],
    [`ประชากรในระยะ ${fmt(a.distance_m, 0)} ม.`, fmtInt(a.population_within),
     a.pct_within != null ? `${fmt(a.pct_within, 1)}% ของทั้งหมด` : '—'],
  ];
  html += table(['ตัวชี้วัด', 'ค่า', 'หมายเหตุ'], rows,
    { firstColWidth: 200, keepTogether: true });

  html += note(
    `* วัดระยะถึง "พืชพรรณ" ทุกชนิดที่ตรวจพบด้วยดาวเทียม ไม่ใช่เฉพาะสวนสาธารณะที่เข้าถึงได้ ` +
    `— สัดส่วนนี้จึงเป็นค่าประมาณขั้นต้น (upper bound) ของการเข้าถึงจริง ` +
    `การวิเคราะห์ที่แม่นยำกว่านี้ต้องใช้ระยะทางบนโครงข่ายถนนและข้อมูลพื้นที่สาธารณะจริง (ดู FR-19/FR-20)`
  );
  html += '</div>';

  return [{ label: 'Access300', html }];
};
