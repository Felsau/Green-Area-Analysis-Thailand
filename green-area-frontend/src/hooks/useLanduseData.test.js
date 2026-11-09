import { act,renderHook,waitFor } from '@testing-library/react';
import { vi } from 'vitest';
import { useLanduseData } from './useLanduseData';
import { gisRequest } from '../utils/gisClient';
import { fetchWithRetry } from '../utils/fetchRetry';
vi.mock('../utils/gisClient',()=>({gisRequest:vi.fn()}));
vi.mock('../utils/fetchRetry',()=>({fetchWithRetry:vi.fn()}));
import {publishedLddFixture as data} from '../testFixtures/publishedSnapshots';
beforeEach(()=>{gisRequest.mockReset();fetchWithRetry.mockReset();});

test('Legacy remains default and keeps its existing endpoint',async()=>{
  const {result}=renderHook(()=>useLanduseData());
  expect(result.current.landuseSource).toBe('dynamic_world');
  fetchWithRetry.mockResolvedValue({ok:true,json:async()=>({source:'legacy'})});
  await act(()=>result.current.fetchLanduse('Bangkok Metropolis',null,2026,'ldd'));
  expect(fetchWithRetry.mock.calls[0][0]).toContain('/analysis/landuse/Bangkok%20Metropolis?year=2026&source=ldd');
  expect(gisRequest).not.toHaveBeenCalled();
});
test('Published bundle is cleared immediately for failed rechecks',async()=>{
  const {result}=renderHook(()=>useLanduseData());
  act(()=>result.current.setLanduseSource('published'));
  gisRequest.mockResolvedValue(data('a'));
  await act(()=>result.current.fetchLanduse('Bangkok Metropolis',null,2026,'published'));
  expect(result.current.landuseData.geometry.metadata.edition_id).toBe(result.current.landuseData.summary.metadata.edition_id);
  gisRequest.mockRejectedValueOnce(new Error('revoked'));
  await act(()=>result.current.fetchLanduse('Bangkok Metropolis',null,2026,'published'));
  expect(result.current.landuseData).toBeNull();expect(result.current.landuseError).toContain('ไม่มีการใช้ Legacy แทน');
  expect(fetchWithRetry).not.toHaveBeenCalled();
});
test('Published geometry is fetched once per snapshot and merged into the bundle',async()=>{
  const split=seed=>{const {geometry,...summary}=data(seed);return {summary:{...summary,geometry_artifact:{sha256:seed.repeat(64),byte_size:1}},geometry};};
  const a=split('a'),b=split('b');
  const calls=()=>gisRequest.mock.calls.filter(call=>call[0]==='/published-ldd/geometry');
  gisRequest.mockImplementation(path=>Promise.resolve(path==='/published-ldd/geometry'?a.geometry:a.summary));
  const {result}=renderHook(()=>useLanduseData());act(()=>result.current.setLanduseSource('published'));
  await act(()=>result.current.fetchLanduse('Bangkok Metropolis',null,2026,'published'));
  expect(result.current.landuseData.geometry).toEqual(a.geometry);
  expect(calls()).toHaveLength(1);
  expect(calls()[0][1].query).toEqual({province:'Bangkok Metropolis',data_year:2026,snapshot_id:a.summary.snapshot_id});
  await act(()=>result.current.fetchLanduse('Bangkok Metropolis',null,2026,'published'));   // same snapshot: no second download
  expect(calls()).toHaveLength(1);expect(result.current.landuseData.geometry).toEqual(a.geometry);
  gisRequest.mockImplementation(path=>Promise.resolve(path==='/published-ldd/geometry'?b.geometry:b.summary));
  await act(()=>result.current.fetchLanduse('Bangkok Metropolis',null,2026,'published'));   // new snapshot: downloaded again
  expect(calls()).toHaveLength(2);expect(result.current.landuseData.snapshot_id).toBe(b.summary.snapshot_id);
});
test('switching source ignores a delayed old Published response',async()=>{
  const {result}=renderHook(()=>useLanduseData());let resolve;
  act(()=>result.current.setLanduseSource('published'));
  gisRequest.mockReturnValue(new Promise(r=>{resolve=r;}));
  let pending;act(()=>{pending=result.current.fetchLanduse('Bangkok Metropolis',null,2026,'published');});
  act(()=>result.current.setLanduseSource('dynamic_world'));
  await act(async()=>{resolve(data('old'));await pending;});
  expect(result.current.landuseData).toBeNull();expect(result.current.landuseSource).toBe('dynamic_world');
});
test('changing Published year clears geometry and stops old request',async()=>{
  const {result}=renderHook(()=>useLanduseData());act(()=>result.current.setLanduseSource('published'));
  gisRequest.mockResolvedValue(data('a'));await act(()=>result.current.fetchLanduse('Bangkok Metropolis',null,2026,'published'));
  act(()=>result.current.setLanduseYear(2025));expect(result.current.landuseData).toBeNull();
});
test('district scope cannot fetch full-province Published results',async()=>{
  const {result}=renderHook(()=>useLanduseData());act(()=>result.current.setLanduseSource('published'));
  await act(()=>result.current.fetchLanduse('Bangkok Metropolis','Bang Rak',2026,'published'));
  expect(gisRequest).not.toHaveBeenCalled();expect(fetchWithRetry).not.toHaveBeenCalled();expect(result.current.landuseData).toBeNull();
});

