import { useCallback, useState } from 'react';
import { API_BASE, CURRENT_YEAR } from '../constants';
import { pushError } from '../utils/toast';
import { apiFetch } from '../utils/apiClient';

export function useTrendData() {
  const [trendYears, setTrendYears]     = useState([CURRENT_YEAR - 2, CURRENT_YEAR - 1, CURRENT_YEAR]);
  const [trendData, setTrendData]       = useState([]);
  const [trendLoading, setTrendLoading] = useState(false);
  const [trendProgress, setTrendProgress] = useState('');
  const [trendMetric, setTrendMetric]   = useState('ndvi_mean');
  // forecast จาก /analysis/timeseries — keyed ตาม metric (ndvi_mean,
  // green_area_pct, lst_mean) แต่ละตัวมี points = [{x, value, lo, hi}]
  const [trendForecast, setTrendForecast] = useState(null);

  const fetchTrend = async (provinceName, years) => {
    if (!years.length) return;
    setTrendLoading(true);
    setTrendData([]);
    setTrendForecast(null);
    setTrendProgress('');
    const sorted = [...years].sort((a, b) => a - b);
    const results = [];
    const failedYears = [];
    for (let i = 0; i < sorted.length; i++) {
      const year = sorted[i];
      setTrendProgress(`กำลังโหลดปี ${year} (${i + 1}/${sorted.length})...`);
      try {
        const res  = await apiFetch(`${API_BASE}/ndvi/${encodeURIComponent(provinceName)}?year=${year}`);
        const json = await res.json();
        if (json.ndvi_mean != null) {
          results.push({ year, ndvi_mean: json.ndvi_mean, green_area_pct: json.green_area_pct });
          setTrendData([...results]);
        } else {
          failedYears.push(year);
        }
      } catch (err) {
        console.error(`fetchTrend year ${year}:`, err);
        failedYears.push(year);
      }
    }
    if (failedYears.length) {
      pushError(`โหลด trend ปี ${failedYears.join(', ')} ไม่สำเร็จ`);
    }
    // คาดการณ์ — ใช้ปีที่เพิ่ง cache ข้างบน (timeseries อ่าน cache เท่านั้น
    // ไม่ trigger GEE) ต้อง ≥ 3 ปีถึงมี forecast · fail เงียบๆ ได้ ไม่ใช่ข้อมูลหลัก
    if (results.length >= 3) {
      try {
        setTrendProgress('กำลังคำนวณคาดการณ์...');
        const r = await apiFetch(
          `${API_BASE}/analysis/timeseries/${encodeURIComponent(provinceName)}` +
          `?start_year=${sorted[0]}&end_year=${sorted[sorted.length - 1]}`);
        if (r.ok) {
          const ts = await r.json();
          setTrendForecast(ts.forecast && Object.keys(ts.forecast).length ? ts.forecast : null);
        }
      } catch (err) {
        console.error('fetchTrend forecast:', err);
      }
    }
    setTrendProgress('');
    setTrendLoading(false);
  };

  const toggleTrendYear = (year) => {
    setTrendYears(prev =>
      prev.includes(year) ? prev.filter(y => y !== year) : [...prev, year].sort((a, b) => a - b)
    );
  };

  const resetTrend = useCallback(() => {
    setTrendData([]);
    setTrendForecast(null);
  }, []);

  return {
    trendYears, trendData, trendLoading, trendProgress, trendMetric,
    trendForecast,
    setTrendMetric, fetchTrend, toggleTrendYear, resetTrend,
  };
}
