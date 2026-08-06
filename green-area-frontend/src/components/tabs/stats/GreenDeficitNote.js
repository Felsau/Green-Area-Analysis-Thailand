// พืชพรรณต่อประชากร เทียบ "ค่าอ้างอิง" WHO 9 m²/คน
// ไม่ตัดสินผ่าน/ไม่ผ่าน เพราะตัวชี้วัดนี้นับพืชพรรณทุกชนิด (NDVI > 0.3) ไม่ใช่พื้นที่
// สาธารณะที่เข้าถึงได้ตามนิยาม WHO — เหตุผลเต็มอยู่ใน utils/greenMetric.js
import { Note } from '../../ui/Metric';
import { WHO_REFERENCE_M2, WHO_CAVEAT_SHORT } from '../../../utils/greenMetric';

export default function GreenDeficitNote({ ndviStats }) {
  if (!(ndviStats?.green_area_m2_per_person != null && ndviStats?.population > 0)) return null;

  const current = ndviStats.green_area_m2_per_person;
  const gap = Math.max(0, WHO_REFERENCE_M2 - current);
  const gapKm2 = (gap * ndviStats.population / 1_000_000).toFixed(1);
  const gapRai = Math.round(gap * ndviStats.population / 1600).toLocaleString('th');
  // โทนสีสื่อว่า "ค่าต่ำผิดปกติ" ไม่ใช่ "สอบตก"
  const sev = current < 3 ? 'crit' : current < WHO_REFERENCE_M2 ? 'warn' : 'default';

  return (
    <Note tone={sev} label={`พืชพรรณต่อประชากร · ค่าอ้างอิง WHO ${WHO_REFERENCE_M2} m² ต่อคน`}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
        <span>วัดได้</span>
        <span className="note__num">{current.toFixed(1)} / {WHO_REFERENCE_M2} m²</span>
      </div>
      {gap > 0 ? (
        <div>
          ต่ำกว่าค่าอ้างอิง <span className="note__num">{gap.toFixed(1)} m²</span> ต่อคน
          — เทียบเท่า <span className="note__num">{gapKm2} km²</span> หรือ <span className="note__num">{gapRai} ไร่</span>
        </div>
      ) : (
        <div>
          สูงกว่าค่าอ้างอิง <span className="note__num">{(current - WHO_REFERENCE_M2).toFixed(1)} m²</span> ต่อคน
        </div>
      )}
      <div className="helper" style={{ marginTop: 6 }}>{WHO_CAVEAT_SHORT}</div>
    </Note>
  );
}
