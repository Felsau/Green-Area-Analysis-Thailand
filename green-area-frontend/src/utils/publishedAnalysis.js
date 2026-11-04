// Presentation contract only. Actual file verification and authorization stay
// in the existing Backend providers. No scientific measurements are calculated.
const hash=v=>typeof v==='string'&&/^[0-9a-f]{64}$/.test(v);
const text=v=>typeof v==='string'&&v.length>0;
const count=v=>Number.isInteger(v)&&v>=0;
const colour=v=>typeof v==='string'&&/^[0-9a-f]{6}$/i.test(v);
const sameLineage=(metadata,id)=>metadata&&['dataset_id','edition_id','validation_result_id','input_hash','source_sha256',
  'province','data_year','month','method_version'].every(k=>metadata[k]===id[k]);

export function publishedSnapshotMatches(bundle,expected={}){
  const id=bundle?.source_identity;
  if(!id||!hash(bundle.snapshot_id)||id.namespace!=='published'||id.scope!=='province'
    ||!['landuse','ndvi','lst'].includes(id.product)||!text(id.province)
    ||!Number.isInteger(id.data_year)||id.data_year<1980||id.data_year>2200||!count(id.month)||id.month>12
    ||!['dataset_id','edition_id','validation_result_id'].every(k=>text(id[k]))||!hash(id.input_hash)||!hash(id.source_sha256)
    ||bundle.complete_province_inventory!==false||bundle.local_only!==true
    ||Object.entries(expected).some(([k,v])=>id[k]!==v))return false;
  const summary=bundle.summary,meta=summary?.metadata;
  if(!sameLineage(meta,id)||meta.complete_province_inventory!==false)return false;
  if(id.product==='landuse')return id.month===0&&id.method_version==='ldd-source-area-v1'
    &&bundle.coverage_mode==='validated_source_footprint'&&bundle.geometry?.type==='FeatureCollection'
    &&Array.isArray(bundle.geometry.features)&&sameLineage(bundle.geometry.metadata,id)
    &&count(summary.feature_count)&&summary.feature_count>0&&summary.feature_count===bundle.geometry.features.length
    &&Number.isFinite(summary.total_area_m2)&&summary.total_area_m2>=0
    &&Array.isArray(bundle.legend)&&bundle.legend.length>0&&bundle.legend.every(v=>text(v.code)&&text(v.name_th)&&colour(v.color))
    &&!!summary.area_by_code_m2&&Object.values(summary.area_by_code_m2).every(v=>Number.isFinite(v)&&v>=0);
  const stats=summary.statistics,units=id.product==='ndvi'?'unitless':'celsius',p=bundle.publication_identity;
  return id.method_version==='geotiff-grid-celsius-v1'&&bundle.coverage_mode==='source_footprint_intersection'
    &&bundle.period_verified===false&&meta.period_verified===false&&stats?.units===units&&meta.output_units===units
    &&['mean','min','max'].every(k=>Number.isFinite(stats[k]))&&stats.min<=stats.max
    &&count(stats.valid_pixels)&&stats.valid_pixels>0&&count(stats.nodata_pixels)
    &&!!p&&sameLineage(p,id)&&p.product===id.product&&p.output_units===units&&p.period_verified===false
    &&hash(bundle.raster?.artifact_sha256)&&bundle.raster.artifact_sha256===p.artifacts?.[id.product+'_raster']?.sha256
    &&bundle.raster.render_crs==='EPSG:3857'&&bundle.raster.nodata_transparent===true
    &&count(bundle.raster.width)&&bundle.raster.width>0&&bundle.raster.width<=64&&count(bundle.raster.height)&&bundle.raster.height>0&&bundle.raster.height<=64
    &&typeof bundle.raster.png_base64==='string'&&bundle.raster.png_base64.length<=64000&&/^[A-Za-z0-9+/]+={0,2}$/.test(bundle.raster.png_base64)
    &&Array.isArray(bundle.raster.bounds)&&bundle.raster.bounds.length===4&&bundle.raster.bounds.every(Number.isFinite)
    &&bundle.legend?.units===units&&Number.isFinite(bundle.legend.min)&&Number.isFinite(bundle.legend.max)&&bundle.legend.min<bundle.legend.max
    &&Array.isArray(bundle.legend.palette)&&bundle.legend.palette.length>0&&bundle.legend.palette.every(colour);
}

