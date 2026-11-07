import { cloneElement, useCallback, useEffect, useId, useRef, useState } from 'react';
import { gisConfigured, gisRequest } from '../utils/gisClient';
import '../styles/gis.css';
import LddPreparedPreview from './LddPreparedPreview';
import LddPublicationActions from './LddPublicationActions';
import GeoTiffPreparedPreview from './GeoTiffPreparedPreview';
import GeoTiffPublicationActions from './GeoTiffPublicationActions';

const labels = { draft: 'ฉบับร่าง', validating: 'กำลังตรวจสอบ', validated: 'ตรวจผ่านแล้ว', withdrawn: 'ถอนแล้ว',
  queued: 'รอประมวลผล', running: 'กำลังประมวลผล', succeeded: 'สำเร็จ', failed: 'ไม่สำเร็จ', expired: 'Lease หมดอายุ',
  landuse: 'การใช้ที่ดิน LDD', ndvi: 'NDVI', lst: 'LST' };
const errorLabels = { invalid_data: 'ข้อมูลไม่ผ่านการตรวจ', transient: 'ปัญหาชั่วคราวของระบบ',
  attempts_exhausted: 'ครบจำนวนครั้งที่อนุญาต', lease_expired: 'Worker ขาดการติดต่อ', internal_error: 'ข้อผิดพลาดภายใน' };
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function Status({ value }) { return <span className={`gis-status gis-status--${value}`}>{labels[value] || 'ไม่ทราบสถานะ'}</span>; }
function ErrorNote({ error }) { return error ? <p role="alert" className="gis-error">{error.message || 'โหลดข้อมูลไม่สำเร็จ'}</p> : null; }
function Field({ label, children, ...props }) {
  const id = useId();
  return <div className="gis-field"><label htmlFor={id}>{label}</label>{children ? cloneElement(children, { id }) : <input id={id} {...props} />}</div>;
}

function usePage(path, query, version) {
  const filterKey = JSON.stringify(query);
  const [page, setPage] = useState({ data: [], loading: true });
  const [cursor, setCursor] = useState(null);
  const [reload, setReload] = useState(0);
  const latest = useRef(null);
  const identity = `${path}|${filterKey}|${version}`;
  const load = useCallback((next = null) => setCursor(next), []);
  useEffect(() => { setCursor(null); }, [identity]);
  useEffect(() => {
    const abort = new AbortController();
    // A changed filter/parent always starts from page one, even before cursor reset renders.
    const next = latest.current === identity ? cursor : null;
    latest.current = identity;
    setPage({ data: [], loading: true });
    gisRequest(path, { query: { ...JSON.parse(filterKey), limit: 20, ...(next ? { cursor: next } : {}) }, signal: abort.signal })
      .then(value => { if (!abort.signal.aborted) setPage({ ...value, loading: false }); })
      .catch(error => { if (!abort.signal.aborted) setPage({ data: [], loading: false, error }); });
    return () => abort.abort();
  }, [path, filterKey, version, cursor, identity, reload]);
  return { ...page, load, refresh: () => { setCursor(null); setReload(n => n + 1); } };
}

function PageControls({ page }) {
  return <div className="gis-actions">
    <button onClick={page.refresh} disabled={page.loading}>รีเฟรชรายการ</button>
    <button onClick={() => page.load(null)} disabled={page.loading}>หน้าแรก</button>
    {page.has_more && <button onClick={() => page.load(page.next_cursor)} disabled={page.loading}>หน้าถัดไป</button>}
  </div>;
}
function PageState({ page, empty = 'ยังไม่มีข้อมูลในหน้านี้' }) {
  return <><ErrorNote error={page.error} />{page.loading ? <p role="status">กำลังโหลดข้อมูล…</p>
    : !page.error && page.data.length === 0 ? <p className="gis-empty">{empty}</p> : null}</>;
}

