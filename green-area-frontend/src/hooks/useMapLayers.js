import { useMemo } from 'react';
import { buildMapLayers }  from '../utils/mapLayers';
import { swipeLayers }     from '../utils/mapLayers/swipeLayer';
import { drawLayers }      from '../utils/mapLayers/drawLayer';
import { recommendLayers } from '../utils/mapLayers/recommendLayers';

// Stable empty layer array so panning while swipe is OFF doesn't churn the
// combined `layers` memo.
const EMPTY_LAYERS = [];

// Compose every Deck.GL layer the map renders, split into independently-memoised
// groups so a cheap change (dragging the swipe divider, adding a draw vertex)
// only rebuilds its own group — not the whole province choropleth.
export function useMapLayers({
  thailandData, effectiveNdviCache, timelapseMetric,
  province, district, trend, recommend, raster, swipe, draw,
  showingDistricts, viewState, setViewState, setTooltip, setSidebarTab,
  selectProvince, viewportBounds, onSwipeTileLoad, satelliteBase,
}) {
  const baseLayers = useMemo(() => buildMapLayers({
    thailandData, ndviCache: effectiveNdviCache, timelapseMetric,
    selectedProvinceEN:    province.selectedProvinceEN,
    setSelectedProvince:   province.setSelectedProvince,
    setSelectedProvinceEN: province.setSelectedProvinceEN,
    setProvinceArea:       province.setProvinceArea,
    fetchNDVI:             province.fetchNDVI,
    districtsData:         district.districtsData,
    districtCache:         district.districtCache,
    selectedDistrictEN:    district.selectedDistrictEN,
    setSelectedDistrict:   district.setSelectedDistrict,
    setSelectedDistrictEN: district.setSelectedDistrictEN,
    setDistrictArea:       district.setDistrictArea,
    fetchDistrictNDVI:     district.fetchDistrictNDVI,
    selectProvince,
    ensureDistrictsLoaded: district.ensureDistrictsLoaded,
    loadDistrictCache:     district.loadDistrictCache,
    resetDistrict:         district.resetDistrict,
    resetTrend:            trend.resetTrend,
    showingDistricts,
    setViewState, setTooltip, setSidebarTab,
    zoom: viewState.zoom,
    recommendData:    recommend.recommendData,
    recommendVisible: recommend.recommendVisible,
    rasterTileInfo:   raster.tileInfo,
    swipeActive:      swipe.active,
    // draw mode → ปิด picking ของ province/district เพื่อให้คลิกปักหมุดแทนการเลือก
    drawActive:       draw.drawActive,
    // แผนที่ฐานเป็นภาพถ่ายดาวเทียม → choropleth บางลง/แบนราบ (ดู utils/mapLayers/index.js)
    satelliteBase,
    // Intentional partial deps — only re-layer on data/selection/zoom changes
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }), [
    thailandData, effectiveNdviCache, timelapseMetric,
    province.selectedProvinceEN,
    district.districtsData, district.districtCache, district.selectedDistrictEN,
    showingDistricts,
    viewState.zoom,
    recommend.recommendData, recommend.recommendVisible,
    raster.tileInfo, swipe.active, draw.drawActive, satelliteBase,
  ]);

  // Swipe layers built separately so panning (which changes viewportBounds) only
  // rebuilds the two clipped rasters, not the whole province choropleth.
  const swipeLayersMemo = useMemo(
    () => (swipe.active
      ? swipeLayers({
          swipe: { tileA: swipe.tileA, tileB: swipe.tileB, diffTile: swipe.diffTile,
                   bounds: viewportBounds, split: swipe.split },
          onTileLoad: onSwipeTileLoad,
        })
      : EMPTY_LAYERS),
    [swipe.active, swipe.tileA, swipe.tileB, swipe.diffTile, viewportBounds, swipe.split, onSwipeTileLoad]
  );

  // Draw overlay built separately so adding a vertex only rebuilds the polygon,
  // not the whole choropleth.
  const drawLayersMemo = useMemo(
    () => drawLayers({ points: draw.points }), [draw.points]);

  // AI Recommend on the drawn area — reuse the province recommend layers
  // (heatmap tiles + top-spot markers) driven by the draw hook's result.
  const drawRecommendLayersMemo = useMemo(
    () => (draw.recommendResult
      ? recommendLayers({ recommendData: draw.recommendResult,
                          recommendVisible: draw.recommendVisible, setTooltip })
      : EMPTY_LAYERS),
    // setTooltip is a stable state setter — only data/visibility drive a rebuild
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [draw.recommendResult, draw.recommendVisible]);

  return useMemo(
    () => [...baseLayers, ...swipeLayersMemo, ...drawRecommendLayersMemo, ...drawLayersMemo],
    [baseLayers, swipeLayersMemo, drawRecommendLayersMemo, drawLayersMemo]);
}
