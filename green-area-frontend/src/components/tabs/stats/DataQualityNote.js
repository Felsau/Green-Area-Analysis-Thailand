// NDVI composite quality (NFR-07) — ความไม่แน่นอนของค่ากลางรายปี + ความครบของฤดูกาล
// เกณฑ์มาจากภายนอกทั้งคู่: GCOS-245 (2σ ≤ 5% Goal / ≤ 10% Threshold) และนิยามฤดู
// ของกรมอุตุนิยมวิทยา · backend คำนวณ level/label/note มาให้แล้ว ที่นี่แค่จัดรูปแบบ
import { Note } from '../../ui/Metric';

// ผ่านเกณฑ์ (goal/threshold) = ไม่ต้องเตือน · ต่ำกว่าเกณฑ์ = เตือน · ไม่มีภาพ = วิกฤต
const TONE_BY_LEVEL = { below: 'warn', none: 'crit' };

export default function DataQualityNote({ dataQuality, compact = false }) {
  if (!dataQuality) return null;

  const {
    level, label, image_count: images, clear_obs_mean: obsMean,
    uncertainty: u, uncertainty_2sigma_pct: relPct,
    seasons_missing: seasonsMissing, months_covered: months,
    first_date: firstDate, last_date: lastDate, note,
  } = dataQuality;

  return (
    <Note tone={TONE_BY_LEVEL[level] || 'default'} label="คุณภาพข้อมูล NDVI">
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, marginBottom: compact ? 0 : 6 }}>
        <span>{label}</span>
        {u != null && (
          <span className="note__num">±{(2 * u).toFixed(3)} NDVI · {relPct}% (2σ)</span>
        )}
      </div>
      <div className="helper">
        {images?.toLocaleString('th')} ภาพ · {obsMean} ภาพปลอดเมฆ/pixel · {months}/12 เดือน
        {seasonsMissing?.length > 0 && ` · ไม่มีภาพฤดู${seasonsMissing.join(', ')}`}
      </div>
      {!compact && (
        <>
          <div style={{ marginTop: 6 }}>{note}</div>
          {firstDate && lastDate && (
            <div className="helper" style={{ marginTop: 4 }}>
              ช่วงภาพที่ใช้: {firstDate} – {lastDate} · เกณฑ์ตัดระดับตาม GCOS-245 (ECV
              ด้านพืชพรรณ) ซึ่งเป็นมาตรฐานสำหรับข้อมูลระดับ climate record จึงเข้มกว่า
              ที่การจัดอันดับพื้นที่สีเขียวต้องการ
            </div>
          )}
        </>
      )}
    </Note>
  );
}
