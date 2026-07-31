import OverviewPanel from './tabs/OverviewPanel';
import StatsTab     from './tabs/StatsTab';
import TrendTab     from './tabs/TrendTab';
import CompareTab   from './tabs/CompareTab';
import RecommendTab from './tabs/RecommendTab';
import CoolingTab   from './tabs/CoolingTab';
import ProvinceSearch from './ProvinceSearch';
import ErrorBoundary from './ErrorBoundary';
import { AVAILABLE_YEARS } from '../constants';

const TABS = [
  { id: 'stats',     label: 'ข้อมูล' },
  { id: 'trend',     label: 'แนวโน้ม' },
  { id: 'cooling',   label: 'ความเย็น' },
  { id: 'compare',   label: 'เปรียบเทียบ' },
  { id: 'recommend', label: 'AI แนะนำ' },
];

export default function Sidebar({ data, handlers }) {
  const {
    selectedProvince, selectedDistrict,
    sidebarTab,
    ndviStats, districtNdviStats, ndviLoading, districtNdviLoading,
    districtsLoading,
    provinceList, ndviCache, selectedYear,
  } = data;
  const { onReset, setSidebarTab, onSelectProvince, setSelectedYear } = handlers;

  const hasProvince = !!selectedProvince;
  const dataReady   = !!(ndviStats || districtNdviStats);
  const isLoading   = ndviLoading || districtNdviLoading;

  const statusLabel = isLoading ? 'กำลังโหลดข้อมูล GEE'
                    : dataReady ? 'ข้อมูลสด · Sentinel-2'
                    : 'ยังไม่มีข้อมูล';
  const statusState = isLoading ? 'loading' : dataReady ? 'ready' : 'empty';

  return (
    <>
      <div className="psearch-bar">
        <ProvinceSearch
          provinces={provinceList}
          onSelect={onSelectProvince}
          ndviCache={ndviCache}
        />
      </div>

      {hasProvince ? (
        <>
          <nav className="tabs" role="tablist">
            {TABS.map(t => (
              <button
                key={t.id}
                id={`tab-${t.id}`}
                className="tab"
                role="tab"
                data-active={sidebarTab === t.id}
                aria-selected={sidebarTab === t.id}
                aria-controls="sidebar-tabpanel"
                onClick={() => setSidebarTab(t.id)}
              >
                {t.label}
              </button>
            ))}
          </nav>

          <div className="context">
            <div className="context__crumb">
              {selectedDistrict ? 'จังหวัด / อำเภอ' : 'จังหวัด'}
            </div>
            <div className="context__title">{selectedProvince}</div>
            {selectedDistrict && <div className="context__sub">{selectedDistrict}</div>}
            <div className="context__status">
              <span className="status-dot" data-state={statusState}>{statusLabel}</span>
              {districtsLoading && <span className="helper">โหลดอำเภอ…</span>}
              {/* The year lives here, not only on the country overview: every
                  number below is computed for it, and without a control in this
                  scope you'd have to leave the province to change year. */}
              <label className="context__year">
                ปีข้อมูล
                <select
                  className="field"
                  value={selectedYear}
                  onChange={e => setSelectedYear(Number(e.target.value))}
                  aria-label="ปีของข้อมูลที่แสดง"
                >
                  {AVAILABLE_YEARS.map(y => <option key={y} value={y}>{y}</option>)}
                </select>
              </label>
            </div>
          </div>

          <div className="panel">
            <div
              className="panel__inner"
              id="sidebar-tabpanel"
              role="tabpanel"
              aria-labelledby={`tab-${sidebarTab}`}
              tabIndex={0}
            >
              <ErrorBoundary resetKey={`${selectedProvince}:${selectedDistrict}:${sidebarTab}`}>
                {sidebarTab === 'stats'     && <StatsTab     data={data} handlers={handlers} />}
                {sidebarTab === 'trend'     && <TrendTab     data={data} handlers={handlers} />}
                {sidebarTab === 'cooling'   && <CoolingTab   data={data} handlers={handlers} />}
                {sidebarTab === 'compare'   && <CompareTab   data={data} handlers={handlers} />}
                {sidebarTab === 'recommend' && <RecommendTab data={data} handlers={handlers} />}
              </ErrorBoundary>
            </div>
          </div>

          <div className="panel__footer">
            <button className="btn--text" onClick={onReset}>
              ← ดูภาพรวมประเทศ
            </button>
          </div>
        </>
      ) : (
        <>
          <div className="context">
            <div className="context__crumb">ประเทศไทย</div>
            <div className="context__title">ดัชนีพื้นที่สีเขียว</div>
            <div className="context__status">
              <span className="helper">คลิกจังหวัดบนแผนที่เพื่อดูข้อมูลเชิงลึก</span>
            </div>
          </div>
          <div className="panel">
            <div className="panel__inner">
              <ErrorBoundary resetKey="overview">
                <OverviewPanel data={data} handlers={handlers} />
              </ErrorBoundary>
            </div>
          </div>
        </>
      )}
    </>
  );
}
