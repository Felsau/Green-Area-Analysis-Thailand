// Recommended tree species for the region — name / traits / planting rationale.

// ที่มาของข้อมูลพันธุ์ไม้ — backend แนบ `verification` มาต่อชนิด (ตรวจกับ BGCI
// GlobalTreeSearch / Kew WCVP / GBIF ตอนสร้าง data/tree_species.json)
// แสดงเป็น "ข้อเท็จจริง + ลิงก์" ไม่ใช่คำตัดสินว่าดี/ไม่ดี ให้ผู้ใช้กดดูต้นทางเองได้
// คำตอบจากแคชรุ่นเก่าไม่มีฟิลด์นี้ → ไม่แสดงอะไร (ไม่ใช่เคสผิดพลาด)
function SpeciesSource({ verification }) {
  if (!verification) return null;

  const {
    gbif_url: gbifUrl,
    bgci_native_to_thailand: nativeTh,
    bgci_native_range: nativeRange,
    gbif_records_in_this_region: recordsHere,
  } = verification;

  const origin = nativeTh
    ? 'ไม้ยืนต้นพื้นเมืองของไทย'
    : `ไม้ยืนต้นต่างถิ่น${nativeRange?.length ? ` ถิ่นกำเนิด ${nativeRange.slice(0, 3).join(', ')}` : ''}`;

  return (
    <div className="species__source">
      {origin} (BGCI GlobalTreeSearch)
      {/* นับจากบันทึกการพบจริงที่มีพิกัดในภาคนี้ — 0 ไม่ได้แปลว่าไม่มี แต่แปลว่า
          ยังไม่มีใครบันทึกไว้ จึงเขียนให้ตรงตามนั้น */}
      {typeof recordsHere === 'number' && (
        <> · {recordsHere > 0
          ? `มีบันทึกการพบในภาคนี้ ${recordsHere.toLocaleString('th-TH')} รายการ`
          : 'ยังไม่มีบันทึกการพบพร้อมพิกัดในภาคนี้'} (GBIF)</>
      )}
      {gbifUrl && (
        <> · <a href={gbifUrl} target="_blank" rel="noopener noreferrer">ดูระเบียนต้นทาง</a></>
      )}
    </div>
  );
}

export default function SpeciesSection({ recommendedSpecies }) {
  if (!(recommendedSpecies?.species?.length > 0)) return null;

  return (
    <section className="section">
      <div className="section__head">
        <span className="section__title">พันธุ์ไม้แนะนำ</span>
        {recommendedSpecies.region && (
          <span className="section__meta">
            ภาค{recommendedSpecies.region}
            {/* จัดอันดับโดยคำนึงถึงการใช้ที่ดินเด่นของจุดแนะนำ (backend ส่งมา
                เมื่อสัญญาณชัดพอ — ดู rerank_species_for_spots) */}
            {recommendedSpecies.landuse_context && (
              <> · ที่ดินเด่น: {recommendedSpecies.landuse_context.name_th}</>
            )}
          </span>
        )}
      </div>
      <div>
        {recommendedSpecies.species.map((sp, i) => (
          <div className="species" key={i}>
            <div>
              <span className="species__name">{sp.name_th}</span>
              <span className="species__sci">{sp.scientific}</span>
            </div>
            <div className="species__tags">
              {sp.site_fit && (
                <span className="species__tag" style={{ background: 'var(--good-bg, #e6f4ea)', color: 'var(--good, #1a7f37)', fontWeight: 600 }}>
                  ✓ เหมาะกับพื้นที่นี้
                </span>
              )}
              <span className="species__tag">{sp.purpose}</span>
              <span className="species__tag">สูง {sp.height_m} ม.</span>
              {sp.traits?.map((t, j) => (
                <span key={j} className="species__tag">{t}</span>
              ))}
            </div>
            <div className="species__reason">{sp.site_fit ? `${sp.site_fit} · ${sp.reason}` : sp.reason}</div>
            <SpeciesSource verification={sp.verification} />
          </div>
        ))}
      </div>
      <div className="helper">
        คัดเลือกจากพันธุ์ที่เหมาะกับภูมิอากาศและดินของแต่ละภาค
        {recommendedSpecies.landuse_context && ' · จัดอันดับตามการใช้ที่ดินเด่นของจุดแนะนำ'}
        {' · '}สถานะพันธุ์และการพบจริงตรวจกับ BGCI GlobalTreeSearch, Kew WCVP และ GBIF
      </div>
    </section>
  );
}
