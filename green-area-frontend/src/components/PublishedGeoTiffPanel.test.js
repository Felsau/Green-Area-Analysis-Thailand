import {render,screen} from '@testing-library/react';
import {vi} from 'vitest';
import PublishedGeoTiffPanel from './PublishedGeoTiffPanel';
import {publishedGeoTiffLayers} from '../utils/mapLayers/publishedGeoTiffLayer';
vi.mock('../utils/gisClient',()=>({gisConfigured:()=>true}));
vi.mock('@deck.gl/layers',()=>({BitmapLayer:class {constructor(props){this.props=props;}}}));
const bundle={snapshot_id:'c'.repeat(64),source_identity:{product:'lst',edition_id:'edition',province:'Bangkok Metropolis',data_year:2026,month:0,method_version:'geotiff-grid-celsius-v1'},
 summary:{statistics:{mean:20,min:0,max:40,units:'celsius',valid_pixels:3,nodata_pixels:1},metadata:{kelvin_to_celsius_count:1}},
 raster:{render_crs:'EPSG:3857',png_base64:'iVBORw0KGgo=',bounds:[100.5,13.698,100.502,13.7]},legend:{min:-100,max:100,units:'celsius',palette:['ff003c','7f6e3c','00dc3c']}};
test('Raster summary and legend share one snapshot with explicit provenance',()=>{
 render(<PublishedGeoTiffPanel view={{source:'published',scope:{province:'Bangkok Metropolis',data_year:2026,month:0,product:'lst'},bundle,setSource:vi.fn(),setScope:vi.fn(),load:vi.fn()}}/>);
 expect(screen.getByRole('img',{name:'Legend Published GeoTIFF Snapshot'})).toHaveAttribute('data-source-snapshot',bundle.snapshot_id);
 expect(screen.getByRole('img',{name:'Raster จาก Immutable Published GeoTIFF Snapshot'})).toHaveAttribute('src','data:image/png;base64,iVBORw0KGgo=');
 expect(screen.getByText(/Kelvin conversion 1 ครั้ง/)).toBeInTheDocument();expect(screen.getByText(/ปี\/เดือนยังไม่ยืนยัน/)).toBeInTheDocument();
 const layer=publishedGeoTiffLayers(bundle)[0];expect(layer.props.id).toContain(bundle.snapshot_id);expect(layer.props.bounds).toEqual(bundle.raster.bounds);expect(layer.props._imageCoordinateSystem).toBe('cartesian');
});
test('Absent or unsafe raster cannot create map imagery',()=>{
 expect(publishedGeoTiffLayers(null)).toEqual([]);expect(publishedGeoTiffLayers({...bundle,raster:{...bundle.raster,png_base64:'https://invalid.test'}})).toEqual([]);
});
test('Source and period controls expose exact accessible labels',()=>{
 render(<PublishedGeoTiffPanel view={{source:'published',scope:{province:'',data_year:2026,month:0,product:'ndvi'},setSource:vi.fn(),setScope:vi.fn(),load:vi.fn()}}/>);
 for(const label of ['แหล่งข้อมูล Raster','จังหวัด Published','ผลิตภัณฑ์ Published','ปี Published (ค.ศ.)','เดือน Published'])expect(screen.getByLabelText(label,{exact:true})).toBeInTheDocument();
});
test('active Published LDD is not mislabeled as an active Legacy raster',()=>{
 render(<PublishedGeoTiffPanel view={{source:'legacy',otherPublished:true,setSource:vi.fn(),scope:{}}}/>);
 expect(screen.getByRole('option',{name:'ใช้ Published LDD (ไม่มี Raster)'})).toBeInTheDocument();
 expect(screen.queryByRole('option',{name:'Legacy GEE (ค่าเริ่มต้น)'})).not.toBeInTheDocument();
});
