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
});