test.each(['province','data_year','lineage'])('wrong Published %s cannot populate geometry or summary',field=>{
 const b=data('a');
 if(field==='province')b.source_identity.province='Chiang Mai';
 if(field==='data_year')b.source_identity.data_year=2025;
 if(field==='lineage')b.geometry.metadata.edition_id='stale-edition';
 gisRequest.mockResolvedValue(b);return (async()=>{
  const {result}=renderHook(()=>useLanduseData());act(()=>result.current.setLanduseSource('published'));
  await act(()=>result.current.fetchLanduse('Bangkok Metropolis',null,2026,'published'));
  expect(result.current.landuseData).toBeNull();expect(result.current.landuseError).toBeTruthy();expect(fetchWithRetry).not.toHaveBeenCalled();
 })();
});
test('replacement, rollback and revocation refresh the same selected-source contract',async()=>{
 gisRequest.mockResolvedValueOnce(data('a')).mockResolvedValueOnce(data('b')).mockResolvedValueOnce(data('a')).mockRejectedValueOnce(Error('revoked'));
 const {result}=renderHook(()=>useLanduseData());act(()=>result.current.setLanduseSource('published'));
 await act(()=>result.current.fetchLanduse('Bangkok Metropolis',null,2026,'published'));
 for(const edition of ['edition-b','edition-a']){
  act(()=>window.dispatchEvent(new Event('gis-ldd-publication-change')));
  await waitFor(()=>expect(result.current.landuseData?.source_identity.edition_id).toBe(edition));
 }
 act(()=>window.dispatchEvent(new Event('gis-ldd-publication-change')));
 await waitFor(()=>expect(result.current.landuseData).toBeNull());expect(result.current.landuseSource).toBe('published');expect(fetchWithRetry).not.toHaveBeenCalled();
});
test('scope clearing preserves explicit Published selection and removes old snapshot',async()=>{
 gisRequest.mockResolvedValue(data('a'));const {result}=renderHook(()=>useLanduseData());act(()=>result.current.setLanduseSource('published'));
 await act(()=>result.current.fetchLanduse('Bangkok Metropolis',null,2026,'published'));
 act(()=>result.current.clearLanduseScope());expect(result.current.landuseData).toBeNull();expect(result.current.landuseSource).toBe('published');
});
const recheck=()=>act(()=>window.dispatchEvent(new Event('gis-ldd-publication-change')));
const pending=()=>{let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return {promise,resolve,reject};};
test('a background recheck keeps the same Published snapshot on screen until it answers',async()=>{
 gisRequest.mockResolvedValue(data('a'));const {result}=renderHook(()=>useLanduseData());act(()=>result.current.setLanduseSource('published'));
 await act(()=>result.current.fetchLanduse('Bangkok Metropolis',null,2026,'published'));
 const shown=result.current.landuseData,next=pending();gisRequest.mockReturnValue(next.promise);
 recheck();
 expect(gisRequest).toHaveBeenCalledTimes(2);   // the recheck is in flight
 expect(result.current.landuseData).toBe(shown);expect(result.current.landuseLoading).toBe(false);
 await act(async()=>{next.resolve(data('a'));await next.promise;});
 await waitFor(()=>expect(result.current.landuseData).not.toBe(shown));
 expect(result.current.landuseData.snapshot_id).toBe(shown.snapshot_id);expect(result.current.landuseLoading).toBe(false);
});
test('a background recheck that finds another snapshot removes the old one before the new one arrives',async()=>{
 const split=seed=>{const {geometry,...summary}=data(seed);return {summary:{...summary,geometry_artifact:{sha256:seed.repeat(64),byte_size:1}},geometry};};
 const a=split('a'),b=split('b'),slow=pending();
 gisRequest.mockImplementation(path=>Promise.resolve(path==='/published-ldd/geometry'?a.geometry:a.summary));
 const {result}=renderHook(()=>useLanduseData());act(()=>result.current.setLanduseSource('published'));
 await act(()=>result.current.fetchLanduse('Bangkok Metropolis',null,2026,'published'));
 expect(result.current.landuseData.snapshot_id).toBe(a.summary.snapshot_id);
 gisRequest.mockImplementation(path=>path==='/published-ldd/geometry'?slow.promise:Promise.resolve(b.summary));
 recheck();
 await waitFor(()=>expect(result.current.landuseData).toBeNull());expect(result.current.landuseLoading).toBe(true);
 await act(async()=>{slow.resolve(b.geometry);await slow.promise;});
 await waitFor(()=>expect(result.current.landuseData?.snapshot_id).toBe(b.summary.snapshot_id));expect(result.current.landuseLoading).toBe(false);
});
test('a failed recheck clears the snapshot and its error stays on screen through the next recheck',async()=>{
 gisRequest.mockResolvedValueOnce(data('a')).mockRejectedValueOnce(Error('withdrawn'));
 const {result}=renderHook(()=>useLanduseData());act(()=>result.current.setLanduseSource('published'));
 await act(()=>result.current.fetchLanduse('Bangkok Metropolis',null,2026,'published'));
 recheck();
 await waitFor(()=>expect(result.current.landuseError).toContain('ไม่มีการใช้ Legacy แทน'));expect(result.current.landuseData).toBeNull();
 const next=pending();gisRequest.mockReturnValue(next.promise);
 recheck();
 expect(gisRequest).toHaveBeenCalledTimes(3);
 expect(result.current.landuseError).toContain('ไม่มีการใช้ Legacy แทน');expect(result.current.landuseLoading).toBe(false);
 await act(async()=>{next.resolve(data('a'));await next.promise;});
 await waitFor(()=>expect(result.current.landuseData?.snapshot_id).toBe(data('a').snapshot_id));expect(result.current.landuseError).toBeNull();
});
test('late failure after a source/scope change cannot attach an old error to the new selection',async()=>{
 let reject;gisRequest.mockReturnValue(new Promise((_,no)=>{reject=no;}));const {result}=renderHook(()=>useLanduseData());
 act(()=>result.current.setLanduseSource('published'));let pending;act(()=>{pending=result.current.fetchLanduse('Bangkok Metropolis',null,2026,'published');});
 act(()=>result.current.clearLanduseScope());await act(async()=>{reject(Error('old failure'));await pending;});
 expect(result.current.landuseData).toBeNull();expect(result.current.landuseError).toBeNull();expect(result.current.landuseSource).toBe('published');
});
