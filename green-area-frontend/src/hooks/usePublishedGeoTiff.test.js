import {act,renderHook,waitFor} from '@testing-library/react';
import {vi} from 'vitest';
import {usePublishedGeoTiff} from './usePublishedGeoTiff';
import {gisRequest} from '../utils/gisClient';
vi.mock('../utils/gisClient',()=>({gisRequest:vi.fn()}));
const target={province:'Bangkok Metropolis',data_year:2026,month:0,product:'ndvi'};
const bundle={snapshot_id:'c'.repeat(64),source_identity:{...target,namespace:'published',scope:'province'},raster:{artifact_sha256:'a'.repeat(64)},publication_identity:{artifacts:{ndvi_raster:{sha256:'a'.repeat(64)}}}};
beforeEach(()=>gisRequest.mockReset());
test('Legacy stays default and no Published request runs until explicitly selected',()=>{
 const {result}=renderHook(()=>usePublishedGeoTiff());expect(result.current.source).toBe('legacy');expect(result.current.bundle).toBeNull();expect(gisRequest).not.toHaveBeenCalled();
});
test('Exact province/product/period bundle only; changing scope immediately hides it',async()=>{
 gisRequest.mockResolvedValue(bundle);const {result}=renderHook(()=>usePublishedGeoTiff());
 act(()=>{result.current.setSource('published');result.current.setScope(target);});await act(async()=>result.current.load());
 expect(result.current.bundle).toEqual(bundle);expect(gisRequest.mock.calls[0][1].query).toEqual({...target,coverage_mode:'source_footprint_intersection'});
 act(()=>result.current.setScope({month:1}));expect(result.current.bundle).toBeNull();
});
test('Failed refresh never retains raster or falls back to Legacy',async()=>{
 gisRequest.mockResolvedValueOnce(bundle).mockRejectedValueOnce(new Error('corrupt'));
 const {result}=renderHook(()=>usePublishedGeoTiff());act(()=>{result.current.setSource('published');result.current.setScope(target);});await act(async()=>result.current.load());
 act(()=>window.dispatchEvent(new Event('gis-geotiff-publication-change')));
 await waitFor(()=>expect(result.current.error).toBe('corrupt'));expect(result.current.bundle).toBeNull();expect(result.current.source).toBe('published');
});
test('Mismatched product or month cannot render a stale snapshot',async()=>{
 gisRequest.mockResolvedValue({...bundle,source_identity:{...bundle.source_identity,month:1}});
 const {result}=renderHook(()=>usePublishedGeoTiff());act(()=>{result.current.setSource('published');result.current.setScope(target);});await act(async()=>result.current.load());
 expect(result.current.bundle).toBeNull();expect(result.current.error).toMatch(/Snapshot/);
});
