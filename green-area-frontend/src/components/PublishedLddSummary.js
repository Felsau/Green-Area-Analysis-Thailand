export default function PublishedLddSummary({ bundle }) {
  const source=bundle.source_identity,summary=bundle.summary;
  return <section aria-label="สรุป Published LDD" data-source-snapshot={bundle.snapshot_id}>
    <p><strong>Published LDD · Local · เฉพาะข้อมูลในไฟล์ต้นฉบับ ไม่ใช่พื้นที่ครบทั้งจังหวัด</strong></p>
    <p>จังหวัด {source.province} · ปี ค.ศ. {source.data_year} · Edition <code>{source.edition_id}</code></p>
    <p>Method {source.method_version} · Snapshot <code>{bundle.snapshot_id}</code></p>
    <p>ปีข้อมูลมาจาก Metadata ที่ระบุ · Boundary เป็นแบบประมาณ · ไม่ใช่การรับรองข้อมูล LDD ทางการ</p>
    <p>{summary.feature_count} Features · พื้นที่ {summary.total_area_m2.toLocaleString()} m² จาก Shape_Area เดิม ไม่ตัดขอบจังหวัด</p>
    <table><caption>สรุปรหัส LDD จาก Snapshot เดียวกับ Geometry บนแผนที่</caption>
      <thead><tr><th>รหัส</th><th>พื้นที่ m²</th></tr></thead><tbody>
        {Object.entries(summary.area_by_code_m2).map(([code,area])=><tr key={code}><td>{code}</td><td>{area.toLocaleString()}</td></tr>)}
      </tbody></table>
    <p>ไม่เปลี่ยนผล NDVI/LST, Ranking หรือจุดแนะนำ · ตรวจใหม่ทุก 10 วินาทีขณะที่เปิดหน้านี้ และเมื่อกลับมาที่แท็บ</p>
  </section>;
}
