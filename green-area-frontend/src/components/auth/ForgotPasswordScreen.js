import { useState } from 'react';

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export default function ForgotPasswordScreen({ auth, onGoTo }) {
  const [email, setEmail] = useState('');
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');

  const submit = async (e) => {
    e.preventDefault();
    if (busy) return;
    if (!EMAIL_RE.test(email)) return setErr('กรอกอีเมลให้ถูกต้อง');
    setErr('');
    setBusy(true);
    const res = await auth.forgotPassword(email);
    setBusy(false);
    if (!res.ok) return setErr(res.error);
    setSent(true);
  };

  return (
    <div data-screen-label="04 ลืมรหัสผ่าน">
      {err && <div className="auth-note auth-note--err">{err}</div>}
      {sent && !err && (
        <div className="auth-note">ส่งลิงก์แล้ว — ตรวจกล่องจดหมายของ {email}</div>
      )}

      <div className="auth-eyebrow">Reset password</div>
      <h1 className="auth-h1">ลืมรหัสผ่าน</h1>
      <p className="auth-sub">กรอกอีเมลที่ใช้สมัคร ระบบจะส่งลิงก์ตั้งรหัสผ่านใหม่ให้</p>

      <form onSubmit={submit}>
        <div className="auth-field" style={{ marginBottom: 'var(--s-5)' }}>
          <label htmlFor="gl-fg-email" className="auth-label">อีเมล</label>
          <input id="gl-fg-email" type="email" className="auth-input" placeholder="name@example.com"
            value={email} onChange={(e) => { setEmail(e.target.value); setErr(''); }} />
        </div>
        <button type="submit" className="auth-btn" disabled={busy}>
          {busy ? 'กำลังส่ง…' : (sent ? 'ส่งลิงก์อีกครั้ง' : 'ส่งลิงก์ตั้งรหัสผ่าน')}
        </button>
      </form>

      <div className="auth-foot">
        <button type="button" className="auth-link-btn" onClick={() => onGoTo('signin')}>← กลับไปเข้าสู่ระบบ</button>
      </div>
    </div>
  );
}
