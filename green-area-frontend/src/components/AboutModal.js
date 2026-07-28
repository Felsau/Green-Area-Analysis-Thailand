import { useEffect } from 'react';

// Data sources + methodology + citations — surfaced so the public dashboard is
// academically traceable. Kept as a modal so it's reachable from anywhere
// without taking a province-scoped sidebar tab slot.
export const DATASETS = [
  ['Sentinel-2 (ESA Copernicus)', 'COPERNICUS/S2_SR_HARMONIZED — คำนวณ NDVI ความละเอียด 10 m'],
  ['Landsat 8/9 (USGS/NASA)', 'LC08 / LC09 C02/T1_L2 — อุณหภูมิผิวพื้น (LST) 30 m'],
  ['ESA WorldCover v200', 'นิยามเขตเมือง (Built-up) สำหรับ Urban subset'],
  ['WorldPop (GP/100m)', 'ความหนาแน่นประชากร — คำนวณ m²/คน และ priority'],
  ['GADM 4.1', 'ขอบเขตจังหวัด / อำเภอ'],
  ['CARTO + OpenStreetMap', 'แผนที่ฐาน (basemap)'],
  ['Esri World Imagery', 'แผนที่ฐานแบบภาพถ่ายดาวเทียม — Esri, Maxar, Earthstar Geographics'],
];

const CITATIONS = [
  'IPCC 2019 Refinement to 2006 Guidelines, Vol.4 Ch.4 — tropical biomass',
  'Bowler D.E. et al. 2010, Landscape & Urban Planning — urban cooling meta-analysis',
  'Chave J. et al. 2014, Global Change Biology — pan-tropical allometry',
  'U.S. EPA 2023 — passenger-vehicle CO₂ baseline',
];

export default function AboutModal({ open, onClose, onCookieSettings, onOpenPolicy }) {
  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="modal-overlay">
      {/* full-screen backdrop button = click-outside-to-close, keyboard-accessible */}
      <button className="modal-overlay__backdrop" aria-label="ปิด" onClick={onClose} />
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby="about-title">
        <div className="modal__head">
          <h2 id="about-title" className="modal__title">ข้อมูลและระเบียบวิธี</h2>
          <button className="modal__close" onClick={onClose} aria-label="ปิด">×</button>
        </div>

        <div className="modal__body">
          <p>
            แดชบอร์ดวิเคราะห์พื้นที่สีเขียวของประเทศไทย ประมวลผลจาก Google Earth Engine
            (NDVI · LST · Urban subset) พร้อมแนะนำพื้นที่ที่ควรปลูกต้นไม้ —
            วิทยานิพนธ์ระดับปริญญาตรี โดย Felsau
          </p>

          <h3 className="modal__h3">แหล่งข้อมูล</h3>
          <ul className="modal__list">
            {DATASETS.map(([name, use]) => (
              <li key={name}><strong>{name}</strong> — {use}</li>
            ))}
          </ul>

          <h3 className="modal__h3">ระเบียบวิธีโดยสรุป</h3>
          <ul className="modal__list">
            <li>พื้นที่สีเขียว: NDVI &gt; 0.3 (รวมพืชเกษตร) · ป่าหนาแน่น: NDVI &gt; 0.5</li>
            <li>มาตรฐาน WHO: พื้นที่สีเขียว ≥ 9 m²/คน · Urban subset เทียบเฉพาะในเขตเมือง</li>
            <li>AI Recommend: Priority = 0.40·NDVI deficit + 0.30·LST heat + 0.30·population need</li>
            <li>Cooling: regression ของ LST ต่อ NDVI ระดับอำเภอ (slope &lt; 0 = ยิ่งเขียวยิ่งเย็น)</li>
          </ul>

          <h3 className="modal__h3">การประเมินผลกระทบ (อ้างอิง)</h3>
          <ul className="modal__list">
            {CITATIONS.map((c) => <li key={c}>{c}</li>)}
          </ul>
          <p className="modal__note">
            ค่าประเมิน CO₂ / การลดอุณหภูมิ เป็น order-of-magnitude estimate ของต้นไม้โตเต็มที่
            ขึ้นกับดิน ระยะปลูก และภูมิอากาศ — ไม่ใช่ค่าตายตัว
          </p>

          <h3 className="modal__h3">สัญญาอนุญาต</h3>
          <p className="modal__note">
            โค้ด: MIT · ข้อมูล/dataset แต่ละชุดเป็นไปตาม license ของเจ้าของ
            (Copernicus, USGS public-domain, CC BY 4.0, GADM academic, OSM ODbL)
          </p>

          {/* ช่องทางถอน/แก้ความยินยอมคุกกี้สำหรับผู้ใช้ที่ล็อกอินแล้ว — หน้าแรกที่มี
              ลิงก์ชุดเดียวกันถูกข้ามไปเมื่อมี session อยู่ ถ้าไม่มีตรงนี้ผู้ใช้ประจำ
              จะไม่มีทางถอนความยินยอมได้เลย */}
          <h3 className="modal__h3">ข้อมูลส่วนบุคคลและคุกกี้</h3>
          <p className="modal__note consent-links">
            <button className="consent-link" onClick={onCookieSettings}>ตั้งค่าคุกกี้</button>
            <button className="consent-link" onClick={() => onOpenPolicy('cookies')}>นโยบายคุกกี้</button>
            <button className="consent-link" onClick={() => onOpenPolicy('privacy')}>นโยบายความเป็นส่วนตัว</button>
            <button className="consent-link" onClick={() => onOpenPolicy('terms')}>ข้อกำหนดการใช้งาน</button>
          </p>
        </div>
      </div>
    </div>
  );
}
