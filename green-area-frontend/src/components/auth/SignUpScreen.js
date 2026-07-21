import { useState } from 'react';
import LegalModal from './LegalModal';

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export default function SignUpScreen({ auth, onGoTo }) {
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [pw, setPw] = useState('');
  const [showPw, setShowPw] = useState(false);
  const [org, setOrg] = useState('');
  const [agree, setAgree] = useState(false);
  const [tried, setTried] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const [legalDoc, setLegalDoc] = useState(null); // 'terms' | 'privacy' | null

  const submit = async (e) => {
    e.preventDefault();
    if (busy) return;
    setTried(true);
    if (!name.trim()) return setErr('กรอกชื่อ-นามสกุล');
    if (!EMAIL_RE.test(email)) return setErr('กรอกอีเมลให้ถูกต้อง');
    if (pw.length < 8) return setErr('รหัสผ่านต้องยาวอย่างน้อย 8 ตัวอักษร');
    if (!agree) return setErr('กรุณายอมรับข้อกำหนดการใช้งานและนโยบายความเป็นส่วนตัว');
    setErr('');
    setBusy(true);
    const res = await auth.signUp(name.trim(), email, pw, org.trim());
    setBusy(false);
    if (!res.ok) return setErr(res.error);
    // on success, useAuth's onAuthStateChange sets `user` → App.js swaps to the dashboard
  };

  return (
    <div data-screen-label="02 สมัครสมาชิก">
      {err && <div className="auth-note auth-note--err">{err}</div>}

      <div className="auth-eyebrow">Register</div>
      <h1 className="auth-h1">สมัครสมาชิก</h1>
      <p className="auth-sub">สมัครด้วยอีเมล ใช้งานได้ทันที</p>

      <form onSubmit={submit}>
        <div className="auth-field auth-field--tight">
          <label htmlFor="gl-su-name" className="auth-label">ชื่อ-นามสกุล</label>
          <input id="gl-su-name" type="text" className="auth-input" value={name}
            onChange={(e) => { setName(e.target.value); setErr(''); }} />
        </div>
        <div className="auth-field auth-field--tight">
          <label htmlFor="gl-su-email" className="auth-label">อีเมล</label>
          <input id="gl-su-email" type="email" className="auth-input" placeholder="name@example.com"
            value={email} onChange={(e) => { setEmail(e.target.value); setErr(''); }} />
        </div>
        <div className="auth-field auth-field--tight">
          <label htmlFor="gl-su-org" className="auth-label">หน่วยงาน <span style={{ textTransform: 'none', fontWeight: 400 }}>(ถ้ามี)</span></label>
          <input id="gl-su-org" type="text" className="auth-input" value={org}
            onChange={(e) => setOrg(e.target.value)} />
        </div>
        <div className="auth-field" style={{ marginBottom: 'var(--s-5)' }}>
          <label htmlFor="gl-su-pw" className="auth-label">รหัสผ่าน</label>
          <div className="auth-input-wrap">
            <input id="gl-su-pw" type={showPw ? 'text' : 'password'} className="auth-input auth-input--pw"
              value={pw} onChange={(e) => { setPw(e.target.value); setErr(''); }} />
            <button type="button" className="auth-input-toggle" onClick={() => setShowPw(v => !v)}>
              {showPw ? 'ซ่อน' : 'แสดง'}
            </button>
          </div>
          <div className="auth-hint" style={{ color: tried && pw.length < 8 ? 'var(--warn)' : 'var(--ink-3)' }}>
            อย่างน้อย <span style={{ fontFamily: 'var(--mono)' }}>8</span> ตัวอักษร — แนะนำให้มีตัวเลขและสัญลักษณ์
          </div>
        </div>
        <label className="auth-check">
          <input type="checkbox" checked={agree}
            onChange={(e) => { setAgree(e.target.checked); setErr(''); }} />
          <span>ฉันยอมรับข้อกำหนดการใช้งานและนโยบายความเป็นส่วนตัว</span>
        </label>
        <p className="auth-hint" style={{ marginTop: '-10px', marginBottom: 'var(--s-4)' }}>
          อ่าน{' '}
          <button type="button" className="auth-link-btn" onClick={() => setLegalDoc('terms')}>ข้อกำหนดการใช้งาน</button>
          {' '}และ{' '}
          <button type="button" className="auth-link-btn" onClick={() => setLegalDoc('privacy')}>นโยบายความเป็นส่วนตัว</button>
        </p>
        <button type="submit" className="auth-btn" disabled={busy}>
          {busy ? 'กำลังสร้างบัญชี…' : 'สร้างบัญชี →'}
        </button>
      </form>

      <div className="auth-foot">
        มีบัญชีแล้ว?{' '}
        <button type="button" className="auth-link-btn" onClick={() => onGoTo('signin')}>เข้าสู่ระบบ</button>
      </div>

      <LegalModal open={!!legalDoc} doc={legalDoc} onClose={() => setLegalDoc(null)} />
    </div>
  );
}
