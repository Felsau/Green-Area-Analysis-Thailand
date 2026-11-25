import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from 'recharts';
import { PROVINCE_TH, AVAILABLE_YEARS } from '../../constants';
import { getNdviColor } from '../../colorUtils';
import { exportCompareCsv } from '../../utils/exportUtils';
import Pill from '../ui/Pill';
import ExportBar from '../ui/ExportBar';

export default function CompareTab({ data, handlers }) {
  const {
    selectedProvince, selectedProvinceEN, selectedDistrict,
    compareList, compareYear, compareData, compareLoading, compareMetric,
  } = data;
  const { onAddToCompare, onRemoveFromCompare, setCompareMetric, setCompareYear, onFetchCompare } = handlers;

  const cantAdd = compareList.includes(selectedProvinceEN) || !!selectedDistrict;

  return (
    <div id="export-compare" style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      {selectedDistrict && (
        <div className="note note--warn">
          แสดงข้อมูลระดับจังหวัด · ยังไม่รองรับเปรียบเทียบระดับอำเภอ
        </div>
      )}

      <section className="section">
        <div className="section__head">
          <span className="section__title">จังหวัดที่เลือก</span>
          <span className="section__meta">{compareList.length} จังหวัด</span>
        </div>
        {compareList.length === 0 ? (
          <div className="helper">ยังไม่มี · คลิกจังหวัดบนแผนที่แล้วกด เพิ่ม</div>
        ) : (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
            {compareList.map(p => (
              <span key={p} className="compare-chip">
                {PROVINCE_TH[p] || p}
                <button className="compare-chip__close" onClick={() => onRemoveFromCompare(p)} aria-label={`ลบ ${p}`}>×</button>
              </span>
            ))}
          </div>
        )}
        <button
          className="btn btn--sm"
          style={{ alignSelf: 'flex-start', marginTop: 4 }}
          onClick={() => onAddToCompare(selectedProvinceEN)}
          disabled={cantAdd}
          title={selectedDistrict ? 'ล้างอำเภอที่เลือกก่อน' : undefined}
        >
          + เพิ่ม {selectedProvince}
        </button>
      </section>

      <section className="section">
        <div className="section__head section__head--quiet">
          <span className="section__title">เงื่อนไข</span>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <select className="field" style={{ width: 100 }} value={compareYear} onChange={e => setCompareYear(Number(e.target.value))}>
            {AVAILABLE_YEARS.map(y => <option key={y} value={y}>{y}</option>)}
          </select>
          <div style={{ display: 'flex', gap: 4, flex: 1 }}>
            <Pill active={compareMetric === 'ndvi_mean'}      onClick={() => setCompareMetric('ndvi_mean')}>NDVI</Pill>
            <Pill active={compareMetric === 'green_area_pct'} onClick={() => setCompareMetric('green_area_pct')}>% สีเขียว</Pill>
          </div>
        </div>
      </section>

      <button
        className="btn btn--primary btn--full"
        onClick={() => onFetchCompare(compareList, compareYear)}
        disabled={compareList.length < 2 || compareLoading}
      >
        {compareLoading ? 'กำลังโหลด…' : `เปรียบเทียบ ${compareList.length} จังหวัด`}
      </button>

      {compareList.length < 2 && (
        <div className="empty">
          ต้องมีอย่างน้อย <strong>สองจังหวัด</strong> · คลิกบนแผนที่แล้วกด เพิ่ม
        </div>
      )}

      {!compareLoading && compareData.length > 0 && (
        <section className="section">
          <div className="section__head">
            <span className="section__title">ผลเปรียบเทียบ ปี {compareYear}</span>
            <span className="section__meta">{compareData.length}/{compareList.length}</span>
          </div>
          <div style={{ border: '1px solid var(--rule)', background: 'var(--surface)', padding: '8px 4px 0' }}>
            <ResponsiveContainer width="100%" height={200}>
              <BarChart
                data={compareData.map(d => ({ ...d, nameTH: PROVINCE_TH[d.province] || d.province }))}
                margin={{ top: 6, right: 8, left: -22, bottom: 32 }}
              >
                <XAxis dataKey="nameTH" tick={{ fill: '#6b736d', fontSize: 9, angle: -32, textAnchor: 'end' }} interval={0} axisLine={{ stroke: '#cdd1ca' }} tickLine={false} />
                <YAxis domain={compareMetric === 'ndvi_mean' ? [0, 1] : [0, 100]} tick={{ fill: '#6b736d', fontSize: 10 }} axisLine={false} tickLine={false} />
                <Tooltip
                  contentStyle={{ background: '#fff', border: '1px solid #cdd1ca', borderRadius: 3, fontSize: 12, padding: '4px 8px' }}
                  formatter={(v) => [compareMetric === 'ndvi_mean' ? v?.toFixed(3) : `${v?.toFixed(1)}%`, compareMetric === 'ndvi_mean' ? 'NDVI' : 'พื้นที่สีเขียว']}
                />
                <Bar dataKey={compareMetric} radius={[1, 1, 0, 0]}>
                  {compareData.map((entry, i) => <Cell key={i} fill={getNdviColor(entry.ndvi_mean)} />)}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </section>
      )}

      {compareData.length > 0 && (
        <ExportBar
          targetId="export-compare"
          disabled={compareLoading}
          baseName={`compare_${compareYear}`}
          onCsv={() => exportCompareCsv({ compareData, compareYear, compareMetric })}
          onPdf={() => import('../../utils/reportPdf').then(m => m.buildCompareReport({ compareData, compareYear, compareMetric }))}
        />
      )}
    </div>
  );
}
