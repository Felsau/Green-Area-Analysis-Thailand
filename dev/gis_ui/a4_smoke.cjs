// Actual Local officer Prepare -> native worker -> trusted verify -> PNG preview.
const {createRequire}=require('node:module');
const fs=require('node:fs'),path=require('node:path'),readline=require('node:readline');
const {chromium}=createRequire(path.join(process.env.GIS_TEST_NODE_MODULES,'_resolver.cjs'))('playwright');
async function main(data){
 const rows=[];let context,step='login';const check=(name,ok)=>{rows.push({name,status:ok?'Pass':'Fail'});if(!ok)throw Error('ASSERTION');};
 const browser=await chromium.launch({channel:'chrome',headless:true,args:['--disable-background-networking','--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE localhost, EXCLUDE 127.0.0.1']});
 try{
  context=await browser.newContext({viewport:{width:1366,height:1000},reducedMotion:'reduce'});const page=await context.newPage();page.setDefaultTimeout(120000);
  const cdp=await context.newCDPSession(page);await cdp.send('Network.enable');await cdp.send('Network.setBlockedURLs',{urls:['https://*']});
  await page.goto('http://127.0.0.1:3000/?view=gis');const consent=page.getByRole('button',{name:'ใช้เฉพาะที่จำเป็น',exact:true});if(await consent.count())await consent.click();
  await page.getByLabel('อีเมล',{exact:true}).fill(data.users.officer.email);await page.getByLabel('รหัสผ่าน',{exact:true}).fill(data.users.officer.password);await page.getByRole('button',{name:'เข้าสู่ระบบ →',exact:true}).click();
  await page.getByRole('heading',{name:'จัดการข้อมูล GIS',exact:true}).waitFor();check('officer_login',true);
  await page.getByRole('tab',{name:'ชุดข้อมูล',exact:true}).click();await page.getByLabel('ปี (ค.ศ.)',{exact:true}).fill(String(data.dataset.data_year));await page.getByRole('button',{name:'กรองข้อมูล',exact:true}).click();await page.getByRole('button',{name:data.dataset.title,exact:true}).click();
  const article=()=>page.locator(`[data-edition-id="${data.edition.id}"]`);
  async function panel(){if(!await article().getByRole('button',{name:'ปิด Preview GeoTIFF',exact:true}).count())await article().getByRole('button',{name:'เตรียมข้อมูล / ดูตัวอย่าง GeoTIFF',exact:true}).click();return article().getByRole('region',{name:'เตรียมข้อมูลและ Preview GeoTIFF',exact:true});}
  step='enqueue';let p=await panel();await p.getByRole('button',{name:'สั่งเตรียม GeoTIFF',exact:true}).click();await page.getByRole('button',{name:'ยืนยันดำเนินการ',exact:true}).click();await page.getByRole('dialog').waitFor({state:'hidden'});check('prepare_real_confirmation',true);
  step='wait-worker';
  for(let n=0;n<30;n++){p=await panel();if(await p.getByRole('button',{name:'ตรวจไฟล์จริงและเปิด Preview GeoTIFF',exact:true}).count())break;await page.waitForTimeout(1000);await p.getByRole('button',{name:'รีเฟรชสถานะ GeoTIFF',exact:true}).click();}
  p=await panel();await p.getByRole('button',{name:'ตรวจไฟล์จริงและเปิด Preview GeoTIFF',exact:true}).click();step='verify';await page.getByRole('button',{name:'ยืนยันดำเนินการ',exact:true}).click();await page.getByRole('dialog').waitFor({state:'hidden'});
  p=await panel();const img=p.getByRole('img',{name:'ตัวอย่าง Raster GeoTIFF ที่ตรวจไฟล์จริงแล้ว',exact:true});await img.waitFor();await img.evaluate(el=>el.decode());
  check('actual_verified_raster_png',await img.evaluate(el=>el.naturalWidth===2&&el.naturalHeight===2));
  check('summary_valid_nodata_counts',(await p.innerText()).includes('3 / 1 / 4'));
  check('preview_not_published',(await p.innerText()).includes('ยังไม่ Publish หรือเปิดใช้บน Dashboard'));
  check('period_coverage_limitations',(await p.innerText()).includes('ยังไม่ได้ยืนยันช่วงเวลา')&&(await p.innerText()).includes('ไม่รับรองว่าครบทั้งจังหวัด'));
  check('no_geotiff_activation_controls',await p.getByRole('button',{name:/เปิดใช้|Activate|Rollback|ถอน/}).count()===0);
  await img.scrollIntoViewIfNeeded();await p.screenshot({path:path.join(data.output,'a4-geotiff-preview-desktop.png')});
  await page.setViewportSize({width:390,height:844});await img.scrollIntoViewIfNeeded();await p.screenshot({path:path.join(data.output,'a4-geotiff-preview-mobile.png')});
  check('mobile_no_page_overflow',await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
 }catch(error){rows.push({name:step,status:'Fail',diagnostic:String(error.message).split('Call log:')[0].slice(0,260)});}
 finally{if(context)await context.close();await browser.close();}
 fs.writeFileSync(path.join(data.output,'browser-results.json'),JSON.stringify({rows,mocked_api:false,external_https_blocked:true},null,2));console.log(JSON.stringify({rows}));if(rows.some(r=>r.status!=='Pass'))process.exitCode=1;
}
readline.createInterface({input:process.stdin}).once('line',line=>main(JSON.parse(line)).catch(()=>{console.log(JSON.stringify({code:'BROWSER_FAILED'}));process.exitCode=1;}));
