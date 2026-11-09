import { useCallback, useEffect, useRef, useState } from 'react';
import { API_BASE, CURRENT_YEAR, API_COMPUTE_TIMEOUT_MS } from '../constants';
import { pushError } from '../utils/toast';
import { fetchWithRetry } from '../utils/fetchRetry';
import { gisRequest } from '../utils/gisClient';
import {publishedSnapshotMatches} from '../utils/publishedAnalysis';

// สัดส่วนการใช้ที่ดิน 5 ประเภทหลัก (จัดกลุ่มตามนิยามกรมพัฒนาที่ดิน — LDD) ของ
// จังหวัด/อำเภอ · fetch-on-demand แบบ useCoolingData (GEE compute หนัก ไม่ auto-fetch
// ตอนเลือกจังหวัด) · abort แบบ last-call-wins กันผลจังหวัดเก่ามาทับตอนสลับเร็วๆ
// source = แหล่งข้อมูล (dynamic_world | ldd) — ส่งต่อ backend, ผลลัพธ์ schema เดียวกัน
export function useLanduseData() {
  const [landuseData, setLanduseData]       = useState(null);
  const [landuseLoading, setLanduseLoading] = useState(false);
  const [landuseYear, setLanduseYearRaw]    = useState(CURRENT_YEAR);
  const [landuseSource, setLanduseSourceRaw] = useState('dynamic_world');
  const [landuseError, setLanduseError] = useState(null);
  const abortRef = useRef(null);
  const lastScope = useRef(null);
  // Published LDD geometry is fetched once per snapshot (the polled bundle only names it).
  const geometryRef = useRef(null);
  // Published scope now on screen (its snapshot, or null while it shows an error). A background recheck of
  // that same scope keeps it on screen until the recheck answers: an as-of snapshot. A failed recheck or a
  // different snapshot still clears it (a3-contracts.md). Real provinces take 10-16 s per read, so clearing
  // at the start of every 10 s recheck left the map empty most of the time.
  const shownRef = useRef(null);

  const fetchLanduse = useCallback(async (provinceEN, districtEN, year, source, { background = false } = {}) => {
    if (!provinceEN) return;
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    const { signal } = controller;
    const key = [provinceEN, districtEN || '', year, source].join('|');
    const shown = shownRef.current;
    const quiet = background && source === 'published' && shown?.key === key;

    if (!quiet) {
      shownRef.current = null;
      setLanduseLoading(true);
      setLanduseData(null);
      setLanduseError(null);
    }
    lastScope.current = { provinceEN, districtEN, year, source };
    try {
      if (source === 'published') {
        if (districtEN) throw new Error('Published LDD รองรับเฉพาะจังหวัด กรุณายกเลิกการเลือกอำเภอ');
        const summary = await gisRequest('/published-ldd', { query: { province: provinceEN, data_year: year }, signal });
        if (signal.aborted) return;
        if (quiet && summary?.snapshot_id !== shown.snapshot) {
          // The snapshot on screen is no longer the current one: remove it before loading the new one.
          shownRef.current = null;
          setLanduseData(null);
          setLanduseError(null);
          setLanduseLoading(true);
        }
        let geometry = summary?.geometry;
        if (!geometry && summary?.geometry_artifact) {
          const cached = geometryRef.current, sha = summary.geometry_artifact.sha256;
          if (cached && cached.snapshot === summary.snapshot_id && cached.sha === sha) geometry = cached.geometry;
          else {
            geometry = await gisRequest('/published-ldd/geometry', { query: { province: provinceEN, data_year: year, snapshot_id: summary.snapshot_id }, signal });
            geometryRef.current = { snapshot: summary.snapshot_id, sha, geometry };
          }
        }
        const bundle = geometry ? { ...summary, geometry } : summary;
        if(!publishedSnapshotMatches(bundle,{province:provinceEN,data_year:year,month:0,product:'landuse'}))throw new Error('Published Snapshot หรือขอบเขตไม่ตรงกัน');
        if (!signal.aborted) {
          shownRef.current = { key, snapshot: bundle.snapshot_id };
          setLanduseError(null);
          setLanduseData({ ...bundle, checked_at: Date.now() });
        }
        return;
      }
      const enc = encodeURIComponent;
      const qs = `year=${year}&source=${source || 'dynamic_world'}`
        + (districtEN ? `&district_name=${enc(districtEN)}` : '');
      const res = await fetchWithRetry(
        `${API_BASE}/analysis/landuse/${enc(provinceEN)}?${qs}`, { signal }, { timeoutMs: API_COMPUTE_TIMEOUT_MS });
      const json = await res.json();
      if (signal.aborted) return;
      if (res.ok) {
        setLanduseData(json);
      } else {
        pushError(`วิเคราะห์การใช้ที่ดินไม่สำเร็จ — ${json.detail || 'ลองอีกครั้ง'}`);
      }
    } catch (err) {
      if (signal.aborted || err?.name === 'AbortError') return;
      if (source === 'published') {
        // A failed read or recheck clears Published state; the error stays on screen through later rechecks.
        shownRef.current = { key, snapshot: null };
        setLanduseData(null);
        setLanduseError('Published ไม่พร้อมใช้งานหรือเปลี่ยนฉบับ กรุณาตรวจใหม่ ไม่มีการใช้ Legacy แทน');
        return;
      }
      console.error('fetchLanduse:', err);
      pushError('โหลดข้อมูลการใช้ที่ดินไม่สำเร็จ — ลองอีกครั้ง');
    } finally {
      if (abortRef.current === controller) {
        abortRef.current = null;
        setLanduseLoading(false);
      }
    }
  }, []);

  // สลับแหล่งข้อมูล → ล้างผลเดิม (คนละ provider อ่านคู่กันไม่ได้) ให้ผู้ใช้กดวิเคราะห์ใหม่
  const setLanduseSource = useCallback((src) => {
    abortRef.current?.abort();
    shownRef.current = null;
    setLanduseData(null);
    setLanduseError(null);setLanduseLoading(false);lastScope.current = null;
    setLanduseSourceRaw(src);
  }, []);
  const setLanduseYear = useCallback(year => {
    if (landuseSource === 'published') {
      abortRef.current?.abort();shownRef.current = null;setLanduseData(null);setLanduseError(null);lastScope.current = null;setLanduseLoading(false);
    }
    setLanduseYearRaw(year);
  }, [landuseSource]);

  useEffect(() => {
    if (landuseSource !== 'published') return;
    const recheck = () => {
      const scope=lastScope.current;
      if (!abortRef.current && scope?.source==='published' && document.visibilityState!=='hidden')
        fetchLanduse(scope.provinceEN,scope.districtEN,scope.year,scope.source,{background:true});
    };
    const visible = () => { if(document.visibilityState==='hidden') { abortRef.current?.abort();shownRef.current=null;setLanduseData(null); } else recheck(); };
    const timer=setInterval(recheck,10000);
    window.addEventListener('focus',recheck);window.addEventListener('gis-ldd-publication-change',recheck);
    document.addEventListener('visibilitychange',visible);
    const channel=typeof BroadcastChannel==='function'?new BroadcastChannel('gis-ldd-publication'):null;
    if(channel)channel.onmessage=recheck;
    return () => { clearInterval(timer);abortRef.current?.abort();channel?.close();
      window.removeEventListener('focus',recheck);window.removeEventListener('gis-ldd-publication-change',recheck);
      document.removeEventListener('visibilitychange',visible); };
  }, [landuseSource,fetchLanduse]);

  const clearLanduseScope = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current=null;
    shownRef.current=null;
    setLanduseData(null);
    setLanduseError(null);lastScope.current=null;
    setLanduseLoading(false);
  }, []);
  const resetLanduse = useCallback(() => {clearLanduseScope();setLanduseSourceRaw('dynamic_world');},[clearLanduseScope]);

  return {
    landuseData, landuseLoading, landuseYear, landuseSource, landuseError,
    setLanduseYear, setLanduseSource, fetchLanduse, resetLanduse,clearLanduseScope,
  };
}
