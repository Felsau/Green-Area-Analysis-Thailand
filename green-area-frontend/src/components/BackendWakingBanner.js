import { useEffect, useState } from 'react';
import { subscribeBackendStatus } from '../utils/backendStatus';
import { API_TIMEOUT_MS } from '../constants';

// ป้าย "กำลังปลุกเซิร์ฟเวอร์" — ขึ้นเมื่อมีคำขอค้างนานเกินปกติ
//
// ทำไมต้องมี: backend อยู่บน Render free plan ที่หลับเมื่อไม่มีคนใช้ ~15 นาที คำขอแรก
// หลังหลับต้องรอปลุกเครื่องราว 45-60 วินาที เดิมหน้าจอมีแค่ spinner ของแต่ละแผง
// ผู้ใช้จึงแยกไม่ออกว่า "เว็บพัง" หรือ "แค่ช้า" แล้วปิดหนีไปก่อนข้อมูลจะมา
//
// ตัวป้ายไม่รู้จัก hook ไหนเลย — มันฟังสถานะรวมจาก backendStatus ซึ่งนับที่ชั้น
// fetchWithRetry ป้ายจึงขึ้นครั้งเดียวไม่ว่าจะมีกี่คำขอค้างอยู่ และหายเองเมื่อ
// คำขอทุกตัวจบ (สำเร็จ ล้มเหลว หรือถูกยกเลิกก็ตาม)
export default function BackendWakingBanner() {
  const [waking, setWaking] = useState(false);

  useEffect(() => subscribeBackendStatus(setWaking), []);

  if (!waking) return null;

  return (
    <div className="wake-banner" role="status" aria-live="polite">
      <div className="wake-banner__spinner" aria-hidden="true" />
      <div>
        <div className="wake-banner__title">กำลังปลุกเซิร์ฟเวอร์ อาจใช้เวลาประมาณ 1 นาที</div>
        <div className="wake-banner__hint">
          เซิร์ฟเวอร์พักอัตโนมัติเมื่อไม่มีผู้ใช้ ครั้งแรกจึงช้ากว่าปกติ
          หลังจากนี้จะเร็วขึ้น — ระบบจะเลิกรอเองถ้าเกิน {Math.round(API_TIMEOUT_MS / 1000)} วินาที
        </div>
      </div>
    </div>
  );
}
