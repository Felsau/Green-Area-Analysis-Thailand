export const PROVINCE_TH = {
  "Amnat Charoen": "อำนาจเจริญ", "Ang Thong": "อ่างทอง",
  "Bangkok Metropolis": "กรุงเทพมหานคร", "Bueng Kan": "บึงกาฬ",
  "Buri Ram": "บุรีรัมย์", "Chachoengsao": "ฉะเชิงเทรา",
  "Chai Nat": "ชัยนาท", "Chaiyaphum": "ชัยภูมิ",
  "Chanthaburi": "จันทบุรี", "Chiang Mai": "เชียงใหม่",
  "Chiang Rai": "เชียงราย", "Chon Buri": "ชลบุรี",
  "Chumphon": "ชุมพร", "Kalasin": "กาฬสินธุ์",
  "Kamphaeng Phet": "กำแพงเพชร", "Kanchanaburi": "กาญจนบุรี",
  "Khon Kaen": "ขอนแก่น", "Krabi": "กระบี่",
  "Lampang": "ลำปาง", "Lamphun": "ลำพูน",
  "Loei": "เลย", "Lop Buri": "ลพบุรี",
  "Mae Hong Son": "แม่ฮ่องสอน", "Maha Sarakham": "มหาสารคาม",
  "Mukdahan": "มุกดาหาร", "Nakhon Nayok": "นครนายก",
  "Nakhon Pathom": "นครปฐม", "Nakhon Phanom": "นครพนม",
  "Nakhon Ratchasima": "นครราชสีมา", "Nakhon Sawan": "นครสวรรค์",
  "Nakhon Si Thammarat": "นครศรีธรรมราช", "Nan": "น่าน",
  "Narathiwat": "นราธิวาส", "Nong Bua Lam Phu": "หนองบัวลำภู",
  "Nong Khai": "หนองคาย", "Nonthaburi": "นนทบุรี",
  "Pathum Thani": "ปทุมธานี", "Pattani": "ปัตตานี",
  "Phangnga": "พังงา", "Phatthalung": "พัทลุง",
  "Phayao": "พะเยา", "Phetchabun": "เพชรบูรณ์",
  "Phetchaburi": "เพชรบุรี", "Phichit": "พิจิตร",
  "Phitsanulok": "พิษณุโลก", "Phra Nakhon Si Ayutthaya": "พระนครศรีอยุธยา",
  "Phrae": "แพร่", "Phuket": "ภูเก็ต",
  "Prachin Buri": "ปราจีนบุรี", "Prachuap Khiri Khan": "ประจวบคีรีขันธ์",
  "Ranong": "ระนอง", "Ratchaburi": "ราชบุรี",
  "Rayong": "ระยอง", "Roi Et": "ร้อยเอ็ด",
  "Sa Kaeo": "สระแก้ว", "Sakon Nakhon": "สกลนคร",
  "Samut Prakan": "สมุทรปราการ", "Samut Sakhon": "สมุทรสาคร",
  "Samut Songkhram": "สมุทรสงคราม", "Saraburi": "สระบุรี",
  "Satun": "สตูล", "Si Sa Ket": "ศรีสะเกษ",
  "Sing Buri": "สิงห์บุรี", "Songkhla": "สงขลา",
  "Sukhothai": "สุโขทัย", "Suphan Buri": "สุพรรณบุรี",
  "Surat Thani": "สุราษฎร์ธานี", "Surin": "สุรินทร์",
  "Tak": "ตาก", "Trang": "ตรัง",
  "Trat": "ตราด", "Ubon Ratchathani": "อุบลราชธานี",
  "Udon Thani": "อุดรธานี", "Uthai Thani": "อุทัยธานี",
  "Uttaradit": "อุตรดิตถ์", "Yala": "ยะลา",
  "Yasothon": "ยโสธร",
};

export const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000';
export const MAP_STYLE = 'https://basemaps.cartocdn.com/gl/positron-gl-style/style.json';
export const MAP_STYLE_DARK = 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json';

