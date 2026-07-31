import { PROVINCE_TH, AVAILABLE_YEARS } from '../../constants';
import { exportRankingCsv } from '../../utils/exportUtils';
import ExportBar from '../ui/ExportBar';
import { Note } from '../ui/Metric';

// 77 — total Thai provinces. The ranking only covers provinces that already have
// cached data, so we show coverage (X/77) to avoid implying it's the whole country.
const TOTAL_PROVINCES = Object.keys(PROVINCE_TH).length;

export default function OverviewPanel({ data, handlers }) {
  const {
    rankingData = [], rankingStats = null, rankingLoading = false, selectedYear,
    ndviCache, provinceList = [],
    computing = false, computeProgress = { done: 0, total: 0, failed: 0 },
  } = data;
  const {
    onFetchRanking, setSelectedYear, onComputeMissing, onCancelCompute,
  } = handlers;

  const cacheCount = Object.keys(ndviCache || {}).length;
  const passPct = rankingStats?.total > 0
    ? Math.round((rankingStats.whoPass / rankingStats.total) * 100)
    : 0;

  // Provinces with no data for this ranking year (to compute on demand).
  const ranked = new Set(rankingData.map(r => r.province));
  const missing = provinceList.filter(p => !ranked.has(p.en));
  const coveragePct = rankingStats?.total != null
    ? Math.round((rankingStats.total / TOTAL_PROVINCES) * 100)
    : 0;

  const runCompute = async () => {
    await onComputeMissing(selectedYear, missing);
    onFetchRanking(selectedYear);  // refresh ranking with the newly computed provinces
  };

  return (
    <div id="export-ranking" style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>

      <section className="section">
        <div className="section__head">
          <span className="section__title">โหลดอันดับรายปี</span>
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'stretch' }}>
          <select
            className="field"
            style={{ width: 100 }}
            value={selectedYear}
            onChange={e => setSelectedYear(Number(e.target.value))}
          >
            {AVAILABLE_YEARS.map(y => <option key={y} value={y}>{y}</option>)}
          </select>
          <button
            className="btn btn--primary"
            style={{ flex: 1 }}
            onClick={() => onFetchRanking(selectedYear)}
            disabled={rankingLoading}
          >
            {rankingLoading ? 'กำลังโหลด…' : 'โหลดอันดับ'}
          </button>
        </div>
        {cacheCount > 0 && (
          <div className="helper">{cacheCount} จังหวัดอยู่ในแคชแล้ว · แสดงเป็น 3D บนแผนที่</div>
        )}
      </section>

      {rankingStats && (
        <>
          <section className="section">
            <div className="section__head">
              <span className="section__title">สรุปปี {selectedYear}</span>
              <span className="section__meta">{rankingStats.total} / {TOTAL_PROVINCES} จังหวัด</span>
            </div>
            <div className="kv-row">
              <div className="kv">
                <div className="kv__label">ผ่าน WHO</div>
                <div className="kv__value">{rankingStats.whoPass}</div>
                <div className="kv__hint">{passPct}% ของที่จัดอันดับ</div>
              </div>
              <div className="kv">
                <div className="kv__label">ต่ำกว่า WHO</div>
                <div className="kv__value">{rankingStats.whoFail}</div>
                <div className="kv__hint">{100 - passPct}% ของที่จัดอันดับ</div>
              </div>
            </div>
            <div className="bar" style={{ marginTop: 4 }}>
              <div className="bar__fill" style={{ width: `${passPct}%` }} />
            </div>

            {(rankingStats.total < TOTAL_PROVINCES || computing) && (
              <div className="coverage">
                <div className="coverage__head">
                  <span className="helper">ความครอบคลุมข้อมูลปี {selectedYear}</span>
                  <span className="coverage__count">{rankingStats.total} / {TOTAL_PROVINCES}</span>
                </div>
                <div className="bar">
                  <div className="bar__fill" style={{ width: `${coveragePct}%` }} />
                </div>
                {computing ? (
                  <div className="coverage__row">
                    <span className="helper">
                      กำลังคำนวณ {computeProgress.done}/{computeProgress.total}
                      {computeProgress.failed > 0 && ` · ล้มเหลว ${computeProgress.failed}`}
                    </span>
                    <button className="btn btn--sm" onClick={onCancelCompute}>ยกเลิก</button>
                  </div>
                ) : (
                  <div className="coverage__row">
                    <span className="helper">ยังไม่มีข้อมูล {missing.length} จังหวัด</span>
                    <button
                      className="btn btn--sm btn--primary"
                      onClick={runCompute}
                      disabled={missing.length === 0}
                    >
                      คำนวณจังหวัดที่ยังไม่มี
                    </button>
                  </div>
                )}
                {computing && (
                  <div className="helper helper--warn">
                    คำนวณสด GEE · อาจใช้เวลาหลายนาที (ปล่อยทิ้งไว้ได้ · กดดูจังหวัดอื่นต่อได้)
                  </div>
                )}
              </div>
            )}
          </section>

          {rankingData.length > 0 && (
            <section className="section">
              <div className="section__head">
                <span className="section__title">ห้าจังหวัดที่ขาดแคลนพื้นที่สีเขียวที่สุด</span>
              </div>
              <div className="rank-table">
                {rankingData.slice(0, 5).map(r => (
                  <div className="rank-row" key={r.province}>
                    <span className="rank-row__num">{String(r.rank).padStart(2, '0')}</span>
                    <span className="rank-row__name">{PROVINCE_TH[r.province] || r.province}</span>
                    <span className="rank-row__val">{r.green_area_m2_per_person?.toFixed(1) ?? '—'} m²</span>
                  </div>
                ))}
              </div>
            </section>
          )}

          {rankingData.length > 0 && (
            <section className="section">
              <div className="section__head">
                <span className="section__title">ห้าจังหวัดที่มีพื้นที่สีเขียวมากที่สุด</span>
              </div>
              <div className="rank-table">
                {[...rankingData].reverse().slice(0, 5).map(r => (
                  <div className="rank-row" key={r.province}>
                    <span className="rank-row__num">{String(r.rank).padStart(2, '0')}</span>
                    <span className="rank-row__name">{PROVINCE_TH[r.province] || r.province}</span>
                    <span className="rank-row__val">{r.green_area_m2_per_person?.toFixed(1) ?? '—'} m²</span>
                  </div>
                ))}
              </div>
            </section>
          )}
        </>
      )}

      {!rankingStats && (
        <Note label="วิธีใช้งาน">
          คลิกจังหวัดบนแผนที่ <strong>เพื่อดูข้อมูลเชิงลึก</strong> หรือ
          กด <strong>โหลดอันดับ</strong> เพื่อจัดอันดับทั้งประเทศตามพื้นที่สีเขียวต่อคน
        </Note>
      )}

      {rankingStats && (
        <ExportBar
          targetId="export-ranking"
          baseName={`ranking_${selectedYear}`}
          onCsv={() => exportRankingCsv({ rankingData, rankingYear: selectedYear, rankingStats })}
          onPdf={() => import('../../utils/reportPdf').then(m => m.buildRankingReport({ rankingData, rankingYear: selectedYear, rankingStats }))}
        />
      )}
    </div>
  );
}
