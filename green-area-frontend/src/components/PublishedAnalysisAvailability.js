import {publishedAvailability} from '../utils/publishedAnalysis';

export default function PublishedAnalysisAvailability({bundle,kind,feature}){
  const availability=publishedAvailability(bundle,kind);
  const labels={supported:'รองรับ',unsupported:'ยังไม่รองรับ',unavailable:'ยังไม่พร้อม'};
  const rows=feature?availability.features.filter(f=>f.key===feature):availability.features;
  const body=<>
    <p>Published {kind==='landuse'?'LDD':'GeoTIFF'} · สรุปเฉพาะขอบเขตไฟล์ ไม่มีการนำผล Legacy มาแทนค่าที่ขาด</p>
    {availability.source&&<p>Edition <code>{availability.source.edition_id}</code> · ปี/เดือนที่ระบุ {availability.source.data_year}/{availability.source.month} · Method {availability.source.method_version}</p>}
    <ul>{rows.map(f=><li key={f.key}><strong>{f.label} — {labels[f.status]}</strong><p>{f.reason}</p></li>)}</ul>
    <p>ข้อมูลและฟีเจอร์ Legacy ยังอยู่ครบ เลือก Legacy เพื่อใช้งานตามแหล่งข้อมูลเดิม</p>
  </>;
  return <section aria-label="ความพร้อมของฟีเจอร์ Published" data-source-snapshot={availability.snapshot_id||''}>
    {feature?body:<details><summary>ความพร้อมของฟีเจอร์วิเคราะห์ Published</summary>{body}</details>}
  </section>;
}
