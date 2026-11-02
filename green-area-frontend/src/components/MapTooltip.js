export default function MapTooltip({ tooltip }) {
  return (
    <div role="tooltip" style={{
      position: 'absolute',
      left: tooltip.x + 12, top: tooltip.y - 48,
      background: '#ffffff',
      padding: '6px 10px',
      borderRadius: 3,
      border: '1px solid #cdd1ca',
      boxShadow: '0 2px 6px rgba(0,0,0,0.08)',
      fontSize: 12.5, color: '#1f2421',
      pointerEvents: 'none', zIndex: 1000, whiteSpace: 'nowrap',
      fontFamily: 'inherit',
    }}>
      <div style={{ fontWeight: 600, color: '#0b0d0c' }}>{tooltip.nameTH}</div>
      <div style={{ fontSize: 11, color: '#6b736d', marginTop: 1 }}>
        {tooltip.nameEN}
      </div>
      {tooltip.ndvi != null && (
        <div style={{
          fontSize: 11.5, color: '#1f6f43',
          marginTop: 4, paddingTop: 4,
          borderTop: '1px dotted #e1e3df',
          fontFamily: 'IBM Plex Mono, monospace',
          fontVariantNumeric: 'tabular-nums',
        }}>
          NDVI {tooltip.ndvi.toFixed(3)}
        </div>
      )}
      {tooltip.lst != null && (
        <div style={{
          fontSize: 11.5, color: '#c2410c',
          marginTop: 4, paddingTop: 4,
          borderTop: '1px dotted #e1e3df',
          fontFamily: 'IBM Plex Mono, monospace',
          fontVariantNumeric: 'tabular-nums',
        }}>
          LST {tooltip.lst.toFixed(1)}°C
        </div>
      )}
    </div>
  );
}
