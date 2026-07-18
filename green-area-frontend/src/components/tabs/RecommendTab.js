import { AVAILABLE_YEARS } from '../../constants';
import { DEFAULT_WEIGHTS } from '../../hooks/useRecommendData';
import { exportRecommendCsv } from '../../utils/exportUtils';
import ExportBar from '../ui/ExportBar';
import { Note } from '../ui/Metric';
import ImpactSection from './recommend/ImpactSection';
import SpeciesSection from './recommend/SpeciesSection';

const WEIGHT_SLIDERS = [
  { key: 'ndvi',   label: 'NDVI ต่ำ' },
  { key: 'lst',    label: 'LST สูง' },
  { key: 'pop',    label: 'ประชากร' },
  { key: 'access', label: 'เข้าถึงสีเขียวยาก' },
];

// อธิบายว่า top-spot แต่ละจุดคะแนนสูงเพราะอะไร (factors จาก backend, ค่า 0–1)
// peri_urban = โอกาสลดร้อนสูงสุดที่ขอบเมืองกำลังขยาย (Moukomla et al. 2026, Earth 7:76)
const FACTOR_LABELS = {
  ndvi_deficit: 'ขาดต้นไม้',
  lst_heat: 'ร้อนกว่าเฉลี่ย',
  pop_need: 'ชุมชนหนาแน่น',
  access_need: 'ไกลพื้นที่สีเขียว',
  peri_urban: 'ขอบเมืองลดร้อนคุ้ม',
};

const factorText = (factors) =>
  Object.entries(factors)
    .filter(([k]) => FACTOR_LABELS[k])
    .sort((a, b) => b[1] - a[1])            // เด่นสุดก่อน
    .map(([k, v]) => `${FACTOR_LABELS[k]} ${v.toFixed(1)}`)
    .join(' · ');

