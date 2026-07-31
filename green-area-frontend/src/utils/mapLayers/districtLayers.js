// District-level map — FLAT NDVI choropleth + on-map Thai labels.
// (3D extrusion is kept for the province/national hero view only; at district
// level a clean 2D choropleth reads far better — crisp boundaries, clear
// "no data" state, and labels for identification.)
import { GeoJsonLayer, IconLayer } from '@deck.gl/layers';
import * as turf from '@turf/turf';
import { getNdviRgba } from '../../colorUtils';

// Below this zoom a whole province fits in a tiny patch of screen, so the
// per-district pills pile into an unreadable cluster — hide them entirely.
// Every Thai province fits at zoom > 7 (see selectProvince fly-to in App.js),
// so labels always appear once you've drilled into one; they only drop out when
// you manually zoom back out toward the regional/national view.
const LABEL_MIN_ZOOM = 7;

// On-screen pill height (px). Fixed size (not zoom-scaled) keeps labels legible
// and makes the de-clutter overlap test below exact.
const LABEL_PX = 24;
const LABEL_PX_SELECTED = 28;
const LABEL_GAP = 3;            // extra px so kept pills never touch

// Web-Mercator world-pixel position at a given zoom (deck.gl uses a 512px tile).
// The pixel DELTA between two of these equals the on-screen distance between the
// points (bearing/pitch aside) and is independent of pan — so an overlap test in
// this space is stable and only needs recomputing when the zoom changes.
function worldXY([lng, lat], zoom) {
  const scale = 512 * 2 ** zoom;
  const x = ((lng + 180) / 360) * scale;
  const s = Math.sin((lat * Math.PI) / 180);
  const y = (0.5 - Math.log((1 + s) / (1 - s)) / (4 * Math.PI)) * scale;
  return [x, y];
}

// Pick which district labels to draw: walk features by priority (selected first,
// then larger districts, which have the most room) and keep a pill only if its
// box doesn't overlap one already kept. Hides just the colliding ones — every
// non-overlapping label still shows.
function declutterLabels(features, zoom, selectedEN, iconFor) {
  const sized = features.map((f) => {
    const selected = f.properties.name === selectedEN;
    const h = selected ? LABEL_PX_SELECTED : LABEL_PX;
    const icon = iconFor(f, selected);
    let pos = null;
    try { pos = worldXY(turf.centroid(f).geometry.coordinates, zoom); } catch { /* skip */ }
    let area = 0;
    try { area = turf.area(f); } catch { /* keep 0 */ }
    return {
      f, pos,
      halfW: (h * (icon.width / icon.height)) / 2 + LABEL_GAP,
      halfH: h / 2 + LABEL_GAP,
      priority: selected ? Infinity : area,
    };
  }).filter((s) => s.pos);

  sized.sort((a, b) => b.priority - a.priority);

  const kept = [];
  const out = [];
  for (const s of sized) {
    const [x, y] = s.pos;
    const clash = kept.some((k) =>
      Math.abs(x - k.x) < s.halfW + k.halfW &&
      Math.abs(y - k.y) < s.halfH + k.halfH);
    if (!clash) {
      kept.push({ x, y, halfW: s.halfW, halfH: s.halfH });
      out.push(s.f);
    }
  }
  return out;
}

// Thai amphoe name for the on-map label (keep "เมือง…" prefix — it's informative).
// English fallback: drop generic prefixes + split CamelCase.
function labelFor(props) {
  const th = props.name_th;
  if (th && th !== props.name) return th;
  return (props.name || '')
    .replace(/^(K\.|Amphoe |Khet |Muang |Mueang )/, '')
    .replace(/([a-z])([A-Z])/g, '$1 $2');
}

// ── Canvas-rendered labels ──────────────────────────────────────────────────
// deck.gl's TextLayer lays glyphs out one-by-one by advance width and can't do
// complex-script shaping: Thai upper/lower vowels and tone marks get pushed
// sideways instead of stacking on their base consonant, and the SDF atlas adds
// a soft blur. We instead pre-render each label to a small high-DPI canvas with
// the browser's own text engine (correct Thai shaping) and place it as an
// IconLayer icon — crisp, correctly-stacked, with a rounded pill baked in.
const LABEL_FONT_FAMILY = 'Sarabun, "Noto Sans Thai", sans-serif';
const _iconCache = new Map();

