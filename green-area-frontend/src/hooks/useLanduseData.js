import { useCallback, useRef, useState } from 'react';
import { API_BASE, CURRENT_YEAR } from '../constants';
import { pushError } from '../utils/toast';
import { fetchWithRetry } from '../utils/fetchRetry';

// สัดส่วนการใช้ที่ดิน 5 ประเภทหลัก (จัดกลุ่มตามนิยามกรมพัฒนาที่ดิน — LDD) ของ
// จังหวัด/อำเภอ · fetch-on-demand แบบ useCoolingData (GEE compute หนัก ไม่ auto-fetch
// ตอนเลือกจังหวัด) · abort แบบ last-call-wins กันผลจังหวัดเก่ามาทับตอนสลับเร็วๆ
export function useLanduseData() {
  const [landuseData, setLanduseData]       = useState(null);
  const [landuseLoading, setLanduseLoading] = useState(false);
  const [landuseYear, setLanduseYear]       = useState(CURRENT_YEAR);
  const abortRef = useRef(null);

  const fetchLanduse = useCallback(async (provinceEN, districtEN, year) => {
    if (!provinceEN) return;
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    const { signal } = controller;

    setLanduseLoading(true);
    setLanduseData(null);
    try {
      const enc = encodeURIComponent;
      const qs = `year=${year}${districtEN ? `&district_name=${enc(districtEN)}` : ''}`;
      const res = await fetchWithRetry(
        `${API_BASE}/analysis/landuse/${enc(provinceEN)}?${qs}`, { signal });
      const json = await res.json();
      if (signal.aborted) return;
      if (res.ok) {
        setLanduseData(json);
      } else {
        pushError(`วิเคราะห์การใช้ที่ดินไม่สำเร็จ — ${json.detail || 'ลองอีกครั้ง'}`);
      }
    } catch (err) {
      if (err?.name === 'AbortError') return;
      console.error('fetchLanduse:', err);
      pushError('โหลดข้อมูลการใช้ที่ดินไม่สำเร็จ — ลองอีกครั้ง');
    } finally {
      if (abortRef.current === controller) {
        abortRef.current = null;
        setLanduseLoading(false);
      }
    }
  }, []);

  const resetLanduse = useCallback(() => {
    abortRef.current?.abort();
    setLanduseData(null);
    setLanduseLoading(false);
  }, []);

  return {
    landuseData, landuseLoading, landuseYear,
    setLanduseYear, fetchLanduse, resetLanduse,
  };
}
