import { useEffect, useState } from 'react';

import { useAdmin } from '../hooks/useAdmin';

const ROLE_OPTIONS = [
  { value: 'user',  label: 'เจ้าหน้าที่ GIS' },
  { value: 'admin', label: 'ผู้ดูแลระบบ' },
];

const fmtDate = (iso) => {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleDateString('th-TH', { year: 'numeric', month: 'short', day: 'numeric' });
  } catch { return iso; }
};

// System administration — user roles and cached data.
// เปิดจากเมนูผู้ใช้ (ปุ่ม "จัดการระบบ") เฉพาะบัญชีที่มีบทบาทผู้ดูแลระบบ
//
// ทั้งสองงานนี้เดิมทำผ่านหน้าเว็บไม่ได้เลย — เปลี่ยนบทบาทต้องรัน SQL ใน Supabase
// ส่วนล้างแคชต้องยิง curl พร้อม X-Admin-Token หน่วยงานที่รับระบบไปใช้จึงต้องพึ่ง
// ผู้พัฒนาทุกครั้ง หน้านี้ปิดช่องว่างตรงนั้น
export default function AdminModal({ open, onClose }) {
  const { users, loading, error, loadUsers, setRole, clearCache } = useAdmin();

  const [busyId, setBusyId] = useState(null);
  const [note, setNote] = useState(null);          // { ok, text }
  const [confirmClear, setConfirmClear] = useState(false);
  const [clearing, setClearing] = useState(false);

  useEffect(() => {
    if (open) {
      setNote(null);
      setConfirmClear(false);
      loadUsers();
    }
  }, [open, loadUsers]);

  if (!open) return null;

  const onChangeRole = async (user, role) => {
    setBusyId(user.id);
    setNote(null);
    const res = await setRole(user.id, role);
    setBusyId(null);
    const name = user.display_name || user.email || user.id;
    setNote(res.ok
      ? { ok: true, text: `เปลี่ยนบทบาทของ ${name} แล้ว` }
      : { ok: false, text: res.error });
  };

  const onClearCache = async () => {
    setClearing(true);
    setNote(null);
    const res = await clearCache();
    setClearing(false);
    setConfirmClear(false);
    setNote(res.ok ? { ok: true, text: res.message } : { ok: false, text: res.error });
  };

  return (
    <div className="modal-overlay">
      <button className="modal-overlay__backdrop" aria-label="ปิด" onClick={onClose} />
      <div className="modal admin-modal" role="dialog" aria-modal="true" aria-labelledby="admin-title">
        <div className="modal__head">
          <h2 id="admin-title" className="modal__title">จัดการระบบ</h2>
          <button className="modal__close" onClick={onClose} aria-label="ปิด">×</button>
        </div>

        <div className="modal__body">
          {note && (
            <p className={`account__feedback ${note.ok ? 'is-ok' : 'is-error'}`} role="status">
              {note.text}
            </p>
          )}

          <section className="account__section">
            <h3 className="account__section-head">ผู้ใช้งานและบทบาท</h3>
            <p className="admin__hint">
              เจ้าหน้าที่ GIS ใช้งานระบบวิเคราะห์ได้ทั้งหมด ส่วนผู้ดูแลระบบเพิ่มสิทธิ์
              จัดการผู้ใช้และล้างข้อมูลที่จัดเก็บชั่วคราว
            </p>

            {loading && <p className="admin__hint">กำลังโหลด…</p>}
            {error && <p className="account__feedback is-error" role="status">{error}</p>}

            {users && users.length > 0 && (
              <div className="admin__table-wrap">
                <table className="admin__table">
                  <thead>
                    <tr>
                      <th scope="col">ผู้ใช้งาน</th>
                      <th scope="col">หน่วยงาน</th>
                      <th scope="col">สมัครเมื่อ</th>
                      <th scope="col">บทบาท</th>
                    </tr>
                  </thead>
                  <tbody>
                    {users.map((u) => (
                      <tr key={u.id}>
                        <td>
                          <span className="admin__name">
                            {u.display_name || '—'}
                            {u.is_me && <span className="admin__me-tag">คุณ</span>}
                          </span>
                          <span className="admin__email">{u.email || u.id}</span>
                        </td>
                        <td>{u.organization || '—'}</td>
                        <td>{fmtDate(u.created_at)}</td>
                        <td>
                          <select
                            className="admin__role-select"
                            value={u.role}
                            disabled={busyId === u.id}
                            aria-label={`บทบาทของ ${u.display_name || u.email || u.id}`}
                            onChange={(e) => onChangeRole(u, e.target.value)}
                          >
                            {ROLE_OPTIONS.map((o) => (
                              <option key={o.value} value={o.value}>{o.label}</option>
                            ))}
                          </select>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {users && users.length === 0 && !loading && (
              <p className="admin__hint">ยังไม่มีผู้ใช้งานในระบบ</p>
            )}
          </section>

          <section className="account__section">
            <h3 className="account__section-head account__section-head--crit">
              ข้อมูลที่จัดเก็บชั่วคราว
            </h3>
            <p className="admin__hint">
              ล้างผลการคำนวณที่เก็บไว้ทั้งหมด ระบบจะคำนวณใหม่จากดาวเทียมเมื่อมีผู้เปิดดูครั้งถัดไป
              ซึ่งใช้เวลานานกว่าปกติจนกว่าจะเก็บครบอีกครั้ง
            </p>
            {!confirmClear ? (
              <button className="account__btn account__btn--crit" onClick={() => setConfirmClear(true)}>
                ล้างข้อมูลที่จัดเก็บชั่วคราว
              </button>
            ) : (
              <div className="account__actions">
                <span className="admin__hint">ยืนยันการล้างข้อมูลทั้งหมด?</span>
                <button className="account__btn account__btn--crit" onClick={onClearCache} disabled={clearing}>
                  {clearing ? 'กำลังล้าง…' : 'ยืนยัน'}
                </button>
                <button className="account__btn" onClick={() => setConfirmClear(false)} disabled={clearing}>
                  ยกเลิก
                </button>
              </div>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}
