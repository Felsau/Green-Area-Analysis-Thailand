import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';
import { fetchWithRetry } from './fetchRetry';
import { API_ERROR } from './apiErrors';
import { resetBackendStatus, backendHint, inFlightCount, subscribeBackendStatus, markServerAlive } from './backendStatus';
import {
  API_TIMEOUT_MS,
  API_RETRY_HEADROOM_MS,
  API_COLD_START_HINT_MS,
  API_SERVER_ALIVE_TTL_MS,
} from '../constants';
import { apiFetch } from './apiClient';

vi.mock('./apiClient', () => ({ apiFetch: vi.fn() }));

const ok = (body = {}) => ({ ok: true, status: 200, json: async () => body });
const status = (code) => ({ ok: false, status: code, json: async () => ({}) });

// เลียนแบบ fetch จริง: ค้างจนกว่า signal จะถูก abort แล้วค่อย reject ด้วย AbortError
const hangUntilAborted = (opts) => new Promise((_resolve, reject) => {
  opts.signal.addEventListener('abort', () => {
    reject(new DOMException('The operation was aborted.', 'AbortError'));
  });
});

beforeEach(() => {
  vi.useFakeTimers();
  apiFetch.mockReset();
  resetBackendStatus();
});

afterEach(() => {
  vi.useRealTimers();
  resetBackendStatus();
});

describe('fetchWithRetry — เส้นทางปกติ', () => {
  it('คืน response เมื่อสำเร็จ และยิงครั้งเดียว', async () => {
    apiFetch.mockResolvedValue(ok({ ndvi_mean: 0.3 }));
    const res = await fetchWithRetry('https://api.test/ndvi');
    expect(res.ok).toBe(true);
    expect(apiFetch).toHaveBeenCalledTimes(1);
  });

  it('แนบ signal ของตัวเองเข้าไปเสมอ (ไว้บังคับ timeout)', async () => {
    apiFetch.mockResolvedValue(ok());
    await fetchWithRetry('https://api.test/ndvi');
    expect(apiFetch.mock.calls[0][1].signal).toBeInstanceOf(AbortSignal);
  });
});

describe('fetchWithRetry — แยกชนิดความล้มเหลว', () => {
  it('4xx: คืน response ให้ caller อ่านเอง ไม่ retry', async () => {
    apiFetch.mockResolvedValue(status(404));
    const res = await fetchWithRetry('https://api.test/ndvi/ไม่มีจังหวัดนี้');
    expect(res.status).toBe(404);
    expect(apiFetch).toHaveBeenCalledTimes(1);
  });

  it('5xx: retry ครบ 3 ครั้งแล้วโยน ApiError kind=server พร้อม status', async () => {
    apiFetch.mockResolvedValue(status(502));
    const p = fetchWithRetry('https://api.test/ndvi').catch(e => e);
    await vi.advanceTimersByTimeAsync(10_000);
    const err = await p;
    expect(err.name).toBe('ApiError');
    expect(err.kind).toBe(API_ERROR.SERVER);
    expect(err.status).toBe(502);
    expect(apiFetch).toHaveBeenCalledTimes(3);
  });

  it('network error: โยน ApiError kind=network และเก็บต้นเหตุไว้ใน cause', async () => {
    const boom = new TypeError('Failed to fetch');
    apiFetch.mockRejectedValue(boom);
    const p = fetchWithRetry('https://api.test/ndvi').catch(e => e);
    await vi.advanceTimersByTimeAsync(10_000);
    const err = await p;
    expect(err.kind).toBe(API_ERROR.NETWORK);
    expect(err.cause).toBe(boom);
    expect(apiFetch).toHaveBeenCalledTimes(3);
  });

  it('timeout: ยกเลิกคำขอที่ค้างเมื่อครบเวลา แล้วโยน kind=timeout', async () => {
    apiFetch.mockImplementation((_url, opts) => hangUntilAborted(opts));
    const p = fetchWithRetry('https://api.test/lst', {}, { retries: 0 }).catch(e => e);

    // ยังไม่ครบเวลา — ต้องยังไม่ยอมแพ้
    await vi.advanceTimersByTimeAsync(API_TIMEOUT_MS - 1_000);
    expect(apiFetch.mock.calls[0][1].signal.aborted).toBe(false);

    await vi.advanceTimersByTimeAsync(2_000);
    const err = await p;
    expect(err.kind).toBe(API_ERROR.TIMEOUT);
    expect(apiFetch.mock.calls[0][1].signal.aborted).toBe(true);
  });
});