// All writes require a separate confirmation; focus stays inside the modal.
function Modal({ title, children, onClose, locked = false }) {
  const ref = useRef(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  useEffect(() => {
    const previous = document.activeElement;
    const node = ref.current;
    node.querySelector('input,textarea,select,button')?.focus();
    return () => previous?.focus();
  }, []);
  return <div className="gis-scrim"><section ref={ref} role="dialog" aria-modal="true" aria-label={title} className="gis-dialog"
    onKeyDown={event => {
      if (event.key === 'Escape' && !locked) { event.stopPropagation(); closeRef.current(); }
      if (event.key !== 'Tab') return;
      const nodes = [...ref.current.querySelectorAll('button,input,textarea,select')].filter(n => !n.disabled);
      const first = nodes[0], last = nodes[nodes.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    }}><h2>{title}</h2>{children}</section></div>;
}

function ManifestField({ value = '' }) {
  return <Field label="Manifest JSON (Synthetic V1/V2)"><textarea name="manifest" required maxLength={16000} rows={9} defaultValue={value}
    placeholder="วาง Manifest ของ Synthetic Fixture ที่ลงทะเบียนไว้ใน Local Sandbox" /></Field>;
}

function parseManifest(raw, dataset) {
  const manifest = JSON.parse(raw);
  if (![1, 2].includes(manifest?.schema_version) || manifest.provider !== 'synthetic' || !manifest.fixture_id
    || !/^[a-f0-9]{64}$/.test(manifest.sha256 || '') || (dataset.kind === 'ldd_shapefile') !== (manifest.data_kind === 'polygon')) {
    throw new Error('กรุณาใช้ Manifest Synthetic ที่ตรงกับชนิด Dataset และมี SHA256 ถูกต้อง');
  }
  return manifest;
}

function ProcessingFields({ provinces }) {
  const [province, setProvince] = useState('');
  const [scope, setScope] = useState('province');
  const [districts, setDistricts] = useState([]);
  const [metric, setMetric] = useState('ndvi');
  const [error, setError] = useState(null);
  const [modes, setModes] = useState(['offline_synthetic']);
  const [mode, setMode] = useState('offline_synthetic');
  useEffect(() => {
    const abort = new AbortController();
    // Only the backend (migration 048 readiness) can offer the GEE source.
    gisRequest('/processing-options', { signal: abort.signal })
      .then(value => { if (!abort.signal.aborted && Array.isArray(value.modes) && value.modes.includes('gee_dashboard')) setModes(['offline_synthetic', 'gee_dashboard']); })
      .catch(() => {});
    return () => abort.abort();
  }, []);
  useEffect(() => {
    const abort = new AbortController();
    setDistricts([]); setError(null);
    if (province) gisRequest('/processing-options', { query: { province }, signal: abort.signal })
      .then(value => { if (!abort.signal.aborted) setDistricts(value.districts || []); })
      .catch(err => { if (!abort.signal.aborted) setError(err); });
    return () => abort.abort();
  }, [province]);
  const gee = mode === 'gee_dashboard';
  return <>
    {modes.length > 1 && <Field label="แหล่งข้อมูล"><select name="mode" value={mode} onChange={e => setMode(e.target.value)}>
      <option value="offline_synthetic">ข้อมูลจำลอง (Offline Synthetic)</option><option value="gee_dashboard">Google Earth Engine (ภาพดาวเทียมจริง)</option></select></Field>}
    {gee && <p role="note">ประมวลผลจากภาพดาวเทียมจริงใน Google Earth Engine ด้วยวิธีเดียวกับ Dashboard ผลจะเพิ่มหรือปรับปรุงจุดข้อมูลของช่วงเวลาที่เลือกในอนุกรมเวลา โดยไม่ลบข้อมูลช่วงเวลาอื่น ใช้เวลาประมาณ 1 นาที และใช้โควตา GEE ของโครงการ</p>}
    {!gee && <p role="note">Offline Synthetic เท่านั้น: ใช้พิกเซลจำลอง ไม่ใช่ภาพดาวเทียมหรือค่าของพื้นที่ที่เลือก ไม่มีการเรียก Live GEE</p>}
    <Field label="ดัชนีประมวลผล"><select name="metric" value={metric} onChange={e => setMetric(e.target.value)}><option value="ndvi">NDVI</option><option value="lst">LST</option></select></Field>
    <Field label="จังหวัดประมวลผล"><select name="province" required value={province} onChange={e => setProvince(e.target.value)}><option value="">เลือกจังหวัด</option>{provinces.map(p => <option key={p.name_en} value={p.name_en}>{p.name_th || p.name_en}</option>)}</select></Field>
    <Field label="ระดับพื้นที่"><select name="scope" value={scope} onChange={e => setScope(e.target.value)}><option value="province">จังหวัด</option><option value="district">อำเภอ</option></select></Field>
    {scope === 'district' && <Field label="อำเภอประมวลผล"><select key={province} name="district" required disabled={!districts.length}><option value="">เลือกอำเภอ</option>{districts.map(d => <option key={d.name_en} value={d.name_en}>{d.name_th || d.name_en}</option>)}</select></Field>}
    <Field label="ปีประมวลผล (ค.ศ.)" name="data_year" type="number" required min={metric === 'ndvi' ? 2017 : 2013} max={new Date().getFullYear()} defaultValue={new Date().getFullYear()} />
    <Field label="ช่วงเวลาประมวลผล"><select name="month"><option value="0">รายปี</option>{Array.from({ length: 12 }, (_, i) => <option key={i + 1} value={i + 1}>เดือน {i + 1}</option>)}</select></Field>
    {!gee && <Field label="ชุดข้อมูลจำลอง"><select name="scenario"><option value="standard">ข้อมูลทดสอบปกติ</option><option value="no_data">ไม่มีพิกเซลที่ใช้ได้</option><option value="transient_once">จำลองบริการขัดข้องครั้งแรก</option></select></Field>}
    <ErrorNote error={error} />
  </>;
}

function FormDialog({ form, prepare, close, provinces }) {
  const [error, setError] = useState(null);
  const dataset = form.dataset;
  return <Modal title={form.title} onClose={close}>
    <form onSubmit={event => {
      event.preventDefault();
      try {
        const values = Object.fromEntries(new FormData(event.currentTarget));
        let body;
        if (form.type === 'processing') {
          if (values.scope === 'district' && !values.district) throw new Error('กรุณาเลือกอำเภอที่โหลดจากจังหวัด');
          body = { province: values.province, district: values.scope === 'district' ? values.district : null,
            metric: values.metric, data_year: Number(values.data_year), month: Number(values.month),
            mode: values.mode === 'gee_dashboard' ? 'gee_dashboard' : 'offline_synthetic',
            scenario: values.mode === 'gee_dashboard' ? 'standard' : values.scenario, expected_revision: 1 };
        } else if (form.type === 'dataset') {
          const [kind, purpose] = values.profile.split(':');
          body = { title: values.title.trim(), province: values.province, kind, purpose,
            data_year: Number(values.data_year), month: kind === 'ldd_shapefile' ? 0 : Number(values.month) };
        } else if (form.type === 'geotiff_upload') {
          const file = values.file;
          if (!(file instanceof File) || !/\.tiff?$/i.test(file.name) || file.size < 1 || file.size > 20 * 1024**2) throw new Error('กรุณาเลือก GeoTIFF ขนาดไม่เกิน 20 MiB');
          prepare({ title: form.title, path: form.path, body: file,
            query: { expected_revision: dataset.revision, crs: values.crs, profile: values.profile, source_label: values.source_label.trim(), acquisition_date: values.acquisition_date } });
          return;
        } else if (form.type === 'upload') {
          const file = values.file;
          if (!(file instanceof File) || !/\.zip$/i.test(file.name) || file.size < 1 || file.size > 20 * 1024**2) throw new Error('กรุณาเลือก Shapefile ZIP ขนาดไม่เกิน 20 MiB');
          prepare({ title: form.title, path: form.path, body: file,
            query: { expected_revision: dataset.revision, crs: values.crs, encoding: values.encoding, source_label: values.source_label.trim() } });
          return;
        } else if (form.type === 'title') body = { title: values.title.trim(), expected_revision: dataset.revision };
        else if (form.type === 'edition') body = { manifest: parseManifest(values.manifest, dataset),
          ...(form.edition ? { expected_revision: form.edition.input_revision } : {}) };
        else {
          body = { ...form.body, reason: values.reason.trim() };
          if (!body.reason) throw new Error('กรุณาระบุเหตุผล');
          if (form.type === 'grant') { if (!uuid.test(values.user_id)) throw new Error('กรุณาระบุ UUID ของผู้ใช้ Local ที่มีอยู่แล้ว'); body.user_id = values.user_id; }
          if (form.type === 'withdraw') body.replacement_edition_id = values.replacement || null;
        }
        prepare({ title: form.title, path: form.path, method: form.method || 'POST', body });
      } catch (err) { setError(err instanceof SyntaxError ? new Error('Manifest JSON ไม่ถูกต้อง') : err); }
    }}>
      {form.type === 'dataset' && <>
        <Field label="ชื่อชุดข้อมูล" name="title" required maxLength={200} />
        <Field label="จังหวัด"><select name="province" required><option value="">เลือกจังหวัด</option>{provinces.map(p => <option key={p.name_en} value={p.name_en}>{p.name_th || p.name_en}</option>)}</select></Field>
        <Field label="ปีข้อมูล (ค.ศ.)" name="data_year" type="number" min="1980" max={new Date().getFullYear() + 1} required defaultValue={new Date().getFullYear()} />
        <Field label="ประเภทข้อมูล"><select name="profile"><option value="ldd_shapefile:landuse">Shapefile LDD รายปี</option><option value="geotiff:ndvi">GeoTIFF NDVI</option><option value="geotiff:lst">GeoTIFF LST</option></select></Field>
        <Field label="เดือน GeoTIFF (0 = รายปี / LDD ใช้ 0 เสมอ)" name="month" type="number" min="0" max="12" required defaultValue="0" />
      </>}
      {form.type === 'title' && <Field label="ชื่อชุดข้อมูล" name="title" required maxLength={200} defaultValue={dataset.title} />}
      {form.type === 'processing' && <ProcessingFields provinces={provinces} />}
      {form.type === 'geotiff_upload' && <>
        <p>Local/Test เท่านั้น ผลตรวจผ่านยังไม่ใช่ผลวิเคราะห์หรือการเปิดใช้งาน ไม่มีการ Publish หรือเปลี่ยน Cache</p>
        <Field label="ไฟล์ GeoTIFF" name="file" type="file" accept=".tif,.tiff,image/tiff" required />
        <Field label="CRS GeoTIFF"><select name="crs"><option value="EPSG:32647">EPSG:32647</option><option value="EPSG:32648">EPSG:32648</option><option value="EPSG:4326">EPSG:4326</option></select></Field>
        <Field label="แหล่งที่มาของข้อมูล" name="source_label" required maxLength={255} />
        <Field label="วันที่ข้อมูลดาวเทียม" name="acquisition_date" type="date" required min={`${dataset.data_year}-01-01`} max={`${dataset.data_year}-12-31`} />
        <Field label="Scientific Profile"><select name="profile">{dataset.purpose === 'ndvi'
          ? <><option value="ndvi_bands">คำนวณ NDVI จากแบนด์ B4 และ B8</option><option value="ndvi_ready">NDVI สำเร็จรูป / unitless</option></>
          : <><option value="lst_st_b10">คำนวณ LST จากแบนด์ ST_B10 (Landsat C2 L2)</option><option value="lst_celsius_ready">LST สำเร็จรูป / Celsius</option><option value="lst_kelvin_ready">LST สำเร็จรูป / Kelvin → รายงาน Celsius</option></>}</select></Field>
        <p>แบบคำนวณจากแบนด์: ต้องมีชื่อแบนด์ B4, B8 หรือ ST_B10 ในไฟล์และระบุ NoData ระบบคำนวณเฉพาะพิกเซลในขอบเขตจังหวัดของชุดข้อมูล ผลนี้ใช้ดูอย่างเดียว ยังไม่เปิดใช้เป็นข้อมูลของ Dashboard</p>
        <p>แบบสำเร็จรูป: รองรับแบนด์เดียว Float32/64, Scale 1, Offset 0 และ NoData ที่ระบุชัดเจน ต้องมี Tag GIS_PROFILE ตรงกับ Profile ที่เลือก พร้อมชื่อแบนด์ NDVI/LST และหน่วยในไฟล์</p>
      </>}
      {form.type === 'upload' && <>
        <p>อัปโหลดเป็นฉบับใหม่ของ {dataset.province} ปี {dataset.data_year} (ค.ศ.) ไฟล์ต้นฉบับแก้ไขหรือเขียนทับไม่ได้ ไม่เปิดใช้อัตโนมัติ</p>
        <Field label="ไฟล์ LDD Shapefile ZIP" name="file" type="file" accept=".zip,application/zip" required />
        <Field label="แหล่งที่มาของข้อมูล" name="source_label" required maxLength={255} />
        <Field label="CRS ที่คาดว่าใช้ในไฟล์"><select name="crs"><option value="EPSG:32647">UTM 47N / WGS84 (EPSG:32647)</option><option value="EPSG:32648">UTM 48N / WGS84 (EPSG:32648)</option><option value="EPSG:4326">WGS84 (EPSG:4326)</option></select></Field>
        <Field label="Encoding ภาษาไทย"><select name="encoding"><option value="auto">อ่านจาก .cpg (ต้องมี)</option><option value="utf-8">UTF-8</option><option value="cp874">Windows-874</option><option value="tis-620">TIS-620</option></select></Field>
        <p>ต้องมี .shp .shx .dbf .prj และ Attributes LUL1_CODE, LU_CODE, Shape_Area ปีข้อมูลอ้างอิงจาก Dataset ไม่ได้เดาจากชื่อไฟล์</p>
      </>}
      {form.type === 'edition' && <><p>ยังไม่มี API สำหรับเลือก Fixture อัตโนมัติ ให้วาง Manifest ที่ลงทะเบียนไว้เท่านั้น Backend จะตรวจสอบอีกครั้ง ไม่มีการอัปโหลดไฟล์จริง</p>
        <ManifestField value={form.edition ? JSON.stringify(form.edition.manifest, null, 2) : ''} /></>}
      {form.type === 'grant' && <Field label="UUID ผู้ใช้ Local" name="user_id" required maxLength={36} />}
      {form.type === 'withdraw' && <Field label="ฉบับแทนที่ (เฉพาะเมื่อถอนฉบับที่ใช้งาน)"><select name="replacement" disabled={dataset.active_edition_id !== form.edition.id}>
        <option value="">ไม่ใช้ฉบับใดแทน</option>{form.replacements.map(e => <option key={e.id} value={e.id}>{e.id}</option>)}
      </select></Field>}
      {['reason', 'withdraw', 'grant'].includes(form.type) && <Field label="เหตุผล"><textarea name="reason" required maxLength={500} rows={3} /></Field>}
      <ErrorNote error={error} /><div className="gis-actions"><button type="submit">ตรวจทานคำสั่ง</button><button type="button" onClick={close}>ยกเลิก</button></div>
    </form>
  </Modal>;
}

function LddAuditDetails({ audit }) {
  if (!audit || typeof audit !== 'object') return null;
  const outcomes = audit.feature_outcomes || {};
  const boundary = audit.boundary || {};
  const mapping = audit.field_mapping || {};
  const roles = { main_code: 'รหัสหลัก', lu_code: 'รหัสการใช้ที่ดิน', declared_area: 'พื้นที่ในไฟล์' };
  const unknown = Array.isArray(audit.unknown_samples) ? audit.unknown_samples.slice(0, 10) : [];
  const repairs = Array.isArray(audit.repairs) ? audit.repairs.slice(0, 20) : [];
  return <div className="gis-report-audit">
    <p>แปลงที่ผ่าน {Number(outcomes.accepted) || 0} · ผ่านพร้อมข้อสังเกต {Number(outcomes.accepted_with_warnings) || 0} · ต้องตรวจสอบ {Number(outcomes.review_required) || 0} · ไม่ผ่าน {Number(outcomes.rejected) || 0}</p>
    {audit.outcome === 'review_required' && <p role="note">ฉบับนี้ต้องตรวจสอบก่อนใช้ ระบบยังไม่มีขั้นอนุมัติ จึงยังนำเข้าหรือเปิดใช้ไม่ได้ ให้แก้ไฟล์แล้วอัปโหลดใหม่</p>}
    <details><summary>รายละเอียดการตรวจ</summary>
      <p>นโยบาย: {String(audit.policy_version || '—').slice(0, 40)} · Field Profile: {String(audit.field_profile || 'ยังไม่จับคู่').slice(0, 40)} · หน่วยพื้นที่ในไฟล์: {audit.declared_area_units === 'm2' ? 'ตารางเมตร' : 'ยืนยันไม่ได้'}</p>
      {Object.keys(roles).filter(key => typeof mapping[key] === 'string').map(key => <p key={key}>{roles[key]}: {mapping[key].slice(0, 40)}</p>)}
      <p>เกินเขตจังหวัด: เล็กน้อย {Number(boundary.minor) || 0} · ต้องตรวจสอบ {Number(boundary.review) || 0} · ไม่รับ {Number(boundary.fatal) || 0} แปลง · พื้นที่นอกเขต {Number(boundary.outside_area_m2) || 0} ตร.ม. (เส้นเขตเป็นค่าประมาณ)</p>
      {unknown.length > 0 && <><h5>รหัสที่ไม่รู้จัก (แสดงไม่เกิน 10 รายการ)</h5>
        <ul>{unknown.map((u, i) => <li key={i}>{String(u.value ?? '').slice(0, 40)} · รหัสหลัก {String(u.main ?? '').slice(0, 40)} · {String(u.reason ?? '').slice(0, 60)} · {Number(u.count) || 0} แปลง · {Number(u.area_m2) || 0} ตร.ม.</li>)}</ul></>}
      {repairs.length > 0 && <><h5>แปลงที่ซ่อมรูปทรง (ทั้งหมด {Number(audit.repairs_total) || repairs.length} แปลง แสดงไม่เกิน 20)</h5>
        <ul>{repairs.map((r, i) => <li key={i}>แปลงที่ {Number(r.feature) || 0} · {String(r.reason ?? '').slice(0, 40)} · {Number(r.area_before_m2) || 0} → {Number(r.area_after_m2) || 0} ตร.ม. · {String(r.type_before ?? '').slice(0, 40)} → {String(r.type_after ?? '').slice(0, 40)}</li>)}</ul></>}
    </details>
  </div>;
}

function NativeReport({ report }) {
  if (!report) return null;
  if (report.mode === 'offline_synthetic') return <ProcessingReport report={report} />;
  if (report.mode === 'gee_dashboard') return <DashboardProcessingReport report={report} />;
  if (report.provider_build === 'geotiff-local-v1') return <GeoTiffReport report={report} />;
  // Render a closed projection. Never dump raw responses, tokens or diagnostics.
  const stats = ['feature_count','total_area_m2','unknown_area_m2','area_U_m2','area_A_m2','unknown_code_count','composite_feature_count','geometry_error_count','valid_pixels','mean','min','max'];
  const errors = { UNKNOWN_CODE_REVIEW_REQUIRED: 'พบรหัสการใช้ที่ดินที่ยังไม่รองรับ ต้องตรวจสอบก่อนใช้งาน',
    MISSING_COMPONENT_DBF: 'ขาดไฟล์ .dbf', MISSING_COMPONENT_SHP: 'ขาดไฟล์ .shp', MISSING_COMPONENT_SHX: 'ขาดไฟล์ .shx', MISSING_COMPONENT_PRJ: 'ขาดไฟล์ .prj',
    CRS_MISMATCH: 'CRS ในไฟล์ไม่ตรงกับที่เลือก', OUTSIDE_PROVINCE: 'รูปพื้นที่อยู่นอกจังหวัดที่เลือก', ENCODING_INVALID: 'อ่านตัวอักษรตาม Encoding ไม่ได้',
    ENCODING_UNSPECIFIED: 'ไม่พบ Encoding กรุณาระบุหรือเพิ่มไฟล์ .cpg', GEOMETRY_INVALID: 'รูปพื้นที่ไม่สมบูรณ์',
    SHAPEFILE_DATASET_COUNT: 'ไม่พบชั้นการใช้ที่ดิน (LU_*.shp) เพียงชั้นเดียวใน ZIP', UNSUPPORTED_ZIP_MEMBER: 'ZIP มีไฟล์ประเภทที่ไม่อนุญาต (โปรแกรม สคริปต์ ไฟล์ VRT หรือ ZIP ซ้อน)',
    SOURCE_HASH_MISMATCH: 'SHA256 ของไฟล์ไม่ตรงกับต้นฉบับ', LDD_SHA256_MISMATCH: 'SHA256 ของไฟล์ไม่ตรงกับต้นฉบับ',
    NATIVE_MEMORY_LIMIT: 'ไฟล์นี้ใช้หน่วยความจำเกินขีดจำกัดการประมวลผล ยังไม่ได้รับการยืนยันว่าข้อมูล GIS ผิด',
    NATIVE_TIMEOUT: 'ประมวลผลนานเกินเวลาที่กำหนด ยังไม่ได้รับการยืนยันว่าข้อมูล GIS ผิด',
    ATTRIBUTES_MISSING: 'ขาด Attributes ที่จำเป็นตาม Field Profile ที่อนุมัติ',
    FIELD_NAME_AMBIGUOUS: 'มีชื่อ Field ซ้ำกันเมื่อไม่สนตัวพิมพ์ ระบบไม่เลือกให้เอง',
    FIELD_MAPPING_AMBIGUOUS: 'ไฟล์ตรงกับ Field Profile มากกว่าหนึ่งแบบ ระบบไม่เลือกให้เอง',
    BOUNDARY_OUTSIDE_REVIEW_REQUIRED: 'บางแปลงมีส่วนเกินเขตจังหวัดมากกว่าเกณฑ์ ต้องตรวจสอบ',
    BOUNDARY_OUTSIDE_AREA_REVIEW_REQUIRED: 'พื้นที่ส่วนที่เกินเขตจังหวัดรวมเกินเกณฑ์ ต้องตรวจสอบ',
    AREA_DECLARED_MISMATCH_REVIEW_REQUIRED: 'พื้นที่ที่บันทึกในไฟล์ต่างจากพื้นที่ที่คำนวณจากรูปแปลงเกินเกณฑ์ ต้องตรวจสอบ',
    GEOMETRY_REPAIR_LIMIT_REVIEW_REQUIRED: 'จำนวนแปลงที่ต้องซ่อมรูปร่างเกินเกณฑ์ ต้องตรวจสอบ',
    GEOMETRY_REPAIR_AREA_CHANGED: 'ซ่อมรูปร่างแล้วพื้นที่เปลี่ยนเกินเกณฑ์ จึงไม่รับ',
    GEOMETRY_REPAIR_TYPE_CHANGED: 'ซ่อมรูปร่างแล้วไม่ใช่ Polygon จึงไม่รับ',
    GEOMETRY_TYPE: 'พบแปลงที่ไม่มีรูปร่างหรือไม่ใช่ Polygon', GEOMETRY_EMPTY: 'พบแปลงที่รูปร่างว่าง' };
  const notes = { GEOMETRY_REPAIRED: 'ซ่อมรูปร่างที่ผิดรูปเล็กน้อยแล้ว (เก็บรูปต้นฉบับไว้)',
    BOUNDARY_OUTSIDE_MINOR: 'แปลงเกินเขตจังหวัดเล็กน้อยภายในเกณฑ์ (เส้นเขตเป็นค่าประมาณ)',
    AREA_DECLARED_MINOR_DIFF: 'พื้นที่ที่บันทึกต่างจากที่คำนวณเล็กน้อย ใช้พื้นที่จากรูปแปลง',
    DECLARED_AREA_UNITS_UNVERIFIED: 'ยืนยันหน่วยของพื้นที่ที่บันทึกไม่ได้ จึงไม่นำมาเทียบ',
    NUMERIC_MAIN_CODE_NORMALISED: 'แปลงรหัสหลักแบบตัวเลขตาม Legend ที่อนุมัติ',
    COMPOSITE_PLUS_SEPARATOR: 'รหัสผสมที่คั่นด้วย + อ่านเป็นรหัสผสมแบบ / เพราะทุกส่วนเป็นรหัสทางการของหมวดเดียวกัน' };
  const reviewCodes = ['UNKNOWN_CODE_REVIEW_REQUIRED', 'BOUNDARY_OUTSIDE_REVIEW_REQUIRED', 'BOUNDARY_OUTSIDE_AREA_REVIEW_REQUIRED',
    'AREA_DECLARED_MISMATCH_REVIEW_REQUIRED', 'GEOMETRY_REPAIR_LIMIT_REVIEW_REQUIRED'];
  const errorCodes = (Array.isArray(report.errors) ? report.errors : []).map(e => String(e?.code || ''));
  const outcome = report.provider_build !== 'ldd-local-v1' || typeof report.valid !== 'boolean' ? null
    : errorCodes.some(c => !reviewCodes.includes(c)) ? 'ไม่ผ่าน (Rejected)'
    : errorCodes.length ? 'ต้องตรวจสอบก่อนใช้ (Review Required)'
    : (Array.isArray(report.warnings) ? report.warnings : []).some(w => notes[w?.code]) ? 'ผ่านพร้อมข้อสังเกต (Accepted with Warnings)'
    : 'ผ่าน (Accepted)';
  return <div className="gis-report"><h4>รายงานการตรวจ</h4>
    <p>ผล: {report.valid === true ? 'ผ่าน' : report.valid === false ? 'ไม่ผ่าน' : 'ยังไม่ระบุ'} · {report.upload_id ? `ไฟล์อัปโหลด: ${String(report.upload_id).slice(0, 36)}` : `Fixture: ${String(report.fixture_id || '—').slice(0, 60)}`}</p>
    {outcome && <p>จำแนกผล: {outcome}</p>}
    <LddAuditDetails audit={report.audit} />
    {report.error_code && <p>รหัสผลตรวจ: {errors[report.error_code] || String(report.error_code).slice(0, 60)}</p>}
    <ul>{(Array.isArray(report.checks) ? report.checks : []).slice(0, 12).filter(x => typeof x === 'string').map(x => <li key={x}>{x.slice(0, 60)}</li>)}</ul>
    {(Array.isArray(report.errors) ? report.errors : []).slice(0, 20).map((e, i) => <p key={i}>ปัญหา: {errors[e.code] || String(e.code || '').slice(0, 60)} ({Number(e.count) || 0})</p>)}
    {report.upload_id && <p>จังหวัด: {String(report.province || '').slice(0, 120)} · ปี {report.data_year} · {String(report.crs || '').slice(0, 20)} · Encoding {String(report.encoding || '').slice(0, 20)}</p>}
    {stats.filter(key => typeof report.statistics?.[key] === 'number').map(key => <p key={key}>{key}: {report.statistics[key]}</p>)}
    {(Array.isArray(report.warnings) ? report.warnings : []).slice(0, 16).map((w, i) => <p key={i}>ข้อสังเกต: {notes[w.code] || String(w.code || '').slice(0, 60)} ({Number(w.count) || 0})</p>)}
    {Array.isArray(report.values) && <details><summary>ค่าคำนวณจากข้อมูลจำลอง</summary><pre>{JSON.stringify(report.values.slice(0, 8).map(row => Array.isArray(row) ? row.slice(0, 16).map(v => typeof v === 'number' ? v : null) : null), null, 2)}</pre></details>}
  </div>;
}

function GeoTiffReport({ report }) {
  const m = report.metadata || {};
  const messages = { GEOTIFF_TIFF_STRUCTURE: 'อ่านโครงสร้าง TIFF ไม่ได้', GEOTIFF_CRS_MISMATCH: 'CRS ไม่ตรงกับที่ระบุ',
    GEOTIFF_SCALE_OFFSET_UNSUPPORTED: 'Scale/Offset ไม่ตรง หยุดเพื่อป้องกัน Scale ซ้ำ',
    GEOTIFF_SCIENTIFIC_RANGE: 'ค่าพิกเซลไม่อยู่ในช่วงของ Profile', GEOTIFF_UNITS_MISMATCH: 'หน่วยในไฟล์ไม่ตรงกับ Profile',
    GEOTIFF_PROFILE_MISMATCH: 'Tag GIS_PROFILE ไม่ตรงกับ Profile ที่เลือก', GEOTIFF_NO_VALID_PIXELS: 'ไม่มีพิกเซลที่ใช้ตรวจได้',
    GEOTIFF_READ_ERROR: 'ไฟล์ TIFF เสียหายหรืออ่านค่าพิกเซลไม่ได้', GEOTIFF_TIFF_SIGNATURE: 'ส่วนหัวไม่ใช่ TIFF ที่รองรับ',
    GEOTIFF_BANDS_MISMATCH: 'จำนวนหรือชื่อแบนด์ในไฟล์ไม่ตรงกับ Profile ที่เลือก',
    GEOTIFF_DTYPE_UNSUPPORTED: 'ชนิดข้อมูลของแบนด์ไม่ตรงกับ Profile ที่เลือก',
    GEOTIFF_OUTSIDE_PROVINCE: 'ไฟล์ไม่ครอบคลุมพื้นที่ของจังหวัดที่เลือก จึงไม่คำนวณ', GEOTIFF_PROVINCE_UNKNOWN: 'ไม่พบขอบเขตของจังหวัดนี้',
    GEOTIFF_RESOLUTION_INVALID: 'ขนาดพิกเซลหรือทิศทาง Raster ไม่อยู่ในขอบเขตที่รองรับ',
    GEOTIFF_DIMENSIONS_LIMIT: 'จำนวนพิกเซลหรือความกว้าง/สูงเกินขีดจำกัด Local',
    GEOTIFF_BOUNDS_INVALID: 'พิกัด Raster อยู่นอกขอบเขตของ CRS',
    GEOTIFF_NODATA_INVALID: 'ต้องระบุ NoData เป็นค่าจำกัดที่อยู่นอกช่วงค่าจริงของ Profile',
    GEOTIFF_NONFINITE_PIXELS: 'พบ NaN หรือ Infinity ในพิกเซล', GEOTIFF_MASK_UNSUPPORTED: 'รองรับ Mask แบบ NoData เท่านั้น',
    GEOTIFF_OVERVIEWS_UNSUPPORTED: 'ยังไม่รองรับ TIFF ที่มี Overviews',
    GEOTIFF_EXTERNAL_REFERENCE: 'ไฟล์มีการอ้างอิงข้อมูลภายนอกที่ไม่อนุญาต',
    GEOTIFF_METADATA_LIMIT: 'Metadata ของไฟล์เกินขีดจำกัด', GEOTIFF_SIZE_MISMATCH: 'ขนาดไฟล์ไม่ตรงกับต้นฉบับ',
    NATIVE_TIMEOUT: 'ใช้เวลาตรวจเกินกำหนด', NATIVE_MEMORY_LIMIT: 'ใช้หน่วยความจำเกินขีดจำกัด' };
  return <div className="gis-report"><h4>รายงาน GeoTIFF — Local/Test</h4>
    <p>ผล Validation: {report.valid ? 'ผ่าน' : 'ไม่ผ่าน'} · ไม่เปิดใช้ ไม่ Publish และไม่เปลี่ยน Cache</p>
    {report.error_code && <p role="alert">{messages[report.error_code] || String(report.error_code).slice(0, 60)}</p>}
    <p>Profile: {m.profile || 'ยังอ่านไม่ได้'} · CRS: {m.crs || 'ยังอ่านไม่ได้'}</p>
    <p>Bands: {(m.bands || []).join(', ')} · Resolution: {(m.resolution || []).join(' × ')} · Data Type: {m.dtype || '—'}</p>
    <p>NoData: {Number.isFinite(m.nodata) ? m.nodata : 'ยังไม่ระบุ'} · Units: {m.units || '—'} · Output Units: {m.output_units || '—'}</p>
    <p>Scale: {(m.scales || []).join(', ')} · Offset: {(m.offsets || []).join(', ')}</p>
    {report.coverage && <p>พื้นที่ที่คำนวณ: {report.province} (ขอบเขตโดยประมาณ) · ครอบคลุมจังหวัด {(report.coverage.fraction_of_province * 100).toFixed(1)}% · ใช้พิกเซลของไฟล์ {(report.coverage.fraction_of_file * 100).toFixed(1)}%</p>}
    {(report.warnings || []).some(w => w.code === 'GEOTIFF_PARTIAL_PROVINCE_COVERAGE') && <p role="note">ไฟล์ครอบคลุมจังหวัดเพียงบางส่วน ค่านี้จึงแทนเฉพาะส่วนที่ครอบคลุม</p>}
    {['width','height','band_count','valid_pixels','nodata_pixels','nonfinite_pixels','outside_area_pixels','mean','min','max'].filter(k => k !== 'outside_area_pixels' || report.coverage).map(k => <p key={k}>{k}: {Number.isFinite(report.statistics?.[k]) ? report.statistics[k] : 'ไม่มีข้อมูล'}</p>)}
    <details><summary>ต้นฉบับและผลตรวจ</summary><p>SHA256: {report.artifact_sha256}</p><p>File ID: {report.upload_id}</p>
      <p>{(report.checks || []).join(', ')}</p><p>ผ่านการตรวจไฟล์เท่านั้น ยังไม่ได้ยืนยันความถูกต้องของข้อมูลดาวเทียมหรือขอบเขตจังหวัด</p></details>
  </div>;
}

function JobDetail({ id, version, onRetry, context }) {
  const heading = useRef(null);
  useEffect(() => { heading.current?.focus({ preventScroll: true }); heading.current?.scrollIntoView?.({ block: 'start' }); }, [id]);
  const [job, setJob] = useState(null);
  const [error, setError] = useState(null);
  const [related, setRelated] = useState(null);
  const attempts = usePage(`/jobs/${id}/attempts`, {}, version);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    const abort = new AbortController();
    setError(null); setJob(null); setRelated(null);
    gisRequest(`/jobs/${id}`, { signal: abort.signal }).then(async j => {
      if (abort.signal.aborted) return;
      setJob(j);
      try {
        const edition = await gisRequest(`/editions/${j.edition_id}`, { signal: abort.signal });
        const dataset = context?.id === edition.dataset_id ? context
          : await gisRequest(`/datasets/${edition.dataset_id}`, { signal: abort.signal });
        if (!abort.signal.aborted) setRelated({ edition, dataset });
      } catch { /* The report remains available if its context cannot load. */ }
    })
      .catch(err => { if (!abort.signal.aborted) setError(err); });
    return () => abort.abort();
  }, [id, version, tick]);
  return <section className="gis-card gis-job-detail" aria-label="รายละเอียดงานและรายงาน"><h3 ref={heading} tabIndex="-1">รายละเอียดงานและรายงาน</h3><ErrorNote error={error} />
    <p className="gis-context">ชุดข้อมูล: {related?.dataset?.title || context?.title || 'กำลังอ่านชุดข้อมูลที่เกี่ยวข้อง'}</p>
    <button onClick={() => { setTick(n => n + 1); attempts.refresh(); }}>รีเฟรชรายละเอียดงาน</button>
    {!job && !error && <p role="status">กำลังโหลดงาน…</p>}
    {job && <><Status value={job.state} /><p>ตรวจสอบฉบับข้อมูล{related?.edition?.upload ? 'ที่อัปโหลด' : ''} · จำนวนครั้ง: {job.attempt_count} · ความคืบหน้า: {job.progress}%</p>
      <progress value={job.progress || 0} max="100" aria-label="ความคืบหน้าการตรวจสอบ" />
      <details className="gis-technical"><summary>ข้อมูลทางเทคนิคของงานและฉบับ</summary><p>Job ID: {id}</p><p>Edition ID: {job.edition_id}</p><p>Revision: {job.input_revision}</p></details>
      {job.error_code && <p>{errorLabels[job.error_code] || 'ข้อผิดพลาดภายใน'}</p>}
      {job.state === 'failed' && !job.parent_job_id && ['transient', 'attempts_exhausted'].includes(job.error_code)
        && <button onClick={() => onRetry(job)}>ขอลองใหม่</button>}
      <NativeReport report={job.result?.report} /></>}
    <h4>ประวัติการตรวจสอบ (หน้านี้)</h4><PageState page={attempts} empty="ยังไม่มีรอบการตรวจสอบ งานที่รออยู่จะเริ่มเมื่อ Worker พร้อม" />
    {attempts.data.map(a => <article key={a.id}><p>ครั้งที่ {a.attempt_no} · <Status value={a.state} /> · {a.progress}% · {errorLabels[a.error_code] || ''}</p><NativeReport report={a.validation_report} /></article>)}
    <PageControls page={attempts} />
  </section>;
}

