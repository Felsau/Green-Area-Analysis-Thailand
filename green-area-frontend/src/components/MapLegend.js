// Color key for the province choropleth (NDVI greenness) drawn on the map.
// Mirrors the buckets in colorUtils.js (getNdviRgba).
const NDVI_STOPS = [
  { color: '#22c55e', label: 'หนาแน่นมาก', range: '≥ 0.60' },
  { color: '#4ade80', label: 'หนาแน่น',     range: '0.45–0.60' },
  { color: '#86efac', label: 'ปานกลาง',      range: '0.30–0.45' },
  { color: '#bbf7d0', label: 'น้อย',         range: '< 0.30' },
];

// LST buckets — mirrors getLstRgba (ใช้ตอน time-lapse LST แทนสเกล NDVI)
const LST_STOPS = [
  { color: '#ef4444', label: 'ร้อนมาก', range: '≥ 38°C' },
  { color: '#f97316', label: 'ร้อน',     range: '33–38°C' },
  { color: '#fbbf24', label: 'ปานกลาง',  range: '28–33°C' },
  { color: '#60a5fa', label: 'เย็น',     range: '< 28°C' },
];

export default function MapLegend({ overlay = 'none', tileInfo = null, choropleth = 'ndvi' }) {
  // Land use overlay is categorical (5 ประเภทหลักตามนิยาม LDD) — swatch rows per
  // category instead of a gradient. Checked before the gradient branch because
  // the landuse tile response also carries a palette.
  if (overlay !== 'none' && tileInfo?.kind === 'landuse' && tileInfo?.categories?.length) {
    return (
      <div className="legend-card" aria-label="คำอธิบายประเภทการใช้ที่ดิน">
        <div className="legend-card__title">การใช้ที่ดิน · 5 ประเภทหลัก</div>
        {tileInfo.categories.map(c => (
          <div className="legend-card__row" key={c.code}>
            <span className="legend-card__swatch" style={{ background: `#${c.color}` }} />
            <span className="legend-card__label">{c.name_th}</span>
            <span className="legend-card__range">{c.code}</span>
          </div>
        ))}
        <div className="legend-card__row">
          <span className="legend-card__range">
            จัดกลุ่มตามนิยาม LDD · {tileInfo.source_label || 'Dynamic World'} · {tileInfo.data_year}
          </span>
        </div>
      </div>
    );
  }

  // When a raster overlay is active, show a continuous gradient scale instead
  // of the choropleth buckets.
  if (overlay !== 'none' && tileInfo?.palette?.length) {
    const gradient = `linear-gradient(to right, ${tileInfo.palette.map(c => `#${c}`).join(', ')})`;
    const isDiff = !!tileInfo.diff;
    const isLst = tileInfo.kind === 'lst' || tileInfo.kind === 'lst-diff';
    const unit = isLst ? '°C' : '';

    // Difference map → diverging scale centred on 0 (− loss/cooler … + gain/warmer)
    if (isDiff) {
      return (
        <div className="legend-card" aria-label="คำอธิบายแผนที่ผลต่าง">
          <div className="legend-card__title">
            ผลต่าง {isLst ? 'LST' : 'NDVI'} · {tileInfo.year_a}→{tileInfo.year_b}
          </div>
          <div className="legend-gradient" style={{ background: gradient }} />
          <div className="legend-gradient__scale">
            <span>{tileInfo.min}{unit}</span>
            <span>0</span>
            <span>+{tileInfo.max}{unit}</span>
          </div>
        </div>
      );
    }

    return (
      <div className="legend-card" aria-label="คำอธิบาย raster overlay">
        <div className="legend-card__title">
          {isLst ? 'อุณหภูมิผิว · LST' : 'พืชพรรณ · NDVI'} (raster)
        </div>
        <div className="legend-gradient" style={{ background: gradient }} />
        <div className="legend-gradient__scale">
          <span>{tileInfo.min}{unit}</span>
          <span>{tileInfo.max}{unit}</span>
        </div>
      </div>
    );
  }

  const isLstChoropleth = choropleth === 'lst';
  return (
    <div className="legend-card"
         aria-label={isLstChoropleth ? 'คำอธิบายสีอุณหภูมิผิว' : 'คำอธิบายสีพื้นที่สีเขียว'}>
      <div className="legend-card__title">
        {isLstChoropleth ? 'อุณหภูมิผิว · LST' : 'พื้นที่สีเขียว · NDVI'}
      </div>
      {(isLstChoropleth ? LST_STOPS : NDVI_STOPS).map(s => (
        <div className="legend-card__row" key={s.range}>
          <span className="legend-card__swatch" style={{ background: s.color }} />
          <span className="legend-card__label">{s.label}</span>
          <span className="legend-card__range">{s.range}</span>
        </div>
      ))}
      <div className="legend-card__row">
        <span className="legend-card__swatch legend-card__swatch--empty" />
        <span className="legend-card__label">ยังไม่มีข้อมูล</span>
        <span className="legend-card__range">—</span>
      </div>
    </div>
  );
}
