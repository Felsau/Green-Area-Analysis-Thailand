// fetch wrapper สำหรับทุก hook ที่ยิงไป backend — จัดการ timeout, retry และการยกเลิก
//
// ── ปัญหาที่ไฟล์นี้แก้ (13 ก.ย. 2569) ──────────────────────────────────────
// เดิมไม่มี timeout เลย `fetch` จึงรอไม่จำกัด พอ backend บน Render free plan หลับ
// (หลับเมื่อไม่มีคำขอ ~15 นาที) คำขอแรกค้างยาว — วัดจริงได้ first byte 47.2 วินาที
// และครั้งหนึ่งเกิน 180 วินาทีโดยไม่ตอบเลย ระหว่างนั้นหน้าจอไม่บอกอะไรผู้ใช้
//
// ซ้ำร้าย ถ้า Render ตอบ 5xx ระหว่างกำลังตื่น ตัว retry เดิมจะยิงใหม่อีก 2 ครั้ง
// แต่ละครั้งไปรอเครื่องตื่นได้อีกรอบ → รวมเป็นหลายนาที นี่คืออาการที่ผู้ใช้เจอ
//
// ── กติกาใหม่ ─────────────────────────────────────────────────────────────
// 1. ทุกครั้งที่ยิงมีเพดานเวลา (API_TIMEOUT_MS) — ไม่มีคำขอไหนค้างตลอดกาลอีก
// 2. มี "งบเวลารวม" (API_TOTAL_BUDGET_MS) ครอบทั้งคำขอ นับรวมเวลาหน่วงระหว่าง
//    retry ด้วย ดังนั้นต่อให้ retry ครบทุกครั้ง แย่สุดก็จบใน ~2 นาที ไม่ใช่ 4 นาทีครึ่ง
// 3. แยกชนิดความล้มเหลวชัดเจน (timeout / network / server / client) เพื่อให้
//    ชั้นบนเลือกข้อความและตัดสินใจ retry ได้ถูก — ดู utils/apiErrors.js
// 4. การยกเลิกโดยผู้เรียกไม่ใช่ความล้มเหลว: โยน AbortError ทันที ห้าม retry
//    ห้ามนับเป็น error และห้ามขึ้น toast
//
// ── retry เฉพาะกรณีที่ยิงซ้ำแล้วมีโอกาสต่างเดิม ──────────────────────────
//   network error, timeout, 5xx  → retry
//   4xx                          → คืน response เลย (retry ก็ได้ผลเดิม)
//   AbortError                   → โยนออกทันที
import { apiFetch } from './apiClient';
import {
  API_TIMEOUT_MS,
  API_TOTAL_BUDGET_MS,
  API_MIN_ATTEMPT_MS,
} from '../constants';
import { API_ERROR, ApiError, createAbortError, isAbortError } from './apiErrors';
import { beginRequest, endRequest } from './backendStatus';

// หน่วงเวลาที่ยกเลิกได้ — ถ้าผู้ใช้เปลี่ยนจังหวัดระหว่างรอ backoff ต้องเลิกทันที
// ไม่ใช่นอนจนครบแล้วค่อยรู้ตัว
function sleep(ms, signal) {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(createAbortError());
      return;
    }
    const onAbort = () => {
      clearTimeout(timer);
      reject(createAbortError());
    };
    const timer = setTimeout(() => {
      signal?.removeEventListener('abort', onAbort);
      resolve();
    }, ms);
    signal?.addEventListener('abort', onAbort, { once: true });
  });
}

