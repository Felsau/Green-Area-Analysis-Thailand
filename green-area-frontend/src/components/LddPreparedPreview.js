import { useEffect, useState } from 'react';
import { gisRequest } from '../utils/gisClient';

function GeometryPreview({ geometry }) {
  const polygons = (geometry?.features || []).flatMap(f => f.geometry.type === 'Polygon'
    ? [f.geometry.coordinates] : f.geometry.coordinates);
  const points = polygons.flat(2);
  if (!points.length) return <p>Geometry เกินขอบเขต Preview หรือไม่มีส่วนที่แสดงได้</p>;
  const xs = points.map(p => p[0]), ys = points.map(p => p[1]);
  const x = Math.min(...xs), y = Math.min(...ys), width = Math.max(...xs) - x || 0.001, height = Math.max(...ys) - y || 0.001;
  const scale = Math.min(580 / width, 280 / height), left = (600 - width * scale) / 2, bottom = (300 + height * scale) / 2;
  return <svg role="img" aria-label="ตัวอย่าง Geometry LDD ใน EPSG:4326" viewBox="0 0 600 300" style={{ width: '100%', maxHeight: 300, background: '#eef4ee' }}>
    {polygons.map((polygon, i) => <path key={i} d={polygon.map(ring => 'M' + ring.map(p => `${left + (p[0] - x) * scale},${bottom - (p[1] - y) * scale}`).join('L') + 'Z').join(' ')} fillRule="evenodd" fill="#72ad7d" stroke="#215b35" strokeWidth="1" />)}
  </svg>;
}

export default function LddPreparedPreview({ dataset, edition, version, pending, onAction }) {
  const [open, setOpen] = useState(false), [data, setData] = useState(null), [error, setError] = useState(null);
  const [refresh, setRefresh] = useState(0), [loading, setLoading] = useState(false);
  const path = `/editions/${edition.id}`;
  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    setLoading(true);setError(null);setData(null);
    gisRequest(`${path}/prepared`, { signal: controller.signal }).then(setData).catch(e => {
      if (e.name !== 'AbortError') setError(e.message || 'โหลดตัวอย่างไม่สำเร็จ');
    }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [open, path, version, refresh]);
  const body = { expected_dataset_revision: dataset.revision, expected_input_revision: edition.input_revision,
    input_hash: edition.input_hash, province: dataset.province, data_year: dataset.data_year };
  return <section className="gis-ldd-preview" aria-label="เตรียมข้อมูลและ Preview LDD">
    <button aria-expanded={open} onClick={() => setOpen(v => !v)}>{open ? 'ปิดตัวอย่างข้อมูลเตรียมไว้' : 'เตรียมข้อมูล / ดูตัวอย่าง LDD'}</button>
    {open && <>
      <p><strong>Local Preview เท่านั้น — ยังไม่เปิดใช้บน Dashboard</strong></p>
      <p>ครบตาม Feature ของไฟล์ต้นฉบับ ไม่ใช่การรับรองว่าครบทั้งจังหวัด · ปีข้อมูลเป็นค่าที่ระบุในการอัปโหลด</p>
      <button disabled={pending || loading} onClick={() => onAction({ title: 'เตรียม Geometry และ Summary ของ LDD', path: `${path}/prepare-jobs`, body })}>สั่งเตรียมข้อมูล LDD</button>
      <button disabled={loading} onClick={() => setRefresh(v => v + 1)}>รีเฟรชสถานะเตรียมข้อมูล</button>
      {loading && <p role="status">กำลังตรวจสถานะและไฟล์ผลลัพธ์…</p>}
      {error && <p role="alert">{error}</p>}
      {data && !loading && <>
        <p>สถานะ: {({ not_prepared: 'ยังไม่ได้เตรียม', queued: 'รอ Worker', running: 'กำลังเตรียม', succeeded: 'เตรียมแล้ว รอตรวจไฟล์จริง', failed: 'เตรียมไม่สำเร็จ', verified_for_local_review: 'ตรวจไฟล์จริงผ่าน พร้อมให้ตรวจทาน', verification_revoked: 'ไฟล์หายหรือเสียหาย — ไม่พร้อมใช้งาน' })[data.status] || data.status}</p>
        {data.job && <p>ความคืบหน้า: {data.job.progress || 0}% · Attempts: {data.attempts?.length || 0}</p>}
        {data.prepared && !data.ready_for_publication && data.status !== 'verification_revoked' && <button disabled={pending} onClick={() => onAction({ title: 'ตรวจไฟล์ผลลัพธ์จริงด้วย Trusted Verifier', path: `${path}/prepare-verification`, body: { job_id: data.job.id } })}>ตรวจไฟล์จริงและเปิด Preview</button>}
        {data.job?.state === 'failed' && ['transient', 'attempts_exhausted'].includes(data.job.error_code) && <button disabled={pending} onClick={() => onAction({ title: 'ลองเตรียมข้อมูลใหม่หลังปัญหาชั่วคราว', path: `${path}/prepare-retry`, body: { ...body, job_id: data.job.id, reason: 'เจ้าหน้าที่ขอลองเตรียมข้อมูลใหม่หลังปัญหาชั่วคราว' } })}>ลองเตรียมใหม่</button>}
        {data.ready_for_publication && data.summary && <>
          <p>Method: <code>{data.method_version}</code> · {data.summary.feature_count} Features · พื้นที่รวม {data.summary.total_area_m2.toLocaleString()} m²</p>
          <GeometryPreview geometry={data.geometry} />
          {data.preview_truncated && <p>Preview แสดงบาง Feature ตามขีดจำกัดการแสดงผล ไฟล์ที่จัดเก็บและตรวจสอบยังคงครบ</p>}
          <table><caption>{data.method_version === 'ldd-geometry-area-v2' ? 'พื้นที่ตามรหัส LDD — คำนวณจากรูปแปลง (UTM) ไม่ตัดขอบจังหวัด' : 'พื้นที่ตามรหัส LDD — Shape_Area เดิม ไม่ตัดขอบจังหวัด'}</caption><thead><tr><th>LU_CODE</th><th>พื้นที่ m²</th></tr></thead>
            <tbody>{Object.entries(data.summary.area_by_code_m2).map(([code, area]) => <tr key={code}><td>{code}</td><td>{area.toLocaleString()}</td></tr>)}</tbody></table>
          <details><summary>ข้อมูลอ้างอิงผลที่เตรียมไว้</summary><pre>{JSON.stringify(data.summary.metadata, null, 2)}</pre></details>
        </>}
      </>}
    </>}
  </section>;
}