function EditionHistory({ id, version }) {
  const page = usePage(`/editions/${id}/history`, {}, version);
  return <section className="gis-card"><h3>ประวัติฉบับที่เลือก</h3><details className="gis-technical"><summary>รหัสฉบับข้อมูล</summary>{id}</details><PageState page={page} />
    <ul>{page.data.map(row => <li key={row.id}>{row.created_at} · {row.operation} · {row.reason || '—'}</li>)}</ul><PageControls page={page} /></section>;
}

function DatasetDetail({ id, version, access, form, prepare, pending, onLoad, onJobs, onClose }) {
  const [dataset, setDataset] = useState(null);
  const [error, setError] = useState(null);
  const [history, setHistory] = useState(null);
  const heading = useRef(null);
  const page = usePage(`/datasets/${id}/editions`, {}, version);
  useEffect(() => {
    const abort = new AbortController(); setDataset(null); setError(null);
    gisRequest(`/datasets/${id}`, { signal: abort.signal }).then(d => { if (!abort.signal.aborted) { setDataset(d); onLoad?.(d); } })
      .catch(err => { if (!abort.signal.aborted) setError(err); });
    return () => abort.abort();
  }, [id, version]);
  useEffect(() => {
    heading.current?.focus({ preventScroll: true });
    if (window.matchMedia?.('(max-width: 960px)').matches) heading.current?.scrollIntoView?.({ block: 'start' });
  }, [id]);
  const caps = access.me.capabilities;
  const canActivate = access.me.activation_enabled === true;
  const path = `/datasets/${id}`;
  return <section className="gis-card gis-dataset-detail" aria-label="ชุดข้อมูลที่เลือก"><div className="gis-section-heading"><h2 ref={heading} tabIndex="-1">รายละเอียดชุดข้อมูล</h2><button onClick={onClose}>กลับรายการชุดข้อมูล</button></div><ErrorNote error={error} />
    {!dataset && !error && <p role="status">กำลังโหลด Dataset…</p>}
    {dataset && <><h3 className="gis-dataset-title">{dataset.title}</h3><p>{dataset.province} · ปี {dataset.data_year} {dataset.month ? `/ เดือน ${dataset.month}` : '· รายปี'} · {labels[dataset.purpose]}</p>
      <p><span className={`gis-status${dataset.active_edition_id ? ' gis-status--active' : ''}`}>{dataset.active_edition_id ? 'มีฉบับที่ใช้งานอยู่' : 'ยังไม่เปิดใช้ข้อมูล'}</span></p>
      <ol className="gis-workflow" aria-label="ขั้นตอนจัดการชุดข้อมูล"><li>สร้างชุดข้อมูล</li><li>อัปโหลดไฟล์</li><li>ส่งตรวจสอบ</li><li>ดูรายงาน</li></ol>
      <p className="gis-help">เริ่มจากอัปโหลดไฟล์เป็นฉบับใหม่ แล้วส่งตรวจสอบแต่ละฉบับ ผลตรวจผ่านยังไม่เท่ากับการเปิดใช้งาน</p>
      <div className="gis-actions">
        {access.me.ldd_upload_enabled && dataset.kind === 'ldd_shapefile' && caps.includes('edit_draft') && <button className="gis-primary" disabled={pending} onClick={() => form({ type: 'upload', title: 'อัปโหลด LDD ZIP เป็นฉบับใหม่', path: `${path}/ldd-uploads`, dataset })}>อัปโหลด LDD ZIP</button>}
        {access.me.geotiff_upload_enabled && dataset.kind === 'geotiff' && caps.includes('edit_draft') && <button className="gis-primary" disabled={pending} onClick={() => form({ type: 'geotiff_upload', title: 'อัปโหลด GeoTIFF เป็นฉบับใหม่ — Local/Test', path: `${path}/geotiff-uploads`, dataset })}>อัปโหลด GeoTIFF</button>}
        {caps.includes('edit_draft') && <button disabled={pending} onClick={() => form({ type: 'title', title: 'แก้ชื่อ Dataset', path, method: 'PATCH', dataset })}>แก้ชื่อ</button>}
        <button onClick={() => onJobs(null)}>งานและรายงานของชุดนี้</button>
      </div>
      <details className="gis-technical"><summary>ตัวเลือกเพิ่มเติมและข้อมูลทางเทคนิค</summary><p>Dataset ID: {dataset.id}</p><p>Revision: {dataset.revision}</p><p>ฉบับที่ใช้งาน: {dataset.active_edition_id || 'ยังไม่มี'}</p>
        <p>การสร้างฉบับด้วย Manifest ใช้สำหรับข้อมูลจำลองที่ลงทะเบียนไว้เท่านั้น</p>
        {caps.includes('edit_draft') && <button disabled={pending} onClick={() => form({ type: 'edition', title: 'สร้างฉบับข้อมูลจำลอง', path: `${path}/editions`, dataset })}>สร้าง Edition</button>}
      </details>
      {!canActivate && <p className="gis-help">การเปิดใช้ / ถอน / ย้อนกลับฉบับยังปิดอยู่ใน Local Sandbox ข้อมูลอัปโหลดจะไม่แทนที่ข้อมูลวิเคราะห์เดิม</p>}
      {access.me.admin && !canActivate && <p>การเปิดใช้ / ถอน / ย้อนกลับฉบับถูกปิดไว้ใน Sandbox Gate จึงยังไม่มีคำสั่งเหล่านี้ให้ใช้งาน</p>}
      <h3>ฉบับข้อมูล (หน้านี้)</h3><p>จำนวนฉบับในหน้านี้: {page.loading || page.error ? '—' : page.data.length}</p><PageState page={page} empty="ยังไม่มีฉบับข้อมูล อัปโหลดไฟล์เพื่อเริ่มขั้นตอนตรวจสอบ" />
      {page.data.map((e, index) => <article key={e.id} data-edition-id={e.id} className="gis-edition"><div className="gis-section-heading"><h4>ฉบับข้อมูล {index + 1} ในหน้านี้</h4>{dataset.active_edition_id === e.id && <span className="gis-status gis-status--active">ใช้งานอยู่</span>}</div>
        <Status value={e.state} /><p>{e.manifest?.profile || labels[dataset.purpose]}{e.upload ? ' · ไฟล์อัปโหลด' : ' · ข้อมูลจำลอง'}</p>
        <p className="gis-next-step">{e.state === 'validated' ? 'ตรวจผ่านแล้ว — ดูรายงานก่อนดำเนินการต่อ ฉบับนี้ไม่ได้เปิดใช้อัตโนมัติ' : e.state === 'validating' ? 'กำลังตรวจสอบ — ติดตามความคืบหน้าในงานและรายงาน' : e.state === 'withdrawn' ? 'ฉบับนี้ถูกถอนแล้ว หากต้องการใช้ต่อให้สร้างฉบับใหม่' : 'ขั้นตอนถัดไป: ส่งตรวจสอบ หรือเปิดงานและรายงานเพื่อดูผลตรวจล่าสุด'}</p>
        <details className="gis-technical"><summary>ข้อมูลทางเทคนิคของฉบับ</summary><p>Edition ID: {e.id}</p><p>Revision: {e.input_revision} · Metadata V{e.manifest?.schema_version}</p><p>Fixture: {e.manifest?.fixture_id || '—'}</p></details>
        {e.manifest?.schema_version === 3 && <p>Offline Synthetic Candidate — ใช้ส่วนประมวลผล NDVI/LST เพื่อดูรายงาน ไม่ใช่ผล GEE จริง</p>}
        {e.manifest?.schema_version === 4 && <p>GeoTIFF Local/Test — ผลตรวจผ่านไม่ได้เปิดใช้งานหรือแทนที่ Cache</p>}
        {e.upload && <details><summary>ข้อมูลไฟล์ต้นฉบับ</summary><p>File ID: {e.upload.upload_id}</p><p>SHA256: {e.upload.sha256}</p><p>{e.upload.byte_size} bytes · {e.upload.crs} · Encoding {e.upload.encoding} · อัปโหลด {e.upload.created_at}</p>{e.upload.source_label && <p>แหล่งที่มา: {e.upload.source_label}</p>}{e.upload.acquisition_date && <p>วันที่ข้อมูล: {e.upload.acquisition_date} (ตามที่ผู้ส่งระบุ ระบบไม่ได้ตรวจสอบ)</p>}</details>}
        {e.manifest?.schema_version === 1 && !e.upload && <p>ฉบับ V1 แสดงเพื่อความเข้ากันได้ Worker Native ปัจจุบันรองรับเฉพาะ V2 จึงยังไม่เปิดส่งตรวจ V1 จากหน้านี้</p>}
        <div className="gis-actions">
          <button onClick={() => onJobs({ id: e.id, label: `ฉบับข้อมูล ${index + 1} ในหน้านี้` })}>งานและรายงานฉบับนี้</button>
          <button onClick={() => setHistory(history === e.id ? null : e.id)}>{history === e.id ? 'ปิดประวัติ' : 'ดูประวัติ'}</button>
          {caps.includes('edit_draft') && e.state === 'draft' && !e.upload && ![3,4].includes(e.manifest?.schema_version) && <button disabled={pending} onClick={() => form({ type: 'edition', title: 'แก้ฉบับร่าง', path: `/editions/${e.id}`, method: 'PATCH', dataset, edition: e })}>แก้ Manifest</button>}
          {caps.includes('clone_edition') && !e.upload && ![3,4].includes(e.manifest?.schema_version) && <button disabled={pending} onClick={() => prepare({ title: 'สำเนาเป็นฉบับร่างใหม่', path: `/editions/${e.id}/clone`, body: { expected_revision: e.input_revision } })}>สำเนาฉบับ</button>}
          {caps.includes('enqueue_validation') && e.state === 'draft' && (e.manifest?.schema_version === 2 || e.upload) && <button disabled={pending} onClick={() => prepare({ title: e.manifest?.schema_version === 4 ? 'ส่งตรวจสอบ GeoTIFF' : e.upload ? 'ส่งตรวจสอบไฟล์ LDD' : 'ส่งตรวจสอบข้อมูลจำลอง', path: `/editions/${e.id}/validation-jobs`, body: { expected_revision: e.input_revision } })}>ส่งตรวจสอบ</button>}
          {canActivate && e.state === 'validated' && dataset.active_edition_id !== e.id && <>
            {caps.includes('sandbox_activate') && <button disabled={pending} onClick={() => form({ type: 'reason', title: 'เปิดใช้ฉบับใน Synthetic Sandbox', path: `${path}/activation`, body: { edition_id: e.id, expected_revision: dataset.revision, expected_active_edition_id: dataset.active_edition_id } })}>เปิดใช้ฉบับ</button>}
            {caps.includes('sandbox_rollback') && <button disabled={pending} onClick={() => form({ type: 'reason', title: 'ขอย้อนกลับฉบับ (Backend ตรวจประวัติและสิทธิ์)', path: `${path}/rollback`, body: { edition_id: e.id, expected_revision: dataset.revision, expected_active_edition_id: dataset.active_edition_id } })}>ขอย้อนกลับฉบับ</button>}
          </>}
          {canActivate && caps.includes('sandbox_withdraw') && ['draft', 'validated'].includes(e.state) && <button disabled={pending} onClick={() => form({ type: 'withdraw', title: 'ถอนฉบับใน Synthetic Sandbox', path: `/editions/${e.id}/withdrawal`, dataset, edition: e,
            replacements: page.data.filter(r => r.state === 'validated' && r.id !== e.id),
            body: { expected_revision: e.input_revision, expected_dataset_revision: dataset.revision, expected_active_edition_id: dataset.active_edition_id } })}>ถอนฉบับ</button>}
        </div>{access.me.ldd_prepare_enabled && e.upload && e.manifest?.schema_version !== 4 && e.state === 'validated' && <LddPreparedPreview dataset={dataset} edition={e} version={version} pending={pending} onAction={prepare} />}
        {access.me.admin && access.me.ldd_publication_enabled && e.upload && e.manifest?.schema_version !== 4 && e.state === 'validated'
          && <LddPublicationActions dataset={dataset} edition={e} editions={page.data} pending={pending} onAction={prepare} />}
        {access.me.geotiff_prepare_enabled && e.upload && e.manifest?.schema_version === 4 && e.state === 'draft'
          && <GeoTiffPreparedPreview dataset={dataset} edition={e} version={version} pending={pending} onAction={prepare} />}
        {access.me.geotiff_publication_enabled && e.upload && e.manifest?.schema_version===4
          && <GeoTiffPublicationActions dataset={dataset} edition={e} editions={page.data} version={version} pending={pending} admin={access.me.admin} onAction={prepare}/>}
        {history === e.id && <EditionHistory key={history} id={history} version={version} />}</article>)}
      <PageControls page={page} />
    </>}
  </section>;
}

