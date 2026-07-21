// Shared helpers — formatting, escape, font injection, image fetching.
import { apiFetch } from '../apiClient';

export const MONTH_NAMES_TH = [
  'ม.ค.', 'ก.พ.', 'มี.ค.', 'เม.ย.', 'พ.ค.', 'มิ.ย.',
  'ก.ค.', 'ส.ค.', 'ก.ย.', 'ต.ค.', 'พ.ย.', 'ธ.ค.',
];

export const ts = () => {
  const d = new Date();
  const p = n => String(n).padStart(2, '0');
  return `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}_${p(d.getHours())}${p(d.getMinutes())}`;
};

export const fmt = (v, digits = 2) =>
  v == null || Number.isNaN(v) ? '—' : Number(v).toFixed(digits);

export const fmtInt = (v) =>
  v == null ? '—' : Number(v).toLocaleString('th-TH');

export const esc = (s) => {
  if (s == null) return '';
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
};

// "MaeChaem" → "Mae Chaem"  /  "BuengKan" → "Bueng Kan"
export const formatEnName = (s) => s ? String(s).replace(/([a-z])([A-Z])/g, '$1 $2') : s;

// ↑ / ↓ / — indicator string
// threshold ≈ 0.005 เพื่อกัน "↓ 0.000" ที่อ่านแล้วขัดสามัญสำนึก
// (ส่วนต่างที่ปัดเศษเหลือ 0 ไม่ควรมีลูกศรกำกับทิศทาง)
export const arrow = (target, baseline, fmtFn = (v) => v.toFixed(3), epsilon = 0.005) => {
  if (target == null || baseline == null) return '';
  const diff = target - baseline;
  if (Math.abs(diff) < epsilon) return '— เท่ากัน';
  const sign = diff > 0 ? '↑' : '↓';
  return `${sign} ${fmtFn(Math.abs(diff))}`;
};

let fontInjected = false;
export const ensureFont = () => {
  if (fontInjected) return;
  const style = document.createElement('style');
  style.id = 'report-pdf-font';
  style.textContent = `
    @font-face {
      font-family: 'ReportSarabun';
      src: url('/fonts/Sarabun-Regular.ttf') format('truetype');
      font-weight: 400; font-display: block;
    }
    @font-face {
      font-family: 'ReportSarabun';
      src: url('/fonts/Sarabun-Bold.ttf') format('truetype');
      font-weight: 700; font-display: block;
    }
  `;
  document.head.appendChild(style);
  fontInjected = true;
};

// Fetch image from backend → dataUrl (so html2canvas doesn't need CORS round-trip)
export const fetchImageDataUrl = async (url) => {
  try {
    const resp = await apiFetch(url);
    if (!resp.ok) return null;
    const blob = await resp.blob();
    return await new Promise((res) => {
      const r = new FileReader();
      r.onloadend = () => res(r.result);
      r.readAsDataURL(blob);
    });
  } catch (e) {
    console.warn('Image fetch failed:', url, e);
    return null;
  }
};
