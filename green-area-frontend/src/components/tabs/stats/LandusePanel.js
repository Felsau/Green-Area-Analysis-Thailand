import Accordion from '../../ui/Accordion';
import { AVAILABLE_YEARS, LANDUSE_SOURCES, LDD_PROVINCES } from '../../../constants';

// สัดส่วนการใช้ที่ดิน 5 ประเภทหลัก (ชุมชน/เกษตร/ป่า/น้ำ/เบ็ดเตล็ด — จัดกลุ่มตาม
// นิยามกรมพัฒนาที่ดิน) เป็น stacked bar + แถวต่อประเภท · fetch-on-demand เพราะเป็น
// GEE compute หนัก (~ครึ่งนาทีตอน cache miss) — ปุ่มวิเคราะห์อยู่ในการ์ดเอง
// UI ผูกกับ schema กลาง (classes จาก backend) ไม่รู้จักคลาสของ provider →
// สลับแหล่งข้อมูล Dynamic World ↔ LDD ได้ที่ toggle (โผล่เฉพาะจังหวัดที่มีข้อมูล LDD)
// แหล่ง LDD แนบ `detail` รหัสละเอียด 96 ประเภท → แสดงต่อท้าย 5 ประเภทหลัก
export default function LandusePanel({
  scopeLabel, provinceEN, landuseData, landuseLoading, landuseYear, landuseSource,
  setLanduseYear, setLanduseSource, onAnalyze,
}) {
  const classes = landuseData?.classes || [];
  const shown = classes.filter(c => c.share_pct > 0);
  const detail = landuseData?.detail || [];

  const canUseLdd = LDD_PROVINCES.includes(provinceEN);
  const isLdd = landuseSource === 'ldd';

  return (
    <Accordion title="การใช้ที่ดิน · 5 ประเภทหลัก"
               meta={isLdd ? 'LDD 1:25,000' : 'Dynamic World / 10m'}
               defaultOpen={false}>
      {/* Source toggle — โผล่เฉพาะจังหวัดที่มีข้อมูล LDD (ไม่งั้นคงไว้ที่ Dynamic World) */}
      {canUseLdd && (
        <div role="group" aria-label="แหล่งข้อมูลการใช้ที่ดิน"
             style={{ display: 'flex', border: '1px solid var(--rule)', borderRadius: 6,
                      overflow: 'hidden', marginBottom: 8 }}>
          {LANDUSE_SOURCES.map((s, i) => {
            const active = landuseSource === s.id;
            return (
              <button key={s.id} type="button" title={s.hint}
                onClick={() => setLanduseSource(s.id)}
                aria-pressed={active}
                style={{
                  flex: 1, padding: '6px 10px', fontSize: 12, lineHeight: 1.2,
                  cursor: 'pointer', border: 'none',
                  borderLeft: i ? '1px solid var(--rule)' : 'none',
                  background: active ? 'var(--accent)' : 'transparent',
                  color: active ? '#fff' : 'var(--ink-2)',
                  fontWeight: active ? 600 : 500,
                }}>
                {s.label}
              </button>
            );
          })}
        </div>
      )}

      <div style={{ display: 'flex', gap: 8, alignItems: 'stretch' }}>
        {isLdd ? (
          // LDD เป็น edition เดียว (พ.ศ. 2566) ไม่มีรายปี → แสดงป้ายปีคงที่แทน dropdown
          <div className="field" title="ข้อมูล LDD ฉบับปี พ.ศ. 2566"
               style={{ width: 100, display: 'flex', alignItems: 'center',
                        justifyContent: 'center', fontSize: 12.5, color: 'var(--ink-2)',
                        fontFamily: 'var(--mono)' }}>
            พ.ศ. 2566
          </div>
        ) : (
          <select
            className="field" style={{ width: 100 }}
            value={landuseYear}
            onChange={e => setLanduseYear(Number(e.target.value))}
            aria-label="ปีที่วิเคราะห์การใช้ที่ดิน"
          >
            {AVAILABLE_YEARS.map(y => <option key={y} value={y}>{y}</option>)}
          </select>
        )}
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
          {isLdd && ' · ข้อมูลราชการ 1:25,000 (มีรายละเอียด 96 ประเภท)'}
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

          {/* รายละเอียดประเภทที่ดิน (เฉพาะ LDD) — สิ่งที่ Dynamic World ให้ไม่ได้ */}
          {detail.length > 0 && (
            <div style={{ marginTop: 12, paddingTop: 10, borderTop: '1px solid var(--rule)' }}>
              <div className="helper" style={{ marginBottom: 6 }}>
                ประเภทที่ดินละเอียด · พื้นที่มากสุด {detail.length} อันดับ
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
                {detail.map(d => (
                  <div key={d.code} style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
                    <span style={{ width: 8, height: 8, flex: 'none', borderRadius: 2,
                                   background: `#${d.color}`, alignSelf: 'center' }} />
                    <span style={{ fontSize: 12, color: 'var(--ink-1)' }}>{d.name_th}</span>
                    <span style={{ fontSize: 10.5, color: 'var(--ink-3)',
                                   fontFamily: 'var(--mono)' }}>{d.code}</span>
                    <span style={{ marginLeft: 'auto', fontSize: 12, fontWeight: 600,
                                   fontFamily: 'var(--mono)', color: 'var(--ink-0)' }}>
                      {d.share_pct}%
                    </span>
                    <span style={{ fontSize: 10.5, color: 'var(--ink-3)', fontFamily: 'var(--mono)',
                                   width: 80, textAlign: 'right' }}>
                      {d.area_km2.toLocaleString()} km²
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          <div className="helper" style={{ marginTop: 8 }}>
            แหล่งข้อมูล: {landuseData.source_label} ·{' '}
            {isLdd
              ? `ฉบับปี พ.ศ. ${landuseData.data_year} (ค.ศ. ${landuseData.data_year_ce}) · พื้นที่จาก polygon จริง`
              : `ปี ${landuseData.data_year} · จัดกลุ่ม 5 ประเภทหลักตามนิยาม LDD`}{' '}
            · พื้นที่รวม {landuseData.total_km2?.toLocaleString()} km²
          </div>
        </>
      )}
    </Accordion>
  );
}