describe('fetchWithRetry — เพดานเวลาและการไม่ retry เมื่อ timeout', () => {
  it('timeout แล้วต้องไม่ยิงซ้ำ — งานมันนานจริง ยิงซ้ำได้ผลเดิมแต่ผู้ใช้รอสองเท่า', async () => {
    apiFetch.mockImplementation((_url, opts) => hangUntilAborted(opts));
    const started = Date.now();
    // จับเวลา ณ ตอนที่คำขอจบจริง ไม่ใช่หลังเดินนาฬิกาเสร็จ — advanceTimersByTimeAsync
    // ดัน Date.now() ไปเต็มจำนวนที่สั่งเสมอ ต่อให้ promise จบไปตั้งแต่ต้นแล้ว
    let settledAt = null;
    const p = fetchWithRetry('https://api.test/lst').catch(e => { settledAt = Date.now(); return e; });

    await vi.advanceTimersByTimeAsync((API_TIMEOUT_MS + API_RETRY_HEADROOM_MS) * 3);
    const err = await p;

    expect(err.kind).toBe(API_ERROR.TIMEOUT);
    expect(apiFetch).toHaveBeenCalledTimes(1);
    // จบทันทีที่ครบ timeout ไม่ลากยาวไปจนหมดงบ
    expect(settledAt - started).toBe(API_TIMEOUT_MS);
  });

  it('timeoutMs ที่ call site ส่งมาต้องถูกใช้จริง (งานคำนวณหนักจาก GEE)', async () => {
    // เคสจริง: /recommend เชียงใหม่ใช้ 242 วินาที ถ้าเพดานยังเป็นค่าเริ่มต้นจะถูกตัดทิ้ง
    const LONG = 480_000;
    apiFetch.mockImplementation((_url, opts) => hangUntilAborted(opts));
    const p = fetchWithRetry('https://api.test/recommend', {}, { timeoutMs: LONG }).catch(e => e);

    // ผ่านเพดานค่าเริ่มต้นไปแล้วต้องยังไม่ยอมแพ้
    await vi.advanceTimersByTimeAsync(API_TIMEOUT_MS + 10_000);
    expect(apiFetch.mock.calls[0][1].signal.aborted).toBe(false);

    await vi.advanceTimersByTimeAsync(LONG);
    const err = await p;
    expect(err.kind).toBe(API_ERROR.TIMEOUT);
  });

  it('งบรวมต้องขยายตาม timeoutMs ไม่ใช่ค่าคงที่ที่ตัดงานยาวทิ้ง', async () => {
    const LONG = 480_000;
    let call = 0;
    apiFetch.mockImplementation((_url, opts) => {
      call += 1;
      if (call === 1) return Promise.reject(new TypeError('Failed to fetch'));
      return hangUntilAborted(opts);   // ครั้งที่สองค้างยาว
    });
    const p = fetchWithRetry('https://api.test/recommend', {}, { timeoutMs: LONG }).catch(e => e);

    // network error ครั้งแรก → หน่วง 1 วิ แล้วยิงใหม่ · ครั้งที่สองต้องได้เวลาเต็ม ไม่ใช่เศษงบ
    await vi.advanceTimersByTimeAsync(API_TIMEOUT_MS + 10_000);
    expect(apiFetch).toHaveBeenCalledTimes(2);
    expect(apiFetch.mock.calls[1][1].signal.aborted).toBe(false);

    await vi.advanceTimersByTimeAsync(LONG);
    await p;
  });

  it('retryOnError: false → ยิงครั้งเดียวจบ (คำขอที่ยิงซ้ำไม่ได้)', async () => {
    apiFetch.mockResolvedValue(status(503));
    const p = fetchWithRetry('https://api.test/saved-areas', { method: 'POST' }, { retryOnError: false })
      .catch(e => e);
    await vi.advanceTimersByTimeAsync(10_000);
    const err = await p;
    expect(err.kind).toBe(API_ERROR.SERVER);
    expect(apiFetch).toHaveBeenCalledTimes(1);
  });
});

