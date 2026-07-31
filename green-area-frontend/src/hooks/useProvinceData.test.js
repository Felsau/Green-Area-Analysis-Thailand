import { renderHook, act, waitFor } from '@testing-library/react';
import { useProvinceData } from './useProvinceData';
import { CURRENT_YEAR } from '../constants';
import { fetchWithRetry } from '../utils/fetchRetry';
import { pushError } from '../utils/toast';

// fetchWithRetry is the only network dependency — mock it so we control timing
// and assert the abort/last-click-wins behaviour without a real backend.
// (vi.mock is hoisted above the imports above, so they receive the mocks.)
vi.mock('../utils/fetchRetry', () => ({ fetchWithRetry: vi.fn() }));
vi.mock('../utils/toast', () => ({ pushError: vi.fn() }));

const okJson = (body) => ({ ok: true, json: async () => body });

beforeEach(() => {
  fetchWithRetry.mockReset();
  pushError.mockReset();
});

test('fetchNDVI populates stats and updates the ndvi cache', async () => {
  fetchWithRetry.mockResolvedValue(okJson({ ndvi_mean: 0.5, monthly: [], lst_mean: 30 }));
  const setNdviCache = vi.fn();
  const { result } = renderHook(() => useProvinceData({ setNdviCache }));

  await act(async () => { await result.current.fetchNDVI('Chiang Mai'); });

  expect(result.current.ndviStats).toEqual(expect.objectContaining({ ndvi_mean: 0.5 }));
  expect(result.current.lstStats).toEqual(expect.objectContaining({ lst_mean: 30 }));
  expect(result.current.ndviLoading).toBe(false);
  // cache is updated via a functional setter — apply it to verify the value
  const updater = setNdviCache.mock.calls.at(-1)[0];
  expect(updater({})).toEqual({ 'Chiang Mai': 0.5 });
});

test('a newer fetch supersedes an older one (last-click-wins)', async () => {
  // Province A never resolves on its own — it only rejects when its signal is
  // aborted. Province B resolves immediately. Starting B must abort A so a slow
  // A response can never overwrite the panel after B was picked.
  fetchWithRetry.mockImplementation((url, opts) => {
    if (url.includes('ProvinceA')) {
      return new Promise((_resolve, reject) => {
        opts?.signal?.addEventListener('abort', () =>
          reject(Object.assign(new Error('Aborted'), { name: 'AbortError' })));
      });
    }
    return Promise.resolve(okJson({ ndvi_mean: 0.8, monthly: [], lst_mean: 25 }));
  });
  const setNdviCache = vi.fn();
  const { result } = renderHook(() => useProvinceData({ setNdviCache }));

  await act(async () => {
    result.current.fetchNDVI('ProvinceA');        // in-flight, will be superseded
    await result.current.fetchNDVI('ProvinceB');  // aborts A, then resolves
  });

  await waitFor(() =>
    expect(result.current.ndviStats).toEqual(expect.objectContaining({ ndvi_mean: 0.8 })));
  // the superseded (aborted) request must not surface an error toast
  expect(pushError).not.toHaveBeenCalled();
});

// The panel used to ignore the year selector entirely: no ?year= went out, so
// the backend always answered for the current year. These pin the wiring.
test('fetchNDVI asks every endpoint for the year it was given', async () => {
  fetchWithRetry.mockResolvedValue(okJson({ ndvi_mean: 0.42, monthly: [], lst_mean: 28 }));
  const { result } = renderHook(() => useProvinceData({ setNdviCache: vi.fn() }));

  await act(async () => { await result.current.fetchNDVI('Bangkok Metropolis', 2021); });

  const urls = fetchWithRetry.mock.calls.map(([url]) => url);
  expect(urls).toHaveLength(4);
  urls.forEach(url => expect(url).toContain('year=2021'));
  // the monthly variants must keep their path segment, not lose it to the query
  expect(urls.some(u => u.includes('/ndvi/Bangkok%20Metropolis/monthly?year=2021'))).toBe(true);
  expect(urls.some(u => u.includes('/lst/Bangkok%20Metropolis/monthly?year=2021'))).toBe(true);
});

test('fetchNDVI defaults to the current year when none is passed', async () => {
  fetchWithRetry.mockResolvedValue(okJson({ ndvi_mean: 0.5, monthly: [], lst_mean: 30 }));
  const { result } = renderHook(() => useProvinceData({ setNdviCache: vi.fn() }));

  await act(async () => { await result.current.fetchNDVI('Chiang Mai'); });

  fetchWithRetry.mock.calls.forEach(([url]) =>
    expect(url).toContain(`year=${CURRENT_YEAR}`));
});

test('an older year never writes into the choropleth cache', async () => {
  // ndviCache holds one newest-year value per province and colours the national
  // map. Letting a 2021 lookup write into it would leave one province drawn on a
  // different year from every other — a silently wrong map.
  fetchWithRetry.mockResolvedValue(okJson({ ndvi_mean: 0.31, monthly: [], lst_mean: 29 }));
  const setNdviCache = vi.fn();
  const { result } = renderHook(() => useProvinceData({ setNdviCache }));

  await act(async () => { await result.current.fetchNDVI('Bangkok Metropolis', 2021); });

  expect(result.current.ndviStats).toEqual(expect.objectContaining({ ndvi_mean: 0.31 }));
  expect(setNdviCache).not.toHaveBeenCalled();
});

test('an HTTP error surfaces a toast and leaves stats null', async () => {
  fetchWithRetry.mockResolvedValue({ ok: false, status: 500, json: async () => ({}) });
  const { result } = renderHook(() => useProvinceData({ setNdviCache: vi.fn() }));

  await act(async () => { await result.current.fetchNDVI('Krabi'); });

  expect(result.current.ndviStats).toBeNull();
  expect(result.current.ndviLoading).toBe(false);
});
