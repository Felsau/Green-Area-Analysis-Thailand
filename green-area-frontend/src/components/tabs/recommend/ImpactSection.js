// Projected impact of planting — trees / CO₂ / cooling / ecosystem services (i-Tree),
// with per-species breakdown.

// ฿ ย่อ: ≥1 ล้าน → "X.X ล้านบาท" · ต่ำกว่านั้นใส่ , ตามปกติ
function fmtBaht(v) {
  if (v == null) return '–';
  if (v >= 1_000_000) return `${(v / 1_000_000).toLocaleString('th-TH', { maximumFractionDigits: 1 })} ล้านบาท`;
  return `${Math.round(v).toLocaleString('th-TH')} บาท`;
}

export default function ImpactSection({ impact }) {
  if (!(impact && impact.trees_total > 0)) return null;

  const eco = impact.ecosystem_services;
  // Breakdown พื้นที่ควรปลูกตามประเภทการใช้ที่ดิน (LDD 5 ประเภท) — impact จาก
  // cache รุ่นก่อน v8 ยังไม่มี field นี้ · โชว์เฉพาะประเภทที่มีพื้นที่จริง
  const landuseClasses = (impact.plantable_landuse?.classes || [])
    .filter((c) => c.share_pct > 0)
    .sort((a, b) => b.share_pct - a.share_pct);

  return (
    <section className="section">
      <div className="section__head">
        <span className="section__title">ผลกระทบที่คาดการณ์</span>
        <span className="section__meta">ปลูกครบทั้งพื้นที่ priority สูง</span>
      </div>
      <div className="impact">
        <div className="impact__cell">
          <div className="impact__label">ต้นไม้รวม</div>
          <div className="impact__num">{impact.trees_total.toLocaleString()}</div>
          <div className="impact__hint">
            ใน {impact.plantable_area_km2} km² ({impact.plantable_area_ha.toLocaleString()} ไร่)
          </div>
        </div>
        <div className="impact__cell">
          <div className="impact__label">CO₂ ดูดซับ/ปี</div>
          <div className="impact__num">{impact.annual_co2_tonnes.toLocaleString()} <span style={{ fontSize: 12, color: 'var(--ink-3)' }}>ตัน</span></div>
          <div className="impact__hint">
            {impact.annual_co2_tonnes_low != null && impact.annual_co2_tonnes_high != null
              ? `ช่วงจริง (รวมอัตรารอด) ~${impact.annual_co2_tonnes_low.toLocaleString()}–${impact.annual_co2_tonnes_high.toLocaleString()} ตัน · เทียบเท่ารถ ~${impact.equivalent_cars_off_road.toLocaleString()} คัน`
              : `เทียบเท่ารถยนต์ ~${impact.equivalent_cars_off_road.toLocaleString()} คัน`}
          </div>
        </div>
        <div className="impact__cell impact__cell--full">
          <div className="impact__label">อุณหภูมิที่คาดว่าจะลดลง</div>
          <div className="impact__num">{impact.expected_delta_lst_c}°C</div>
          <div className="impact__hint">
            เมื่อ canopy เต็มที่ ~{impact.maturity_years} ปี
          </div>
        </div>
      </div>

      {landuseClasses.length > 0 && (
        <div className="impact" style={{ marginTop: 8 }}>
          <div className="impact__cell impact__cell--full">
            <div className="impact__label">พื้นที่ควรปลูก แยกตามการใช้ที่ดิน</div>
            <div style={{ display: 'flex', height: 8, borderRadius: 4, overflow: 'hidden', margin: '6px 0 4px' }}>
              {landuseClasses.map((c) => (
                <div key={c.code} title={`${c.name_th} ${c.share_pct}%`}
                  style={{ flex: `0 0 ${c.share_pct}%`, background: `#${c.color}` }} />
              ))}
            </div>
            <div className="impact__hint">
              {landuseClasses.map((c) => `${c.name_th} ${c.share_pct}%`).join(' · ')}
            </div>
          </div>
        </div>
      )}

      {eco && eco.annual_value_thb?.total > 0 && (
        <div className="impact" style={{ marginTop: 8 }}>
          <div className="impact__cell impact__cell--full">
            <div className="impact__label">มูลค่าบริการระบบนิเวศรวม/ปี (i-Tree)</div>
            <div className="impact__num">{fmtBaht(eco.annual_value_thb.total)}</div>
            <div className="impact__hint">
              คาดจริง (รวมอัตรารอด) ~{fmtBaht(eco.annual_value_thb_expected)} · คาร์บอน {fmtBaht(eco.annual_value_thb.co2)} · อากาศสะอาด {fmtBaht(eco.annual_value_thb.air_pollution)} · น้ำฝน {fmtBaht(eco.annual_value_thb.stormwater)}
            </div>
          </div>
          <div className="impact__cell">
            <div className="impact__label">ดูดซับมลพิษอากาศ/ปี</div>
            <div className="impact__num">{eco.air_pollution_removal_kg.total.toLocaleString()} <span style={{ fontSize: 12, color: 'var(--ink-3)' }}>kg</span></div>
            <div className="impact__hint">
              PM2.5 {eco.air_pollution_removal_kg.pm25.toLocaleString()} · O₃ {eco.air_pollution_removal_kg.o3.toLocaleString()} · NO₂ {eco.air_pollution_removal_kg.no2.toLocaleString()} kg
            </div>
          </div>
          <div className="impact__cell">
            <div className="impact__label">ดักน้ำฝน/ลดน้ำท่วม/ปี</div>
            <div className="impact__num">{eco.stormwater_runoff_m3.toLocaleString()} <span style={{ fontSize: 12, color: 'var(--ink-3)' }}>m³</span></div>
            <div className="impact__hint">ลดการไหลบ่าของน้ำผิวดิน</div>
          </div>
        </div>
      )}

      {impact.species_breakdown?.length > 0 && (
        <details>
          <summary className="helper" style={{ cursor: 'pointer', userSelect: 'none', padding: '4px 0' }}>
            รายละเอียดต่อพันธุ์ · {impact.species_breakdown.length} ชนิด
          </summary>
          <div style={{ marginTop: 4 }}>
            {impact.species_breakdown.map((sp, i) => (
              <div key={i} className="rank-row">
                <span className="rank-row__num">{String(i + 1).padStart(2, '0')}</span>
                <span className="rank-row__name">{sp.name_th}</span>
                <span className="rank-row__val">{sp.trees.toLocaleString()} ต้น · {sp.kg_co2_per_tree} kg/ต้น</span>
              </div>
            ))}
          </div>
        </details>
      )}

      <div className="helper">
        ค่าประมาณการตามสัมประสิทธิ์มาตรฐาน · ขึ้นกับดิน อายุ ระยะปลูก<br />
        อ้างอิง: {impact.methodology?.sources?.join(' · ') || 'IPCC + Bowler 2010'}
      </div>
    </section>
  );
}
