// Local integration runner, not application code. Bootstrap remains on stdin.
const { createRequire } = require('node:module');
const readline = require('node:readline');
const fs = require('node:fs');
const path = require('node:path');
const bundled = createRequire(path.join(process.env.GIS_TEST_NODE_MODULES, '_resolver.cjs'));
const { chromium } = bundled('playwright');
let step = 'bootstrap';
const rows = [];
function check(name, ok) { rows.push({ name, status: ok ? 'Pass' : 'Fail' }); if (!ok) throw new Error('ASSERTION'); }
async function main(data) {
  const browser = await chromium.launch({ channel: 'chrome', headless: true, args: ['--disable-background-networking'] });
  const contexts = [];
  let currentPage;
  const traffic = [];
  async function pageFor(user) {
    const context = await browser.newContext({ viewport: { width: 1366, height: 900 }, reducedMotion: 'reduce' }); contexts.push(context);
    await context.route('**/*', route => {
      const u = new URL(route.request().url());
      return ['http://127.0.0.1:3000', 'http://127.0.0.1:55421', 'http://127.0.0.1:55422'].includes(u.origin) ? route.continue() : route.abort();
    });
    const page = await context.newPage(); currentPage = page; page.setDefaultTimeout(45000);
    page.on('response', r => { if (r.url().startsWith('http://127.0.0.1:55422/gis/')) traffic.push({ method: r.request().method(), path: new URL(r.url()).pathname, status: r.status() }); });
    await page.goto('http://127.0.0.1:3000/?view=gis');
    await page.getByRole('heading', { name: 'เข้าสู่ระบบ', exact: true }).waitFor();
    check(user.name + '_existing_login_flow', true);
    await page.getByLabel('อีเมล', { exact: true }).fill(user.email);
    await page.getByLabel('รหัสผ่าน', { exact: true }).fill(user.password);
    await page.getByRole('button', { name: 'เข้าสู่ระบบ →', exact: true }).click();
    await page.getByRole('heading', { name: 'จัดการข้อมูล GIS', exact: true }).waitFor();
    return page;
  }
  async function reviewAndConfirm(page) {
    await page.getByRole('button', { name: 'ตรวจทานคำสั่ง', exact: true }).click();
    await page.getByRole('dialog', { name: 'ยืนยันคำสั่ง', exact: true }).waitFor();
    await page.getByRole('button', { name: 'ยืนยันดำเนินการ', exact: true }).click();
    await page.getByRole('dialog').waitFor({ state: 'hidden' });
  }
  try {
    step = 'normal-user'; const normal = await pageFor(data.users.normal);
    await normal.getByText('ไม่มีสิทธิ์จัดการข้อมูล GIS กรุณาติดต่อผู้ดูแลระบบ').waitFor();
    check('normal_user_denied_by_real_me', await normal.getByRole('button', { name: 'สร้าง Dataset', exact: true }).count() === 0);
    step = 'admin-grant'; const admin = await pageFor(data.users.admin);
    await admin.getByRole('heading', { name: 'เจ้าหน้าที่ GIS', exact: true }).waitFor();
    check('admin_officers_visible', true);
    await admin.getByRole('button', { name: 'เพิ่มเจ้าหน้าที่', exact: true }).click();
    await admin.getByLabel('UUID ผู้ใช้ Local').fill(data.users.officer.id);
    await admin.getByLabel('เหตุผล', { exact: true }).fill('T4 local synthetic UI acceptance');
    await reviewAndConfirm(admin);
    check('admin_grant_real_api', traffic.some(r => r.path === '/gis/officers' && r.method === 'POST' && r.status === 200));
    step = 'officer-create'; const officer = await pageFor(data.users.officer);
    await officer.getByRole('button', { name: 'สร้าง Dataset', exact: true }).waitFor();
    check('officer_no_admin_actions', await officer.getByRole('button', { name: 'เพิ่มเจ้าหน้าที่', exact: true }).count() === 0);
    step = 'dataset-open-form';
    await officer.getByRole('button', { name: 'สร้าง Dataset', exact: true }).click();
    step = 'dataset-fill-title';
    await officer.getByLabel('ชื่อ Dataset', { exact: true }).fill(data.title);
    step = 'dataset-fill-province';
    await officer.getByRole('dialog').getByLabel('จังหวัด', { exact: true }).selectOption(data.province);
    step = 'dataset-fill-year';
    await officer.getByRole('dialog').getByLabel('ปีข้อมูล (ค.ศ.)').fill(String(data.year));
    step = 'dataset-review-confirm';
    await reviewAndConfirm(officer);
    step = 'dataset-filter';
    await officer.getByLabel('ปี (ค.ศ.)', { exact: true }).fill(String(data.year));
    await officer.getByRole('button', { name: 'กรองข้อมูล', exact: true }).click();
    await officer.getByRole('button', { name: data.title, exact: true }).click();
    await officer.getByRole('button', { name: 'สร้าง Edition', exact: true }).waitFor();
    check('dataset_created_read_back_real_api', true);
    step = 'edition-create'; await officer.getByRole('button', { name: 'สร้าง Edition', exact: true }).click();
    await officer.getByLabel('Manifest JSON (Synthetic V1/V2)').fill(JSON.stringify(data.manifest));
    await reviewAndConfirm(officer);
    await officer.getByRole('button', { name: 'ส่งตรวจสอบ', exact: true }).waitFor();
    check('edition_created_v2_real_manifest', true);
    step = 'validate'; await officer.getByRole('button', { name: 'ส่งตรวจสอบ', exact: true }).click();
    const response = officer.waitForResponse(r => r.url().includes('/validation-jobs') && r.request().method() === 'POST');
    await officer.getByRole('button', { name: 'ยืนยันดำเนินการ', exact: true }).click();
    const enqueued = await response; check('validation_enqueue_accepted', enqueued.status() === 202);
    const queued = await enqueued.json();
    await officer.getByRole('dialog').waitFor({ state: 'hidden' });
    await officer.getByRole('button', { name: queued.id, exact: true }).click();
    step = 'worker-result';
    for (let n = 0; n < 12; n++) {
      const succeeded = officer.locator('.gis-card').filter({ has: officer.getByRole('heading', { name: 'รายละเอียดงาน ' + queued.id, exact: true }) });
      if (await succeeded.getByText('สำเร็จ', { exact: true }).count()) break;
      await officer.waitForTimeout(2000);
      await officer.getByRole('button', { name: 'รีเฟรชรายละเอียดงาน', exact: true }).click();
      await officer.getByText('จำนวนครั้ง:', { exact: false }).waitFor();
    }
    await officer.getByText('ผล: ผ่าน', { exact: false }).first().waitFor();
    check('ui_queue_linux_worker_native_result', true);
    check('no_automatic_activation', await officer.getByText('ฉบับที่ใช้งาน: ยังไม่มี', { exact: true }).count() === 1);
    step = 'desktop-tablet';
    await officer.screenshot({ path: path.join(data.output, 'gis-desktop.png'), fullPage: true });
    check('desktop_no_document_overflow', await officer.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    await officer.setViewportSize({ width: 768, height: 1024 });
    await officer.screenshot({ path: path.join(data.output, 'gis-tablet.png'), fullPage: true });
    check('tablet_no_document_overflow', await officer.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    step = 'live-conflict';
    await officer.getByRole('button', { name: 'แก้ชื่อ', exact: true }).click();
    await officer.getByLabel('ชื่อ Dataset', { exact: true }).fill(data.title + ' stale');
    await officer.getByRole('button', { name: 'ตรวจทานคำสั่ง', exact: true }).click();
    const d = await officer.evaluate(async ({ year, province, title }) => {
      const { gisRequest } = await import('/src/utils/gisClient.js');
      const rows = await gisRequest('/datasets', { query: { data_year: year, province } });
      const item = rows.data.find(d => d.title === title);
      await gisRequest('/datasets/' + item.id, { method: 'PATCH', key: crypto.randomUUID(), body: { title: title + ' concurrent', expected_revision: item.revision } });
      return item.id;
    }, { year: data.year, province: data.province, title: data.title });
    const conflict = officer.waitForResponse(r => r.url().endsWith('/gis/datasets/' + d) && r.request().method() === 'PATCH');
    await officer.getByRole('button', { name: 'ยืนยันดำเนินการ', exact: true }).click();
    check('real_revision_conflict_409', (await conflict).status() === 409);
    await officer.getByRole('alert').filter({ hasText: 'ข้อมูลหรือสถานะเปลี่ยนแล้ว' }).waitFor();
    step = 'admin-revoke';
    await admin.getByRole('button', { name: 'โหลดข้อมูลและสิทธิ์ล่าสุด', exact: true }).click();
    let row = admin.locator('li').filter({ hasText: data.users.officer.id });
    for (let n = 0; n < 5 && !await row.count(); n++) {
      const section = admin.locator('.gis-card').filter({ has: admin.getByRole('heading', { name: 'เจ้าหน้าที่ GIS', exact: true }) });
      const next = section.getByRole('button', { name: 'หน้าถัดไป', exact: true }); if (!await next.count()) break;
      await next.click(); await admin.waitForTimeout(1000);
    }
    await row.getByRole('button', { name: 'ถอนสิทธิ์', exact: true }).click();
    await admin.getByLabel('เหตุผล', { exact: true }).fill('T4 local smoke complete'); await reviewAndConfirm(admin);
    await officer.getByRole('button', { name: 'โหลดข้อมูลและสิทธิ์ล่าสุด', exact: true }).click();
    await officer.getByText('ไม่มีสิทธิ์จัดการข้อมูล GIS กรุณาติดต่อผู้ดูแลระบบ').waitFor();
    check('revoked_officer_loses_ui_access_real_backend', true);
  } catch (error) {
    // Creation/review failures contain only synthetic catalog labels. Never
    // serialize login errors, request headers, sessions or raw browser traces.
    rows.push({ name: step, status: 'Fail', ...(/^dataset-|^edition-|^worker-|^desktop-|^live-conflict/.test(step)
      ? { diagnostic: String(error.message).split('Call log:')[0].slice(0, 1000) } : {}) });
    if (currentPage) {
      await currentPage.evaluate(() => { document.querySelectorAll('input[type=password]').forEach(input => { input.value = ''; }); }).catch(() => {});
      await currentPage.screenshot({ path: path.join(data.output, 'failure.png'), fullPage: true }).catch(() => {});
    }
  }
  finally { for (const c of contexts) await c.close(); await browser.close(); }
  fs.writeFileSync(path.join(data.output, 'browser-results.json'), JSON.stringify({ local_only: true, mocked_api: false, rows, traffic }, null, 2));
  console.log(JSON.stringify({ rows }));
  if (rows.some(r => r.status !== 'Pass')) process.exitCode = 1;
}
readline.createInterface({ input: process.stdin }).once('line', line => main(JSON.parse(line)).catch(() => { console.log(JSON.stringify({ code: 'LOCAL_BROWSER_SETUP_FAILED', step })); process.exitCode = 1; }));
