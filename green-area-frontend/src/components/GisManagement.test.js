import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import GisManagement from './GisManagement';
import UserMenu from './UserMenu';
import { gisConfigured, gisRequest, GisError } from '../utils/gisClient';

vi.mock('../utils/gisClient', async original => ({ ...await original(), gisConfigured: vi.fn(() => true), gisRequest: vi.fn() }));
const ds = { id: '10000000-0000-4000-8000-000000000001', title: 'ทดสอบ LDD', province: 'Bangkok Metropolis', data_year: 2026, month: 0, kind: 'ldd_shapefile', purpose: 'landuse', revision: 3, active_edition_id: null };
const ed = { id: '20000000-0000-4000-8000-000000000002', dataset_id: ds.id, state: 'draft', input_revision: 4, input_hash: 'a'.repeat(64), manifest: { schema_version: 2, provider: 'synthetic', fixture_id: 'test-fixture', sha256: 'b'.repeat(64), data_kind: 'polygon' } };
const job = { id: '30000000-0000-4000-8000-000000000003', edition_id: ed.id, state: 'failed', input_revision: 4, input_hash: ed.input_hash, attempt_count: 3, progress: 0, parent_job_id: null, error_code: 'transient' };
const officer = { admin: false, officer: true, activation_enabled: false, capabilities: ['read_catalog','create_dataset','edit_draft','clone_edition','enqueue_validation','eligible_retry'] };
const admin = { ...officer, admin: true, capabilities: [...officer.capabilities, 'grant_officer','revoke_officer','sandbox_activate','sandbox_rollback','sandbox_withdraw'] };
const page = data => ({ data, next_cursor: null, has_more: false });
const access = me => ({ me, allowed: !!me?.capabilities?.includes('read_catalog'), refresh: vi.fn(), loading: false });
function respond(path, options = {}) {
  if (options.method) return Promise.resolve({ id: 'new-item' });
  if (path === '/provinces') return Promise.resolve(page([{ name_en: ds.province, name_th: 'กรุงเทพมหานคร' }]));
  if (path === '/datasets') return Promise.resolve(page([ds]));
  if (path === `/datasets/${ds.id}`) return Promise.resolve(ds);
  if (path === `/datasets/${ds.id}/editions`) return Promise.resolve(page([ed]));
  if (path === `/editions/${ed.id}`) return Promise.resolve(ed);
  if (path === '/jobs') return Promise.resolve(page([job]));
  if (path === `/jobs/${job.id}`) return Promise.resolve(job);
  return Promise.resolve(page([]));
}
function switchTab(name) { fireEvent.click(screen.getByRole('tab', { name, exact: true })); }
async function openJob() { switchTab('งานและรายงาน'); fireEvent.click(await screen.findByRole('button', { name: 'ดูงานตรวจสอบ 1' })); }
function show(me = officer) { return render(<GisManagement access={access(me)} userId="user" onBack={vi.fn()} />); }
async function openDataset() { fireEvent.click(await screen.findByRole('button', { name: ds.title })); await screen.findByText('ฉบับข้อมูล (หน้านี้)'); }
async function confirm() { const button = await screen.findByRole('button', { name: 'ยืนยันดำเนินการ' }); await act(async () => { fireEvent.click(button); }); }
const writes = () => gisRequest.mock.calls.filter(([, options]) => options?.method);
beforeEach(() => { vi.clearAllMocks(); gisConfigured.mockReturnValue(true); gisRequest.mockImplementation(respond); });

test('GeoTIFF upload requires confirmation and retains binary profile/revision', async () => {
  const geo = { ...ds, kind: 'geotiff', purpose: 'ndvi' };
  gisRequest.mockImplementation((path, options) => path === `/datasets/${ds.id}` && !options?.method ? Promise.resolve(geo) : respond(path, options));
  show({ ...officer, geotiff_upload_enabled: true }); await openDataset();
  fireEvent.click(screen.getByRole('button', { name: 'อัปโหลด GeoTIFF', exact: true }));
  const file = new File(['II* mock'], 'synthetic.tif', { type: 'image/tiff' });
  fireEvent.change(screen.getByLabelText('ไฟล์ GeoTIFF'), { target: { files: [file] } });
  expect(screen.getByLabelText('Scientific Profile')).toHaveValue('ndvi_bands');
  fireEvent.change(screen.getByLabelText('แหล่งที่มาของข้อมูล'), { target: { value: '  Sentinel-2 ส่งออกจาก GEE  ' } });
  fireEvent.change(screen.getByLabelText('วันที่ข้อมูลดาวเทียม'), { target: { value: '2025-03-01' } });
  // jsdom does not include programmatically supplied files in FormData.
  const NativeFormData = globalThis.FormData;
  const spy = vi.spyOn(globalThis, 'FormData').mockImplementation(function(form) {
    const data = new NativeFormData(form); data.set('file',file); return data;
  });
  fireEvent.submit(screen.getByRole('dialog').querySelector('form'));
  spy.mockRestore(); expect(writes()).toHaveLength(0); await confirm();
  expect(writes()[0][0]).toBe(`/datasets/${ds.id}/geotiff-uploads`);
  expect(writes()[0][1].body).toBe(file);
  expect(writes()[0][1].query).toEqual({ expected_revision: 3, crs: 'EPSG:32647', profile: 'ndvi_bands',
    source_label: 'Sentinel-2 ส่งออกจาก GEE', acquisition_date: '2025-03-01' });
});

