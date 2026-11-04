// DTO fixtures for presentation tests only; not real GIS or trusted certificates.
function identity(seed,product){
  return {namespace:'published',scope:'province',product,province:'Bangkok Metropolis',data_year:2026,month:0,
    dataset_id:'dataset-'+seed,edition_id:'edition-'+seed,validation_result_id:'result-'+seed,
    input_hash:'a'.repeat(64),source_sha256:'b'.repeat(64),method_version:product==='landuse'?'ldd-source-area-v1':'geotiff-grid-celsius-v1'};
}
const snapshot=seed=>(['a','b','c','d'].includes(seed)?seed:'d').repeat(64);
export function publishedLddFixture(seed='a'){
  const source=identity(seed,'landuse'),meta={...source,input_revision:1,complete_province_inventory:false};
  return {snapshot_id:snapshot(seed),source_identity:source,local_only:true,complete_province_inventory:false,coverage_mode:'validated_source_footprint',
    geometry:{type:'FeatureCollection',metadata:{...meta},features:[0,1,2].map(i=>({type:'Feature',properties:{LUL1_CODE:'A'},
      geometry:{type:'Polygon',coordinates:[[[100.5+i*.001,13.7],[100.501+i*.001,13.7],[100.501+i*.001,13.701],[100.5+i*.001,13.7]]]}}))},
    summary:{metadata:{...meta},feature_count:3,total_area_m2:6400,area_by_code_m2:{'U201/A401':1600,A101:3200,U101:1600}},
    legend:[['U','ชุมชน','e5534b'],['A','เกษตร','f2c94c'],['F','ป่า','1a9850'],['W','น้ำ','3d85c6'],['M','เบ็ดเตล็ด','9aa0a6']].map(([code,name_th,color])=>({code,name_th,color}))};
}
export function publishedGeoFixture(seed='a',product='ndvi'){
  const source=identity(seed,product),units=product==='ndvi'?'unitless':'celsius';
  const meta={...source,input_revision:1,output_units:units,period_verified:false,complete_province_inventory:false,kelvin_to_celsius_count:product==='lst'?1:0};
  return {snapshot_id:snapshot(seed),source_identity:source,local_only:true,complete_province_inventory:false,period_verified:false,coverage_mode:'source_footprint_intersection',
    publication_identity:{...meta,artifacts:{[product+'_raster']:{sha256:'a'.repeat(64)}}},
    summary:{metadata:{...meta},statistics:{mean:product==='ndvi'?0:20,min:product==='ndvi'?-1:0,max:product==='ndvi'?1:40,units,valid_pixels:3,nodata_pixels:1}},
    raster:{render_crs:'EPSG:3857',nodata_transparent:true,artifact_sha256:'a'.repeat(64),png_base64:'iVBORw0KGgo=',width:2,height:2,bounds:[100.5,13.698,100.502,13.7]},
    legend:{min:product==='ndvi'?-1:-100,max:product==='ndvi'?1:100,units,palette:['ff003c','7f6e3c','00dc3c']}};
}
