import { act, renderHook, waitFor } from '@testing-library/react';
import { useGisAccess } from './useGisAccess';
import { gisConfigured, gisRequest } from '../utils/gisClient';
import { supabase } from '../lib/supabaseClient';

vi.mock('../utils/gisClient', () => ({ gisConfigured: vi.fn(() => true), gisRequest: vi.fn() }));
vi.mock('../lib/supabaseClient', () => ({ supabase: { auth: { onAuthStateChange: vi.fn() } } }));
const allowed = { capabilities: ['read_catalog'], officer: true };
let unsubscribe;
beforeEach(() => { vi.clearAllMocks(); gisConfigured.mockReturnValue(true); unsubscribe = vi.fn(); supabase.auth.onAuthStateChange.mockReturnValue({ data: { subscription: { unsubscribe } } }); });
test('requires a user, feature flag and backend capability; ignores local profile', async () => {
  gisRequest.mockResolvedValue({ capabilities: [], admin: false }); const { result, rerender, unmount } = renderHook(({ id }) => useGisAccess(id), { initialProps: { id: null } });
  expect(gisRequest).not.toHaveBeenCalled(); rerender({ id: 'user-a' }); await waitFor(() => expect(result.current.loading).toBe(false)); expect(result.current.allowed).toBe(false); unmount(); expect(unsubscribe).toHaveBeenCalled();
});
test('rejects stale previous-user responses and clears privileges immediately', async () => {
  let old; gisRequest.mockImplementationOnce(() => new Promise(resolve => { old = resolve; })).mockResolvedValue({ capabilities: [] });
  const { result, rerender } = renderHook(({ id }) => useGisAccess(id), { initialProps: { id: 'user-a' } }); rerender({ id: 'user-b' });
  await act(async () => { old(allowed); }); await waitFor(() => expect(result.current.loading).toBe(false)); expect(result.current.allowed).toBe(false);
});
test('refreshes rights on auth change and aborts reads when unmounted', async () => {
  gisRequest.mockResolvedValue(allowed); const { result, unmount } = renderHook(() => useGisAccess('user-a')); await waitFor(() => expect(result.current.allowed).toBe(true));
  gisRequest.mockResolvedValue({ capabilities: [] }); await act(async () => { supabase.auth.onAuthStateChange.mock.calls[0][0]('TOKEN_REFRESHED'); });
  await waitFor(() => expect(result.current.allowed).toBe(false)); const signals = gisRequest.mock.calls.map(([, o]) => o.signal); unmount(); expect(signals.every(s => s.aborted)).toBe(true);
});
