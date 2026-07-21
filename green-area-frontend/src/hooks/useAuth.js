import { useCallback, useEffect, useState } from 'react';
import { supabase, supabaseConfigured } from '../lib/supabaseClient';
import { API_BASE } from '../constants';
import { setApiAuthToken } from '../utils/apiClient';

const NOT_CONFIGURED = 'ระบบล็อกอินยังไม่ได้ตั้งค่า — ขาด VITE_SUPABASE_URL / VITE_SUPABASE_ANON_KEY';

// Supabase Auth error messages come back in English — translate the ones users
// actually hit so the all-Thai UI stays consistent. Falls back to the raw
// message (still useful signal) for anything unmapped.
const ERROR_MAP = [
  [/invalid login credentials/i, 'อีเมลหรือรหัสผ่านไม่ถูกต้อง — ลองใหม่อีกครั้ง'],
  [/email not confirmed/i, 'บัญชีนี้ยังไม่ได้ยืนยันอีเมล — ติดต่อผู้ดูแลระบบ'],
  [/user already registered|already been registered/i, 'อีเมลนี้มีผู้ใช้งานแล้ว — ลองเข้าสู่ระบบแทน'],
  [/password should be at least/i, 'รหัสผ่านสั้นเกินไป'],
  [/rate limit|security purposes/i, 'ขอถี่เกินไป — กรุณารอสักครู่แล้วลองใหม่'],
  [/user not found/i, 'ไม่พบบัญชีนี้ในระบบ'],
];

function translateAuthError(error) {
  const msg = error?.message || String(error || '');
  for (const [pattern, th] of ERROR_MAP) {
    if (pattern.test(msg)) return th;
  }
  return msg || 'เกิดข้อผิดพลาด — ลองใหม่อีกครั้ง';
}

function authHeaders(token, withJson) {
  const h = { Authorization: `Bearer ${token}` };
  if (withJson) h['Content-Type'] = 'application/json';
  return h;
}

