import { useCallback, useState } from 'react';
import { API_BASE } from '../constants';
import { pushError } from '../utils/toast';
import { fetchWithRetry } from '../utils/fetchRetry';

// NDVI ↔ LST cooling analysis (province-level, reads cached district rows).
// Fetch-on-demand like useTrendData — no auto-fetch on province select.
// coolingYear starts as null = "the latest year with enough district data": the
// backend picks it, and the response's year is then written back into the selector.
// Defaulting to the calendar year showed a sign-flipped slope from a handful of
// cached districts (Bangkok 2026: 5 of 50 districts, +11.3 °C per NDVI).
export function useCoolingData() {
  const [coolingData, setCoolingData]       = useState(null);
  const [coolingLoading, setCoolingLoading] = useState(false);
  const [coolingYear, setCoolingYear]       = useState(null);

  const fetchCooling = async (provinceName, year) => {
    if (!provinceName) return;
    setCoolingLoading(true);
    setCoolingData(null);
    try {
      const query = year == null ? '' : `?year=${year}`;
      const res = await fetchWithRetry(
        `${API_BASE}/analysis/cooling/${encodeURIComponent(provinceName)}${query}`);
      const json = await res.json();
      if (res.ok) {
        setCoolingData(json);
        if (year == null) setCoolingYear(json.year);
      } else {
        pushError(`วิเคราะห์ความเย็นไม่สำเร็จ — ${json.detail || 'ลองอีกครั้ง'}`);
      }
    } catch (err) {
      console.error('fetchCooling:', err);
      pushError('โหลดข้อมูลวิเคราะห์ความเย็นไม่สำเร็จ — ลองอีกครั้ง');
    } finally {
      setCoolingLoading(false);
    }
  };

  // Province change also clears the year: the latest year with enough data
  // differs between provinces, so carrying the old one over could land on a thin year.
  const resetCooling = useCallback(() => {
    setCoolingData(null);
    setCoolingYear(null);
  }, []);

  return {
    coolingData, coolingLoading, coolingYear,
    setCoolingYear, fetchCooling, resetCooling,
  };
}
