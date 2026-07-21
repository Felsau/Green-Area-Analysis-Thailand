import { useEffect } from 'react';
import { TERMS_SECTIONS, TERMS_LAST_UPDATED, PRIVACY_SECTIONS, PRIVACY_LAST_UPDATED } from './legalContent';

const DOCS = {
  terms: { title: 'ข้อกำหนดการใช้งาน', sections: TERMS_SECTIONS, updated: TERMS_LAST_UPDATED },
  privacy: { title: 'นโยบายความเป็นส่วนตัว', sections: PRIVACY_SECTIONS, updated: PRIVACY_LAST_UPDATED },
};

// Read-only viewer for the Terms of Service / Privacy Policy, opened from the
// sign-up checkbox so the consent it records is actually informed. Reuses the
// same modal chrome as AboutModal.
export default function LegalModal({ open, doc, onClose }) {
  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  if (!open || !doc) return null;
  const { title, sections, updated } = DOCS[doc];

  return (
    <div className="modal-overlay">
      <button className="modal-overlay__backdrop" aria-label="ปิด" onClick={onClose} />
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby="legal-title">
        <div className="modal__head">
          <h2 id="legal-title" className="modal__title">{title}</h2>
          <button className="modal__close" onClick={onClose} aria-label="ปิด">×</button>
        </div>

        <div className="modal__body">
          <p className="modal__note">ปรับปรุงล่าสุด: {updated}</p>
          {sections.map((s, i) => (
            <div key={i}>
              {s.h && <h3 className="modal__h3">{s.h}</h3>}
              {s.body?.map((p, j) => <p key={j}>{p}</p>)}
              {s.list && (
                <ul className="modal__list">
                  {s.list.map((item, j) => <li key={j}>{item}</li>)}
                </ul>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
