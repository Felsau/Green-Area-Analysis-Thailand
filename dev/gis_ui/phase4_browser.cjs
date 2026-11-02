// Actual loopback Auth/UI/API/private immutable storage/queue/Linux worker.
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
    await context.route('**/*', route => ['http://127.0.0.1:3000','http://127.0.0.1:55421','http://127.0.0.1:55422']
      .includes(new URL(route.request().url()).origin) ? route.continue() : route.abort());
    const page = await context.newPage(); current = page; page.setDefaultTimeout(60000);
    page.on('response', r => { if (r.url().startsWith('http://127.0.0.1:55422/gis/')) traffic.push({ method: r.request().method(), path: new URL(r.url()).pathname, status: r.status() }); });
    await page.goto('http://127.0.0.1:3000/?view=gis');
    await page.getByLabel('อีเมล', { exact: true }).fill(user.email);
    await page.getByLabel('รหัสผ่าน', { exact: true }).fill(user.password);
    await page.getByRole('button', { name: 'เข้าสู่ระบบ →', exact: true }).click();
    await page.getByRole('heading', { name: 'จัดการข้อมูล GIS', exact: true }).waitFor();
    return page;
  }
  async function confirm(page, verb, pathname) {
    const response = page.waitForResponse(r => new URL(r.url()).pathname === pathname && r.request().method() === verb);
    const refreshed = page.waitForResponse(r => new URL(r.url()).pathname === '/gis/me' && r.status() === 200);
    response.catch(() => {}); refreshed.catch(() => {});
    await page.getByRole('button', { name: 'ยืนยันดำเนินการ', exact: true }).evaluate(button => { button.click(); button.click(); });
    const result = await response;
    check('command_' + pathname.split('/').at(-1) + '_accepted', [200,201,202].includes(result.status()));
    await page.getByRole('dialog').waitFor({ state: 'hidden' });
    await refreshed;
    return result.status();
  }
  async function uploadAndValidate(page, dataset, filename, profile, valid, expectedMean) {
    await page.getByRole('button', { name: dataset.title, exact: true }).click();
    await page.getByRole('heading', { name: 'รายละเอียด Dataset', exact: true }).waitFor();
    await page.getByRole('button', { name: 'อัปโหลด GeoTIFF', exact: true }).click();
    await page.getByLabel('ไฟล์ GeoTIFF').setInputFiles(path.join(data.fixture_root, filename));
    await page.getByLabel('Scientific Profile').selectOption(profile);
    await page.getByRole('button', { name: 'ตรวจทานคำสั่ง', exact: true }).click();
    check(filename + '_confirmation_profile', (await page.getByRole('dialog').innerText()).includes(profile));
    const before = traffic.filter(x => x.method === 'POST' && x.path.endsWith('/geotiff-uploads')).length;
    await confirm(page, 'POST', '/gis/datasets/' + dataset.id + '/geotiff-uploads');
    // Verify persisted metadata via a real authorized read. CDP may evict a
    // completed POST body after React refreshes; do not depend on that cache.
    const expectedSha = require('node:crypto').createHash('sha256').update(fs.readFileSync(path.join(data.fixture_root, filename))).digest('hex');
    const upload = await page.evaluate(async ({ id, sha, profile }) => {
      const { gisRequest } = await import('/src/utils/gisClient.js');
      const editions = await gisRequest('/datasets/' + id + '/editions', { query: { limit: 100 } });
      return editions.data.find(e => e.upload?.sha256 === sha && e.manifest?.profile === profile)?.upload;
    }, { id: dataset.id, sha: expectedSha, profile });
    check(filename + '_upload_sha_and_test_mode', /^[a-f0-9]{64}$/.test(upload.sha256) && upload.mode === 'local_test');
    check(filename + '_double_submit_one_upload', traffic.filter(x => x.method === 'POST' && x.path.endsWith('/geotiff-uploads')).length === before + 1);
    // Wait for the refreshed edition listing before interacting with it.
    const edition = page.locator('.gis-edition').filter({ has: page.getByRole('heading', { name: upload.edition_id, exact: true }) });
    await edition.getByText('GeoTIFF Local/Test — ผลตรวจผ่านไม่ได้เปิดใช้งานหรือแทนที่ Cache', { exact: true }).waitFor();
    check(filename + '_immutable_no_edit_clone', await edition.getByRole('button', { name: 'แก้ Manifest', exact: true }).count() === 0
      && await edition.getByRole('button', { name: 'สำเนาฉบับ', exact: true }).count() === 0);
    await edition.getByRole('button', { name: 'ส่งตรวจสอบ', exact: true }).click();
    await confirm(page, 'POST', '/gis/editions/' + upload.edition_id + '/validation-jobs');
    const job = await page.evaluate(async id => {
      const { gisRequest } = await import('/src/utils/gisClient.js');
      return (await gisRequest('/jobs', { query: { edition_id: id } })).data[0];
    }, upload.edition_id);
    const jobRow = page.getByRole('button', { name: job.id, exact: true });
    for (let pageNo = 0; pageNo < 20 && !await jobRow.count(); pageNo++) {
      const jobsPanel = page.locator('section.gis-card').filter({ has: page.getByRole('heading', { name: 'งานตรวจสอบข้อมูล GIS', exact: true }) });
      const loaded = page.waitForResponse(r => new URL(r.url()).pathname === '/gis/jobs' && r.status() === 200);
      await jobsPanel.getByRole('button', { name: 'หน้าถัดไป', exact: true }).click(); await loaded;
    }
    const loadedDetail = () => {
      const promise = Promise.all(['', '/attempts'].map(suffix => page.waitForResponse(r => new URL(r.url()).pathname === '/gis/jobs/' + job.id + suffix && r.status() === 200)));
      promise.catch(() => {}); return promise;
    };
    const first = loadedDetail(); await jobRow.click(); await first;
    const detail = page.locator('section.gis-card').filter({ has: page.getByRole('heading', { name: 'รายละเอียดงาน ' + job.id, exact: true }) });
    for (let n = 0; n < 15 && !await detail.getByText('รายงาน GeoTIFF — Local/Test', { exact: true }).count(); n++) {
      await page.waitForTimeout(1000); const loaded = loadedDetail();
      await detail.getByRole('button', { name: 'รีเฟรชรายละเอียดงาน', exact: true }).click(); await loaded;
    }
    await detail.getByText('รายงาน GeoTIFF — Local/Test', { exact: true }).first().waitFor();
    check(filename + '_native_outcome', (await detail.innerText()).includes('ผล Validation: ' + (valid ? 'ผ่าน' : 'ไม่ผ่าน')));
    if (valid) {
      check(filename + '_metadata_rendered', (await detail.innerText()).includes('float32') && (await detail.innerText()).includes('EPSG:32647'));
      const values = await detail.innerText();
      const found = [...values.matchAll(/mean: ([\d.\-]+)/g)].map(m => Number(m[1]));
      check(filename + '_scientific_result', found.some(x => Math.abs(x - expectedMean) < 0.00002));
    } else check(filename + '_readable_invalid_range', (await detail.innerText()).includes('ค่าพิกเซลไม่อยู่ในช่วงของ Profile'));
    check(filename + '_no_activation', await page.getByRole('button', { name: 'เปิดใช้ฉบับ', exact: true }).count() === 0);
    return detail;
  }
  try {
    step = 'normal-login'; const normal = await login(data.users.normal);
    await normal.getByText('ไม่มีสิทธิ์จัดการข้อมูล GIS กรุณาติดต่อผู้ดูแลระบบ').waitFor();
    check('normal_user_denied', await normal.getByRole('button', { name: 'อัปโหลด GeoTIFF', exact: true }).count() === 0);
    step = 'admin-grant'; const admin = await login(data.users.admin);
    await admin.getByRole('button', { name: 'เพิ่มเจ้าหน้าที่', exact: true }).click();
    await admin.getByLabel('UUID ผู้ใช้ Local').fill(data.users.officer.id);
    await admin.getByLabel('เหตุผล', { exact: true }).fill('Phase4 local synthetic browser test');
    await admin.getByRole('button', { name: 'ตรวจทานคำสั่ง', exact: true }).click();
    await confirm(admin, 'POST', '/gis/officers');
    step = 'officer-login'; const officer = await login(data.users.officer);
    const datasets = await officer.evaluate(async data => {
      const { gisRequest } = await import('/src/utils/gisClient.js'); const result = {};
      for (const metric of ['ndvi','lst']) result[metric] = await gisRequest('/datasets', { method: 'POST', key: crypto.randomUUID(),
        body: { province: data.province, data_year: data.year, month: 0, kind: 'geotiff', purpose: metric, title: 'GeoTIFF Browser ' + metric + ' ' + data.run } });
      return result;
    }, { province: data.province, year: data.year, run: data.run });
    await officer.getByLabel('ปี (ค.ศ.)', { exact: true }).fill(String(data.year));
    await officer.getByRole('button', { name: 'กรองข้อมูล', exact: true }).click();
    step = 'ndvi-valid'; await uploadAndValidate(officer, datasets.ndvi, 'ndvi_valid.tif', 'ndvi_ready', true, 0);
    step = 'lst-kelvin-valid'; await uploadAndValidate(officer, datasets.lst, 'lst_kelvin_valid.tif', 'lst_kelvin_ready', true, 30);
    step = 'ndvi-invalid'; const detail = await uploadAndValidate(officer, datasets.ndvi, 'ndvi_range.tif', 'ndvi_ready', false, null);
    step = 'responsive'; await detail.scrollIntoViewIfNeeded();
    await officer.screenshot({ path: path.join(data.output,'geotiff-desktop.png'),fullPage:true });
    check('desktop_no_overflow', await officer.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    await officer.setViewportSize({ width: 768, height: 1024 });
    await officer.screenshot({ path: path.join(data.output,'geotiff-tablet.png'),fullPage:true });
    check('tablet_no_overflow', await officer.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  } catch (error) {
    rows.push({ name:step,status:'Fail', ...(!step.includes('login') && step !== 'admin-grant' ? {diagnostic:String(error.message).split('Call log:')[0].slice(0,1000)}:{}) });
    if(current && !step.includes('login')) await current.screenshot({path:path.join(data.output,'failure.png'),fullPage:true}).catch(()=>{});
  } finally { for(const context of contexts) await context.close().catch(()=>{}); await browser.close().catch(()=>{}); }
  fs.writeFileSync(path.join(data.output,'browser-results.json'),JSON.stringify({local_only:true,mocked_api:false,rows,traffic},null,2));
  console.log(JSON.stringify({rows})); if(rows.some(x=>x.status!=='Pass')) process.exitCode=1;
}
readline.createInterface({input:process.stdin}).once('line',line=>main(JSON.parse(line)).catch(()=>{console.log(JSON.stringify({code:'PHASE4_BROWSER_SETUP_FAILED',step}));process.exitCode=1;}));
