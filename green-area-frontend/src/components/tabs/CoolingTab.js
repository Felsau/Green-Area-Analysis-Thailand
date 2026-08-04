// NDVI ↔ LST cooling scatter — empirical evidence that greener districts run cooler.
import {
  ScatterChart, Scatter, XAxis, YAxis, Tooltip,
  ResponsiveContainer, ReferenceLine, CartesianGrid,
} from 'recharts';
import { AVAILABLE_YEARS } from '../../constants';

export default function CoolingTab({ data, handlers }) {
  const {
    selectedProvince, selectedProvinceEN,
    coolingData, coolingLoading, coolingYear,
  } = data;
  const { onFetchCooling, setCoolingYear } = handlers;

  const reg = coolingData?.regression;
  const points = coolingData?.points || [];

  // Regression line endpoints across the NDVI range actually present in the data
  let segment = null;
  if (reg && points.length >= 2) {
    const xs = points.map(p => p.ndvi);
    const minX = Math.min(...xs);
    const maxX = Math.max(...xs);
    segment = [
      { x: minX, y: reg.slope * minX + reg.intercept },
      { x: maxX, y: reg.slope * maxX + reg.intercept },
    ];
  }

  return (
    <div id="export-cooling" style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      <section className="section">
        <div className="section__head">
          <span className="section__title">ปีที่วิเคราะห์</span>
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'stretch' }}>
          <select
            className="field" style={{ width: 100 }}
            value={coolingYear}
            onChange={e => setCoolingYear(Number(e.target.value))}
          >
            {AVAILABLE_YEARS.map(y => <option key={y} value={y}>{y}</option>)}
          </select>
          <button
            className="btn btn--primary" style={{ flex: 1 }}
            onClick={() => onFetchCooling(selectedProvinceEN, coolingYear)}
            disabled={coolingLoading}
          >
            {coolingLoading ? 'กำลังวิเคราะห์…' : 'วิเคราะห์ความเย็น'}
          </button>
        </div>
        <div className="helper">
          เปรียบเทียบ NDVI กับอุณหภูมิผิว (LST) รายอำเภอใน {selectedProvince} ·
          ความชันติดลบ = ยิ่งเขียวยิ่งเย็น
        </div>
      </section>

      {coolingData && !coolingLoading && (reg ? (
        <>
          <section className="section">
            <div className="section__head">
              <span className="section__title">NDVI ↔ อุณหภูมิผิว</span>
              <span className="section__meta">{coolingData.n_districts} อำเภอ</span>
            </div>
            <div style={{ border: '1px solid var(--rule)', background: 'var(--surface)', padding: '8px 4px 0' }}>
              <ResponsiveContainer width="100%" height={220}>
                <ScatterChart margin={{ top: 10, right: 12, left: -18, bottom: 4 }}>
                  <CartesianGrid stroke="#eef0ec" />
                  <XAxis
                    type="number" dataKey="ndvi" name="NDVI" domain={['auto', 'auto']}
                    tick={{ fill: '#6b736d', fontSize: 10 }}
                    axisLine={{ stroke: '#cdd1ca' }} tickLine={false}
                    tickFormatter={(v) => v.toFixed(2)}
                  />
                  <YAxis
                    type="number" dataKey="lst" name="LST" unit="°C" domain={['auto', 'auto']}
                    tick={{ fill: '#6b736d', fontSize: 10 }}
                    axisLine={false} tickLine={false}
                  />
                  <Tooltip
                    cursor={{ strokeDasharray: '3 3' }}
                    contentStyle={{ background: '#fff', border: '1px solid #cdd1ca', borderRadius: 3, fontSize: 12, padding: '4px 8px' }}
                    formatter={(v, name) => name === 'LST'
                      ? [`${Number(v).toFixed(1)}°C`, 'อุณหภูมิผิว']
                      : [Number(v).toFixed(3), 'NDVI']}
                    labelFormatter={() => ''}
                  />
                  {segment && (
                    <ReferenceLine
                      stroke="#d1495b" strokeWidth={1.5} ifOverflow="extendDomain"
                      segment={segment}
                    />
                  )}
                  <Scatter data={points} fill="#1f6f43" />
                </ScatterChart>
              </ResponsiveContainer>
            </div>
          </section>

          <section className="section">
            <div className="kv-row">
              <div className="kv">
                <div className="kv__label">ความชัน</div>
                <div className="kv__value">{reg.slope.toFixed(1)}</div>
                <div className="kv__hint">°C ต่อ NDVI 1 หน่วย</div>
              </div>
              <div className="kv">
                <div className="kv__label">R²</div>
                <div className="kv__value">{reg.r2.toFixed(2)}</div>
                <div className="kv__hint">
                  {coolingData.n_districts < 5
                    ? `n=${coolingData.n_districts} — ยังน้อยเกินสรุปนัยสำคัญ`
                    : 'ความกระชับของเส้น'}
                </div>
              </div>
            </div>
            <div className="note">{coolingData.interpretation}</div>
          </section>
        </>
      ) : (
        <div className="empty">{coolingData.interpretation}</div>
      ))}

      {!coolingData && !coolingLoading && (
        <div className="empty">
          กด <strong>วิเคราะห์ความเย็น</strong> เพื่อดูความสัมพันธ์ระหว่างพื้นที่สีเขียวกับอุณหภูมิผิวรายอำเภอ
          <br />ต้องมีข้อมูล NDVI และ LST รายอำเภอใน cache ก่อน (โหลดได้จากการคลิกอำเภอบนแผนที่)
        </div>
      )}
    </div>
  );
}
