import Accordion from '../../ui/Accordion';
import { AVAILABLE_YEARS } from '../../../constants';

// สัดส่วนการใช้ที่ดิน 5 ประเภทหลัก (ชุมชน/เกษตร/ป่า/น้ำ/เบ็ดเตล็ด — จัดกลุ่มตาม
// นิยามกรมพัฒนาที่ดิน) เป็น stacked bar + แถวต่อประเภท · fetch-on-demand เพราะเป็น
// GEE compute หนัก (~ครึ่งนาทีตอน cache miss) — ปุ่มวิเคราะห์อยู่ในการ์ดเอง
// UI ผูกกับ schema กลาง (classes จาก backend) ไม่รู้จักคลาส Dynamic World →
// เฟส B สลับ provider เป็นข้อมูล LDD ได้โดยไม่แตะไฟล์นี้
export default function LandusePanel({
  scopeLabel, landuseData, landuseLoading, landuseYear,
  setLanduseYear, onAnalyze,
}) {
  const classes = landuseData?.classes || [];
  const shown = classes.filter(c => c.share_pct > 0);

  return (
    <Accordion title="การใช้ที่ดิน · 5 ประเภทหลัก" meta="Dynamic World / 10m"
               defaultOpen={false}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'stretch' }}>
        <select
          className="field" style={{ width: 100 }}
          value={landuseYear}
          onChange={e => setLanduseYear(Number(e.target.value))}
          aria-label="ปีที่วิเคราะห์การใช้ที่ดิน"
        >
          {AVAILABLE_YEARS.map(y => <option key={y} value={y}>{y}</option>)}
        </select>
        <button
          className="btn btn--primary" style={{ flex: 1 }}
          onClick={onAnalyze}
          disabled={landuseLoading}
        >
          {landuseLoading ? 'กำลังวิเคราะห์…' : 'วิเคราะห์สัดส่วน'}
        </button>
      </div>

      {landuseLoading && (
        <div className="helper">กำลังจำแนกการใช้ที่ดินจาก GEE… ครั้งแรกอาจใช้เวลาราวครึ่งนาที</div>
      )}

      {!landuseLoading && !landuseData && (
        <div className="helper">
          สัดส่วนพื้นที่ชุมชน / เกษตร / ป่า / น้ำ / เบ็ดเตล็ด ของ{scopeLabel} ·
          จัดกลุ่มตามนิยามกรมพัฒนาที่ดิน (LDD)
        </div>
      )}

      {!landuseLoading && landuseData && (
        <>
          {/* Stacked bar — สัดส่วนรวมเป็นแถบเดียว อ่านโครงสร้างพื้นที่ได้ทันที */}
          <div
            style={{ display: 'flex', height: 14, overflow: 'hidden', borderRadius: 3,
                     border: '1px solid var(--rule)' }}
            role="img"
            aria-label={`สัดส่วนการใช้ที่ดิน: ${shown.map(c => `${c.name_th} ${c.share_pct}%`).join(', ')}`}
          >
            {shown.map(c => (
              <span key={c.code} title={`${c.name_th} ${c.share_pct}%`}
                    style={{ width: `${c.share_pct}%`, background: `#${c.color}` }} />
            ))}
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 10 }}>
            {classes.map(c => (
              <div key={c.code} style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
                <span style={{ width: 10, height: 10, flex: 'none', borderRadius: 2,
                               background: `#${c.color}`, alignSelf: 'center' }} />
                <span style={{ fontSize: 12.5, color: 'var(--ink-1)' }}>{c.name_th}</span>
                <span style={{ marginLeft: 'auto', fontSize: 12.5, fontWeight: 600,
                               fontFamily: 'var(--mono)', color: 'var(--ink-0)' }}>
                  {c.share_pct}%
                </span>
                <span style={{ fontSize: 11, color: 'var(--ink-3)', fontFamily: 'var(--mono)',
                               width: 88, textAlign: 'right' }}>
                  {c.area_km2.toLocaleString()} km²
                </span>
              </div>
            ))}
          </div>

          <div className="helper" style={{ marginTop: 8 }}>
            แหล่งข้อมูล: {landuseData.source_label} ปี {landuseData.data_year} ·
            จัดกลุ่ม 5 ประเภทหลักตามนิยามกรมพัฒนาที่ดิน · พื้นที่รวม{' '}
            {landuseData.total_km2?.toLocaleString()} km²
          </div>
        </>
      )}
    </Accordion>
  );
}
