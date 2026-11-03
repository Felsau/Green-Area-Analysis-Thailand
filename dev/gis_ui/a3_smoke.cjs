// Real Local Dashboard/Auth/API/native-artifact snapshot. No API mocking.
const {createRequire}=require('node:module');
const fs=require('node:fs'),path=require('node:path'),readline=require('node:readline');
const {chromium}=createRequire(path.join(process.env.GIS_TEST_NODE_MODULES,'_resolver.cjs'))('playwright');
async function main(data){
 const rows=[];let step='login',context;
 const check=(name,ok)=>{rows.push({name,status:ok?'Pass':'Fail'});if(!ok)throw Error('ASSERTION');};
 const browser=await chromium.launch({channel:'chrome',headless:true,args:['--disable-background-networking','--enable-unsafe-swiftshader','--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE localhost, EXCLUDE 127.0.0.1']});
 try{
  context=await browser.newContext({viewport:{width:1440,height:1000},reducedMotion:'reduce'});
  const page=await context.newPage();page.setDefaultTimeout(120000);
  const cdp=await context.newCDPSession(page);await cdp.send('Network.enable');await cdp.send('Network.setBlockedURLs',{urls:['https://*']});
  await page.goto('http://127.0.0.1:3000/?'+new URLSearchParams({p:data.dataset.province,year:'2024'}));
  const consent=page.getByRole('button',{name:'ใช้เฉพาะที่จำเป็น',exact:true});if(await consent.count())await consent.click();
  await page.getByLabel('อีเมล',{exact:true}).fill(data.users.normal.email);
  await page.getByLabel('รหัสผ่าน',{exact:true}).fill(data.users.normal.password);
  await page.getByRole('button',{name:'เข้าสู่ระบบ →',exact:true}).click();
  await page.locator('.canvas canvas').first().waitFor();check('normal_dashboard_login',true);
  step='legacy-default';
  const accordion=page.getByRole('button',{name:/การใช้ที่ดิน · 5 ประเภทหลัก/});await accordion.click();
  await page.getByRole('button',{name:'Legacy (ค่าเริ่มต้น)',exact:true}).waitFor();
  check('legacy_remains_default',await page.getByRole('button',{name:'Legacy (ค่าเริ่มต้น)',exact:true}).getAttribute('aria-pressed')==='true');
  step='published';await page.getByRole('button',{name:'Published LDD (Local)',exact:true}).click();
  await page.getByLabel('ปี Published (ค.ศ.)',{exact:true}).fill(String(data.dataset.data_year));
  const response=page.waitForResponse(r=>r.url().includes('/gis/published-ldd')&&r.request().method()==='GET'&&r.status()===200);
  await page.getByRole('button',{name:'โหลด Published LDD',exact:true}).click();const bundle=await (await response).json();
  const summary=page.getByRole('region',{name:'สรุป Published LDD',exact:true});await summary.waitFor();
  const legend=page.getByLabel('คำอธิบาย Published LDD',{exact:true});await legend.waitFor();
  check('real_response_current_edition',bundle.source_identity.edition_id===data.edition.id&&bundle.summary.total_area_m2===6400&&bundle.geometry.features.length===3);
  check('map_legend_summary_one_snapshot',await summary.getAttribute('data-source-snapshot')===bundle.snapshot_id&&await legend.getAttribute('data-source-snapshot')===bundle.snapshot_id);
  check('summary_original_area_provenance',(await summary.innerText()).includes('6,400')&&(await summary.innerText()).includes('ไม่ใช่พื้นที่ครบทั้งจังหวัด'));
  // Screenshot captures the actual DeckGL rendering. No replacement geometry.
  await page.waitForTimeout(1000);await summary.screenshot({path:path.join(data.output,'a3-published-summary.png')});
  await page.locator('.canvas').screenshot({path:path.join(data.output,'a3-published-map.png')});
  check('map_canvas_present',await page.locator('.canvas canvas').count()>0);
  step='legacy-switch';await page.getByRole('button',{name:'Legacy (ค่าเริ่มต้น)',exact:true}).click();
  check('switch_clears_published_geometry_legend',await legend.count()===0&&await summary.count()===0);
  step='district';await page.goto('http://127.0.0.1:3000/?'+new URLSearchParams({p:data.dataset.province,d:'BangRak',year:'2024'}));
  await page.locator('.context__sub').waitFor();await page.getByRole('button',{name:/การใช้ที่ดิน · 5 ประเภทหลัก/}).click();
  check('district_navigation_preserved_and_published_disabled',new URL(page.url()).searchParams.get('d')==='BangRak'&&await page.getByRole('button',{name:'Published LDD (Local)',exact:true}).isDisabled());
 }catch(error){rows.push({name:step,status:'Fail',diagnostic:String(error.message).split('Call log:')[0].slice(0,300)});}
 finally{if(context)await context.close();await browser.close();}
 fs.writeFileSync(path.join(data.output,'browser-results.json'),JSON.stringify({rows,mocked_api:false,external_https_blocked:true},null,2));
 console.log(JSON.stringify({rows}));if(rows.some(r=>r.status!=='Pass'))process.exitCode=1;
}
readline.createInterface({input:process.stdin}).once('line',line=>main(JSON.parse(line)).catch(()=>{console.log(JSON.stringify({code:'BROWSER_FAILED'}));process.exitCode=1;}));
