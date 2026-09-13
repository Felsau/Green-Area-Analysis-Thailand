import { useState, useCallback, useEffect, useRef } from 'react';
import { API_BASE, API_COMPUTE_TIMEOUT_MS } from '../constants';
import { pushError } from '../utils/toast';
import { fetchWithRetry } from '../utils/fetchRetry';

// Live raster overlay (real pixel-level NDVI/LST tiles) drawn over the basemap,
// versus the province choropleth which only shows admin-unit averages.
// overlay: 'none' | 'ndvi' | 'lst'. tileInfo = { tile_url, kind, min, max, palette }.
export function useRasterOverlay() {
  const [overlay, setOverlay]   = useState('none');
  const [tileInfo, setTileInfo] = useState(null);
  const [loading, setLoading]   = useState(false);
  // last-call-wins: a newer tile request aborts the previous one
  const abortRef = useRef(null);

  const fetchTiles = useCallback(async (kind, provinceEN, districtEN, year) => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    const { signal } = controller;

    setLoading(true);
    setTileInfo(null);
    try {
      const enc = encodeURIComponent;
      const qs = `year=${year}${districtEN ? `&district_name=${enc(districtEN)}` : ''}`;
      const url = `${API_BASE}/maps/${enc(provinceEN)}/${kind}-tiles?${qs}`;
      const res = await fetchWithRetry(url, { signal }, { timeoutMs: API_COMPUTE_TIMEOUT_MS });
      if (signal.aborted) return;
      if (!res.ok) {
        let detail = `HTTP ${res.status}`;
        try { const j = await res.json(); if (j?.detail) detail = j.detail; }
        catch { /* not JSON — keep status */ }
        throw new Error(detail);
      }
      const json = await res.json();
      if (signal.aborted) return;
      setTileInfo({ ...json, kind });
    } catch (err) {
      if (err?.name === 'AbortError') return;
      console.error('fetchTiles error:', err);
      pushError('โหลด raster overlay ไม่สำเร็จ — ' + (err?.message || err));
      setTileInfo(null);
    } finally {
      if (abortRef.current === controller) {
        abortRef.current = null;
        setLoading(false);
      }
    }
  }, []);

  const clearOverlay = useCallback(() => {
    abortRef.current?.abort();
    setOverlay('none');
    setTileInfo(null);
  }, []);

  // unmount → cancel pending request
  useEffect(() => () => abortRef.current?.abort(), []);

  return { overlay, setOverlay, tileInfo, loading, fetchTiles, clearOverlay };
}