// ยิงหนึ่งครั้งพร้อมเพดานเวลา
//
// จุดสำคัญ: ผู้เรียกส่ง signal ของตัวเองมา (last-click-wins ใน useProvinceData /
// useDistrictData) เราจึงต้องรวมสองเหตุของการ abort เข้าด้วยกัน — ของผู้เรียก และ
// ของ timeout — แต่ยัง **แยกออกจากกันให้ได้** ว่าอันไหนทำให้หยุด เพราะผลต่างกันมาก:
// ผู้เรียกยกเลิก = เงียบ ๆ ไม่ใช่ error · timeout = ต้องบอกผู้ใช้และ retry ได้
//
// ไม่ใช้ AbortSignal.any() เพราะ (ก) มันไม่บอกว่าใครสั่ง abort (ข) รองรับเฉพาะ
// เบราว์เซอร์ใหม่ — ทำเองด้วยตัวแปร cause ตรงไปตรงมากว่าและเช็คได้ในเทสต์
async function attemptFetch(url, options, { timeoutMs, callerSignal }) {
  if (callerSignal?.aborted) throw createAbortError();

  const controller = new AbortController();
  let cause = null;

  const onCallerAbort = () => {
    cause = 'aborted';
    controller.abort();
  };
  callerSignal?.addEventListener('abort', onCallerAbort);

  const timer = setTimeout(() => {
    cause = 'timeout';
    controller.abort();
  }, timeoutMs);

  try {
    return await apiFetch(url, { ...options, signal: controller.signal });
  } catch (err) {
    if (cause === 'timeout') {
      throw new ApiError(
        API_ERROR.TIMEOUT,
        `หมดเวลารอ ${Math.round(timeoutMs / 1000)} วินาที`,
        { url, cause: err },
      );
    }
    // ผู้เรียกยกเลิก — หรือ fetch โยน AbortError มาเองโดยเราไม่ได้สั่ง
    if (cause === 'aborted' || isAbortError(err)) throw createAbortError();
    throw new ApiError(API_ERROR.NETWORK, err?.message || 'เครือข่ายขัดข้อง', { url, cause: err });
  } finally {
    clearTimeout(timer);
    callerSignal?.removeEventListener('abort', onCallerAbort);
  }
}

export async function fetchWithRetry(url, options = {}, {
  retries = 2,
  baseDelayMs = 1000,
  timeoutMs = API_TIMEOUT_MS,
  totalBudgetMs = API_TOTAL_BUDGET_MS,
  // ตั้ง false สำหรับคำขอที่ยิงซ้ำไม่ได้ (POST/DELETE ที่เปลี่ยนข้อมูลจริง) —
  // คำขอที่ timeout อาจถึงเซิร์ฟเวอร์ไปแล้ว การยิงซ้ำจะได้ของซ้ำ
  retryOnError = true,
} = {}) {
  const callerSignal = options.signal;
  const startedAt = Date.now();
  const remaining = () => totalBudgetMs - (Date.now() - startedAt);
  const maxAttempts = retryOnError ? retries : 0;

  // นับคำขอนี้เข้าสถานะรวม เพื่อให้ป้าย "กำลังปลุกเซิร์ฟเวอร์" ขึ้นได้เมื่อช้าผิดปกติ
  // คู่กับ endRequest() ใน finally — ต้องเรียกครั้งเดียวต่อหนึ่ง fetchWithRetry
  // ไม่ใช่ต่อหนึ่ง attempt ไม่งั้นป้ายจะกะพริบตอน retry
  beginRequest();
  try {
    let lastErr = null;

    for (let attempt = 0; attempt <= maxAttempts; attempt++) {
      if (callerSignal?.aborted) throw createAbortError();

      const budget = remaining();
      if (budget <= 0) break;

      try {
        const res = await attemptFetch(url, options, {
          // ครั้งสุดท้ายต้องไม่กินเกินงบที่เหลือ ไม่งั้นงบรวมไม่มีความหมาย
          timeoutMs: Math.min(timeoutMs, budget),
          callerSignal,
        });
        if (res.ok) return res;
        if (res.status >= 400 && res.status < 500) return res;  // 4xx — ให้ caller อ่านเอง
        lastErr = new ApiError(API_ERROR.SERVER, `HTTP ${res.status}`, { status: res.status, url });
      } catch (err) {
        if (isAbortError(err)) throw err;  // ผู้เรียกยกเลิก — ออกทันที ไม่ retry ไม่ error
        lastErr = err;                      // timeout | network
      }

      if (attempt === maxAttempts) break;

      // งบเวลาครอบทั้งการหน่วงด้วย ถ้าหน่วงแล้วเหลือเวลาไม่พอจะยิงจริงให้จบ
      // ก็ไม่ต้องหน่วงให้ผู้ใช้รอเปล่า ๆ — เลิกแล้วรายงานผลทันที
      const delay = baseDelayMs * (attempt + 1);  // 1s → 2s
      if (remaining() - delay < API_MIN_ATTEMPT_MS) break;
      await sleep(delay, callerSignal);
    }

    throw lastErr ?? new ApiError(API_ERROR.NETWORK, 'คำขอไม่สำเร็จ', { url });
  } finally {
    endRequest();
  }
}
