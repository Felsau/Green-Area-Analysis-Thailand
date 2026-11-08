// Build the two GIS handoff documents as .docx.
// Content mirrors docs/gis/handoff-2026-11-08-*.md in the repository.
const fs = require('fs');
const path = require('path');
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  HeadingLevel, AlignmentType, WidthType, BorderStyle, ShadingType, PageOrientation,
} = require('docx');

const THAI = 'Leelawadee UI';
const MONO = 'Consolas';
const CONTENT = 9026;           // A4 (11906) minus 1440 margins on each side, in DXA
const INK = '1A1A1A';
const MUTED = '595959';
const RULE = 'BFBFBF';
const HEAD_FILL = 'EFEFEF';

const font = name => ({ ascii: name, hAnsi: name, cs: name });

function run(text, o = {}) {
  return new TextRun({
    text,
    font: font(o.mono ? MONO : THAI),
    size: o.size || 24,
    sizeComplexScript: o.size || 24,
    bold: !!o.bold,
    color: o.color || INK,
  });
}

function para(text, o = {}) {
  return new Paragraph({
    children: Array.isArray(text) ? text : [run(text, o)],
    alignment: o.align,
    spacing: { before: o.before === undefined ? 0 : o.before, after: o.after === undefined ? 120 : o.after, line: o.line || 300 },
    indent: o.indent,
    border: o.border,
  });
}

function title(text) {
  return new Paragraph({
    children: [run(text, { size: 36, bold: true })],
    alignment: AlignmentType.CENTER,
    spacing: { after: 160, line: 320 },
  });
}

function heading(text) {
  return new Paragraph({
    children: [run(text, { size: 28, bold: true })],
    spacing: { before: 320, after: 140, line: 300 },
    border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: RULE, space: 4 } },
  });
}

function subheading(text) {
  return new Paragraph({
    children: [run(text, { size: 25, bold: true })],
    spacing: { before: 220, after: 100, line: 300 },
  });
}

function bullet(text, o = {}) {
  return new Paragraph({
    children: [run('–  ', o), run(text, o)],
    spacing: { after: 80, line: 300 },
    indent: { left: 360, hanging: 200 },
  });
}

// A fixed-width block for commands and their output. Shaded so it reads as
// quoted evidence rather than prose. Consolas carries no Thai glyphs, so these
// blocks stay ASCII and any explanation goes in a paragraph of its own.
function evidence(lines) {
  for (const line of lines) {
    if (/[฀-๿]/.test(line)) throw new Error('Thai text inside an evidence block: ' + line);
  }
  return lines.map((line, index) => new Paragraph({
    children: [run(line || ' ', { mono: true, size: 18, color: '2A2A2A' })],
    spacing: { before: index === 0 ? 60 : 0, after: index === lines.length - 1 ? 140 : 0, line: 240 },
    indent: { left: 200 },
    shading: { type: ShadingType.CLEAR, fill: 'F4F4F4', color: 'auto' },
  }));
}

function cell(content, o = {}) {
  const children = (Array.isArray(content) ? content : [content]).map((text, i) =>
    new Paragraph({
      children: [run(String(text), { bold: o.bold, size: o.size || 21 })],
      alignment: o.align,
      spacing: { before: i === 0 ? 40 : 0, after: 40, line: 260 },
    }));
  return new TableCell({
    children,
    width: { size: o.width, type: WidthType.DXA },
    shading: o.fill ? { type: ShadingType.CLEAR, fill: o.fill, color: 'auto' } : undefined,
    margins: { top: 60, bottom: 60, left: 110, right: 110 },
  });
}

// rows[0] is the header. widths must sum to CONTENT.
function table(widths, rows, o = {}) {
  return new Table({
    columnWidths: widths,
    width: { size: CONTENT, type: WidthType.DXA },
    borders: {
      top: { style: BorderStyle.SINGLE, size: 4, color: RULE },
      bottom: { style: BorderStyle.SINGLE, size: 4, color: RULE },
      left: { style: BorderStyle.SINGLE, size: 4, color: RULE },
      right: { style: BorderStyle.SINGLE, size: 4, color: RULE },
      insideHorizontal: { style: BorderStyle.SINGLE, size: 4, color: RULE },
      insideVertical: { style: BorderStyle.SINGLE, size: 4, color: RULE },
    },
    rows: rows.map((cells, r) => new TableRow({
      tableHeader: r === 0 && !o.noHeader,
      children: cells.map((c, i) => cell(c, {
        width: widths[i],
        bold: r === 0 && !o.noHeader,
        fill: r === 0 && !o.noHeader ? HEAD_FILL : undefined,
        align: o.align && o.align[i],
      })),
    })),
  });
}

function spacer(h = 160) {
  return new Paragraph({ children: [run(' ')], spacing: { after: h, line: 200 } });
}

function signatures() {
  return [
    spacer(260),
    para('ผู้ส่งมอบ ................................................................     วันที่ ........... / ........... / ...........'),
    spacer(200),
    para('ผู้รับมอบ ................................................................     วันที่ ........... / ........... / ...........'),
    spacer(200),
    para('ผู้รับทราบ (หัวหน้าโครงงาน) ...............................................     วันที่ ........... / ........... / ...........'),
  ];
}

