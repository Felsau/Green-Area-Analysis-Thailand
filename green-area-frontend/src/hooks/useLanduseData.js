import { useCallback, useRef, useState } from 'react';
import { API_BASE, CURRENT_YEAR } from '../constants';
import { pushError } from '../utils/toast';
import { fetchWithRetry } from '../utils/fetchRetry';

// สัดส่วนการใช้ที่ดิน 5 ประเภทหลัก (จัดกลุ่มตามนิยามกรมพัฒนาที่ดิน — LDD) ของ
// จังหวัด/อำเภอ · fetch-on-demand แบบ useCoolingData (GEE compute หนัก ไม่ auto-fetch
// ตอนเลือกจังหวัด) · abort แบบ last-call-wins กันผลจังหวัดเก่ามาทับตอนสลับเร็วๆ
// source = แหล่งข้อมูล (dynamic_world | ldd) — ส่งต่อ backend, ผลลัพธ์ schema เดียวกัน
export function useLanduseData() {
  const [landuseData, setLanduseData]       = useState(null);
  const [landuseLoading, setLanduseLoading] = useState(false);
  const [landuseYear, setLanduseYear]       = useState(CURRENT_YEAR);
  const [landuseSource, setLanduseSourceRaw] = useState('dynamic_world');
  const abortRef = useRef(null);

  const fetchLanduse = useCallback(async (provinceEN, districtEN, year, source) => {
    if (!provinceEN) return;
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    const { signal } = controller;

    setLanduseLoading(true);
    setLanduseData(null);
    try {
      const enc = encodeURIComponent;
      const qs = `year=${year}&source=${source || 'dynamic_world'}`
        + (districtEN ? `&district_name=${enc(districtEN)}` : '');
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

  // สลับแหล่งข้อมูล → ล้างผลเดิม (คนละ provider อ่านคู่กันไม่ได้) ให้ผู้ใช้กดวิเคราะห์ใหม่
  const setLanduseSource = useCallback((src) => {
    abortRef.current?.abort();
    setLanduseData(null);
    setLanduseSourceRaw(src);
  }, []);

  const resetLanduse = useCallback(() => {
    abortRef.current?.abort();
    setLanduseData(null);
    setLanduseLoading(false);
    setLanduseSourceRaw('dynamic_world');  // เปลี่ยนจังหวัด → กลับ default (LDD gate ราย จว.)
  }, []);

  return {
    landuseData, landuseLoading, landuseYear, landuseSource,
    setLanduseYear, setLanduseSource, fetchLanduse, resetLanduse,
  };
}
