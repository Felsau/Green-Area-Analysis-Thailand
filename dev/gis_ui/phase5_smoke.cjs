// Cross-feature demo smoke: all HTTP/Auth/storage/jobs are real and local.
const { createRequire } = require('node:module');
const fs = require('node:fs'), path = require('node:path'), readline = require('node:readline');
const crypto = require('node:crypto');
const modules = createRequire(path.join(process.env.GIS_TEST_NODE_MODULES,'_resolver.cjs'));
const { chromium } = modules('playwright');
const rows=[], traffic=[]; let step='setup';
function check(name,ok){rows.push({name,status:ok?'Pass':'Fail'});if(!ok)throw new Error('ASSERTION');}
function handled(p){p.catch(()=>{});return p;}

async function main(data){
  const browser=await chromium.launch({channel:'chrome',headless:true,args:['--disable-background-networking',
    '--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE localhost, EXCLUDE 127.0.0.1']});
  const contexts=[];let current;
  async function login(user){
    const context=await browser.newContext({viewport:{width:1366,height:1000},reducedMotion:'reduce'});contexts.push(context);
    const page=await context.newPage();current=page;page.setDefaultTimeout(60000);
    // Native browser CORS must remain active. Request interception can mask a
    // missing preflight header; block external HTTPS via CDP without routing.
    const cdp=await context.newCDPSession(page);await cdp.send('Network.enable');
    await cdp.send('Network.setBlockedURLs',{urls:['https://*']});
    page.on('response',r=>{if(r.url().startsWith('http://127.0.0.1:55422/gis/'))traffic.push({path:new URL(r.url()).pathname,method:r.request().method(),status:r.status()});});
    await page.goto('http://127.0.0.1:3000/?view=gis');
    const consent=page.getByRole('button',{name:'ใช้เฉพาะที่จำเป็น',exact:true});
    if(await consent.count())await consent.click();
    await page.getByLabel('อีเมล',{exact:true}).fill(user.email);await page.getByLabel('รหัสผ่าน',{exact:true}).fill(user.password);
    await page.getByRole('button',{name:'เข้าสู่ระบบ →',exact:true}).click();await page.getByRole('heading',{name:'จัดการข้อมูล GIS',exact:true}).waitFor();return page;
  }
  async function read(page,route,query={}){return page.evaluate(async({route,query})=>{const{gisRequest}=await import('/src/utils/gisClient.js');return gisRequest(route,{query});},{route,query});}
  async function denied(page,route,body){return page.evaluate(async({route,body})=>{const{gisRequest}=await import('/src/utils/gisClient.js');try{await gisRequest(route,{method:'POST',key:crypto.randomUUID(),body});return 200;}catch(e){return e.status;}},{route,body});}
  async function confirm(page,pathname){
    const response=handled(page.waitForResponse(r=>new URL(r.url()).pathname===pathname&&r.request().method()==='POST'));
    const refresh=handled(page.waitForResponse(r=>new URL(r.url()).pathname==='/gis/me'&&r.status()===200));
    const count=traffic.filter(r=>r.path===pathname&&r.method==='POST').length;
    await page.getByRole('button',{name:'ยืนยันดำเนินการ',exact:true}).evaluate(b=>{b.click();b.click();});
    check('confirmed_'+pathname.split('/').at(-1),[200,201,202].includes((await response).status()));
    await page.getByRole('dialog').waitFor({state:'hidden'});await refresh;
    check('one_post_'+pathname.split('/').at(-1),traffic.filter(r=>r.path===pathname&&r.method==='POST').length===count+1);
  }
  async function createDataset(page,kind,purpose){
    await page.getByRole('tab',{name:'ชุดข้อมูล',exact:true}).click();
    await page.getByRole('button',{name:'สร้างชุดข้อมูล',exact:true}).click();
    const dialog=page.getByRole('dialog');const title='Demo '+purpose+' '+data.run;
    await dialog.getByLabel('ชื่อชุดข้อมูล',{exact:true}).fill(title);await dialog.getByLabel('จังหวัด',{exact:true}).selectOption(data.province);
    await dialog.getByLabel('ปีข้อมูล (ค.ศ.)').fill(String(data.year));await dialog.getByLabel('ประเภทข้อมูล',{exact:true}).selectOption(kind+':'+purpose);
    await dialog.getByRole('button',{name:'ตรวจทานคำสั่ง',exact:true}).click();await confirm(page,'/gis/datasets');
    await page.getByLabel('ปี (ค.ศ.)',{exact:true}).fill(String(data.year));await page.getByRole('button',{name:'กรองข้อมูล',exact:true}).click();
    await page.getByRole('button',{name:title,exact:true}).click();
    return (await read(page,'/datasets',{province:data.province,data_year:data.year,kind,purpose,limit:100})).data.find(d=>d.title===title);
  }
  async function validate(page,editionId,reportTitle){
    await page.getByRole('tab',{name:'ชุดข้อมูล',exact:true}).click();
    const article=page.locator(`[data-edition-id="${editionId}"]`);
    await article.getByRole('button',{name:'ส่งตรวจสอบ',exact:true}).click();await confirm(page,'/gis/editions/'+editionId+'/validation-jobs');
    const job=(await read(page,'/jobs',{edition_id:editionId})).data[0];
    const loaded=()=>handled(Promise.all(['','/attempts'].map(s=>page.waitForResponse(r=>new URL(r.url()).pathname==='/gis/jobs/'+job.id+s&&r.status()===200))));
    const first=loaded();await page.locator(`[data-job-id="${job.id}"]`).click();await first;
    const detail=page.getByRole('region',{name:'รายละเอียดงานและรายงาน',exact:true});
    for(let i=0;i<12&&!await detail.getByText(reportTitle,{exact:true}).count();i++){await page.waitForTimeout(1000);const wait=loaded();await detail.getByRole('button',{name:'รีเฟรชรายละเอียดงาน',exact:true}).click();await wait;}
    await detail.getByText(reportTitle,{exact:true}).first().waitFor();
    check('validated_'+reportTitle,(await read(page,'/jobs/'+job.id)).state==='succeeded');
    check('attempt_report_'+reportTitle,(await read(page,'/jobs/'+job.id+'/attempts')).data.some(a=>a.validation_report?.valid===true));
    return job;
  }
  async function upload(page,dataset,kind,filename,profile){
    await page.getByRole('tab',{name:'ชุดข้อมูล',exact:true}).click();
    const geo=kind==='geotiff';
    await page.getByRole('button',{name:geo?'อัปโหลด GeoTIFF':'อัปโหลด LDD ZIP',exact:true}).click();
    await page.getByLabel(geo?'ไฟล์ GeoTIFF':'ไฟล์ LDD Shapefile ZIP',{exact:true}).setInputFiles(filename);
    if(geo)await page.getByLabel('Scientific Profile').selectOption(profile);
    await page.getByRole('button',{name:'ตรวจทานคำสั่ง',exact:true}).click();await confirm(page,'/gis/datasets/'+dataset.id+'/'+(geo?'geotiff':'ldd')+'-uploads');
    const sha=crypto.createHash('sha256').update(fs.readFileSync(filename)).digest('hex');
    const edition=(await read(page,'/datasets/'+dataset.id+'/editions',{limit:100})).data.find(e=>e.upload?.sha256===sha);
    check(kind+'_immutable_metadata',!!edition&&edition.upload.sha256===sha);
    const article=page.locator(`[data-edition-id="${edition.id}"]`);
    check(kind+'_edit_hidden',await article.getByRole('button',{name:'แก้ Manifest',exact:true}).count()===0);
    return edition;
  }
  async function processJob(page,scenario){
    await page.getByRole('tab',{name:'ประมวลผล NDVI/LST',exact:true}).click();
    await page.getByRole('button',{name:'สร้างงานประมวลผล NDVI/LST',exact:true}).click();
    await page.getByLabel('จังหวัดประมวลผล').selectOption(data.province);await page.getByLabel('ปีประมวลผล (ค.ศ.)').fill(String(data.processing_year));
    await page.getByLabel('ช่วงเวลาประมวลผล').selectOption(String(data.processing_month));await page.getByLabel('ชุดข้อมูลจำลอง').selectOption(scenario);
    await page.getByRole('button',{name:'ตรวจทานคำสั่ง',exact:true}).click();await confirm(page,'/gis/processing-jobs');
    const job=(await read(page,'/processing-jobs',{limit:100,province:data.province,metric:'ndvi'})).data.find(j=>j.metadata.data_year===data.processing_year&&j.metadata.month===data.processing_month&&j.metadata.scenario===scenario);
    const panel=page.locator('section.gis-card').filter({has:page.getByRole('heading',{name:'ประมวลผล NDVI/LST',exact:true})});
    const button=panel.locator(`[data-processing-id="${job.id}"]`);
    for(let n=0;n<15&&!await button.count();n++){const response=handled(page.waitForResponse(r=>new URL(r.url()).pathname==='/gis/processing-jobs'&&r.status()===200));await panel.getByRole('button',{name:'หน้าถัดไป',exact:true}).first().click();await response;}
    const loaded=()=>handled(Promise.all(['','/attempts','/history'].map(s=>page.waitForResponse(r=>new URL(r.url()).pathname==='/gis/processing-jobs/'+job.id+s&&r.status()===200))));
    const first=loaded();await button.click();await first;
    const detail=panel.getByRole('region',{name:'รายละเอียดงานประมวลผล',exact:true});
    for(let n=0;n<12&&!await detail.getByText('Candidate / Offline Synthetic',{exact:true}).count();n++){await page.waitForTimeout(1000);const wait=loaded();await detail.getByRole('button',{name:'รีเฟรชงานประมวลผล',exact:true}).click();await wait;}
    await detail.getByText('Candidate / Offline Synthetic',{exact:true}).first().waitFor();
    const current=await read(page,'/processing-jobs/'+job.id);
    check('processing_'+scenario+'_outcome',current.state===(scenario==='standard'?'succeeded':'failed'));
    check('processing_'+scenario+'_history',(await read(page,'/processing-jobs/'+job.id+'/history')).data.length>0);
    check('processing_'+scenario+'_offline_label',(await detail.innerText()).includes('ไม่ใช่ผล GEE'));
    if(scenario==='standard')check('processing_numeric_result',Math.abs(current.result.report.statistics.mean-.1614)<.00001);
    else{
      check('failure_no_fake_candidate',!current.result&&(await detail.innerText()).includes('mean: ไม่มีข้อมูล'));
      check('invalid_data_retry_denied',await denied(page,'/processing-jobs/'+job.id+'/retry',{expected_revision:current.input_revision,input_hash:current.input_hash,reason:'Local smoke invalid data cannot be retried'})===409);
    }
  }
  try{
    step='normal-login';const normal=await login(data.users.normal);await normal.getByText('ไม่มีสิทธิ์จัดการข้อมูล GIS กรุณาติดต่อผู้ดูแลระบบ').waitFor();check('normal_user_denied',true);
    step='admin-login';const admin=await login(data.users.admin);await admin.getByRole('tab',{name:'เจ้าหน้าที่ GIS',exact:true}).click();await admin.getByRole('button',{name:'เพิ่มเจ้าหน้าที่',exact:true}).click();
    await admin.getByLabel('UUID ผู้ใช้ Local').fill(data.users.officer.id);await admin.getByLabel('เหตุผล',{exact:true}).fill('Phase5 local demo only');
    await admin.getByRole('button',{name:'ตรวจทานคำสั่ง',exact:true}).click();await confirm(admin,'/gis/officers');
    step='officer-login';const officer=await login(data.users.officer);await officer.getByRole('button',{name:'สร้างชุดข้อมูล',exact:true}).waitFor();check('officer_no_admin_controls',await officer.getByRole('button',{name:'เพิ่มเจ้าหน้าที่',exact:true}).count()===0);
    step='legacy-integration';await require('./legacy_smoke.cjs')(officer,data,check);
    step='ldd-dataset';const ldd=await createDataset(officer,'ldd_shapefile','landuse');check('ui_created_dataset',!!ldd);
    step='map-interactions';await require('./phase5_ui_checks.cjs')(officer,data,check,'map');
    await officer.getByLabel('ปี (ค.ศ.)',{exact:true}).fill(String(data.year));
    await officer.getByRole('button',{name:'กรองข้อมูล',exact:true}).click();
    await officer.getByRole('button',{name:'Demo landuse '+data.run,exact:true}).click();
    step='native-edition';await officer.getByText('ตัวเลือกเพิ่มเติมและข้อมูลทางเทคนิค',{exact:true}).click();await officer.getByRole('button',{name:'สร้าง Edition',exact:true}).click();await officer.getByLabel('Manifest JSON (Synthetic V1/V2)').fill(JSON.stringify(data.native_manifest));
    await officer.getByRole('button',{name:'ตรวจทานคำสั่ง',exact:true}).click();await confirm(officer,'/gis/datasets/'+ldd.id+'/editions');
    const draft=(await read(officer,'/datasets/'+ldd.id+'/editions')).data.find(e=>e.manifest.fixture_id===data.native_manifest.fixture_id);check('ui_created_native_edition',!!draft);
    check('revision_conflict_denied',await denied(officer,'/editions/'+draft.id+'/validation-jobs',{expected_revision:draft.input_revision+1})===409);
    await validate(officer,draft.id,'รายงานการตรวจ');
    step='ldd-upload';const uploaded=await upload(officer,ldd,'ldd',data.ldd_fixture);await validate(officer,uploaded.id,'รายงานการตรวจ');
    step='geotiff-upload';const geo=await createDataset(officer,'geotiff','ndvi');const tif=await upload(officer,geo,'geotiff',path.join(data.fixture_root,'ndvi_valid.tif'),'ndvi_ready');await validate(officer,tif.id,'รายงาน GeoTIFF — Local/Test');
    step='offline-success';await processJob(officer,'standard');step='offline-failure';await processJob(officer,'no_data');
    step='closed-gates';const latest=await read(admin,'/datasets/'+ldd.id);
    check('activation_gate_rejected',await denied(admin,'/datasets/'+ldd.id+'/activation',{edition_id:uploaded.id,expected_revision:latest.revision,expected_active_edition_id:null,reason:'Closed gate smoke; must reject'})===503);
    check('active_pointers_unchanged',(await read(officer,'/datasets/'+ldd.id)).active_edition_id===null&&(await read(officer,'/datasets/'+geo.id)).active_edition_id===null);
    check('live_gee_still_disabled',(await read(officer,'/me')).gee_live_enabled===false);
    step='ui-responsive-map';await require('./phase5_ui_checks.cjs')(officer,data,check,'workspace');
    await officer.screenshot({path:path.join(data.output,'demo-desktop.png'),fullPage:true});
  }catch(error){rows.push({name:step,status:'Fail',...(!step.includes('login')?{diagnostic:String(error.message).split('Call log:')[0].slice(0,800)}:{})});if(current&&!step.includes('login'))await current.screenshot({path:path.join(data.output,'failure.png'),fullPage:true}).catch(()=>{});}
  finally{for(const c of contexts)await c.close().catch(()=>{});await browser.close().catch(()=>{});}
  fs.writeFileSync(path.join(data.output,'browser-results.json'),JSON.stringify({local_only:true,mocked_api:false,rows,traffic},null,2));console.log(JSON.stringify({rows}));if(rows.some(r=>r.status!=='Pass'))process.exitCode=1;
}
readline.createInterface({input:process.stdin}).once('line',line=>main(JSON.parse(line)).catch(()=>{console.log(JSON.stringify({code:'DEMO_SMOKE_SETUP_FAILED',step}));process.exitCode=1;}));
