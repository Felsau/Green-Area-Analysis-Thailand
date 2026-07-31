import { renderHook, act, waitFor } from '@testing-library/react';
import { useDistrictData } from './useDistrictData';
import { fetchWithRetry } from '../utils/fetchRetry';
import { pushError } from '../utils/toast';

// Only fetchDistrictNDVI is exercised here — it uses fetchWithRetry exclusively,
// so mocking that is enough to assert the last-click-wins abort we added.
// (vi.mock is hoisted above the imports above, so they receive the mocks.)
vi.mock('../utils/fetchRetry', () => ({ fetchWithRetry: vi.fn() }));
vi.mock('../utils/toast', () => ({ pushError: vi.fn() }));

const okJson = (body) => ({ ok: true, json: async () => body });

beforeEach(() => {
  fetchWithRetry.mockReset();
  pushError.mockReset();
});

test('fetchDistrictNDVI: a newer district fetch supersedes an older one', async () => {
  // District A only settles by rejecting on abort; district B resolves at once.
  fetchWithRetry.mockImplementation((url, opts) => {
    if (url.includes('DistrictA')) {
      return new Promise((_resolve, reject) => {
        opts?.signal?.addEventListener('abort', () =>
          reject(Object.assign(new Error('Aborted'), { name: 'AbortError' })));
      });
    }
    return Promise.resolve(okJson({ ndvi_mean: 0.42, monthly: [], lst_mean: 31 }));
  });
  const { result } = renderHook(() => useDistrictData());

  await act(async () => {
    result.current.fetchDistrictNDVI('Chiang Mai', 'DistrictA');       // superseded
    await result.current.fetchDistrictNDVI('Chiang Mai', 'DistrictB'); // wins
  });

  await waitFor(() =>
    expect(result.current.districtNdviStats).toEqual(
      expect.objectContaining({ ndvi_mean: 0.42 })));
  expect(result.current.districtNdviLoading).toBe(false);
  expect(pushError).not.toHaveBeenCalled();  // abort is silent
});

test('fetchDistrictNDVI asks every endpoint for the year it was given', async () => {
  fetchWithRetry.mockResolvedValue(okJson({ ndvi_mean: 0.28, monthly: [], lst_mean: 33 }));
  const { result } = renderHook(() => useDistrictData());

  await act(async () => {
    await result.current.fetchDistrictNDVI('Bangkok Metropolis', 'Pathum Wan', 2021);
  });

  const urls = fetchWithRetry.mock.calls.map(([url]) => url);
  expect(urls).toHaveLength(4);
  urls.forEach(url => {
    expect(url).toContain('/districts/Pathum%20Wan');
    expect(url).toContain('year=2021');
  });
  expect(urls.some(u => u.endsWith('/districts/Pathum%20Wan/monthly?year=2021'))).toBe(true);
});

test('an older year never writes into the district colour cache', async () => {
  // Same reasoning as the province choropleth: districtCache is newest-year only,
  // so a 2021 lookup must not repaint one district on a different year.
  fetchWithRetry.mockResolvedValue(okJson({ ndvi_mean: 0.28, monthly: [], lst_mean: 33 }));
  const { result } = renderHook(() => useDistrictData());

  await act(async () => {
    await result.current.fetchDistrictNDVI('Bangkok Metropolis', 'Pathum Wan', 2021);
  });

  expect(result.current.districtNdviStats).toEqual(
    expect.objectContaining({ ndvi_mean: 0.28 }));
  expect(result.current.districtCache).toEqual({});
});
