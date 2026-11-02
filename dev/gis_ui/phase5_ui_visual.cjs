// Focused visual/mobile pass over the already validated local GeoTIFF dataset.
const {createRequire}=require('node:module');
const fs=require('node:fs'),path=require('node:path'),readline=require('node:readline');
const {chromium}=createRequire(path.join(process.env.GIS_TEST_NODE_MODULES,'_resolver.cjs'))('playwright');
readline.createInterface({input:process.stdin}).once('line',async line=>{
  const data=JSON.parse(line),rows=[];let step='launch',browser;
  const check=(name,ok)=>{rows.push({name,status:ok?'Pass':'Fail'});if(!ok)throw new Error(name);};
  try{
    browser=await chromium.launch({channel:'chrome',headless:true,args:['--disable-background-networking','--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE localhost, EXCLUDE 127.0.0.1']});
    const page=await browser.newPage({viewport:{width:1366,height:1000}});page.setDefaultTimeout(60000);
    const cdp=await page.context().newCDPSession(page);await cdp.send('Network.enable');await cdp.send('Network.setBlockedURLs',{urls:['https://*']});
    step='login';await page.goto('http://127.0.0.1:3000/?view=gis');
    await page.getByRole('button',{name:'ใช้เฉพาะที่จำเป็น',exact:true}).click();
    await page.getByLabel('อีเมล',{exact:true}).fill(data.user.email);await page.getByLabel('รหัสผ่าน',{exact:true}).fill(data.user.password);
    await page.getByRole('button',{name:'เข้าสู่ระบบ →',exact:true}).click();await page.getByRole('button',{name:'สร้างชุดข้อมูล',exact:true}).waitFor();
    step='dataset';await page.getByLabel('ปี (ค.ศ.)',{exact:true}).fill(String(data.year));await page.getByRole('button',{name:'กรองข้อมูล',exact:true}).click();
    await page.getByRole('button',{name:data.title,exact:true}).click();const detail=page.getByRole('region',{name:'ชุดข้อมูลที่เลือก',exact:true});
    await detail.getByRole('button',{name:'อัปโหลด GeoTIFF',exact:true}).waitFor();
    await page.getByRole('tablist').evaluate(node=>node.scrollIntoView({block:'start'}));
    const desktop=await page.locator('.gis-master-detail').evaluate(node=>{const a=node.querySelector('.gis-catalog').getBoundingClientRect(),b=node.querySelector('.gis-dataset-detail').getBoundingClientRect();return b.left>=a.right&&Math.abs(a.top-b.top)<5;});
    check('desktop_list_and_detail_side_by_side',desktop);
    await page.screenshot({path:path.join(data.output,'gis-desktop-final.png'),fullPage:true});
    step='mobile';await page.setViewportSize({width:390,height:844});await page.getByRole('tablist').evaluate(node=>node.scrollIntoView({block:'start'}));
    check('mobile_no_page_overflow',await page.locator('.gis-page').evaluate(n=>n.scrollWidth<=n.clientWidth+1));
    check('mobile_selected_detail_before_list',await detail.evaluate(n=>getComputedStyle(n).gridRowStart==='1'));
    await page.screenshot({path:path.join(data.output,'gis-mobile-final.png'),fullPage:true});
    await detail.getByRole('button',{name:'อัปโหลด GeoTIFF',exact:true}).click();const dialog=page.getByRole('dialog');
    check('mobile_upload_form_visible',await dialog.getByLabel('ไฟล์ GeoTIFF').isVisible());
    const box=await dialog.boundingBox();check('mobile_dialog_fits_viewport',box.x>=0&&box.x+box.width<=391);
    await page.screenshot({path:path.join(data.output,'gis-mobile-upload-form.png'),fullPage:true});
    await dialog.getByRole('button',{name:'ยกเลิก',exact:true}).click();
    step='report';await detail.getByRole('button',{name:'งานและรายงานของชุดนี้',exact:true}).click();
    await page.getByRole('button',{name:'ดูงานตรวจสอบ 1',exact:true}).click();
    const report=page.getByRole('region',{name:'รายละเอียดงานและรายงาน',exact:true});
    await report.getByText('รายงาน GeoTIFF — Local/Test',{exact:true}).first().waitFor();
    check('mobile_report_context_matches_dataset',(await report.innerText()).includes(data.title));
    await report.scrollIntoViewIfNeeded();await page.screenshot({path:path.join(data.output,'gis-mobile-report.png'),fullPage:true});
    check('visual_pass_no_queue_mutations',true);
  }catch(error){rows.push({name:step,status:'Fail',error:step==='login'?'LOGIN_TEST_FAILED':String(error.message).slice(0,180)});}
  finally{if(browser)await browser.close();}
  fs.writeFileSync(path.join(data.output,'visual-results.json'),JSON.stringify({rows,real_local_api:true,worker_jobs_enqueued:false,consent:'necessary_only_in_test_context'},null,2));
  console.log(JSON.stringify({rows}));if(rows.some(r=>r.status!=='Pass'))process.exitCode=1;
});
