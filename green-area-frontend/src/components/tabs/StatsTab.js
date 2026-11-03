import { getNdviLabel, getLstLabel } from '../../colorUtils';
import { exportStatsCsv } from '../../utils/exportUtils';
import Accordion from '../ui/Accordion';
import { Figure, KVRow, KV, Note } from '../ui/Metric';
import ExportBar from '../ui/ExportBar';
import MonthlyChart from './stats/MonthlyChart';
import GreenDeficitNote from './stats/GreenDeficitNote';
import UhiRiskNote from './stats/UhiRiskNote';
import DataQualityNote from './stats/DataQualityNote';
import CanopyNote from './stats/CanopyNote';
import ValidationNote from './stats/ValidationNote';
import DataTrustSection from './stats/DataTrustSection';
import LandusePanel from './stats/LandusePanel';

/** ข้อความกำกับแถว "ต่อหัวประชากร (ทั้งจังหวัด)" ตอนที่ยังไม่มีค่าเขตเมืองให้ใช้.
 *
 * เดิมเช็ค `urbanStats === null` ตัวเดียว ซึ่งเป็นจริงทั้งตอนกำลังโหลดและตอนโหลด
 * ไม่สำเร็จ → คำขอที่ล้มไปแล้วยังโชว์ "กำลังดึง…" ค้างตลอด · แยกตามสถานะจริงของ
 * คำขอ (ดู useProvinceData.urbanStatus) แล้วบอกผู้ใช้ว่าค่าที่เห็นคือค่าทั้งจังหวัด
 * เพราะเหตุใด — ไม่ใช่ปล่อยให้เข้าใจว่าระบบค้าง
 */
export function urbanFallbackHint(urbanStatus, urbanStats) {
  if (urbanStatus === 'loading') return 'กำลังดึงค่าเฉพาะเขตเมือง…';
  if (urbanStatus === 'error') return 'ดึงค่าเฉพาะเขตเมืองไม่สำเร็จ — แสดงค่าทั้งจังหวัด';
  // ตอบกลับสำเร็จแต่หารไม่ได้ (urban.py คืน m2_per_person_urban = null เมื่อ
  // ประชากรในเขต built-up รวมได้ 0 — เขตเมืองเล็กมากหรือ WorldPop ไม่ครอบคลุม)
  if (urbanStatus === 'ready' && urbanStats?.m2_per_person_urban == null) {
    return 'เขตเมืองไม่มีข้อมูลประชากรพอคำนวณ — แสดงค่าทั้งจังหวัด';
  }
  return null;
}

