import {gisConfigured} from '../utils/gisClient';
import {PROVINCE_TH} from '../constants';
import '../styles/published-geotiff.css';
import PublishedAnalysisAvailability from './PublishedAnalysisAvailability';

export default function PublishedGeoTiffPanel({view}){
  if(!gisConfigured())return null;
  const {source,setSource,scope,setScope,bundle,error,loading,load,otherPublished}=view;
  const png=bundle?.raster?.png_base64;
  const safePng=typeof png==='string'&&png.length<=64000&&/^[A-Za-z0-9+/]+={0,2}$/.test(png);
  return <section className="published-geotiff-panel" aria-label="แหล่งข้อมูล Raster Dashboard" data-source-snapshot={bundle?.snapshot_id||''}>
    <label>แหล่งข้อมูล Raster <select aria-label="แหล่งข้อมูล Raster" value={source} onChange={e=>setSource(e.target.value)}><option value="legacy">{otherPublished?'ใช้ Published LDD (ไม่มี Raster)':'Legacy GEE (ค่าเริ่มต้น)'}</option><option value="published">Published GeoTIFF (Local / ขอบเขตไฟล์)</option></select></label>
    {source==='published'&&<>
      <p><strong>ข้อมูลอัปโหลด Ready Profile ไม่ใช่ GEE</strong> · ไม่แทนค่า Ranking, จุดแนะนำ หรือสถิติจังหวัดเดิม</p>
      <label>จังหวัด Published <select aria-label="จังหวัด Published" value={scope.province} onChange={e=>setScope({province:e.target.value})}><option value="">เลือกจังหวัด</option>{Object.entries(PROVINCE_TH).sort((a,b)=>a[1].localeCompare(b[1],'th')).map(([en,th])=><option key={en} value={en}>{th}</option>)}</select></label>
      <label>ผลิตภัณฑ์ Published <select aria-label="ผลิตภัณฑ์ Published" value={scope.product} onChange={e=>setScope({product:e.target.value})}><option value="ndvi">NDVI</option><option value="lst">LST (Celsius)</option></select></label>
      <label>ปี Published (ค.ศ.) <input aria-label="ปี Published (ค.ศ.)" type="number" min="1980" max="2200" value={scope.data_year} onChange={e=>setScope({data_year:Number(e.target.value)})}/></label>
      <label>เดือน Published <select aria-label="เดือน Published" value={scope.month} onChange={e=>setScope({month:Number(e.target.value)})}><option value={0}>รายปีที่ระบุ (ไม่ใช้แทนรายเดือน)</option>{Array.from({length:12},(_,i)=><option key={i+1} value={i+1}>{i+1}</option>)}</select></label>
      <button disabled={loading||!scope.province} onClick={load}>ตรวจและแสดง Published Raster</button>
      {loading&&<p role="status">กำลังตรวจไฟล์จริงและ Snapshot…</p>}{error&&<p role="alert">{error} · ไม่มีการใช้ Legacy แทน</p>}
      {bundle&&<div aria-label="Published GeoTIFF Snapshot" data-source-snapshot={bundle.snapshot_id}>
        <p><strong>{bundle.source_identity.product.toUpperCase()} · {bundle.summary.statistics.units}</strong> · {bundle.source_identity.province} · {bundle.source_identity.data_year}/{bundle.source_identity.month}</p>
        <p>Edition <code>{bundle.source_identity.edition_id}</code> · Method {bundle.source_identity.method_version}</p>
        <p>ปี/เดือนยังไม่ยืนยันจากแหล่งอิสระ · เฉพาะขอบเขตไฟล์ ไม่รับรองทั้งจังหวัด · Boundary ประมาณ</p>
        <p>Mean / Min / Max: {bundle.summary.statistics.mean} / {bundle.summary.statistics.min} / {bundle.summary.statistics.max}</p>
        <p>Valid / NoData: {bundle.summary.statistics.valid_pixels} / {bundle.summary.statistics.nodata_pixels} · Kelvin conversion {bundle.summary.metadata.kelvin_to_celsius_count} ครั้ง</p>
        {safePng&&<img alt="Raster จาก Immutable Published GeoTIFF Snapshot" src={`data:image/png;base64,${png}`} width={96} height={96}/>}<p>ภาพสุ่ม nearest สูงสุด 64×64 · NoData โปร่งใส · สถิติใช้พิกเซลต้นฉบับที่ใช้ได้ทั้งหมด</p>
        <div role="img" aria-label="Legend Published GeoTIFF Snapshot" data-source-snapshot={bundle.snapshot_id}>
          <div className="published-geotiff-gradient" style={{background:`linear-gradient(to right, ${bundle.legend.palette.map(c=>'#'+c).join(',')})`}}/>
          <span>{bundle.legend.min} → {bundle.legend.max} {bundle.legend.units}</span>
        </div>
        <p>Snapshot <code>{bundle.snapshot_id}</code> · ตรวจใหม่ทุก 10 วินาทีเมื่อเปิดหน้า และเมื่อกลับมาที่แท็บ</p>
      </div>}
      <PublishedAnalysisAvailability bundle={bundle} kind="raster"/>
    </>}
  </section>;
}
