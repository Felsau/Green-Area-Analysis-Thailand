import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import DeckGL from '@deck.gl/react';
import { FlyToInterpolator } from '@deck.gl/core';
import Map from 'react-map-gl/maplibre';
import 'maplibre-gl/dist/maplibre-gl.css';
import './App.css';

import * as turf from '@turf/turf';
import { MAP_STYLE, MAP_STYLE_DARK, INITIAL_VIEW_STATE, PROVINCE_TH, CURRENT_YEAR } from './constants';
import { useNdviCache }    from './hooks/useNdviCache';
import { useProvinceData } from './hooks/useProvinceData';
import { useDistrictData } from './hooks/useDistrictData';
import { useTrendData }    from './hooks/useTrendData';
import { useCompareData }  from './hooks/useCompareData';
import { useRankingData }  from './hooks/useRankingData';
import { useRecommendData } from './hooks/useRecommendData';
import { useTimelapseData } from './hooks/useTimelapseData';
import { useCoolingData } from './hooks/useCoolingData';
import { useLanduseData } from './hooks/useLanduseData';
import { useCoverageCompute } from './hooks/useCoverageCompute';
import { useRasterOverlay } from './hooks/useRasterOverlay';
import { useSwipeCompare } from './hooks/useSwipeCompare';
import { useAreaTools }   from './hooks/useAreaTools';
import { useTheme }          from './hooks/useTheme';
import { useLandingGate }    from './hooks/useLandingGate';
import { useCanvasViewport } from './hooks/useCanvasViewport';
import { useMapLayers }      from './hooks/useMapLayers';
import Sidebar    from './components/Sidebar';
import AppHeader  from './components/AppHeader';
import MapTooltip from './components/MapTooltip';
import MapLegend  from './components/MapLegend';
import MapOverlayControls from './components/MapOverlayControls';
import Toast      from './components/Toast';
import TimelapsePlayer from './components/TimelapsePlayer';
import AboutModal from './components/AboutModal';
import Landing from './components/Landing';
import DrawControl from './components/DrawControl';
import SavedAreasPanel from './components/SavedAreasPanel';
import { pushError } from './utils/toast';

// Sidebar tab ids — whitelist for the ?tab= deep-link param (mirrors Sidebar TABS)
const TAB_IDS = ['stats', 'trend', 'cooling', 'compare', 'recommend'];