export default function StatsTab({ data, handlers }) {
  const {
    selectedProvince, selectedProvinceEN, selectedDistrict, selectedDistrictEN,
    provinceArea, districtArea,
    ndviStats, ndviMonthly, ndviLoading, urbanStats, urbanStatus,
    lstStats, lstMonthly, lstLoading,
    districtNdviStats, districtNdviMonthly, districtNdviLoading,
    districtLstStats, districtLstMonthly, districtLstLoading,
    landuseData, landuseLoading, landuseYear, landuseSource, landuseError,
  } = data;
  const { onClearDistrict, onFetchLanduse, setLanduseYear, setLanduseSource } = handlers;

  return (
    <div id="export-stats" style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>

      {/* District banner */}
      {selectedDistrict && (
        <div style={{
          padding: '10px 12px',
          background: 'var(--paper)',
          border: '1px solid var(--rule)',
          borderLeft: '2px solid var(--accent)',
          display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8,
        }}>
          <div>
            <div style={{ fontSize: 10.5, fontWeight: 600, letterSpacing: '0.12em', textTransform: 'uppercase', color: 'var(--ink-3)' }}>
              อำเภอที่เลือก
            </div>
            <div style={{ fontSize: 15, fontWeight: 600, color: 'var(--ink-0)' }}>
              {selectedDistrict}
            </div>
            {districtArea && (
              <div style={{ fontSize: 11.5, color: 'var(--ink-3)', fontFamily: 'var(--mono)' }}>
                {Number(districtArea).toLocaleString()} km²
              </div>
            )}
          </div>
          <button className="btn--text" onClick={onClearDistrict} aria-label="ล้างอำเภอ">ล้าง</button>
        </div>
      )}

      {/* District section */}
      {selectedDistrict && (
        <>
          <Accordion title={`NDVI · อำเภอ${selectedDistrict ? ' ' + selectedDistrict : ''}`} meta="Sentinel-2 / 100m" defaultOpen={true}>
            {districtNdviLoading ? (
              <div className="helper">กำลังดึงข้อมูลจาก GEE…</div>
            ) : (
              <>
                <Figure
                  value={districtNdviStats?.ndvi_mean ?? '—'}
                  unit="ค่าเฉลี่ยทั้งปี"
                  tag={districtNdviStats ? getNdviLabel(districtNdviStats.ndvi_mean) : null}
                  progress={(districtNdviStats?.ndvi_mean || 0) * 100}
                />
                <KVRow>
                  <KV label="Min" value={districtNdviStats?.ndvi_min != null ? districtNdviStats.ndvi_min.toFixed(2) : '—'} />
                  <KV label="Max" value={districtNdviStats?.ndvi_max != null ? districtNdviStats.ndvi_max.toFixed(2) : '—'} />
                </KVRow>
                <KVRow>
                  <KV
                    label="พื้นที่สีเขียว (NDVI > 0.3)"
                    value={districtNdviStats?.green_area_pct != null ? `${districtNdviStats.green_area_pct}%` : '—'}
                    hint={districtNdviStats?.green_area_km2 != null ? `${districtNdviStats.green_area_km2.toLocaleString()} km²` : null}
                  />
                  {/* ค่าเรือนยอดของอำเภอวางคู่กันแบบเดียวกับฝั่งจังหวัด — เป็นค่า ไม่ใช่คำตัดสิน */}
                  {districtNdviStats?.canopy?.available && (
                    <KV
                      label="เรือนยอดไม้ยืนต้น"
                      value={`${districtNdviStats.canopy.canopy_pct.toFixed(1)}%`}
                      hint={`${districtNdviStats.canopy.canopy_km2.toLocaleString('th')} km²`
                        + (districtNdviStats.canopy.epoch_offset_years > 0
                            ? ` · ข้อมูลปี ${districtNdviStats.canopy.epoch_year}` : '')}
                    />
                  )}
                </KVRow>
                <DataTrustSection dataQuality={districtNdviStats?.data_quality}
                                  hasEvidence={!!districtNdviStats}
                                  title="ความน่าเชื่อถือของข้อมูล · เกณฑ์อ้างอิง">
                  {/* เกณฑ์ 30% ของ 3-30-300 เป็นเกณฑ์ระดับย่าน ระดับอำเภอจึงเป็นหน่วย
                      ที่ตรงกับเจตนาของเกณฑ์มากกว่าค่าเฉลี่ยทั้งจังหวัด */}
                  <CanopyNote canopy={districtNdviStats?.canopy}
                              areaKm2={districtNdviStats?.total_area_km2} />
                  <DataQualityNote dataQuality={districtNdviStats?.data_quality} />
                </DataTrustSection>
                {districtNdviMonthly.length > 0 && (
                  <div>
                    <div className="label">รายเดือน</div>
                    <MonthlyChart data={districtNdviMonthly} kind="ndvi" />
                  </div>
                )}
              </>
            )}
          </Accordion>

          {districtLstStats && (
            <Accordion title="อุณหภูมิผิวพื้น · อำเภอ" meta="Landsat 8/9" defaultOpen={false}>
              {districtLstLoading ? (
                <div className="helper">กำลังดึง LST จาก Landsat…</div>
              ) : (
                <>
                  <Figure
                    value={`${districtLstStats.lst_mean}°C`}
                    tag={getLstLabel(districtLstStats.lst_mean)}
                  />
                  <KVRow>
                    <KV label="Min" value={`${districtLstStats.lst_min}°C`} />
                    <KV label="Max" value={`${districtLstStats.lst_max}°C`} />
                  </KVRow>
                  <Note tone="warn">
                    LST คืออุณหภูมิผิวพื้น/พืช จากดาวเทียม สูงกว่าอุณหภูมิอากาศปกติ 5–20°C ·
                    Max คือพิกเซลที่ร้อนที่สุดในพื้นที่
                  </Note>
                  {districtLstMonthly.length > 0 && (
                    <div>
                      <div className="label">รายเดือน</div>
                      <MonthlyChart data={districtLstMonthly} kind="lst" />
                    </div>
                  )}
                </>
              )}
            </Accordion>
          )}

          <div style={{ height: 1, background: 'var(--rule)' }} />
        </>
      )}

      {/* Province NDVI */}
      <Accordion title={selectedDistrict ? 'NDVI · จังหวัด' : 'NDVI · พื้นที่สีเขียว'} meta="Sentinel-2 / annual" defaultOpen={!selectedDistrict}>
        {ndviLoading ? (
          <div className="helper">กำลังดึงข้อมูลจาก GEE…</div>
        ) : (
          <>
            <Figure
              value={ndviStats ? ndviStats.ndvi_mean : '—'}
              unit="ค่าเฉลี่ยทั้งปี"
              tag={ndviStats ? getNdviLabel(ndviStats.ndvi_mean) : null}
              progress={(ndviStats?.ndvi_mean || 0) * 100}
            />
            <KVRow cols={3}>
              {/* ทศนิยม 2 ตำแหน่งพอ — ค่าสุดขั้วราย pixel ที่ 4 ตำแหน่งให้ความแม่นยำลวง
                  ทั้งที่ความไม่แน่นอนของค่ากลางรายปีอยู่ระดับ ±0.03 NDVI */}
              <KV label="Min" value={ndviStats?.ndvi_min != null ? ndviStats.ndvi_min.toFixed(2) : '—'} />
              <KV label="Max" value={ndviStats?.ndvi_max != null ? ndviStats.ndvi_max.toFixed(2) : '—'} />
              <KV label="พื้นที่จังหวัด" value={provinceArea ? `${Number(provinceArea).toLocaleString()}` : '—'} hint="km²" />
            </KVRow>
            <KVRow>
              <KV
                label="พื้นที่สีเขียว (NDVI > 0.3)"
                value={ndviStats?.green_area_pct != null ? `${ndviStats.green_area_pct}%` : '—'}
                hint={ndviStats?.green_area_km2 != null ? `${ndviStats.green_area_km2.toLocaleString()} km²` : null}
              />
              {/* ค่าหลักคิดเฉพาะเขตเมือง ไม่ใช่ทั้งจังหวัด — ประชากรกระจุกในเขตเมือง
                  แต่พืชพรรณส่วนใหญ่อยู่นอกเขต ค่าทั้งจังหวัดจึงสูงจนไม่สื่อความจริง
                  (สมุทรปราการ 354.7 เทียบ 38.2 m²/คน) และเป็นฐานเดียวกับตารางจัดอันดับ
                  ใน OverviewPanel เสียที · ถ้าดึงค่าเขตเมืองไม่ได้ค่อยถอยไปใช้ทั้งจังหวัด
                  พร้อมป้ายกำกับขอบเขตตามเดิม */}
              {urbanStats?.m2_per_person_urban != null ? (
                <KV
                  label="ต่อหัวประชากร (เขตเมือง)"
                  value={`${urbanStats.m2_per_person_urban.toFixed(1)} m²`}
                  hint={ndviStats?.green_area_m2_per_person != null
                    ? `ทั้งจังหวัด ${ndviStats.green_area_m2_per_person.toFixed(1)} m²`
                    : null}
                />
              ) : (
                <KV
                  label="ต่อหัวประชากร (ทั้งจังหวัด)"
                  value={ndviStats?.green_area_m2_per_person != null ? `${ndviStats.green_area_m2_per_person.toFixed(1)} m²` : '—'}
                  hint={urbanFallbackHint(urbanStatus, urbanStats)}
                />
              )}
            </KVRow>
            {/* เรือนยอดไม้ยืนต้นอยู่ตรงนี้ในฐานะ "อีกค่าหนึ่งที่วัดได้" ไม่ใช่คำตัดสิน —
                คู่กับพื้นที่สีเขียวด้านบนมันเล่าเรื่องได้เองโดยไม่ต้องมีเกณฑ์มาช่วย
                (พืชพรรณทุกชนิด 51.6% แต่เป็นไม้ยืนต้นจริง 14.3%) ส่วนการเทียบเกณฑ์ 30%
                ของ 3-30-300 ว่าผ่านหรือไม่ ต้องเพิ่มอีกกี่ km² และข้อจำกัดของชุดข้อมูล
                อยู่ในหัวข้อที่ยุบไว้ด้านล่าง — คนส่วนใหญ่เปิดมาเพื่อดูว่าค่าเท่าไร
                ไม่ได้เปิดมาเพื่อรับคำตัดสิน */}
            {ndviStats?.canopy?.available && (
              <KVRow>
                <KV
                  label="เรือนยอดไม้ยืนต้น"
                  value={`${ndviStats.canopy.canopy_pct.toFixed(1)}%`}
                  hint={`${ndviStats.canopy.canopy_km2.toLocaleString('th')} km²`
                    + (ndviStats.canopy.epoch_offset_years > 0
                        ? ` · ข้อมูลปี ${ndviStats.canopy.epoch_year}` : '')}
                />
              </KVRow>
            )}
            {/* ประชากร fallback: m²/คน อ้างอิงประชากรคนละปีกับ NDVI — บอกปีจริงให้ผู้ใช้รู้ */}
            {ndviStats?.population_year != null && ndviStats.population_year !== ndviStats.year && (
              <div className="helper" style={{ marginTop: 4 }}>
                * “ต่อหัวประชากร” คำนวณจากประชากรปี {ndviStats.population_year} (ปี {ndviStats.year} ยังไม่มีข้อมูลประชากร)
              </div>
            )}
            {!selectedDistrict && ndviMonthly.length > 0 && (
              <div>
                <div className="label">NDVI รายเดือน</div>
                <MonthlyChart data={ndviMonthly} kind="ndvi" />
                <div className="helper" style={{ marginTop: 4 }}>
                  ข้อมูลจาก Sentinel-2 ผ่าน Google Earth Engine
                </div>
              </div>
            )}
          </>
        )}
      </Accordion>

      {/* หลักฐานเชิงสถิติทั้งหมดยุบไว้ใต้หัวข้อเดียว ปิดไว้เป็นค่าเริ่มต้น —
          ทั้งคุณภาพภาพดาวเทียม (NFR-07), ผลเทียบ WorldCover (NFR-08) และการเทียบ
          ค่าอ้างอิง WHO ซึ่งวัดคนละปริมาณกับตัวชี้วัดนี้ (ดู utils/greenMetric.js)
          สามอย่างนี้ตอบคำถาม "เชื่อเลขนี้ได้แค่ไหน" ไม่ใช่ "ต้องทำอะไรต่อ" */}
      <DataTrustSection
        dataQuality={ndviStats?.data_quality}
        validation={ndviStats?.validation}
        hasEvidence={!!ndviStats}
      >
        {/* เกณฑ์ 3-30-300 (FR-17) และค่าอ้างอิง WHO อยู่ในกองเดียวกับหลักฐานคุณภาพ
            ข้อมูล — ทั้งสามอย่างเป็น "การตีความค่าเทียบเกณฑ์ภายนอก" ไม่ใช่ตัวค่าเอง */}
        <CanopyNote canopy={ndviStats?.canopy} areaKm2={ndviStats?.total_area_km2} />
        <GreenDeficitNote ndviStats={ndviStats} urbanStats={urbanStats} />
        <DataQualityNote dataQuality={ndviStats?.data_quality} />
        <ValidationNote validation={ndviStats?.validation} />
      </DataTrustSection>

      {/* Land use composition — 5 ประเภทหลักตามนิยาม LDD (Dynamic World หรือ LDD ราชการ) */}
      <LandusePanel
        scopeLabel={selectedDistrict ? `อำเภอ${selectedDistrict}`
                    : selectedProvince ? `จังหวัด${selectedProvince}` : 'พื้นที่'}
        provinceEN={selectedProvinceEN}
        districtEN={selectedDistrictEN}
        landuseData={landuseData}
        landuseLoading={landuseLoading}
        landuseYear={landuseYear}
        landuseSource={landuseSource}
        landuseError={landuseError}
        setLanduseYear={setLanduseYear}
        setLanduseSource={setLanduseSource}
        onAnalyze={onFetchLanduse}
      />

      {/* Province LST */}
      {(lstStats || lstLoading) && (
        <Accordion title={`อุณหภูมิผิวพื้น${selectedDistrict ? ' · จังหวัด' : ''}`} meta="Landsat 8/9" defaultOpen={false}>
          {lstLoading ? (
            <div className="helper">กำลังดึงข้อมูล LST…</div>
          ) : lstStats ? (
            <>
              <Figure
                value={`${lstStats.lst_mean}°C`}
                tag={getLstLabel(lstStats.lst_mean)}
              />
              <KVRow>
                <KV label="Min" value={`${lstStats.lst_min}°C`} />
                <KV label="Max" value={`${lstStats.lst_max}°C`} />
              </KVRow>
              <Note tone="warn">
                LST คืออุณหภูมิผิวพื้น สูงกว่าอุณหภูมิอากาศ 5–20°C · Max = พิกเซลร้อนสุดในพื้นที่
              </Note>
              {!selectedDistrict && lstMonthly.length > 0 && (
                <div>
                  <div className="label">รายเดือน</div>
                  <MonthlyChart data={lstMonthly} kind="lst" />
                </div>
              )}
            </>
          ) : null}
        </Accordion>
      )}

      {/* UHI Risk */}
      <UhiRiskNote ndviStats={ndviStats} lstStats={lstStats} selectedDistrict={selectedDistrict} />

      <ExportBar
        targetId="export-stats"
        baseName={`stats_${(selectedDistrictEN || selectedProvinceEN || 'province').replace(/\s+/g, '_')}`}
        onCsv={() => exportStatsCsv({
          selectedProvince, selectedProvinceEN, selectedDistrict, selectedDistrictEN,
          provinceArea, districtArea,
          ndviStats, ndviMonthly, lstStats, lstMonthly,
          districtNdviStats, districtNdviMonthly, districtLstStats, districtLstMonthly,
        })}
        onPdf={() => import('../../utils/reportPdf').then(m => m.buildStatsReport({
          selectedProvince, selectedProvinceEN, selectedDistrict, selectedDistrictEN,
          provinceArea, districtArea,
          ndviStats, ndviMonthly, lstStats, lstMonthly,
          districtNdviStats, districtNdviMonthly,
          districtLstStats, districtLstMonthly,
        }))}
      />
    </div>
  );
}
