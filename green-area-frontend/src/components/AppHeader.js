import UserMenu from './UserMenu';

export default function AppHeader({
  loading, sidebarCollapsed, onToggleSidebar, theme, onToggleTheme, onShowAbout, onGoHome,
  user, profile, onShowAccount, onSavedAreas, onSignOut,
}) {
  const isDark = theme === 'dark';
  return (
    <header className="topbar">
      <button className="topbar__brand" onClick={onGoHome} title="กลับหน้าแรก">
        <div className="topbar__mark" aria-hidden="true" />
        <div className="topbar__title">
          Green Area Analysis<em>Thailand</em>
        </div>
      </button>
      <div className="topbar__meta">
        <span className="topbar__source"><strong>Sentinel-2</strong> · Google Earth Engine</span>
      </div>
      <button
        className="topbar__icon-btn"
        onClick={onShowAbout}
        aria-label="ข้อมูลและระเบียบวิธี"
        title="ข้อมูลและระเบียบวิธี"
      >
        ⓘ
      </button>
      <button
        className="topbar__icon-btn"
        onClick={onToggleTheme}
        aria-label={isDark ? 'สลับเป็นธีมสว่าง' : 'สลับเป็นธีมมืด'}
        title={isDark ? 'ธีมสว่าง' : 'ธีมมืด'}
      >
        {isDark ? '☀' : '☾'}
      </button>
      <button
        className="topbar__sidebar-toggle"
        onClick={onToggleSidebar}
        aria-label={sidebarCollapsed ? 'แสดงแผงข้อมูล' : 'ซ่อนแผงข้อมูล'}
      >
        {sidebarCollapsed ? 'แสดงแผง ›' : '‹ ซ่อนแผง'}
      </button>
      {user && (
        <UserMenu
          displayName={profile?.display_name}
          email={user.email}
          isAdmin={profile?.role === 'admin'}
          onAccount={onShowAccount}
          onSavedAreas={onSavedAreas}
          onSignOut={onSignOut}
        />
      )}
      {loading && <div className="loading-bar" />}
    </header>
  );
}
