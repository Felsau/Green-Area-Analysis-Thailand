import {fireEvent,render,screen} from '@testing-library/react';
import {vi} from 'vitest';
import Sidebar from './Sidebar';
import {publishedLddFixture} from '../testFixtures/publishedSnapshots';
vi.mock('../utils/gisClient',()=>({gisConfigured:()=>true}));
vi.mock('./tabs/CompareTab',()=>({default:()=> <p>LEGACY_COMPARE_RESULT</p>}));
vi.mock('./tabs/TrendTab',()=>({default:()=> <p>LEGACY_TREND_RESULT</p>}));
vi.mock('./tabs/CoolingTab',()=>({default:()=> <p>LEGACY_COOLING_RESULT</p>}));
vi.mock('./tabs/RecommendTab',()=>({default:()=> <p>LEGACY_PRIORITY_RESULT</p>}));
vi.mock('./tabs/OverviewPanel',()=>({default:()=> <p>LEGACY_RANKING_RESULT</p>}));
const setup=extra=>{
  const handlers={onReset:vi.fn(),setSidebarTab:vi.fn(),onSelectProvince:vi.fn(),setSelectedYear:vi.fn(),
    setLanduseYear:vi.fn(),setLanduseSource:vi.fn(),onFetchLanduse:vi.fn(),onClearDistrict:vi.fn(),onFetchCompare:vi.fn(),onFetchTrend:vi.fn(),onFetchRecommend:vi.fn()};
  const data={selectedProvince:'กรุงเทพมหานคร',selectedProvinceEN:'Bangkok Metropolis',selectedDistrict:null,selectedDistrictEN:null,
    sidebarTab:'stats',provinceList:[],ndviCache:{'Bangkok Metropolis':.99},selectedYear:2025,ndviStats:{ndvi_mean:.99},
    ndviLoading:false,districtNdviLoading:false,districtsLoading:false,
    landuseSource:'published',landuseYear:2026,landuseData:publishedLddFixture(),landuseLoading:false,landuseError:null,...extra};
  render(<Sidebar data={data} handlers={handlers}/>);return {handlers,data};
};
test('Published stats mount only LDD source controls/summary, never cached legacy NDVI or export',()=>{
 const {handlers,data}=setup();
 expect(screen.getByRole('region',{name:'สรุป Published LDD'})).toHaveAttribute('data-source-snapshot',data.landuseData.snapshot_id);
 expect(screen.queryByText('NDVI · พื้นที่สีเขียว')).not.toBeInTheDocument();expect(screen.queryByText(/ข้อมูลสด.*Sentinel/)).not.toBeInTheDocument();
 expect(screen.queryByLabelText('ปีของข้อมูลที่แสดง')).not.toBeInTheDocument();
 fireEvent.click(screen.getByRole('button',{name:'โหลด Published LDD'}));expect(handlers.onFetchLanduse).toHaveBeenCalledWith('Bangkok Metropolis',null,2026,'published');
 fireEvent.click(screen.getByRole('button',{name:'Legacy (ค่าเริ่มต้น)'}));expect(handlers.setLanduseSource).toHaveBeenCalledWith('dynamic_world');
});
test.each(['compare','trend','cooling','recommend'])('Published %s navigation explains unsupported state instead of mounting Legacy views',tab=>{
 const {handlers}=setup({sidebarTab:tab});
 expect(screen.getByRole('region',{name:'ความพร้อมของฟีเจอร์ Published'})).toBeInTheDocument();
 expect(screen.queryByText(/LEGACY_.*_RESULT/)).not.toBeInTheDocument();
 fireEvent.click(screen.getByRole('button',{name:'เลือกแหล่งข้อมูล / ปี'}));expect(handlers.setSidebarTab).toHaveBeenCalledWith('stats');
 fireEvent.click(screen.getByRole('button',{name:'กลับไป Legacy'}));expect(handlers.setLanduseSource).toHaveBeenCalledWith('dynamic_world');
 expect(handlers.onFetchCompare).not.toHaveBeenCalled();expect(handlers.onFetchTrend).not.toHaveBeenCalled();expect(handlers.onFetchRecommend).not.toHaveBeenCalled();
});
test('missing or revoked bundle stays Published and unavailable, with reachable source controls',()=>{
 setup({landuseData:null,landuseError:'Published unavailable'});
 expect(screen.queryByRole('region',{name:'สรุป Published LDD'})).not.toBeInTheDocument();
 expect(screen.getByText(/Published LDD · ยังไม่มี Snapshot/)).toBeVisible();expect(screen.getByRole('button',{name:'Legacy (ค่าเริ่มต้น)'})).toBeVisible();
 expect(screen.getByRole('alert')).toHaveTextContent('Published unavailable');
});
test('Legacy comparison keeps the established component and data path',()=>{
 setup({landuseSource:'dynamic_world',sidebarTab:'compare'});expect(screen.getByText('LEGACY_COMPARE_RESULT')).toBeVisible();
 expect(screen.queryByRole('region',{name:'ความพร้อมของฟีเจอร์ Published'})).not.toBeInTheDocument();
});
test('Published country overview never mounts Legacy ranking/compute/export and retains a source escape',()=>{
 const {handlers}=setup({selectedProvince:null,selectedProvinceEN:null,landuseData:null});
 expect(screen.queryByText('LEGACY_RANKING_RESULT')).not.toBeInTheDocument();
 expect(screen.getByText('ยังไม่ได้เลือกจังหวัด')).toBeVisible();expect(screen.getByText(/Ranking — ยังไม่รองรับ/)).toBeVisible();
 fireEvent.click(screen.getByRole('button',{name:'กลับไป Legacy'}));expect(handlers.setLanduseSource).toHaveBeenCalledWith('dynamic_world');
});
