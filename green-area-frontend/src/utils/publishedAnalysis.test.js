import {publishedSnapshotMatches,publishedAvailability} from './publishedAnalysis';
import {publishedGeoFixture,publishedLddFixture} from '../testFixtures/publishedSnapshots';

test.each(['ndvi','lst'])('ready %s preserves valid zero values, NoData, units and source identity',product=>{
  const b=publishedGeoFixture('a',product),original=JSON.stringify(b);
  expect(publishedSnapshotMatches(b,{province:'Bangkok Metropolis',data_year:2026,month:0,product})).toBe(true);
  expect(publishedAvailability(b,'raster').features.filter(f=>f.status==='supported').map(f=>f.key)).toEqual(['map','summary']);
  expect(JSON.stringify(b)).toBe(original);
});
test('LDD remains code/Shape_Area data and never becomes an NDVI measurement',()=>{
  const b=publishedLddFixture();expect(publishedSnapshotMatches(b)).toBe(true);
  expect(publishedAvailability(b,'landuse').features.find(f=>f.key==='summary').reason).toContain('ไม่ใช่ค่า NDVI');
  expect(publishedAvailability(b,'raster').features.some(f=>f.status==='supported')).toBe(false);
});
test.each(['province','data_year','month','product'])('requested %s mismatch rejects the entire snapshot',key=>{
  const b=publishedGeoFixture();const wrong={province:'Chiang Mai',data_year:2025,month:1,product:'lst'};
  expect(publishedSnapshotMatches(b,{[key]:wrong[key]})).toBe(false);
});
test.each(['legacy','hash','lineage','units','nodata','no_valid_pixels','nonfinite','period','method','artifact'])('invalid %s never produces supported analytical values',kind=>{
  const b=publishedGeoFixture();
  if(kind==='legacy')b.source_identity.namespace='legacy';
  if(kind==='hash')b.source_identity.source_sha256='missing';
  if(kind==='lineage')b.summary.metadata.edition_id='old-edition';
  if(kind==='units')b.summary.statistics.units='kelvin';
  if(kind==='nodata')b.summary.statistics.nodata_pixels=null;
  if(kind==='no_valid_pixels')b.summary.statistics.valid_pixels=0;
  if(kind==='nonfinite')b.summary.statistics.mean=NaN;
  if(kind==='period')b.publication_identity.period_verified=true;
  if(kind==='method')b.source_identity.method_version='unknown';
  if(kind==='artifact')b.raster.artifact_sha256='f'.repeat(64);
  expect(publishedSnapshotMatches(b)).toBe(false);expect(publishedAvailability(b,'raster').features.some(f=>f.status==='supported')).toBe(false);
});
test('no implicit timeseries, comparison, rank, priority, saved-AOI or cooling for any current published product',()=>{
  for(const b of [publishedLddFixture(),publishedGeoFixture(),publishedGeoFixture('b','lst')]){
    const a=publishedAvailability(b,b.source_identity.product==='landuse'?'landuse':'raster');
    expect(a.snapshot_id).toBe(b.snapshot_id);
    for(const key of ['province','compare','trend','ranking','recommend','cooling','saved'])expect(a.features.find(f=>f.key===key).status).toBe('unsupported');
  }
});
test('loading, revocation or source removal makes supported views unavailable rather than zero',()=>{
  const a=publishedAvailability(null,'raster');expect(a.snapshot_id).toBeNull();
  expect(a.features.filter(f=>['map','summary'].includes(f.key)).every(f=>f.status==='unavailable')).toBe(true);
});
test('LDD geometry/summary lineage and count must match the same snapshot',()=>{
  const b=publishedLddFixture();b.geometry.metadata.input_hash='f'.repeat(64);expect(publishedSnapshotMatches(b)).toBe(false);
  const c=publishedLddFixture();c.summary.feature_count=1;expect(publishedSnapshotMatches(c)).toBe(false);
});
test('partial display payloads cannot be advertised as supported maps or crash the legend',()=>{
 for(const product of ['landuse','ndvi','lst']){
  const b=product==='landuse'?publishedLddFixture():publishedGeoFixture('a',product);delete b.legend;
  expect(publishedSnapshotMatches(b)).toBe(false);
 }
 const b=publishedGeoFixture();b.raster.png_base64='https://invalid.test/image';expect(publishedSnapshotMatches(b)).toBe(false);
});
