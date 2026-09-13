import { useCallback, useMemo, useRef, useState } from 'react';
import * as turf from '@turf/turf';
import { API_BASE, API_COMPUTE_TIMEOUT_MS } from '../constants';
import { pushError } from '../utils/toast';
import { fetchWithRetry } from '../utils/fetchRetry';

// Client-side guard — mirrors MAX_AREA_KM2 ใน backend custom.py เพื่อ fail เร็ว
// (ก่อนยิง request) พร้อมข้อความ ก่อน server จะ reject ซ้ำอีกชั้น
const MAX_AREA_KM2 = 20_000;

// Draw-your-own-area: เก็บจุดที่คลิกบนแผนที่เป็น polygon แล้วส่งไปวิเคราะห์ที่
// POST /analysis/custom-area · state machine: idle → drawing → (loading) → result
export function useDrawArea() {
  const [drawActive, setDrawActive] = useState(false);
  const [points, setPoints] = useState([]);   // [[lng, lat], ...] — ring เปิด (ยังไม่ปิด)
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  // AI Recommend บนพื้นที่ที่วาด (heatmap + จุดควรปลูก + impact + พันธุ์ไม้)
  const [recommendResult, setRecommendResult] = useState(null);
  const [recommendLoading, setRecommendLoading] = useState(false);
  const [recommendVisible, setRecommendVisible] = useState(true);
  const abortRef = useRef(null);
  const recAbortRef = useRef(null);

  // เริ่มวาดใหม่ — ล้างผลเดิม (รวม recommend) + เปิดโหมดเก็บคลิก
  const startDraw = useCallback(() => {
    abortRef.current?.abort();
    recAbortRef.current?.abort();
    setResult(null);
    setRecommendResult(null);
    setPoints([]);
    setDrawActive(true);
  }, []);

  const addPoint = useCallback((coord) => {
    if (!coord || coord.length < 2) return;
    // ปัดเป็น 5 ตำแหน่ง (~1m) ลดขนาด payload + กัน float noise
    const lng = Math.round(coord[0] * 1e5) / 1e5;
    const lat = Math.round(coord[1] * 1e5) / 1e5;
    setPoints(prev => [...prev, [lng, lat]]);
  }, []);

  const undoPoint = useCallback(() => setPoints(prev => prev.slice(0, -1)), []);

  // ยกเลิกระหว่างวาด — กลับสู่ idle แต่คง result เดิมไว้ (ถ้ามี)
  const cancelDraw = useCallback(() => {
    setDrawActive(false);
    setPoints([]);
  }, []);

  // ปิดทั้งหมด — ล้าง polygon + ผลลัพธ์ (ใช้ตอนกด "ปิด" หรือ reset ทั้งแอป)
  const reset = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    recAbortRef.current?.abort();
    recAbortRef.current = null;
    setDrawActive(false);
    setPoints([]);
    setResult(null);
    setLoading(false);
    setRecommendResult(null);
    setRecommendLoading(false);
  }, []);

  const toggleRecommendVisible = useCallback(() => setRecommendVisible(v => !v), []);

  // โหลดพื้นที่ที่บันทึกไว้กลับมาแสดง — polygon + ผลวิเคราะห์ + recommend (ถ้ามี)
  // row = full row จาก GET /saved-areas/{id} (มี geometry, analysis, recommendation)
  const loadSaved = useCallback((row) => {
    abortRef.current?.abort();
    recAbortRef.current?.abort();
    const ring = row?.geometry?.coordinates?.[0] || [];
    let pts = ring.map(p => [p[0], p[1]]);
    // ตัดจุดปิด ring (จุดแรก = จุดสุดท้าย) ให้เป็น ring เปิดเหมือน points ที่วาดเอง
    if (pts.length > 1) {
      const a = pts[0], b = pts[pts.length - 1];
      if (a[0] === b[0] && a[1] === b[1]) pts = pts.slice(0, -1);
    }
    setDrawActive(false);
    setLoading(false);
    setRecommendLoading(false);
    setPoints(pts);
    setResult(row?.analysis || null);
    setRecommendResult(row?.recommendation || null);
    setRecommendVisible(true);
  }, []);

  // พื้นที่โดยประมาณ (km²) ของ ring ปัจจุบัน — โชว์ระหว่างวาด
  const area = useMemo(() => {
    if (points.length < 3) return null;
    try {
      return turf.area(turf.polygon([[...points, points[0]]])) / 1e6;
    } catch {
      return null;
    }
  }, [points]);

  const analyze = useCallback(async (year) => {
    if (points.length < 3) {
      pushError('ปักหมุดอย่างน้อย 3 จุดก่อนวิเคราะห์');
      return;
    }
    const ring = [...points, points[0]];  // ปิด ring (จุดแรก = จุดสุดท้าย)
    const geometry = { type: 'Polygon', coordinates: [ring] };

    let km2 = null;
    try { km2 = turf.area(turf.polygon([ring])) / 1e6; } catch { /* ปล่อยให้ server guard */ }
    if (km2 != null && km2 > MAX_AREA_KM2) {
      pushError(`พื้นที่ใหญ่เกินไป (~${Math.round(km2).toLocaleString()} km²) — สูงสุด ${MAX_AREA_KM2.toLocaleString()} km²`);
      return;
    }

    abortRef.current?.abort();
    recAbortRef.current?.abort();           // ผลวิเคราะห์ใหม่ → recommend เดิมใช้ไม่ได้แล้ว
    const controller = new AbortController();
    abortRef.current = controller;
    setLoading(true);
    setResult(null);
    setRecommendResult(null);
    try {
      const res = await fetchWithRetry(`${API_BASE}/analysis/custom-area`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ geometry, year }),
        signal: controller.signal,
      }, { timeoutMs: API_COMPUTE_TIMEOUT_MS });
      const json = await res.json().catch(() => ({}));
      if (!res.ok) {
        pushError(json.detail || 'วิเคราะห์พื้นที่ไม่สำเร็จ — ลองอีกครั้ง');
        return;
      }
      setResult(json);
      setDrawActive(false);  // ออกจากโหมดวาด แต่คง polygon บนแผนที่คู่กับผลลัพธ์
    } catch (err) {
      if (err?.name === 'AbortError') return;
      console.error('วิเคราะห์พื้นที่ที่วาดไม่สำเร็จ:', err);
      pushError('วิเคราะห์พื้นที่ไม่สำเร็จ — ลองอีกครั้ง');
    } finally {
      if (abortRef.current === controller) setLoading(false);
    }
  }, [points]);

  // AI Recommend บนพื้นที่ที่วาด — POST /recommend/custom-area (compute สดทุกครั้ง)
  // provinceHint = จังหวัดที่ centroid ตกอยู่ (App หาด้วย turf) ใช้เลือกพันธุ์ไม้ตามภาค
  const recommendArea = useCallback(async (year, provinceHint) => {
    if (points.length < 3) return;
    const ring = [...points, points[0]];
    const geometry = { type: 'Polygon', coordinates: [ring] };
    recAbortRef.current?.abort();
    const controller = new AbortController();
    recAbortRef.current = controller;
    setRecommendLoading(true);
    setRecommendResult(null);
    try {
      const res = await fetchWithRetry(`${API_BASE}/recommend/custom-area`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ geometry, year, province: provinceHint || undefined }),
        signal: controller.signal,
      }, { timeoutMs: API_COMPUTE_TIMEOUT_MS });
      const json = await res.json().catch(() => ({}));
      if (!res.ok) {
        pushError(json.detail || 'หาจุดควรปลูกไม่สำเร็จ — ลองอีกครั้ง');
        return;
      }
      setRecommendResult(json);
      setRecommendVisible(true);
    } catch (err) {
      if (err?.name === 'AbortError') return;
      console.error('recommend custom-area error:', err);
      pushError('หาจุดควรปลูกไม่สำเร็จ — ลองอีกครั้ง');
    } finally {
      if (recAbortRef.current === controller) setRecommendLoading(false);
    }
  }, [points]);

  return {
    drawActive, points, result, loading, area,
    startDraw, addPoint, undoPoint, cancelDraw, reset, analyze,
    recommendResult, recommendLoading, recommendVisible,
    recommendArea, toggleRecommendVisible, loadSaved,
  };
}
