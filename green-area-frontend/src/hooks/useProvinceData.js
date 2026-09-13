import { useCallback, useRef, useState } from 'react';
import { API_BASE, CURRENT_YEAR, API_COMPUTE_TIMEOUT_MS } from '../constants';
import { pushApiError } from '../utils/apiErrors';
import { fetchWithRetry } from '../utils/fetchRetry';

export function useProvinceData({ setNdviCache }) {
  const [selectedProvince, setSelectedProvince]     = useState(null);
  const [selectedProvinceEN, setSelectedProvinceEN] = useState(null);
  const [provinceArea, setProvinceArea]             = useState(null);
  const [ndviStats, setNdviStats]                   = useState(null);
  const [ndviMonthly, setNdviMonthly]               = useState([]);
  const [ndviLoading, setNdviLoading]               = useState(false);
  // urban subset — ค่าต่อหัวประชากรเฉพาะเขตเมือง · แผงสถิติใช้ค่านี้เป็นตัวหลัก
  // แทนค่าทั้งจังหวัด เพราะประชากรกระจุกในเขตเมืองแต่พื้นที่สีเขียวส่วนใหญ่อยู่นอกเขต
  // ค่าทั้งจังหวัดจึงสูงจนไม่สื่อความจริง (สมุทรปราการ 354.7 vs 38.2 m²/คน)
  const [urbanStats, setUrbanStats]                 = useState(null);
  // สถานะของคำขอ urban แยกจากตัวข้อมูล — 'idle' | 'loading' | 'ready' | 'error'
  //
  // เดิมมีแค่ urbanStats แล้วให้ UI ตีความ `null` ว่า "กำลังโหลด" ซึ่งชนกับกรณี
  // "โหลดไม่สำเร็จ" ที่ก็เป็น null เหมือนกัน (คำขอนี้ล้มได้จริง — urban.py คืน 404
  // เมื่อปีนั้นไม่มีภาพ S2 และ 422/503 เมื่อ GEE/WorldPop ไม่พร้อม) ผลคือป้าย
  // "กำลังดึงค่าเฉพาะเขตเมือง…" ค้างตลอดกาลทั้งที่คำขอจบไปแล้ว
  const [urbanStatus, setUrbanStatus]               = useState('idle');
  const [lstStats, setLstStats]                     = useState(null);
  const [lstMonthly, setLstMonthly]                 = useState([]);
  const [lstLoading, setLstLoading]                 = useState(false);
  // last-click-wins: abort any in-flight province fetch when a new one starts,
  // so a slow response for province A can't overwrite the panel after B is picked
  const abortRef = useRef(null);

  // year: the app-wide selected year (Dashboard owns it). Every one of these
  // endpoints takes ?year= and falls back to the current year server-side —
  // omitting it was why the panel always showed the newest year no matter what
  // the year selector said.
  const fetchNDVI = async (provinceName, year = CURRENT_YEAR) => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    const { signal } = controller;

    setNdviLoading(true);
    setLstLoading(true);
    setNdviStats(null);
    setNdviMonthly([]);
    setLstStats(null);
    setLstMonthly([]);
    setUrbanStats(null);
    setUrbanStatus('loading');
    try {
      const enc = encodeURIComponent;
      const qs = `?year=${year}`;

      // ยิงแยกจากชุดหลัก ไม่รวมใน Promise.all — จังหวัดที่ยังไม่มีแถวใน urban_ndvi_annual
      // ต้องคำนวณผ่าน GEE ซึ่งช้ากว่าชุดหลักหลายเท่า ถ้ารอพร้อมกันแผงทั้งแผงจะค้างตาม
      // ล้มเหลวก็ไม่เป็นไร — แผงถอยไปแสดงค่าทั้งจังหวัด แต่ต้องบันทึกสถานะ 'error'
      // ไว้ด้วย ไม่งั้น UI แยกไม่ออกจาก 'loading' แล้วโชว์ข้อความโหลดค้าง
      //
      // ทุกการ set ต้องเช็ค abortRef ก่อน (เหมือน loading flag ท้ายฟังก์ชัน) — คำขอนี้
      // อยู่นอก Promise.all จึงค้างข้าม fetchNDVI รอบถัดไปได้ ถ้าไม่เช็ค ผลของจังหวัด
      // ก่อนหน้าอาจมาทับสถานะของจังหวัดที่เลือกใหม่
      const isCurrent = () => abortRef.current === controller;
      fetchWithRetry(`${API_BASE}/analysis/urban-subset/${enc(provinceName)}${qs}`, { signal },
                     { timeoutMs: API_COMPUTE_TIMEOUT_MS })
        .then(res => (res.ok ? res.json() : null))
        .then(urban => {
          if (!isCurrent()) return;
          if (urban) {
            setUrbanStats(urban);
            setUrbanStatus('ready');
          } else {
            setUrbanStatus('error');
          }
        })
        .catch(err => {
          if (err?.name === 'AbortError') return;  // superseded — สถานะเป็นของรอบใหม่แล้ว
          console.error('ดึงข้อมูลเขตเมืองไม่สำเร็จ:', err);
          if (isCurrent()) setUrbanStatus('error');
        });

      const [statsRes, monthlyRes, lstRes, lstMonthlyRes] = await Promise.all([
        fetchWithRetry(`${API_BASE}/ndvi/${enc(provinceName)}${qs}`, { signal }),
        fetchWithRetry(`${API_BASE}/ndvi/${enc(provinceName)}/monthly${qs}`, { signal }),
        fetchWithRetry(`${API_BASE}/lst/${enc(provinceName)}${qs}`, { signal }),
        fetchWithRetry(`${API_BASE}/lst/${enc(provinceName)}/monthly${qs}`, { signal }),
      ]);
      const [stats, monthly, lst, lstMonthlyJson] = await Promise.all([
        statsRes.json(), monthlyRes.json(), lstRes.json(), lstMonthlyRes.json(),
      ]);
      if (statsRes.ok) setNdviStats(stats);
      setNdviMonthly(monthlyRes.ok ? (monthly.monthly?.filter(m => m.ndvi !== null) ?? []) : []);
      if (lstRes.ok) setLstStats(lst);
      setLstMonthly(lstMonthlyRes.ok ? (lstMonthlyJson.monthly?.filter(m => m.lst !== null) ?? []) : []);
      // ndviCache colours the country choropleth and holds ONE value per
      // province, reduced to the newest year (/cache/ndvi-latest). Writing an
      // older year's value into it would leave the map mixing years — one
      // province drawn on 2021 while the rest sit on the latest. Only the
      // current year may refresh it.
      if (statsRes.ok && stats.ndvi_mean != null && year === CURRENT_YEAR) {
        setNdviCache(prev => ({ ...prev, [provinceName]: stats.ndvi_mean }));
      }
    } catch (err) {
      if (err?.name === 'AbortError') return;  // superseded by a newer selection
      console.error('ดึงข้อมูล NDVI/LST ไม่สำเร็จ:', err);
      // ข้อความจะเลือกเองตามชนิดของปัญหา (timeout / เน็ตไม่ถึง / 5xx / 4xx)
      // และยุบซ้ำให้อัตโนมัติเมื่อคำขออื่นล้มด้วยสาเหตุเดียวกัน
      pushApiError(err, `ข้อมูลจังหวัด ${provinceName}`);
    } finally {
      // only the most-recent request may clear the loading flags
      if (abortRef.current === controller) {
        setNdviLoading(false);
        setLstLoading(false);
      }
    }
  };

  const resetProvince = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setSelectedProvince(null);
    setSelectedProvinceEN(null);
    setNdviStats(null);
    setNdviMonthly([]);
    setProvinceArea(null);
    setLstStats(null);
    setLstMonthly([]);
    setUrbanStats(null);
    setUrbanStatus('idle');
  }, []);

  return {
    selectedProvince, setSelectedProvince,
    selectedProvinceEN, setSelectedProvinceEN,
    provinceArea, setProvinceArea,
    ndviStats, ndviMonthly, ndviLoading, urbanStats, urbanStatus,
    lstStats, lstMonthly, lstLoading,
    fetchNDVI, resetProvince,
  };
}