const unsupported=[
  {key:'province',label:'วิเคราะห์จังหวัด / อำเภอ',reason:'ไฟล์ครอบคลุมเพียง Footprint ไม่รับรองพื้นที่ครบจังหวัด และยังไม่มีผลตัดขอบเขตอำเภอหรือพื้นที่ที่วาด'},
  {key:'compare',label:'เปรียบเทียบจังหวัด',reason:'ยังไม่มี NDVI และสัดส่วนพื้นที่สีเขียวที่ครอบคลุมจังหวัดด้วยช่วงเวลาและวิธีที่เทียบกันได้ ไม่ใช้ค่า Legacy มาปน'},
  {key:'trend',label:'Timeseries / แนวโน้ม',reason:'ต้องมีหลายช่วงเวลาที่สังเกตจริงและยืนยันได้ ไฟล์เดียวหรือปี/เดือนที่ระบุเองไม่ใช่อนุกรมเวลา'},
  {key:'ranking',label:'Ranking',reason:'ขาดข้อมูลพื้นที่สีเขียวเขตเมืองและประชากรที่ใช้ตัวหารเดียวกัน จึงยังจัดอันดับจังหวัดไม่ได้'},
  {key:'recommend',label:'จุดแนะนำ / Priority Score',reason:'ขาดชุด NDVI/LST ประชากร การเข้าถึง และปัจจัยความเหมาะสมที่จัดแนวพื้นที่และเวลาตรงกัน ไม่คำนวณคะแนนจากข้อมูลที่ขาด'},
  {key:'cooling',label:'ความเย็น / ความสัมพันธ์ NDVI–LST',reason:'ยังไม่มีคู่ข้อมูลและแบบจำลองที่ตรวจสอบร่วมกัน ไม่อนุมานความสัมพันธ์หรือเหตุและผลจากสรุปไฟล์'},
  {key:'saved',label:'วิเคราะห์พื้นที่ที่บันทึกไว้',reason:'รายการเดิมเก็บ Geometry ปี และผลวิเคราะห์เดิมไว้ครบ แต่ยังไม่ผูก Published Snapshot หรือผลตัด AOI ให้กลับไป Legacy เพื่อเปิดรายการเดิม'},
];

export function publishedAvailability(bundle,kind){
  const valid=publishedSnapshotMatches(bundle)&&((kind==='landuse')===(bundle?.source_identity?.product==='landuse'));
  return {snapshot_id:valid?bundle.snapshot_id:null,source:valid?bundle.source_identity:null,
    features:[{key:'map',label:'แผนที่ / Legend',status:valid?'supported':'unavailable',reason:valid?'ใช้ข้อมูลจาก Snapshot ปัจจุบัน เฉพาะขอบเขตไฟล์':'ยังไม่มี Published Snapshot ที่ตรงขอบเขตและพร้อมแสดงผล'},
      {key:'summary',label:kind==='landuse'?'สรุปรหัสและพื้นที่การใช้ที่ดิน':'สถิติพิกเซลที่มีข้อมูล / NoData',status:valid?'supported':'unavailable',reason:!valid?'ยังไม่มีสรุปที่ตรงกับ Published Snapshot':kind==='landuse'?'ใช้ Shape_Area เดิมและรหัส LDD ไม่ใช่ค่า NDVI':'ใช้สถิติจากไฟล์ที่ตรวจแล้ว NDVI ไม่มีหน่วย และ LST เป็น Celsius ไม่แปลง Kelvin ซ้ำ'},
      ...unsupported.map(f=>({...f,status:'unsupported'}))]};
}
