import {BitmapLayer} from '@deck.gl/layers';
export function publishedGeoTiffLayers(bundle){
  const r=bundle?.raster;
  if(!bundle||typeof r?.png_base64!=='string'||r.png_base64.length>64000||!/^[A-Za-z0-9+/]+={0,2}$/.test(r.png_base64)
    ||r.render_crs!=='EPSG:3857'||!Array.isArray(r.bounds)||r.bounds.length!==4||!r.bounds.every(Number.isFinite))return [];
  return [new BitmapLayer({id:`published-geotiff-${bundle.snapshot_id}`,image:`data:image/png;base64,${r.png_base64}`,
    bounds:r.bounds,_imageCoordinateSystem:'cartesian',pickable:false,opacity:1,textureParameters:{minFilter:'nearest',magFilter:'nearest'},parameters:{depthTest:false}})];
}
