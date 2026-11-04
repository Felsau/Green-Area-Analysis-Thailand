// Real Local admin activation -> Dashboard bytes -> corruption rejection.
const {createRequire}=require('node:module');
const fs=require('node:fs'),path=require('node:path'),readline=require('node:readline');
const {chromium}=createRequire(path.join(process.env.GIS_TEST_NODE_MODULES,'_resolver.cjs'))('playwright');
async function main(data){
 const rows=[];let context,page,step='login';const errors=[];const check=(name,value)=>{rows.push({name,status:value?'Pass':'Fail'});if(!value)throw Error('ASSERTION');};
 const browser=await chromium.launch({channel:'chrome',headless:true,args:['--disable-background-networking','--enable-unsafe-swiftshader','--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE localhost, EXCLUDE 127.0.0.1']});
 try{
  context=await browser.newContext({viewport:{width:1440,height:1000},reducedMotion:'reduce'});page=await context.newPage();page.setDefaultTimeout(120000);page.on('pageerror',e=>errors.push(String(e.message).split('\n')[0].slice(0,200)));
  const cdp=await context.newCDPSession(page);await cdp.send('Network.enable');await cdp.send('Network.setBlockedURLs',{urls:['https://*']});
  await page.goto('http://127.0.0.1:3000/?view=gis');const consent=page.getByRole('button',{name:'ใช้เฉพาะที่จำเป็น',exact:true});if(await consent.count())await consent.click();
  await page.getByLabel('อีเมล',{exact:true}).fill(data.users.admin.email);await page.getByLabel('รหัสผ่าน',{exact:true}).fill(data.users.admin.password);await page.getByRole('button',{name:'เข้าสู่ระบบ →',exact:true}).click();
  await page.getByRole('heading',{name:'จัดการข้อมูล GIS',exact:true}).waitFor();check('real_admin_login',true);
  await page.getByRole('tab',{name:'ชุดข้อมูล',exact:true}).click();await page.getByLabel('ปี (ค.ศ.)',{exact:true}).fill(String(data.dataset.data_year));await page.getByRole('button',{name:'กรองข้อมูล',exact:true}).click();await page.getByRole('button',{name:data.dataset.title,exact:true}).click();
  const section=page.locator(`[data-edition-id="${data.edition.id}"]`).getByRole('region',{name:'เปิดใช้ GeoTIFF ใน Local Dashboard',exact:true});
  step='admin-activation';await section.getByText(/มี Certificate/).waitFor();const activate=section.getByRole('button',{name:'เปิดใช้ GeoTIFF (Local)',exact:true});check('both_acknowledgements_required',await activate.isDisabled());
  for(const c of await section.getByRole('checkbox').all())await c.check();await activate.click();await page.getByRole('button',{name:'ยืนยันดำเนินการ',exact:true}).click();await page.getByRole('dialog').waitFor({state:'hidden'});check('actual_admin_confirmed_activation',true);
  step='dashboard';let reads=0;page.on('request',r=>{if(r.url().includes('/gis/published-geotiff'))reads++;});await page.getByRole('button',{name:'กลับแผนที่',exact:true}).click();
  const source=page.getByLabel('แหล่งข้อมูล Raster',{exact:true});await source.waitFor();check('legacy_default_no_published_request',await source.inputValue()==='legacy'&&reads===0);
  await source.selectOption('published');await page.getByLabel('จังหวัด Published',{exact:true}).selectOption(data.dataset.province);await page.getByLabel('ปี Published (ค.ศ.)',{exact:true}).fill(String(data.dataset.data_year));
  const panel=page.getByRole('region',{name:'แหล่งข้อมูล Raster Dashboard',exact:true});
  async function load(product){
   await page.getByLabel('ผลิตภัณฑ์ Published',{exact:true}).selectOption(product);
   const response=page.waitForResponse(r=>r.url().includes('/gis/published-geotiff')&&new URL(r.url()).searchParams.get('product')===product&&r.status()===200);
   await page.getByRole('button',{name:'ตรวจและแสดง Published Raster',exact:true}).click();return (await response).json();
  }
  let bundle=await load('ndvi');let snapshot=page.getByLabel('Published GeoTIFF Snapshot',{exact:true});await snapshot.waitFor();const img=panel.getByRole('img',{name:'Raster จาก Immutable Published GeoTIFF Snapshot',exact:true});await img.evaluate(el=>el.decode());
  check('actual_ndvi_raster_from_active_edition',bundle.source_identity.edition_id===data.edition.id&&bundle.summary.statistics.mean===.75&&await img.evaluate(el=>el.naturalWidth===2));
  check('raster_legend_summary_one_snapshot',await panel.getAttribute('data-source-snapshot')===bundle.snapshot_id&&await panel.getByRole('img',{name:'Legend Published GeoTIFF Snapshot',exact:true}).getAttribute('data-source-snapshot')===bundle.snapshot_id);
  check('unverified_period_coverage_warnings_visible',(await snapshot.innerText()).includes('ปี/เดือนยังไม่ยืนยัน')&&(await snapshot.innerText()).includes('ไม่รับรองทั้งจังหวัด'));
  await page.locator('.canvas').screenshot({path:path.join(data.output,'a42-published-ndvi-map.png')});check('real_deck_canvas_present',await page.locator('.canvas canvas').count()>0);
  bundle=await load('lst');await panel.getByText(/Kelvin conversion 1 ครั้ง/).waitFor();check('actual_kelvin_lst_displays_celsius_once',bundle.source_identity.edition_id===data.kelvin.id&&bundle.summary.statistics.mean===20&&bundle.legend.units==='celsius'&&bundle.summary.metadata.kelvin_to_celsius_count===1);
  await page.locator('.canvas').screenshot({path:path.join(data.output,'a42-published-lst-map.png')});
  await page.getByLabel('เดือน Published',{exact:true}).selectOption('1');check('period_change_clears_prior_snapshot',await page.getByLabel('Published GeoTIFF Snapshot',{exact:true}).count()===0);
  await page.getByLabel('เดือน Published',{exact:true}).selectOption('0');await load('ndvi');
  await page.setViewportSize({width:390,height:844});await panel.screenshot({path:path.join(data.output,'a42-published-mobile.png')});check('mobile_no_page_overflow',await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
  step='corrupt-active';fs.writeFileSync(path.join(data.output,'browser-awaiting-fault'),'ready');
  const deadline=Date.now()+180000;while(!fs.existsSync(path.join(data.output,'browser-fault-injected'))&&Date.now()<deadline)await page.waitForTimeout(200);
  if(Date.now()>=deadline)throw Error('FAULT_TIMEOUT');await page.getByRole('button',{name:'ตรวจและแสดง Published Raster',exact:true}).click();await panel.getByRole('alert').waitFor();
  check('corrupt_active_clears_raster_legend_summary_no_fallback',await page.getByLabel('Published GeoTIFF Snapshot',{exact:true}).count()===0&&await source.inputValue()==='published'&&await panel.getByRole('img').count()===0);
 }catch(e){rows.push({name:step,status:'Fail',diagnostic:step==='login'?'BROWSER_STEP_FAILED':String(e.message).split('\n')[0].slice(0,200)});if(page)await page.screenshot({path:path.join(data.output,'a42-browser-failure.png')}).catch(()=>{});}
 finally{if(context)await context.close();await browser.close();}
 fs.writeFileSync(path.join(data.output,'browser-results.json'),JSON.stringify({rows,page_errors:errors,mocked_api:false,external_https_blocked:true},null,2));console.log(JSON.stringify({rows}));if(rows.some(r=>r.status!=='Pass'))process.exitCode=1;
}
readline.createInterface({input:process.stdin}).once('line',line=>main(JSON.parse(line)).catch(()=>{console.log(JSON.stringify({code:'BROWSER_FAILED'}));process.exitCode=1;}));
