import { fireEvent,render,screen } from '@testing-library/react';
import { vi } from 'vitest';
import PublishedLddSummary from './PublishedLddSummary';
import LddPublicationActions from './LddPublicationActions';
import { publishedLddLayers } from '../utils/mapLayers/publishedLddLayer';
const identity={namespace:'published',province:'Bangkok Metropolis',data_year:2026,edition_id:'edition-a',method_version:'ldd-source-area-v1'};
const bundle={snapshot_id:'snapshot-a',source_identity:identity,geometry:{type:'FeatureCollection',features:[]},
  summary:{feature_count:3,total_area_m2:6400,area_by_code_m2:{'U201/A401':1600,A101:3200,U101:1600}}};
test('provenance identifies partial source footprint and original area method',()=>{
  render(<PublishedLddSummary bundle={bundle}/>);
  expect(screen.getByRole('region').getAttribute('data-source-snapshot')).toBe('snapshot-a');
  expect(screen.getByText(/ไม่ใช่พื้นที่ครบทั้งจังหวัด/)).toBeInTheDocument();
  expect(screen.getByText('U201/A401')).toBeInTheDocument();expect(screen.getByText('edition-a')).toBeInTheDocument();
});
test('map layer binds exactly the same snapshot and preserves picking below',()=>{
  const layer=publishedLddLayers(bundle)[0];expect(layer.id).toContain(bundle.snapshot_id);
  expect(layer.props.data).toBe(bundle.geometry);expect(layer.props.pickable).toBe(false);
  expect(layer.props.getFillColor({properties:{LUL1_CODE:1}})).toEqual(layer.props.getFillColor({properties:{LUL1_CODE:'U'}}));
  expect(publishedLddLayers(null)).toEqual([]);
});
test('Admin publication uses existing confirmation callback and pointer CAS',()=>{
  const action=vi.fn(),edition={id:'edition-a',input_revision:1,input_hash:'a'.repeat(64),validated_result_id:'result-a',upload:{sha256:'b'.repeat(64)}};
  render(<LddPublicationActions dataset={{id:'dataset-a',revision:4,active_edition_id:'edition-b',province:'Bangkok Metropolis',data_year:2026}}
    edition={edition} editions={[edition]} pending={false} onAction={action}/>);
  fireEvent.click(screen.getByText('เปิดใช้ LDD (Local)'));
  expect(action).toHaveBeenCalledWith(expect.objectContaining({path:'/datasets/dataset-a/ldd-publication/activation',
    body:expect.objectContaining({edition_id:'edition-a',expected_dataset_revision:4,expected_active_edition_id:'edition-b',coverage_mode:'validated_source_footprint'})}));
});
