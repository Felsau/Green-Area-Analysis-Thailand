// UI-only browser checks. Uses the same real local session and original geometry.
const path=require('node:path');

module.exports=async function uiChecks(page,data,check,mode='all'){
  if(mode!=='map'){
  await page.getByRole('tab',{name:'ชุดข้อมูล',exact:true}).click();
  const detail=page.getByRole('region',{name:'ชุดข้อมูลที่เลือก',exact:true});
  await detail.waitFor();
  check('ui_dataset_master_detail',await detail.getByRole('list',{name:'ขั้นตอนจัดการชุดข้อมูล'}).count()===1);
  check('ui_validation_is_not_activation',(await detail.innerText()).includes('ยังไม่เปิดใช้ข้อมูล'));
  check('ui_identifiers_not_headings',await page.locator('.gis-page h2,.gis-page h3,.gis-page h4').evaluateAll(nodes=>nodes.every(n=>!/[0-9a-f]{8}-[0-9a-f]{4}-/i.test(n.textContent))));
  const edition=detail.locator('.gis-edition').first();
  const editionId=await edition.getAttribute('data-edition-id');
  const history=page.waitForResponse(r=>new URL(r.url()).pathname===`/gis/editions/${editionId}/history`&&r.status()===200);
  await edition.getByRole('button',{name:'ดูประวัติ',exact:true}).click();
  await history;
  await edition.getByRole('heading',{name:'ประวัติฉบับที่เลือก',exact:true}).waitFor();
  check('ui_history_attached_to_edition',true);
  await edition.getByRole('button',{name:'ปิดประวัติ',exact:true}).click();
  await page.locator('.gis-page').evaluate(node=>node.scrollTop=0);
  await page.screenshot({path:path.join(data.output,'gis-workspace-desktop.png'),fullPage:true});
  await page.setViewportSize({width:390,height:844});
  await detail.locator('h2').scrollIntoViewIfNeeded();
  check('ui_mobile_no_page_overflow',await page.locator('.gis-page').evaluate(node=>node.scrollWidth<=node.clientWidth+1));
  check('ui_mobile_selected_detail_first',await page.locator('.gis-dataset-detail').evaluate(node=>getComputedStyle(node).gridRowStart==='1'));
  await page.screenshot({path:path.join(data.output,'gis-workspace-mobile.png'),fullPage:true});
  await page.setViewportSize({width:1366,height:1000});
  }
  if(mode==='workspace')return;
  await page.getByRole('button',{name:'กลับแผนที่',exact:true}).click();
  await page.locator('.context__sub').waitFor();
  await page.waitForTimeout(1100); // Original camera fly-to animation.

  async function point(districtName){
    return page.evaluate(async({province,districtName})=>{
      const [{WebMercatorViewport},turf,provinces,districts]=await Promise.all([
        import('/node_modules/.vite/deps/@deck__gl_core.js'),import('/node_modules/.vite/deps/@turf_turf.js'),
        fetch('/thailand.json').then(r=>r.json()),fetch('/thailand_districts.json').then(r=>r.json())]);
      const p=provinces.features.find(f=>f.properties.name===province);
      const d=districts.features.find(f=>f.properties.province===province&&f.properties.name===districtName);
      const [minX,minY,maxX,maxY]=turf.bbox(p),span=Math.max(maxX-minX,maxY-minY);
      const rect=document.querySelector('.canvas').getBoundingClientRect();
      const viewport=new WebMercatorViewport({width:rect.width,height:rect.height,longitude:(minX+maxX)/2,latitude:(minY+maxY)/2,
        zoom:Math.min(10,Math.max(6,Math.log2(4/span)+7)),pitch:40,bearing:0});
      const [x,y]=viewport.project(turf.pointOnFeature(d).geometry.coordinates);
      return {x:rect.left+x,y:rect.top+y,name:d.properties.name_th||d.properties.name};
    },{province:data.province,districtName});
  }
  await page.mouse.move(30,20);
  check('map_default_no_tooltip',await page.getByRole('tooltip').count()===0);
  const target=await point('BangKhoLaem');
  await page.mouse.move(target.x,target.y);
  await page.getByRole('tooltip').filter({hasText:target.name}).waitFor();
  check('map_real_hover_name',true);
  await page.screenshot({path:path.join(data.output,'map-hover.png'),fullPage:true});
  await page.mouse.click(target.x,target.y);
  await page.waitForFunction(()=>new URLSearchParams(location.search).get('d')==='BangKhoLaem');
  check('map_real_click_selection',true);
  await page.mouse.move(30,20);
  await page.getByRole('tooltip').waitFor({state:'hidden'});
  await page.screenshot({path:path.join(data.output,'map-no-persistent-labels.png'),fullPage:true});
  const touch=await point('BangRak');
  const cdp=await page.context().newCDPSession(page);
  await cdp.send('Emulation.setTouchEmulationEnabled',{enabled:true});
  await cdp.send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x:touch.x,y:touch.y}]});
  await cdp.send('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});
  await page.waitForFunction(()=>new URLSearchParams(location.search).get('d')==='BangRak');
  check('map_emulated_touch_selection',true);
  await cdp.send('Emulation.setTouchEmulationEnabled',{enabled:false});
  await page.locator('.usermenu__trigger').click();
  await page.getByRole('menuitem',{name:/จัดการข้อมูล GIS/}).click();
  await page.getByRole('button',{name:'สร้างชุดข้อมูล',exact:true}).waitFor();
};
