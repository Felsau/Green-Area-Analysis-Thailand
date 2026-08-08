// buildRankingReport — nation-wide ranking of provinces by green-area-per-capita.
import { PROVINCE_TH, API_BASE } from '../../constants';
import { ts, fmt, fetchImageDataUrl } from './helpers';
import { COLOR, cover, sectionTitle, table, calloutBox } from './components';
import { methodologySection, limitationsSection, referencesSection } from './sections';
import { renderSegmentsToPdf } from './layout';
import { WHO_CAVEAT_FULL } from '../greenMetric';

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
      subheading: 'จัดอันดับจาก green area m²/คน (urban subset) เทียบค่าอ้างอิง WHO',
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
        ['สูงกว่าค่าอ้างอิง WHO 9 m²/คน', String(rankingStats.whoPass), `${passPct}%`],
        ['ต่ำกว่าค่าอ้างอิง', String(rankingStats.whoFail), `${(100 - parseFloat(passPct)).toFixed(1)}%`],
      ],
      { firstColWidth: 240 }
    );
    // ไม่เรียกว่าผ่าน/ไม่ผ่านเกณฑ์ — ตัวชี้วัดนี้นับพืชพรรณทุกชนิด ไม่ใช่พื้นที่สาธารณะ
    // ตามนิยาม WHO (ดู utils/greenMetric.js)
    h += calloutBox(WHO_CAVEAT_FULL, COLOR.orange);
    sections.push({ label: 'Summary', html: h });
  }

  if (rankingData?.length > 0) {
    sections.push({
      label: 'ต่ำที่สุด',
      // เลี่ยงคำว่า "วิกฤต" — จังหวัดต่ำสุดในตารางนี้ก็ยังสูงกว่าค่าอ้างอิง WHO
      html: sectionTitle('จังหวัดพื้นที่สีเขียวต่อคนต่ำที่สุด (Urban Subset, เทียบกันเอง)', { color: COLOR.red }) +
        table(
          ['อันดับ', 'จังหวัด', 'm²/คน', 'NDVI Mean', 'Green % (Urban)'],
          rankingData.slice(0, 10).map(r => [
            String(r.rank),
            PROVINCE_TH[r.province] || r.province,
            fmt(r.m2_per_person_urban, 2),
            fmt(r.ndvi_mean_urban, 3),
            r.green_share_in_urban_pct != null ? `${fmt(r.green_share_in_urban_pct, 2)}%` : '—',
          ])
        ),
    });

    sections.push({
      label: 'จังหวัดดีที่สุด',
      html: sectionTitle('จังหวัดพื้นที่สีเขียวดีที่สุด (Urban Subset)', { color: COLOR.green }) +
        table(
          ['อันดับ', 'จังหวัด', 'm²/คน', 'NDVI Mean', 'Green % (Urban)'],
          [...rankingData].reverse().slice(0, 10).map(r => [
            String(r.rank),
            PROVINCE_TH[r.province] || r.province,
            fmt(r.m2_per_person_urban, 2),
            fmt(r.ndvi_mean_urban, 3),
            r.green_share_in_urban_pct != null ? `${fmt(r.green_share_in_urban_pct, 2)}%` : '—',
          ])
        ),
    });

    sections.push({
      label: 'ทั้งหมด',
      html: sectionTitle('ข้อมูลทั้งหมด (Urban Subset)') +
        table(
          ['#', 'จังหวัด', 'm²/คน', 'NDVI'],
          rankingData.map(r => [
            String(r.rank),
            PROVINCE_TH[r.province] || r.province,
            fmt(r.m2_per_person_urban, 2),
            fmt(r.ndvi_mean_urban, 3),
          ])
        ),
    });
  }

  sections.push({ label: 'Methodology', html: methodologySection(rankingYear) });
  sections.push({ label: 'Limitations', html: limitationsSection() });
  sections.push({ label: 'References', html: referencesSection() });

  await renderSegmentsToPdf(sections, `ranking_report_${rankingYear}_${ts()}.pdf`, { docTitle });
};
