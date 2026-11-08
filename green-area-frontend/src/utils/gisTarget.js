// The one target the GIS screens are allowed to talk to. Mirrors
// green-area-backend/gis_target.py: the browser reaches its own conclusion
// about the target from its own configuration, and the backend reaches the
// same conclusion from its own. Neither trusts the other's answer.
//
// A target is never assumed. Nothing is configured by default, and every part
// of the target has to be stated and has to agree with every other part, so a
// half-set deployment selects nothing rather than selecting something unsafe.

export const LOCAL_TARGET = Object.freeze({
  name: 'local-t0',
  api: 'http://127.0.0.1:55422',
  auth: 'http://127.0.0.1:55421',
  issuer: 'http://127.0.0.1:55421/auth/v1',
});

const LOCAL_HOSTS = ['localhost', '127.0.0.1'];
// A Supabase project ref: twenty lowercase letters, exactly as the backend
// reads it out of the hostname and stores it as the cluster identity.
const CLOUD_AUTH = /^https:\/\/[a-z]{20}\.supabase\.co$/;
// An https origin and nothing else: no port, path, query, fragment or
// credentials, and at least one dot so a bare host cannot slip through.
const CLOUD_API = /^https:\/\/[a-z0-9-]{1,63}(?:\.[a-z0-9-]{1,63})+$/;

const clean = value => (typeof value === 'string' ? value.trim() : '');

// Returns the target, or null when the configuration does not describe one.
export function gisTarget(env = import.meta.env, location = window.location, authUrl = '') {
  if (env?.VITE_GIS_ENABLED !== 'true') return null;
  const api = clean(env.VITE_GIS_API_URL);
  const auth = clean(authUrl);
  // The backend URL is stated twice, by two different variables, and the two
  // statements have to agree — the same rule the backend applies to itself.
  if (!api || api !== clean(env.VITE_API_URL)) return null;

  if (location?.protocol === 'http:' && LOCAL_HOSTS.includes(location.hostname)) {
    return api === LOCAL_TARGET.api && auth === LOCAL_TARGET.auth ? LOCAL_TARGET : null;
  }
  // Off the development machine the page itself must be served over TLS,
  // or the session token would travel in clear text to reach it.
  if (location?.protocol !== 'https:') return null;
  if (!CLOUD_API.test(api) || !CLOUD_AUTH.test(auth)) return null;
  return Object.freeze({ name: 'cloud', api, auth, issuer: `${auth}/auth/v1` });
}
