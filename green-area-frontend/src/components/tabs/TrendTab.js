import { useMemo } from 'react';
import { ComposedChart, Area, Line, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts';
import { AVAILABLE_YEARS } from '../../constants';
import { exportTrendCsv } from '../../utils/exportUtils';
import Pill from '../ui/Pill';
import ExportBar from '../ui/ExportBar';

export default function TrendTab({ data, handlers }) {
  const {
    selectedProvince, selectedProvinceEN, selectedDistrict,
    trendYears, trendData, trendLoading, trendProgress, trendMetric,
    trendForecast,
  } = data;
  const { onToggleTrendYear, setTrendMetric, onFetchTrend } = handlers;

  const blocked = trendYears.length === 0 || trendLoading || !!selectedDistrict;

  // ต่อจุดคาดการณ์ (เส้นประ + แถบ 95% PI) ท้าย series จริง — จุดสุดท้ายของ
  // ข้อมูลจริงถูกใส่ค่า forecast ด้วยเพื่อให้เส้นประลากต่อจากเส้นทึบพอดี
  const fc = trendForecast?.[trendMetric];
  const chartData = useMemo(() => {
    const rows = trendData.map(d => ({ ...d }));
    if (rows.length && fc?.points?.length) {
      rows[rows.length - 1].forecast = rows[rows.length - 1][trendMetric];
      fc.points.forEach(p => rows.push({
        year: p.x, forecast: p.value, band: [p.lo, p.hi],
      }));
    }
    return rows;
  }, [trendData, fc, trendMetric]);

  const fmtValue = (v) => (trendMetric === 'ndvi_mean' ? v?.toFixed(3) : `${v?.toFixed(1)}%`);

  return (
    <div id="export-trend" style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      {selectedDistrict && (
        <div className="note note--warn">
          แสดงข้อมูลระดับจังหวัด · ยังไม่รองรับแนวโน้มระดับอำเภอ
        </div>
      )}

      <section className="section">
        <div className="section__head">
          <span className="section__title">ปีที่ต้องการ</span>
          <span className="section__meta">{trendYears.length} เลือกแล้ว</span>
        </div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
          {AVAILABLE_YEARS.map(y => (
            <Pill key={y} active={trendYears.includes(y)} onClick={() => onToggleTrendYear(y)}>{y}</Pill>
          ))}
        </div>
      </section>

      <section className="section">
        <div className="section__head section__head--quiet">
          <span className="section__title">ตัวชี้วัด</span>
        </div>
        <div style={{ display: 'flex', gap: 6 }}>
          <Pill active={trendMetric === 'ndvi_mean'}      onClick={() => setTrendMetric('ndvi_mean')}>NDVI</Pill>
          <Pill active={trendMetric === 'green_area_pct'} onClick={() => setTrendMetric('green_area_pct')}>พื้นที่สีเขียว %</Pill>
        </div>
      </section>

      <button
        className="btn btn--primary btn--full"
        onClick={() => onFetchTrend(selectedProvinceEN, trendYears)}
        disabled={blocked}
        title={selectedDistrict ? 'ล้างอำเภอที่เลือกก่อน' : undefined}
      >
        {trendLoading ? 'กำลังโหลด…' : 'ดูแนวโน้ม'}
      </button>

      {trendLoading ? (
        <div className="helper">
          {trendProgress}
          {trendData.length > 0 && <> · โหลดแล้ว {trendData.length} ปี</>}
        </div>
      ) : trendData.length > 0 ? (
        <section className="section">
          <div className="section__head">
            <span className="section__title">แนวโน้มรายปี</span>
            <span className="section__meta">{selectedProvince}</span>
          </div>
          <div style={{ border: '1px solid var(--rule)', background: 'var(--surface)', padding: '8px 4px 0' }}>
            <ResponsiveContainer width="100%" height={180}>
              <ComposedChart data={chartData} margin={{ top: 6, right: 8, left: -22, bottom: 0 }}>
                <XAxis dataKey="year" tick={{ fill: '#6b736d', fontSize: 10 }} axisLine={{ stroke: '#cdd1ca' }} tickLine={false} />
                <YAxis
                  domain={trendMetric === 'ndvi_mean' ? [0, 1] : [0, 100]}
                  tick={{ fill: '#6b736d', fontSize: 10 }}
                  axisLine={false} tickLine={false}
                />
                <Tooltip
                  contentStyle={{ background: '#fff', border: '1px solid #cdd1ca', borderRadius: 3, fontSize: 12, padding: '4px 8px' }}
                  formatter={(v, name) => {
                    if (name === 'band') return [`${fmtValue(v[0])} – ${fmtValue(v[1])}`, 'ช่วงคาดการณ์ 95%'];
                    if (name === 'forecast') return [fmtValue(v), 'คาดการณ์'];
                    return [fmtValue(v), trendMetric === 'ndvi_mean' ? 'NDVI' : 'พื้นที่สีเขียว'];
                  }}
                />
                <Area
                  type="monotone" dataKey="band"
                  stroke="none" fill="#1f6f43" fillOpacity={0.10}
                  activeDot={false} legendType="none"
                />
                <Line
                  type="monotone" dataKey={trendMetric}
                  stroke="#1f6f43" strokeWidth={1.75}
                  dot={{ r: 3, fill: '#fff', stroke: '#1f6f43', strokeWidth: 1.5 }}
                  activeDot={{ r: 4.5, fill: '#1f6f43' }}
                />
                <Line
                  type="monotone" dataKey="forecast"
                  stroke="#1f6f43" strokeWidth={1.5} strokeDasharray="5 4"
                  dot={{ r: 2.5, fill: '#fff', stroke: '#6b736d', strokeWidth: 1.25 }}
                  activeDot={{ r: 4, fill: '#6b736d' }}
                />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
          <div className="helper">
            แสดงเฉพาะปีที่มีข้อมูลใน cache · {trendData.length} ปี
            {fc?.points?.length > 0 && (
              <> · เส้นประ = คาดการณ์ {fc.points.length} ปีข้างหน้า
                 (linear regression · แถบ = ช่วงเชื่อมั่น 95% · R² {fc.r2?.toFixed(2)})</>
            )}
          </div>
        </section>
      ) : (
        <div className="empty">
          เลือกปีอย่างน้อยสองปี แล้วกด <strong>ดูแนวโน้ม</strong> เพื่อดูข้อมูลย้อนหลังเปรียบเทียบกัน
        </div>
      )}

      {trendData.length > 0 && (
        <ExportBar
          targetId="export-trend"
          disabled={trendLoading}
          baseName={`trend_${selectedProvinceEN || 'province'}`}
          onCsv={() => exportTrendCsv({ selectedProvince, selectedProvinceEN, trendData, trendMetric })}
          onPdf={() => import('../../utils/reportPdf').then(m => m.buildTrendReport({ selectedProvince, selectedProvinceEN, trendData, trendMetric }))}
        />
      )}
    </div>
  );
}
