// District names appear on hover or selection, never as persistent overlay labels.
import { GeoJsonLayer } from '@deck.gl/layers';
import * as turf from '@turf/turf';
import { getNdviRgba } from '../../colorUtils';

// Neutral fill for districts that have no NDVI cached yet — matches the
// "ยังไม่มีข้อมูล" swatch in MapLegend so partial coverage reads as
// "not computed yet", not "broken".
const NO_DATA_FILL = [225, 229, 226, 90];

export const districtLayers = (ctx) => {
  const {
    showingDistricts, districtFeatures, districtCache,
    selectedProvinceEN, selectedDistrictEN, rasterActive, drawActive, satelliteBase,
    setSelectedDistrict, setSelectedDistrictEN, setDistrictArea,
    setSidebarTab, fetchDistrictNDVI, setTooltip, selectedYear,
  } = ctx;
  if (!showingDistricts) return [];

  const cacheKey = (f) => `${f.properties.province}::${f.properties.name}`;

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

  ];
};
