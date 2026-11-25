import { useState } from 'react';
import { pushError } from '../../utils/toast';

// jspdf + html2canvas (~heavy) โหลดแบบ dynamic ตอนกดปุ่มเท่านั้น — ไม่อยู่ใน
// main bundle · run() มี await + busy spinner รองรับ promise ของ import() อยู่แล้ว
const loadImageExport = () => import('../../utils/export/image');

// disabled — ข้อมูลของแท็บยังโหลดไม่เสร็จ: ห้ามส่งออกไฟล์ว่าง/ครึ่งเดียว/ของรอบก่อน
export default function ExportBar({ targetId, baseName, onCsv, onPdf, includeMap = true, disabled = false }) {
  const [busy, setBusy] = useState(null);

  const run = async (kind, fn) => {
    if (busy || disabled) return;
    setBusy(kind);
    try { await fn(); }
    catch (e) {
      console.error(e);
      pushError('ส่งออกไม่สำเร็จ: ' + (e?.message || e));
    } finally { setBusy(null); }
  };

  return (
    <div className="section">
      <div className="section__head section__head--quiet">
        <span className="section__title">ส่งออกข้อมูล</span>
      </div>
      <div className="export-bar">
        {onCsv && (
          <button className="export-btn" disabled={!!busy || disabled}
            onClick={() => run('csv', async () => onCsv())}>
            {busy === 'csv' ? '…' : 'CSV'}
          </button>
        )}
        <button className="export-btn" disabled={!!busy || disabled}
          onClick={() => run('png', async () => {
            const { exportElementPng } = await loadImageExport();
            return exportElementPng(targetId, `${baseName}.png`);
          })}>
          {busy === 'png' ? '…' : 'PNG'}
        </button>
        {onPdf && (
          <button className="export-btn" disabled={!!busy || disabled}
            onClick={() => run('pdf', () => onPdf())}>
            {busy === 'pdf' ? '…' : 'PDF'}
          </button>
        )}
        {includeMap && (
          <button className="export-btn" disabled={!!busy || disabled}
            onClick={() => run('map', async () => {
              const { exportTabWithMapPng } = await loadImageExport();
              return exportTabWithMapPng(targetId, `${baseName}_with_map.png`);
            })}>
            {busy === 'map' ? '…' : 'PNG + แผนที่'}
          </button>
        )}
      </div>
    </div>
  );
}
