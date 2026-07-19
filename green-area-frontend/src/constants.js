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

export const INITIAL_VIEW_STATE = {
  longitude: 101.0,
  latitude: 13.0,
  zoom: 5.5,
  pitch: 25,
  bearing: 0,
};

export const CURRENT_YEAR = new Date().getFullYear();
export const AVAILABLE_YEARS = Array.from({ length: 6 }, (_, i) => CURRENT_YEAR - 5 + i);

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
