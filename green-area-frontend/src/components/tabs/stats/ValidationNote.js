// NFR-08 — ความถูกต้องของ "พื้นที่สีเขียว (NDVI)" เทียบ ESA WorldCover
//
// เจตนาของบล็อกนี้คือ *บอกความเชื่อมั่นของตัวเลข* แบบเดียวกับ DataQualityNote
// ไม่ใช่ตัดสินว่าจังหวัดไหน "ข้อมูลผิด" — จากการวัดจริงทั้ง 77 จังหวัด (REQUIREMENTS
// §5.1) ความต่างที่พบอธิบายได้ครบด้วยกลไกเชิงนิยาม 2 แบบที่ทิศทางตรงข้ามกัน:
//   error > 0  เขตเมือง — NDVI จับหญ้า/ต้นไม้แทรกอาคาร แต่ WorldCover ตัดสินทั้ง
//              pixel เป็นสิ่งปลูกสร้าง
//   error < 0  เขตนาข้าว — WorldCover นับ Cropland ตลอดปี แต่ median NDVI รายปี
//              ตกต่ำกว่า 0.3 ช่วงพักดิน/น้ำท่วมขัง
// จึงจงใจ **ไม่ใช้ป้าย "ไม่ผ่าน"** กับจังหวัดที่เกิน ±10 จุด% — ใช้คำว่า "ต่างมาก"
// แล้วอธิบายต้นเหตุแทน · backend คำนวณ error/breakdown/note มาให้แล้ว ที่นี่จัดรูปแบบ
import { Note } from '../../ui/Metric';

// ทิศทางของความต่างบอกกลไกได้ตรง ๆ — เขียนให้ผู้ใช้เห็นความหมาย ไม่ใช่แค่เครื่องหมาย
const KIND_TEXT = {
  false_negative: 'WorldCover นับเป็นสีเขียว แต่ NDVI ไม่นับ',
  false_positive: 'NDVI นับเป็นสีเขียว แต่ WorldCover ไม่นับ',
};

export default function ValidationNote({ validation, compact = false }) {
  if (!validation?.available) return null;

  const {
    ndvi_green_pct: ndviPct, worldcover_green_pct: wcPct, error_pp: errorPp,
    target_pp: target, within_target: within, worldcover_epoch_year: epochYear,
    year, breakdown,
  } = validation;

  const magnitude = Math.abs(errorPp);
  const higher = errorPp > 0;
  const top = breakdown?.dominant;

  return (
    <Note tone={within ? 'default' : 'warn'}
          label={`ความถูกต้องเทียบ ESA WorldCover (±${target} จุด%)`}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, marginBottom: 6 }}>
        <span>
          ต่างกัน <strong>{magnitude.toFixed(1)} จุด%</strong>
          {' '}<span className="helper">({within ? 'อยู่ในเกณฑ์' : 'ต่างมาก'})</span>
        </span>
        <span className="note__num">{ndviPct.toFixed(1)}% / {wcPct.toFixed(1)}%</span>
      </div>

      <div>
        NDVI วัดได้ <span className="note__num">{ndviPct.toFixed(1)}%</span>{' '}
        {higher ? 'สูงกว่า' : 'ต่ำกว่า'} WorldCover ที่{' '}
        <span className="note__num">{wcPct.toFixed(1)}%</span>
      </div>

      {top && (
        <div style={{ marginTop: 6 }}>
          ต้นเหตุหลัก: <strong>{top.name}</strong>{' '}
          <span className="note__num">{top.pp.toFixed(1)} จุด%</span>
          <div className="helper">{KIND_TEXT[top.kind]}</div>
        </div>
      )}

      {!compact && (
        <>
          {breakdown?.by_class?.length > 1 && (
            <div style={{ marginTop: 6 }}>
              <div className="label">แยกตามประเภทพื้นที่</div>
              {breakdown.by_class.slice(0, 4).map(c => (
                <div key={`${c.kind}_${c.code}`}
                     style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
                  <span>{c.name}</span>
                  <span className="note__num">
                    {c.kind === 'false_positive' ? '+' : '−'}{c.pp.toFixed(1)}
                  </span>
                </div>
              ))}
            </div>
          )}
          <div className="helper" style={{ marginTop: 6 }}>
            ความต่างนี้เป็นเรื่องของ<strong>นิยาม</strong> ไม่ใช่ความผิดพลาดของการวัด —
            NDVI วัดพืชพรรณที่เขียวจริงในช่วงเวลานั้น (จึงตอบเกณฑ์ WHO m²/คน ได้ตรง)
            ส่วน WorldCover จำแนก<em>ประเภทการใช้ที่ดิน</em> เช่นนับนาข้าวเป็นพื้นที่
            เกษตรตลอดปีแม้ช่วงพักดิน และตัดสินทั้ง pixel เมืองที่ปนต้นไม้กับอาคารเป็น
            สิ่งปลูกสร้าง
            {epochYear !== year &&
              ` · ค่าอ้างอิงเป็นข้อมูล WorldCover ปี ${epochYear} (ไม่ใช่ปี ${year} ที่เลือก)`}
          </div>
        </>
      )}
    </Note>
  );
}
