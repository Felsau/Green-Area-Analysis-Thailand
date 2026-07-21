import { useEffect, useState } from 'react';
import SignInScreen from './SignInScreen';
import SignUpScreen from './SignUpScreen';
import ForgotPasswordScreen from './ForgotPasswordScreen';
import ResetPasswordScreen from './ResetPasswordScreen';

// Auth gate — sign in / sign up / forgot+reset password.
// Shown instead of the dashboard until `auth.user` is set (see App.js).
// Screen chrome (logo, glow, theme toggle, card, footer) lives here; each
// screen owns its own form state and calls into the `auth` (useAuth) actions.
export default function AuthGate({ auth, theme, onToggleTheme }) {
  const [screen, setScreen] = useState('signin');
  const [note, setNote] = useState(''); // one-shot success message carried across a screen change (e.g. "password reset")
  const isDark = theme === 'dark';

  // A password-reset email link lands here with a recovery session already
  // active (Supabase parses the URL fragment automatically) — jump straight
  // to the reset-password screen regardless of whatever screen was showing.
  useEffect(() => {
    if (auth.isRecovery) setScreen('reset');
  }, [auth.isRecovery]);

  const goTo = (next, carriedNote) => {
    setNote(carriedNote || '');
    setScreen(next);
  };

  return (
    <div className="auth-gate" data-screen-label="Auth gate">
      <div className="auth-gate__glow" aria-hidden="true" />
      <button
        className="auth-gate__theme-btn"
        onClick={onToggleTheme}
        title="สลับธีม"
        aria-label={isDark ? 'สลับเป็นธีมสว่าง' : 'สลับเป็นธีมมืด'}
      >
        {isDark ? '☀' : '☾'}
      </button>

      <div className="auth-brand">
        <span className="auth-brand__mark" aria-hidden="true" />
        <span className="auth-brand__name">
          GreenLens<em className="auth-brand__tagline">วิเคราะห์พื้นที่สีเขียว</em>
        </span>
      </div>

      <div className="auth-card">
        {screen === 'signin' && (
          <SignInScreen auth={auth} note={note} onGoTo={goTo} />
        )}
        {screen === 'signup' && (
          <SignUpScreen auth={auth} onGoTo={goTo} />
        )}
        {screen === 'forgot' && (
          <ForgotPasswordScreen auth={auth} onGoTo={goTo} />
        )}
        {screen === 'reset' && (
          <ResetPasswordScreen auth={auth} onGoTo={goTo} />
        )}
      </div>

      <div className="auth-gate__copyright">
        © <span style={{ fontFamily: 'var(--mono)' }}>2026</span> GreenLens · ข้อมูลดาวเทียม Sentinel-2 · Landsat 8/9
      </div>
    </div>
  );
}
