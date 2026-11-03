import {useEffect,useState} from 'react';
import {gisRequest} from '../utils/gisClient';

export default function GeoTiffPreparedPreview({dataset,edition,version,pending,onAction}){
  const [open,setOpen]=useState(false),[data,setData]=useState(null),[error,setError]=useState(null),[loading,setLoading]=useState(false),[refresh,setRefresh]=useState(0);
  const path=`/editions/${edition.id}`;
  useEffect(()=>{
    if(!open)return;
    const c=new AbortController();setLoading(true);setData(null);setError(null);
    gisRequest(`${path}/geotiff-prepared`,{signal:c.signal}).then(value=>{if(!c.signal.aborted)setData(value);})
      .catch(e=>{if(e.name!=='AbortError')setError(e.message||'โหลดผลเตรียม GeoTIFF ไม่สำเร็จ');})
      .finally(()=>{if(!c.signal.aborted)setLoading(false);});
    return()=>c.abort();
  },[open,path,version,refresh]);
  const body={expected_dataset_revision:dataset.revision,expected_input_revision:edition.input_revision,input_hash:edition.input_hash,
    province:dataset.province,data_year:dataset.data_year,month:dataset.month,validation_result_id:data?.validation_result_id};
  const summary=data?.ready_for_review?data.summary:null,meta=summary?.metadata,stats=summary?.statistics;
  const png=summary?.preview?.png_base64;
  const safePng=typeof png==='string'&&png.length<=64000&&/^[A-Za-z0-9+/]+={0,2}$/.test(png);
  return <section className="gis-ldd-preview" aria-label="เตรียมข้อมูลและ Preview GeoTIFF">
    <button aria-expanded={open} onClick={()=>setOpen(v=>!v)}>{open?'ปิด Preview GeoTIFF':'เตรียมข้อมูล / ดูตัวอย่าง GeoTIFF'}</button>
    {open&&<>
      <p><strong>Local Preview เพื่อการตรวจทาน — ยังไม่ Publish หรือเปิดใช้บน Dashboard</strong></p>
      <p>ข้อมูล Ready Profile ที่อัปโหลด ไม่เทียบเท่า GEE Pipeline รายปีหรือรายเดือน</p>
      <button disabled={pending||loading||!data?.validation_result_id} onClick={()=>onAction({title:'เตรียม Raster และ Summary ของ GeoTIFF',path:`${path}/geotiff-prepare-jobs`,body})}>สั่งเตรียม GeoTIFF</button>
      <button disabled={loading} onClick={()=>setRefresh(v=>v+1)}>รีเฟรชสถานะ GeoTIFF</button>
      {loading&&<p role="status">กำลังตรวจสถานะและไฟล์จริง…</p>}{error&&<p role="alert">{error}</p>}
      {data&&!loading&&<>
        <p>Native Validation: {data.validation_result_id?'มีผลตรวจผ่านปัจจุบัน':'ต้องตรวจ Validation ก่อน'}</p>
        <p>Prepare/Verification: {data.status} · {data.job?.progress||0}% · Attempts {data.attempts?.length||0}</p>
        {data.prepared&&!data.ready_for_review&&data.status!=='verification_revoked'&&<button disabled={pending} onClick={()=>onAction({title:'ตรวจ Raster และ Summary ด้วย Trusted Verifier',path:`${path}/geotiff-prepare-verification`,body:{job_id:data.job.id}})}>ตรวจไฟล์จริงและเปิด Preview GeoTIFF</button>}
        {data.job?.state==='failed'&&['transient','attempts_exhausted'].includes(data.job.error_code)&&<button disabled={pending||!body.validation_result_id} onClick={()=>onAction({title:'ลองเตรียม GeoTIFF ใหม่',path:`${path}/geotiff-prepare-retry`,body:{...body,job_id:data.job.id,reason:'เจ้าหน้าที่ขอลองใหม่หลังปัญหาชั่วคราว'}})}>ลองเตรียม GeoTIFF ใหม่</button>}
        {summary&&<>
          <p>Method <code>{meta.method_version}</code> · Edition <code>{meta.edition_id}</code></p>
          {safePng&&<img src={`data:image/png;base64,${png}`} alt="ตัวอย่าง Raster GeoTIFF ที่ตรวจไฟล์จริงแล้ว" width={256} height={256} style={{objectFit:'contain',imageRendering:'pixelated',maxWidth:'100%'}}/>}
          <p>Preview สุ่มตำแหน่งแบบ nearest สูงสุด64×64 ไม่ใช้คำนวณสถิติ พิกเซล NoData โปร่งใส</p>
          <table><caption>สถิติจาก Raster ที่เตรียมไว้ — พิกเซลที่ใช้ได้เท่านั้น</caption><tbody>
            <tr><th>Mean / Min / Max</th><td>{stats.mean} / {stats.min} / {stats.max} {stats.units}</td></tr>
            <tr><th>Valid / NoData / Total</th><td>{stats.valid_pixels} / {stats.nodata_pixels} / {stats.total_pixels}</td></tr>
            <tr><th>CRS / Resolution</th><td>{meta.crs} / {meta.resolution.join(' × ')}</td></tr>
            <tr><th>Profile / Units</th><td>{meta.source_profile} · {meta.source_units} → {meta.output_units}</td></tr>
            <tr><th>NoData / Kelvin conversion</th><td>{meta.nodata} / {meta.kelvin_to_celsius_count} ครั้ง</td></tr>
          </tbody></table>
          <p>จังหวัด {meta.province} · ปี {meta.data_year} · เดือน {meta.month} · ปี/เดือนเป็นค่าที่ระบุ ยังไม่ได้ยืนยันช่วงเวลาจากแหล่งอิสระ</p>
          <p>ขอบเขตจังหวัดประมาณ · ครอบคลุมเฉพาะ Footprint ของไฟล์ ไม่รับรองว่าครบทั้งจังหวัด · Valid pixels {(100*meta.valid_pixel_fraction).toFixed(2)}%</p>
          <details><summary>Footprint, Affine Transform และที่มาของ Artifact</summary><pre style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere'}}>{JSON.stringify(meta,null,2)}</pre></details>
        </>}
      </>}
    </>}
  </section>;
}
