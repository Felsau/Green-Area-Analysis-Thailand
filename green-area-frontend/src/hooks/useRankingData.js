import { useState, useCallback } from 'react';
import { API_BASE } from '../constants';
import { pushError } from '../utils/toast';

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
      const res = await fetch(`${API_BASE}/analysis/ranking?year=${y}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setRankingData(data.data || []);
      setRankingStats({
        total:    data.total_cached,
        whoPass:  data.who_pass_count,
        whoFail:  data.who_fail_count,
      });
    } catch (e) {
      setRankingData([]);
      setRankingStats(null);
      pushError(`โหลดอันดับจังหวัดปี ${y} ไม่สำเร็จ`);
    } finally {
      setRankingLoading(false);
    }
  }, [selectedYear]);

  return { rankingData, rankingStats, rankingLoading, fetchRanking };
}