export default function RecommendTab({ data, handlers }) {
  const {
    selectedProvince, selectedProvinceEN, selectedDistrict, selectedDistrictEN,
    recommendData, recommendLoading, recommendVisible, recommendYear, recommendWeights,
  } = data;
  const {
    onFetchRecommend, onToggleRecommend, onClearRecommend,
    setRecommendYear, setRecommendWeights,
  } = handlers;

  return (
    <div id="export-recommend" style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>

      <p className="helper" style={{ fontSize: 13, lineHeight: 1.55, color: 'var(--ink-2)' }}>
        วิเคราะห์จุดที่ควรปลูกต้นไม้ในพื้นที่เป้าหมาย โดยถ่วงน้ำหนัก NDVI, อุณหภูมิผิวพื้น,
        ความหนาแน่นของประชากร (WorldPop) และระยะถึงพื้นที่สีเขียวเดิม (การเข้าถึง)
      </p>

      <section className="section">
        <div className="section__head">
          <span className="section__title">น้ำหนักตัวแปร</span>
          <button
            className="btn--text"
            onClick={() => setRecommendWeights({ ...DEFAULT_WEIGHTS })}
          >รีเซ็ตค่า</button>
        </div>
        {WEIGHT_SLIDERS.map(({ key, label }) => (
          <div className="weight-row" key={key}>
            <span className="weight-row__label">{label}</span>
            <input
              type="range" min="0" max="1" step="0.05"
              value={recommendWeights[key]}
              onChange={e => setRecommendWeights({ ...recommendWeights, [key]: Number(e.target.value) })}
              disabled={recommendLoading}
            />
            <span className="weight-row__val">{recommendWeights[key].toFixed(2)}</span>
          </div>
        ))}
        <div className="helper">น้ำหนักรวมจะถูก normalize อัตโนมัติ</div>
      </section>

      <div style={{ display: 'flex', gap: 8 }}>
        <select className="field" style={{ width: 100 }} value={recommendYear} onChange={e => setRecommendYear(Number(e.target.value))} disabled={recommendLoading}>
          {AVAILABLE_YEARS.map(y => <option key={y} value={y}>{y}</option>)}
        </select>
        <button
          className="btn btn--primary"
          style={{ flex: 1 }}
          onClick={() => onFetchRecommend(selectedProvinceEN, selectedDistrictEN || null, recommendYear, recommendWeights)}
          disabled={recommendLoading}
        >
          {recommendLoading
            ? 'กำลังวิเคราะห์…'
            : `วิเคราะห์${selectedDistrict ? 'อำเภอ' : 'จังหวัด'}`}
        </button>
      </div>

      {recommendData && (
        <>
          <div style={{ display: 'flex', gap: 6 }}>
            <button className="btn btn--sm" style={{ flex: 1 }} onClick={onToggleRecommend}>
              {recommendVisible ? 'ซ่อน Heatmap' : 'แสดง Heatmap'}
            </button>
            <button className="btn btn--sm" onClick={onClearRecommend}>ล้างผล</button>
          </div>

          <section className="section">
            <div className="section__head">
              <span className="section__title">น้ำหนักที่ใช้จริง</span>
            </div>
            {[
              { k: 'NDVI ต่ำ',          v: recommendData.weights.ndvi },
              { k: 'LST สูง',           v: recommendData.weights.lst },
              { k: 'ประชากรหนาแน่น',    v: recommendData.weights.population },
              { k: 'เข้าถึงสีเขียวยาก', v: recommendData.weights.access },
            ].filter(({ v }) => v != null).map(({ k, v }) => (
              <div className="weight-row" key={k}>
                <span className="weight-row__label" style={{ width: 110 }}>{k}</span>
                <div className="score-bar">
                  <div className="score-bar__fill" style={{ width: `${v * 100}%` }} />
                </div>
                <span className="weight-row__val">{(v * 100).toFixed(0)}%</span>
              </div>
            ))}
            {recommendData.worldpop_year && (
              <div className="helper">ประชากรอ้างอิง WorldPop ปี {recommendData.worldpop_year}</div>
            )}
          </section>

          <section className="section">
            <div className="section__head">
              <span className="section__title">สเกล Priority Score</span>
            </div>
            <div className="legend" />
            <div className="legend-labels">
              <span>ต่ำ</span>
              <span>สูง · ปลูกด่วน</span>
            </div>
          </section>

          <section className="section">
            <div className="section__head">
              <span className="section__title">จุดที่ควรปลูกสูงสุด · Top 10</span>
              <span className="section__meta">คลิกเพื่อเปิด Google Maps</span>
            </div>
            <div className="rank-table">
              {recommendData.top_locations?.length > 0 ? recommendData.top_locations.map((p, i) => (
                <a
                  key={i}
                  href={`https://www.google.com/maps?q=${p.lat},${p.lng}`}
                  target="_blank" rel="noreferrer"
                  className="loc-row"
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span className="loc-row__rank">{String(i + 1).padStart(2, '0')}</span>
                    <span className="loc-row__coord">{p.lat.toFixed(4)}, {p.lng.toFixed(4)}</span>
                    <span className="loc-row__score" style={{ marginLeft: 'auto' }}>{p.score.toFixed(2)}</span>
                  </div>
                  {p.factors && (
                    <div style={{ fontSize: 11, color: 'var(--ink-3)' }}>{factorText(p.factors)}</div>
                  )}
                  {/* ประเภทการใช้ที่ดินที่จุดนี้ (5 ประเภทหลักตามนิยาม LDD) — จุดจาก
                      cache รุ่นก่อนยังไม่มี field นี้ จึงต้องเช็คก่อนแสดง */}
                  {p.landuse && (
                    <div style={{ fontSize: 11, color: 'var(--ink-3)' }}>
                      การใช้ที่ดิน: {p.landuse.name_th}
                    </div>
                  )}
                </a>
              )) : (
                <div className="helper">ไม่พบจุดที่เหมาะสม</div>
              )}
            </div>
          </section>

          <ImpactSection impact={recommendData.impact} />

          <SpeciesSection recommendedSpecies={recommendData.recommended_species} />

          {recommendData.from_cache && (
            <div className="helper" style={{ textAlign: 'right' }}>
              จาก cache · {new Date(recommendData.cached_at).toLocaleString('th')}
            </div>
          )}
        </>
      )}

      {!recommendData && !recommendLoading && (
        <Note label="หมายเหตุ">
          ใช้สูตรถ่วงน้ำหนักจาก Sentinel-2 (NDVI), Landsat 8/9 (LST), WorldPop (ประชากร)
          และ ESA WorldCover (ระยะถึงพื้นที่สีเขียว). คะแนนสูง = ควรปลูกก่อน
        </Note>
      )}

      {recommendData && (
        <ExportBar
          targetId="export-recommend"
          baseName={`recommend_${(selectedDistrictEN || selectedProvinceEN || 'thailand').replace(/\s+/g, '_')}`}
          onCsv={() => exportRecommendCsv({ recommendData, selectedProvinceEN, selectedDistrict, selectedDistrictEN })}
          onPdf={() => import('../../utils/reportPdf').then(m => m.buildRecommendReport({ recommendData, selectedProvince, selectedProvinceEN, selectedDistrict, selectedDistrictEN }))}
        />
      )}
    </div>
  );
}
