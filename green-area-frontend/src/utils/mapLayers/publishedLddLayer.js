import { GeoJsonLayer } from '@deck.gl/layers';
const colours={U:[229,83,75,200],A:[242,201,76,200],F:[26,152,80,200],W:[61,133,198,200],M:[154,160,166,200]};
export function publishedLddLayers(bundle){
  if(!bundle)return [];
  return [new GeoJsonLayer({id:`published-ldd-${bundle.snapshot_id}`,data:bundle.geometry,filled:true,stroked:true,
    pickable:false,extruded:false,getFillColor:f=>{
      const main=f.properties.LUL1_CODE;
      return colours[typeof main==='number'?['','U','A','F','W','M'][main]:String(main).trim()]||[100,100,100,180];
    },
    getLineColor:[30,60,40,255],getLineWidth:1,lineWidthUnits:'pixels',parameters:{depthTest:false}})];
}
