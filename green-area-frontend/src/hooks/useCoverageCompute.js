import { useCallback, useRef, useState } from 'react';
import { API_BASE } from '../constants';
import { pushError } from '../utils/toast';
import { fetchWithRetry } from '../utils/fetchRetry';

// Computes urban-subset data for provinces that don't yet have it cached for a
// given year, so the national ranking can cover all 77 provinces. Runs a small
// concurrency pool (GEE compute is the bottleneck) with progress and cancel.
//
// No longer touches ndviCache — that used to be a side effect of hitting
// /ndvi/{province} here, back when ranking read the whole-province table.
// The map choropleth fills independently via /cache/ndvi-latest.
const CONCURRENCY = 4;

export function useCoverageCompute() {
  const [computing, setComputing] = useState(false);
  const [computeProgress, setComputeProgress] = useState({ done: 0, total: 0, failed: 0 });
  const abortRef = useRef(null);

  // missing: array of { en } (English province names) to compute for `year`.
  const computeMissing = useCallback(async (year, missing) => {
    if (!missing?.length) return;
    const controller = new AbortController();
    abortRef.current = controller;
    const { signal } = controller;

    setComputing(true);
    setComputeProgress({ done: 0, total: missing.length, failed: 0 });

    let index = 0, done = 0, failed = 0;

    const worker = async () => {
      while (index < missing.length && !signal.aborted) {
        const { en } = missing[index++];
        try {
          const res = await fetchWithRetry(
            `${API_BASE}/analysis/urban-subset/${encodeURIComponent(en)}?year=${year}`, { signal });
          if (!res.ok) failed++;
        } catch (err) {
          if (err?.name === 'AbortError') return;
          failed++;
        } finally {
          done++;
          setComputeProgress({ done, total: missing.length, failed });
        }
      }
    };

    try {
      await Promise.all(
        Array.from({ length: Math.min(CONCURRENCY, missing.length) }, worker));
      if (!signal.aborted && failed > 0) {
        pushError(`คำนวณไม่สำเร็จ ${failed} จังหวัด — ลองกดคำนวณอีกครั้งได้`);
      }
    } finally {
      if (abortRef.current === controller) {
        setComputing(false);
        abortRef.current = null;
      }
    }
  }, []);

  const cancelCompute = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setComputing(false);
  }, []);

  return { computing, computeProgress, computeMissing, cancelCompute };
}