describe('fetchWithRetry — การยกเลิกโดยผู้เรียก', () => {
  it('signal ที่ abort มาแล้ว: โยน AbortError โดยไม่ยิงเลย', async () => {
    const ctrl = new AbortController();
    ctrl.abort();
    apiFetch.mockResolvedValue(ok());
    await expect(fetchWithRetry('https://api.test/ndvi', { signal: ctrl.signal }))
      .rejects.toMatchObject({ name: 'AbortError' });
    expect(apiFetch).not.toHaveBeenCalled();
  });

  it('abort ระหว่างคำขอค้าง: เป็น AbortError ไม่ใช่ timeout และไม่ retry', async () => {
    const ctrl = new AbortController();
    apiFetch.mockImplementation((_url, opts) => hangUntilAborted(opts));
    const p = fetchWithRetry('https://api.test/ndvi', { signal: ctrl.signal }).catch(e => e);

    await vi.advanceTimersByTimeAsync(1_000);
    ctrl.abort();
    await vi.advanceTimersByTimeAsync(10_000);

    const err = await p;
    expect(err.name).toBe('AbortError');
    expect(err.kind).toBeUndefined();      // ไม่ใช่ ApiError — ชั้นบนต้องเงียบ
    expect(apiFetch).toHaveBeenCalledTimes(1);
  });

  it('abort ระหว่างหน่วงรอ retry: เลิกทันที ไม่นอนจนครบ', async () => {
    const ctrl = new AbortController();
    apiFetch.mockResolvedValue(status(500));
    const p = fetchWithRetry('https://api.test/ndvi', { signal: ctrl.signal }).catch(e => e);

    await vi.advanceTimersByTimeAsync(10);   // ยิงครั้งแรกเสร็จ เข้าสู่ช่วงหน่วง 1 วินาที
    expect(apiFetch).toHaveBeenCalledTimes(1);
    ctrl.abort();
    await vi.advanceTimersByTimeAsync(5_000);

    const err = await p;
    expect(err.name).toBe('AbortError');
    expect(apiFetch).toHaveBeenCalledTimes(1);   // ไม่มีครั้งที่สอง
  });
});

