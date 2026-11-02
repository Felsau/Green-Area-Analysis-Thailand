import { Suspense, lazy, useEffect, useState } from 'react';
import './App.css';

import { useTheme }       from './hooks/useTheme';
import { useAuth }        from './hooks/useAuth';
import { useLandingGate } from './hooks/useLandingGate';
import Toast      from './components/Toast';
import BackendWakingBanner from './components/BackendWakingBanner';
import Landing from './components/Landing';
import AuthGate from './components/auth/AuthGate';
import CookieConsent from './components/CookieConsent';
import LegalModal from './components/auth/LegalModal';
import { pushError } from './utils/toast';
import { useGisAccess } from './hooks/useGisAccess';

// The dashboard carries deck.gl, maplibre, turf, recharts and every sidebar
// tab. None of it renders on the landing page or the auth gate, so it loads on
// demand instead of sitting in the entry chunk — a first-time visitor gets to
// the marketing page without paying for the map engine first.
const Dashboard = lazy(() => import('./Dashboard'));
const GisManagement = lazy(() => import('./components/GisManagement'));

// Brand splash — shared by the "resolving session" state and the Suspense
// fallback while the dashboard chunk is in flight, so the handoff into the map
// is one continuous screen rather than a flash of something else.
function BrandSplash() {
  return (
    <div className="auth-gate">
      <div className="auth-gate__glow" aria-hidden="true" />
      <div className="auth-brand">
        <span className="auth-brand__mark" aria-hidden="true" />
        <span className="auth-brand__name">GreenLens</span>
      </div>
    </div>
  );
}

function App() {
  const [thailandData, setThailandData] = useState(null);
  const [loading, setLoading]           = useState(true);
  const [cookieSettings, setCookieSettings] = useState(false);
  const [legalDoc, setLegalDoc]         = useState(null);
  const { theme, toggleTheme } = useTheme();
  const auth = useAuth();
  const gisAccess = useGisAccess(auth.user?.id);
  const [gisView, setGisView] = useState(() => new URLSearchParams(window.location.search).get('view') === 'gis');
  useEffect(() => {
    const update = () => setGisView(new URLSearchParams(window.location.search).get('view') === 'gis');
    window.addEventListener('popstate', update);
    return () => window.removeEventListener('popstate', update);
  }, []);
  const navigateGis = open => {
    const url = new URL(window.location.href);
    if (open) url.searchParams.set('view', 'gis'); else url.searchParams.delete('view');
    window.history.pushState(null, '', url);
    setGisView(open);
  };

  // Landing gate — shown once per browser session. Shared deep-links
  // (?p= ?d= ?tab= ?year=) must keep opening the dashboard directly.
  // Signing in is required for the dashboard itself (see the auth.user check
  // below), so a returning signed-in visitor skips the marketing page too.
  const { showLanding, enterDashboard, goToLanding } = useLandingGate();

  // Province boundaries — fetched here rather than inside Dashboard so the
  // request starts while the landing page is still up (entry into the map then
  // feels instant), and so it doesn't pull the dashboard chunk in early.
  useEffect(() => {
    fetch('/thailand.json')
      .then(r => r.json())
      .then(data => { setThailandData(data); setLoading(false); })
      .catch(() => {
        setLoading(false);
        pushError('โหลดขอบเขตจังหวัดไม่สำเร็จ — รีเฟรชหน้าเว็บใหม่');
      });
  }, []);

  // Still resolving any existing Supabase session — brief, avoids a landing/
  // auth-gate flash for a returning signed-in visitor.
  if (auth.initializing) return <BrandSplash />;

  // แถบขอความยินยอมคุกกี้ + นโยบายคุกกี้ — ต้อง render ทุก branch (หน้าแรก / หน้า
  // ล็อกอิน / แดชบอร์ด) เพราะต้องได้รับความยินยอมก่อนบันทึกอะไรลงเบราว์เซอร์
  // ตั้งแต่หน้าจอแรกที่ผู้ใช้เห็น ไม่ใช่หลังล็อกอิน
  const consentLayer = (
    <>
      <CookieConsent
        settingsOpen={cookieSettings}
        onSettingsOpenChange={setCookieSettings}
        onOpenPolicy={() => setLegalDoc('cookies')}
      />
      <LegalModal open={!!legalDoc} doc={legalDoc} onClose={() => setLegalDoc(null)} />
    </>
  );

  // Landing view — the dashboard (map, sidebar) isn't mounted yet, but the
  // effect above already prefetches /thailand.json so entry feels instant.
  // Skipped entirely for an already-signed-in visitor (auth.user).
  const screen = showLanding && !auth.user && !gisView ? (
    <Landing
      onEnter={enterDashboard}
      theme={theme}
      onToggleTheme={toggleTheme}
      onCookieSettings={() => setCookieSettings(true)}
      onOpenPolicy={setLegalDoc}
    />
  // Auth gate — signing in is required to reach the dashboard. A recovery
  // session (from clicking the reset-password email link) also sets
  // auth.user, so it must be checked here too or AuthGate never mounts and
  // the visitor lands straight in the dashboard instead of ตั้งรหัสผ่านใหม่.
  ) : !auth.user || auth.isRecovery ? (
    <AuthGate auth={auth} theme={theme} onToggleTheme={toggleTheme} />
  ) : (
    <Suspense fallback={<BrandSplash />}>
      {gisView ? <GisManagement access={gisAccess} userId={auth.user.id} onBack={() => navigateGis(false)} /> : <Dashboard
        thailandData={thailandData}
        loading={loading}
        theme={theme}
        onToggleTheme={toggleTheme}
        auth={auth}
        onGoHome={goToLanding}
        onCookieSettings={() => setCookieSettings(true)}
        onOpenPolicy={setLegalDoc}
        onOpenGis={gisAccess.allowed ? () => navigateGis(true) : undefined}
      />}
    </Suspense>
  );

  return (
    <>
      {screen}
      <BackendWakingBanner />
      <Toast />
      {consentLayer}
    </>
  );
}

export default App;
