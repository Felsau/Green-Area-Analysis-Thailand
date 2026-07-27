import { useEffect, useState } from 'react';
import { CATEGORIES, acceptAll, rejectOptional, setConsent } from '../utils/consent';
import { useConsent } from '../hooks/useConsent';

// แถบขอความยินยอมคุกกี้ + หน้าตั้งค่ารายหมวด (PDPA พ.ศ. 2562)
//
// สิ่งที่ต้องไม่พลาดตามกฎหมาย และเหตุผลที่เขียนโค้ดแบบนี้:
//   · ปุ่ม "ยอมรับทั้งหมด" กับ "ใช้เฉพาะที่จำเป็น" ต้องเด่นเท่ากัน — การทำปุ่มปฏิเสธ
//     ให้จางกว่าคือ dark pattern ที่ทำให้ความยินยอมไม่เป็นอิสระตามมาตรา 19 วรรคสี่
//     ทั้งคู่จึงใช้ .btn เหมือนกัน ต่างแค่ปุ่มยอมรับเป็น --primary
//   · ปิดแถบทิ้งเฉย ๆ ไม่ได้ (ไม่มีปุ่ม ✕) เพราะ "ไม่ตอบ" ต้องไม่ถูกตีความว่ายินยอม
//     ผู้ใช้ต้องเลือกอย่างใดอย่างหนึ่ง — แต่แถบไม่บังหน้าจอ ใช้เว็บต่อได้ระหว่างยังไม่ตอบ
//   · ค่าเริ่มต้นของสวิตช์ในหน้าตั้งค่าคือ "ปิด" เสมอ (opt-in ไม่ใช่ opt-out)
export default function CookieConsent({ settingsOpen, onSettingsOpenChange, onOpenPolicy }) {
  const { consent, decided } = useConsent();
  // แถบขึ้นเฉพาะตอนยังไม่เคยตัดสินใจ · หน้าตั้งค่าเปิดได้ตลอดเวลาจากลิงก์ "ตั้งค่าคุกกี้"
  // (ช่องทางถอนความยินยอมที่ต้องเข้าถึงง่ายพอ ๆ กับตอนให้)
  const showBar = !decided && !settingsOpen;

  if (!showBar && !settingsOpen) return null;
  return (
    <>
      {showBar && (
        <ConsentBar onOpenPolicy={onOpenPolicy}
                    onSettings={() => onSettingsOpenChange(true)} />
      )}
      {settingsOpen && (
        <ConsentPanel consent={consent} onOpenPolicy={onOpenPolicy}
                      onClose={() => onSettingsOpenChange(false)} />
      )}
    </>
  );
}

function ConsentBar({ onSettings, onOpenPolicy }) {
  return (
    <div className="consent-bar" role="region" aria-label="การตั้งค่าคุกกี้">
      <div className="consent-bar__text">
        <b>เว็บนี้บันทึกการตั้งค่าบางอย่างไว้ในเบราว์เซอร์ของคุณ</b>
        <span>
          ส่วนที่จำเป็นต่อการเข้าสู่ระบบทำงานอยู่แล้ว · ส่วนที่ใช้จำธีมและพื้นที่ที่คุณวาดเอง
          ขอความยินยอมก่อน — <b>ไม่มีคุกกี้ติดตาม ไม่มี analytics ไม่มีโฆษณา</b>{' '}
          <button className="btn--text" onClick={onOpenPolicy}>อ่านนโยบายคุกกี้</button>
        </span>
      </div>
      <div className="consent-bar__actions">
        <button className="btn" onClick={onSettings}>ตั้งค่า</button>
        <button className="btn" onClick={() => rejectOptional()}>ใช้เฉพาะที่จำเป็น</button>
        <button className="btn btn--primary" onClick={() => acceptAll()}>ยอมรับทั้งหมด</button>
      </div>
    </div>
  );
}

function ConsentPanel({ consent, onClose, onOpenPolicy }) {
  // สวิตช์เริ่มจากค่าที่เคยเลือกไว้ · ยังไม่เคยเลือก = ปิดทุกอัน (opt-in)
  const [choices, setChoices] = useState(() => Object.fromEntries(
    CATEGORIES.filter(c => !c.required)
      .map(c => [c.id, consent?.categories?.[c.id] === true])));

  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  const save = () => { setConsent(choices); onClose(); };

  return (
    <div className="modal-overlay">
      {/* ไม่มี backdrop กดปิด — การกดพื้นหลังหลุดมือไม่ควรถูกนับเป็นการตัดสินใจ */}
      <div className="modal modal--consent" role="dialog" aria-modal="true"
           aria-labelledby="consent-title">
        <div className="modal__head">
          <h2 id="consent-title" className="modal__title">ตั้งค่าคุกกี้</h2>
          <button className="modal__close" onClick={onClose} aria-label="ปิด">×</button>
        </div>

        <div className="modal__body">
          <p className="modal__note">
            GreenLens ไม่ได้ตั้งคุกกี้จริงสักตัว — ทุกอย่างด้านล่างบันทึกอยู่ใน localStorage
            ของเบราว์เซอร์บนเครื่องคุณเอง และไม่มีรายการใดใช้เพื่อติดตามหรือโฆษณา{' '}
            <button className="btn--text" onClick={onOpenPolicy}>ดูนโยบายคุกกี้ฉบับเต็ม</button>
          </p>

          {CATEGORIES.map(cat => {
            const on = cat.required || choices[cat.id];
            return (
              <section key={cat.id} className="consent-cat">
                <div className="consent-cat__head">
                  <div>
                    <h3 className="modal__h3">{cat.title}</h3>
                    <p className="consent-cat__summary">{cat.summary}</p>
                  </div>
                  {/* aria-label ระบุชื่อหมวด — ป้ายข้าง ๆ เป็นแค่ "เปิด/ปิด" ซึ่ง
                      ผู้ใช้ screen reader จะไม่รู้ว่ากำลังสลับหมวดไหน */}
                  <label className="consent-switch">
                    <input
                      type="checkbox"
                      aria-label={`คุกกี้หมวด${cat.title}`}
                      checked={on}
                      disabled={cat.required}
                      onChange={(e) => setChoices(c => ({ ...c, [cat.id]: e.target.checked }))}
                    />
                    <span aria-hidden="true">{cat.required ? 'เปิดตลอด' : on ? 'เปิด' : 'ปิด'}</span>
                  </label>
                </div>
                <ul className="consent-cat__items">
                  {cat.items.map(it => (
                    <li key={it.key}>
                      <b>{it.label}</b>
                      <span className="consent-cat__key">{it.key}</span>
                      <span>{it.purpose}</span>
                      <span className="consent-cat__keep">เก็บไว้: {it.keep}</span>
                    </li>
                  ))}
                </ul>
              </section>
            );
          })}
        </div>

        <div className="consent-panel__foot">
          <button className="btn--text" onClick={() => { rejectOptional(); onClose(); }}>
            ปฏิเสธทั้งหมดที่เลือกได้
          </button>
          <div className="consent-panel__foot-actions">
            <button className="btn" onClick={() => { acceptAll(); onClose(); }}>ยอมรับทั้งหมด</button>
            <button className="btn btn--primary" onClick={save}>บันทึกตัวเลือก</button>
          </div>
        </div>
      </div>
    </div>
  );
}
