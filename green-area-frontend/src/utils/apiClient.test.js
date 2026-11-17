import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { API_BASE } from '../constants';
import { apiFetch, setApiAuthToken } from './apiClient';

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn(() => Promise.resolve({ ok: true })));
});

afterEach(() => {
  setApiAuthToken(null);
  vi.unstubAllGlobals();
});

describe('apiFetch — แนบ access token เฉพาะ request ไปแบ็กเอนด์ของเราเอง (API_BASE)', () => {
  test('ไม่มี token → ไม่แนบ Authorization', async () => {
    await apiFetch(`${API_BASE}/analysis/ranking`);
    const [, options] = fetch.mock.calls[0];
    expect(options?.headers?.Authorization).toBeUndefined();
  });

  test('มี token + URL เป็น API_BASE → แนบ Authorization', async () => {
    setApiAuthToken('secret-token');
    await apiFetch(`${API_BASE}/account/me`);
    const [, options] = fetch.mock.calls[0];
    expect(options.headers.Authorization).toBe('Bearer secret-token');
  });

  test('มี token แต่ URL เป็นโดเมนอื่น → ไม่แนบ Authorization (กัน token หลุดไปที่อื่น)', async () => {
    setApiAuthToken('secret-token');
    await apiFetch('https://tile.example.com/x/y/z.png');
    const [, options] = fetch.mock.calls[0];
    expect(options?.headers?.Authorization).toBeUndefined();
  });

  test('เก็บ headers ที่ส่งมาเดิมไว้ครบ ไม่ทับของเดิม', async () => {
    setApiAuthToken('secret-token');
    await apiFetch(`${API_BASE}/account/me`, { headers: { 'Content-Type': 'application/json' } });
    const [, options] = fetch.mock.calls[0];
    expect(options.headers['Content-Type']).toBe('application/json');
    expect(options.headers.Authorization).toBe('Bearer secret-token');
  });

  test('sign out (token = null) → หยุดแนบ Authorization ต่อจากนี้', async () => {
    setApiAuthToken('secret-token');
    setApiAuthToken(null);
    await apiFetch(`${API_BASE}/account/me`);
    const [, options] = fetch.mock.calls[0];
    expect(options?.headers?.Authorization).toBeUndefined();
  });

  // startsWith(API_BASE) เดิมให้ผ่าน เพราะ string ขึ้นต้นด้วย API_BASE จริง
  // แต่ host ที่ browser จะยิงไปคือโดเมนอื่น
  test('URL ขึ้นต้นด้วย API_BASE แต่ต่อท้ายโดเมนอื่น → ไม่แนบ Authorization', async () => {
    setApiAuthToken('secret-token');
    await apiFetch(`${API_BASE}.evil.com/x`);
    const [, options] = fetch.mock.calls[0];
    expect(options?.headers?.Authorization).toBeUndefined();
  });

  test('URL ขึ้นต้นด้วย API_BASE แต่มี userinfo ชี้ไปโดเมนอื่น (@evil.com) → ไม่แนบ Authorization', async () => {
    setApiAuthToken('secret-token');
    await apiFetch(`${API_BASE}@evil.com/x`);
    const [, options] = fetch.mock.calls[0];
    expect(options?.headers?.Authorization).toBeUndefined();
  });

  test('URL ของเราเองที่มี path + query string → แนบ Authorization', async () => {
    setApiAuthToken('secret-token');
    await apiFetch(`${API_BASE}/ndvi/Bangkok%20Metropolis/monthly?year=2021&lang=th`);
    const [, options] = fetch.mock.calls[0];
    expect(options.headers.Authorization).toBe('Bearer secret-token');
  });

  test.each([
    ['ข้อความธรรมดา', 'not a url'],
    ['string ว่าง', ''],
    ['relative path', '/account/me'],
    ['undefined', undefined],
    ['null', null],
  ])('ค่าที่ไม่ใช่ URL (%s) → ไม่แนบ Authorization และไม่ throw', async (_label, value) => {
    setApiAuthToken('secret-token');
    await expect(apiFetch(value)).resolves.toBeDefined();
    const [, options] = fetch.mock.calls[0];
    expect(options?.headers?.Authorization).toBeUndefined();
  });
});