test('GeoTIFF band report shows the computed area and partial coverage', async () => {
  const report = { provider_build: 'geotiff-local-v1', valid: true, province: ds.province, metadata: { profile: 'ndvi_bands',
    crs: 'EPSG:4326', bands: ['B4', 'B8'], resolution: [0.001, 0.001], dtype: 'uint16', nodata: 0,
    units: 'reflectance', output_units: 'unitless', scales: [1, 1], offsets: [0, 0] },
    warnings: [{ code: 'GEOTIFF_PARTIAL_PROVINCE_COVERAGE', count: 1 }],
    coverage: { mode: 'province_boundary_clip', fraction_of_province: 0.25, fraction_of_file: 0.5 },
    statistics: { valid_pixels: 3, outside_area_pixels: 5, mean: 0.5 } };
  gisRequest.mockImplementation((path, options) => path === `/jobs/${job.id}` ? Promise.resolve({ ...job, state: 'succeeded', result: { report } }) : respond(path, options));
  show(); await openJob();
  expect(await screen.findByText(/ครอบคลุมจังหวัด 25\.0% · ใช้พิกเซลของไฟล์ 50\.0%/)).toBeInTheDocument();
  expect(screen.getByRole('note')).toHaveTextContent('เพียงบางส่วน');
  expect(screen.getByText('outside_area_pixels: 5')).toBeInTheDocument();
});

const lddReport = (errors, warnings, valid) => ({ provider_build: 'ldd-local-v1', upload_id: '40000000-0000-4000-8000-000000000004',
  valid, error_code: errors[0]?.code ?? null, errors, checks: [], province: ds.province, data_year: 2025, crs: 'EPSG:32647',
  encoding: 'utf-8', statistics: { feature_count: 2 },
  warnings: [{ code: 'BOUNDARY_APPROXIMATE', count: 1 }, { code: 'LDD_POLICY_V2', count: 1 }, ...warnings] });

test.each([
  [[], [], true, 'ผ่าน (Accepted)'],
  [[], [{ code: 'GEOMETRY_REPAIRED', count: 6 }, { code: 'BOUNDARY_OUTSIDE_MINOR', count: 3 }], true, 'ผ่านพร้อมข้อสังเกต (Accepted with Warnings)'],
  [[{ code: 'UNKNOWN_CODE_REVIEW_REQUIRED', count: 2 }], [], false, 'ต้องตรวจสอบก่อนใช้ (Review Required)'],
  [[{ code: 'OUTSIDE_PROVINCE', count: 1 }, { code: 'UNKNOWN_CODE_REVIEW_REQUIRED', count: 2 }], [], false, 'ไม่ผ่าน (Rejected)'],
])('LDD report separates accepted, warnings, review and rejected (%#)', async (errors, warnings, valid, label) => {
  const report = lddReport(errors, warnings, valid);
  gisRequest.mockImplementation((path, options) => path === `/jobs/${job.id}` ? Promise.resolve({ ...job, state: 'succeeded', result: { report } }) : respond(path, options));
  show(); await openJob();
  expect(await screen.findByText(`จำแนกผล: ${label}`)).toBeInTheDocument();
  if (warnings.length) expect(screen.getByText(/ซ่อมรูปร่างที่ผิดรูปเล็กน้อยแล้ว/)).toHaveTextContent('(6)');
});

test('a plus-separated composite code is shown as a warning, not hidden and not a failure', async () => {
  const report = lddReport([], [{ code: 'COMPOSITE_PLUS_SEPARATOR', count: 34 }], true);
  gisRequest.mockImplementation((path, options) => path === `/jobs/${job.id}` ? Promise.resolve({ ...job, state: 'succeeded', result: { report } }) : respond(path, options));
  show(); await openJob();
  expect(await screen.findByText('จำแนกผล: ผ่านพร้อมข้อสังเกต (Accepted with Warnings)')).toBeInTheDocument();
  expect(screen.getByText(/รหัสผสมที่คั่นด้วย \+ อ่านเป็นรหัสผสมแบบ \//)).toHaveTextContent('(34)');
});

test('GeoTIFF report separates file validation from analysis and activation', async () => {
  const report = { provider_build: 'geotiff-local-v1', valid: true, metadata: { profile: 'ndvi_ready',
    crs: 'EPSG:32647', bands: ['NDVI'], resolution: [10,10], dtype: 'float32', nodata: -9999,
    units: 'unitless', output_units: 'unitless', scales: [1], offsets: [0] }, statistics: { valid_pixels: 3, mean: 0 } };
  gisRequest.mockImplementation((path, options) => path === `/jobs/${job.id}` ? Promise.resolve({ ...job, state: 'succeeded', result: { report } }) : respond(path, options));
  show(); await openJob();
  expect(await screen.findByText('รายงาน GeoTIFF — Local/Test')).toBeInTheDocument();
  expect(screen.getByText(/ผล Validation: ผ่าน/)).toHaveTextContent('ไม่เปลี่ยน Cache');
  expect(screen.getByText('mean: 0')).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'เปิดใช้ฉบับ' })).not.toBeInTheDocument();
});

