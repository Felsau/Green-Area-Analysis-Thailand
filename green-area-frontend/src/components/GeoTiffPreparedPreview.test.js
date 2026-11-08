import {fireEvent,render,screen} from '@testing-library/react';
import {vi} from 'vitest';
import GeoTiffPreparedPreview from './GeoTiffPreparedPreview';
import {gisRequest} from '../utils/gisClient';
vi.mock('../utils/gisClient',()=>({gisRequest:vi.fn()}));
const dataset={id:'dataset',revision:3,province:'Bangkok Metropolis',data_year:2026,month:1};
const edition={id:'edition',input_revision:1,input_hash:'a'.repeat(64)};
const meta={method_version:'geotiff-grid-celsius-v1',edition_id:'edition',province:'Bangkok Metropolis',data_year:2026,month:1,source_profile:'lst_kelvin_ready',source_units:'kelvin',output_units:'celsius',resolution:[30,30],crs:'EPSG:32647',nodata:-9999,kelvin_to_celsius_count:1,valid_pixel_fraction:.75};
const ready={status:'verified_for_local_review',ready_for_review:true,ready_for_publication:false,validation_result_id:'validation',prepared:true,job:{id:'job',progress:100},attempts:[{}],summary:{metadata:meta,statistics:{mean:20,min:0,max:40,units:'celsius',valid_pixels:3,nodata_pixels:1,total_pixels:4},preview:{png_base64:'iVBORw0KGgo='}}};
beforeEach(()=>gisRequest.mockReset());
test('verified preview clearly remains unpublished with units and limitations',async()=>{
  gisRequest.mockResolvedValue(ready);render(<GeoTiffPreparedPreview dataset={dataset} edition={edition} version={1} pending={false} onAction={vi.fn()}/>);
  fireEvent.click(screen.getByText('เตรียมข้อมูล / ดูตัวอย่าง GeoTIFF'));
  expect(await screen.findByRole('img')).toHaveAttribute('src','data:image/png;base64,iVBORw0KGgo=');
  expect(screen.getByText(/ยังไม่ Publish/)).toBeInTheDocument();expect(screen.getByText(/ไม่เทียบเท่า GEE/)).toBeInTheDocument();
  expect(screen.getByText(/ปี\/เดือนเป็นค่าที่ระบุ/)).toBeInTheDocument();expect(screen.getByText(/kelvin → celsius/)).toBeInTheDocument();
  expect(screen.queryByRole('button',{name:/เปิดใช้|Activate|Rollback/})).not.toBeInTheDocument();
});
test('prepare confirmation binds month validation id and revision',async()=>{
  gisRequest.mockResolvedValue({status:'not_prepared',validation_result_id:'validation'});const action=vi.fn();
  render(<GeoTiffPreparedPreview dataset={dataset} edition={edition} version={1} pending={false} onAction={action}/>);
  fireEvent.click(screen.getByText('เตรียมข้อมูล / ดูตัวอย่าง GeoTIFF'));await screen.findByText(/มีผลตรวจผ่านปัจจุบัน/);
  fireEvent.click(screen.getByText('สั่งเตรียม GeoTIFF'));
  expect(action).toHaveBeenCalledWith(expect.objectContaining({path:'/editions/edition/geotiff-prepare-jobs',body:expect.objectContaining({month:1,validation_result_id:'validation',expected_dataset_revision:3})}));
});
test('failed refresh removes old preview without fallback',async()=>{
  gisRequest.mockResolvedValueOnce(ready).mockRejectedValueOnce(new Error('unavailable'));
  render(<GeoTiffPreparedPreview dataset={dataset} edition={edition} version={1} pending={false} onAction={vi.fn()}/>);
  fireEvent.click(screen.getByText('เตรียมข้อมูล / ดูตัวอย่าง GeoTIFF'));await screen.findByRole('img');
  fireEvent.click(screen.getByText('รีเฟรชสถานะ GeoTIFF'));await screen.findByRole('alert');
  expect(screen.queryByRole('img')).not.toBeInTheDocument();
});
test('unvalidated edition cannot enqueue',async()=>{
  gisRequest.mockResolvedValue({status:'not_prepared',validation_result_id:null});render(<GeoTiffPreparedPreview dataset={dataset} edition={edition} version={1} pending={false} onAction={vi.fn()}/>);
  fireEvent.click(screen.getByText('เตรียมข้อมูล / ดูตัวอย่าง GeoTIFF'));await screen.findByText(/ต้องตรวจ Validation ก่อน/);
  expect(screen.getByText('สั่งเตรียม GeoTIFF')).toBeDisabled();
});
