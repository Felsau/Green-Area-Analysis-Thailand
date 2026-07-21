import { useState } from 'react';

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export default function SignInScreen({ auth, note, onGoTo }) {
  const [email, setEmail] = useState('');
  const [pw, setPw] = useState('');
  const [showPw, setShowPw] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');

  const submit = async (e) => {
    e.preventDefault();
    if (busy) return;
    if (!EMAIL_RE.test(email)) return setErr('กรอกอีเมลให้ถูกต้อง เช่น name@agency.go.th');
    if (pw.length < 8) return setErr('อีเมลหรือรหัสผ่านไม่ถูกต้อง — ลองใหม่อีกครั้ง');
    setErr('');
    setBusy(true);
    const res = await auth.signIn(email, pw);
    setBusy(false);
    if (!res.ok) setErr(res.error);
    // on success, useAuth's onAuthStateChange sets `user` → App.js swaps to the dashboard
  };

  const message = err || note;
  const isErr = !!err;

  return (
    <div data-screen-label="01 เข้าสู่ระบบ">
      {message && <div className={`auth-note${isErr ? ' auth-note--err' : ''}`}>{message}</div>}

      <div className="auth-eyebrow">Sign in</div>
      <h1 className="auth-h1">เข้าสู่ระบบ</h1>
      <p className="auth-sub">เข้าถึงแดชบอร์ด NDVI / LST ครบทั้ง 77 จังหวัด</p>

      <form onSubmit={submit}>
        <div className="auth-field">
          <label htmlFor="gl-si-email" className="auth-label">อีเมล</label>
          <input
            id="gl-si-email" type="email" className="auth-input"
            placeholder="name@example.com" value={email}
            onChange={(e) => { setEmail(e.target.value); setErr(''); }}
          />
        </div>
        <div className="auth-field" style={{ marginBottom: 'var(--s-5)' }}>
          <div className="auth-row-between">
            <label htmlFor="gl-si-pw" className="auth-label" style={{ marginBottom: 0 }}>รหัสผ่าน</label>
            <button type="button" className="auth-link-btn" onClick={() => onGoTo('forgot')}>ลืมรหัสผ่าน?</button>
          </div>
          <div className="auth-input-wrap">
            <input
              id="gl-si-pw" type={showPw ? 'text' : 'password'} className="auth-input auth-input--pw"
              placeholder="อย่างน้อย 8 ตัวอักษร" value={pw}
              onChange={(e) => { setPw(e.target.value); setErr(''); }}
            />
            <button type="button" className="auth-input-toggle" onClick={() => setShowPw(v => !v)}>
              {showPw ? 'ซ่อน' : 'แสดง'}
            </button>
          </div>
        </div>
        <button type="submit" className="auth-btn" disabled={busy}>
          {busy ? 'กำลังตรวจสอบ…' : 'เข้าสู่ระบบ →'}
        </button>
      </form>

      <div className="auth-foot">
        ยังไม่มีบัญชี?{' '}
        <button type="button" className="auth-link-btn" onClick={() => onGoTo('signup')}>สมัครสมาชิก</button>
      </div>
    </div>
  );
}
