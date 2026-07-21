// buildRecommendReport — AI tree-planting recommendations (weights + locations + species).
import { ts, esc, formatEnName } from './helpers';
import { COLOR, cover, sectionTitle, paragraph, table } from './components';
import { renderSegmentsToPdf } from './layout';

export const buildRecommendReport = async (data) => {
  const { recommendData, selectedProvince, selectedProvinceEN, selectedDistrict } = data;
  if (!recommendData) return;

  const districtEN = data.selectedDistrictEN || selectedDistrict;
  const districtPretty = formatEnName(districtEN);
  const docTitle = `AI Recommendation — ${selectedProvinceEN}${selectedDistrict ? ` / ${districtPretty}` : ''}`;
  const sections = [];

  sections.push({
    label: 'Cover',
    html: cover({
      kicker: 'AI RECOMMENDATION',
      heading: 'แผนปลูกต้นไม้เชิงพื้นที่',
      subheading: `${selectedProvince}${selectedDistrict ? ' — ' + districtPretty : ''}`,
      accent: COLOR.green,
    }),
  });

  let h = sectionTitle('วิธีการวิเคราะห์');
  const popYearNote = recommendData.worldpop_year ? ` ปี ${recommendData.worldpop_year}` : '';
  h += paragraph(
    `ระบบวิเคราะห์จุดที่เหมาะสมในการปลูกต้นไม้โดยถ่วงน้ำหนัก 4 ปัจจัย: ดัชนีพืชพรรณ <b>NDVI</b> (พื้นที่ที่ขาดต้นไม้), อุณหภูมิผิวพื้น <b>LST</b> (พื้นที่ร้อน), ความหนาแน่นประชากร (WorldPop 100m${popYearNote}) และระยะถึงพื้นที่สีเขียวเดิม (การเข้าถึง — ESA WorldCover)`
  );
  const w = recommendData.weights || {};
  const weightRows = [
    ['NDVI ต่ำ (ขาดต้นไม้)', `${(w.ndvi * 100).toFixed(0)}%`],
    ['LST สูง (ความร้อน)', `${(w.lst * 100).toFixed(0)}%`],
    ['ประชากรหนาแน่น', `${(w.population * 100).toFixed(0)}%`],
  ];
  if (w.access != null) weightRows.push(['เข้าถึงพื้นที่สีเขียวยาก', `${(w.access * 100).toFixed(0)}%`]);
  h += table(['ปัจจัย', 'น้ำหนัก'], weightRows, { firstColWidth: 240 });
  sections.push({ label: 'Method', html: h });

  if (recommendData.top_locations?.length > 0) {
    // จุดจาก cache รุ่นเก่าอาจไม่มีป้าย landuse — โชว์คอลัมน์เมื่อมีอย่างน้อยหนึ่งจุด
    const hasLanduse = recommendData.top_locations.some((p) => p.landuse);
    let th = sectionTitle(`Top ${recommendData.top_locations.length} จุดที่ควรปลูกต้นไม้`) +
      table(
        ['อันดับ', 'Latitude', 'Longitude', 'Score', 'ความเร่งด่วน',
          ...(hasLanduse ? ['การใช้ที่ดิน'] : [])],
        recommendData.top_locations.map((p, i) => [
          String(i + 1),
          p.lat.toFixed(5), p.lng.toFixed(5),
          p.score.toFixed(3),
          p.score >= 0.7 ? 'เร่งด่วนสูง' : p.score >= 0.5 ? 'เร่งด่วน' : 'ปานกลาง',
          ...(hasLanduse ? [p.landuse?.name_th || '–'] : []),
        ])
      );
    // แนวทางการปลูกตามประเภทที่ดินที่พบในจุดแนะนำ (unique ต่อประเภท)
    const guides = [...new Map(recommendData.top_locations
      .filter((p) => p.landuse?.guidance)
      .map((p) => [p.landuse.code, p.landuse])).values()];
    if (guides.length > 0) {
      th += paragraph(guides
        .map((lu) => `<b>${esc(lu.name_th)}:</b> ${esc(lu.guidance)}`)
        .join('<br/>'));
    }
    sections.push({ label: 'Top จุดปลูก', html: th });
  }

  const sp = recommendData.recommended_species;
  if (sp?.species?.length > 0) {
    const spMeta = sp.region
      ? ` (ภาค${sp.region}${sp.landuse_context ? ` · ที่ดินเด่น: ${sp.landuse_context.name_th}` : ''})`
      : '';
    let sh = sectionTitle(`พันธุ์ไม้แนะนำ${spMeta}`, { color: COLOR.green });
    sh += sp.species.map(s => `
      <div style="margin:6px 40px 10px;padding:12px 16px;background:#f8f9fa;border-radius:6px;border-left:3px solid ${COLOR.green};">
        <div style="display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;">
          <div style="font-size:13pt;font-weight:700;color:${COLOR.text};">${esc(s.name_th)}</div>
          <div style="font-size:9.5pt;font-style:italic;color:${COLOR.muted};">${esc(s.scientific || '')}</div>
        </div>
        <div style="font-size:10pt;color:${COLOR.text};margin-top:4px;">${esc(s.purpose)} · สูง ${esc(s.height_m)} ม.${s.traits?.length ? ' · ' + s.traits.map(esc).join(' / ') : ''}</div>
        <div style="font-size:9.5pt;color:${COLOR.muted};margin-top:4px;line-height:1.6;">เหตุผล: ${esc(s.reason)}</div>
      </div>
    `).join('');
    sections.push({ label: 'Species', html: sh });
  }

  const im = recommendData.impact;
  if (im && im.trees_total > 0) {
    const baht = (v) => v == null ? '–'
      : v >= 1e6 ? `${(v / 1e6).toLocaleString('th-TH', { maximumFractionDigits: 1 })} ล้านบาท`
        : `${Math.round(v).toLocaleString('th-TH')} บาท`;
    let ih = sectionTitle('ผลกระทบและมูลค่าบริการระบบนิเวศ (i-Tree)', { color: COLOR.green });
    const rows = [
      ['ต้นไม้รวม (400 ต้น/เฮกตาร์)', `${im.trees_total.toLocaleString()} ต้น`],
      ['CO₂ ดูดซับ/ปี (ศักยภาพเต็ม)', `${im.annual_co2_tonnes.toLocaleString()} ตัน`],
    ];
    // breakdown พื้นที่ควรปลูกตามการใช้ที่ดิน — impact จาก cache ก่อน v8 ไม่มี field นี้
    const luClasses = (im.plantable_landuse?.classes || []).filter((c) => c.share_pct > 0);
    if (luClasses.length > 0)
      rows.push(['พื้นที่ควรปลูก แยกตามการใช้ที่ดิน',
        luClasses.map((c) => `${c.name_th} ${c.share_pct}%`).join(' · ')]);
    if (im.annual_co2_tonnes_low != null)
      rows.push(['CO₂ ช่วงจริง (รวมอัตรารอด)', `${im.annual_co2_tonnes_low.toLocaleString()}–${im.annual_co2_tonnes_high.toLocaleString()} ตัน`]);
    rows.push(['อุณหภูมิที่คาดว่าจะลดลง', `${im.expected_delta_lst_c}°C (canopy เต็มที่ ~${im.maturity_years} ปี)`]);
    const eco = im.ecosystem_services;
    if (eco) {
      const air = eco.air_pollution_removal_kg;
      rows.push(
        ['ดูดซับมลพิษอากาศ/ปี', `${air.total.toLocaleString()} kg (PM2.5 ${air.pm25.toLocaleString()} · O₃ ${air.o3.toLocaleString()} · NO₂ ${air.no2.toLocaleString()})`],
        ['ดักน้ำฝน/ลดน้ำท่วม/ปี', `${eco.stormwater_runoff_m3.toLocaleString()} m³`],
        ['มูลค่าคาร์บอน/ปี', baht(eco.annual_value_thb.co2)],
        ['มูลค่าอากาศสะอาด/ปี', baht(eco.annual_value_thb.air_pollution)],
        ['มูลค่าจัดการน้ำฝน/ปี', baht(eco.annual_value_thb.stormwater)],
        ['มูลค่าบริการนิเวศรวม/ปี', `${baht(eco.annual_value_thb.total)} (คาดจริง ~${baht(eco.annual_value_thb_expected)})`],
      );
    }
    ih += table(['ตัวชี้วัด', 'ค่าประมาณการ'], rows, { firstColWidth: 240 });
    if (im.methodology?.sources?.length)
      ih += paragraph(`<span style="font-size:9pt;color:${COLOR.muted};">อ้างอิง: ${esc(im.methodology.sources.join(' · '))}</span>`);
    sections.push({ label: 'Impact', html: ih });
  }

  await renderSegmentsToPdf(
    sections,
    `recommend_report_${(districtEN || selectedProvinceEN || 'thailand').replace(/\s+/g, '_')}_${ts()}.pdf`,
    { docTitle }
  );
};
