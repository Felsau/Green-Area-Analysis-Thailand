// Recommended tree species for the region — name / traits / planting rationale.
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
          </div>
        ))}
      </div>
      <div className="helper">
        คัดเลือกจากพันธุ์ที่เหมาะกับภูมิอากาศและดินของแต่ละภาค
        {recommendedSpecies.landuse_context && ' · จัดอันดับตามการใช้ที่ดินเด่นของจุดแนะนำ'}
      </div>
    </section>
  );
}
