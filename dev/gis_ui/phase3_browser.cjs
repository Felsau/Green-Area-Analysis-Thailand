// Actual loopback UI/Auth/API/queue/worker checks; no mock HTTP or stored sessions.
const { createRequire } = require('node:module');
const readline = require('node:readline');
const fs = require('node:fs');
const path = require('node:path');
const bundled = createRequire(path.join(process.env.GIS_TEST_NODE_MODULES, '_resolver.cjs'));
const { chromium } = bundled('playwright');
const rows = [], traffic = [];
let step = 'setup';
function check(name, ok) { rows.push({ name, status: ok ? 'Pass' : 'Fail' }); if (!ok) throw new Error('ASSERTION'); }

async function main(data) {
  const browser = await chromium.launch({ channel: 'chrome', headless: true, args: ['--disable-background-networking'] });
  const contexts = [];
  let current;
  async function login(user) {
    const context = await browser.newContext({ viewport: { width: 1366, height: 1000 }, reducedMotion: 'reduce' });
    contexts.push(context);
    await context.route('**/*', route => {
      const origin = new URL(route.request().url()).origin;
      return ['http://127.0.0.1:3000','http://127.0.0.1:55421','http://127.0.0.1:55422'].includes(origin) ? route.continue() : route.abort();
    });
    const page = await context.newPage(); current = page; page.setDefaultTimeout(60000);
    page.on('response', r => { if (r.url().startsWith('http://127.0.0.1:55422/gis/')) traffic.push({ method: r.request().method(), path: new URL(r.url()).pathname, status: r.status() }); });
    page.on('requestfailed', r => { if (r.url().startsWith('http://127.0.0.1:55422/gis/')) traffic.push({ method: r.method(), path: new URL(r.url()).pathname, failed: r.failure()?.errorText }); });
    await page.goto('http://127.0.0.1:3000/?view=gis');
    await page.getByLabel('อีเมล', { exact: true }).fill(user.email);
    await page.getByLabel('รหัสผ่าน', { exact: true }).fill(user.password);
    await page.getByRole('button', { name: 'เข้าสู่ระบบ →', exact: true }).click();
    await page.getByRole('heading', { name: 'จัดการข้อมูล GIS', exact: true }).waitFor();
    return page;
  }
  async function confirmForm(page) {
    await page.getByRole('button', { name: 'ตรวจทานคำสั่ง', exact: true }).click();
    await page.getByRole('button', { name: 'ยืนยันดำเนินการ', exact: true }).click();
    await page.getByRole('dialog').waitFor({ state: 'hidden' });
  }
  async function runProcessing(page, metric, month, district, scenario) {
    await page.getByRole('button', { name: 'สร้างงานประมวลผล NDVI/LST', exact: true }).click();
    await page.getByLabel('ดัชนีประมวลผล').selectOption(metric);
    await page.getByLabel('จังหวัดประมวลผล').selectOption(data.province);
    if (district) {
      await page.getByLabel('ระดับพื้นที่').selectOption('district');
      await page.getByLabel('อำเภอประมวลผล').selectOption(data.district);
    }
    await page.getByLabel('ปีประมวลผล (ค.ศ.)').fill(String(data.year));
    await page.getByLabel('ช่วงเวลาประมวลผล').selectOption(String(month));
    await page.getByLabel('ชุดข้อมูลจำลอง').selectOption(scenario);
    const before = traffic.filter(x => x.method === 'POST' && x.path === '/gis/processing-jobs').length;
    await page.getByRole('button', { name: 'ตรวจทานคำสั่ง', exact: true }).click();
    check(metric + '_' + scenario + '_confirmation_offline', (await page.getByRole('dialog').innerText()).includes('offline_synthetic'));
    const response = page.waitForResponse(r => new URL(r.url()).pathname === '/gis/processing-jobs' && r.request().method() === 'POST');
    const refreshed = Promise.all(['/gis/me', '/gis/processing-jobs'].map(pathname =>
      page.waitForResponse(r => new URL(r.url()).pathname === pathname && r.request().method() === 'GET' && r.status() === 200)));
    await page.getByRole('button', { name: 'ยืนยันดำเนินการ', exact: true }).evaluate(button => { button.click(); button.click(); });
    const result = await response;
    check(metric + '_' + scenario + '_job_accepted', result.status() === 202);
    const job = await result.json();
    check(metric + '_' + scenario + '_mode_metadata', job.mode === 'offline_synthetic' && job.metadata.metric === metric && job.metadata.month === month && job.metadata.district === (district ? data.district : null));
    await page.getByRole('dialog').waitFor({ state: 'hidden' });
    await refreshed;
    check(metric + '_' + scenario + '_double_submit_one_request', traffic.filter(x => x.method === 'POST' && x.path === '/gis/processing-jobs').length === before + 1);
    const detailLoaded = () => Promise.all(['', '/attempts', '/history'].map(suffix =>
      page.waitForResponse(r => new URL(r.url()).pathname === '/gis/processing-jobs/' + job.id + suffix && r.status() === 200)));
    const firstDetail = detailLoaded();
    await page.getByRole('button', { name: 'ดูงานประมวลผล ' + job.id, exact: true }).click();
    await firstDetail;
    const detail = page.locator('.gis-card').filter({ has: page.getByRole('heading', { name: 'รายละเอียดงานประมวลผล ' + job.id, exact: true }) }).last();
    for (let n = 0; n < 15; n++) {
      if (await detail.getByText('Candidate / Offline Synthetic', { exact: true }).count()) break;
      await page.waitForTimeout(1000);
      const loaded = detailLoaded();
      await detail.getByRole('button', { name: 'รีเฟรชงานประมวลผล', exact: true }).click();
      await loaded;
    }
    await detail.getByText('Candidate / Offline Synthetic', { exact: true }).first().waitFor();
    if (scenario === 'no_data') {
      await detail.getByText('ไม่มีพิกเซลที่ใช้ได้ จึงไม่มี Candidate Result', { exact: true }).first().waitFor();
      check('browser_no_data_not_zero_candidate', await detail.getByText('mean: ไม่มีข้อมูล', { exact: true }).count() > 0);
    } else {
      await detail.getByText('ผลประมวลผล: มีผลรอตรวจทาน', { exact: true }).first().waitFor();
      check(metric + '_candidate_scientific_mean', await detail.getByText('mean: ' + (metric === 'ndvi' ? '0.4921' : '29.66'), { exact: true }).count() > 0);
    }
    check(metric + '_' + scenario + '_synthetic_never_live', await detail.getByText('ข้อมูลจำลองเท่านั้น ไม่ใช่ผล GEE หรือค่าของจังหวัด/อำเภอจริง ไม่มีการ Publish หรือเปลี่ยน Cache', { exact: true }).count() > 0);
    return job;
  }
  try {
    step = 'normal-login'; const normal = await login(data.users.normal);
    await normal.getByText('ไม่มีสิทธิ์จัดการข้อมูล GIS กรุณาติดต่อผู้ดูแลระบบ').waitFor();
    check('normal_user_cannot_process', await normal.getByRole('button', { name: 'สร้างงานประมวลผล NDVI/LST', exact: true }).count() === 0);
    step = 'admin-grant'; const admin = await login(data.users.admin);
    await admin.getByRole('button', { name: 'เพิ่มเจ้าหน้าที่', exact: true }).click();
    await admin.getByLabel('UUID ผู้ใช้ Local').fill(data.users.officer.id);
    await admin.getByLabel('เหตุผล', { exact: true }).fill('Phase3 synthetic browser test');
    await confirmForm(admin);
    step = 'officer-login'; const officer = await login(data.users.officer);
    await officer.getByRole('heading', { name: 'ประมวลผล NDVI/LST', exact: true }).waitFor();
    check('live_gee_disabled_label', await officer.getByText('Live GEE ยังไม่ได้รับอนุมัติ', { exact: false }).count() > 0);
    step = 'ndvi-annual'; await runProcessing(officer, 'ndvi', 0, false, 'standard');
    step = 'lst-monthly-district'; await runProcessing(officer, 'lst', 2, true, 'standard');
    step = 'ndvi-no-data'; await runProcessing(officer, 'ndvi', 3, false, 'no_data');
    step = 'negative-mode-scope';
    const denied = await officer.evaluate(async data => {
      const { gisRequest } = await import('/src/utils/gisClient.js');
      const body = { province: data.province, district: null, metric: 'ndvi', data_year: data.year, month: 0, mode: 'offline_synthetic', scenario: 'standard', expected_revision: 1 };
      const statuses = [];
      for (const change of [{ mode: 'gee_live' }, { district: 'NOT_AN_EXISTING_DISTRICT' }]) {
        try { await gisRequest('/processing-jobs', { method: 'POST', key: crypto.randomUUID(), body: { ...body, ...change } }); statuses.push(200); }
        catch (error) { statuses.push(error.status); }
      }
      return statuses;
    }, { province: data.province, year: data.year });
    check('browser_live_and_invalid_district_denied', denied.every(status => status === 422));
    step = 'responsive';
    await officer.screenshot({ path: path.join(data.output, 'processing-desktop.png'), fullPage: true });
    check('desktop_no_overflow', await officer.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    await officer.setViewportSize({ width: 768, height: 1024 });
    await officer.screenshot({ path: path.join(data.output, 'processing-tablet.png'), fullPage: true });
    check('tablet_no_overflow', await officer.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  } catch (error) {
    rows.push({ name: step, status: 'Fail', ...(!step.includes('login') && step !== 'admin-grant'
      ? { diagnostic: String(error.message).split('Call log:')[0].slice(0, 1000) } : {}) });
    if (current) {
      await current.evaluate(() => { document.querySelectorAll('input[type=password]').forEach(input => { input.value = ''; }); }).catch(() => {});
      await current.screenshot({ path: path.join(data.output, 'failure.png'), fullPage: true }).catch(() => {});
    }
  } finally { for (const context of contexts) await context.close(); await browser.close(); }
  fs.writeFileSync(path.join(data.output, 'browser-results.json'), JSON.stringify({ local_only: true, mocked_api: false, rows, traffic }, null, 2));
  console.log(JSON.stringify({ rows }));
  if (rows.some(x => x.status !== 'Pass')) process.exitCode = 1;
}
readline.createInterface({ input: process.stdin }).once('line', line => main(JSON.parse(line)).catch(() => { console.log(JSON.stringify({ code: 'PHASE3_BROWSER_SETUP_FAILED', step })); process.exitCode = 1; }));
