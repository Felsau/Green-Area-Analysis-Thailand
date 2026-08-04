// buildRankingReport — nation-wide ranking of provinces by green-area-per-capita.
import { PROVINCE_TH, API_BASE } from '../../constants';
import { ts, fmt, fetchImageDataUrl } from './helpers';
import { COLOR, cover, sectionTitle, table, calloutBox } from './components';
import { methodologySection, limitationsSection, referencesSection } from './sections';
import { renderSegmentsToPdf } from './layout';

export const buildRankingReport = async (data) => {
  const { rankingData, rankingYear, rankingStats } = data;
  const docTitle = `Province Ranking — ${rankingYear}`;

  const miniMap = await fetchImageDataUrl(`${API_BASE}/maps/thailand-thumb`);

  const sections = [];
  sections.push({
    label: 'Cover',
    html: cover({
      kicker: 'PROVINCE RANKING',
      heading: `อันดับพื้นที่สีเขียว ปี ${rankingYear}`,
      subheading: 'จัดอันดับจาก green area m²/คน เทียบมาตรฐาน WHO',
      accent: COLOR.green,
      miniMapDataUrl: miniMap,
      year: rankingYear,
    }),
  });

  if (rankingStats) {
    const passPct = rankingStats.total > 0
      ? (rankingStats.whoPass / rankingStats.total * 100).toFixed(1) : '0';
    let h = sectionTitle('สรุปภาพรวม');
    h += table(
      ['รายการ', 'จำนวน', 'สัดส่วน'],
      [
        ['จังหวัดทั้งหมดในระบบ', String(rankingStats.total), '100%'],
        ['ผ่านมาตรฐาน WHO', String(rankingStats.whoPass), `${passPct}%`],
        ['ต่ำกว่ามาตรฐาน WHO', String(rankingStats.whoFail), `${(100 - parseFloat(passPct)).toFixed(1)}%`],
      ],
      { firstColWidth: 240 }
    );
    // ตัวเลขนี้คือพื้นที่สีเขียวทั้งจังหวัด (รวมป่า/เกษตร) หารด้วยประชากรทั้งจังหวัด — ไม่ใช่
    // "พื้นที่สีเขียวที่เข้าถึงได้ในเมือง" ที่เกณฑ์ WHO 9 m²/คน ตั้งใจวัด (ดูรายละเอียดใน Limitations)
    // จึงเกือบทุกจังหวัด "ผ่าน" แม้แต่กรุงเทพฯ ที่มีพื้นที่สีเขียวในเมืองต่ำมาก
    h += calloutBox(
      'หมายเหตุ: ตัวเลข m²/คน นี้คำนวณจากพื้นที่สีเขียวทั้งจังหวัด (รวมป่าและพื้นที่เกษตรนอกเมือง) ' +
      'หารด้วยประชากรทั้งจังหวัด — ไม่ใช่พื้นที่สีเขียวที่ประชาชนเข้าถึงได้ในเขตเมืองตามเจตนาเดิมของเกณฑ์ WHO ' +
      'จึง "ผ่านเกณฑ์" เกือบทุกจังหวัดรวมถึงกรุงเทพฯ ที่มีพื้นที่สีเขียวในเมืองต่ำมาก · ' +
      'สำหรับตัวเลขที่เทียบเคียงเขตเมืองได้ตรงกว่า ดู Urban Subset ในรายงานรายจังหวัด (Stats)',
      COLOR.orange
    );
    sections.push({ label: 'Summary', html: h });
  }

  if (rankingData?.length > 0) {
    sections.push({
      label: 'ต่ำที่สุด',
      // "วิกฤต" เกินจริงเมื่อดูเป็นตัวเลขล้วน — จังหวัดต่ำสุดในตารางนี้ (เช่นกรุงเทพฯ) ยังคำนวณ
      // ผ่านเกณฑ์ WHO เพราะตัวส่วนคือพื้นที่สีเขียวทั้งจังหวัด ไม่ใช่เฉพาะเขตเมือง (ดู Summary ด้านบน)
      html: sectionTitle('จังหวัดพื้นที่สีเขียวต่อคนต่ำที่สุด (เทียบกันเอง)', { color: COLOR.red }) +
        table(
          ['อันดับ', 'จังหวัด', 'm²/คน', 'NDVI Mean', 'Green Area %'],
          rankingData.slice(0, 10).map(r => [
            String(r.rank),
            PROVINCE_TH[r.province] || r.province,
            fmt(r.green_area_m2_per_person, 2),
            fmt(r.ndvi_mean, 3),
            r.green_area_pct != null ? `${fmt(r.green_area_pct, 2)}%` : '—',
          ])
        ),
    });

    sections.push({
      label: 'จังหวัดดีที่สุด',
      html: sectionTitle('จังหวัดพื้นที่สีเขียวดีที่สุด', { color: COLOR.green }) +
        table(
          ['อันดับ', 'จังหวัด', 'm²/คน', 'NDVI Mean', 'Green Area %'],
          [...rankingData].reverse().slice(0, 10).map(r => [
            String(r.rank),
            PROVINCE_TH[r.province] || r.province,
            fmt(r.green_area_m2_per_person, 2),
            fmt(r.ndvi_mean, 3),
            r.green_area_pct != null ? `${fmt(r.green_area_pct, 2)}%` : '—',
          ])
        ),
    });

    sections.push({
      label: 'ทั้งหมด',
      html: sectionTitle('ข้อมูลทั้งหมด') +
        table(
          ['#', 'จังหวัด', 'm²/คน', 'NDVI'],
          rankingData.map(r => [
            String(r.rank),
            PROVINCE_TH[r.province] || r.province,
            fmt(r.green_area_m2_per_person, 2),
            fmt(r.ndvi_mean, 3),
          ])
        ),
    });
  }

  sections.push({ label: 'Methodology', html: methodologySection(rankingYear) });
  sections.push({ label: 'Limitations', html: limitationsSection() });
  sections.push({ label: 'References', html: referencesSection() });

  await renderSegmentsToPdf(sections, `ranking_report_${rankingYear}_${ts()}.pdf`, { docTitle });
};