test('offline processing requires backend readiness and confirmation; district/month body is explicit', async () => {
  gisRequest.mockImplementation((path, options) => path === '/processing-options'
    ? Promise.resolve({ districts: [{ name_en: 'BangRak', name_th: 'บางรัก' }], live_enabled: false }) : respond(path, options));
  show({ ...officer, processing_enabled: true }); switchTab('ประมวลผล NDVI/LST');
  fireEvent.click(await screen.findByRole('button', { name: 'สร้างงานประมวลผล NDVI/LST' }));
  expect(screen.getByRole('note')).toHaveTextContent('ไม่ใช่ภาพดาวเทียม');
  fireEvent.change(screen.getByLabelText('ดัชนีประมวลผล'), { target: { value: 'lst' } });
  fireEvent.change(screen.getByLabelText('จังหวัดประมวลผล'), { target: { value: ds.province } });
  fireEvent.change(screen.getByLabelText('ระดับพื้นที่'), { target: { value: 'district' } });
  await screen.findByRole('option', { name: 'บางรัก' });
  fireEvent.change(screen.getByLabelText('อำเภอประมวลผล'), { target: { value: 'BangRak' } });
  fireEvent.change(screen.getByLabelText('ปีประมวลผล (ค.ศ.)'), { target: { value: '2025' } });
  fireEvent.change(screen.getByLabelText('ช่วงเวลาประมวลผล'), { target: { value: '2' } });
  fireEvent.click(screen.getByRole('button', { name: 'ตรวจทานคำสั่ง' }));
  expect(writes()).toHaveLength(0);
  await confirm();
  expect(writes()[0][0]).toBe('/processing-jobs');
  expect(writes()[0][1].body).toEqual({ province: ds.province, district: 'BangRak', metric: 'lst',
    data_year: 2025, month: 2, mode: 'offline_synthetic', scenario: 'standard', expected_revision: 1 });
});

test('GEE source appears only when the backend offers it and sends the gee_dashboard body', async () => {
  gisRequest.mockImplementation((path, options) => path === '/processing-options'
    ? Promise.resolve({ districts: [], live_enabled: false, modes: ['offline_synthetic', 'gee_dashboard'] }) : respond(path, options));
  show({ ...officer, processing_enabled: true }); switchTab('ประมวลผล NDVI/LST');
  fireEvent.click(await screen.findByRole('button', { name: 'สร้างงานประมวลผล NDVI/LST' }));
  fireEvent.change(await screen.findByLabelText('แหล่งข้อมูล'), { target: { value: 'gee_dashboard' } });
  expect(screen.getByRole('note')).toHaveTextContent('ภาพดาวเทียมจริงใน Google Earth Engine');
  expect(screen.queryByLabelText('ชุดข้อมูลจำลอง')).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('จังหวัดประมวลผล'), { target: { value: ds.province } });
  fireEvent.change(screen.getByLabelText('ปีประมวลผล (ค.ศ.)'), { target: { value: '2024' } });
  fireEvent.click(screen.getByRole('button', { name: 'ตรวจทานคำสั่ง' }));
  expect(writes()).toHaveLength(0);
  await confirm();
  expect(writes()[0][1].body).toEqual({ province: ds.province, district: null, metric: 'ndvi',
    data_year: 2024, month: 0, mode: 'gee_dashboard', scenario: 'standard', expected_revision: 1 });
});

test('without backend GEE readiness there is no source selector and the body stays offline', async () => {
  gisRequest.mockImplementation((path, options) => path === '/processing-options'
    ? Promise.resolve({ districts: [], live_enabled: false }) : respond(path, options));
  show({ ...officer, processing_enabled: true }); switchTab('ประมวลผล NDVI/LST');
  fireEvent.click(await screen.findByRole('button', { name: 'สร้างงานประมวลผล NDVI/LST' }));
  expect(screen.queryByLabelText('แหล่งข้อมูล')).not.toBeInTheDocument();
  expect(screen.getByLabelText('ชุดข้อมูลจำลอง')).toBeInTheDocument();
});

test('GEE result shows the Dashboard time-series point and rejects a synthetic-flagged report', async () => {
  const metadata = { metric: 'lst', province: ds.province, district: null, data_year: 2023, month: 4,
    cache_table: 'province_lst_monthly', processing_version: 'gee-dashboard-v1', source_collections: [], requested_on: '2026-11-06', scale_m: 500 };
  const report = { mode: 'gee_dashboard', synthetic: false, valid: true, error_code: null, metadata,
    statistics: { valid_pixels: null, mean: 31.27, min: null, max: null },
    observation: { from_cache: false, cached_at: null, image_count: 3, data_quality: null },
    cache: { table: 'province_lst_monthly', province: ds.province, district: null, year: 2023, month: 4, written: true } };
  const processing = { ...job, mode: 'gee_dashboard', state: 'succeeded', progress: 100, metadata, result: { report } };
  gisRequest.mockImplementation((path, options) => path === '/processing-jobs' ? Promise.resolve(page([processing]))
    : path === `/processing-jobs/${job.id}` ? Promise.resolve(processing)
      : path.startsWith('/processing-jobs/') ? Promise.resolve(page([])) : respond(path, options));
  show({ ...officer, processing_enabled: true }); switchTab('ประมวลผล NDVI/LST');
  expect(await screen.findByText(/Google Earth Engine · LST/)).toBeInTheDocument();
  fireEvent.click(await screen.findByRole('button', { name: 'ดูงานประมวลผล 1' }));
  expect(await screen.findByText('ผลประมวลผล Google Earth Engine')).toBeInTheDocument();
  expect(screen.getByText(/บันทึกจุดข้อมูลลงอนุกรมเวลาของ Dashboard แล้ว \(province_lst_monthly\)/)).toBeInTheDocument();
  expect(screen.getByText('mean: 31.27 °C')).toBeInTheDocument();
  expect(screen.getByText(/จำนวนภาพ 3/)).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'เปิดใช้ฉบับ' })).not.toBeInTheDocument();
});

