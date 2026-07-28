import { useCallback } from 'react';
import { AVAILABLE_YEARS } from '../constants';

// Map-canvas layer UI: one panel for everything that changes what the map shows —
// แผนที่ฐาน (vector/ภาพถ่ายดาวเทียม) ที่เลือกได้เสมอ แล้วต่อด้วยชั้นข้อมูล raster
// (NDVI/LST/ที่ดิน) + swipe เทียบ 2 ปี ซึ่งมีให้เลือกเมื่อเจาะจังหวัดแล้วเท่านั้น —
// และเส้นแบ่ง swipe พร้อมป้ายปีตอนเปิดโหมดเทียบ
// Purely presentational — all state lives in the raster/swipe hooks passed in.
export default function MapOverlayControls({
  selectedProvinceEN, swipe, raster, enableOverlay, enableSwipe,
  swipeTilesReady, canvasRef, basemap, setBasemap,
}) {
  const { setSplit: setSwipeSplit } = swipe;

  // Drag the swipe divider — convert pointer x to a 0–1 split fraction.
  const startSwipeDrag = useCallback((e) => {
    e.preventDefault();
    const el = canvasRef.current;
    if (!el) return;
    // keep receiving move events even if the pointer leaves the handle (touch)
    try { e.currentTarget.setPointerCapture?.(e.pointerId); } catch { /* unsupported */ }
    // Coalesce pointermove → at most ONE split update per animation frame.
    // pointermove fires ~120Hz; without this every event re-renders the whole
    // app (incl. the sidebar charts), dropping frames. The clip itself is a
    // cheap GPU re-clip (no tile re-fetch), so 60fps tracking is buttery.
    let rafId = 0;
    let pending = null;
    const commit = () => { rafId = 0; if (pending != null) setSwipeSplit(pending); };
    const move = (ev) => {
      const rect = el.getBoundingClientRect();
      pending = Math.max(0.05, Math.min(0.95, (ev.clientX - rect.left) / rect.width));
      if (!rafId) rafId = requestAnimationFrame(commit);
    };
    const end = () => {
      if (rafId) cancelAnimationFrame(rafId);
      if (pending != null) setSwipeSplit(pending);  // commit final position
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', end);
      window.removeEventListener('pointercancel', end);  // touch cancel → no leak
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', end);
    window.addEventListener('pointercancel', end);
  }, [canvasRef, setSwipeSplit]);

  return (
    <>
      <div className="overlay-toggle" role="group" aria-label="ชั้นแผนที่">
        {/* แผนที่ฐาน — เลือกได้ตลอด ไม่ต้องเจาะจังหวัดก่อน จึงอยู่บนสุดของแผง */}
        <span className="overlay-toggle__label">แผนที่ฐาน</span>
        <div className="overlay-toggle__btns">
          <button className="overlay-btn" data-active={basemap === 'map'}
            aria-pressed={basemap === 'map'}
            title="แผนที่ลายเส้น อ่านตัวเลข/สีชั้นข้อมูลได้ชัดที่สุด"
            onClick={() => setBasemap('map')}>แผนที่</button>
          <button className="overlay-btn" data-active={basemap === 'satellite'}
            aria-pressed={basemap === 'satellite'}
            title="ภาพถ่ายดาวเทียมจริง (Esri World Imagery) — เห็นต้นไม้/สิ่งปลูกสร้างรายแปลง"
            onClick={() => setBasemap('satellite')}>ดาวเทียม</button>
        </div>

        {selectedProvinceEN && (<>
          <span className="overlay-toggle__label overlay-toggle__label--sep">ชั้นข้อมูล</span>
          <div className="overlay-toggle__btns">
            <button className="overlay-btn" data-active={!swipe.active && raster.overlay === 'none'}
              onClick={() => { swipe.reset(); raster.clearOverlay(); }}>ปิด</button>
            <button className="overlay-btn" data-active={!swipe.active && raster.overlay === 'ndvi'}
              onClick={() => enableOverlay('ndvi')}>NDVI</button>
            <button className="overlay-btn" data-active={!swipe.active && raster.overlay === 'lst'}
              onClick={() => enableOverlay('lst')}>LST</button>
            <button className="overlay-btn" data-active={!swipe.active && raster.overlay === 'landuse'}
              title="การใช้ที่ดิน 5 ประเภทหลัก (นิยามกรมพัฒนาที่ดิน)"
              onClick={() => enableOverlay('landuse')}>ที่ดิน</button>
          </div>

          <button className="overlay-btn overlay-btn--full" data-active={swipe.active}
            onClick={() => (swipe.active ? swipe.reset() : enableSwipe())}>
            ⇆ เทียบ 2 ปี
          </button>

          {swipe.active && (
            <div className="swipe-control">
              <div className="overlay-toggle__btns">
                <button className="overlay-btn" data-active={swipe.metric === 'ndvi'}
                  onClick={() => swipe.setMetric('ndvi')}>NDVI</button>
                <button className="overlay-btn" data-active={swipe.metric === 'lst'}
                  onClick={() => swipe.setMetric('lst')}>LST</button>
              </div>
              <div className="overlay-toggle__btns">
                <button className="overlay-btn" data-active={swipe.mode === 'split'}
                  onClick={() => swipe.setMode('split')}>ซ้าย-ขวา</button>
                <button className="overlay-btn" data-active={swipe.mode === 'diff'}
                  onClick={() => swipe.setMode('diff')}>Δ ผลต่าง</button>
              </div>
              <div className="swipe-years">
                <label>ซ้าย
                  <select value={swipe.yearA} onChange={(e) => swipe.setYearA(Number(e.target.value))}>
                    {AVAILABLE_YEARS.map(y => <option key={y} value={y}>{y}</option>)}
                  </select>
                </label>
                <label>ขวา
                  <select value={swipe.yearB} onChange={(e) => swipe.setYearB(Number(e.target.value))}>
                    {AVAILABLE_YEARS.map(y => <option key={y} value={y}>{y}</option>)}
                  </select>
                </label>
              </div>
            </div>
          )}

          {(raster.loading || swipe.loading
            || (swipe.active && swipe.mode === 'diff' && swipe.diffTile && !swipeTilesReady.a)
            || (swipe.active && swipe.mode === 'split' && swipe.tileA && swipe.tileB
                && !(swipeTilesReady.a && swipeTilesReady.b)))
            && <span className="overlay-toggle__status">กำลังโหลดภาพ…</span>}
        </>)}
      </div>

      {swipe.active && swipe.mode === 'split' && swipe.tileA && swipe.tileB && (
        <>
          <div className="swipe-divider" style={{ left: `${swipe.split * 100}%` }}>
            <button className="swipe-divider__handle" onPointerDown={startSwipeDrag}
              aria-label="ลากเพื่อเลื่อนเส้นเทียบ">⇆</button>
          </div>
          <span className="swipe-yearbadge swipe-yearbadge--a">{swipe.metric.toUpperCase()} · {swipe.yearA}</span>
          <span className="swipe-yearbadge swipe-yearbadge--b">{swipe.metric.toUpperCase()} · {swipe.yearB}</span>
        </>
      )}
    </>
  );
}
