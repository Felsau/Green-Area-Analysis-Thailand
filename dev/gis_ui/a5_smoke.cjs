// Real Local Normal-user Dashboard and explicit Admin test-fixture mutations.
// Auth travels only in the private stdin pipe; never persisted or printed.
const {createRequire}=require('node:module');
const fs=require('node:fs'),path=require('node:path'),readline=require('node:readline'),crypto=require('node:crypto');
const {chromium}=createRequire(path.join(process.env.GIS_TEST_NODE_MODULES,'_resolver.cjs'))('playwright');
async function main(data){
 const rows=[],errors=[],derived=[];let context,page,step='setup',publishedPhase=false;
 const check=(name,ok)=>{rows.push({name,status:ok?'Pass':'Fail'});if(!ok)throw Error('ASSERTION');};
 async function api(route,body){
  const response=await fetch('http://127.0.0.1:55422/gis'+route,{method:body?'POST':'GET',redirect:'error',
   headers:{Authorization:'Bearer '+data.admin_token,'Content-Type':'application/json','Idempotency-Key':crypto.randomUUID()},...(body?{body:JSON.stringify(body)}:{})});
  const value=await response.json();if(!response.ok)throw Error('API_'+response.status+'_'+(value.detail?.code||'FAILED'));return value;
 }
 async function ldd(op,e){
  const d=await api('/datasets/'+data.ldd.id);
  return api('/datasets/'+d.id+'/ldd-publication/'+op,{edition_id:e.id,expected_dataset_revision:d.revision,expected_active_edition_id:d.active_edition_id,
   expected_input_revision:e.input_revision,input_hash:e.input_hash,validation_result_id:e.validated_result_id,source_sha256:e.upload.sha256,
   province:d.province,data_year:d.data_year,method_version:'ldd-source-area-v1',coverage_mode:'validated_source_footprint',reason:'A5 synthetic browser source test',
   ...(op==='withdrawal'?{replacement_edition_id:null}:{})});
 }
 async function geo(op){
  const d=await api('/datasets/'+data.geo.id),e=data.ge,s=await api('/editions/'+e.id+'/geotiff-publication');
  return api('/datasets/'+d.id+'/geotiff-publication/'+op,{edition_id:e.id,expected_dataset_revision:d.revision,expected_active_edition_id:d.active_edition_id,
   expected_input_revision:e.input_revision,input_hash:e.input_hash,validation_result_id:s.validation_result_id,certificate_id:s.certificate_id,source_sha256:e.upload.sha256,
   province:d.province,data_year:d.data_year,month:0,product:'ndvi',profile:'ndvi_ready',method_version:'geotiff-grid-celsius-v1',coverage_mode:'source_footprint_intersection',
   policy_version:'local-declared-period-footprint-v1',acknowledge_unverified_period:true,acknowledge_limited_coverage:true,reason:'A5 synthetic browser source test',
   ...(op==='withdrawal'?{replacement_edition_id:null}:{})});
 }
 const browser=await chromium.launch({channel:'chrome',headless:true,args:['--disable-background-networking','--enable-unsafe-swiftshader','--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE localhost, EXCLUDE 127.0.0.1']});
 try{
  await ldd('activation',data.a);if(!data.country_only)await geo('activation');
  context=await browser.newContext({viewport:{width:1440,height:1000},reducedMotion:'reduce'});page=await context.newPage();page.setDefaultTimeout(120000);
  page.on('pageerror',e=>errors.push(String(e.message).split('\n')[0].slice(0,150)));
  page.on('request',r=>{const p=new URL(r.url()).pathname;if(publishedPhase&&/\/(compare|recommend|analysis\/(ranking|timeseries|cooling))(\/|$)/.test(p))derived.push(p);});
  const cdp=await context.newCDPSession(page);await cdp.send('Network.enable');await cdp.send('Network.setBlockedURLs',{urls:['https://*']});
  step='login';await page.goto('http://127.0.0.1:3000/?'+new URLSearchParams({p:data.ldd.province,year:'2024'}));
  const consent=page.getByRole('button',{name:'ใช้เฉพาะที่จำเป็น',exact:true});if(await consent.count())await consent.click();
  await page.getByLabel('อีเมล',{exact:true}).fill(data.user.email);await page.getByLabel('รหัสผ่าน',{exact:true}).fill(data.user.password);await page.getByRole('button',{name:'เข้าสู่ระบบ →',exact:true}).click();
  await page.locator('.canvas canvas').first().waitFor();check('real_normal_user_dashboard',true);
  const accordion=page.getByRole('button',{name:/การใช้ที่ดิน · 5 ประเภทหลัก/});await accordion.click();
  const legacy=page.getByRole('button',{name:'Legacy (ค่าเริ่มต้น)',exact:true});await legacy.waitFor();check('legacy_remains_default',await legacy.getAttribute('aria-pressed')==='true');
  const summary=page.getByRole('region',{name:'สรุป Published LDD',exact:true}),legend=page.getByLabel('คำอธิบาย Published LDD',{exact:true});
  async function loadLdd(expected,status=200){
   const response=page.waitForResponse(r=>r.url().includes('/gis/published-ldd')&&r.status()===status);
   await page.getByRole('button',{name:'โหลด Published LDD',exact:true}).click();const b=await (await response).json();
   if(status===200){await summary.waitFor();check('ldd_response_'+expected,b.source_identity.edition_id===expected&&b.summary.total_area_m2===6400);
    check('ldd_snapshot_'+expected,await summary.getAttribute('data-source-snapshot')===b.snapshot_id&&await legend.getAttribute('data-source-snapshot')===b.snapshot_id);}
   return b;
  }
  step='published-ldd';publishedPhase=true;await page.getByRole('button',{name:'Published LDD (Local)',exact:true}).click();
  await page.getByLabel('ปี Published (ค.ศ.)',{exact:true}).fill(String(data.ldd.data_year));await loadLdd(data.a.id);
  if(data.country_only){
   step='published-country';await page.getByRole('button',{name:'← ดูภาพรวมประเทศ',exact:true}).click();await page.getByText('ยังไม่ได้เลือกจังหวัด',{exact:true}).waitFor();
   check('published_country_stays_explicitly_published',(await page.locator('.topbar__source').innerText()).includes('Published LDD'));
   check('published_country_ranking_explicitly_unsupported',await page.getByText('Ranking — ยังไม่รองรับ',{exact:true}).isVisible());
   check('published_country_no_legacy_compute_or_exports',await page.getByRole('button',{name:/คำนวณ|CSV|PDF|โหลดอันดับ/}).count()===0&&derived.length===0);
   check('published_country_source_escape_reachable',await page.getByRole('button',{name:'กลับไป Legacy',exact:true}).isVisible());
   await page.screenshot({path:path.join(data.output,'a5-published-country.png')});
   await page.getByPlaceholder('ค้นหาหรือเลือกจังหวัด…',{exact:true}).fill(data.ldd.province);await page.getByRole('option').filter({hasText:data.ldd.province}).click();
   await page.getByRole('button',{name:'โหลด Published LDD',exact:true}).waitFor();
   check('province_reselection_preserves_published_and_declared_year',await page.getByRole('button',{name:'Published LDD (Local)',exact:true}).getAttribute('aria-pressed')==='true'&&await page.getByLabel('ปี Published (ค.ศ.)',{exact:true}).inputValue()===String(data.ldd.data_year));
   await loadLdd(data.a.id);await page.getByRole('button',{name:'← ดูภาพรวมประเทศ',exact:true}).click();await page.getByText('ยังไม่ได้เลือกจังหวัด',{exact:true}).waitFor();
   check('no_legacy_derived_call_before_explicit_return',derived.length===0);publishedPhase=false;await page.getByRole('button',{name:'กลับไป Legacy',exact:true}).click();
   check('explicit_return_restores_legacy_country',!(await page.locator('.topbar__source').innerText()).includes('Published LDD')&&await page.getByText('ดัชนีพื้นที่สีเขียว',{exact:true}).isVisible());
   await ldd('withdrawal',data.a);check('no_uncaught_browser_errors',errors.length===0);
  }else{
  check('ldd_has_no_legacy_ndvi_stats',(await page.getByText('NDVI · พื้นที่สีเขียว',{exact:true}).count())===0&&(await page.locator('.topbar__source').innerText()).includes('Published LDD'));
  check('published_draw_and_saved_disabled',await page.getByRole('button',{name:'วาดพื้นที่วิเคราะห์เอง',exact:true}).isDisabled()&&await page.getByRole('button',{name:'พื้นที่ที่บันทึกไว้',exact:true}).isDisabled());
  await page.locator('.usermenu__trigger').click();check('header_saved_disabled',await page.getByRole('menuitem',{name:'พื้นที่ที่บันทึกไว้',exact:true}).isDisabled());await page.getByRole('button',{name:'ปิดเมนู',exact:true}).click();
  for(const name of ['เปรียบเทียบ','แนวโน้ม','ความเย็น','AI แนะนำ']){
   await page.getByRole('tab',{name,exact:true}).click();const unavailable=page.getByRole('region',{name:'ความพร้อมของฟีเจอร์ Published',exact:true});await unavailable.waitFor();
   check('unsupported_'+name,(await unavailable.innerText()).includes('ยังไม่รองรับ')&&await page.getByRole('button',{name:'กลับไป Legacy',exact:true}).isVisible());
  }
  check('unsupported_tabs_never_call_legacy_derived_api',derived.length===0);await page.getByRole('button',{name:'เลือกแหล่งข้อมูล / ปี',exact:true}).click();await summary.waitFor();
  await page.getByLabel('ปี Published (ค.ศ.)',{exact:true}).fill(String(data.ldd.data_year+1));
  check('year_change_clears_old_summary_legend',await summary.count()===0&&await legend.count()===0);await loadLdd('missing',404);
  check('missing_period_explicit_no_legacy_fallback',await page.getByRole('alert').count()>0&&await summary.count()===0&&await legend.count()===0&&await page.getByRole('button',{name:'Published LDD (Local)',exact:true}).getAttribute('aria-pressed')==='true');
  await page.getByLabel('ปี Published (ค.ศ.)',{exact:true}).fill(String(data.ldd.data_year));await loadLdd(data.a.id);
  step='replacement';await ldd('activation',data.b);await loadLdd(data.b.id);await ldd('rollback',data.a);await loadLdd(data.a.id);check('actual_replacement_and_rollback_bound_to_current_ui',true);
  await ldd('activation',data.b);await loadLdd(data.b.id);
  await page.screenshot({path:path.join(data.output,'a5-published-ldd.png')});
  step='revocation';fs.writeFileSync(path.join(data.output,'browser-awaiting-fault'),'ready');
  const deadline=Date.now()+180000;while(!fs.existsSync(path.join(data.output,'browser-fault-injected'))&&Date.now()<deadline)await page.waitForTimeout(200);
  if(Date.now()>=deadline)throw Error('FAULT_TIMEOUT');await loadLdd('corrupt',409);await page.getByRole('alert').first().waitFor();
  check('revoked_clears_geometry_legend_summary_availability',await summary.count()===0&&await legend.count()===0&&await page.getByText(/แผนที่ \/ Legend — ยังไม่พร้อม/).count()>0);
  await ldd('withdrawal',data.b);await page.getByRole('button',{name:'Legacy (ค่าเริ่มต้น)',exact:true}).click();publishedPhase=false;
  step='legacy-return';await page.getByRole('tab',{name:'เปรียบเทียบ',exact:true}).click();await page.getByText('จังหวัดที่เลือก',{exact:true}).waitFor();
  check('legacy_compare_navigation_preserved',await page.getByRole('region',{name:'ความพร้อมของฟีเจอร์ Published',exact:true}).count()===0&&await page.getByRole('button',{name:'พื้นที่ที่บันทึกไว้',exact:true}).isEnabled());
  step='geotiff';await page.getByLabel('แหล่งข้อมูล Raster',{exact:true}).selectOption('published');publishedPhase=true;
  await page.getByLabel('จังหวัด Published',{exact:true}).selectOption(data.geo.province);await page.getByLabel('ปี Published (ค.ศ.)',{exact:true}).fill(String(data.geo.data_year));
  const panel=page.getByRole('region',{name:'แหล่งข้อมูล Raster Dashboard',exact:true});
  async function loadGeo(status=200){const response=page.waitForResponse(r=>r.url().includes('/gis/published-geotiff')&&r.status()===status);await page.getByRole('button',{name:'ตรวจและแสดง Published Raster',exact:true}).click();return (await response).json();}
  const g=await loadGeo();const snapshot=page.getByLabel('Published GeoTIFF Snapshot',{exact:true});await snapshot.waitFor();
  check('real_geo_dto_science_unchanged',g.source_identity.edition_id===data.ge.id&&g.summary.statistics.mean===.75&&g.summary.statistics.valid_pixels===3&&g.summary.statistics.nodata_pixels===1&&g.summary.metadata.kelvin_to_celsius_count===0);
  await panel.getByText('ความพร้อมของฟีเจอร์วิเคราะห์ Published',{exact:true}).click();
  const availability=panel.getByRole('region',{name:'ความพร้อมของฟีเจอร์ Published',exact:true});
  check('geo_map_legend_summary_availability_one_snapshot',await availability.getAttribute('data-source-snapshot')===g.snapshot_id&&await panel.getAttribute('data-source-snapshot')===g.snapshot_id);
  check('geo_derived_features_explain_missing_inputs',(await availability.innerText()).includes('Timeseries / แนวโน้ม — ยังไม่รองรับ')&&(await availability.innerText()).includes('Ranking — ยังไม่รองรับ'));
  await page.screenshot({path:path.join(data.output,'a5-published-geotiff.png')});
  await page.getByLabel('เดือน Published',{exact:true}).selectOption('1');await loadGeo(404);
  check('geo_missing_month_clears_snapshot_without_annual_fallback',await snapshot.count()===0&&await availability.getAttribute('data-source-snapshot')==='');
  await page.setViewportSize({width:390,height:844});await panel.screenshot({path:path.join(data.output,'a5-mobile.png')});const box=await panel.boundingBox();
  check('mobile_unsupported_controls_usable',box.width>=250&&await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
  check('no_legacy_derived_api_in_published_mode',derived.length===0);check('no_uncaught_browser_errors',errors.length===0);
  await geo('withdrawal');await page.getByLabel('แหล่งข้อมูล Raster',{exact:true}).selectOption('legacy');
  }
 }catch(error){rows.push({name:step,status:'Fail',diagnostic:String(error.message).split('\n')[0].slice(0,180)});if(page)await page.screenshot({path:path.join(data.output,'a5-browser-failure.png')}).catch(()=>{});}
 finally{if(context)await context.close();await browser.close();}
 fs.writeFileSync(path.join(data.output,data.country_only?'browser-country-results.json':'browser-results.json'),JSON.stringify({rows,page_errors:errors,legacy_derived_requests_while_published:derived,mocked_api:false,external_https_blocked:true},null,2));
 console.log(JSON.stringify({rows}));if(rows.some(r=>r.status!=='Pass'))process.exitCode=1;
}
readline.createInterface({input:process.stdin}).once('line',line=>main(JSON.parse(line)).catch(()=>{console.log(JSON.stringify({code:'A5_BROWSER_FAILED'}));process.exitCode=1;}));
