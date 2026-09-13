import { useState, useCallback } from 'react';
import { API_BASE } from '../constants';
import { API_ERROR, ApiError, pushApiError } from '../utils/apiErrors';
import { fetchWithRetry } from '../utils/fetchRetry';

// selectedYear is owned by Dashboard and shared with the province/district
// panels, the raster overlay and the draw tool — the ranking used to keep its
// own copy, which is why picking a year here changed nothing anywhere else.
export function useRankingData(selectedYear) {
  const [rankingData, setRankingData]   = useState([]);
  const [rankingStats, setRankingStats] = useState(null);
  const [rankingLoading, setRankingLoading] = useState(false);

  const fetchRanking = useCallback(async (year) => {
    const y = year !== undefined ? year : selectedYear;
    setRankingLoading(true);
    try {
      // ผ่าน fetchWithRetry เหมือน hook อื่น — เดิมเป็น fetch() ดิบจึงไม่มี timeout
      // และไม่ถูกนับเข้าป้าย "กำลังปลุกเซิร์ฟเวอร์" ทั้งที่เป็นคำขอแรก ๆ ที่ผู้ใช้เจอ
      const res = await fetchWithRetry(`${API_BASE}/analysis/ranking?year=${y}`);
      if (!res.ok) throw new ApiError(API_ERROR.CLIENT, `HTTP ${res.status}`, { status: res.status });
      const data = await res.json();
      setRankingData(data.data || []);
      setRankingStats({
        total:    data.total_cached,
        whoPass:  data.above_who_reference_count,
        whoFail:  data.below_who_reference_count,
      });
    } catch (e) {
      setRankingData([]);
      setRankingStats(null);
      pushApiError(e, `อันดับจังหวัดปี ${y}`);
    } finally {
      setRankingLoading(false);
    }
  }, [selectedYear]);

  return { rankingData, rankingStats, rankingLoading, fetchRanking };
}