function ProcessingReport({ report }) {
  if (!report) return null;
  if (report.mode !== 'offline_synthetic' || report.synthetic !== true) return <p role="alert">ผลนี้ไม่ตรงกับโหมด Offline ที่อนุญาต</p>;
  const m = report.metadata || {};
  const errors = { PROCESSING_NO_VALID_PIXELS: 'ไม่มีพิกเซลที่ใช้ได้ จึงไม่มี Candidate Result',
    TRANSIENT_SYNTHETIC: 'บริการจำลองขัดข้องชั่วคราว ระบบจะลองใหม่ตามงบ Retry',
    NATIVE_TIMEOUT: 'ประมวลผลเกินเวลาที่อนุญาต', NATIVE_MEMORY_LIMIT: 'ใช้หน่วยความจำเกินขีดจำกัด' };
  return <div className="gis-report"><h4>Candidate / Offline Synthetic</h4>
    <p>ข้อมูลจำลองเท่านั้น ไม่ใช่ผล GEE หรือค่าของจังหวัด/อำเภอจริง ไม่มีการ Publish หรือเปลี่ยน Cache</p>
    <p>ผลประมวลผล: {report.valid ? 'มีผลรอตรวจทาน' : 'ยังไม่มีผลสำเร็จ'}</p>
    {report.error_code && <p>{errors[report.error_code] || String(report.error_code).slice(0, 60)}</p>}
    <p>{String(m.metric || '').toUpperCase()} · {m.province} {m.district || 'ระดับจังหวัด'} · {m.start_date} ถึง {m.end_date} (ไม่รวมวันสุดท้าย)</p>
    <p>Scale {m.scale_m} m · Source Resolution {m.resolution} m · หน่วย {m.units}</p>
    {['valid_pixels', 'mean', 'min', 'max'].map(key => <p key={key}>{key}: {Number.isFinite(report.statistics?.[key]) ? report.statistics[key] : 'ไม่มีข้อมูล'}</p>)}
    <details><summary>แหล่งข้อมูลและรุ่นประมวลผล</summary><p>Fixture: {m.fixture_id}</p><p>SHA256: {report.artifact_sha256}</p>
      <p>Version: {m.processing_version}</p><p>Cloud Mask: {m.cloud_mask}</p>
      <p>Collection ที่ Pipeline เดิมอ้างอิง (ไม่ได้เรียกจริง): {(m.source_collections || []).join(', ')}</p></details>
  </div>;
}

