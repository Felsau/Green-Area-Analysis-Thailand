import PublishedAnalysisAvailability from './PublishedAnalysisAvailability';

export default function PublishedLddSummary({ bundle }) {
  const source=bundle.source_identity,summary=bundle.summary;
  // v2 (policy-v2 validation): areas from the parcel geometry in UTM; the outline may be the data producer's own.
  const v2=source.method_version==='ldd-geometry-area-v2',meta=summary.metadata||{};
  const producerOutline=v2&&Array.isArray(meta.warnings)&&meta.warnings.includes('BOUNDARY_FROM_DATA_PRODUCER');
  const outcome={accepted:'ผ่าน',accepted_with_warnings:'ผ่านพร้อมข้อสังเกต'}[meta.validation_outcome];
  return <section aria-label="สรุป Published LDD" data-source-snapshot={bundle.snapshot_id}>
    <p><strong>Published LDD · Local · เฉพาะข้อมูลในไฟล์ต้นฉบับ ไม่ใช่พื้นที่ครบทั้งจังหวัด</strong></p>
    <p>จังหวัด {source.province} · ปี ค.ศ. {source.data_year} · Edition <code>{source.edition_id}</code></p>
    <p>Method {source.method_version} · Snapshot <code>{bundle.snapshot_id}</code></p>
    <p>ปีข้อมูลมาจาก Metadata ที่ระบุ · {producerOutline?'Boundary จากชั้นขอบเขตจังหวัดในแพ็กเกจของผู้ผลิตข้อมูล (ไม่ใช่แหล่งอิสระ)':'Boundary เป็นแบบประมาณ'} · ไม่ใช่การรับรองข้อมูล LDD ทางการ</p>
    {v2&&outcome&&<p>ผลตรวจไฟล์: {outcome} ({meta.validation_outcome})</p>}
    <p>{summary.feature_count} Features · พื้นที่ {summary.total_area_m2.toLocaleString()} m² {v2?'คำนวณจากรูปแปลงในระบบพิกัด UTM':'จาก Shape_Area เดิม'} ไม่ตัดขอบจังหวัด</p>
    <table><caption>สรุปรหัส LDD จาก Snapshot เดียวกับ Geometry บนแผนที่</caption>
      <thead><tr><th>รหัส</th><th>พื้นที่ m²</th></tr></thead><tbody>
        {Object.entries(summary.area_by_code_m2).map(([code,area])=><tr key={code}><td>{code}</td><td>{area.toLocaleString()}</td></tr>)}
      </tbody></table>
    <p>ไม่เปลี่ยนผล NDVI/LST, Ranking หรือจุดแนะนำ · ตรวจใหม่ทุก 10 วินาทีขณะที่เปิดหน้านี้ และเมื่อกลับมาที่แท็บ</p>
    <PublishedAnalysisAvailability bundle={bundle} kind="landuse"/>
  </section>;
}
