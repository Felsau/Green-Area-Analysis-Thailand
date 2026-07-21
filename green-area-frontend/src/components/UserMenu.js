import { useState } from 'react';

// User avatar + dropdown in the topbar — account settings, saved areas, sign out.
export default function UserMenu({ displayName, email, isAdmin, onAccount, onSavedAreas, onSignOut }) {
  const [open, setOpen] = useState(false);
  const initial = (displayName || email || '?').trim().charAt(0).toUpperCase();

  const pick = (fn) => () => { setOpen(false); fn(); };

  return (
    <div className="usermenu">
      <button className="usermenu__trigger" onClick={() => setOpen(o => !o)}>
        <span className="usermenu__avatar">{initial}</span>
        <span className="usermenu__name">{displayName || email}</span>
        <span className="usermenu__chevron">▾</span>
      </button>

      {open && (
        <>
          <button className="usermenu__scrim" aria-label="ปิดเมนู" onClick={() => setOpen(false)} />
          <div className="usermenu__panel" role="menu" data-screen-label="เมนูผู้ใช้">
            <div className="usermenu__panel-head">
              <div className="usermenu__panel-name">{displayName || email}</div>
              <div className="usermenu__panel-email">{email}</div>
              <div className="usermenu__panel-role">
                <span className="usermenu__role-label">บทบาท</span>
                <span className="account__role-tag">{isAdmin ? 'ADMIN' : 'USER'}</span>
              </div>
            </div>
            <div className="usermenu__panel-items">
              <button role="menuitem" className="usermenu__item usermenu__item--active" onClick={pick(onAccount)}>
                บัญชีผู้ใช้<span>→</span>
              </button>
              <button role="menuitem" className="usermenu__item" onClick={pick(onSavedAreas)}>
                พื้นที่ที่บันทึกไว้
              </button>
              {isAdmin && (
                <button role="menuitem" className="usermenu__item" onClick={() => setOpen(false)}>
                  จัดการระบบ<span>→</span>
                </button>
              )}
            </div>
            <div className="usermenu__panel-signout">
              <button role="menuitem" className="usermenu__item" onClick={pick(onSignOut)}>ออกจากระบบ</button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
