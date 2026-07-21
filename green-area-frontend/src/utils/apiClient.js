// Attaches the signed-in user's Supabase access token to requests against our
// own backend (API_BASE) so protected endpoints work — most of the app is
// gated behind login already (see App.js/AuthGate), the backend now enforces
// that at the API layer too. useAuth calls setApiAuthToken() on session change.
let currentToken = null;

export function setApiAuthToken(token) {
  currentToken = token || null;
}

function withAuthHeaders(options = {}) {
  if (!currentToken) return options;
  return {
    ...options,
    headers: { ...(options.headers || {}), Authorization: `Bearer ${currentToken}` },
  };
}

// Drop-in replacement for fetch() against the backend API. No-op (plain
// fetch) when no session token is set — safe to use even for endpoints that
// stay public (e.g. /analysis/ranking).
export function apiFetch(url, options) {
  return fetch(url, withAuthHeaders(options));
}
