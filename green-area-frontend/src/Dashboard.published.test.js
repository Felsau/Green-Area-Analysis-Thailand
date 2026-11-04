import {render,screen,waitFor,fireEvent} from '@testing-library/react';
import Dashboard from './Dashboard';
import {publishedLddFixture} from './testFixtures/publishedSnapshots';
const mock=vi.hoisted(()=>({source:'published',bundle:null}));
vi.mock('./utils/gisClient',()=>({gisConfigured:()=>true,gisRequest:vi.fn()}));
vi.mock('./hooks/useLanduseData',()=>({useLanduseData:()=>({landuseSource:mock.source,landuseData:mock.bundle,landuseYear:2026,landuseLoading:false,
  landuseError:mock.bundle?null:'unavailable',setLanduseSource:vi.fn(),setLanduseYear:vi.fn(),fetchLanduse:vi.fn(),resetLanduse:vi.fn(),clearLanduseScope:vi.fn()})}));
vi.mock('./hooks/useMapLayers',()=>({useMapLayers:()=>[{id:'legacy-sensitive-layer'}]}));
vi.mock('@deck.gl/react',()=>({default:({children,layers})=><div data-testid="deckgl" data-layers={layers.map(l=>l.id).join(',')}>{children}</div>}));
vi.mock('@deck.gl/layers',()=>({GeoJsonLayer:class {constructor(props){this.props=props;this.id=props.id;}},BitmapLayer:class {},ScatterplotLayer:class {},TextLayer:class {}}));
vi.mock('@deck.gl/geo-layers',()=>({TileLayer:class {}}));
vi.mock('@deck.gl/extensions',()=>({ClipExtension:class {}}));
vi.mock('@deck.gl/core',()=>({FlyToInterpolator:class {},WebMercatorViewport:class {getBounds(){return [0,0,1,1];}}}));
vi.mock('@turf/turf',()=>({area:()=>6400,bbox:()=>[100.5,13.7,100.51,13.71]}));
vi.mock('react-map-gl/maplibre',()=>({default:()=>null}));
const auth={user:{id:'test',email:'local@example.invalid'},profile:{role:'user',display_name:'Local'},signOut:vi.fn()};
const boundary={type:'FeatureCollection',features:[{type:'Feature',properties:{name:'Bangkok Metropolis'},geometry:{type:'Polygon',coordinates:[]}}]};
function mount(){return render(<Dashboard thailandData={boundary} loading={false} theme="light" onToggleTheme={vi.fn()} auth={auth} onGoHome={vi.fn()} onCookieSettings={vi.fn()} onOpenPolicy={vi.fn()}/>);}
beforeEach(()=>{window.history.replaceState(null,'','/?p=Bangkok%20Metropolis');mock.source='published';mock.bundle=null;});

test.each(['missing','year','province','lineage'])('selected Published mode with %s snapshot never falls through to Legacy map or legend',async kind=>{
 if(kind!=='missing'){
  mock.bundle=publishedLddFixture();
  if(kind==='year')mock.bundle.source_identity.data_year=2025;
  if(kind==='province')mock.bundle.source_identity.province='Chiang Mai';
  if(kind==='lineage')mock.bundle.summary.metadata.input_hash='f'.repeat(64);
 }
 mount();await waitFor(()=>expect(screen.getByRole('button',{name:'โหลด Published LDD'})).toBeVisible());
 expect(screen.getByTestId('deckgl')).toHaveAttribute('data-layers','');
 expect(screen.getByRole('button',{name:'วาดพื้นที่วิเคราะห์เอง'})).toBeDisabled();
 expect(screen.getByRole('button',{name:'พื้นที่ที่บันทึกไว้'})).toBeDisabled();
 expect(screen.queryByRole('region',{name:'สรุป Published LDD'})).not.toBeInTheDocument();
 expect(screen.queryByText('NDVI · พื้นที่สีเขียว')).not.toBeInTheDocument();
 fireEvent.click(screen.getByText('Local',{selector:'.usermenu__name'}));expect(screen.getByRole('menuitem',{name:'พื้นที่ที่บันทึกไว้'})).toBeDisabled();
});
test('valid LDD map, legend, summary and availability bind the same snapshot without Legacy layers',async()=>{
 mock.bundle=publishedLddFixture();mount();
 const summary=await screen.findByRole('region',{name:'สรุป Published LDD'});
 expect(summary).toHaveAttribute('data-source-snapshot',mock.bundle.snapshot_id);
 expect(screen.getByTestId('deckgl')).toHaveAttribute('data-layers','published-ldd-'+mock.bundle.snapshot_id);
 expect(screen.getByRole('region',{name:'ความพร้อมของฟีเจอร์ Published'})).toHaveAttribute('data-source-snapshot',mock.bundle.snapshot_id);
 expect(screen.getAllByText(/Published LDD/).length).toBeGreaterThan(0);
});
test('Legacy mode keeps the original map path and enables existing saved/draw controls',()=>{
 mock.source='dynamic_world';mount();expect(screen.getByTestId('deckgl')).toHaveAttribute('data-layers','legacy-sensitive-layer');
 expect(screen.getByRole('button',{name:'วาดพื้นที่วิเคราะห์เอง'})).toBeEnabled();expect(screen.getByRole('button',{name:'พื้นที่ที่บันทึกไว้'})).toBeEnabled();
});
test('country-back navigation keeps Published unavailable without exposing Legacy overview',async()=>{
 mock.bundle=publishedLddFixture();mount();await screen.findByRole('region',{name:'สรุป Published LDD'});
 fireEvent.click(screen.getByRole('button',{name:'← ดูภาพรวมประเทศ'}));
 await screen.findByText('ยังไม่ได้เลือกจังหวัด');expect(screen.getByText(/Ranking — ยังไม่รองรับ/)).toBeVisible();
 expect(screen.getByTestId('deckgl')).toHaveAttribute('data-layers','');expect(screen.getByRole('button',{name:'กลับไป Legacy'})).toBeVisible();
 expect(screen.queryByRole('region',{name:'สรุป Published LDD'})).not.toBeInTheDocument();
});