function App() {
  const [thailandData, setThailandData] = useState(null);
  const [loading, setLoading]           = useState(true);
  const [viewState, setViewState]       = useState(INITIAL_VIEW_STATE);
  const [tooltip, setTooltip]           = useState(null);
  const [sidebarTab, setSidebarTab]     = useState('stats');
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [showAbout, setShowAbout]       = useState(false);
  const { theme, toggleTheme } = useTheme();

  // Landing gate — shown once per browser session. Shared deep-links
  // (?p= ?d= ?tab= ?year=) must keep opening the dashboard directly.
  const { showLanding, enterDashboard, goToLanding } = useLandingGate();

  const { ndviCache, setNdviCache } = useNdviCache();
  const province = useProvinceData({ setNdviCache });
  const district = useDistrictData();
  const trend    = useTrendData();
  const compare  = useCompareData();
  const ranking  = useRankingData();
  const recommend = useRecommendData();
  const timelapse = useTimelapseData();
  const cooling = useCoolingData();
  const landuse = useLanduseData();
  const coverage = useCoverageCompute({ setNdviCache });
  const raster = useRasterOverlay();
  const swipe = useSwipeCompare();
  // วาดพื้นที่เอง + บันทึกพื้นที่ — orchestration อยู่ใน useAreaTools
  const {
    draw, savedAreas, savedPanelOpen, setSavedPanelOpen,
    handleMapClick, resolveProvince, toggleSavedPanel, handleSaveArea, handleLoadSaved,
  } = useAreaTools({ thailandData, setViewState });
  // are BOTH swipe years' tiles fully rendered? (used to show "loading" until
  // ready, so dragging happens on cached tiles = instant GPU re-clip)
  const [swipeTilesReady, setSwipeTilesReady] = useState({ a: false, b: false });
  const onSwipeTileLoad = useCallback(
    (side) => setSwipeTilesReady(s => (s[side] ? s : { ...s, [side]: true })), []);

  // Map canvas size → geographic viewport bounds (drives the swipe clip).
  const { canvasRef, viewportBounds } = useCanvasViewport(viewState);

  const effectiveNdviCache = timelapse.timelapseCache || ndviCache;
  // time-lapse LST เล่นอยู่ → ค่าใน cache เป็น °C — provinceLayer ใช้สลับสเกลสี
  const timelapseMetric = timelapse.timelapseCache ? timelapse.metric : null;

  // Province list for the search/select box — Thai + English, sorted by Thai name.
  const provinceList = useMemo(
    () => Object.entries(PROVINCE_TH)
      .map(([en, th]) => ({ en, th }))
      .sort((a, b) => a.th.localeCompare(b.th, 'th')),
    []
  );

  // Reflect the current selection in the tab title — clearer bookmarks and a
  // readable name for shared deep-links (?p=…).
  useEffect(() => {
    const base = 'Green Area Analysis · Thailand';
    const scope = [province.selectedProvince, district.selectedDistrict].filter(Boolean).join(' · ');
    document.title = scope ? `${scope} — ${base}` : base;
  }, [province.selectedProvince, district.selectedDistrict]);

  // Raster/swipe overlays read poorly over the dark basemap (the blue→red /
  // green palettes get muddied). Force the light, neutral basemap whenever an
  // overlay is shown so the data colours stay true — regardless of theme.
  const overlayShown = !!raster.tileInfo?.tile_url || swipe.active;
  const mapStyle = overlayShown ? MAP_STYLE
                 : theme === 'dark' ? MAP_STYLE_DARK : MAP_STYLE;

  useEffect(() => {
    fetch('/thailand.json')
      .then(r => r.json())
      .then(data => { setThailandData(data); setLoading(false); })
      .catch(() => {
        setLoading(false);
        pushError('โหลดขอบเขตจังหวัดไม่สำเร็จ — รีเฟรชหน้าเว็บใหม่');
      });
  }, []);

  // Deep-link: restore province (?p=), district (?d=), sidebar tab (?tab=) and
  // ranking year (?year=) from the URL once the map data is ready, then keep
  // the URL in sync for shareable links.
  const didInitFromUrl = useRef(false);
  const [urlReady, setUrlReady] = useState(false);
  // district restore ต้องรอ thailand_districts.json โหลดเสร็จ (async หลัง
  // selectProvince) — พักไว้ใน ref แล้วให้ effect ด้านล่างเลือกเมื่อข้อมูลมา
  const pendingDistrictRef = useRef(null);
  useEffect(() => {
    if (didInitFromUrl.current || !thailandData) return;
    didInitFromUrl.current = true;
    const params = new URLSearchParams(window.location.search);
    const year = Number(params.get('year'));
    if (year && !Number.isNaN(year)) ranking.setRankingYear(year);
    const tab = params.get('tab');
    if (tab && TAB_IDS.includes(tab)) setSidebarTab(tab);
    const p = params.get('p');
    if (p && PROVINCE_TH[p]) {
      selectProvince(p);
      const d = params.get('d');
      if (d) pendingDistrictRef.current = { province: p, district: d };
    }
    setUrlReady(true);  // only now may the writer below touch the URL
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [thailandData]);

  // Complete the ?d= restore once district boundaries are in — mirrors the
  // district-layer click handler, minus the tab switch (keep the ?tab= choice).
  useEffect(() => {
    const pending = pendingDistrictRef.current;
    if (!pending || !district.districtsData) return;
    pendingDistrictRef.current = null;
    const feat = district.districtsData.features.find(
      f => f.properties.province === pending.province
        && f.properties.name === pending.district);
    if (!feat) return;  // ชื่ออำเภอใน URL ไม่ตรงกับข้อมูล — ข้ามเงียบๆ
    district.setSelectedDistrict(feat.properties.name_th || feat.properties.name);
    district.setSelectedDistrictEN(feat.properties.name);
    district.setDistrictArea((turf.area(feat) / 1_000_000).toFixed(2));
    district.fetchDistrictNDVI(pending.province, feat.properties.name);
    // Intentional partial deps — district hook fns are stable setters/callbacks
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [district.districtsData]);

  useEffect(() => {
    if (!urlReady) return;  // don't clobber the incoming URL before it's restored
    const params = new URLSearchParams();
    if (province.selectedProvinceEN) {
      params.set('p', province.selectedProvinceEN);
      if (district.selectedDistrictEN) params.set('d', district.selectedDistrictEN);
    }
    if (sidebarTab !== 'stats') params.set('tab', sidebarTab);
    if (ranking.rankingYear !== CURRENT_YEAR) params.set('year', ranking.rankingYear);
    const qs = params.toString();
    window.history.replaceState(null, '', qs ? `?${qs}` : window.location.pathname);
  }, [urlReady, province.selectedProvinceEN, district.selectedDistrictEN,
      sidebarTab, ranking.rankingYear]);

  // cooling analysis is province-scoped — clear it whenever the province changes.
  // Intentional single dep: resetCooling is stable; depending on `cooling` re-fires each render.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { cooling.resetCooling(); }, [province.selectedProvinceEN]);

  // land use composition is scope-bound (province OR district) — clear on either change
  // so the card never shows the previous scope's proportions.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { landuse.resetLanduse(); }, [province.selectedProvinceEN, district.selectedDistrictEN]);

  // Raster overlay: (re)fetch NDVI/LST tiles when the overlay or scope changes.
  // fetchTiles is a stable useCallback; province/district/overlay drive the refetch.
  useEffect(() => {
    if (raster.overlay === 'none' || !province.selectedProvinceEN) return;
    raster.fetchTiles(raster.overlay, province.selectedProvinceEN,
                      district.selectedDistrictEN || null, CURRENT_YEAR);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [raster.overlay, province.selectedProvinceEN, district.selectedDistrictEN]);

  // Swipe compare: (re)fetch both years when active / scope / metric / years change.
  useEffect(() => {
    if (!swipe.active || !province.selectedProvinceEN) return;
    setSwipeTilesReady({ a: false, b: false });  // new tiles incoming → not ready
    swipe.load(province.selectedProvinceEN, district.selectedDistrictEN || null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [swipe.active, swipe.mode, swipe.metric, swipe.yearA, swipe.yearB,
      province.selectedProvinceEN, district.selectedDistrictEN]);

  const showingDistricts = !!(province.selectedProvinceEN && district.districtsData);

  const handleReset = useCallback(() => {
    province.resetProvince();
    district.resetDistrict();
    trend.resetTrend();
    compare.resetCompare();
    recommend.resetRecommend();
    cooling.resetCooling();
    raster.clearOverlay();
    swipe.reset();
    draw.reset();
    setSidebarTab('stats');
    setViewState({
      ...INITIAL_VIEW_STATE,
      transitionDuration: 800,
      transitionInterpolator: new FlyToInterpolator(),
    });
    // Intentional partial deps — reset fns are stable; objects would re-fire each render
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [province.resetProvince, district.resetDistrict, trend.resetTrend,
      compare.resetCompare, recommend.resetRecommend]);

  const handleViewStateChange = useCallback(({ viewState: vs }) => setViewState(vs), []);
  // draw mode → crosshair (กำลังปักหมุด); ปกติ → pointer เมื่อ hover พื้นที่
  const getCursor = useCallback(
    ({ isHovering }) => (draw.drawActive ? 'crosshair' : isHovering ? 'pointer' : 'default'),
    [draw.drawActive]);

  // Enter swipe mode: clear the single overlay + flatten pitch/bearing so the
  // screen divider maps cleanly to a clip longitude (top-down).
  const enableSwipe = useCallback(() => {
    raster.clearOverlay();
    swipe.setActive(true);
    swipe.setSplit(0.5);   // always open centred, not wherever it was last dragged
    setViewState(vs => ({
      ...vs, pitch: 0, bearing: 0,
      transitionDuration: 400, transitionInterpolator: new FlyToInterpolator(),
    }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Single raster overlay — exit swipe + flatten to top-down so the pixel data
  // reads cleanly (3D extrusion is for the choropleth, not the raster).
  const enableOverlay = useCallback((kind) => {
    swipe.reset();
    raster.setOverlay(kind);
    setViewState(vs => ({
      ...vs, pitch: 0, bearing: 0,
      transitionDuration: 400, transitionInterpolator: new FlyToInterpolator(),
    }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Select a province programmatically (from the search box) — mirrors the map
  // click handler so both entry points fly to, fetch, and open the same province.
  const selectProvince = useCallback((nameEN) => {
    if (!thailandData) return;
    const feature = thailandData.features.find(f => f.properties.name === nameEN);
    if (!feature) return;
    province.setSelectedProvince(PROVINCE_TH[nameEN] || nameEN);
    province.setSelectedProvinceEN(nameEN);
    province.setProvinceArea((turf.area(feature) / 1_000_000).toFixed(2));
    district.resetDistrict();
    trend.resetTrend();
    province.fetchNDVI(nameEN);
    district.ensureDistrictsLoaded();
    district.loadDistrictCache(nameEN);
    const [minLng, minLat, maxLng, maxLat] = turf.bbox(feature);
    const maxSpan = Math.max(maxLng - minLng, maxLat - minLat);
    const zoom = Math.min(10, Math.max(6, Math.log2(4 / maxSpan) + 7));
    setViewState({
      longitude: (minLng + maxLng) / 2, latitude: (minLat + maxLat) / 2,
      zoom, pitch: 40, bearing: 0,
      transitionDuration: 800, transitionInterpolator: new FlyToInterpolator(),
    });
    // Intentional partial deps — hook fns are stable (setters + refs); listing the
    // hook objects would re-create this each render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [thailandData]);

  // All Deck.GL layers (province choropleth + swipe rasters + draw overlay),
  // memoised in independent groups — see useMapLayers.
  const layers = useMapLayers({
    thailandData, effectiveNdviCache, timelapseMetric,
    province, district, trend, recommend, raster, swipe, draw,
    showingDistricts, viewState, setViewState, setTooltip, setSidebarTab,
    selectProvince, viewportBounds, onSwipeTileLoad,
  });

  const sidebarData = {
    provinceList,
    selectedProvince:     province.selectedProvince,
    selectedProvinceEN:   province.selectedProvinceEN,
    selectedDistrict:     district.selectedDistrict,    // Thai — for display
    selectedDistrictEN:   district.selectedDistrictEN,  // English — for API calls
    provinceArea:         province.provinceArea,
    districtArea:         district.districtArea,
    districtsLoading:     district.districtsLoading,
    ndviStats:            province.ndviStats,
    ndviMonthly:          province.ndviMonthly,
    ndviLoading:          province.ndviLoading,
    lstStats:             province.lstStats,
    lstMonthly:           province.lstMonthly,
    lstLoading:           province.lstLoading,
    districtNdviStats:    district.districtNdviStats,
    districtNdviMonthly:  district.districtNdviMonthly,
    districtNdviLoading:  district.districtNdviLoading,
    districtLstStats:     district.districtLstStats,
    districtLstMonthly:   district.districtLstMonthly,
    districtLstLoading:   district.districtLstLoading,
    sidebarTab,
    trendYears:    trend.trendYears,
    trendData:     trend.trendData,
    trendLoading:  trend.trendLoading,
    trendProgress: trend.trendProgress,
    trendMetric:   trend.trendMetric,
    trendForecast: trend.trendForecast,
    compareList:    compare.compareList,
    compareYear:    compare.compareYear,
    compareData:    compare.compareData,
    compareLoading: compare.compareLoading,
    compareMetric:  compare.compareMetric,
    ndviCache,
    rankingData:    ranking.rankingData,
    rankingStats:   ranking.rankingStats,
    rankingLoading: ranking.rankingLoading,
    rankingYear:    ranking.rankingYear,
    recommendData:    recommend.recommendData,
    recommendLoading: recommend.recommendLoading,
    recommendVisible: recommend.recommendVisible,
    recommendScope:   recommend.recommendScope,
    recommendYear:    recommend.recommendYear,
    recommendWeights: recommend.recommendWeights,
    coolingData:    cooling.coolingData,
    coolingLoading: cooling.coolingLoading,
    coolingYear:    cooling.coolingYear,
    landuseData:    landuse.landuseData,
    landuseLoading: landuse.landuseLoading,
    landuseYear:    landuse.landuseYear,
    computing:        coverage.computing,
    computeProgress:  coverage.computeProgress,
  };

  const sidebarHandlers = {
    onReset:            handleReset,
    onSelectProvince:   selectProvince,
    onClearDistrict:    district.resetDistrict,
    setSidebarTab,
    onToggleTrendYear:  trend.toggleTrendYear,
    setTrendMetric:     trend.setTrendMetric,
    onFetchTrend:       trend.fetchTrend,
    onAddToCompare:     compare.addToCompare,
    onRemoveFromCompare: compare.removeFromCompare,
    setCompareMetric:   compare.setCompareMetric,
    setCompareYear:     compare.setCompareYear,
    onFetchCompare:     compare.fetchCompareData,
    onFetchRanking:     ranking.fetchRanking,
    setRankingYear:     ranking.setRankingYear,
    onFetchRecommend:    recommend.fetchRecommendation,
    onToggleRecommend:   () => recommend.setRecommendVisible(v => !v),
    onClearRecommend:    recommend.resetRecommend,
    setRecommendYear:    recommend.setRecommendYear,
    setRecommendWeights: recommend.setRecommendWeights,
    onFetchCooling:  cooling.fetchCooling,
    setCoolingYear:  cooling.setCoolingYear,
    onFetchLanduse:  () => landuse.fetchLanduse(province.selectedProvinceEN,
                       district.selectedDistrictEN || null, landuse.landuseYear),
    setLanduseYear:  landuse.setLanduseYear,
    onComputeMissing: coverage.computeMissing,
    onCancelCompute:  coverage.cancelCompute,
  };

  // Landing view — the dashboard (map, sidebar) isn't mounted yet, but the
  // hooks above already prefetch /thailand.json so entry feels instant.
  if (showLanding) {
    return (
      <>
        <Landing
          onEnter={enterDashboard}
          theme={theme}
          onToggleTheme={toggleTheme}
        />
        <Toast />
      </>
    );
  }

  return (
    <div className="App" data-sidebar={sidebarCollapsed ? 'collapsed' : 'open'}>
      <AppHeader
        loading={loading}
        sidebarCollapsed={sidebarCollapsed}
        onToggleSidebar={() => setSidebarCollapsed(c => !c)}
        theme={theme}
        onToggleTheme={toggleTheme}
        onShowAbout={() => setShowAbout(true)}
        onGoHome={goToLanding}
      />

      <aside className="side">
        <Sidebar data={sidebarData} handlers={sidebarHandlers} />
      </aside>

      <div className="canvas" ref={canvasRef}>
        <DeckGL
          viewState={viewState}
          onViewStateChange={handleViewStateChange}
          onClick={handleMapClick}
          controller={true}
          layers={layers}
          getCursor={getCursor}
          glOptions={{ preserveDrawingBuffer: true }}
        >
          <Map mapStyle={mapStyle} preserveDrawingBuffer={true} />
        </DeckGL>
        {tooltip && <MapTooltip tooltip={tooltip} />}
        <MapLegend
          overlay={swipe.active ? swipe.metric : raster.overlay}
          tileInfo={swipe.active
            ? (swipe.mode === 'diff' ? swipe.diffTile : swipe.tileA)
            : raster.tileInfo}
          choropleth={timelapseMetric === 'lst' ? 'lst' : 'ndvi'}
        />

        <MapOverlayControls
          selectedProvinceEN={province.selectedProvinceEN}
          swipe={swipe}
          raster={raster}
          enableOverlay={enableOverlay}
          enableSwipe={enableSwipe}
          swipeTilesReady={swipeTilesReady}
          canvasRef={canvasRef}
        />

        <div className="map-controls">
          <button
            className="map-btn"
            onClick={() => setViewState({
              ...INITIAL_VIEW_STATE,
              transitionDuration: 800,
              transitionInterpolator: new FlyToInterpolator(),
            })}
            aria-label="รีเซ็ตมุมมอง"
            title="รีเซ็ตมุมมอง"
          >⟲</button>
          <button
            className="map-btn"
            data-active={draw.drawActive || !!draw.result}
            onClick={() => (draw.drawActive || draw.result ? draw.reset() : draw.startDraw())}
            aria-label="วาดพื้นที่วิเคราะห์เอง"
            title="วาดพื้นที่วิเคราะห์เอง"
          >✏️</button>
          <button
            className="map-btn"
            data-active={savedPanelOpen}
            onClick={toggleSavedPanel}
            aria-label="พื้นที่ที่บันทึกไว้"
            title="พื้นที่ที่บันทึกไว้"
          >📁</button>
        </div>

        <DrawControl draw={draw} year={CURRENT_YEAR}
          resolveProvince={resolveProvince}
          onSave={handleSaveArea} saving={savedAreas.saving} />

        <SavedAreasPanel open={savedPanelOpen} onClose={() => setSavedPanelOpen(false)}
          saved={savedAreas} onLoad={handleLoadSaved} />

        <TimelapsePlayer timelapse={timelapse} />
      </div>

      <Toast />
      <AboutModal open={showAbout} onClose={() => setShowAbout(false)} />
    </div>
  );
}

export default App;