test('a GEE result read from the cache does not claim it saved a new point', async () => {
  const metadata = { metric: 'ndvi', province: ds.province, district: null, data_year: 2025, month: 0,
    cache_table: 'ndvi_annual', processing_version: 'gee-dashboard-v1', source_collections: [], requested_on: '2026-11-06', scale_m: 500 };
  const report = { mode: 'gee_dashboard', synthetic: false, valid: true, error_code: null, metadata,
    statistics: { valid_pixels: null, mean: 0.3963, min: 0.0008, max: 0.9011 },
    observation: { from_cache: true, cached_at: '2026-08-05T07:25:38', image_count: null, data_quality: null },
    cache: { table: 'ndvi_annual', province: ds.province, district: null, year: 2025, month: 0, written: true } };
  const processing = { ...job, mode: 'gee_dashboard', state: 'succeeded', progress: 100, metadata, result: { report } };
  gisRequest.mockImplementation((path, options) => path === '/processing-jobs' ? Promise.resolve(page([processing]))
    : path === `/processing-jobs/${job.id}` ? Promise.resolve(processing)
      : path.startsWith('/processing-jobs/') ? Promise.resolve(page([])) : respond(path, options));
  show({ ...officer, processing_enabled: true }); switchTab('ประมวลผล NDVI/LST');
  fireEvent.click(await screen.findByRole('button', { name: 'ดูงานประมวลผล 1' }));
  expect(await screen.findByText(/มีจุดข้อมูลนี้ในอนุกรมเวลาของ Dashboard อยู่แล้ว ไม่ได้บันทึกใหม่ \(ndvi_annual\)/)).toBeInTheDocument();
  expect(screen.queryByText(/บันทึกจุดข้อมูลลงอนุกรมเวลาของ Dashboard แล้ว/)).not.toBeInTheDocument();
});

test('a gee_dashboard report claiming synthetic data is refused', async () => {
  const report = { mode: 'gee_dashboard', synthetic: true, valid: true, metadata: {}, statistics: {} };
  const processing = { ...job, mode: 'gee_dashboard', state: 'succeeded', progress: 100, metadata: {}, result: { report } };
  gisRequest.mockImplementation((path, options) => path === '/processing-jobs' ? Promise.resolve(page([processing]))
    : path === `/processing-jobs/${job.id}` ? Promise.resolve(processing)
      : path.startsWith('/processing-jobs/') ? Promise.resolve(page([])) : respond(path, options));
  show({ ...officer, processing_enabled: true }); switchTab('ประมวลผล NDVI/LST');
  fireEvent.click(await screen.findByRole('button', { name: 'ดูงานประมวลผล 1' }));
  expect(await screen.findByText('ผลนี้ไม่ตรงกับโหมด Google Earth Engine ที่อนุญาต')).toBeInTheDocument();
});

test('offline candidate cannot be presented as live GEE or automatically published', async () => {
  const report = { mode: 'offline_synthetic', synthetic: true, valid: true, error_code: null,
    metadata: { metric: 'ndvi', province: ds.province, start_date: '2025-01-01', end_date: '2026-01-01',
      scale_m: 500, resolution: 10, units: 'unitless', fixture_id: 'p3-ndvi-standard-v1', source_collections: [] },
    statistics: { valid_pixels: 2, mean: .4921, min: .4286, max: .5556 } };
  const processing = { ...job, state: 'succeeded', progress: 100, metadata: report.metadata, result: { report } };
  gisRequest.mockImplementation((path, options) => path === '/processing-jobs' ? Promise.resolve(page([processing]))
    : path === `/processing-jobs/${job.id}` ? Promise.resolve(processing)
      : path.startsWith('/processing-jobs/') ? Promise.resolve(page([])) : respond(path, options));
  show({ ...officer, processing_enabled: true }); switchTab('ประมวลผล NDVI/LST');
  fireEvent.click(await screen.findByRole('button', { name: 'ดูงานประมวลผล 1' }));
  expect(await screen.findByText('Candidate / Offline Synthetic')).toBeInTheDocument();
  expect(screen.getByText(/ข้อมูลจำลองเท่านั้น ไม่ใช่ผล GEE/)).toBeInTheDocument();
  expect(screen.getByText('mean: 0.4921')).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'เปิดใช้ฉบับ' })).not.toBeInTheDocument();
});

test('processing controls stay hidden before processing migration readiness', async () => {
  show(officer);
  await screen.findByRole('button', { name: ds.title });
  expect(screen.queryByRole('button', { name: 'สร้างงานประมวลผล NDVI/LST' })).not.toBeInTheDocument();
});

test('LDD upload requires backend local-storage capability and opens bounded file form', async () => {
  show({ ...officer, ldd_upload_enabled: true });
  await openDataset();
  fireEvent.click(screen.getByRole('button', { name: 'อัปโหลด LDD ZIP', exact: true }));
  const input = screen.getByLabelText('ไฟล์ LDD Shapefile ZIP');
  expect(input).toHaveAttribute('type', 'file');
  expect(input).toHaveAttribute('accept', '.zip,application/zip');
  expect(screen.getByLabelText('CRS ที่คาดว่าใช้ในไฟล์')).toHaveValue('EPSG:32647');
  expect(screen.getByLabelText('Encoding ภาษาไทย')).toHaveValue('auto');
  expect(writes()).toHaveLength(0);
});

test('LDD upload hidden when backend has no approved local storage', async () => {
  show(officer);
  await openDataset();
  expect(screen.queryByRole('button', { name: 'อัปโหลด LDD ZIP', exact: true })).not.toBeInTheDocument();
});

