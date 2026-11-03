import { act,renderHook } from '@testing-library/react';
import { vi } from 'vitest';
import { useLanduseData } from './useLanduseData';
import { gisRequest } from '../utils/gisClient';
import { fetchWithRetry } from '../utils/fetchRetry';
vi.mock('../utils/gisClient',()=>({gisRequest:vi.fn()}));
vi.mock('../utils/fetchRetry',()=>({fetchWithRetry:vi.fn()}));
const data=id=>({snapshot_id:id,source_identity:{namespace:'published',province:'Bangkok Metropolis',data_year:2026,edition_id:id},
  geometry:{metadata:{edition_id:id},features:[]},summary:{metadata:{edition_id:id},total_area_m2:6400}});
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