// Warm the webfont so the very first canvas paint uses Sarabun, not a fallback.
if (typeof document !== 'undefined' && document.fonts?.load) {
  document.fonts.load('600 32px Sarabun').catch(() => {});
}

function roundRectPath(g, x, y, w, h, r) {
  const rr = Math.min(r, w / 2, h / 2);
  g.beginPath();
  g.moveTo(x + rr, y);
  g.arcTo(x + w, y, x + w, y + h, rr);
  g.arcTo(x + w, y + h, x, y + h, rr);
  g.arcTo(x, y + h, x, y, rr);
  g.arcTo(x, y, x + w, y, rr);
  g.closePath();
}

function labelIcon(text, selected) {
  // Re-render once the webfont becomes available (key flips → cache miss).
  const fontReady = typeof document !== 'undefined'
    && !!document.fonts?.check?.('600 32px Sarabun');
  const key = `${text}|${selected ? 1 : 0}|${fontReady ? 1 : 0}`;
  const cached = _iconCache.get(key);
  if (cached) return cached;

  const dpr = Math.min(
    typeof window !== 'undefined' ? window.devicePixelRatio || 1 : 1, 3);
  const fontPx = 30;                 // logical text size inside the pill
  const padX = 13, padY = 7, radius = 9;
  const font = `600 ${fontPx}px ${LABEL_FONT_FAMILY}`;

  const c = document.createElement('canvas');
  const g = c.getContext('2d');
  g.font = font;
  const textW = Math.ceil(g.measureText(text).width);
  const w = textW + padX * 2;
  const h = fontPx + padY * 2;

  c.width = Math.ceil(w * dpr);
  c.height = Math.ceil(h * dpr);
  g.scale(dpr, dpr);
  g.font = font;
  g.textAlign = 'center';
  g.textBaseline = 'middle';

  // Rounded pill — same palette as the old TextLayer background, plus a hairline
  // border so labels separate from the choropleth fill underneath.
  roundRectPath(g, 0.75, 0.75, w - 1.5, h - 1.5, radius);
  g.fillStyle = selected ? 'rgba(220,240,255,0.95)' : 'rgba(255,255,255,0.93)';
  g.fill();
  g.lineWidth = selected ? 1.6 : 1;
  g.strokeStyle = selected ? 'rgba(26,115,232,0.95)' : 'rgba(70,92,70,0.30)';
  g.stroke();

  g.fillStyle = selected ? '#0f500a' : '#1e1e1e';
  g.fillText(text, w / 2, h / 2 + 1);

  const icon = { url: c.toDataURL(), width: c.width, height: c.height, id: key };
  _iconCache.set(key, icon);
  return icon;
}

// Neutral fill for districts that have no NDVI cached yet — matches the
// "ยังไม่มีข้อมูล" swatch in MapLegend so partial coverage reads as
// "not computed yet", not "broken".
const NO_DATA_FILL = [225, 229, 226, 90];