function DashboardProcessingReport({ report }) {
  if (!report) return null;
  if (report.mode !== 'gee_dashboard' || report.synthetic !== false) return <p role="alert">ผลนี้ไม่ตรงกับโหมด Google Earth Engine ที่อนุญาต</p>;
  const m = report.metadata || {};
  const o = report.observation || {};
  const errors = { PROCESSING_NO_VALID_PIXELS: 'ไม่พบภาพดาวเทียมที่ใช้ได้ในช่วงเวลานี้ จึงไม่มีจุดข้อมูลใหม่',
    PROCESSING_RESULT_IMPLAUSIBLE: 'ค่าที่คำนวณได้อยู่นอกช่วงที่เป็นไปได้ จึงไม่บันทึกเป็นผลสำเร็จ',
    NATIVE_PROCESS_FAILED: 'เชื่อมต่อ Google Earth Engine ไม่สำเร็จชั่วคราว ระบบจะลองใหม่ตามงบ Retry',
    NATIVE_TIMEOUT: 'ประมวลผลเกินเวลาที่อนุญาต', WORKER_SHUTDOWN: 'Worker หยุดทำงานระหว่างประมวลผล' };
  const unit = m.metric === 'lst' ? ' °C' : '';
  return <div className="gis-report"><h4>ผลประมวลผล Google Earth Engine</h4>
    <p>{report.valid ? `${o.from_cache ? 'มีจุดข้อมูลนี้ในอนุกรมเวลาของ Dashboard อยู่แล้ว ไม่ได้บันทึกใหม่' : 'บันทึกจุดข้อมูลลงอนุกรมเวลาของ Dashboard แล้ว'} (${report.cache?.table || m.cache_table})` : 'ยังไม่มีผลสำเร็จ'}</p>
    {report.error_code && <p>{errors[report.error_code] || String(report.error_code).slice(0, 60)}</p>}
    <p>{String(m.metric || '').toUpperCase()} · {m.province} {m.district || 'ระดับจังหวัด'} · {m.month ? `เดือน ${m.month}/${m.data_year}` : `รายปี ${m.data_year}`}</p>
    {['mean', 'min', 'max'].map(key => <p key={key}>{key}: {Number.isFinite(report.statistics?.[key]) ? `${report.statistics[key]}${unit}` : 'ไม่มีข้อมูล'}</p>)}
    {report.valid && <p>{o.from_cache ? `มีข้อมูลช่วงนี้อยู่แล้วตั้งแต่ ${o.cached_at || 'ก่อนหน้า'} จึงไม่ได้เรียก GEE ซ้ำ` : 'คำนวณใหม่จาก Google Earth Engine'}{Number.isFinite(o.image_count) ? ` · จำนวนภาพ ${o.image_count}` : ''}</p>}
    <details><summary>แหล่งข้อมูลและรุ่นประมวลผล</summary><p>Version: {m.processing_version}</p><p>Cloud Mask: {m.cloud_mask}</p>
      <p>Collection: {(m.source_collections || []).join(', ')}</p><p>Scale {m.scale_m} m · ขอเมื่อ {m.requested_on}</p></details>
  </div>;
}