// แผนที่ฐานแบบภาพถ่ายดาวเทียม (Esri World Imagery) — เป็น style ของ MapLibre ที่เขียนเอง
// ทั้งก้อน เพราะ Esri ให้บริการเป็น XYZ raster ไม่ใช่ vector style เหมือน CARTO
//   · ไม่ต้องใช้ API key และ CSP ปัจจุบันอนุญาต img/connect https: อยู่แล้ว
//   · Esri เรียงไทล์เป็น /tile/{z}/{row}/{col} จึงต้องสลับเป็น {z}/{y}/{x}
//   · ซ้อนชั้น reference (ขอบเขต+ชื่อสถานที่) ทับไว้ ไม่งั้นภาพถ่ายล้วนจะหาจังหวัด/อำเภอ
//     ไม่เจอเลย — ชั้นนี้เป็น PNG โปร่งใส วางบนภาพถ่ายได้ตรง ๆ
// ประกาศเป็นค่าคงที่ระดับโมดูล → identity คงที่ ไม่ทำให้ maplibre reload style ทุก render
export const MAP_STYLE_SATELLITE = {
  version: 8,
  sources: {
    'esri-imagery': {
      type: 'raster',
      tiles: ['https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'],
      tileSize: 256,
      maxzoom: 19,
      attribution: 'Imagery © Esri, Maxar, Earthstar Geographics, GIS User Community',
    },
    'esri-reference': {
      type: 'raster',
      tiles: ['https://services.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}'],
      tileSize: 256,
      maxzoom: 19,
      attribution: 'Esri, Garmin, GeoTechnologies, Inc.',
    },
  },
  layers: [
    { id: 'esri-imagery', type: 'raster', source: 'esri-imagery' },
    { id: 'esri-reference', type: 'raster', source: 'esri-reference' },
  ],
};

export const INITIAL_VIEW_STATE = {
  longitude: 101.0,
  latitude: 13.0,
  zoom: 5.5,
  pitch: 25,
  bearing: 0,
};

export const CURRENT_YEAR = new Date().getFullYear();
export const AVAILABLE_YEARS = Array.from({ length: 6 }, (_, i) => CURRENT_YEAR - 5 + i);

// ปีแรกที่มีภาพ Sentinel-2 ใช้ได้ — จุดเริ่มของ time-lapse (FR-10) และฐานของ
// "ชุดข้อมูลรายปี" ที่โฆษณาบนหน้าแรก · ตัวเลขเดียวกันสองที่ ต้องไม่ hardcode แยก
export const DATA_START_YEAR = 2015;
export const DATA_YEAR_SPAN = CURRENT_YEAR - DATA_START_YEAR + 1;

// จำนวนอำเภอ/เขตทั้งประเทศ — ตรงกับ thailand_districts.json ที่ backend โหลด
// (dependencies._load_district_geometries · log "โหลดขอบเขต 928 อำเภอ")
export const TOTAL_DISTRICTS = 928;

// แหล่งข้อมูลการใช้ที่ดิน — ตรงกับ LANDUSE_SOURCES ฝั่ง backend (schema ผลลัพธ์เดียวกัน)
//   dynamic_world = ดาวเทียมจำแนกอัตโนมัติ รายปี ทั้งประเทศ
//   ldd           = ข้อมูลราชการ LDD 1:25,000 สำรวจภาคสนาม (มีรายละเอียด 96 ประเภท)
export const LANDUSE_SOURCES = [
  { id: 'dynamic_world', label: 'Dynamic World', hint: 'ดาวเทียม 10m · รายปี · ทั้งประเทศ' },
  { id: 'ldd', label: 'LDD ราชการ', hint: 'กรมพัฒนาที่ดิน 1:25,000 · ปี 2566' },
];
// จังหวัด (ชื่อ EN) ที่มีข้อมูล LDD ในระบบ — ตรงกับ LDD_COVERAGE_PROVINCES ฝั่ง backend
// ยังไม่ครอบคลุมจังหวัดนี้ → UI ไม่โชว์ตัวเลือก LDD (คงไว้ที่ Dynamic World)
export const LDD_PROVINCES = ['Bangkok Metropolis'];

// WHO urban green-space standard (m² per person) — single source of truth for
// deficit math + report copy. Mirrors WHO_STANDARD_M2 in the backend.
export const WHO_STANDARD_M2 = 9;