test('disabled/denied state never mounts catalog or invokes GIS requests', () => {
  const { unmount } = show({ capabilities: [] }); expect(screen.getByRole('alert')).toHaveTextContent('ไม่มีสิทธิ์'); expect(gisRequest).not.toHaveBeenCalled(); unmount();
  gisConfigured.mockReturnValue(false); show(); expect(screen.getByRole('alert')).toHaveTextContent('ปิดอยู่'); expect(gisRequest).not.toHaveBeenCalled();
});
test('loading and access-error offer safe recovery', () => {
  const a = { ...access(null), loading: true }; const { rerender } = render(<GisManagement access={a} />);
  expect(screen.getByRole('status')).toHaveTextContent('ตรวจสอบสิทธิ์');
  rerender(<GisManagement access={{ ...a, loading: false, error: new GisError(401) }} />);
  expect(screen.getByRole('alert')).toHaveTextContent('เข้าสู่ระบบใหม่'); fireEvent.click(screen.getByText('ตรวจสิทธิ์อีกครั้ง')); expect(a.refresh).toHaveBeenCalled();
});
test('menu is controlled by backend-derived callback, not legacy admin profile', () => {
  const props = { email: 'test@example.invalid', isAdmin: true, onAccount: vi.fn(), onSavedAreas: vi.fn(), onSignOut: vi.fn() };
  const { rerender } = render(<UserMenu {...props} />); fireEvent.click(screen.getByRole('button', { name: /test@example/ }));
  expect(screen.queryByRole('menuitem', { name: /จัดการข้อมูล GIS/ })).not.toBeInTheDocument();
  const open = vi.fn(); rerender(<UserMenu {...props} onOpenGis={open} />); fireEvent.click(screen.getByRole('menuitem', { name: /จัดการข้อมูล GIS/ })); expect(open).toHaveBeenCalledOnce();
});
test('shows real API page counts and officer actions; hides admin/gated actions', async () => {
  show(); await openDataset(); expect(screen.getByText(/Datasets: 1/)).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'ส่งตรวจสอบ' })).toBeInTheDocument(); expect(screen.queryByText('เจ้าหน้าที่ GIS', { selector: 'h2' })).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'เปิดใช้ฉบับ' })).not.toBeInTheDocument();
});
test('empty/error states never invent counts', async () => {
  gisRequest.mockImplementation(path => path === '/datasets' ? Promise.reject(new GisError(503)) : Promise.resolve(page([])));
  show(); expect(await screen.findByRole('alert')).toHaveTextContent('ยังไม่พร้อม'); expect(screen.getByText(/Datasets: —/)).toBeInTheDocument(); expect(screen.getByText(/Datasets: —/)).toBeInTheDocument();
});
test('filters and opaque pagination are sent to API', async () => {
  gisRequest.mockImplementation((path, options) => path === '/datasets' ? Promise.resolve({ ...page([ds]), has_more: !options.query.cursor, next_cursor: 'opaque-cursor' }) : respond(path, options));
  show(); await screen.findByRole('button', { name: ds.title });
  fireEvent.change(screen.getByLabelText('ปี (ค.ศ.)'), { target: { value: '2025' } }); fireEvent.click(screen.getByText('กรองข้อมูล'));
  await waitFor(() => expect(gisRequest).toHaveBeenCalledWith('/datasets', expect.objectContaining({ query: expect.objectContaining({ data_year: '2025' }) })));
  fireEvent.click(await screen.findByRole('button', { name: 'หน้าถัดไป' }));
  await waitFor(() => expect(gisRequest).toHaveBeenCalledWith('/datasets', expect.objectContaining({ query: expect.objectContaining({ cursor: 'opaque-cursor' }) })));
});
test('create dataset requires review and confirmation and uses actual contract', async () => {
  show(); await screen.findByRole('button', { name: ds.title });
  fireEvent.click(screen.getByRole('button', { name: 'สร้างชุดข้อมูล' }));
  const form = screen.getByRole('dialog'); fireEvent.change(within(form).getByLabelText('ชื่อชุดข้อมูล'), { target: { value: 'ชุดใหม่' } });
  fireEvent.change(within(form).getByLabelText('จังหวัด'), { target: { value: ds.province } });
  fireEvent.click(within(form).getByText('ตรวจทานคำสั่ง')); expect(writes()).toHaveLength(0);
  expect(screen.getByRole('dialog')).toHaveTextContent('ชุดใหม่'); await confirm();
  await waitFor(() => expect(writes()).toHaveLength(1)); expect(writes()[0][1]).toMatchObject({ method: 'POST', body: { province: ds.province, kind: 'ldd_shapefile', purpose: 'landuse', month: 0 } });
});
test('enqueue is confirmed with immutable revision; no optimistic succeeded', async () => {
  show(); await openDataset(); fireEvent.click(screen.getByRole('button', { name: 'ส่งตรวจสอบ', exact: true })); expect(writes()).toHaveLength(0);
  expect(screen.getByRole('dialog')).toHaveTextContent(ed.id); await confirm(); await waitFor(() => expect(writes()).toHaveLength(1));
  expect(writes()[0]).toEqual([`/editions/${ed.id}/validation-jobs`, expect.objectContaining({ body: { expected_revision: 4 } })]);
  expect(screen.queryByText('สำเร็จ', { selector: '.gis-status' })).not.toBeInTheDocument();
});
test('LDD report shows audit details and that a Review Required edition cannot be used yet', async () => {
  const report = { ...lddReport([{ code: 'UNKNOWN_CODE_REVIEW_REQUIRED', count: 1 }], [], false), audit: {
    policy_version: 'ldd-policy-v2', outcome: 'review_required', field_profile: 'ldd-lu-text-v1', declared_area_units: 'm2',
    field_mapping: { main_code: 'LUL1_CODE', lu_code: 'LU_CODE', declared_area: 'Shape_Area' },
    feature_outcomes: { accepted: 2, accepted_with_warnings: 1, review_required: 3, rejected: 0 },
    boundary: { minor: 4, review: 5, fatal: 0, outside_area_m2: 12.5 },
    unknown_samples: [{ value: 'X999', main: 'U', reason: 'LU_CODE_NOT_IN_LEGEND', count: 7, area_m2: 88 }],
    repairs: [{ feature: 9, reason: 'Self-intersection', area_before_m2: 10, area_after_m2: 11, type_before: 'Polygon', type_after: 'MultiPolygon' }], repairs_total: 30 } };
  gisRequest.mockImplementation((path, options) => path === `/jobs/${job.id}` ? Promise.resolve({ ...job, state: 'failed', result: { report } }) : respond(path, options));
  show(); await openJob();
  expect(await screen.findByText(/แปลงที่ผ่าน 2 · ผ่านพร้อมข้อสังเกต 1 · ต้องตรวจสอบ 3 · ไม่ผ่าน 0/)).toBeInTheDocument();
  expect(screen.getByRole('note')).toHaveTextContent('ยังนำเข้าหรือเปิดใช้ไม่ได้');
  expect(screen.getByText('รหัสการใช้ที่ดิน: LU_CODE')).toBeInTheDocument();
  expect(screen.getByText(/เล็กน้อย 4 · ต้องตรวจสอบ 5 · ไม่รับ 0 แปลง · พื้นที่นอกเขต 12.5/)).toBeInTheDocument();
  expect(screen.getByText(/X999 · รหัสหลัก U · LU_CODE_NOT_IN_LEGEND · 7 แปลง · 88/)).toBeInTheDocument();
  expect(screen.getByText(/ทั้งหมด 30 แปลง/)).toBeInTheDocument();
  expect(screen.getByText(/แปลงที่ 9 · Self-intersection · 10 → 11/)).toBeInTheDocument();
});

