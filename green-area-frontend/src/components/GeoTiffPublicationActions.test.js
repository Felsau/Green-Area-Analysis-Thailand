import {fireEvent,render,screen} from '@testing-library/react';
import {vi} from 'vitest';
import GeoTiffPublicationActions from './GeoTiffPublicationActions';
import {gisRequest} from '../utils/gisClient';
vi.mock('../utils/gisClient',()=>({gisRequest:vi.fn()}));
const dataset={id:'dataset',revision:4,active_edition_id:null,province:'Bangkok Metropolis',data_year:2026,month:0,purpose:'ndvi'};
const edition={id:'edition',state:'draft',input_revision:1,input_hash:'a'.repeat(64),upload:{sha256:'b'.repeat(64)},manifest:{profile:'ndvi_ready'}};
beforeEach(()=>gisRequest.mockResolvedValue({certificate_id:'certificate',validation_result_id:'validation',catalog_prepared:true,identity:{}}));
test('Admin must explicitly acknowledge both limitations before confirmation',async()=>{
 const onAction=vi.fn();render(<GeoTiffPublicationActions dataset={dataset} edition={edition} editions={[edition]} version={1} pending={false} admin onAction={onAction}/>);
 await screen.findByText(/มี Certificate/);const button=screen.getByRole('button',{name:'เปิดใช้ GeoTIFF (Local)'});expect(button).toBeDisabled();
 for(const c of screen.getAllByRole('checkbox'))fireEvent.click(c);fireEvent.click(button);
 expect(onAction).toHaveBeenCalledWith(expect.objectContaining({path:'/datasets/dataset/geotiff-publication/activation',body:expect.objectContaining({certificate_id:'certificate',validation_result_id:'validation',month:0,product:'ndvi',expected_dataset_revision:4,acknowledge_unverified_period:true,acknowledge_limited_coverage:true})}));
});
test('Officer sees status without publication authority',async()=>{
 render(<GeoTiffPublicationActions dataset={dataset} edition={edition} editions={[edition]} version={1} pending={false} admin={false} onAction={vi.fn()}/>);await screen.findByText(/มี Certificate/);
 expect(screen.queryByRole('button')).not.toBeInTheDocument();expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
});
test('Withdrawal explicitly supplies null, never invents a replacement',async()=>{
 const action=vi.fn();render(<GeoTiffPublicationActions dataset={{...dataset,active_edition_id:edition.id}} edition={edition} editions={[edition]} version={1} pending={false} admin onAction={action}/>);
 await screen.findByText(/มี Certificate/);for(const c of screen.getAllByRole('checkbox'))fireEvent.click(c);fireEvent.click(screen.getByRole('button',{name:'ถอน GeoTIFF (ไม่แทนที่)'}));
 expect(action.mock.calls[0][0].body.replacement_edition_id).toBeNull();expect(action.mock.calls[0][0].body.expected_active_edition_id).toBe(edition.id);
});
