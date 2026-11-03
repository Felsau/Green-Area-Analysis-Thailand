// Actual local browser/CORS/Auth/API/queue/native files. No request mocking.
const {createRequire}=require('node:module');
const fs=require('node:fs'),path=require('node:path'),readline=require('node:readline');
const {chromium}=createRequire(path.join(process.env.GIS_TEST_NODE_MODULES,'_resolver.cjs'))('playwright');
async function main(data){
 const rows=[];let step='login',context;
 const check=(name,ok)=>{rows.push({name,status:ok?'Pass':'Fail'});if(!ok)throw Error('ASSERTION');};
 const browser=await chromium.launch({channel:'chrome',headless:true,args:['--disable-background-networking','--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE localhost, EXCLUDE 127.0.0.1']});
 try{
  context=await browser.newContext({viewport:{width:1366,height:1000},reducedMotion:'reduce'});
  const page=await context.newPage();page.setDefaultTimeout(90000);
  const cdp=await context.newCDPSession(page);await cdp.send('Network.enable');await cdp.send('Network.setBlockedURLs',{urls:['https://*']});
  await page.goto('http://127.0.0.1:3000/?view=gis');
  const consent=page.getByRole('button',{name:'ใช้เฉพาะที่จำเป็น',exact:true});if(await consent.count())await consent.click();
  await page.getByLabel('อีเมล',{exact:true}).fill(data.users.officer.email);
  await page.getByLabel('รหัสผ่าน',{exact:true}).fill(data.users.officer.password);
  await page.getByRole('button',{name:'เข้าสู่ระบบ →',exact:true}).click();
  await page.getByRole('heading',{name:'จัดการข้อมูล GIS',exact:true}).waitFor();check('officer_login',true);
  step='open-edition';await page.getByRole('tab',{name:'ชุดข้อมูล',exact:true}).click();
  await page.getByLabel('ปี (ค.ศ.)',{exact:true}).fill(String(data.dataset.data_year));
  await page.getByRole('button',{name:'กรองข้อมูล',exact:true}).click();
  await page.getByRole('button',{name:data.dataset.title,exact:true}).click();
  const article=()=>page.locator(`[data-edition-id="${data.edition.id}"]`);
  async function panel(){
   if(!await article().getByRole('button',{name:'ปิดตัวอย่างข้อมูลเตรียมไว้',exact:true}).count())
    await article().getByRole('button',{name:'เตรียมข้อมูล / ดูตัวอย่าง LDD',exact:true}).click();
   return article();
  }
  let p;
  if(!data.preview_only){
  step='enqueue';p=await panel();await p.getByRole('button',{name:'สั่งเตรียมข้อมูล LDD',exact:true}).click();
  await page.getByRole('button',{name:'ยืนยันดำเนินการ',exact:true}).click();
  await page.getByRole('dialog').waitFor({state:'hidden'});
  step='wait-prepare';
  for(let n=0;n<25;n++){
   p=await panel();if(await p.getByRole('button',{name:'ตรวจไฟล์จริงและเปิด Preview',exact:true}).count())break;
   await page.waitForTimeout(1500);await p.getByRole('button',{name:'รีเฟรชสถานะเตรียมข้อมูล',exact:true}).click();
  }
  p=await panel();await p.getByRole('button',{name:'ตรวจไฟล์จริงและเปิด Preview',exact:true}).click();
  step='verify';await page.getByRole('button',{name:'ยืนยันดำเนินการ',exact:true}).click();
  await page.getByRole('dialog').waitFor({state:'hidden'});
  }
  p=await panel();
  // Refresh is an actual endpoint that rereads source and output SHA/size.
  await p.getByRole('button',{name:'รีเฟรชสถานะเตรียมข้อมูล',exact:true}).click();
  await p.getByRole('img',{name:'ตัวอย่าง Geometry LDD ใน EPSG:4326',exact:true}).waitFor();
  check('real_geometry_preview',true);
  check('known_summary_area',(await p.innerText()).includes('6,400'));
  check('preview_not_dashboard',(await p.innerText()).includes('Dashboard'));
  check('no_activation_button',await p.getByRole('button',{name:/เปิดใช้|Activate/}).count()===0);
  await p.getByRole('img').scrollIntoViewIfNeeded();
  await p.screenshot({path:path.join(data.output,'a2-preview-desktop.png')});
  await page.setViewportSize({width:390,height:844});
  check('mobile_no_page_overflow',await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
  await p.getByRole('img').scrollIntoViewIfNeeded();
  await p.screenshot({path:path.join(data.output,'a2-preview-mobile.png')});
 }catch(error){rows.push({name:step,status:'Fail',diagnostic:step==='login'?'LOGIN_FAILED':String(error.message).split('Call log:')[0].slice(0,400)});}
 finally{if(context)await context.close();await browser.close();}
 fs.writeFileSync(path.join(data.output,'browser-results.json'),JSON.stringify({rows,mocked_api:false,external_https_blocked:true},null,2));
 console.log(JSON.stringify({rows}));if(rows.some(r=>r.status!=='Pass'))process.exitCode=1;
}
readline.createInterface({input:process.stdin}).once('line',line=>main(JSON.parse(line)).catch(()=>{console.log(JSON.stringify({failure:'BROWSER_SETUP_FAILED'}));process.exitCode=1;}));