describe('fetchWithRetry — สถานะ "กำลังปลุกเซิร์ฟเวอร์"', () => {
  it('ขึ้นป้ายเมื่อค้างเกินเกณฑ์ และลบทิ้งเมื่อสำเร็จ', async () => {
    let resolveFetch;
    apiFetch.mockImplementation(() => new Promise(r => { resolveFetch = r; }));
    const p = fetchWithRetry('https://api.test/ndvi');

    expect(backendHint()).toBe(null);
    await vi.advanceTimersByTimeAsync(API_COLD_START_HINT_MS + 100);
    expect(backendHint()).toBe('waking');

    resolveFetch(ok());
    await p;
    expect(backendHint()).toBe(null);
    expect(inFlightCount()).toBe(0);
  });

  it('คำขอที่จบเร็วกว่าเกณฑ์ ไม่ขึ้นป้ายเลย', async () => {
    apiFetch.mockResolvedValue(ok());
    await fetchWithRetry('https://api.test/ndvi');
    await vi.advanceTimersByTimeAsync(API_COLD_START_HINT_MS * 2);
    expect(backendHint()).toBe(null);
  });

  it('ล้มเหลวก็ต้องลบป้าย ไม่ค้าง', async () => {
    apiFetch.mockImplementation((_url, opts) => hangUntilAborted(opts));
    const p = fetchWithRetry('https://api.test/lst').catch(e => e);
    await vi.advanceTimersByTimeAsync(API_COLD_START_HINT_MS + 100);
    expect(backendHint()).toBe('waking');

    await vi.advanceTimersByTimeAsync((API_TIMEOUT_MS + API_RETRY_HEADROOM_MS) * 3);
    await p;
    expect(backendHint()).toBe(null);
    expect(inFlightCount()).toBe(0);
  });

  // อาการที่ผู้ใช้เจอจริง 13 ก.ย. 2569: อยู่หน้า "AI แนะนำ" ซึ่งข้อมูลจังหวัดโหลดเสร็จ
  // ไปแล้ว (เครื่องตื่นแน่นอน) พอกดวิเคราะห์ซึ่งใช้เวลานาน ป้ายกลับขึ้นว่า
  // "กำลังปลุกเซิร์ฟเวอร์" ทั้งที่ความจริงคือกำลังคำนวณจาก GEE
  it('ช้าเพราะกำลังคำนวณ (เคยได้ response มาแล้ว) → ต้องเป็น working ไม่ใช่ waking', async () => {
    apiFetch.mockResolvedValue(ok());
    await fetchWithRetry('https://api.test/ndvi/ChiangMai');   // โหลดข้อมูลจังหวัดสำเร็จก่อน

    apiFetch.mockImplementation(() => new Promise(() => {}));  // คำขอวิเคราะห์ที่ค้างยาว
    fetchWithRetry('https://api.test/recommend/ChiangMai');
    await vi.advanceTimersByTimeAsync(API_COLD_START_HINT_MS + 100);

    expect(backendHint()).toBe('working');
  });

  it('ช้าโดยไม่เคยได้ response เลย → เป็น waking ตามเดิม', async () => {
    apiFetch.mockImplementation(() => new Promise(() => {}));
    fetchWithRetry('https://api.test/analysis/ranking');
    await vi.advanceTimersByTimeAsync(API_COLD_START_HINT_MS + 100);

    expect(backendHint()).toBe('waking');
  });

  it('หลักฐานว่าเครื่องตื่นหมดอายุตามเวลา → กลับไปเป็น waking', async () => {
    markServerAlive();
    await vi.advanceTimersByTimeAsync(API_SERVER_ALIVE_TTL_MS + 1_000);

    apiFetch.mockImplementation(() => new Promise(() => {}));
    fetchWithRetry('https://api.test/ndvi');
    await vi.advanceTimersByTimeAsync(API_COLD_START_HINT_MS + 100);

    expect(backendHint()).toBe('waking');
  });

  it('response ที่เป็น 4xx/5xx ก็นับว่าเครื่องตื่น — เครื่องที่หลับตอบอะไรไม่ได้เลย', async () => {
    apiFetch.mockResolvedValue(status(404));
    await fetchWithRetry('https://api.test/ndvi/ไม่มีจังหวัดนี้');

    apiFetch.mockImplementation(() => new Promise(() => {}));
    fetchWithRetry('https://api.test/recommend');
    await vi.advanceTimersByTimeAsync(API_COLD_START_HINT_MS + 100);

    expect(backendHint()).toBe('working');
  });

  it('หลายคำขอพร้อมกัน: ป้ายขึ้นครั้งเดียว และหายเมื่อตัวสุดท้ายจบ', async () => {
    const seen = [];
    subscribeBackendStatus(v => seen.push(v));

    const resolvers = [];
    apiFetch.mockImplementation(() => new Promise(r => resolvers.push(r)));
    const all = Promise.all([
      fetchWithRetry('https://api.test/ndvi'),
      fetchWithRetry('https://api.test/ndvi/monthly'),
      fetchWithRetry('https://api.test/lst'),
      fetchWithRetry('https://api.test/lst/monthly'),
    ]);

    await vi.advanceTimersByTimeAsync(API_COLD_START_HINT_MS + 100);
    expect(backendHint()).toBe('waking');

    // สามตัวแรกตอบกลับมาแล้ว = พิสูจน์ว่าเครื่องตื่น → ป้ายต้องเปลี่ยนข้อความเองทันที
    // จาก "กำลังปลุกเซิร์ฟเวอร์" เป็น "กำลังประมวลผล" ทั้งที่ตัวสุดท้ายยังค้างอยู่
    resolvers.slice(0, 3).forEach(r => r(ok()));
    await vi.advanceTimersByTimeAsync(10);
    expect(backendHint()).toBe('working');

    resolvers[3](ok());
    await all;
    expect(backendHint()).toBe(null);

    expect(seen).toEqual([null, 'waking', 'working', null]);
  });
});
