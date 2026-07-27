// Tree canopy cover vs เกณฑ์ 30% ของกฎ 3-30-300 (FR-17) — วางคู่ GreenDeficitNote
// ที่เทียบมาตรฐาน WHO m²/คน เพราะสองเกณฑ์นี้ตอบคนละคำถามและต้องอ่านคู่กัน
//
// ค่าหลักมาจาก ESA WorldCover ซึ่งมี epoch เดียว (2021) จึงไม่ขยับตามปีที่ผู้ใช้เลือก
// — ต้องกำกับปีข้อมูลไว้ข้างตัวเลขเสมอ ไม่งั้นผู้ใช้จะเข้าใจว่าเป็นค่าของปีที่เลือก
// backend คำนวณ meets_target/gap/label/note มาให้แล้ว ที่นี่แค่จัดรูปแบบ
import { Note } from '../../ui/Metric';

const DIRECTION_MARK = { increase: '▲', decrease: '▼', stable: '→' };

export default function CanopyNote({ canopy, areaKm2, compact = false }) {
  if (!canopy?.available) return null;

  const {
    canopy_pct: pct, canopy_km2: km2, target_pct: target,
    meets_target: meets, gap_pct: gap, epoch_year: epochYear,
    epoch_offset_years: epochOffset, trend,
  } = canopy;

  // ขาดอีกกี่ km² ถึงเกณฑ์ — จุด% อ่านยากกว่าพื้นที่จริงเวลาคุยเรื่องงบ/แผนปลูก
  // (คำนวณจากพื้นที่ที่ backend วัดได้จริง ไม่ใช่ area_km2 ของตาราง districts
  // เพราะสองค่านี้มาจากคนละ geometry อาจต่างกันเล็กน้อย)
  const totalKm2 = areaKm2 ?? (pct > 0 ? km2 / (pct / 100) : null);
  const needKm2 = totalKm2 != null ? (gap / 100) * totalKm2 : null;

  return (
    <Note tone={meets ? 'default' : gap >= 15 ? 'crit' : 'warn'}
          label={`เรือนยอดไม้ / เกณฑ์ ${target}% (3-30-300)`}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, marginBottom: 6 }}>
        <span>สถานะ: <strong>{meets ? 'ผ่านเกณฑ์' : 'ต่ำกว่าเกณฑ์'}</strong></span>
        <span className="note__num">{pct.toFixed(1)} / {target}%</span>
      </div>

      {meets ? (
        <div>เรือนยอดปกคลุม <span className="note__num">{km2.toLocaleString('th')} km²</span> — เกินเกณฑ์อยู่ <span className="note__num">{(pct - target).toFixed(1)} จุด%</span></div>
      ) : (
        <div>
          ต้องเพิ่มอีก <span className="note__num">{gap.toFixed(1)} จุด%</span>
          {needKm2 != null && <> — เทียบเท่า <span className="note__num">{needKm2.toFixed(1)} km²</span></>}
        </div>
      )}

      {!compact && (
        <>
          {trend && (
            <div style={{ marginTop: 6 }}>
              แนวโน้ม {DIRECTION_MARK[trend.direction]}{' '}
              {trend.direction === 'stable' ? 'ทรงตัว'
                : `${trend.direction === 'increase' ? 'เพิ่มขึ้น' : 'ลดลง'} ${Math.abs(trend.change_pp).toFixed(1)} จุด%`}
              {' '}<span className="helper">({trend.year} เทียบ {trend.baseline_year} · Dynamic World)</span>
            </div>
          )}
          <div className="helper" style={{ marginTop: 6 }}>
            ค่าเรือนยอดเป็นข้อมูล ESA WorldCover ปี {epochYear}
            {epochOffset > 0 && ` (ไม่ใช่ปีที่เลือก — ห่างกัน ${epochOffset} ปี)`} ·
            นับเฉพาะเรือนยอดไม้ยืนต้น จึงต่างจาก “พื้นที่สีเขียว (NDVI &gt; 0.3)”
            ด้านบนที่รวมพืชล้มลุก นาข้าว และสนามหญ้า
            {trend && ' · แนวโน้มมาจาก Dynamic World ซึ่งตรวจไม่เจอเรือนยอดในเมือง'
              + ' ใช้อ่านได้เฉพาะทิศทาง ไม่ใช่ระดับ'}
          </div>
        </>
      )}
    </Note>
  );
}
