-- Migration 006: ตารางอ้างอิง provinces (normalization)
-- รวมข้อมูลจังหวัดที่เดิมกระจาย/ซ้ำหลายที่ (province TEXT ซ้ำทุกตาราง · ชื่อไทยใน
-- frontend constants · ภาคใน species.py) ให้เป็น single source of truth ตารางเดียว
-- แล้วให้ตารางอื่น FK อ้างอิง name_en (3NF — ตัด redundancy ของชื่อไทย/ภาค)
--
-- รันหลัง 005 · seed ครบ 77 จังหวัด generate จากไฟล์ต้นทางจริง (กันพิมพ์ผิด)
-- idempotent: CREATE IF NOT EXISTS + INSERT ... ON CONFLICT + FK ใน DO block

CREATE TABLE IF NOT EXISTS provinces (
  name_en TEXT PRIMARY KEY,    -- key ที่ทุกตารางใช้อยู่แล้ว
  name_th TEXT NOT NULL,
  region  TEXT NOT NULL        -- เหนือ / อีสาน / กลาง / ตะวันออก / ตะวันตก / ใต้
);

-- Seed 77 จังหวัด (en, th, region)
INSERT INTO provinces (name_en, name_th, region) VALUES
  ('Amnat Charoen', 'อำนาจเจริญ', 'อีสาน'),
  ('Ang Thong', 'อ่างทอง', 'กลาง'),
  ('Bangkok Metropolis', 'กรุงเทพมหานคร', 'กลาง'),
  ('Bueng Kan', 'บึงกาฬ', 'อีสาน'),
  ('Buri Ram', 'บุรีรัมย์', 'อีสาน'),
  ('Chachoengsao', 'ฉะเชิงเทรา', 'ตะวันออก'),
  ('Chai Nat', 'ชัยนาท', 'กลาง'),
  ('Chaiyaphum', 'ชัยภูมิ', 'อีสาน'),
  ('Chanthaburi', 'จันทบุรี', 'ตะวันออก'),
  ('Chiang Mai', 'เชียงใหม่', 'เหนือ'),
  ('Chiang Rai', 'เชียงราย', 'เหนือ'),
  ('Chon Buri', 'ชลบุรี', 'ตะวันออก'),
  ('Chumphon', 'ชุมพร', 'ใต้'),
  ('Kalasin', 'กาฬสินธุ์', 'อีสาน'),
  ('Kamphaeng Phet', 'กำแพงเพชร', 'กลาง'),
  ('Kanchanaburi', 'กาญจนบุรี', 'ตะวันตก'),
  ('Khon Kaen', 'ขอนแก่น', 'อีสาน'),
  ('Krabi', 'กระบี่', 'ใต้'),
  ('Lampang', 'ลำปาง', 'เหนือ'),
  ('Lamphun', 'ลำพูน', 'เหนือ'),
  ('Loei', 'เลย', 'อีสาน'),
  ('Lop Buri', 'ลพบุรี', 'กลาง'),
  ('Mae Hong Son', 'แม่ฮ่องสอน', 'เหนือ'),
  ('Maha Sarakham', 'มหาสารคาม', 'อีสาน'),
  ('Mukdahan', 'มุกดาหาร', 'อีสาน'),
  ('Nakhon Nayok', 'นครนายก', 'กลาง'),
  ('Nakhon Pathom', 'นครปฐม', 'กลาง'),
  ('Nakhon Phanom', 'นครพนม', 'อีสาน'),
  ('Nakhon Ratchasima', 'นครราชสีมา', 'อีสาน'),
  ('Nakhon Sawan', 'นครสวรรค์', 'กลาง'),
  ('Nakhon Si Thammarat', 'นครศรีธรรมราช', 'ใต้'),
  ('Nan', 'น่าน', 'เหนือ'),
  ('Narathiwat', 'นราธิวาส', 'ใต้'),
  ('Nong Bua Lam Phu', 'หนองบัวลำภู', 'อีสาน'),
  ('Nong Khai', 'หนองคาย', 'อีสาน'),
  ('Nonthaburi', 'นนทบุรี', 'กลาง'),
  ('Pathum Thani', 'ปทุมธานี', 'กลาง'),
  ('Pattani', 'ปัตตานี', 'ใต้'),
  ('Phangnga', 'พังงา', 'ใต้'),
  ('Phatthalung', 'พัทลุง', 'ใต้'),
  ('Phayao', 'พะเยา', 'เหนือ'),
  ('Phetchabun', 'เพชรบูรณ์', 'กลาง'),
  ('Phetchaburi', 'เพชรบุรี', 'ตะวันตก'),
  ('Phichit', 'พิจิตร', 'กลาง'),
  ('Phitsanulok', 'พิษณุโลก', 'กลาง'),
  ('Phra Nakhon Si Ayutthaya', 'พระนครศรีอยุธยา', 'กลาง'),
  ('Phrae', 'แพร่', 'เหนือ'),
  ('Phuket', 'ภูเก็ต', 'ใต้'),
  ('Prachin Buri', 'ปราจีนบุรี', 'ตะวันออก'),
  ('Prachuap Khiri Khan', 'ประจวบคีรีขันธ์', 'ตะวันตก'),
  ('Ranong', 'ระนอง', 'ใต้'),
  ('Ratchaburi', 'ราชบุรี', 'ตะวันตก'),
  ('Rayong', 'ระยอง', 'ตะวันออก'),
  ('Roi Et', 'ร้อยเอ็ด', 'อีสาน'),
  ('Sa Kaeo', 'สระแก้ว', 'ตะวันออก'),
  ('Sakon Nakhon', 'สกลนคร', 'อีสาน'),
  ('Samut Prakan', 'สมุทรปราการ', 'กลาง'),
  ('Samut Sakhon', 'สมุทรสาคร', 'กลาง'),
  ('Samut Songkhram', 'สมุทรสงคราม', 'กลาง'),
  ('Saraburi', 'สระบุรี', 'กลาง'),
  ('Satun', 'สตูล', 'ใต้'),
  ('Si Sa Ket', 'ศรีสะเกษ', 'อีสาน'),
  ('Sing Buri', 'สิงห์บุรี', 'กลาง'),
  ('Songkhla', 'สงขลา', 'ใต้'),
  ('Sukhothai', 'สุโขทัย', 'กลาง'),
  ('Suphan Buri', 'สุพรรณบุรี', 'กลาง'),
  ('Surat Thani', 'สุราษฎร์ธานี', 'ใต้'),
  ('Surin', 'สุรินทร์', 'อีสาน'),
  ('Tak', 'ตาก', 'ตะวันตก'),
  ('Trang', 'ตรัง', 'ใต้'),
  ('Trat', 'ตราด', 'ตะวันออก'),
  ('Ubon Ratchathani', 'อุบลราชธานี', 'อีสาน'),
  ('Udon Thani', 'อุดรธานี', 'อีสาน'),
  ('Uthai Thani', 'อุทัยธานี', 'กลาง'),
  ('Uttaradit', 'อุตรดิตถ์', 'เหนือ'),
  ('Yala', 'ยะลา', 'ใต้'),
  ('Yasothon', 'ยโสธร', 'อีสาน')
