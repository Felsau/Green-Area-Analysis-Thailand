import { API_BASE, API_COMPUTE_TIMEOUT_MS } from '../constants';
import { fetchWithRetry } from './fetchRetry';

// Fetch a GEE raster tile descriptor ({ tile_url, kind, min, max, palette }) for
// a province/district + metric ('ndvi'|'lst') + year. Shared by the single
// overlay and the swipe-compare hook.
export async function fetchTileInfo(kind, provinceEN, districtEN, year, signal) {
  const enc = encodeURIComponent;
  const qs = `year=${year}${districtEN ? `&district_name=${enc(districtEN)}` : ''}`;
  const res = await fetchWithRetry(
    `${API_BASE}/maps/${enc(provinceEN)}/${kind}-tiles?${qs}`, { signal }, { timeoutMs: API_COMPUTE_TIMEOUT_MS });
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try { const j = await res.json(); if (j?.detail) detail = j.detail; }
    catch { /* not JSON — keep status */ }
    const e = new Error(detail);
    e.status = res.status;
    throw e;
  }
  const json = await res.json();
  return { ...json, kind };
}

// Fetch a year-over-year DIFFERENCE tile (image(yearB) − image(yearA)) for a
// metric. Response already carries { tile_url, kind:'<m>-diff', diff:true,
// year_a, year_b, min, max, palette }.
export async function fetchDiffTile(kind, provinceEN, districtEN, yearA, yearB, signal) {
  const enc = encodeURIComponent;
  const qs = `year_a=${yearA}&year_b=${yearB}${districtEN ? `&district_name=${enc(districtEN)}` : ''}`;
  const res = await fetchWithRetry(
    `${API_BASE}/maps/${enc(provinceEN)}/${kind}-diff-tiles?${qs}`, { signal }, { timeoutMs: API_COMPUTE_TIMEOUT_MS });
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try { const j = await res.json(); if (j?.detail) detail = j.detail; }
    catch { /* not JSON — keep status */ }
    const e = new Error(detail);
    e.status = res.status;
    throw e;
  }
  return res.json();
}