test('LDD report without audit keeps rendering for results stored earlier', async () => {
  const report = lddReport([], [], true);
  gisRequest.mockImplementation((path, options) => path === `/jobs/${job.id}` ? Promise.resolve({ ...job, state: 'succeeded', result: { report } }) : respond(path, options));
  show(); await openJob();
  expect(await screen.findByText(/จำแนกผล:/)).toBeInTheDocument();
  expect(screen.queryByText(/แปลงที่ผ่าน/)).not.toBeInTheDocument();
});

test('sending an edition whose earlier job failed says no new job was created', async () => {
  gisRequest.mockImplementation((path, options) => options?.method ? Promise.resolve({ ...job, state: 'failed', error_code: 'attempts_exhausted' }) : respond(path, options));
  show(); await openDataset(); fireEvent.click(screen.getByRole('button', { name: 'ส่งตรวจสอบ', exact: true })); await confirm();
  expect(await screen.findByText(/ระบบไม่ได้สร้างงานใหม่/)).toBeInTheDocument();
  expect(screen.queryByText(/Backend ยืนยันบันทึกคำสั่งแล้ว/)).not.toBeInTheDocument();
});
test('ambiguous server failure retains same command and key; double click blocked', async () => {
  let done; gisRequest.mockImplementation((path, options) => options?.method ? new Promise(resolve => { done = resolve; }) : respond(path, options));
  show(); await openDataset(); fireEvent.click(screen.getByRole('button', { name: 'ส่งตรวจสอบ', exact: true })); await confirm(); fireEvent.click(screen.getByRole('button', { name: 'กำลังส่งคำสั่ง…' }));
  expect(writes()).toHaveLength(1); await act(async () => { done({ id: job.id }); }); await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  gisRequest.mockImplementation((path, options) => options?.method ? Promise.reject(new GisError(503)) : respond(path, options));
  switchTab('ชุดข้อมูล'); fireEvent.click(await screen.findByRole('button', { name: 'ส่งตรวจสอบ', exact: true })); await confirm(); await screen.findByRole('button', { name: 'ยืนยันดำเนินการ' });
  await confirm(); await waitFor(() => expect(writes()).toHaveLength(3)); expect(writes()[1][1].key).toBe(writes()[2][1].key); expect(writes()[1][1].body).toEqual(writes()[2][1].body);
});
test.each([403, 409, 422, 429])('rejected mutation %s stays failed and reports actual error', async status => {
  gisRequest.mockImplementation((path, options) => options?.method ? Promise.reject(new GisError(status)) : respond(path, options));
  show(); await openDataset(); fireEvent.click(screen.getByRole('button', { name: 'ส่งตรวจสอบ', exact: true })); await confirm();
  await waitFor(() => expect(screen.getAllByRole('alert')[0]).toHaveTextContent(new GisError(status).message));
  expect(screen.queryByText(/Backend ยืนยันบันทึก/)).not.toBeInTheDocument();
});
test('V1 metadata is preserved but not dispatched to V2 worker', async () => {
  gisRequest.mockImplementation((path, options) => path.endsWith('/editions') && !options.method ? Promise.resolve(page([{ ...ed, manifest: { ...ed.manifest, schema_version: 1 } }])) : respond(path, options));
  show(); await openDataset(); expect(screen.getByText(/Worker Native ปัจจุบัน/)).toBeInTheDocument(); expect(screen.queryByRole('button', { name: 'ส่งตรวจสอบ' })).not.toBeInTheDocument();
});
test('admin actions require both gates; rejection never updates active pointer', async () => {
  gisRequest.mockImplementation((path, options) => path.endsWith('/editions') && !options.method ? Promise.resolve(page([{ ...ed, state: 'validated' }])) : options?.method ? Promise.reject(new GisError(409)) : respond(path, options));
  const view = show(admin); await openDataset(); expect(screen.getByText(/Sandbox Gate/)).toBeInTheDocument(); expect(screen.queryByRole('button', { name: 'เปิดใช้ฉบับ' })).not.toBeInTheDocument();
  view.rerender(<GisManagement access={access({ ...admin, activation_enabled: true })} userId="user" />);
  fireEvent.click(screen.getByText('เปิดใช้ฉบับ')); fireEvent.change(screen.getByLabelText('เหตุผล'), { target: { value: 'ทดสอบ' } }); fireEvent.click(screen.getByText('ตรวจทานคำสั่ง')); await confirm();
  await waitFor(() => expect(writes()).toHaveLength(1)); expect(writes()[0][1].body).toEqual({ edition_id: ed.id, expected_revision: ds.revision, expected_active_edition_id: null, reason: 'ทดสอบ' });
  expect(screen.queryByText(/Backend ยืนยันบันทึก/)).not.toBeInTheDocument();
});
test('retry reads current edition and uses hash/revision, reports safe attempt fields', async () => {
  gisRequest.mockImplementation((path, options) => path.endsWith('/attempts') ? Promise.resolve(page([{ id: 'a', state: 'expired', attempt_no: 1, progress: 0, validation_report: { valid: false, checks: ['bounded_input'], statistics: { mean: 1, secret: 99 }, access_token: 'DO_NOT_RENDER' } }])) : respond(path, options));
  show(); await openJob(); fireEvent.click(await screen.findByText('ขอลองใหม่'));
  fireEvent.change(await screen.findByLabelText('เหตุผล'), { target: { value: 'ทดสอบ Retry' } }); fireEvent.click(screen.getByText('ตรวจทานคำสั่ง')); await confirm();
  await waitFor(() => expect(writes()).toHaveLength(1)); expect(writes()[0][1].body).toEqual({ expected_revision: ed.input_revision, input_hash: ed.input_hash, reason: 'ทดสอบ Retry' });
  expect(screen.queryByText('DO_NOT_RENDER')).not.toBeInTheDocument(); expect(screen.queryByText(/secret:/)).not.toBeInTheDocument(); expect(screen.getByText('Lease หมดอายุ')).toBeInTheDocument();
});
test('officer grant/revoke are admin-only, reasoned and confirmed', async () => {
  gisRequest.mockImplementation((path, options) => path === '/officers' && !options?.method ? Promise.resolve(page([{ user_id: ed.id }])) : respond(path, options));
  show(admin); switchTab('เจ้าหน้าที่ GIS'); fireEvent.click(await screen.findByText('เพิ่มเจ้าหน้าที่')); fireEvent.change(screen.getByLabelText('UUID ผู้ใช้ Local'), { target: { value: ed.id } });
  fireEvent.change(screen.getByLabelText('เหตุผล'), { target: { value: 'ทดสอบสิทธิ์' } }); fireEvent.click(screen.getByText('ตรวจทานคำสั่ง')); expect(writes()).toHaveLength(0); await confirm();
  await waitFor(() => expect(writes()).toHaveLength(1)); expect(writes()[0][1].body).toEqual({ user_id: ed.id, reason: 'ทดสอบสิทธิ์' });
  fireEvent.click(await screen.findByText('ถอนสิทธิ์')); fireEvent.change(screen.getByLabelText('เหตุผล'), { target: { value: 'ถอนสิทธิ์ทดสอบ' } }); fireEvent.click(screen.getByText('ตรวจทานคำสั่ง')); await confirm();
  await waitFor(() => expect(writes()).toHaveLength(2)); expect(writes()[1][0]).toBe(`/officers/${ed.id}/revocation`);
});
test('unmount cancels pending reads without polling', async () => {
  gisRequest.mockImplementation(() => new Promise(() => {})); const view = show(); const signals = gisRequest.mock.calls.map(([, o]) => o.signal); view.unmount(); expect(signals.every(s => s.aborted)).toBe(true);
});

