// Closing sections — Methodology / Conclusions / Limitations / References.
// รวม logic คำนวณ deficitText (Urban-comparable หรือ fallback ระดับจังหวัด) + comparisonText.
import {
  methodologySection, conclusionsSection,
  limitationsSection, referencesSection,
} from '../sections';
import {
  WHO_REFERENCE_M2, WHO_CAVEAT_FULL, describeVsWhoReference,
} from '../../greenMetric';

const buildComparisonText = (contextResp) => {
  if (!contextResp?.target?.ndvi_rank) return '';
  const N = contextResp.provinces_in_cache;
  return `จากการเทียบกับ ${N} จังหวัดที่มีข้อมูล cached ปัจจุบัน จังหวัดนี้อยู่ <b>อันดับ ${contextResp.target.ndvi_rank} จาก ${contextResp.target.ndvi_total_ranked}</b> ` +
    `— ดูรายชื่อจริงในตาราง "ลำดับ NDVI ใน N จังหวัดที่มีข้อมูล" ของส่วน Comparison · อันดับยังเปลี่ยนได้เมื่อมีข้อมูลครบ 77 จังหวัด`;
};

// รายงานค่าที่วัดได้ตามจริง + เทียบเส้นอ้างอิง WHO แบบไม่ตัดสินผ่าน/ตก
// (ตัวชี้วัดนี้นับพืชพรรณทุกชนิด ไม่ใช่พื้นที่สาธารณะที่เข้าถึงได้ — ดู utils/greenMetric.js)
const buildDeficitText = (ndviStats, urbanResp) => {
  // ถ้ามี urban subset (Phase B-3) → ใช้เป็นค่าหลัก เพราะจำกัดขอบเขตให้ตรงกับที่คนอาศัยอยู่
  if (urbanResp?.m2_per_person_urban != null && urbanResp.population_urban > 0) {
    const curU = urbanResp.m2_per_person_urban;
    const provVal = ndviStats?.green_area_m2_per_person;
    const provNote = provVal != null
      ? ` <i>(ค่ารวมระดับจังหวัด ${provVal.toFixed(0)} m²/คน นับรวมป่า+เกษตรนอกเมืองด้วย จึงสูงกว่ามาก)</i>`
      : '';
    return `<b>พืชพรรณต่อประชากรในเขตเมือง:</b> <b>${curU.toFixed(2)} m²/คน</b> ` +
      `— ${describeVsWhoReference(curU, WHO_REFERENCE_M2)}${provNote}<br/><br/>${WHO_CAVEAT_FULL}`;
  }

  // Fallback: ไม่มี urban subset — ค่ารวมระดับจังหวัด ซึ่งกว้างกว่าเดิมอีกชั้น
  if (ndviStats?.green_area_m2_per_person != null && ndviStats.population > 0) {
    const cur = ndviStats.green_area_m2_per_person;
    return `<b>พืชพรรณต่อประชากร (ทั้งจังหวัด):</b> <b>${cur.toFixed(1)} m²/คน</b> ` +
      `— ${describeVsWhoReference(cur, WHO_REFERENCE_M2)} · ` +
      `ค่านี้นับรวมป่าและพื้นที่เกษตรนอกเขตชุมชนซึ่งประชากรในเมืองเข้าถึงไม่ได้ ` +
      `จึงสูงกว่าสภาพจริงในเมืองมาก<br/><br/>${WHO_CAVEAT_FULL}`;
  }
  return '';
};

export const closingSections = (ctx) => {
  const { ndviStats, lstStats, urbanResp, contextResp, year } = ctx;
  return [
    { label: 'Methodology', html: methodologySection(year) },
    {
      label: 'Conclusions',
      html: conclusionsSection({
        ndvi: ndviStats,
        lst: lstStats,
        deficitInfo: buildDeficitText(ndviStats, urbanResp),
        comparison: buildComparisonText(contextResp),
      }),
    },
    { label: 'Limitations', html: limitationsSection() },
    { label: 'References', html: referencesSection() },
  ];
};