function ProcessingDetail({ id, version, retry }) {
  const [tick, setTick] = useState(0);
  const [job, setJob] = useState(null);
  const [error, setError] = useState(null);
  const attempts = usePage(`/processing-jobs/${id}/attempts`, {}, `${version}:${tick}`);
  const history = usePage(`/processing-jobs/${id}/history`, {}, `${version}:${tick}`);
  useEffect(() => {
    const abort = new AbortController(); setError(null);
    gisRequest(`/processing-jobs/${id}`, { signal: abort.signal }).then(value => { if (!abort.signal.aborted) setJob(value); })
      .catch(err => { if (!abort.signal.aborted) setError(err); });
    return () => abort.abort();
  }, [id, version, tick]);
  return <section className="gis-card" aria-label="รายละเอียดงานประมวลผล"><h3>รายละเอียดงานประมวลผล</h3>
    <details className="gis-technical"><summary>รหัสงานประมวลผล</summary>{id}</details>
    <button onClick={() => setTick(n => n + 1)}>รีเฟรชงานประมวลผล</button><ErrorNote error={error} />
    {job && <><p><Status value={job.state} /> · {job.progress}% · ครั้งที่ {job.attempt_count}</p>
      <p>{job.mode === 'gee_dashboard' ? 'Google Earth Engine / ผลสำเร็จบันทึกเป็นจุดข้อมูลของ Dashboard ไม่มีการเปิดใช้ฉบับ GIS' : 'Offline Synthetic / รอตรวจทาน ไม่มีการเปิดใช้ผลอัตโนมัติ'}</p>
      {job.result?.report?.mode === 'gee_dashboard' ? <DashboardProcessingReport report={job.result.report} /> : <ProcessingReport report={job.result?.report} />}
      {job.state === 'failed' && ['transient','attempts_exhausted'].includes(job.error_code) && !job.parent_job_id
        && <button onClick={() => retry(job)}>ขอลองประมวลผลใหม่</button>}</>}
    <h4>ประวัติการประมวลผล</h4><PageState page={attempts} />
    {attempts.data.map(a => <article key={a.id}><p>ครั้งที่ {a.attempt_no} · <Status value={a.state} /></p><ProcessingReport report={a.validation_report} /></article>)}
    <PageControls page={attempts} />
    <details><summary>ประวัติคำสั่งและ Audit</summary><PageState page={history} />
      <ul>{history.data.map(h => <li key={h.id}>{h.operation} · {h.created_at}</li>)}</ul><PageControls page={history} /></details>
  </section>;
}

function ProcessingPanel({ version, form, pending, provinces }) {
  const jobs = usePage('/processing-jobs', {}, version);
  const [selected, setSelected] = useState(null);
  return <section className="gis-card"><h2>ประมวลผล NDVI/LST</h2>
    <p>เลือกแหล่งข้อมูลได้เมื่อ Backend พร้อม: Offline Synthetic ใช้พิกเซลทดสอบ 4 จุด ไม่ใช่ค่าของพื้นที่จริง ส่วน Google Earth Engine ใช้ภาพดาวเทียมจริงผ่านวิธีเดียวกับ Dashboard</p>
    <button disabled={pending || provinces.length === 0} onClick={() => form({ type: 'processing', title: 'สร้างงานประมวลผล NDVI/LST', path: '/processing-jobs' })}>สร้างงานประมวลผล NDVI/LST</button>
    <p>Worker ทำงานต่อเมื่อปิดหน้าเว็บ ใช้ปุ่มรีเฟรชเพื่อติดตามสถานะ</p><PageState page={jobs} />
    <div className="gis-table-wrap"><table><thead><tr><th>งาน / ขอบเขต</th><th>สถานะ</th><th>ความคืบหน้า</th></tr></thead>
      <tbody>{jobs.data.map((j,index) => <tr key={j.id}><td><button data-processing-id={j.id} onClick={() => setSelected(j.id)}>ดูงานประมวลผล {index + 1}</button>
        <p>{j.mode === 'gee_dashboard' ? 'Google Earth Engine' : 'Offline Synthetic'} · {j.metadata?.metric?.toUpperCase()} · {j.metadata?.province} {j.metadata?.district || ''} · {j.metadata?.data_year}/{j.metadata?.month || 'รายปี'}</p></td>
        <td><Status value={j.state} /></td><td>{j.progress}%</td></tr>)}</tbody></table></div><PageControls page={jobs} />
    {selected && <ProcessingDetail key={selected} id={selected} version={version} retry={job => form({ type: 'reason',
      title: job.mode === 'gee_dashboard' ? 'ลองประมวลผล Google Earth Engine ใหม่' : 'ลองประมวลผล Offline Synthetic ใหม่', path: `/processing-jobs/${job.id}/retry`,
      body: { expected_revision: job.input_revision, input_hash: job.input_hash } })} />}
  </section>;
}