export const districtLayers = (ctx) => {
  const {
    showingDistricts, districtFeatures, districtCache,
    selectedProvinceEN, selectedDistrictEN, rasterActive, drawActive, satelliteBase,
    setSelectedDistrict, setSelectedDistrictEN, setDistrictArea,
    setSidebarTab, fetchDistrictNDVI, setTooltip, zoom = 6, selectedYear,
  } = ctx;
  if (!showingDistricts) return [];

  const cacheKey = (f) => `${f.properties.province}::${f.properties.name}`;

  // Below LABEL_MIN_ZOOM the whole province is a tiny blob → no labels at all.
  // Otherwise keep every label that doesn't overlap a higher-priority one.
  const labelData = zoom >= LABEL_MIN_ZOOM
    ? declutterLabels(
        districtFeatures, zoom, selectedDistrictEN,
        (f, selected) => labelIcon(labelFor(f.properties), selected))
    : [];

  return [
    new GeoJsonLayer({
      id: 'thailand-districts',
      data: { type: 'FeatureCollection', features: districtFeatures },
      extruded: false,            // flat choropleth
      stroked: true,
      filled: true,
      getFillColor: (f) => {
        // raster overlay/swipe on → transparent so the pixel data shows through
        if (rasterActive) return [0, 0, 0, 0];
        if (f.properties.name === selectedDistrictEN) return [26, 115, 232, satelliteBase ? 130 : 230];
        const ndvi = districtCache[cacheKey(f)];
        // ภาพถ่ายดาวเทียม → ย้อมบาง ๆ พอให้เทียบระดับกันได้ · อำเภอที่ยังไม่มีค่า
        // ปล่อยโปร่งไปเลย ให้ภาพจริงเป็นตัวบอกว่ายังไม่ได้คำนวณ (ตรงกับคีย์สีในตำนาน)
        if (satelliteBase) return ndvi != null ? getNdviRgba(ndvi, 115) : [0, 0, 0, 0];
        return ndvi != null ? getNdviRgba(ndvi, 210) : NO_DATA_FILL;
      },
      getLineColor: (f) => {
        if (f.properties.name === selectedDistrictEN) return [26, 115, 232, 255];
        // crisp neutral boundary — visible on both green fills and the basemap;
        // a touch lighter when a raster or satellite imagery sits underneath
        return (rasterActive || satelliteBase) ? [255, 255, 255, 150] : [70, 92, 70, 200];
      },
      getLineWidth: (f) => (f.properties.name === selectedDistrictEN ? 2.5 : 0.8),
      lineWidthUnits: 'pixels',
      lineWidthMinPixels: 0.8,
      // draw mode → ปิด picking เพื่อให้คลิกบนแผนที่ปักหมุดแทนการเลือกอำเภอ
      pickable: !drawActive,
      autoHighlight: !rasterActive && !drawActive,
      highlightColor: [26, 115, 232, 90],
      onClick: ({ object }) => {
        if (!object) return;
        const districtEN = object.properties.name;
        const districtTH = object.properties.name_th || districtEN;
        setSelectedDistrict(districtTH);     // shown in sidebar
        setSelectedDistrictEN(districtEN);   // used for API calls
        setDistrictArea((turf.area(object) / 1_000_000).toFixed(2));
        setSidebarTab('stats');
        fetchDistrictNDVI(selectedProvinceEN, districtEN, selectedYear);
      },
      onHover: ({ object, x, y }) => {
        setTooltip(object ? {
          x, y,
          nameTH: object.properties.name_th || object.properties.name,
          nameEN: `${selectedProvinceEN} › ${object.properties.name}`,
          ndvi: districtCache[`${object.properties.province}::${object.properties.name}`],
        } : null);
      },
      updateTriggers: {
        getFillColor: [districtCache, selectedDistrictEN, rasterActive, satelliteBase],
        getLineColor: [selectedDistrictEN, rasterActive, satelliteBase],
        getLineWidth: selectedDistrictEN,
      },
    }),

    // labelData is the de-cluttered subset (see above) — only non-overlapping
    // pills, and nothing at all when zoomed too far out.
    labelData.length && new IconLayer({
      id: 'thailand-district-labels',
      data: labelData,
      getPosition: (f) => {
        try { return turf.centroid(f).geometry.coordinates; }
        catch { return [0, 0]; }
      },
      getIcon: (f) => labelIcon(
        labelFor(f.properties), f.properties.name === selectedDistrictEN),
      // Fixed on-screen pill height (px) — matches the de-clutter overlap test.
      getSize: (f) => (f.properties.name === selectedDistrictEN
        ? LABEL_PX_SELECTED : LABEL_PX),
      sizeUnits: 'pixels',
      billboard: true,
      alphaCutoff: -1,            // keep antialiased pill/text edges
      pickable: false,
      parameters: { depthTest: false },
      updateTriggers: {
        getIcon: selectedDistrictEN,
        getSize: selectedDistrictEN,
      },
    }),
  ].filter(Boolean);
};