// Central auth hook — wraps Supabase Auth (token lifecycle: signup / signin /
// forgot+reset password / sign out) directly, since that's the standard
// Supabase pattern and the anon key can't do anything RLS
// disallows. Profile data (display name, role) and account deletion instead
// go through the FastAPI backend (/account/*), which holds the service-role
// key — see routers/account.py.
export function useAuth() {
  const [session, setSession] = useState(null);
  const [profile, setProfile] = useState(null);
  const [initializing, setInitializing] = useState(true);
  const [isRecovery, setIsRecovery] = useState(false);

  const loadProfile = useCallback(async (accessToken) => {
    if (!accessToken) { setProfile(null); return; }
    try {
      const res = await fetch(`${API_BASE}/account/me`, { headers: authHeaders(accessToken) });
      const json = await res.json().catch(() => ({}));
      if (res.ok) setProfile(json);
    } catch (err) {
      console.error('load profile error:', err);
    }
  }, []);

  useEffect(() => {
    if (!supabaseConfigured) { setInitializing(false); return undefined; }
    let active = true;
    supabase.auth.getSession().then(({ data }) => {
      if (!active) return;
      setSession(data.session || null);
      setApiAuthToken(data.session?.access_token);
      if (data.session) loadProfile(data.session.access_token);
      setInitializing(false);
    });
    const { data: sub } = supabase.auth.onAuthStateChange((event, newSession) => {
      if (event === 'PASSWORD_RECOVERY') setIsRecovery(true);
      if (event === 'SIGNED_OUT') setIsRecovery(false);
      setSession(newSession);
      setApiAuthToken(newSession?.access_token);
      if (newSession) loadProfile(newSession.access_token);
      else setProfile(null);
    });
    return () => { active = false; sub.subscription.unsubscribe(); };
  }, [loadProfile]);

  const signIn = useCallback(async (email, password) => {
    if (!supabaseConfigured) return { ok: false, error: NOT_CONFIGURED };
    const { error } = await supabase.auth.signInWithPassword({ email, password });
    if (error) return { ok: false, error: translateAuthError(error) };
    return { ok: true };
  }, []);

  const signUp = useCallback(async (displayName, email, password, organization) => {
    if (!supabaseConfigured) return { ok: false, error: NOT_CONFIGURED };
    const { data, error } = await supabase.auth.signUp({
      email, password,
      options: { data: { display_name: displayName, organization: organization || undefined } },
    });
    if (error) return { ok: false, error: translateAuthError(error) };
    // identities = [] (no error) means this email already has a confirmed account —
    // Supabase silently no-ops signUp for existing users instead of erroring.
    if (data.user && data.user.identities && data.user.identities.length === 0) {
      return { ok: false, error: 'อีเมลนี้มีผู้ใช้งานแล้ว — ลองเข้าสู่ระบบแทน' };
    }
    return { ok: true };
  }, []);

  const forgotPassword = useCallback(async (email) => {
    if (!supabaseConfigured) return { ok: false, error: NOT_CONFIGURED };
    const { error } = await supabase.auth.resetPasswordForEmail(email, {
      redirectTo: window.location.origin,
    });
    if (error) return { ok: false, error: translateAuthError(error) };
    return { ok: true };
  }, []);

  // Only meaningful inside the recovery session established by clicking the
  // reset-password email link (isRecovery === true).
  const resetPassword = useCallback(async (newPassword) => {
    if (!supabaseConfigured) return { ok: false, error: NOT_CONFIGURED };
    const { error } = await supabase.auth.updateUser({ password: newPassword });
    if (error) return { ok: false, error: translateAuthError(error) };
    // A leaked/guessed old password shouldn't still work on other devices
    // after a reset — best-effort, doesn't block success on failure.
    await supabase.auth.signOut({ scope: 'others' }).catch(() => {});
    setIsRecovery(false);
    return { ok: true };
  }, []);

  const changePassword = useCallback(async (currentPassword, newPassword) => {
    if (!supabaseConfigured) return { ok: false, error: NOT_CONFIGURED };
    const email = session?.user?.email;
    if (!email) return { ok: false, error: 'เซสชันหมดอายุ — เข้าสู่ระบบใหม่อีกครั้ง' };
    // Re-verify the current password via a real sign-in attempt before changing it.
    const { error: signInErr } = await supabase.auth.signInWithPassword({ email, password: currentPassword });
    if (signInErr) return { ok: false, error: 'รหัสผ่านปัจจุบันไม่ถูกต้อง' };
    const { error } = await supabase.auth.updateUser({ password: newPassword });
    if (error) return { ok: false, error: translateAuthError(error) };
    await supabase.auth.signOut({ scope: 'others' }).catch(() => {});
    return { ok: true };
  }, [session]);

  // Supabase's default "secure email change" sends a confirmation link to
  // both the old and new address — the change only takes effect once (both)
  // links are clicked, so `session.user.email` doesn't flip immediately here.
  const changeEmail = useCallback(async (newEmail) => {
    if (!supabaseConfigured) return { ok: false, error: NOT_CONFIGURED };
    const { error } = await supabase.auth.updateUser({ email: newEmail });
    if (error) return { ok: false, error: translateAuthError(error) };
    return { ok: true };
  }, []);

  const updateProfile = useCallback(async (displayName, organization) => {
    const token = session?.access_token;
    if (!token) return { ok: false, error: 'เซสชันหมดอายุ — เข้าสู่ระบบใหม่อีกครั้ง' };
    try {
      const res = await fetch(`${API_BASE}/account/me`, {
        method: 'PATCH',
        headers: authHeaders(token, true),
        body: JSON.stringify({ display_name: displayName, organization: organization || null }),
      });
      const json = await res.json().catch(() => ({}));
      if (!res.ok) return { ok: false, error: json.detail || 'บันทึกข้อมูลไม่สำเร็จ' };
      setProfile(json);
      return { ok: true };
    } catch (err) {
      console.error('update profile error:', err);
      return { ok: false, error: 'บันทึกข้อมูลไม่สำเร็จ — ตรวจการเชื่อมต่อ' };
    }
  }, [session]);

  // Requires the current password even though the session token alone would
  // be enough to authorize the call — a walk-away/unlocked-tab attacker with
  // the session but not the password shouldn't be able to delete the account.
  const deleteAccount = useCallback(async (currentPassword) => {
    const token = session?.access_token;
    if (!token) return { ok: false, error: 'เซสชันหมดอายุ — เข้าสู่ระบบใหม่อีกครั้ง' };
    const email = session?.user?.email;
    if (!currentPassword) return { ok: false, error: 'กรอกรหัสผ่านเพื่อยืนยัน' };
    if (email) {
      const { error: signInErr } = await supabase.auth.signInWithPassword({ email, password: currentPassword });
      if (signInErr) return { ok: false, error: 'รหัสผ่านไม่ถูกต้อง' };
    }
    try {
      const res = await fetch(`${API_BASE}/account/me`, {
        method: 'DELETE', headers: authHeaders(token),
      });
      if (!res.ok) {
        const json = await res.json().catch(() => ({}));
        return { ok: false, error: json.detail || 'ลบบัญชีไม่สำเร็จ' };
      }
      await supabase.auth.signOut();
      return { ok: true };
    } catch (err) {
      console.error('delete account error:', err);
      return { ok: false, error: 'ลบบัญชีไม่สำเร็จ — ตรวจการเชื่อมต่อ' };
    }
  }, [session]);

  const signOut = useCallback(async () => {
    if (!supabaseConfigured) return;
    await supabase.auth.signOut();
  }, []);

  return {
    user: session?.user || null,
    profile,
    initializing,
    isRecovery,
    configured: supabaseConfigured,
    signIn, signUp,
    forgotPassword, resetPassword, changePassword, changeEmail,
    updateProfile, deleteAccount, signOut,
  };
}
