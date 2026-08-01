import { useState, useCallback } from 'react';
import { API_BASE } from '../constants';
import { pushError, pushInfo } from '../utils/toast';
import { fetchWithRetry } from '../utils/fetchRetry';

// CRUD บน /saved-areas — บันทึก polygon ที่วาด + ผลวิเคราะห์ ไว้ดูย้อนหลัง
// ownership ผูกกับบัญชีที่ล็อกอิน (user_id) ฝั่ง backend — ไม่ต้องส่ง header อะไรเพิ่ม
// เพราะ fetchWithRetry → apiClient.apiFetch แนบ `Authorization: Bearer <token>` ให้
// ทุก request ที่ยิงไป API_BASE อยู่แล้ว (utils/apiClient.js)
export function useSavedAreas() {
  const [items, setItems] = useState([]);     // list แบบ lean (มี geometry, ไม่มี analysis เต็ม)
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetchWithRetry(`${API_BASE}/saved-areas`);
      const json = await res.json().catch(() => ({}));
      if (res.ok) setItems(json.data || []);
      else pushError(json.detail || 'โหลดรายการพื้นที่ไม่สำเร็จ');
    } catch (err) {
      console.error('list saved-areas error:', err);
      pushError('โหลดรายการพื้นที่ที่บันทึกไม่สำเร็จ');
    } finally {
      setLoading(false);
    }
  }, []);

  const save = useCallback(async (payload) => {
    setSaving(true);
    try {
      const res = await fetchWithRetry(`${API_BASE}/saved-areas`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const json = await res.json().catch(() => ({}));
      if (!res.ok) {
        pushError(json.detail || 'บันทึกพื้นที่ไม่สำเร็จ');
        return null;
      }
      setItems(prev => [json, ...prev]);   // prepend ตัวใหม่ขึ้นบนสุด
      pushInfo('บันทึกพื้นที่แล้ว ✓');
      return json;
    } catch (err) {
      console.error('save area error:', err);
      pushError('บันทึกพื้นที่ไม่สำเร็จ — ลองอีกครั้ง');
      return null;
    } finally {
      setSaving(false);
    }
  }, []);

  // ดึงพื้นที่แบบเต็ม (รวม analysis + recommendation) สำหรับโหลดกลับบนแผนที่
  const getOne = useCallback(async (id) => {
    try {
      const res = await fetchWithRetry(`${API_BASE}/saved-areas/${id}`);
      const json = await res.json().catch(() => ({}));
      if (!res.ok) { pushError(json.detail || 'โหลดพื้นที่ไม่สำเร็จ'); return null; }
      return json;
    } catch (err) {
      console.error('get saved-area error:', err);
      pushError('โหลดพื้นที่ไม่สำเร็จ');
      return null;
    }
  }, []);

  const remove = useCallback(async (id) => {
    try {
      const res = await fetchWithRetry(`${API_BASE}/saved-areas/${id}`, { method: 'DELETE' });
      if (!res.ok) {
        const json = await res.json().catch(() => ({}));
        pushError(json.detail || 'ลบพื้นที่ไม่สำเร็จ');
        return;
      }
      setItems(prev => prev.filter(x => x.id !== id));
    } catch (err) {
      console.error('delete saved-area error:', err);
      pushError('ลบพื้นที่ไม่สำเร็จ');
    }
  }, []);

  return { items, loading, saving, refresh, save, getOne, remove };
}
