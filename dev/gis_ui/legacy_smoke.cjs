// Real local APIs and original Dashboard; never substitutes analysis results.
const fs = require('node:fs'), path = require('node:path'), crypto = require('node:crypto');

module.exports = async function legacySmoke(page, data, check) {
  async function request(route, method='GET', body, identity='session') {
    return page.evaluate(async ({route,method,body,identity}) => {
      const {supabase}=await import('/src/lib/supabaseClient.js');
      const {data}=await supabase.auth.getSession();
      const token=identity==='session'?data.session.access_token:identity==='invalid'?'not-a-valid-jwt':null;
      const response=await fetch('http://127.0.0.1:55422'+route,{method,credentials:'omit',redirect:'error',
        headers:{...(token?{Authorization:'Bearer '+token}:{}),...(body?{'Content-Type':'application/json'}:{})},
        ...(body?{body:JSON.stringify(body)}:{})});
      const value=await response.json();
      return {status:response.status,body:value,userMatches:route==='/account/me'&&value.id===data.session.user.id};
    },{route,method,body,identity});
  }
  const profile=await request('/account/me');
  check('legacy_profile_real_auth_owner',profile.status===200&&profile.userMatches&&profile.body.role==='user');
  check('legacy_no_auth_denied',(await request('/account/me','GET',undefined,'none')).status===401);
  check('legacy_forged_jwt_denied',(await request('/account/me','GET',undefined,'invalid')).status===401);
  const province=encodeURIComponent(data.province);
  for(const route of ['/health','/cache/ndvi-latest','/cache','/cache/districts?province='+province,
    '/analysis/ranking?year=2024','/compare?provinces='+province+'&year=2024',
    '/timelapse/ndvi/provinces?start_year=2023&end_year=2024',
    '/timelapse/lst/provinces?start_year=2023&end_year=2024',
    '/analysis/context/'+province+'?year=2024','/analysis/districts/'+province+'?year=2024',
    '/analysis/cooling/'+province+'?year=2024','/analysis/timeseries/'+province+'?start_year=2023&end_year=2024',
    '/ndvi/'+province+'/compare?years=2023,2024','/saved-areas']) {
    check('legacy_read_'+route.split('?')[0],(await request(route)).status===200);
  }
  check('legacy_empty_cache_not_fake',(await request('/cache/ndvi-latest')).body.count===0);
  check('legacy_empty_ranking_not_fake',(await request('/analysis/ranking?year=2024')).body.total_cached===0);
  for(const route of ['/ndvi/'+province,'/lst/'+province,'/recommend/'+province,
    '/ndvi/'+province+'/districts/BangRak','/lst/'+province+'/districts/BangRak',
    '/analysis/urban-subset/'+province,'/maps/'+province+'/ndvi-tiles']) {
    const response=await request(route);
    check('legacy_explicit_block_'+route,response.status===503&&response.body.detail.code==='LOCAL_GEE_BLOCKED');
  }
  check('legacy_profile_write_blocked',(await request('/account/me','PATCH',{display_name:'Must not persist'})).body.detail.code==='LOCAL_READ_ONLY');
  check('legacy_saved_write_blocked',(await request('/saved-areas','POST',{})).body.detail.code==='LOCAL_READ_ONLY');

  const fixtures=await page.evaluate(async()=>{
    const out={};
    for(const name of ['thailand.json','thailand_districts.json']) {
      const response=await fetch('/'+name);const bytes=await response.arrayBuffer();
      const hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),b=>b.toString(16).padStart(2,'0')).join('');
      out[name]={sha256:hash,count:JSON.parse(new TextDecoder().decode(bytes)).features.length};
    }
    return out;
  });
  for(const [file,count] of [['thailand.json',77],['thailand_districts.json',928]]) {
    const digest=crypto.createHash('sha256').update(fs.readFileSync(path.join(data.repo,'green-area-frontend/public',file))).digest('hex');
    check('legacy_original_geometry_'+file,fixtures[file].count===count&&fixtures[file].sha256===digest);
  }

  await page.getByRole('button',{name:'กลับแผนที่',exact:true}).click();
  await page.getByRole('combobox').first().waitFor();
  check('legacy_dashboard_mounted',await page.locator('.canvas canvas').count()>0);
  check('legacy_local_scope_label',(await page.locator('.topbar__source').innerText()).includes('Live GEE ยังปิดอยู่'));
  await page.getByRole('combobox').first().fill(data.province);
  await page.getByRole('option').filter({hasText:data.province}).click();
  await page.waitForFunction(province=>new URLSearchParams(location.search).get('p')===province,data.province);
  check('legacy_province_ui_selection',true);
  await page.goto('http://127.0.0.1:3000/?'+new URLSearchParams({p:data.province,d:'BangRak',year:'2024'}));
  await page.locator('.context__sub').waitFor();
  check('legacy_district_deeplink_restored',new URL(page.url()).searchParams.get('d')==='BangRak');
  await page.screenshot({path:path.join(data.output,'legacy-dashboard.png'),fullPage:true});
  await page.locator('.usermenu__trigger').click();
  await page.getByRole('menuitem',{name:/จัดการข้อมูล GIS/}).click();
  await page.getByRole('button',{name:'สร้างชุดข้อมูล',exact:true}).waitFor();
  check('legacy_dashboard_to_gis',new URL(page.url()).searchParams.get('view')==='gis');
  await page.getByRole('button',{name:'กลับแผนที่',exact:true}).click();
  await page.locator('.context__sub').waitFor();
  check('legacy_gis_to_dashboard_keeps_district',new URL(page.url()).searchParams.get('d')==='BangRak');
  await page.locator('.usermenu__trigger').click();
  await page.getByRole('menuitem',{name:/จัดการข้อมูล GIS/}).click();
  await page.getByRole('button',{name:'สร้างชุดข้อมูล',exact:true}).waitFor();
};