function progressRows(codes) {
  const header = ['รหัส', 'ผู้รับผิดชอบ', 'วันที่เริ่ม', 'วันที่เสร็จ', 'ผลการตรวจ'];
  return [header, ...codes.map(c => [c, '', '', '', 'ผ่าน / ไม่ผ่าน'])];
}

function build(fileName, children) {
  const doc = new Document({
    creator: 'GreenLens project',
    title: fileName,
    styles: { default: { document: { run: { font: font(THAI), size: 24 } } } },
    sections: [{
      properties: {
        page: {
          size: { width: 11906, height: 16838, orientation: PageOrientation.PORTRAIT },
          margin: { top: 1440, bottom: 1440, left: 1440, right: 1440 },
        },
      },
      children,
    }],
  });
  return Packer.toBuffer(doc).then(buf => {
    fs.writeFileSync(fileName, buf);
    console.log('wrote', fileName, buf.length, 'bytes');
  });
}

// ─────────────────────────────────────────────────────────────────────────
// เอกสารฉบับที่ 1 — สภาพแวดล้อมการทำงานที่ทำซ้ำได้
// ─────────────────────────────────────────────────────────────────────────
const docB = [
  title('เอกสารส่งมอบงาน'),
  para([run('ฉบับที่ 1 — สภาพแวดล้อมการทำงานที่ทำซ้ำได้ (Reproducible Runtime)', { size: 26, bold: true, color: MUTED })],
    { align: AlignmentType.CENTER, after: 300 }),

  table([2200, 6826], [
    ['หัวข้อ', 'รายละเอียด'],
    ['วันที่จัดทำ', '8 พฤศจิกายน 2569'],
    ['ผู้ส่งมอบ', '.............................................. (ระบุชื่อ-นามสกุล)'],
    ['ผู้รับมอบ', '.............................................. (ระบุชื่อ-นามสกุล)'],
    ['ขอบเขตงาน', 'การทำให้ระบบ GIS ประกอบขึ้นใหม่และทำงานได้บนเครื่องอื่น'],
    ['บรานช์ที่เกี่ยวข้อง', 'gis-unlock (อยู่บน GitHub แล้ว) ต่อยอดจาก feature/gis-data-management'],
    ['สถานะ', 'ยังไม่รวมเข้ากับบรานช์หลัก (main)'],
  ]),
  spacer(),

  heading('1. บทสรุปสำหรับผู้รับมอบ'),
  para('ระบบจัดการข้อมูล GIS ได้รับการพัฒนาจนทำงานได้ครบวงจรบนเครื่องของผู้พัฒนา และมีชุดทดสอบอัตโนมัติจำนวน 2,089 รายการที่ผ่านการตรวจสอบทั้งหมดบนระบบตรวจอัตโนมัติของ GitHub'),
  para('อย่างไรก็ตาม ส่วนประกอบที่จำเป็นต่อการรันระบบบางรายการไม่ได้ถูกบันทึกไว้ในคลังโค้ด ทำให้บุคคลอื่นไม่สามารถประกอบระบบขึ้นมาใหม่ได้ งานที่ส่งมอบตามเอกสารฉบับนี้คือการปิดช่องว่างดังกล่าว'),
  para('งานทั้งหมดเป็นงานเขียนโค้ดและตั้งค่า ซึ่งไม่ขึ้นกับการตัดสินใจของผู้ใด สามารถเริ่มดำเนินการได้ทันที และมีเกณฑ์ตัดสินความสำเร็จที่ชัดเจนจากชุดทดสอบที่มีอยู่แล้ว'),

  heading('2. ปัญหาที่ตรวจพบ พร้อมหลักฐาน'),

  subheading('2.1 ไม่มีผู้ใดสามารถรันกระบวนการประมวลผล (worker) ได้ นอกจากเครื่องของผู้พัฒนาเดิม'),
  para('ระบบเรียกใช้ container image ด้วยค่า digest โดยตรง โดยไม่มีชื่อกำกับและไม่มีไฟล์ Dockerfile ประกอบ'),
  ...evidence([
    'dev/gis_local/manage.py:47   WORKER_IMAGE = "sha256:fca4560d8a0d...aa04c9"',
    'dev/gis_local/manage.py:48   GEE_MOCK_WORKER_IMAGE = "sha256:7557955c9e2c...9566674"',
  ]),
  para('ผลการตรวจสอบบนเครื่องผู้จัดทำเอกสาร'),
  ...evidence([
    '$ find . -iname "Dockerfile*" -not -path "*/node_modules/*"',
    './green-area-backend/Dockerfile',
    './green-area-frontend/Dockerfile',
    '',
    '$ docker image inspect sha256:fca4560d8a0d...aa04c9',
    'NOT ON THIS MACHINE',
    '$ docker image inspect sha256:7557955c9e2c...9566674',
    'NOT ON THIS MACHINE',
  ]),
  para('ไฟล์ Dockerfile ที่พบเป็นของเว็บเซอร์วิสและของส่วนหน้าเว็บเท่านั้น ไม่พบของ worker และ image ทั้งสองรายการไม่มีอยู่บนเครื่องที่ตรวจสอบ'),
  para('เอกสาร docs/gis/a6-3-handoff.md บันทึกไว้เพียงว่าใช้ digest ใด แต่ไม่ได้ระบุวิธีสร้าง'),
  para([run('ผลกระทบ  ', { bold: true }), run('หาก image ดังกล่าวสูญหาย จะไม่มีวิธีสร้างขึ้นใหม่ให้เหมือนเดิม')]),

  subheading('2.2 สภาพแวดล้อมของ sandbox ก็ประกอบขึ้นใหม่ไม่ได้เช่นกัน'),
  para('ไฟล์ dev/gis_local/compose.yaml กำหนด image ผ่านตัวแปรสภาพแวดล้อมแบบบังคับ'),
  ...evidence([
    'image: ${GIS_LOCAL_DB_IMAGE:?pinned image required}',
    'image: ${GIS_LOCAL_AUTH_IMAGE:?pinned image required}',
    'image: ${GIS_LOCAL_REST_IMAGE:?pinned image required}',
    'image: ${GIS_LOCAL_GATEWAY_IMAGE:?pinned image required}',
  ]),
  para('ค้นทั้งคลังโค้ดแล้วไม่พบค่าจริงของตัวแปรทั้งสี่รายการ จึงไม่สามารถสั่ง docker compose up ได้'),

  subheading('2.3 ค่า hash ที่ตรึงไว้ขึ้นกับไลบรารีของระบบ ไม่ใช่เพียงรุ่นของแพ็กเกจ'),
  para('ชุดทดสอบ test_v1_artifacts_of_existing_fixtures_are_byte_identical ตรวจว่าผลลัพธ์จากการแปลงไฟล์ shapefile ต้องมีค่า hash ตรงกับที่ตรึงไว้ทุกไบต์ ผลการทดลองเปรียบเทียบสามสภาพแวดล้อม'),
  table([3000, 4026, 2000], [
    ['สภาพแวดล้อม', 'รุ่นไลบรารี', 'ผลการทดสอบ'],
    ['python:3.12-slim (Docker)', 'fiona 1.10.1 / GDAL 3.9.2, shapely 2.2.0 / GEOS 3.14.1', 'ผ่าน'],
    ['GitHub ubuntu-24.04', 'รุ่นเดียวกันทุกรายการ (ไฟล์ wheel เดียวกัน)', 'ไม่ผ่าน'],
    ['Windows 11', 'รุ่นเดียวกัน แต่ wheel คนละ build', 'ไม่ผ่าน'],
  ], { align: [null, null, AlignmentType.CENTER] }),
  spacer(100),
  para('ตัวอย่างค่าที่ต่างกันบน GitHub runner'),
  ...evidence([
    'expected  c8201dded27c987f7d2979cf78b33fcb987289bf8acbbed56ad836d43a623085',
    'actual    12ff267b84767b20daef64698262078659ee3e8848bc359953bc5cc485b90a41',
  ]),
  para([run('ข้อสรุป  ', { bold: true }), run('การตรึงรุ่นไลบรารีในไฟล์ requirements-native.txt เป็นสิ่งจำเป็นแต่ยังไม่เพียงพอ ต้องตรึงทั้ง image จึงจะรับประกันผลลัพธ์ได้ ปัจจุบันชุดทดสอบนี้ถูกตั้งให้ข้ามโดยอัตโนมัติ และจะทำงานก็ต่อเมื่อประกาศตัวแปร GIS_NATIVE_RUNTIME=pinned เท่านั้น')]),

  subheading('2.4 ไฟล์ที่ผู้ใช้อัปโหลดถูกเก็บบนดิสก์ของเครื่อง'),
  para('ไฟล์ gis_ldd_storage.py และ gis_geotiff_storage.py เขียนไฟล์ลงดิสก์พร้อมไฟล์ owner.json กำกับความเป็นเจ้าของ และตรวจสอบค่า hash ทุกครั้งที่อ่าน (รหัสข้อผิดพลาด GIS_LDD_INTEGRITY) เมื่อนำขึ้นโฮสต์ประเภท Render ดิสก์จะถูกล้างทุกครั้งที่เริ่มระบบใหม่'),

  heading('3. รายการงานที่ส่งมอบ'),
  para([run('หมายเหตุ  ', { bold: true }), run('วันกำหนดส่งเป็นข้อเสนอเบื้องต้น ขอให้ยืนยันร่วมกับหัวหน้าโครงงานอีกครั้ง')], { color: MUTED }),
  spacer(80),
  table([700, 2500, 2400, 2226, 1200], [
    ['รหัส', 'งาน', 'สิ่งที่ต้องส่ง', 'เกณฑ์ว่าเสร็จ', 'กำหนดส่ง'],
    ['B1', 'บันทึก image ที่ใช้อยู่ลงคลังโค้ด', 'ไฟล์ dev/gis_local/images.json ระบุ digest ทั้ง 6 รายการ (sandbox 4 + worker 2)', 'สั่ง docker compose up ได้โดยไม่ต้องสอบถามผู้ใด', '12 พ.ย. 2569'],
    ['B2', 'สร้าง Dockerfile ของ worker', 'green-area-backend/gis_worker/Dockerfile พร้อมคำสั่ง build', 'รันชุดทดสอบใน image นั้นโดยตั้ง GIS_NATIVE_RUNTIME=pinned แล้วผ่านทุกข้อ', '20 พ.ย. 2569'],
    ['B3', 'ตัวรัน migration สำหรับฐานข้อมูลบนคลาวด์', 'สคริปต์ติดตั้ง migration 027–048 รวดเดียว พร้อมบันทึก ledger', 'ติดตั้งบนฐานข้อมูลเปล่าได้สำเร็จ และ gis_readiness() รายงานตัวตนถูกต้อง', '27 พ.ย. 2569'],
    ['B4', 'ย้ายที่จัดเก็บไฟล์อัปโหลด', 'แก้ไข gis_ldd_storage.py และ gis_geotiff_storage.py ให้เก็บบนบริการภายนอก', 'ชุดทดสอบเดิมผ่านทั้งหมด และการตรวจสอบ hash ยังทำงาน', '11 ธ.ค. 2569'],
  ]),

  heading('4. รายละเอียดประกอบรายการงาน'),
  subheading('งาน B1'),
  para('ขอค่า digest จากผู้พัฒนาเดิม แล้วบันทึกลงคลังโค้ด เป็นงานที่ใช้เวลาไม่นาน แต่ควรดำเนินการก่อนงานอื่นทั้งหมด เนื่องจากปัจจุบันข้อมูลนี้อยู่ในความครอบครองของบุคคลเพียงผู้เดียว'),

  subheading('งาน B2'),
  para('สูตรต่อไปนี้ผ่านการทดสอบแล้ว และสามารถใช้เป็นจุดตั้งต้นได้'),
  ...evidence([
    'FROM python:3.11-slim',
    'RUN apt-get update && apt-get install -y --no-install-recommends libexpat1 \\',
    '    && rm -rf /var/lib/apt/lists/*',
    'COPY requirements-native.txt .',
    'RUN pip install --no-cache-dir -r requirements-native.txt',
    'ENV GIS_NATIVE_RUNTIME=pinned',
  ]),
  para('ยืนยันแล้วว่าได้ Rasterio 1.4.4 / GDAL 3.10.3, Fiona 1.10.1 / GDAL 3.9.2, Shapely 2.2.0 / GEOS 3.14.1 และ NumPy 2.4.6 ซึ่งตรงกับที่บันทึกไว้ใน docs/gis/t3-remediation-handoff.md ทุกรายการ'),
  para([run('ข้อควรระวัง  ', { bold: true }), run('การสร้าง image สำเร็จไม่ได้หมายความว่าถูกต้อง ต้องผ่านชุดทดสอบตามข้อ 2.3 ด้วย หากไม่ผ่าน แสดงว่า image ยังไม่ตรงกับสภาพแวดล้อมที่ค่า hash ถูกตรึงไว้')]),

  subheading('งาน B3'),
  para('ปัจจุบันการติดตั้ง migration กระจายอยู่ในไฟล์ dev/gis_local/*_local.py ประมาณ 8 ไฟล์ โดยแต่ละไฟล์ฝังหมายเลขเวอร์ชันของตนเอง ยังไม่มีตัวรันเดียวที่ครอบคลุม 027 ถึง 048'),
  para('ตัวรันต้องประกาศค่าสองรายการก่อนรันเนื้อ migration'),
  ...evidence([
    "SELECT set_config('gis.cluster_name', '<project-ref>', true);",
    "SELECT set_config('gis.mode', 'cloud', true);",
  ]),
  para('โดย <project-ref> คือรหัสโครงการของ Supabase ซึ่งเป็นตัวอักษรพิมพ์เล็ก 20 ตัว หากไม่ประกาศค่าทั้งสอง ระบบจะถือว่าเป็น sandbox ในเครื่อง ซึ่งเป็นพฤติกรรมเดิมที่ยังคงไว้'),
  para([run('สิ่งที่ต้องตรวจสอบก่อนเริ่ม (ควรเสร็จภายใน 11 พ.ย. 2569 เนื่องจากกระทบงานอื่นทั้งหมด)', { bold: true })]),
  bullet('ฐานข้อมูล Supabase ของโครงงานเป็น PostgreSQL รุ่น 17 ขึ้นไปหรือไม่ เนื่องจาก migration 027 กำหนดเงื่อนไข server_version_num >= 170000 หากไม่ถึงจะติดตั้งไม่ได้'),
  bullet('สิทธิ์ในการสร้าง role เนื่องจาก migration 027 และ 043 ถึง 047 มีคำสั่ง CREATE ROLE สำหรับ gis_owner, gis_worker, gis_native_worker และ authenticator ต้องตรวจสอบว่าบัญชีที่ใช้มีสิทธิ์เพียงพอ หากไม่มี ต้องแยกออกเป็นขั้นตอนตั้งค่าต่างหาก'),

  subheading('งาน B4'),
  para('การย้ายที่จัดเก็บต้องคงกลไกตรวจสอบความถูกต้องของไฟล์เดิมไว้ทั้งหมด ไม่อนุญาตให้ตัดการตรวจสอบค่า hash ออกเพื่อความสะดวก'),

  heading('5. สิ่งที่จัดเตรียมไว้ให้แล้ว'),
  table([4500, 4526], [
    ['รายการ', 'สถานะ'],
    ['requirements-native.txt ระบุรุ่นไลบรารีที่ตรวจสอบแล้ว', 'เพิ่มเข้าคลังโค้ดแล้ว'],
    ['ขั้นตอนติดตั้งไลบรารีในระบบตรวจอัตโนมัติ', 'เพิ่มใน .github/workflows/ci.yml แล้ว'],
    ['ช่องทางประกาศเป้าหมาย (GIS_TARGET, GIS_API_URL และอื่น ๆ)', 'ใช้งานได้แล้ว ดู green-area-backend/.env.example'],
    ['ตัวอย่างการตั้งค่าฝั่งเว็บ', 'ดู green-area-frontend/.env.example'],
    ['ระบบตรวจอัตโนมัติ (CI)', 'แก้ไขจนผ่านทุกขั้นตอนแล้ว'],
  ]),

  heading('6. วิธีตรวจสอบสภาพปัจจุบันด้วยตนเอง'),
  ...evidence([
    'git clone <repo> && cd <repo>',
    'git checkout gis-unlock',
    '',
    'cd green-area-backend',
    'pip install -r requirements.txt',
    'pip install -r requirements-native.txt',
    'ruff check .',
    'pytest tests/ -q',
    '',
    'cd ../green-area-frontend',
    'npm ci',
    'npx eslint src --max-warnings 0',
    'npm test',
    'npm run build',
  ]),
  para('เกณฑ์ที่ถือว่าผ่าน'),
  bullet('การติดตั้ง requirements-native.txt ต้องมี libexpat1 อยู่ในระบบก่อน'),
  bullet('คำสั่ง ruff check . ต้องแสดงข้อความ All checks passed'),
  bullet('คำสั่ง pytest ต้องไม่มีรายการที่ไม่ผ่าน'),
  bullet('คำสั่ง eslint ต้องไม่มีข้อผิดพลาดและไม่มีคำเตือน'),

  heading('7. แบบบันทึกความคืบหน้า'),
  table([900, 2300, 1800, 1800, 2226], progressRows(['B1', 'B2', 'B3', 'B4']),
    { align: [AlignmentType.CENTER, null, AlignmentType.CENTER, AlignmentType.CENTER, AlignmentType.CENTER] }),
  ...signatures(),
];

