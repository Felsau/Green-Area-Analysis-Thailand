import { useCallback, useState } from 'react';
import { API_BASE, CURRENT_YEAR } from '../constants';
import { pushError } from '../utils/toast';
import { apiFetch } from '../utils/apiClient';

export function useCompareData() {
  const [compareList, setCompareList]       = useState([]);
  const [compareYear, setCompareYear]       = useState(CURRENT_YEAR);
  const [compareData, setCompareData]       = useState([]);
  const [compareLoading, setCompareLoading] = useState(false);
  const [compareMetric, setCompareMetric]   = useState('ndvi_mean');

  const fetchCompareData = async (provinces, year) => {
    if (provinces.length < 2) return;
    setCompareLoading(true);
    try {
      const res  = await apiFetch(`${API_BASE}/compare?provinces=${provinces.join(',')}&year=${year}`);
      const json = await res.json();
      setCompareData(json.data.filter(d => d.available));
    } catch (err) {
      console.error('fetchCompareData error:', err);
      pushError('โหลดข้อมูลเปรียบเทียบไม่สำเร็จ — ลองอีกครั้ง');
    } finally {
      setCompareLoading(false);
    }
  };

  const addToCompare    = (p) => { if (!compareList.includes(p)) setCompareList(prev => [...prev, p]); };
  const removeFromCompare = (p) => { setCompareList(prev => prev.filter(x => x !== p)); setCompareData([]); };
  const resetCompare    = useCallback(() => { setCompareList([]); setCompareData([]); }, []);

  return {
    compareList, compareYear, compareData, compareLoading, compareMetric,
    setCompareYear, setCompareMetric,
    fetchCompareData, addToCompare, removeFromCompare, resetCompare,
  };
}
