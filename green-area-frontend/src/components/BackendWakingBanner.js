import { useEffect, useState } from 'react';
import { subscribeBackendStatus } from '../utils/backendStatus';

// ป้ายบอกสถานะเมื่อคำขอใช้เวลานานผิดปกติ
//
// ⚠️ ป้ายนี้ต้องไม่ "เดาสาเหตุ" ให้ผู้ใช้ · เวอร์ชันแรกขึ้นว่า "กำลังปลุกเซิร์ฟเวอร์"
// ทุกครั้งที่คำขอช้า ทำให้หน้า AI แนะนำที่กดตอนเครื่องตื่นอยู่แล้วก็ยังบอกว่ากำลังปลุก
// ซึ่งผิดความจริง — ตอนนี้ backendStatus แยกสองกรณีจากหลักฐาน (เพิ่งได้ response
// จาก backend หรือไม่) แล้วส่ง reason มาให้ ที่นี่แค่เลือกข้อความตามนั้น
//
// ข้อความทั้งสองแบบตั้งใจบอก "ต้องรอนานแค่ไหน" และ "ทำไม" — ไม่ใช่แค่ spinner เปล่า
// เพราะปัญหาเดิมคือผู้ใช้แยกไม่ออกว่าเว็บพังหรือแค่ช้า แล้วปิดหนีไปก่อนข้อมูลจะมา
const COPY = {
  waking: {
    title: 'กำลังปลุกเซิร์ฟเวอร์ อาจใช้เวลาประมาณ 1 นาที',
    hint: 'เซิร์ฟเวอร์พักอัตโนมัติเมื่อไม่มีผู้ใช้ ครั้งแรกจึงช้ากว่าปกติ หลังจากนี้จะเร็วขึ้น',
  },
  working: {
    title: 'กำลังประมวลผลข้อมูลดาวเทียม อาจใช้เวลาหลายนาที',
    hint: 'พื้นที่นี้ยังไม่มีผลคำนวณเก็บไว้ ระบบจึงคำนวณสดจาก Google Earth Engine '
        + 'ยิ่งพื้นที่กว้างยิ่งใช้เวลานาน · เปิดหน้านี้ทิ้งไว้ได้ ผลจะขึ้นเองเมื่อเสร็จ',
  },
};

export default function BackendWakingBanner() {
  const [reason, setReason] = useState(null);

  useEffect(() => subscribeBackendStatus(setReason), []);

  const copy = COPY[reason];
  if (!copy) return null;

  return (
    <div className="wake-banner" role="status" aria-live="polite">
      <div className="wake-banner__spinner" aria-hidden="true" />
      <div>
        <div className="wake-banner__title">{copy.title}</div>
        <div className="wake-banner__hint">{copy.hint}</div>
      </div>
    </div>
  );
}
