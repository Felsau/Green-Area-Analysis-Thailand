import { useState } from 'react';

export default function ResetPasswordScreen({ auth, onGoTo }) {
  const [pw, setPw] = useState('');
  const [pw2, setPw2] = useState('');
  const [showPw, setShowPw] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const email = auth.user?.email || '';

  const submit = async (e) => {
    e.preventDefault();
    if (busy) return;
    if (pw.length < 8) return setErr('รหัสผ่านใหม่ต้องยาวอย่างน้อย 8 ตัวอักษร');
    if (pw !== pw2) return setErr('รหัสผ่านทั้งสองช่องไม่ตรงกัน');
    setErr('');
    setBusy(true);
    const res = await auth.resetPassword(pw);
    setBusy(false);
    if (!res.ok) return setErr(res.error);
    // Signing out forces a fresh sign-in with the new password, matching the
    // mockup's "→ signin ด้วยรหัสผ่านใหม่" hand-off (a recovery session
    // shouldn't quietly become the app session).
    await auth.signOut();
    onGoTo('signin', 'ตั้งรหัสผ่านใหม่แล้ว — เข้าสู่ระบบด้วยรหัสผ่านใหม่');
  };

  return (
    <div data-screen-label="05 ตั้งรหัสผ่านใหม่">
      {err && <div className="auth-note auth-note--err">{err}</div>}

      <div className="auth-eyebrow">New password</div>
      <h1 className="auth-h1">ตั้งรหัสผ่านใหม่</h1>
      <p className="auth-sub">
        สำหรับบัญชี <span style={{ fontFamily: 'var(--mono)', color: 'var(--ink-1)' }}>{email}</span>
      </p>

      <form onSubmit={submit}>
        <div className="auth-field auth-field--tight">
          <label htmlFor="gl-rs-pw" className="auth-label">รหัสผ่านใหม่</label>
          <div className="auth-input-wrap">
            <input id="gl-rs-pw" type={showPw ? 'text' : 'password'} className="auth-input auth-input--pw"
              placeholder="อย่างน้อย 8 ตัวอักษร"
              value={pw} onChange={(e) => { setPw(e.target.value); setErr(''); }} />
            <button type="button" className="auth-input-toggle" onClick={() => setShowPw(v => !v)}>
              {showPw ? 'ซ่อน' : 'แสดง'}
            </button>
          </div>
        </div>
        <div className="auth-field" style={{ marginBottom: 'var(--s-5)' }}>
          <label htmlFor="gl-rs-pw2" className="auth-label">ยืนยันรหัสผ่านใหม่</label>
          <input id="gl-rs-pw2" type={showPw ? 'text' : 'password'} className="auth-input"
            value={pw2} onChange={(e) => { setPw2(e.target.value); setErr(''); }} />
        </div>
        <button type="submit" className="auth-btn" disabled={busy}>
          {busy ? 'กำลังบันทึก…' : 'บันทึกรหัสผ่านใหม่'}
        </button>
      </form>

      <div className="auth-hint" style={{ marginTop: 'var(--s-3)' }}>
        ลิงก์นี้ใช้ได้ครั้งเดียวและหมดอายุใน <span style={{ fontFamily: 'var(--mono)' }}>60</span> นาที
      </div>
    </div>
  );
}
