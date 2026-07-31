// The signed-in dashboard: map canvas, sidebar, overlays, drawing tools.
//
// Split out of App.js and loaded with React.lazy so the two screens that come
// *before* it (Landing, AuthGate) no longer drag deck.gl, maplibre, turf and
// every sidebar tab into the entry chunk — none of that renders until a
// visitor is signed in. App.js still owns auth, theme, the landing gate, the
// consent layer and the /thailand.json prefetch (so the fetch keeps starting
// while the landing page is up, not on dashboard mount), and passes them in.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import DeckGL from '@deck.gl/react';
import { FlyToInterpolator } from '@deck.gl/core';
import Map from 'react-map-gl/maplibre';
import 'maplibre-gl/dist/maplibre-gl.css';

import * as turf from '@turf/turf';
import { MAP_STYLE, MAP_STYLE_DARK, MAP_STYLE_SATELLITE, INITIAL_VIEW_STATE, PROVINCE_TH, CURRENT_YEAR } from './constants';
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
import { useCanvasViewport } from './hooks/useCanvasViewport';
import { useMapLayers }      from './hooks/useMapLayers';
import Sidebar    from './components/Sidebar';
import AppHeader  from './components/AppHeader';
import MapTooltip from './components/MapTooltip';
import MapLegend  from './components/MapLegend';
import MapOverlayControls from './components/MapOverlayControls';
import TimelapsePlayer from './components/TimelapsePlayer';
import AboutModal from './components/AboutModal';
import DrawControl from './components/DrawControl';
import SavedAreasPanel from './components/SavedAreasPanel';
import AccountModal from './components/AccountModal';

// Sidebar tab ids — whitelist for the ?tab= deep-link param (mirrors Sidebar TABS)
const TAB_IDS = ['stats', 'trend', 'cooling', 'compare', 'recommend'];

