export default function LddPublicationActions({ dataset, edition, editions, pending, onAction }) {
  const body={ edition_id:edition.id,expected_dataset_revision:dataset.revision,
    expected_active_edition_id:dataset.active_edition_id,expected_input_revision:edition.input_revision,
    input_hash:edition.input_hash,validation_result_id:edition.validated_result_id,
    source_sha256:edition.upload.sha256,province:dataset.province,data_year:dataset.data_year,
    method_version:'ldd-source-area-v1',coverage_mode:'validated_source_footprint' };
  const action=(operation,title,extra={})=>onAction({title,path:`/datasets/${dataset.id}/ldd-publication/${operation}`,
    body:{...body,reason:title,...extra}});
  const active=dataset.active_edition_id===edition.id;
  return <section aria-label="เปิดใช้ LDD ใน Local Dashboard" className="gis-banner">
    <p>Admin · Local LDD เท่านั้น · ตรวจไฟล์จริงใหม่ก่อนเปลี่ยนฉบับ · ไม่รับรองว่าครบทั้งจังหวัด</p>
    <p>{active?'กำลังเปิดใช้ฉบับนี้':'ยังไม่ได้เปิดใช้ฉบับนี้'} · ไม่เปลี่ยน NDVI/LST</p>
    {!active && <>
      <button disabled={pending} onClick={()=>action('activation','เปิดใช้ LDD ใน Local Dashboard')}>เปิดใช้ LDD (Local)</button>
      <button disabled={pending} onClick={()=>action('rollback','ย้อนกลับ LDD ไปฉบับที่เคยเปิดใช้')}>ย้อนกลับมาฉบับนี้</button>
    </>}
    <button disabled={pending} onClick={()=>action('withdrawal','ถอนฉบับ LDD แบบถาวร โดยเก็บประวัติ',{
      replacement_edition_id:null})}>ถอนฉบับนี้ (ไม่แทนที่)</button>
    {active && editions.filter(e=>e.id!==edition.id && e.state==='validated' && e.upload).map(e=>
      <button key={e.id} disabled={pending} onClick={()=>action('withdrawal','ถอนฉบับและใช้ฉบับแทนที่ที่ตรวจไฟล์ใหม่',{
        replacement_edition_id:e.id})}>ถอนและใช้ฉบับ {e.id.slice(0,8)} แทน</button>)}
    <p>Withdrawn เป็นสถานะปลายทาง เก็บไฟล์เดิมไว้ และไม่สามารถ Rollback มาฉบับที่ถอนแล้ว</p>
  </section>;
}
