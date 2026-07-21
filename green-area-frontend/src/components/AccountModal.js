import { useEffect, useState } from 'react';

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

const fmtDate = (iso) => {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleDateString('th-TH', { year: 'numeric', month: 'long', day: 'numeric' });
  } catch { return iso; }
};

// Account settings — profile, change password, admin note, delete account.
// Reachable from the user menu in AppHeader once signed in.
export default function AccountModal({ open, onClose, auth }) {
  const [name, setName] = useState('');
  const [org, setOrg] = useState('');
  const [nameNote, setNameNote] = useState('');
  const [savingName, setSavingName] = useState(false);

  const [cpCur, setCpCur] = useState('');
  const [cpNew, setCpNew] = useState('');
  const [cpNote, setCpNote] = useState(null); // { ok, text }
  const [changingPw, setChangingPw] = useState(false);

  const [newEmail, setNewEmail] = useState('');
  const [emailNote, setEmailNote] = useState(null); // { ok, text }
  const [changingEmail, setChangingEmail] = useState(false);

  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [deletePw, setDeletePw] = useState('');
  const [deleting, setDeleting] = useState(false);
  const [deleteErr, setDeleteErr] = useState('');

  useEffect(() => {
    if (open) {
      setName(auth.profile?.display_name || '');
      setOrg(auth.profile?.organization || '');
      setNewEmail('');
      setEmailNote(null);
      setConfirmingDelete(false);
      setDeletePw('');
      setDeleteErr('');
    }
  }, [open, auth.profile]);

  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  if (!open) return null;

  const isAdmin = auth.profile?.role === 'admin';
  const displayName = auth.profile?.display_name || auth.user?.email || '';
  const monogram = displayName.trim().charAt(0).toUpperCase() || '?';

  const saveName = async () => {
    if (!name.trim() || savingName) return;
    setSavingName(true);
    setNameNote('');
    const res = await auth.updateProfile(name.trim(), org.trim());
    setSavingName(false);
    setNameNote(res.ok ? 'บันทึกข้อมูลแล้ว' : (res.error || 'บันทึกไม่สำเร็จ'));
  };

  const changePw = async () => {
    if (changingPw) return;
    if (!cpCur) return setCpNote({ ok: false, text: 'กรอกรหัสผ่านปัจจุบัน' });
    if (cpNew.length < 8) return setCpNote({ ok: false, text: 'รหัสผ่านใหม่ต้องยาวอย่างน้อย 8 ตัวอักษร' });
    setChangingPw(true);
    setCpNote(null);
    const res = await auth.changePassword(cpCur, cpNew);
    setChangingPw(false);
    if (!res.ok) return setCpNote({ ok: false, text: res.error });
    setCpNote({ ok: true, text: 'เปลี่ยนรหัสผ่านแล้ว' });
    setCpCur(''); setCpNew('');
  };

  const changeEmail = async () => {
    if (changingEmail) return;
    if (!EMAIL_RE.test(newEmail)) return setEmailNote({ ok: false, text: 'กรอกอีเมลใหม่ให้ถูกต้อง' });
    if (newEmail === auth.user?.email) return setEmailNote({ ok: false, text: 'อีเมลใหม่ต้องต่างจากอีเมลเดิม' });
    setChangingEmail(true);
    setEmailNote(null);
    const res = await auth.changeEmail(newEmail);
    setChangingEmail(false);
    if (!res.ok) return setEmailNote({ ok: false, text: res.error });
    setEmailNote({ ok: true, text: 'ส่งลิงก์ยืนยันไปที่อีเมลเดิมและอีเมลใหม่แล้ว — คลิกยืนยันทั้งสองลิงก์เพื่อเปลี่ยน' });
    setNewEmail('');
  };

  const confirmDelete = async () => {
    if (deleting) return;
    if (!deletePw) return setDeleteErr('กรอกรหัสผ่านเพื่อยืนยัน');
    setDeleting(true);
    setDeleteErr('');
    const res = await auth.deleteAccount(deletePw);
    setDeleting(false);
    if (!res.ok) { setDeleteErr(res.error); return; }
    onClose();
  };

  return (
    <div className="modal-overlay">
      <button className="modal-overlay__backdrop" aria-label="ปิด" onClick={onClose} />
      <div className="modal account-modal" role="dialog" aria-modal="true" aria-labelledby="account-title">
        <div className="modal__head">
          <h2 id="account-title" className="modal__title">บัญชีผู้ใช้</h2>
          <button className="modal__close" onClick={onClose} aria-label="ปิด">×</button>
        </div>

        <div className="modal__body">
          <div className="account-id">
            <div className="account-id__mark" aria-hidden="true">{monogram}</div>
            <div className="account-id__info">
              <div className="account-id__name">
                {auth.profile?.display_name || '—'}
                <span className="account__role-tag">{isAdmin ? 'ADMIN' : 'USER'}</span>
              </div>
              <div className="account-id__meta">
                <span className="account-id__email">{auth.user?.email}</span>
                <span className="account-id__sep">·</span>
                <span>สมาชิกตั้งแต่ {fmtDate(auth.profile?.created_at)}</span>
              </div>
            </div>
          </div>

          <div className="account__section">
            <div className="account__section-head">ข้อมูลส่วนตัว</div>
            <div className="account__grid-2">
              <div>
                <label htmlFor="gl-ac-name" className="auth-label">ชื่อ-นามสกุล</label>
                <input id="gl-ac-name" type="text" className="auth-input" value={name}
                  onChange={(e) => setName(e.target.value)} />
              </div>
              <div>
                <label htmlFor="gl-ac-org" className="auth-label">หน่วยงาน <span className="auth-label__soft">(ถ้ามี)</span></label>
                <input id="gl-ac-org" type="text" className="auth-input" value={org}
                  onChange={(e) => setOrg(e.target.value)} />
              </div>
            </div>
            <div className="account__actions">
              <button className="account__btn account__btn--primary" onClick={saveName} disabled={savingName}>
                {savingName ? 'กำลังบันทึก…' : 'บันทึกข้อมูล'}
              </button>
              {nameNote && <span className="account__note">{nameNote}</span>}
            </div>
          </div>

          <div className="account__section">
            <div className="account__section-head">การเข้าสู่ระบบ</div>

            <div className="account__sub">
              <div className="account__control-row">
                <div className="account__control">
                  <label htmlFor="gl-ac-email-new" className="auth-label">อีเมลใหม่</label>
                  <input id="gl-ac-email-new" type="email" className="auth-input" placeholder="name@example.com"
                    value={newEmail} onChange={(e) => setNewEmail(e.target.value)} />
                </div>
                <button className="account__btn" onClick={changeEmail} disabled={changingEmail}>
                  {changingEmail ? 'กำลังส่งลิงก์…' : 'เปลี่ยนอีเมล'}
                </button>
              </div>
              {emailNote && (
                <div className={`auth-note account__feedback${emailNote.ok ? '' : ' auth-note--err'}`}>{emailNote.text}</div>
              )}
            </div>

            <div className="account__sub">
              <div className="account__control-row account__control-row--pw">
                <div className="account__control">
                  <label htmlFor="gl-cp-cur" className="auth-label">รหัสผ่านปัจจุบัน</label>
                  <input id="gl-cp-cur" type="password" className="auth-input" value={cpCur}
                    onChange={(e) => setCpCur(e.target.value)} />
                </div>
                <div className="account__control">
                  <label htmlFor="gl-cp-new" className="auth-label">รหัสผ่านใหม่</label>
                  <input id="gl-cp-new" type="password" className="auth-input" placeholder="อย่างน้อย 8 ตัวอักษร"
                    value={cpNew} onChange={(e) => setCpNew(e.target.value)} />
                </div>
                <button className="account__btn" onClick={changePw} disabled={changingPw}>
                  {changingPw ? 'กำลังเปลี่ยน…' : 'เปลี่ยนรหัสผ่าน'}
                </button>
              </div>
              {cpNote && (
                <div className={`auth-note account__feedback${cpNote.ok ? '' : ' auth-note--err'}`}>{cpNote.text}</div>
              )}
            </div>
          </div>

          <div className="account__section" style={{ marginBottom: 0 }}>
            <div className="account__section-head account__section-head--crit">โซนอันตราย</div>
            {deleteErr && <div className="auth-note auth-note--err account__feedback" style={{ marginBottom: 'var(--s-3)' }}>{deleteErr}</div>}
            {!confirmingDelete ? (
              <div className="account__danger-box">
                <p>ลบบัญชีถาวร — พื้นที่ที่บันทึกไว้ทั้งหมดจะถูกลบและกู้คืนไม่ได้</p>
                <button className="account__btn--danger" onClick={() => setConfirmingDelete(true)}>ลบบัญชี</button>
              </div>
            ) : (
              <div className="account__danger-box account__danger-box--confirm">
                <p>ยืนยันการลบบัญชี? การกระทำนี้ย้อนกลับไม่ได้</p>
                <div className="account__field">
                  <label htmlFor="gl-ac-del-pw" className="auth-label">กรอกรหัสผ่านเพื่อยืนยัน</label>
                  <input id="gl-ac-del-pw" type="password" className="auth-input" value={deletePw}
                    onChange={(e) => { setDeletePw(e.target.value); setDeleteErr(''); }} />
                </div>
                <div className="account__danger-actions">
                  <button className="account__btn" onClick={() => { setConfirmingDelete(false); setDeletePw(''); setDeleteErr(''); }} disabled={deleting}>ยกเลิก</button>
                  <button className="account__btn--danger" onClick={confirmDelete} disabled={deleting}>
                    {deleting ? 'กำลังลบ…' : 'ยืนยันลบ'}
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