export default function Dashboard({
  thailandData, loading, theme, onToggleTheme, auth,
  onGoHome, onCookieSettings, onOpenPolicy,
}) {
  const [viewState, setViewState]       = useState(INITIAL_VIEW_STATE);
  const [tooltip, setTooltip]           = useState(null);
  const [sidebarTab, setSidebarTab]     = useState('stats');
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [showAbout, setShowAbout]       = useState(false);
  const [showAccount, setShowAccount]   = useState(false);

  // The year every scope-bound view reads: country ranking, province/district
  // panels, the NDVI/LST raster overlay and the draw tool. The analysis tabs
  // (trend, compare, cooling, land use, recommend) keep their own year — they
  // answer questions *about* years, so pinning them here would break them.
  const [selectedYear, setSelectedYear] = useState(CURRENT_YEAR);

  // This component only mounts once signed in (see App.js), so the data hooks
  // never need to defer on an auth check of their own.
  const { ndviCache, setNdviCache } = useNdviCache();
  const province = useProvinceData({ setNdviCache });
  const district = useDistrictData();
  const trend    = useTrendData();
  const compare  = useCompareData();
  const ranking  = useRankingData(selectedYear);
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

  // ชนิดแผนที่ฐาน: 'map' (CARTO vector) | 'satellite' (ภาพถ่ายดาวเทียม Esri)
  // เก็บไว้เฉพาะ session นี้ ไม่เขียน localStorage — การ *จำ* ค่าข้ามการเปิดเว็บเป็น
  // รายการที่ต้องขอความยินยอมตาม PDPA (ดู CATEGORIES ใน utils/consent.js)
  const [basemap, setBasemap] = useState('map');

  // Raster/swipe overlays read poorly over the dark basemap (the blue→red /
  // green palettes get muddied). Force the light, neutral basemap whenever an
  // overlay is shown so the data colours stay true — regardless of theme.
  // ผู้ใช้เลือกภาพถ่ายดาวเทียมเองเมื่อไหร่ ให้ตัวเลือกนั้นชนะทั้งธีมและ overlay —
  // เป็นการเลือกโดยตั้งใจ ไม่ควรถูกสลับกลับเงียบ ๆ
  const overlayShown = !!raster.tileInfo?.tile_url || swipe.active;
  const mapStyle = basemap === 'satellite' ? MAP_STYLE_SATELLITE
                 : overlayShown ? MAP_STYLE
                 : theme === 'dark' ? MAP_STYLE_DARK : MAP_STYLE;

  // Deep-link: restore province (?p=), district (?d=), sidebar tab (?tab=) and
  // ranking year (?year=) from the URL once the map data is ready, then keep
  // the URL in sync for shareable links. No auth check needed — this component
  // only mounts for a signed-in visitor, and selectProvince() fetches NDVI/LST
  // and district data that requires a session.
  const didInitFromUrl = useRef(false);
  const [urlReady, setUrlReady] = useState(false);
  // Mirrors selectedYear so selectProvince can read the current year without
  // taking it as a dep (it must stay stable — useMapLayers holds onto it), and
  // so the refetch effect below can tell a real year change from first render.
  const yearRef = useRef(selectedYear);
  // district restore ต้องรอ thailand_districts.json โหลดเสร็จ (async หลัง
  // selectProvince) — พักไว้ใน ref แล้วให้ effect ด้านล่างเลือกเมื่อข้อมูลมา
  const pendingDistrictRef = useRef(null);
  useEffect(() => {
    if (didInitFromUrl.current || !thailandData) return;
    didInitFromUrl.current = true;
    const params = new URLSearchParams(window.location.search);
    const year = Number(params.get('year'));
    // Set the ref up front: selectProvince() below reads it synchronously, and
    // the refetch effect must not treat this restore as a user year change and
    // fire a second fetch for the province we are about to load.
    if (year && !Number.isNaN(year)) {
      yearRef.current = year;
      setSelectedYear(year);
    }
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
    district.fetchDistrictNDVI(pending.province, feat.properties.name, yearRef.current);
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
    if (selectedYear !== CURRENT_YEAR) params.set('year', selectedYear);
    const qs = params.toString();
    window.history.replaceState(null, '', qs ? `?${qs}` : window.location.pathname);
  }, [urlReady, province.selectedProvinceEN, district.selectedDistrictEN,
      sidebarTab, selectedYear]);

  // Year changed while something is selected → reload that scope at the new
  // year. Guarded by yearRef so first render (and the ?year= restore, which
  // primes the ref) doesn't duplicate the fetch selectProvince already made.
  useEffect(() => {
    if (yearRef.current === selectedYear) return;
    yearRef.current = selectedYear;
    const provinceEN = province.selectedProvinceEN;
    if (!provinceEN) return;
    province.fetchNDVI(provinceEN, selectedYear);
    if (district.selectedDistrictEN) {
      district.fetchDistrictNDVI(provinceEN, district.selectedDistrictEN, selectedYear);
    }
    // Intentional partial deps — hook fns are stable; the year is the trigger
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedYear]);

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
                      district.selectedDistrictEN || null, selectedYear);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [raster.overlay, province.selectedProvinceEN, district.selectedDistrictEN, selectedYear]);

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
    province.fetchNDVI(nameEN, yearRef.current);
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
    satelliteBase: basemap === 'satellite',
    selectedYear,
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
    selectedYear,
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
    landuseSource:  landuse.landuseSource,
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
    setSelectedYear,
    onFetchRecommend:    recommend.fetchRecommendation,
    onToggleRecommend:   () => recommend.setRecommendVisible(v => !v),
    onClearRecommend:    recommend.resetRecommend,
    setRecommendYear:    recommend.setRecommendYear,
    setRecommendWeights: recommend.setRecommendWeights,
    onFetchCooling:  cooling.fetchCooling,
    setCoolingYear:  cooling.setCoolingYear,
    onFetchLanduse:  () => landuse.fetchLanduse(province.selectedProvinceEN,
                       district.selectedDistrictEN || null, landuse.landuseYear,
                       landuse.landuseSource),
    setLanduseYear:  landuse.setLanduseYear,
    setLanduseSource: landuse.setLanduseSource,
    onComputeMissing: coverage.computeMissing,
    onCancelCompute:  coverage.cancelCompute,
  };

  return (
    <div className="App" data-sidebar={sidebarCollapsed ? 'collapsed' : 'open'}>
      <AppHeader
        loading={loading}
        sidebarCollapsed={sidebarCollapsed}
        onToggleSidebar={() => setSidebarCollapsed(c => !c)}
        theme={theme}
        onToggleTheme={onToggleTheme}
        onShowAbout={() => setShowAbout(true)}
        onGoHome={onGoHome}
        user={auth.user}
        profile={auth.profile}
        onShowAccount={() => setShowAccount(true)}
        onSavedAreas={toggleSavedPanel}
        onSignOut={auth.signOut}
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
          basemap={basemap}
          setBasemap={setBasemap}
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

        <DrawControl draw={draw} year={selectedYear}
          resolveProvince={resolveProvince}
          onSave={handleSaveArea} saving={savedAreas.saving} />

        <SavedAreasPanel open={savedPanelOpen} onClose={() => setSavedPanelOpen(false)}
          saved={savedAreas} onLoad={handleLoadSaved} />

        <TimelapsePlayer timelapse={timelapse} />
      </div>

      <AboutModal open={showAbout} onClose={() => setShowAbout(false)}
        onCookieSettings={() => { setShowAbout(false); onCookieSettings(); }}
        onOpenPolicy={(doc) => { setShowAbout(false); onOpenPolicy(doc); }} />
      <AccountModal open={showAccount} onClose={() => setShowAccount(false)} auth={auth} />
    </div>
  );
}
