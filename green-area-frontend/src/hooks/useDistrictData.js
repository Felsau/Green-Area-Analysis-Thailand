import { useCallback, useRef, useState } from 'react';
import { API_BASE, CURRENT_YEAR } from '../constants';
import { pushError } from '../utils/toast';
import { fetchWithRetry } from '../utils/fetchRetry';
import { apiFetch } from '../utils/apiClient';

export function useDistrictData() {
  const [districtsData, setDistrictsData]               = useState(null);
  const [districtsLoading, setDistrictsLoading]         = useState(false);
  const [selectedDistrict, setSelectedDistrict]         = useState(null);
  const [selectedDistrictEN, setSelectedDistrictEN]     = useState(null);
  const [districtArea, setDistrictArea]                 = useState(null);
  const [districtNdviStats, setDistrictNdviStats]       = useState(null);
  const [districtNdviMonthly, setDistrictNdviMonthly]   = useState([]);
  const [districtNdviLoading, setDistrictNdviLoading]   = useState(false);
  const [districtCache, setDistrictCache]               = useState({});
  const [loadedCacheProvinces, setLoadedCacheProvinces] = useState(new Set());
  const [districtLstStats, setDistrictLstStats]         = useState(null);
  const [districtLstMonthly, setDistrictLstMonthly]     = useState([]);
  const [districtLstLoading, setDistrictLstLoading]     = useState(false);
  // last-click-wins: abort any in-flight district fetch when a new one starts,
  // so a slow response for district A can't overwrite the panel after B is picked
  const abortRef = useRef(null);

  const ensureDistrictsLoaded = async () => {
    if (districtsData || districtsLoading) return;
    setDistrictsLoading(true);
    try {
      const r = await fetch('/thailand_districts.json');
      const data = await r.json();
      setDistrictsData(data);
    } catch (err) {
      console.error('โหลด thailand_districts.json ไม่สำเร็จ:', err);
      pushError('โหลดขอบเขตอำเภอไม่สำเร็จ — เช็คการเชื่อมต่อแล้วลองอีกครั้ง');
    } finally {
      setDistrictsLoading(false);
    }
  };

  const loadDistrictCache = async (provinceName) => {
    if (!provinceName || loadedCacheProvinces.has(provinceName)) return;
    try {
      const r = await apiFetch(`${API_BASE}/cache/districts?province=${encodeURIComponent(provinceName)}`);
      if (!r.ok) return;
      const { annual = [] } = await r.json();
      const latestByKey = {};
      const latestYearByKey = {};
      annual.forEach(row => {
        if (row.ndvi_mean == null) return;
        const key = `${row.province}::${row.district}`;
        if (latestYearByKey[key] == null || row.year > latestYearByKey[key]) {
          latestYearByKey[key] = row.year;
          latestByKey[key] = row.ndvi_mean;
        }
      });
      setDistrictCache(prev => ({ ...prev, ...latestByKey }));
      setLoadedCacheProvinces(prev => {
        const next = new Set(prev);
        next.add(provinceName);
        return next;
      });
    } catch (err) {
      console.error('โหลด district cache ไม่สำเร็จ:', err);
      // ไม่ push error toast — cache load เงียบๆ ได้ ไม่กระทบ UX หลัก
    }
  };

  // year: the app-wide selected year — see the same note in useProvinceData.
  const fetchDistrictNDVI = async (provinceName, districtName, year = CURRENT_YEAR) => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    const { signal } = controller;

    setDistrictNdviLoading(true);
    setDistrictLstLoading(true);
    setDistrictNdviStats(null);
    setDistrictNdviMonthly([]);
    setDistrictLstStats(null);
    setDistrictLstMonthly([]);
    try {
      const enc = encodeURIComponent;
      const base = `${enc(provinceName)}/districts/${enc(districtName)}`;
      const qs = `?year=${year}`;
      const [statsRes, monthlyRes, lstRes, lstMonthlyRes] = await Promise.all([
        fetchWithRetry(`${API_BASE}/ndvi/${base}${qs}`, { signal }),
        fetchWithRetry(`${API_BASE}/ndvi/${base}/monthly${qs}`, { signal }),
        fetchWithRetry(`${API_BASE}/lst/${base}${qs}`, { signal }),
        fetchWithRetry(`${API_BASE}/lst/${base}/monthly${qs}`, { signal }),
      ]);
      const [stats, monthly, lst, lstMonthlyJson] = await Promise.all([
        statsRes.json(), monthlyRes.json(), lstRes.json(), lstMonthlyRes.json(),
      ]);
      if (statsRes.ok) setDistrictNdviStats(stats);
      setDistrictNdviMonthly(monthlyRes.ok ? (monthly.monthly?.filter(m => m.ndvi !== null) ?? []) : []);
      if (lstRes.ok) setDistrictLstStats(lst);
      setDistrictLstMonthly(lstMonthlyRes.ok ? (lstMonthlyJson.monthly?.filter(m => m.lst !== null) ?? []) : []);
      // districtCache is the newest-year value per district (loadDistrictCache
      // reduces /cache/districts the same way) and colours the district layer —
      // keep older years out of it so the map never mixes years.
      if (statsRes.ok && stats.ndvi_mean != null && year === CURRENT_YEAR) {
        const key = `${provinceName}::${districtName}`;
        setDistrictCache(prev => ({ ...prev, [key]: stats.ndvi_mean }));
      }
    } catch (err) {
      if (err?.name === 'AbortError') return;  // superseded by a newer selection
      console.error('ดึงข้อมูล NDVI/LST อำเภอไม่สำเร็จ:', err);
      pushError(`โหลดข้อมูลอำเภอ ${districtName} ไม่สำเร็จ — ลองอีกครั้ง`);
    } finally {
      // only the most-recent request may clear the loading flags
      if (abortRef.current === controller) {
        setDistrictNdviLoading(false);
        setDistrictLstLoading(false);
      }
    }
  };

  const resetDistrict = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setSelectedDistrict(null);
    setSelectedDistrictEN(null);
    setDistrictNdviStats(null);
    setDistrictNdviMonthly([]);
    setDistrictArea(null);
    setDistrictLstStats(null);
    setDistrictLstMonthly([]);
  }, []);

  return {
    districtsData, districtsLoading,
    selectedDistrict, setSelectedDistrict,
    selectedDistrictEN, setSelectedDistrictEN,
    districtArea, setDistrictArea,
    districtNdviStats, districtNdviMonthly, districtNdviLoading,
    districtCache,
    districtLstStats, districtLstMonthly, districtLstLoading,
    ensureDistrictsLoaded, fetchDistrictNDVI, loadDistrictCache, resetDistrict,
  };
}