ON CONFLICT (name_en) DO UPDATE
  SET name_th = EXCLUDED.name_th, region = EXCLUDED.region;

-- FK: ตารางที่อ้างจังหวัด → provinces(name_en)
-- idempotent (ALTER ADD CONSTRAINT ไม่มี IF NOT EXISTS) · province nullable ใน
-- บางตาราง (saved_areas = custom polygon นอกจังหวัด) — FK ยอม NULL อยู่แล้ว
-- ⚠️ ต้อง seed provinces ครบก่อน (ด้านบน) ไม่งั้น row เดิมที่ชื่อไม่ตรงจะ block
--    ถ้า ALTER ใด error เพราะ cache เก่าชื่อเพี้ยน ลบ cache ตารางนั้นแล้วรันซ้ำได้
DO $$
DECLARE
  t TEXT;
  tables TEXT[] := ARRAY[
    'ndvi_annual', 'ndvi_monthly', 'district_ndvi_annual', 'district_ndvi_monthly',
    'province_lst_annual', 'province_lst_monthly', 'district_lst_annual',
    'district_lst_monthly', 'urban_ndvi_annual', 'planting_recommendations',
    'province_population', 'saved_areas'
  ];
  cname TEXT;
BEGIN
  FOREACH t IN ARRAY tables LOOP
    cname := 'fk_' || t || '_province';
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = cname) THEN
      EXECUTE format(
        'ALTER TABLE %I ADD CONSTRAINT %I FOREIGN KEY (province) REFERENCES provinces(name_en)',
        t, cname);
    END IF;
  END LOOP;
END $$;

-- index ช่วย JOIN provinces ↔ ตารางข้อมูล (province ถูก filter บ่อย)
CREATE INDEX IF NOT EXISTS idx_provinces_region ON provinces(region);
