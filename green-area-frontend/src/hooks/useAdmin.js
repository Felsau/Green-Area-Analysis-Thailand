import { useCallback, useState } from 'react';

import { API_BASE } from '../constants';
import { fetchWithRetry } from '../utils/fetchRetry';

// Admin console data — user list, role changes, cache clearing.
// เดิมงานเหล่านี้ทำผ่านหน้าเว็บไม่ได้เลย: เปลี่ยนบทบาทต้องรัน SQL ใน Supabase
// (ดู migration 010) ส่วนล้างแคชต้องยิง curl พร้อม X-Admin-Token หน่วยงานที่รับ
// ระบบไปใช้จึงต้องพึ่งผู้พัฒนาทุกครั้ง hook นี้พาไปเรียก /admin/* แทน
//
// ไม่ต้องส่ง Authorization เอง — fetchWithRetry → apiClient.apiFetch แนบ
// `Bearer <token>` ของผู้ใช้ที่ล็อกอินให้ทุก request ที่ยิงไป API_BASE อยู่แล้ว
export function useAdmin() {
  const [users, setUsers] = useState(null);   // null = ยังไม่ได้โหลด
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const loadUsers = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const res = await fetchWithRetry(`${API_BASE}/admin/users`);
      const json = await res.json().catch(() => null);
      if (!res.ok) throw new Error(json?.detail || 'โหลดรายชื่อผู้ใช้ไม่สำเร็จ');
      setUsers(Array.isArray(json) ? json : []);
    } catch (err) {
      setError(err.message || 'โหลดรายชื่อผู้ใช้ไม่สำเร็จ');
    } finally {
      setLoading(false);
    }
  }, []);

  // คืน { ok, error } แทนการ throw เพื่อให้หน้าจอแสดงข้อความจาก backend ได้ตรง ๆ
  // (เช่น "ต้องเหลือผู้ดูแลระบบอย่างน้อย 1 คน") โดยไม่ต้อง try/catch ทุกจุดที่เรียก
  const setRole = useCallback(async (userId, role) => {
    try {
      const res = await fetchWithRetry(`${API_BASE}/admin/users/${userId}/role`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ role }),
      }, { retryOnError: false });          // PATCH ยิงซ้ำเองไม่ได้
      const json = await res.json().catch(() => null);
      if (!res.ok) return { ok: false, error: json?.detail || 'เปลี่ยนบทบาทไม่สำเร็จ' };
      setUsers((prev) => (prev || []).map((u) => (u.id === userId ? { ...u, ...json } : u)));
      return { ok: true };
    } catch {
      return { ok: false, error: 'เปลี่ยนบทบาทไม่สำเร็จ — ตรวจการเชื่อมต่อ' };
    }
  }, []);

  const clearCache = useCallback(async (province) => {
    const path = province ? `/cache/${encodeURIComponent(province)}` : '/cache';
    try {
      const res = await fetchWithRetry(`${API_BASE}${path}`, { method: 'DELETE' },
                                       { retryOnError: false });
      const json = await res.json().catch(() => null);
      if (!res.ok) return { ok: false, error: json?.detail || 'ล้างข้อมูลไม่สำเร็จ' };
      return { ok: true, message: json?.message || 'ล้างข้อมูลแล้ว' };
    } catch {
      return { ok: false, error: 'ล้างข้อมูลไม่สำเร็จ — ตรวจการเชื่อมต่อ' };
    }
  }, []);

  return { users, loading, error, loadUsers, setRole, clearCache };
}