test.each(['ขอย้อนกลับฉบับ', 'ถอนฉบับ'])('admin %s sends revision/pointer and defers rejection to backend', async action => {
  gisRequest.mockImplementation((path, options) => path.endsWith('/editions') && !options?.method ? Promise.resolve(page([{ ...ed, state: 'validated' }])) : options?.method ? Promise.reject(new GisError(409)) : respond(path, options));
  show({ ...admin, activation_enabled: true }); await openDataset(); fireEvent.click(screen.getByRole('button', { name: action }));
  fireEvent.change(screen.getByLabelText('เหตุผล'), { target: { value: 'คำสั่งทดสอบ' } }); fireEvent.click(screen.getByText('ตรวจทานคำสั่ง')); await confirm();
  expect(writes()).toHaveLength(1); const [path, options] = writes()[0];
  expect(path.endsWith(action === 'ถอนฉบับ' ? '/withdrawal' : '/rollback')).toBe(true);
  expect(options.body).toMatchObject({ expected_active_edition_id: null, reason: 'คำสั่งทดสอบ' });
  if (action === 'ถอนฉบับ') expect(options.body).toMatchObject({ expected_revision: ed.input_revision, expected_dataset_revision: ds.revision, replacement_edition_id: null });
  expect(screen.queryByText(/Backend ยืนยันบันทึก/)).not.toBeInTheDocument();
});

test('edition JSON is validated before review and preserves V2 metadata exactly', async () => {
  show(); await openDataset(); fireEvent.click(screen.getByText('ตัวเลือกเพิ่มเติมและข้อมูลทางเทคนิค')); fireEvent.click(screen.getByRole('button', { name: 'สร้าง Edition' }));
  fireEvent.change(screen.getByLabelText('Manifest JSON (Synthetic V1/V2)'), { target: { value: '{bad' } }); fireEvent.click(screen.getByText('ตรวจทานคำสั่ง'));
  expect(screen.getByRole('alert')).toHaveTextContent('JSON ไม่ถูกต้อง'); expect(writes()).toHaveLength(0);
  fireEvent.change(screen.getByLabelText('Manifest JSON (Synthetic V1/V2)'), { target: { value: JSON.stringify(ed.manifest) } }); fireEvent.click(screen.getByText('ตรวจทานคำสั่ง')); await confirm();
  expect(writes()).toHaveLength(1); expect(writes()[0][1].body).toEqual({ manifest: ed.manifest });
});

