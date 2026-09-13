import { useState, useCallback, useEffect, useRef } from 'react';
import { API_BASE, CURRENT_YEAR, API_COMPUTE_TIMEOUT_MS } from '../constants';
import { pushError } from '../utils/toast';
import { fetchWithRetry } from '../utils/fetchRetry';

// Default น้ำหนัก — ตรงกับ backend (W_NDVI / W_LST / W_POP / W_ACCESS, รวม = 1.0)
export const DEFAULT_WEIGHTS = { ndvi: 0.35, lst: 0.25, pop: 0.25, access: 0.15 };

export function useRecommendData() {
  const [recommendData, setRecommendData]       = useState(null);
  const [recommendLoading, setRecommendLoading] = useState(false);
  const [recommendVisible, setRecommendVisible] = useState(true);
  const [recommendScope, setRecommendScope]     = useState(null); // {province, district?, year}
  const [recommendYear, setRecommendYear]       = useState(CURRENT_YEAR);
  const [recommendWeights, setRecommendWeights] = useState(DEFAULT_WEIGHTS);

  // เก็บ AbortController ของ request ล่าสุด — ยิงใหม่ = ยกเลิกตัวเก่า
  // กัน race condition: ถ้า user คลิกถี่ๆ จะไม่เกิด response มาถึงคนละลำดับ
  const inflightRef = useRef(null);

  const fetchRecommendation = useCallback(async (provinceEN, districtEN = null, year, weights) => {
    // ยกเลิก request ก่อนหน้า (ถ้ายังค้าง) แล้วสร้างตัวใหม่
    inflightRef.current?.abort();
    const controller = new AbortController();
    inflightRef.current = controller;

    setRecommendLoading(true);
    setRecommendData(null);
    try {
      const enc  = encodeURIComponent;
      const path = districtEN
        ? `/recommend/${enc(provinceEN)}/districts/${enc(districtEN)}`
        : `/recommend/${enc(provinceEN)}`;
      const params = new URLSearchParams();
      if (year) params.set('year', year);
      if (weights) {
        params.set('w_ndvi', weights.ndvi);
        params.set('w_lst',  weights.lst);
        params.set('w_pop',  weights.pop);
        // access อาจไม่มีใน weights ที่ persist ไว้ก่อน factor นี้ → ปล่อยให้ backend ใช้ default
        if (weights.access != null) params.set('w_access', weights.access);
      }
      const qs  = params.toString();
      const url = `${API_BASE}${path}${qs ? `?${qs}` : ''}`;
      // งานคำนวณสดจาก GEE — ใช้เวลาได้หลายนาที (วัดจริง /recommend เชียงใหม่ 242 วิ)
      const res  = await fetchWithRetry(url, { signal: controller.signal }, { timeoutMs: API_COMPUTE_TIMEOUT_MS });
      if (!res.ok) {
        // อ่าน detail (FastAPI HTTPException) ให้ user เห็นเหตุผลจริง เช่น
        // "ปี 2026 ยังไม่มีข้อมูล Sentinel-2 เพียงพอ — ลองเลือกปีก่อนหน้านี้"
        let detail = `HTTP ${res.status}`;
        try { const j = await res.json(); if (j?.detail) detail = j.detail; }
        catch { /* response ไม่ใช่ JSON — ใช้ status เป็น message พอ */ }
        const e = new Error(detail);
        e.status = res.status;
        throw e;
      }
      const json = await res.json();
      // กัน race ซ้อน: เช็คอีกครั้งหลัง await ว่ายังเป็น request ปัจจุบันอยู่หรือไม่
      if (controller.signal.aborted) return;
      setRecommendData(json);
      setRecommendScope({ province: provinceEN, district: districtEN, year: year || CURRENT_YEAR });
      setRecommendVisible(true);
    } catch (err) {
      if (err?.name === 'AbortError') return;  // ถูก cancel ไม่ต้อง toast
      console.error('fetchRecommendation error:', err);
      setRecommendData(null);
      // 4xx → server บอกเหตุชัดเจน แสดง detail ตรงๆ · 5xx/network → generic
      pushError(err?.status >= 400 && err?.status < 500
        ? err.message
        : 'วิเคราะห์ AI Recommend ไม่สำเร็จ — ลองอีกครั้ง');
    } finally {
      // เคลียร์ ref เฉพาะถ้า controller ตัวนี้ยังเป็นตัวล่าสุด
      if (inflightRef.current === controller) {
        inflightRef.current = null;
        setRecommendLoading(false);
      }
    }
  }, []);

  // unmount → cancel pending request กัน state update บน component ที่หายไป
  useEffect(() => () => inflightRef.current?.abort(), []);

  const resetRecommend = useCallback(() => {
    inflightRef.current?.abort();
    setRecommendData(null);
    setRecommendScope(null);
  }, []);

  return {
    recommendData, recommendLoading, recommendVisible, recommendScope, recommendYear,
    recommendWeights, setRecommendWeights,
    setRecommendVisible, setRecommendYear, fetchRecommendation, resetRecommend,
  };
}
