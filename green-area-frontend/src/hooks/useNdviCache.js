import { useState, useEffect } from 'react';
import { API_BASE } from '../constants';
import { pushError } from '../utils/toast';
import { apiFetch } from '../utils/apiClient';

// Retry the fetch a few times before surfacing an error. A freshly
// minted access token (right after login/refresh) can be briefly rejected by
// the backend with 401 — its nbf/iat sits a second or two ahead of the server
// clock (normal small skew), then verifies fine moments later. /account/me
// self-heals because useAuth re-fires on auth-state changes; this one-shot
// fetch had no such retry, so a transient 401 left the map permanently
// colourless until a manual refresh. A short backoff covers that window.
const CACHE_RETRIES = 4;
const CACHE_RETRY_MS = 1500;

const sleep = (ms) => new Promise(r => setTimeout(r, ms));

// enabled: defer the fetch until the caller is ready (e.g. signed in) —
// the endpoint requires auth, so firing this before login just 401s.
//
// /cache/ndvi-latest returns exactly what the choropleth needs — one NDVI value
// per province, already reduced to the newest year server-side. It replaced a
// /cache fetch that pulled every province × every year (plus a monthly array
// nothing read) and did the same reduction in the browser: the payload grew
// with each computed year while the useful output stayed 77 numbers.
export function useNdviCache(enabled = true) {
  const [ndviCache, setNdviCache] = useState({});

  useEffect(() => {
    if (!enabled) return undefined;
    let cancelled = false;  // enabled flip / unmount → stop retrying

    const load = async () => {
      for (let attempt = 0; attempt <= CACHE_RETRIES; attempt++) {
        try {
          const r = await apiFetch(`${API_BASE}/cache/ndvi-latest`);
          if (!r.ok) throw new Error(`HTTP ${r.status}`);
          const json = await r.json();
          if (cancelled) return;
          setNdviCache(json.data || {});
          return;  // success
        } catch (err) {
          if (cancelled) return;
          if (attempt < CACHE_RETRIES) {
            await sleep(CACHE_RETRY_MS);  // token likely still settling — try again
            continue;
          }
          console.warn('NDVI cache load failed after retries:', err);
          pushError('โหลด NDVI cache ไม่สำเร็จ — แผนที่อาจไม่มีสี ลองรีเฟรชหน้าเว็บ');
        }
      }
    };

    load();
    return () => { cancelled = true; };
  }, [enabled]);

  return { ndviCache, setNdviCache };
}