function Officers({ version, form, pending }) {
  const page = usePage('/officers', {}, version);
  return <section className="gis-card"><h2>เจ้าหน้าที่ GIS</h2><p>ใช้ UUID ของบัญชี Local ที่มีอยู่แล้ว ระบบจะไม่สร้างบัญชีใหม่หรือยกระดับเป็น Admin</p>
    <button disabled={pending} onClick={() => form({ type: 'grant', title: 'เพิ่มสิทธิ์เจ้าหน้าที่ GIS', path: '/officers' })}>เพิ่มเจ้าหน้าที่</button>
    <PageState page={page} />
    <ul>{page.data.map(o => <li key={o.user_id}>{o.user_id} <button disabled={pending} onClick={() => form({ type: 'reason', title: 'ถอนสิทธิ์เจ้าหน้าที่ GIS', path: `/officers/${o.user_id}/revocation`, body: {} })}>ถอนสิทธิ์</button></li>)}</ul>
    <PageControls page={page} />
  </section>;
}

function Workspace({ access, pendingCommand, setPendingCommand }) {
  const [view, setView] = useState('datasets');
  const navigation = useRef(null);
  const previousView = useRef(view);
  useEffect(() => {
    if (previousView.current !== view) navigation.current?.scrollIntoView?.({ block: 'start' });
    previousView.current = view;
  }, [view]);
  const [version, setVersion] = useState(0);
  const [filters, setFilters] = useState({});
  const datasets = usePage('/datasets', filters, version);
  const [jobState, setJobState] = useState('');
  const [selectedDataset, setDataset] = useState(null);
  const [datasetInfo, setDatasetInfo] = useState(null);
  const [editionFilter, setEditionFilter] = useState(null);
  const jobs = usePage('/jobs', { state: jobState, dataset_id: selectedDataset || undefined, edition_id: editionFilter?.id }, version);
  const [selectedJob, setJob] = useState(null);
  const [provinces, setProvinces] = useState([]);
  const [form, setForm] = useState(null);
  // Keep uncertain writes above the authorization branch so a failed /me
  // refresh cannot discard their key while the API is temporarily unavailable.
  const command = pendingCommand?.command || null;
  const setCommand = value => setPendingCommand(value ? { command: value, uncertain: false } : null);
  const [busy, setBusy] = useState(false);
  const uncertain = pendingCommand?.uncertain === true;
  const setUncertain = value => setPendingCommand(old => old ? { ...old, uncertain: value } : null);
  const [showConfirmation, setShowConfirmation] = useState(!!pendingCommand);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState('');
  const lock = useRef(false);
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  useEffect(() => {
    const abort = new AbortController();
    gisRequest('/provinces', { signal: abort.signal }).then(value => { if (!abort.signal.aborted) setProvinces(value.data); })
      .catch(err => { if (!abort.signal.aborted) setError(err); });
    return () => abort.abort();
  }, []);
  const prepare = action => {
    if (lock.current || uncertain) return;
    setForm(null); setError(null); setNotice('');
    setCommand({ ...action, key: crypto.randomUUID() });
    setShowConfirmation(true);
  };
  const refresh = () => { setVersion(n => n + 1); access.refresh(); };
  const selectDataset = dataset => {
    setDataset(dataset?.id || null); setDatasetInfo(dataset || null); setEditionFilter(null); setJob(null);
  };
  const openJobs = edition => { setEditionFilter(edition); setJob(null); setView('jobs'); };
  const confirm = async () => {
    if (lock.current) return;
    lock.current = true; setBusy(true); setError(null);
    try {
      const result = await gisRequest(command.path, { method: command.method || 'POST', body: command.body, key: command.key, query: command.query });
      if (command.path.includes('/ldd-publication/')) {
        window.dispatchEvent(new Event('gis-ldd-publication-change'));
        if (typeof BroadcastChannel==='function') { const c=new BroadcastChannel('gis-ldd-publication');c.postMessage('changed');c.close(); }
      }
      if(command.path.includes('/geotiff-publication/')){
        window.dispatchEvent(new Event('gis-geotiff-publication-change'));
        if(typeof BroadcastChannel==='function'){const c=new BroadcastChannel('gis-geotiff-publication');c.postMessage('changed');c.close();}
      }
      if (mounted.current) {
        if (command.path === '/datasets' && uuid.test(result?.id || '')) { selectDataset(result); setView('datasets'); }
        if (command.path.endsWith('/validation-jobs')) { setJob(null); setView('jobs'); }
        setCommand(null); setUncertain(false); setShowConfirmation(false); setNotice(command.path.endsWith('/validation-jobs') && result?.state === 'failed'
          ? 'ฉบับนี้เคยตรวจแล้วและไม่สำเร็จ ระบบไม่ได้สร้างงานใหม่ เปิดงานเดิมเพื่อดูผล และกด "ขอลองใหม่" ถ้าหน้างานมีปุ่มนี้'
          : 'Backend ยืนยันบันทึกคำสั่งแล้ว กรุณาดูสถานะล่าสุดในรายการ'); refresh();
      }
    } catch (err) {
      if (mounted.current) {
        setError(err);
        // Unknown transport/server outcomes retain the exact key and frozen body.
        if (err.status > 0 && err.status < 500 && err.status !== 429) { setCommand(null); setUncertain(false); setShowConfirmation(false); refresh(); }
        else if (!err.status || err.status >= 500) setUncertain(true);
      }
    } finally { lock.current = false; if (mounted.current) setBusy(false); }
  };
  return <>
    <div className="gis-actions"><button onClick={refresh} disabled={busy}>โหลดข้อมูลและสิทธิ์ล่าสุด</button></div>
    <ErrorNote error={error} />{notice && <p role="status">{notice}</p>}
    {uncertain && <aside className="gis-banner"><p>ยังไม่ทราบผลคำสั่งก่อนหน้า ระบบพักคำสั่งใหม่เพื่อป้องกันข้อมูลซ้ำ ใช้การโหลดสถานะล่าสุดหรือลองคำสั่งเดิมด้วย Key เดิม</p><button onClick={() => setShowConfirmation(true)}>ตรวจคำสั่งที่ยังไม่ทราบผล</button></aside>}
    <nav ref={navigation} className="gis-navigation" role="tablist" aria-label="ส่วนจัดการข้อมูล GIS" onKeyDown={event => {
      if (!['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) return;
      const tabs = [...event.currentTarget.querySelectorAll('[role="tab"]')];
      const index = tabs.indexOf(document.activeElement);
      const next = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
      event.preventDefault(); tabs[next]?.focus(); tabs[next]?.click();
    }}>
      {[['datasets','ชุดข้อมูล'],['jobs','งานและรายงาน'],...(access.me.processing_enabled ? [['processing','ประมวลผล NDVI/LST']] : []),...(access.me.capabilities.includes('grant_officer') ? [['officers','เจ้าหน้าที่ GIS']] : [])].map(([key,title]) =>
        <button key={key} id={`gis-tab-${key}`} role="tab" tabIndex={view === key ? 0 : -1} aria-selected={view === key} aria-controls={`gis-panel-${key}`} onClick={() => setView(key)}>{title}</button>)}
    </nav>
    <details className="gis-overview"><summary>จำนวนรายการที่โหลด</summary><p>นับเฉพาะหน้า Dataset / Jobs ปัจจุบัน หน้าละไม่เกิน 20 รายการ ไม่ใช่ยอดรวมทั้งระบบ</p>
      <p>Datasets: {datasets.loading || datasets.error ? '—' : datasets.data.length} · Jobs: {jobs.loading || jobs.error ? '—' : jobs.data.length}</p>
      <p>{['queued', 'running', 'succeeded', 'failed'].map(s => `${labels[s]}: ${jobs.loading || jobs.error ? '—' : jobs.data.filter(j => j.state === s).length}`).join(' · ')}</p>
      <p>ดูจำนวน Editions เฉพาะหน้ารายการของ Dataset ที่เลือกด้านล่าง</p>
    </details>
    <div role="tabpanel" id="gis-panel-datasets" aria-labelledby="gis-tab-datasets" hidden={view !== 'datasets'}>
    <div className={`gis-master-detail${selectedDataset ? ' has-selection' : ''}`}>
    <section className="gis-card gis-catalog"><h2>ชุดข้อมูล</h2><p className="gis-help">เลือกชุดข้อมูลเพื่ออัปโหลดไฟล์ จัดการฉบับ และติดตามผลตรวจ</p>
      <form className="gis-filters" onSubmit={event => { event.preventDefault(); const f = Object.fromEntries(new FormData(event.currentTarget)); setFilters(f); selectDataset(null); }}>
        <Field label="จังหวัด"><select name="province"><option value="">ทุกจังหวัด</option>{provinces.map(p => <option key={p.name_en} value={p.name_en}>{p.name_th || p.name_en}</option>)}</select></Field>
        <Field label="ปี (ค.ศ.)" name="data_year" type="number" min="1980" max={new Date().getFullYear() + 1} />
        <Field label="ประเภท"><select name="kind"><option value="">ทุกประเภท</option><option value="ldd_shapefile">LDD Shapefile</option><option value="geotiff">GeoTIFF</option></select></Field>
        <button type="submit">กรองข้อมูล</button>
      </form>
      {access.me.capabilities.includes('create_dataset') && <button className="gis-primary" disabled={busy || uncertain || provinces.length === 0} onClick={() => setForm({ type: 'dataset', title: 'สร้างชุดข้อมูล', path: '/datasets' })}>สร้างชุดข้อมูล</button>}
      <PageState page={datasets} empty="ยังไม่มีชุดข้อมูลที่ตรงกับตัวกรอง เริ่มด้วยสร้าง Dataset หรือปรับตัวกรอง" />
      <ul className="gis-dataset-list" aria-label="รายการชุดข้อมูล">{datasets.data.map(d => <li key={d.id}>
        <button aria-label={d.title} aria-pressed={selectedDataset === d.id} className="gis-dataset-choice" onClick={() => selectDataset(d)}><strong>{d.title}</strong><span>{d.province} · {d.data_year}{d.month ? ` / ${d.month}` : ''}</span><span>{labels[d.purpose]} · {d.active_edition_id ? 'มีฉบับใช้งาน' : 'ยังไม่เปิดใช้'}</span></button>
      </li>)}</ul>
      <PageControls page={datasets} />
    </section>
    {selectedDataset ? <DatasetDetail key={selectedDataset} id={selectedDataset} version={version} access={access} form={setForm} prepare={prepare} pending={busy || uncertain} onLoad={setDatasetInfo} onJobs={openJobs} onClose={() => selectDataset(null)} />
      : <section className="gis-card gis-start"><span className="gis-kicker">เริ่มต้นจัดการข้อมูล</span><h2>เลือกชุดข้อมูลเพื่อเริ่มทำงาน</h2><p>เลือกจากรายการด้านซ้าย หรือสร้างชุดข้อมูลใหม่ ระบบจะเก็บไฟล์แต่ละครั้งเป็นฉบับแยกกัน</p><ol><li>สร้างชุดข้อมูลจังหวัดและปีที่ต้องการ</li><li>อัปโหลด Shapefile ZIP หรือ GeoTIFF</li><li>ส่งตรวจสอบและเปิดรายงานผล</li></ol><p className="gis-help">การตรวจผ่านไม่เปิดใช้ข้อมูลโดยอัตโนมัติ</p></section>}
    </div></div>
    <div role="tabpanel" id="gis-panel-jobs" aria-labelledby="gis-tab-jobs" hidden={view !== 'jobs'}>
    <section className="gis-card"><h2>งานตรวจสอบข้อมูล GIS</h2><p>ใช้ปุ่มรีเฟรชเพื่อติดตามงาน Worker ทำต่อได้เมื่อปิดหน้าเว็บ ไม่มีการเปิดใช้ Edition อัตโนมัติ</p>
      <div className="gis-context"><strong>{datasetInfo?.title || 'ทุกชุดข้อมูลที่มีสิทธิ์เข้าถึง'}</strong><p>{editionFilter ? editionFilter.label : 'แสดงทุกฉบับของขอบเขตที่เลือก'}</p>
        {selectedDataset && <div className="gis-actions"><button onClick={() => setView('datasets')}>กลับชุดข้อมูลที่เลือก</button><button onClick={() => { setEditionFilter(null); setJob(null); }}>แสดงทุกฉบับในชุดนี้</button><button onClick={() => selectDataset(null)}>ดูงานทุกชุดข้อมูล</button></div>}
      </div>
      <Field label="สถานะงาน"><select value={jobState} onChange={e => setJobState(e.target.value)}><option value="">ทุกสถานะ</option>{['queued','running','succeeded','failed'].map(s => <option key={s} value={s}>{labels[s]}</option>)}</select></Field>
      <PageState page={jobs} empty="ยังไม่มีงานในขอบเขตนี้ กลับไปเลือกฉบับข้อมูลแล้วกดส่งตรวจสอบ" />
      <div className="gis-table-wrap"><table><thead><tr><th>งานตรวจสอบ</th><th>สถานะ</th><th>ความคืบหน้า</th><th>ครั้งที่พยายาม</th></tr></thead><tbody>{jobs.data.map((j,index) => <tr key={j.id}>
        <td><button data-job-id={j.id} onClick={() => setJob(j.id)}>ดูงานตรวจสอบ {index + 1}</button><details className="gis-technical"><summary>รหัสงานและฉบับ</summary><p>{j.id}</p><p>Edition ID: {j.edition_id}</p></details></td><td><Status value={j.state} /></td><td>{j.progress}%</td><td>{j.attempt_count}</td>
      </tr>)}</tbody></table></div><PageControls page={jobs} />
    </section>
    {view === 'jobs' && selectedJob && <JobDetail key={selectedJob} id={selectedJob} version={version} context={datasetInfo} onRetry={async job => {
      if (busy || uncertain) return;
      try {
        const e = await gisRequest(`/editions/${job.edition_id}`);
        if (e.state !== 'draft' || e.input_revision !== job.input_revision || e.input_hash !== job.input_hash) throw new Error('ข้อมูลฉบับเปลี่ยนแล้ว ไม่สามารถลองงานเดิมใหม่ได้');
        setForm({ type: 'reason', title: 'ขอลองตรวจสอบใหม่ (Backend ตรวจสิทธิ์อีกครั้ง)', path: `/jobs/${job.id}/retry`, body: { expected_revision: e.input_revision, input_hash: e.input_hash } });
      } catch (err) { setError(err); }
    }} />}
    </div>
    {access.me.processing_enabled && <div role="tabpanel" id="gis-panel-processing" aria-labelledby="gis-tab-processing" hidden={view !== 'processing'}>{view === 'processing' && <ProcessingPanel version={version} form={setForm} pending={busy || uncertain} provinces={provinces} />}</div>}
    {access.me.capabilities.includes('grant_officer') && <div role="tabpanel" id="gis-panel-officers" aria-labelledby="gis-tab-officers" hidden={view !== 'officers'}>{view === 'officers' && <Officers version={version} form={setForm} pending={busy || uncertain} />}</div>}
    {form && <FormDialog key={`${form.path}:${form.type}`} form={form} prepare={prepare} close={() => setForm(null)} provinces={provinces} />}
    {command && showConfirmation && <Modal title="ยืนยันคำสั่ง" onClose={() => { setShowConfirmation(false); if (!uncertain) setCommand(null); }} locked={busy}>
      <p>{command.title}</p><p>ดำเนินการกับข้อมูลใน Local Sandbox เท่านั้น Backend จะตรวจสิทธิ์ Revision และสถานะล่าสุดอีกครั้ง</p>
      {command.body instanceof Blob && <p>ไฟล์: {command.body.name} · {command.body.size} bytes · {command.query?.crs} · {command.query?.profile ? `Profile ${command.query.profile}` : `Encoding ${command.query?.encoding}`} · Dataset Revision {command.query?.expected_revision}</p>}
      {busy && command.body instanceof Blob && <div role="status"><progress aria-label="กำลังส่งไฟล์ GIS" /> กำลังส่งและจัดเก็บไฟล์ กรุณารอ Backend ยืนยัน</div>}
      <p>ชุดข้อมูล: {command.body.title || datasetInfo?.title || 'ตามขอบเขตที่ตรวจทาน'}</p>
      <details className="gis-technical"><summary>รายละเอียดคำสั่งและรหัสอ้างอิง</summary><p>เป้าหมาย: {command.path.split('/').filter(part => uuid.test(part)).join(' / ') || 'รายการใหม่'}</p>
      <dl>{Object.entries({ ชื่อ: command.body.title, จังหวัด: command.body.province, ปี: command.body.data_year, เดือน: command.body.month,
        ประเภท: command.body.kind, วัตถุประสงค์: command.body.purpose, ผู้ใช้: command.body.user_id,
        ดัชนี: command.body.metric, อำเภอ: command.body.district, โหมด: command.body.mode, ชุดทดสอบ: command.body.scenario,
        ฉบับ: command.body.edition_id, Revision: command.body.expected_revision, DatasetRevision: command.body.expected_dataset_revision,
        ฉบับใช้งานที่คาดไว้: command.body.expected_active_edition_id, ฉบับแทนที่: command.body.replacement_edition_id,
        Fixture: command.body.manifest?.fixture_id, MetadataVersion: command.body.manifest?.schema_version,
        SHA256: command.body.manifest?.sha256,
      }).filter(([, value]) => value !== undefined).map(([name, value]) => <div key={name}><dt>{name}</dt><dd>{value === null ? 'ไม่มี' : String(value)}</dd></div>)}</dl></details>
      {command.body.manifest && <details><summary>ตรวจทาน Metadata</summary><dl>{['provider','crs','data_kind','byte_size','profile','provider_build','provenance','attributes','bands','resolution','nodata','units','scales','offsets']
        .filter(name => command.body.manifest[name] !== undefined).map(name => <div key={name}><dt>{name}</dt><dd>{String(command.body.manifest[name]).slice(0, 1000)}</dd></div>)}</dl></details>}
      {command.body.reason && <p>เหตุผล: {command.body.reason}</p>}
      <p>หากการเชื่อมต่อขัดข้อง ให้ลองคำสั่งเดิมจากหน้าต่างนี้เพื่อใช้ Idempotency-Key เดิม ห้ามสร้างรายการใหม่ซ้ำก่อนตรวจสถานะ</p>
      <ErrorNote error={error} /><div className="gis-actions"><button disabled={busy} onClick={confirm}>{busy ? 'กำลังส่งคำสั่ง…' : 'ยืนยันดำเนินการ'}</button>
        <button disabled={busy} onClick={() => { setShowConfirmation(false); if (!uncertain) setCommand(null); }}>{uncertain ? 'ปิดเพื่อดูสถานะ (เก็บคำสั่งเดิม)' : 'ยกเลิก'}</button></div>
    </Modal>}
  </>;
}

export default function GisManagement({ access, userId, onBack }) {
  const [pending, setPending] = useState(null);
  const ownedPending = pending && pending.owner === userId ? pending.value : null;
  const updatePending = value => setPending(old => {
    const next = typeof value === 'function' ? value(old && old.owner === userId ? old.value : null) : value;
    return next ? { owner: userId, value: next } : null;
  });
  return <main className="gis-page"><header className="gis-heading"><div><span className="gis-kicker">GREENLENS / LOCAL SANDBOX</span><h1>จัดการข้อมูล GIS</h1></div><button onClick={onBack}>กลับแผนที่</button></header>
    <aside className="gis-banner"><strong>Local Sandbox · ตรวจผ่านไม่ได้เปิดใช้ข้อมูลอัตโนมัติ</strong><details><summary>ขอบเขตการใช้งานและข้อจำกัด</summary><p>{access.me?.ldd_upload_enabled || access.me?.geotiff_upload_enabled ? 'ไฟล์ที่อัปโหลดใช้เฉพาะ Local Sandbox ไม่เปลี่ยนแหล่งข้อมูลระบบเดิม และไม่เชื่อม GEE' : 'ยังไม่รองรับไฟล์อัปโหลดจริงหรือ GEE'} {access.me?.processing_enabled ? 'ผลในส่วน Offline Synthetic มาจากข้อมูลจำลอง ไม่ใช่ผลดาวเทียมหรือค่าของพื้นที่จริง' : 'ข้อมูล NDVI/LST ของระบบเดิมเป็นผลวิเคราะห์ดาวเทียม ไม่ใช่ข้อมูลภาคสนามหรืออุณหภูมิอากาศ'}</p></details></aside>
    {!gisConfigured() ? <p role="alert">ระบบจัดการ GIS ปิดอยู่ หรือการตั้งค่าไม่ใช่ Local Target ที่อนุญาต</p>
      : access.loading && !access.me ? <p role="status">กำลังตรวจสอบสิทธิ์จาก Backend…</p>
        : access.error ? <><ErrorNote error={access.error} /><button onClick={access.refresh}>ตรวจสิทธิ์อีกครั้ง</button></>
          : !access.allowed ? <p role="alert">ไม่มีสิทธิ์จัดการข้อมูล GIS กรุณาติดต่อผู้ดูแลระบบ</p>
            : <Workspace key={userId} access={access} pendingCommand={ownedPending} setPendingCommand={updatePending} />}
  </main>;
}
