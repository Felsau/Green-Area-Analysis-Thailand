// Attaches the signed-in user's Supabase access token to requests against our
// own backend (API_BASE) so protected endpoints work — most of the app is
// gated behind login already (see App.js/AuthGate), the backend now enforces
// that at the API layer too. useAuth calls setApiAuthToken() on session change.
import { API_BASE } from '../constants';

let currentToken = null;

export function setApiAuthToken(token) {
  currentToken = token || null;
}

// url ต้องขึ้นต้นด้วย API_BASE เท่านั้นถึงจะแนบ token — ทุก call site วันนี้ใช้
// ${API_BASE}/... อยู่แล้วก็จริง แต่ apiFetch เป็น wrapper ที่ทุกคนเรียกได้ ถ้าวันหลัง
// เผลอส่ง URL ที่มาจาก response ตรงๆ (เช่น GEE tile_url จาก maps/tiles.py) เข้ามา
// การเช็คนี้กัน access token หลุดไปโดเมนที่สาม
function withAuthHeaders(url, options = {}) {
  if (!currentToken || !url.startsWith(API_BASE)) return options;
  return {
    ...options,
    headers: { ...(options.headers || {}), Authorization: `Bearer ${currentToken}` },
  };
}

// Drop-in replacement for fetch() against the backend API. No-op (plain
// fetch) when no session token is set — safe to use even for endpoints that
// stay public (e.g. /analysis/ranking).
export function apiFetch(url, options) {
  return fetch(url, withAuthHeaders(url, options));
}