// ─────────────────────────────────────────────────────────────────────────
// เอกสารฉบับที่ 2 — สัญญาวิธีคำนวณและการอนุมัติประมวลผลจริง
// ─────────────────────────────────────────────────────────────────────────
const docA = [
  title('เอกสารส่งมอบงาน'),
  para([run('ฉบับที่ 2 — สัญญาวิธีคำนวณและการอนุมัติประมวลผลจริง', { size: 26, bold: true, color: MUTED })],
    { align: AlignmentType.CENTER, after: 300 }),

  table([2200, 6826], [
    ['หัวข้อ', 'รายละเอียด'],
    ['วันที่จัดทำ', '8 พฤศจิกายน 2569'],
    ['ผู้ส่งมอบ', '.............................................. (ระบุชื่อ-นามสกุล)'],
    ['ผู้รับมอบ', '.............................................. (ผู้พัฒนาบรานช์ feature/gis-data-management)'],
    ['ขอบเขตงาน', 'การตัดสินใจเชิงออกแบบที่ค้างอยู่ และการรวมบรานช์เข้ากับงานหลัก'],
    ['บรานช์ที่เกี่ยวข้อง', 'gis-unlock (อยู่บน GitHub แล้ว) ต่อยอดจาก feature/gis-data-management'],
    ['สถานะ', 'ยังไม่รวมเข้ากับบรานช์หลัก (main)'],
  ]),
  spacer(),

  heading('1. บทสรุปสำหรับผู้รับมอบ'),
  para('ระหว่างวันที่ 7 ถึง 8 พฤศจิกายน 2569 ได้มีการต่อยอดงานบนบรานช์ feature/gis-data-management เพื่อให้ระบบสามารถทำงานกับฐานข้อมูลที่ไม่ใช่ sandbox ในเครื่องได้ รวม 6 commit บนบรานช์ใหม่ชื่อ gis-unlock'),
  para('การเปลี่ยนแปลงทั้งหมดคงพฤติกรรมเดิมของ sandbox ไว้ครบถ้วน และไม่ต้องแก้ไขสคริปต์ในโฟลเดอร์ dev แม้แต่ไฟล์เดียว อย่างไรก็ตามมีผลข้างเคียงหนึ่งรายการที่ต้องดำเนินการ ตามข้อ 2.2'),
  para('งานที่ส่งมอบตามเอกสารฉบับนี้เป็นเรื่องที่ต้องใช้ความเข้าใจในสิ่งที่ผู้รับมอบออกแบบไว้เอง จึงไม่สามารถมอบหมายให้ผู้อื่นตัดสินใจแทนได้'),

  heading('2. สิ่งที่เปลี่ยนแปลงแล้ว และผลกระทบต่อผู้รับมอบ'),

  subheading('2.1 รายการ commit บนบรานช์ gis-unlock'),
  table([1600, 7426], [
    ['commit', 'สาระสำคัญ'],
    ['185f7a6', 'รวมตัวตนของเป้าหมายไว้ที่ไฟล์ gis_target.py แทนการเขียนค่าคงที่กระจายในหลายไฟล์'],
    ['27fcf3f', 'ปรับ migration 027 ถึง 048 ให้ติดตั้งบนฐานข้อมูลที่ตั้ง cluster_name ไม่ได้'],
    ['e9c4c97', 'ปรับ main.py และส่วนหน้าเว็บให้รองรับเป้าหมายที่ประกาศผ่านการตั้งค่า'],
    ['fc36d6d', 'แก้ไขระบบตรวจอัตโนมัติ (CI) ให้ผ่านทุกขั้นตอน'],
    ['6f520b0', 'ขยายขอบเขตการตรวจอัตโนมัติให้ครอบคลุมบรานช์ที่ใช้งานจริง'],
    ['2a80643', 'เอกสารส่งมอบงาน และปรับชุดทดสอบที่ยืนยันค่าไบต์'],
  ]),

  subheading('2.2 ผลข้างเคียงที่ต้องดำเนินการ — sandbox เดิมใช้งานต่อไม่ได้'),
  para('migration 027 ถูกแก้ไข ส่งผลให้ค่า checksum ที่ตรึงต่อกันเป็นลูกโซ่ต้องคำนวณใหม่ทั้งหมด ไฟล์ที่ได้รับผลกระทบ'),
  ...evidence([
    'migrations/  027, 030, 031, 032, 033, 034, 035, 036, 037, 038,',
    '             039, 040, 041, 042, 043, 044, 045, 046, 047, 048',
    'tests/       test_gis_migration_runner.py, test_gee_dashboard_processing.py',
  ]),
  para([run('สิ่งที่ต้องดำเนินการ  ', { bold: true }), run('ตาราง gis.schema_migrations ใน sandbox T0 เดิมจะไม่ตรงกับไฟล์ใหม่ จึงต้องสร้าง T0 ขึ้นใหม่ โดยโค้ดและสคริปต์ของผู้รับมอบไม่ต้องแก้ไข กระทบเฉพาะฐานข้อมูลเท่านั้น')]),
  para('ตรวจสอบรายการที่เปลี่ยนแปลงได้ด้วยคำสั่ง'),
  ...evidence(['git diff b9b5b3a HEAD -- green-area-backend/migrations']),

  subheading('2.3 เหตุผลของการแก้ไข migration 027'),
  para('cluster_name เป็นค่าตั้งระดับ postmaster ซึ่งกำหนดได้เฉพาะในไฟล์ postgresql.conf พร้อมการเริ่มบริการฐานข้อมูลใหม่ บริการแบบ Supabase Cloud จึงไม่สามารถตั้งค่านี้ได้'),
  para([run('หลักฐาน  ', { bold: true }), run('นำ migration 027 ฉบับเดิมไปติดตั้งบน PostgreSQL 17 มาตรฐาน')]),
  ...evidence(['ERROR: GIS_LOCAL_TARGET_REQUIRED']),
  para('หลังการแก้ไข ตัวรันจะประกาศค่า gis.cluster_name และ gis.mode เอง แล้วบันทึกลงตาราง gis.environment โดยการไม่ประกาศค่ายังคงหมายถึง sandbox เหมือนเดิม และ sandbox ยังต้องพิสูจน์ตนเองกับ postmaster เช่นเดิม'),
  para('ผลการทดสอบบน container PostgreSQL 17 จำนวน 5 กรณี'),
  table([6026, 3000], [
    ['กรณีทดสอบ', 'ผลลัพธ์'],
    ['ไม่ประกาศค่าใด และ postmaster ไม่ใช่ sandbox', 'ปฏิเสธ'],
    ['ประกาศ sandbox แต่ postmaster ไม่ใช่ sandbox', 'ปฏิเสธ'],
    ['ประกาศ project ref แต่ mode เป็น local', 'ปฏิเสธ'],
    ['ไม่ประกาศค่าใด และ postmaster เป็น sandbox (ทางเดิม)', 'ติดตั้งครบ 027–048'],
    ['ประกาศ cloud และไม่มี cluster_name', 'ติดตั้งครบ 027–048'],
  ], { align: [null, AlignmentType.CENTER] }),

  heading('3. ปัญหาที่ตรวจพบ พร้อมหลักฐาน'),

  subheading('3.1 การรวม 78f0219 กระทบโครงสร้างที่ถูกอ่านด้วย AST มิใช่เพียงค่า hash'),
  para('commit 78f0219 บนบรานช์ main ซึ่งแก้ไขข้อผิดพลาดการวัด 4 รายการ ได้ปรับโครงสร้างของโค้ดที่ไฟล์ gis_worker/processing_provider.py อ่านค่าด้วย ast ในช่วงบรรทัดที่ 145 ถึง 190'),
  table([2600, 3300, 3126], [
    ['จุดตรวจสอบ', 'รูปแบบที่ตัวอ่านคาดหวัง', 'รูปแบบหลังการรวม'],
    ['_mask_landsat_clouds', 'bitwiseAnd(1 << n)', 'bitwiseAnd(_LANDSAT_CLOUD_BITMASK) ซึ่งไม่ใช่ ast.BinOp'],
    ['S2_CLOUD_FILTER_PCT ใน compute.py', 'ค่าคงที่ระดับโมดูล', 'เปลี่ยนเป็น from gee_utils import ...'],
    ['ฟิลเตอร์เมฆใน _compute_ndvi_monthly', 'CLOUDY_PIXEL_PERCENTAGE ภายในฟังก์ชัน', 'ย้ายไปอยู่ใน s2_clean_collection()'],
  ]),
  spacer(100),
  para('นอกจากนี้ค่าทางวิทยาศาสตร์เปลี่ยนแปลงจริง ได้แก่ bit สำหรับ mask เมฆของ Landsat จาก (3, 4) เป็น (1, 2, 3, 4) ขณะที่ไฟล์ method_registry.py ประกาศไว้ว่า lst_mask_bits เท่ากับ (3, 4)'),
  para([run('ประเด็นที่ต้องตัดสินใจ  ', { bold: true }), run('ค่าที่แก้ไขให้ถูกต้องแล้ว ยังถือเป็น legacy-v1 อยู่หรือไม่ หรือต้องกำหนดเป็นเวอร์ชันวิธีคำนวณใหม่')]),
  para([run('ข้อควรระวัง  ', { bold: true }), run('78f0219 ยังไม่ได้อยู่ในสายของบรานช์ gis-unlock ค่า hash ที่ตรึงไว้จึงยังตรงกับไฟล์บนบรานช์ ห้ามปรับค่า hash ก่อนการรวมบรานช์ เพราะจะทำให้ชุดทดสอบไม่ผ่านโดยไม่จำเป็น')]),

  subheading('3.2 การประมวลผล GEE จริงถูกปิดไว้ในระดับโครงสร้างฐานข้อมูล'),
  para('ค่าที่บ่งชี้ว่าการประมวลผลจริงยังไม่ได้รับอนุมัติ ปรากฏในหลายตำแหน่ง'),
  table([3800, 5226], [
    ['ตำแหน่ง', 'สิ่งที่กำหนดไว้'],
    ['migrations/035, 043, 044, 045', "กำหนด 'live_enabled', false ในผลลัพธ์ readiness ทุกรายการ"],
    ['migrations/045', 'ค่าตั้งต้นของระเบียนความปลอดภัยเป็น kind: "unapproved"'],
    ['gis_worker/gee_execution_safety.py:33', 'live_enabled: Literal[False] = False'],
    ['routers/gis.py:76', "result['gee_live_enabled'] = False"],
  ]),
  spacer(100),
  para('และ worker ทุกรายการกำหนดให้ค่านี้ต้องเป็น False จึงจะยอมทำงาน'),
  para([run('ประเด็นที่ต้องตัดสินใจ  ', { bold: true }), run('จะเปิดการประมวลผลจริงที่เผยแพร่ผลได้เมื่อใด ผู้ใดเป็นผู้อนุมัติ และต้องใช้หลักฐานใดประกอบ ตราบที่ยังไม่มีการตัดสินใจ ระบบจะให้ผลเฉพาะแบบสังเคราะห์เท่านั้น ไม่ว่าจะติดตั้งที่ใด')]),

  subheading('3.3 worker จำนวน 5 รายการผูกกับโหมด local_synthetic'),
  para('ไฟล์ processing_worker.py, ldd_worker.py, ldd_prepare_worker.py, geotiff_worker.py และ geotiff_prepare_worker.py กำหนดเงื่อนไขให้ปฏิเสธการทำงานเมื่อ mode ไม่เท่ากับ local_synthetic'),
  para('เนื่องจาก migration 027 ผูก cluster_name กับ mode ไว้ด้วยกันผ่านเงื่อนไข CHECK ฐานข้อมูลบนคลาวด์จะมี mode เป็น cloud เสมอ worker ทั้งห้ารายการจึงปฏิเสธการทำงานเสมอ'),
  para([run('ประเด็นที่ต้องตัดสินใจ  ', { bold: true }), run('worker ใดควรทำงานบนคลาวด์ และ worker ใดควรทำงานเฉพาะใน sandbox ตามเจตนาเดิม')]),
  para([run('ข้อควรระวัง  ', { bold: true }), run('การแก้ไขเพียงค่า cluster_name ในไฟล์เหล่านี้ จะทำให้ระบบดูเหมือนพร้อมใช้งาน แต่ยังปฏิเสธที่เงื่อนไข mode และ live_enabled อยู่ดี ซึ่งจะทำให้ผู้ตรวจสอบภายหลังเสียเวลาค้นหาสาเหตุ')]),

  heading('4. รายการงานที่ส่งมอบ'),
  para([run('หมายเหตุ  ', { bold: true }), run('วันกำหนดส่งเป็นข้อเสนอเบื้องต้น ขอให้ยืนยันร่วมกับหัวหน้าโครงงานอีกครั้ง')], { color: MUTED }),
  spacer(80),
  table([700, 2400, 2400, 2326, 1200], [
    ['รหัส', 'งาน', 'สิ่งที่ต้องส่ง', 'เกณฑ์ว่าเสร็จ', 'กำหนดส่ง'],
    ['A1', 'ส่งมอบค่า digest ของ container image ทั้ง 6 รายการ', 'ค่า digest ของ sandbox 4 รายการ และ worker 2 รายการ', 'ผู้อื่นสั่ง docker compose up ได้โดยไม่ต้องสอบถาม', '12 พ.ย. 2569'],
    ['A2', 'สร้าง sandbox T0 ขึ้นใหม่', 'ผลการรันที่ยืนยันว่า gis_readiness() รายงานถูกต้อง', 'ชุดทดสอบในเครื่องผ่านครบ', '14 พ.ย. 2569'],
    ['A3', 'ตัดสินใจขอบเขตของ legacy-v1 และแก้ไขตัวอ่าน AST', 'บันทึกการตัดสินใจ และโค้ดที่แก้ไขแล้ว', 'รวม 78f0219 แล้วชุดทดสอบผ่านครบ', '27 พ.ย. 2569'],
    ['A4', 'ตัดสินใจว่า worker ใดควรทำงานบนคลาวด์', 'เอกสารระบุรายตัว พร้อมเหตุผล', 'มีข้อสรุปเป็นลายลักษณ์อักษร', '20 พ.ย. 2569'],
    ['A5', 'กำหนดเงื่อนไขการอนุมัติประมวลผล GEE จริง', 'เอกสารระบุผู้อนุมัติ หลักฐานที่ต้องใช้ และขั้นตอน', 'มีข้อสรุปเป็นลายลักษณ์อักษร', '20 พ.ย. 2569'],
  ]),
  spacer(100),
  para([run('หมายเหตุ  ', { bold: true }), run('งาน A1 มีความเร่งด่วนสูงสุด เนื่องจากข้อมูลดังกล่าวอยู่ในความครอบครองของผู้รับมอบเพียงผู้เดียว และหากสูญหายจะไม่สามารถกู้คืนได้ รายละเอียดอยู่ในเอกสารส่งมอบงานฉบับที่ 1 ข้อ 2.1 และ 2.2')]),

  heading('5. เรื่องที่ควรทราบเพิ่มเติม'),
  para('ระบบตรวจอัตโนมัติ (CI) ของคลังโค้ดไม่เคยทำงานกับบรานช์นี้มาก่อน เนื่องจากตั้งค่าให้ตรวจเฉพาะการผลักขึ้นบรานช์ main และการเปิด pull request ซึ่งบรานช์นี้ยังไม่เคยเปิด เมื่อนำมาทดลองรันจริงพบว่าไม่ผ่านทุกขั้นตอน และได้ดำเนินการแก้ไขแล้ว'),
  table([4026, 2500, 2500], [
    ['ขั้นตอนตรวจสอบ', 'ก่อนแก้ไข', 'หลังแก้ไข'],
    ['ruff check .', 'ไม่ผ่าน 769 รายการ', 'ผ่าน'],
    ['pytest tests/', 'หยุดตั้งแต่ขั้นรวบรวมไฟล์', 'ผ่าน 2,089 รายการ'],
    ['eslint src --max-warnings 0', 'ไม่ผ่าน 1 ข้อผิดพลาด 2 คำเตือน', 'ผ่าน'],
  ], { align: [null, AlignmentType.CENTER, AlignmentType.CENTER] }),
  spacer(100),
  para('ในจำนวน 769 รายการ มี 714 รายการเป็นรูปแบบการเขียนแบบรวบรัด (E701 และ E702) ซึ่งไม่ได้ปรับแก้โค้ด แต่ประกาศข้อยกเว้นไว้ในไฟล์ ruff.toml พร้อมเหตุผล ส่วนอีก 55 รายการเป็นการ import ที่ไม่ได้ใช้งาน ได้นำออกแล้ว'),
  para('นอกจากนี้ ชุดทดสอบ test_real_credentials_and_live_egress_cannot_be_enabled ตรวจสอบสถานะระดับโปรเซส ซึ่งไฟล์ tests/test_canopy.py อันเป็นชุดทดสอบของเว็บหลักและไม่เกี่ยวข้องกับ GIS ได้ import earthengine-api ไว้ก่อนแล้ว จึงปรับให้ตรวจสอบใน interpreter ใหม่แทน'),
  para('ตั้งแต่บัดนี้ ระบบตรวจอัตโนมัติจะทำงานทุกครั้งที่ผลักขึ้นบรานช์ feature และ gis'),

  heading('6. แบบบันทึกความคืบหน้า'),
  table([900, 2300, 1800, 1800, 2226], progressRows(['A1', 'A2', 'A3', 'A4', 'A5']),
    { align: [AlignmentType.CENTER, null, AlignmentType.CENTER, AlignmentType.CENTER, AlignmentType.CENTER] }),
  ...signatures(),
];

const OUT = process.argv[2] || '.';
Promise.all([
  build(path.join(OUT, 'เอกสารส่งมอบงาน_1_สภาพแวดล้อมที่ทำซ้ำได้.docx'), docB),
  build(path.join(OUT, 'เอกสารส่งมอบงาน_2_สัญญาวิธีคำนวณและการอนุมัติ.docx'), docA),
]).catch(e => { console.error(e); process.exit(1); });
