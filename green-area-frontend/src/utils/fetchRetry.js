// fetch wrapper ที่ retry 2 ครั้ง (1s → 2s backoff) สำหรับ transient GEE timeout
// ใช้แทน fetch() ตรงๆ ใน hook ที่ยิงไป backend
//
// retry เฉพาะ:
//   - network error (fetch reject)
//   - 5xx status (server-side blip)
// ไม่ retry:
//   - 4xx (request ผิด — retry ก็ไม่เปลี่ยน)

import { apiFetch } from './apiClient';

const sleep = (ms) => new Promise(r => setTimeout(r, ms));

export async function fetchWithRetry(url, options = {}, { retries = 2, baseDelayMs = 1000 } = {}) {
  const signal = options.signal;
  let lastErr;
  for (let attempt = 0; attempt <= retries; attempt++) {
    if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
    try {
      const res = await apiFetch(url, options);
      if (res.ok || (res.status >= 400 && res.status < 500)) {
        return res;
      }
      lastErr = new Error(`HTTP ${res.status}`);
    } catch (err) {
      // AbortError ห้าม retry — ผู้ใช้ยกเลิกหรือ component unmount แล้ว
      if (err?.name === 'AbortError') throw err;
      lastErr = err;
    }
    if (attempt < retries) {
      await sleep(baseDelayMs * (attempt + 1));  // 1s, 2s
    }
  }
  throw lastErr;
}
