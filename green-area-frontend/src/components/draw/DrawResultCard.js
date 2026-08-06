import { useState } from 'react';
import { getNdviLabel, getLstLabel } from '../../colorUtils';
import { fmtArea } from '../../utils/formatArea';
import { WHO_REFERENCE_M2, describeVsWhoReference } from '../../utils/greenMetric';
import { Figure, KVRow, KV, Note } from '../ui/Metric';
import ImpactSection from '../tabs/recommend/ImpactSection';
import SpeciesSection from '../tabs/recommend/SpeciesSection';
import DataQualityNote from '../tabs/stats/DataQualityNote';

// การ์ดผลลัพธ์หลังวิเคราะห์ — สถิติพื้นที่ + AI Recommend (ออปชัน) + บันทึก
// คืน fragment (parent ห่อด้วย .draw-panel ให้แล้ว)
export default function DrawResultCard({
  result, recommendResult, recommendLoading, recommendVisible,
  onRecommend, onToggleRecommendVisible, onStartDraw, onClose, onSave, saving,
}) {
  const [label, setLabel] = useState('');

  return (
    <>
      <div className="draw-panel__title">
        <span>ผลวิเคราะห์พื้นที่ · {result.year}</span>
        <button className="btn--text" onClick={onClose} aria-label="ปิดผลวิเคราะห์">ปิด</button>
      </div>

      <Figure
        value={result.ndvi_mean ?? '—'}
        unit="NDVI เฉลี่ย"
        tag={result.ndvi_mean != null ? getNdviLabel(result.ndvi_mean) : null}
        progress={(result.ndvi_mean || 0) * 100}
      />

      <KVRow cols={3}>
        <KV label="พื้นที่" value={fmtArea(result.area_km2)} hint="km²" />
        <KV
          label="สีเขียว"
          value={result.green_area_pct != null ? `${result.green_area_pct}%` : '—'}
          hint={result.green_area_km2 != null ? `${result.green_area_km2.toLocaleString()} km²` : null}
        />
        <KV
          label="ป่าทึบ"
          value={result.dense_area_pct != null ? `${result.dense_area_pct}%` : '—'}
          hint={result.dense_area_km2 != null ? `${result.dense_area_km2.toLocaleString()} km²` : null}
        />
      </KVRow>

      <KVRow>
        <KV
          label="ประชากร (ประมาณ)"
          value={result.population != null ? result.population.toLocaleString() : '—'}
          hint={`WorldPop ${result.worldpop_year}`}
        />
        <KV
          label="พืชพรรณต่อหัว"
          value={result.green_area_m2_per_person != null ? `${result.green_area_m2_per_person.toFixed(1)} m²` : '—'}
          // คิดสดจากตัวเลข ไม่อ่านข้อความ who_status ที่กำลังเลิกใช้
          hint={result.green_area_m2_per_person != null
            ? describeVsWhoReference(result.green_area_m2_per_person, WHO_REFERENCE_M2)
            : null}
        />
      </KVRow>

      {result.lst_mean != null && (
        <KVRow>
          <KV label="อุณหภูมิผิวพื้น" value={`${result.lst_mean}°C`} hint={getLstLabel(result.lst_mean)} />
          <KV label="ช่วง" value={`${result.lst_min}–${result.lst_max}°C`} hint="Landsat 8/9" />
        </KVRow>
      )}

      {/* พื้นที่วาดเองมักเล็ก → จำนวนภาพปลอดเมฆแปรผันมาก ยิ่งต้องบอกความไม่แน่นอน */}
      <DataQualityNote dataQuality={result.data_quality} compact />

      <Note>
        ค่าจาก Sentinel-2 / Landsat ผ่าน Google Earth Engine · ประชากรประมาณจาก
        WorldPop ภายในพื้นที่ที่วาด เทียบมาตรฐาน WHO 9 m²/คน
      </Note>

      {/* AI Recommend — หาจุดควรปลูกในพื้นที่ที่วาด */}
      {!recommendResult ? (
        <div className="draw-panel__btns">
          <button className="overlay-btn" data-active={recommendLoading}
            disabled={recommendLoading} onClick={onRecommend}>
            {recommendLoading ? 'กำลังหาจุดควรปลูก…' : '🌱 หาจุดควรปลูก (AI)'}
          </button>
        </div>
      ) : (
        <>
          <div className="draw-panel__title" style={{ marginTop: 2 }}>
            <span>จุดควรปลูก (AI)</span>
            <button className="btn--text" onClick={onToggleRecommendVisible}>
              {recommendVisible ? 'ซ่อนบนแผนที่' : 'แสดงบนแผนที่'}
            </button>
          </div>
          {recommendResult.top_locations?.length > 0 && (
            <div className="draw-panel__hint">
              จุดแนะนำ {recommendResult.top_locations.length} จุด (หมุดแดงบนแผนที่) ·
              คะแนนสูง = ควรปลูกก่อน
            </div>
          )}
          <ImpactSection impact={recommendResult.impact} />
          <SpeciesSection recommendedSpecies={recommendResult.recommended_species} />
        </>
      )}

      {/* บันทึกพื้นที่นี้ไว้ดูย้อนหลัง/แชร์ */}
      {onSave && (
        <div className="draw-save">
          <input className="draw-save__input" type="text" maxLength={120}
            placeholder="ตั้งชื่อพื้นที่ (ไม่บังคับ)"
            value={label} onChange={(e) => setLabel(e.target.value)} />
          <button className="overlay-btn" disabled={saving}
            onClick={async () => { const r = await onSave(label.trim()); if (r) setLabel(''); }}>
            {saving ? '…' : '💾 บันทึก'}
          </button>
        </div>
      )}

      <div className="draw-panel__btns">
        <button className="overlay-btn" onClick={onStartDraw}>✏️ วาดใหม่</button>
      </div>
    </>
  );
}
