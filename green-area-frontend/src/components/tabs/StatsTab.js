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

export default function StatsTab({ data, handlers }) {
  const {
    selectedProvince, selectedProvinceEN, selectedDistrict, selectedDistrictEN,
    provinceArea, districtArea,
    ndviStats, ndviMonthly, ndviLoading, urbanStats,
    lstStats, lstMonthly, lstLoading,
    districtNdviStats, districtNdviMonthly, districtNdviLoading,
    districtLstStats, districtLstMonthly, districtLstLoading,
    landuseData, landuseLoading, landuseYear, landuseSource,
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

      {/* เรือนยอดไม้ตามเกณฑ์ 3-30-300 ขึ้นก่อนทุกอย่าง — เป็นค่าเดียวบนแผงที่บอก
          ตรง ๆ ว่าต้องปลูกเพิ่มอีกกี่ km² จึงเอาไปทำแผน/งบประมาณต่อได้ทันที
          เดิมอยู่ล่างสุดเพราะเป็นสิ่งที่เพิ่มทีหลังตาม FR-17 ไม่ใช่เพราะผู้ใช้ต้องอ่านทีหลัง
          เลือกขอบเขตตามที่ผู้ใช้เลือกอยู่ — อำเภอมาก่อนถ้าเจาะอำเภออยู่ เพราะเกณฑ์
          30% เป็นเกณฑ์ระดับย่าน ค่าเฉลี่ยทั้งจังหวัดกลบพื้นที่เมืองที่ขาดจริง */}
      <CanopyNote
        canopy={selectedDistrict ? districtNdviStats?.canopy : ndviStats?.canopy}
        areaKm2={selectedDistrict ? districtNdviStats?.total_area_km2 : ndviStats?.total_area_km2}
      />

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
                </KVRow>
                {/* เรือนยอดของอำเภอย้ายไปอยู่บนสุดของแท็บแล้ว (ดูคอมเมนต์ที่นั่น)
                    เหลือแต่หลักฐานคุณภาพข้อมูลที่ยุบไว้เหมือนฝั่งจังหวัด */}
                <DataTrustSection dataQuality={districtNdviStats?.data_quality}
                                  title="ความน่าเชื่อถือของข้อมูล">
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
                  hint={urbanStats === null ? 'กำลังดึงค่าเฉพาะเขตเมือง…' : null}
                />
              )}
            </KVRow>
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
      >
        <DataQualityNote dataQuality={ndviStats?.data_quality} />
        <ValidationNote validation={ndviStats?.validation} />
        <GreenDeficitNote ndviStats={ndviStats} urbanStats={urbanStats} />
      </DataTrustSection>

      {/* Land use composition — 5 ประเภทหลักตามนิยาม LDD (Dynamic World หรือ LDD ราชการ) */}
      <LandusePanel
        scopeLabel={selectedDistrict ? `อำเภอ${selectedDistrict}`
                    : selectedProvince ? `จังหวัด${selectedProvince}` : 'พื้นที่'}
        provinceEN={selectedProvinceEN}
        landuseData={landuseData}
        landuseLoading={landuseLoading}
        landuseYear={landuseYear}
        landuseSource={landuseSource}
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