test('transient access recheck cannot discard an uncertain command or permit a new key', async () => {
  gisRequest.mockImplementation((path, options) => options?.method ? Promise.reject(new GisError(503)) : respond(path, options));
  const view = show(); await openDataset(); fireEvent.click(screen.getByRole('button', { name: 'ส่งตรวจสอบ', exact: true })); await confirm();
  const firstKey = writes()[0][1].key;
  view.rerender(<GisManagement access={{ ...access(null), error: new GisError(503) }} userId="user" />);
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  view.rerender(<GisManagement access={access(officer)} userId="user" />);
  expect(await screen.findByRole('dialog')).toHaveTextContent('ส่งตรวจสอบข้อมูลจำลอง'); await confirm();
  expect(writes()).toHaveLength(2); expect(writes()[1][1].key).toBe(firstKey);
});

test('dataset-centered workflow hides identifiers from headings and keeps validation distinct from active', async () => {
  gisRequest.mockImplementation((path, options) => path.endsWith('/editions') && !options?.method
    ? Promise.resolve(page([{ ...ed, state: 'validated' }])) : respond(path, options));
  show(); await openDataset();
  const detail = screen.getByRole('region', { name: 'ชุดข้อมูลที่เลือก' });
  expect(within(detail).getByRole('list', { name: 'ขั้นตอนจัดการชุดข้อมูล' })).toBeInTheDocument();
  expect(within(detail).getByText('ยังไม่เปิดใช้ข้อมูล')).toBeInTheDocument();
  expect(within(detail).getByText(/ตรวจผ่านแล้ว — ดูรายงาน/)).toBeInTheDocument();
  expect(screen.queryByRole('heading', { name: ed.id })).not.toBeInTheDocument();
  expect(screen.getByText('ข้อมูลทางเทคนิคของฉบับ')).toBeInTheDocument();
  expect(screen.getByRole('tab', { name: 'ชุดข้อมูล' })).toHaveAttribute('aria-selected','true');
});

test('edition action scopes jobs to its selected dataset and edition', async () => {
  show(); await openDataset();
  fireEvent.click(screen.getByRole('button', { name: 'งานและรายงานฉบับนี้' }));
  expect(screen.getByRole('tab', { name: 'งานและรายงาน' })).toHaveAttribute('aria-selected','true');
  await waitFor(() => expect(gisRequest).toHaveBeenCalledWith('/jobs', expect.objectContaining({
    query: expect.objectContaining({ dataset_id: ds.id, edition_id: ed.id }) })));
  fireEvent.click(await screen.findByRole('button', { name: 'ดูงานตรวจสอบ 1' }));
  expect(await screen.findByText(`ชุดข้อมูล: ${ds.title}`)).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'กลับชุดข้อมูลที่เลือก' }));
  expect(screen.getByRole('region', { name: 'ชุดข้อมูลที่เลือก' })).toBeVisible();
});

test('edition history opens inside its own edition card', async () => {
  show(); await openDataset();
  const card = document.querySelector(`[data-edition-id="${ed.id}"]`);
  fireEvent.click(within(card).getByRole('button', { name: 'ดูประวัติ' }));
  expect(await within(card).findByRole('heading', { name: 'ประวัติฉบับที่เลือก' })).toBeInTheDocument();
  expect(gisRequest).toHaveBeenCalledWith(`/editions/${ed.id}/history`, expect.anything());
  fireEvent.click(within(card).getByRole('button', { name: 'ปิดประวัติ' }));
  expect(within(card).queryByRole('heading', { name: 'ประวัติฉบับที่เลือก' })).not.toBeInTheDocument();
});

test('creating a dataset opens the actual server-confirmed dataset', async () => {
  gisRequest.mockImplementation((path, options) => path === '/datasets' && options?.method
    ? Promise.resolve(ds) : respond(path, options));
  show(); fireEvent.click(await screen.findByRole('button', { name: 'สร้างชุดข้อมูล' }));
  fireEvent.change(screen.getByLabelText('ชื่อชุดข้อมูล'), { target: { value: ds.title } });
  fireEvent.change(screen.getByRole('dialog').querySelector('select[name="province"]'), { target: { value: ds.province } });
  fireEvent.click(screen.getByRole('button', { name: 'ตรวจทานคำสั่ง' })); await confirm();
  expect(await screen.findByRole('region', { name: 'ชุดข้อมูลที่เลือก' })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: ds.title })).toHaveAttribute('aria-pressed','true');
});

test('section tabs support keyboard navigation and never expose admin controls to officers', async () => {
  show({ ...officer, processing_enabled: true });
  const tab = screen.getByRole('tab', { name: 'ชุดข้อมูล' }); tab.focus();
  fireEvent.keyDown(tab, { key: 'ArrowRight' });
  expect(screen.getByRole('tab', { name: 'งานและรายงาน' })).toHaveAttribute('aria-selected','true');
  fireEvent.keyDown(document.activeElement, { key: 'End' });
  expect(screen.getByRole('tab', { name: 'ประมวลผล NDVI/LST' })).toHaveAttribute('aria-selected','true');
  expect(screen.queryByRole('tab', { name: 'เจ้าหน้าที่ GIS' })).not.toBeInTheDocument();
});
