import {useEffect,useState} from 'react';
import {gisRequest} from '../utils/gisClient';

export default function GeoTiffPublicationActions({dataset,edition,editions,version,pending,admin,onAction}){
  const [info,setInfo]=useState(null),[error,setError]=useState(''),[period,setPeriod]=useState(false),[coverage,setCoverage]=useState(false);
  useEffect(()=>{
    const c=new AbortController();setInfo(null);setError('');setPeriod(false);setCoverage(false);
    gisRequest(`/editions/${edition.id}/geotiff-publication`,{signal:c.signal}).then(v=>{if(!c.signal.aborted)setInfo(v);})
      .catch(e=>{if(e.name!=='AbortError')setError(e.message);});return()=>c.abort();
  },[edition.id,version]);
  const active=dataset.active_edition_id===edition.id;
  const body={edition_id:edition.id,expected_dataset_revision:dataset.revision,expected_active_edition_id:dataset.active_edition_id,
    expected_input_revision:edition.input_revision,input_hash:edition.input_hash,validation_result_id:info?.validation_result_id,
    certificate_id:info?.certificate_id,source_sha256:edition.upload.sha256,province:dataset.province,data_year:dataset.data_year,
    month:dataset.month,product:dataset.purpose,profile:edition.manifest.profile,method_version:'geotiff-grid-celsius-v1',
    coverage_mode:'source_footprint_intersection',policy_version:'local-declared-period-footprint-v1',
    acknowledge_unverified_period:true,acknowledge_limited_coverage:true};
  const disabled=pending||!period||!coverage||!info?.certificate_id;
  const action=(op,title,extra={})=>onAction({title,path:`/datasets/${dataset.id}/geotiff-publication/${op}`,body:{...body,reason:title,...extra}});
  return <section className="gis-banner" aria-label="เปิดใช้ GeoTIFF ใน Local Dashboard">
    <strong>Local Published GeoTIFF · {dataset.purpose.toUpperCase()} · {active?'กำลังเปิดใช้ฉบับนี้':'ยังไม่ได้เปิดใช้ฉบับนี้'}</strong>
    <p>ข้อมูลอัปโหลด Ready Profile ไม่ใช่ผลวิเคราะห์ GEE · ปี/เดือนยังไม่ผ่านการรับรองจากแหล่งอิสระ · ไม่รับรองว่าครบทั้งจังหวัด</p>
    {error&&<p role="alert">{error}</p>}
    <p>{info?.catalog_prepared?'มี Certificate ใน Catalog — ยังต้องตรวจไฟล์จริงใหม่ก่อนเปิดใช้':'ยังไม่พร้อมเปิดใช้: ต้อง Prepare และ Trusted Verify ก่อน'}</p>
    {admin&&edition.state==='draft'&&<>
      <label><input type="checkbox" checked={period} onChange={e=>setPeriod(e.target.checked)}/> ยอมรับว่าปีและเดือนเป็นค่าที่ระบุ ยังไม่ได้ยืนยันช่วงเวลาจริง</label>
      <label><input type="checkbox" checked={coverage} onChange={e=>setCoverage(e.target.checked)}/> ยอมรับเฉพาะขอบเขตไฟล์และสถิติพิกเซล ไม่ใช่สถิติทั้งจังหวัด</label>
      {!active&&<>
        <button disabled={disabled||!info?.catalog_prepared||!info?.identity} onClick={()=>action('activation','เปิดใช้ GeoTIFF Local โดยยอมรับช่วงเวลาและขอบเขตที่ยังไม่รับรอง')}>เปิดใช้ GeoTIFF (Local)</button>
        <button disabled={disabled||!info?.catalog_prepared||!info?.identity} onClick={()=>action('rollback','ย้อนกลับ GeoTIFF ไปฉบับที่เคยเปิดใช้ โดยตรวจไฟล์จริงใหม่')}>ย้อนกลับ GeoTIFF มาฉบับนี้</button>
      </>}
      <button disabled={disabled} onClick={()=>action('withdrawal','ถอนฉบับ GeoTIFF แบบถาวร โดยเก็บประวัติ',{replacement_edition_id:null})}>ถอน GeoTIFF (ไม่แทนที่)</button>
      {active&&editions.filter(e=>e.id!==edition.id&&e.state==='draft'&&e.upload&&e.manifest?.schema_version===4).map(e=>
        <button key={e.id} disabled={disabled} onClick={()=>action('withdrawal','ถอน GeoTIFF และตรวจฉบับแทนที่ใหม่',{replacement_edition_id:e.id})}>ถอนและแทนด้วย GeoTIFF {e.id.slice(0,8)}</button>)}
      <p>ถอนใช้เป็นสถานะปลายทาง ไม่ลบไฟล์ และย้อนกลับมาฉบับที่ถอนแล้วไม่ได้</p>
    </>}
  </section>;
}
