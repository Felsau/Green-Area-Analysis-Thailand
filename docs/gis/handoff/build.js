// Build the two GIS handoff documents as .docx.
// Content mirrors docs/gis/handoff-2026-11-08-*.md in the repository.
//
// Scope on purpose: both documents cover only the week of 9-15 Nov 2026. The
// owner asked for that so the two people receiving them do not start work that
// the week's answers would make them redo.
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
const WARN_FILL = 'FBF3E4';

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
    spacing: { before: o.before || 0, after: o.after === undefined ? 120 : o.after, line: o.line || 300 },
  });
}

function title(text) {
  return new Paragraph({
    children: [run(text, { size: 34, bold: true })],
    alignment: AlignmentType.CENTER,
    spacing: { after: 100, line: 320 },
  });
}

function heading(text) {
  return new Paragraph({
    children: [run(text, { size: 28, bold: true })],
    spacing: { before: 300, after: 130, line: 300 },
    border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: RULE, space: 4 } },
  });
}

function subheading(text) {
  return new Paragraph({
    children: [run(text, { size: 25, bold: true })],
    spacing: { before: 220, after: 100, line: 300 },
  });
}

// Numbered rather than dashed: every list in these documents is a set of
// things somebody has to work through and refer back to, so the items need to
// be nameable ("ข้อ 2") rather than just visually separated.
function numbered(items) {
  return items.map((text, i) => new Paragraph({
    children: [run(`${i + 1}.  `, { bold: true }), run(text)],
    spacing: { after: 80, line: 300 },
    indent: { left: 420, hanging: 260 },
  }));
}

// A boxed line for the "do not start this yet" instructions. These are the
// point of the document, so they are set apart rather than buried in prose.
function callout(lines) {
  const items = Array.isArray(lines) ? lines : [lines];
  return items.map((text, i) => new Paragraph({
    children: [run(text, { bold: true })],
    spacing: { before: i === 0 ? 140 : 0, after: i === items.length - 1 ? 160 : 60, line: 300 },
    indent: { left: 200, right: 200 },
    shading: { type: ShadingType.CLEAR, fill: WARN_FILL, color: 'auto' },
    border: { left: { style: BorderStyle.SINGLE, size: 18, color: 'C9A227', space: 8 } },
  }));
}

// Consolas carries no Thai glyphs, so these blocks stay ASCII and any
// explanation goes in a paragraph of its own.
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

function header(recipient) {
  return table([2200, 6826], [
    ['หัวข้อ', 'รายละเอียด'],
    ['วันที่จัดทำ', '8 พฤศจิกายน 2569'],
    ['ผู้ส่งมอบ', '.............................................. (ระบุชื่อ-นามสกุล)'],
    ['ผู้รับมอบ', recipient],
    ['ขอบเขต', 'เฉพาะสัปดาห์ที่ 9 ถึง 13 พฤศจิกายน 2569 · ทุกงานเสร็จภายในพฤหัสบดี 12 พ.ย.'],
    ['บรานช์', 'gis-unlock (อยู่บน GitHub แล้ว)'],
  ]);
}

function signoff(codes) {
  return [
    heading('แบบบันทึกและลงนาม'),
    table([1200, 3400, 2200, 2226], [
      ['รหัส', 'ผู้รับผิดชอบ', 'วันที่เสร็จ', 'ผลการตรวจ'],
      ...codes.map(c => [c, '', '', 'ผ่าน / ไม่ผ่าน']),
    ], { align: [AlignmentType.CENTER, null, AlignmentType.CENTER, AlignmentType.CENTER] }),
    spacer(300),
    para('ผู้ส่งมอบ ...................................................... วันที่ ........ / ........ / ........'),
    spacer(220),
    para('ผู้รับมอบ ...................................................... วันที่ ........ / ........ / ........'),
  ];
}

const IMAGE_ROWS = [
  ['ตัวแปร', 'ที่มา'],
  ['GIS_LOCAL_DB_IMAGE', 'dev/gis_local/compose.yaml'],
  ['GIS_LOCAL_AUTH_IMAGE', 'dev/gis_local/compose.yaml'],
  ['GIS_LOCAL_REST_IMAGE', 'dev/gis_local/compose.yaml'],
  ['GIS_LOCAL_GATEWAY_IMAGE', 'dev/gis_local/compose.yaml'],
  ['WORKER_IMAGE', 'dev/gis_local/manage.py บรรทัดที่ 47'],
  ['GEE_MOCK_WORKER_IMAGE', 'dev/gis_local/manage.py บรรทัดที่ 48'],
];

function build(fileName, children) {
  const doc = new Document({
    creator: 'GreenLens project',
    title: path.basename(fileName, '.docx'),
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
// ฉบับที่ 1 — สำหรับผู้ดูแลเรื่องสภาพแวดล้อม
// ─────────────────────────────────────────────────────────────────────────
const doc1 = [
  title('เอกสารส่งมอบงาน ฉบับที่ 1'),
  para([run('สัปดาห์ที่ 9 – 13 พฤศจิกายน 2569', { size: 26, bold: true, color: MUTED })],
    { align: AlignmentType.CENTER, after: 280 }),
  header('.............................................. (ระบุชื่อ-นามสกุล)'),
  spacer(),

  heading('1. ขอบเขตของเอกสารฉบับนี้'),
  para('เอกสารนี้ครอบคลุมเฉพาะงานของสัปดาห์ที่ 9 ถึง 13 พฤศจิกายน 2569 เท่านั้น'),
  para('งานในระบบ GIS ยังมีอีกหลายส่วน แต่ยังไม่ส่งมอบในรอบนี้ เนื่องจากต้องรอผลของสองงานด้านล่างก่อน จึงจะวางแผนส่วนที่เหลือได้อย่างถูกต้อง'),
  ...callout([
    'ขอความร่วมมือ กรุณาทำเฉพาะสามรายการนี้ และยังไม่ต้องเริ่มงานส่วนอื่น',
    'หากทำล่วงหน้าไปก่อนโดยยังไม่ทราบคำตอบของงาน W1 มีความเป็นไปได้สูงที่จะต้องรื้อทำใหม่',
  ]),

  heading('2. งานที่ส่งมอบ'),
  ...callout([
    'กำหนดส่งรวม ทุกงานต้องเสร็จภายในวันพฤหัสบดีที่ 12 พฤศจิกายน 2569',
    'เนื่องจากต้องรวบรวมผลส่งอาจารย์ที่ปรึกษาในบ่ายวันศุกร์ที่ 13 พฤศจิกายน วันศุกร์ช่วงเช้าจึงกันไว้เป็นเวลาสำรองสำหรับรวบรวมเอกสาร ไม่ใช่เวลาทำงาน',
  ]),
  table([900, 4400, 2300, 1426], [
    ['รหัส', 'งาน', 'กำหนดส่ง', 'เวลาโดยประมาณ'],
    ['W1', 'ตรวจสอบความพร้อมของฐานข้อมูล Supabase', 'ภายในอังคาร 10 พ.ย.', 'ไม่เกิน 1 ชม.'],
    ['W2', 'บันทึกค่า digest ของ container image ลงคลังโค้ด', 'ภายในพุธ 11 พ.ย.', 'ไม่เกิน 1 ชม.'],
    ['W5', 'สร้าง Dockerfile ของ worker (งานเขียนโค้ด)', 'ภายในพฤหัสบดี 12 พ.ย.', 'ครึ่งวัน'],
  ], { align: [AlignmentType.CENTER, null, null, AlignmentType.CENTER] }),

  heading('3. รายละเอียดงาน'),

  subheading('W1 — ตรวจสอบความพร้อมของฐานข้อมูล Supabase'),
  para([run('สิ่งที่ต้องทำ  ', { bold: true }), run('เปิดแดชบอร์ดของโครงการบน Supabase แล้วตอบสองคำถาม')]),
  ...numbered([
    'ฐานข้อมูลเป็น PostgreSQL รุ่น 17 ขึ้นไปหรือไม่',
    'บัญชีที่ใช้งานมีสิทธิ์สร้าง role (คำสั่ง CREATE ROLE) หรือไม่',
  ]),
  para([run('เหตุผล  ', { bold: true }), run('สคริปต์ติดตั้งฐานข้อมูล migrations/027_gis_foundation.sql กำหนดเงื่อนไขไว้ว่า server_version_num ต้องไม่ต่ำกว่า 170000 หากรุ่นต่ำกว่านี้จะติดตั้งไม่ได้ทั้งชุด และแผนงานส่วนที่เหลือต้องทบทวนใหม่ ส่วนคำสั่ง CREATE ROLE ปรากฏใน migration หมายเลข 027 และ 043 ถึง 047 สำหรับสร้าง gis_owner, gis_worker, gis_native_worker และ authenticator')]),
  para([run('สิ่งที่ต้องส่ง  ', { bold: true }), run('คำตอบสองข้อ ใช่หรือไม่ใช่ พร้อมภาพหน้าจอประกอบ')]),
  para([run('เกณฑ์ว่าเสร็จ  ', { bold: true }), run('ทีมทราบคำตอบทั้งสองข้ออย่างชัดเจน')]),
  ...callout('ยังไม่ต้องติดตั้ง migration และยังไม่ต้องแก้ไขฐานข้อมูลใด ๆ ในสัปดาห์นี้'),

  subheading('W2 — บันทึกค่า digest ของ container image ลงคลังโค้ด'),
  para([run('สิ่งที่ต้องทำ  ', { bold: true }), run('รับค่า digest จากผู้พัฒนาเดิม (ดูเอกสารฉบับที่ 2 รายการ W3) แล้วสร้างไฟล์ dev/gis_local/images.json บันทึกค่าทั้ง 6 รายการ จากนั้น commit เข้าคลังโค้ด')]),
  table([4000, 5026], IMAGE_ROWS),
  spacer(100),
  para([run('เหตุผล  ', { bold: true }), run('ปัจจุบันค่าเหล่านี้ไม่มีบันทึกอยู่ในคลังโค้ด ผลการตรวจสอบบนเครื่องผู้จัดทำเอกสาร')]),
  ...evidence([
    '$ docker image inspect sha256:fca4560d8a0d...aa04c9',
    'NOT ON THIS MACHINE',
    '$ docker image inspect sha256:7557955c9e2c...9566674',
    'NOT ON THIS MACHINE',
  ]),
  para('และไฟล์ compose.yaml กำหนดไว้แบบบังคับโดยไม่มีค่าเริ่มต้น'),
  ...evidence(['image: ${GIS_LOCAL_DB_IMAGE:?pinned image required}']),
  para('เท่ากับว่าขณะนี้มีเพียงเครื่องของผู้พัฒนาเดิมเพียงเครื่องเดียวที่ประกอบระบบขึ้นมาได้ หากเครื่องนั้นเสียหาย จะไม่มีวิธีสร้างสภาพแวดล้อมเดิมขึ้นใหม่'),
  para([run('สิ่งที่ต้องส่ง  ', { bold: true }), run('ไฟล์ dev/gis_local/images.json ที่ commit แล้ว')]),
  para([run('เกณฑ์ว่าเสร็จ  ', { bold: true }), run('ผู้อื่นสามารถสั่ง docker compose up ได้สำเร็จโดยไม่ต้องสอบถามผู้ใด')]),
  ...callout('ยังไม่ต้องสร้าง Dockerfile และยังไม่ต้องแก้ไขสคริปต์ใด ๆ ในสัปดาห์นี้'),

  subheading('W5 — สร้าง Dockerfile ของ worker'),
  para([run('สิ่งที่ต้องทำ  ', { bold: true }), run('สร้างไฟล์ green-area-backend/gis_worker/Dockerfile แล้ว build เป็น image จากนั้นรันชุดทดสอบ native ภายใน image นั้นโดยตั้ง GIS_NATIVE_RUNTIME=pinned')]),
  para('สูตรต่อไปนี้ผ่านการทดสอบแล้ว ใช้เป็นจุดตั้งต้นได้'),
  ...evidence([
    'FROM python:3.11-slim',
    'RUN apt-get update && apt-get install -y --no-install-recommends libexpat1 \\',
    '    && rm -rf /var/lib/apt/lists/*',
    'COPY requirements-native.txt .',
    'RUN pip install --no-cache-dir -r requirements-native.txt',
    'ENV GIS_NATIVE_RUNTIME=pinned',
  ]),
  para([run('เหตุผล  ', { bold: true }), run('ชุดทดสอบ test_v1_artifacts_of_existing_fixtures_are_byte_identical ตรวจว่าผลลัพธ์จากการแปลง shapefile ตรงกับค่าที่ตรึงไว้ทุกไบต์ ผลการทดลองพบว่าไลบรารีรุ่นเดียวกันให้ผลต่างกันตามเครื่อง')]),
  table([5826, 3200], [
    ['สภาพแวดล้อม', 'ผลการทดสอบ'],
    ['python:3.12-slim ใน Docker', 'ผ่าน'],
    ['เครื่อง GitHub ubuntu-24.04 (ไฟล์ wheel เดียวกัน)', 'ไม่ผ่าน'],
    ['Windows 11', 'ไม่ผ่าน'],
  ], { align: [null, AlignmentType.CENTER] }),
  spacer(100),
  para('การตรึงรุ่นไลบรารีจึงยังไม่พอ ต้องตรึงทั้ง image ปัจจุบันชุดทดสอบนี้ถูกข้ามอัตโนมัติ และจะทำงานก็ต่อเมื่อมี image ที่ตรึงไว้แล้วเท่านั้น'),
  para([run('สิ่งที่ต้องส่ง  ', { bold: true }), run('ไฟล์ Dockerfile คำสั่ง build และผลการรันชุดทดสอบ')]),
  para([run('เกณฑ์ว่าเสร็จ  ', { bold: true }), run('รัน pytest tests/test_ldd_policy_native.py ภายใน image แล้วผ่านครบทุกข้อ รวมถึงข้อที่ปกติถูกข้าม หากข้อนั้นยังไม่ผ่าน แปลว่า image ยังไม่ตรง')]),
  ...callout([
    'งานนี้ไม่ต้องรอคำตอบของ W1 หรือ W3 เริ่มได้ทันที เพราะใช้เพียง base image สาธารณะกับไฟล์ requirements-native.txt ที่มีอยู่แล้ว',
    'ยังไม่ต้องนำ image ไปผูกกับ dev/gis_local/manage.py และยังไม่ต้องอัปขึ้น registry ใด ๆ ขอแค่พิสูจน์ว่า image สร้างผลลัพธ์ตรงกับที่ตรึงไว้',
  ]),

  heading('4. งานที่ยังไม่ส่งมอบในรอบนี้'),
  para('รายการต่อไปนี้อยู่ในแผนระยะถัดไป กรุณายังไม่เริ่มดำเนินการ'),
  ...numbered([
    'การเขียนตัวติดตั้ง migration สำหรับฐานข้อมูลบนคลาวด์',
    'การย้ายที่จัดเก็บไฟล์ที่ผู้ใช้อัปโหลด',
  ]),
  para('ทั้งสองรายการขึ้นอยู่กับคำตอบของงาน W1 และ W2 โดยตรง จะส่งมอบในรอบถัดไป'),

  heading('5. สิ่งที่จัดเตรียมไว้ให้แล้ว'),
  ...numbered([
    'ระบบตรวจอัตโนมัติ (CI) ทำงานได้และผ่านทุกขั้นตอนแล้ว หากเปิด pull request แล้วขึ้นสถานะไม่ผ่าน แสดงว่าเป็นสิ่งที่เพิ่งแก้เข้าไป ไม่ใช่ปัญหาเดิมที่ค้างอยู่',
    'ไฟล์ green-area-backend/requirements-native.txt ระบุรุ่นไลบรารีที่ตรวจสอบแล้ว',
    'ไฟล์ตัวอย่างการตั้งค่าอยู่ที่ green-area-backend/.env.example และ green-area-frontend/.env.example',
  ]),

  ...signoff(['W1', 'W2', 'W5']),
];

// ─────────────────────────────────────────────────────────────────────────
// ฉบับที่ 2 — สำหรับผู้พัฒนาบรานช์เดิม
// ─────────────────────────────────────────────────────────────────────────
const doc2 = [
  title('เอกสารส่งมอบงาน ฉบับที่ 2'),
  para([run('สัปดาห์ที่ 9 – 13 พฤศจิกายน 2569', { size: 26, bold: true, color: MUTED })],
    { align: AlignmentType.CENTER, after: 280 }),
  header('.............................................. (ผู้พัฒนาบรานช์ feature/gis-data-management)'),
  spacer(),

  heading('1. ขอบเขตของเอกสารฉบับนี้'),
  para('เอกสารนี้ครอบคลุมเฉพาะงานของสัปดาห์ที่ 9 ถึง 13 พฤศจิกายน 2569 เท่านั้น ยังมีเรื่องที่ต้องตัดสินใจอีกหลายข้อในระบบ GIS แต่ยังไม่ส่งมอบในรอบนี้'),
  ...callout('ขอความร่วมมือ กรุณาทำเฉพาะสามรายการด้านล่าง และยังไม่ต้องเริ่มงานส่วนอื่น'),

  heading('2. สิ่งที่เปลี่ยนแปลงไปแล้ว และกระทบท่านอย่างไร'),
  para('ระหว่างวันที่ 7 ถึง 8 พฤศจิกายน 2569 มีการต่อยอดงานบนบรานช์ feature/gis-data-management เพื่อให้ระบบติดตั้งลงฐานข้อมูลที่ไม่ใช่ sandbox ในเครื่องได้ รวม 9 commit บนบรานช์ใหม่ชื่อ gis-unlock'),
  para('พฤติกรรมเดิมของ sandbox ถูกรักษาไว้ครบถ้วน และไม่ต้องแก้ไขสคริปต์ในโฟลเดอร์ dev แม้แต่ไฟล์เดียว แต่มีผลข้างเคียงหนึ่งรายการที่ต้องดำเนินการ'),
  para([run('ผลข้างเคียง  ', { bold: true }), run('migrations/027_gis_foundation.sql ถูกแก้ไข ทำให้ค่า checksum ที่ตรึงต่อกันเป็นลูกโซ่ต้องคำนวณใหม่ ตั้งแต่หมายเลข 027 จนถึง 048 ตาราง gis.schema_migrations ใน sandbox T0 เดิมจึงไม่ตรงกับไฟล์ปัจจุบันอีกต่อไป')]),
  para('ตรวจสอบรายการที่เปลี่ยนแปลงได้ด้วยคำสั่ง'),
  ...evidence(['git diff b9b5b3a HEAD -- green-area-backend/migrations']),
  para([run('เหตุผลที่ต้องแก้  ', { bold: true }), run('cluster_name เป็นค่าตั้งระดับ postmaster ซึ่งบริการแบบ Supabase Cloud กำหนดไม่ได้ เมื่อนำ migration 027 ฉบับเดิมไปติดตั้งบน PostgreSQL 17 มาตรฐาน จะได้ผลดังนี้')]),
  ...evidence(['ERROR: GIS_LOCAL_TARGET_REQUIRED']),
  para('หลังแก้ไข ตัวติดตั้งจะประกาศค่า gis.cluster_name และ gis.mode เอง โดยการไม่ประกาศค่ายังคงหมายถึง sandbox เหมือนเดิมทุกประการ'),

  heading('3. งานที่ส่งมอบ'),
  ...callout([
    'กำหนดส่งรวม ทุกงานต้องเสร็จภายในวันพฤหัสบดีที่ 12 พฤศจิกายน 2569',
    'เนื่องจากต้องรวบรวมผลส่งอาจารย์ที่ปรึกษาในบ่ายวันศุกร์ที่ 13 พฤศจิกายน วันศุกร์ช่วงเช้าจึงกันไว้เป็นเวลาสำรองสำหรับรวบรวมเอกสาร ไม่ใช่เวลาทำงาน',
  ]),
  table([900, 4400, 2300, 1426], [
    ['รหัส', 'งาน', 'กำหนดส่ง', 'เวลาโดยประมาณ'],
    ['W3', 'ส่งค่า digest ของ container image ทั้ง 6 รายการ', 'ภายในจันทร์ 9 พ.ย.', 'ไม่เกิน 1 ชม.'],
    ['W4', 'สร้าง sandbox T0 ขึ้นใหม่', 'ภายในพุธ 11 พ.ย.', 'ตามปกติ'],
    ['W6', 'ตรวจทานการแก้ไขด่านความปลอดภัยใน migration 027', 'ภายในพฤหัสบดี 12 พ.ย.', '1–2 ชม.'],
  ], { align: [AlignmentType.CENTER, null, null, AlignmentType.CENTER] }),

  heading('4. รายละเอียดงาน'),

  subheading('W3 — ส่งค่า digest ของ container image ทั้ง 6 รายการ'),
  para([run('สิ่งที่ต้องทำ  ', { bold: true }), run('ส่งค่า digest ที่ใช้งานอยู่จริงบนเครื่องของท่าน')]),
  table([4000, 5026], IMAGE_ROWS),
  spacer(100),
  para([run('เหตุผล  ', { bold: true }), run('ค่าทั้งหมดไม่มีบันทึกอยู่ในคลังโค้ด จากการตรวจสอบบนเครื่องของผู้จัดทำเอกสารพบว่า image ทั้งสองรายการของ worker ไม่มีอยู่ และค้นทั้งคลังโค้ดแล้วไม่พบค่าของตัวแปรทั้งสี่รายการแรก ขณะนี้จึงมีเพียงเครื่องของท่านเพียงเครื่องเดียวที่ประกอบระบบขึ้นมาได้')]),
  para([run('สิ่งที่ต้องส่ง  ', { bold: true }), run('ค่า digest ทั้ง 6 รายการ ส่งเป็นข้อความได้')]),
  para([run('เกณฑ์ว่าเสร็จ  ', { bold: true }), run('ผู้รับผิดชอบงาน W2 นำไปบันทึกลงคลังโค้ดได้')]),
  ...callout('นี่คืองานที่เร่งด่วนที่สุดในสัปดาห์นี้ หากเครื่องของท่านเสียหายก่อนส่งมอบ จะไม่มีวิธีสร้างสภาพแวดล้อมเดิมขึ้นใหม่ได้เลย'),

  subheading('W4 — สร้าง sandbox T0 ขึ้นใหม่'),
  para([run('สิ่งที่ต้องทำ  ', { bold: true }), run('ดึงบรานช์ gis-unlock มาแล้วสร้าง T0 ขึ้นใหม่ตามขั้นตอนเดิมของท่าน')]),
  para([run('เหตุผล  ', { bold: true }), run('ตามข้อ 2 ค่า checksum ถูกคำนวณใหม่ ledger เดิมจึงไม่ตรงกับไฟล์ปัจจุบัน โค้ดและสคริปต์ของท่านไม่ต้องแก้ไข กระทบเฉพาะฐานข้อมูลเท่านั้น')]),
  para([run('สิ่งที่ต้องส่ง  ', { bold: true }), run('ผลการรันที่ยืนยันว่า gis_readiness() รายงานค่าถูกต้อง')]),
  para([run('เกณฑ์ว่าเสร็จ  ', { bold: true }), run('ชุดทดสอบบนเครื่องของท่านผ่านครบ')]),

  subheading('W6 — ตรวจทานการแก้ไขด่านความปลอดภัยใน migration 027'),
  para([run('สิ่งที่ต้องทำ  ', { bold: true }), run('ตรวจทานการแก้ไขด่านตรวจเป้าหมายใน migrations/027_gis_foundation.sql และฟังก์ชันใหม่ gis.target_ok() ว่ายังรักษาหลักประกันเดิมที่ท่านออกแบบไว้ครบถ้วนหรือไม่')]),
  ...evidence(['git diff b9b5b3a HEAD -- green-area-backend/migrations/027_gis_foundation.sql']),
  para([run('เหตุผล  ', { bold: true }), run('ด่านนี้เป็นส่วนที่กันไม่ให้ระบบไปแตะฐานข้อมูลที่ไม่ได้ประกาศไว้ ซึ่งท่านเป็นผู้ออกแบบ การแก้ไขครั้งนี้ยังไม่มีผู้ใดตรวจทานอย่างเป็นอิสระ')]),
  para('ระหว่างการพัฒนาเคยเกิดข้อผิดพลาดขึ้นจริงหนึ่งครั้ง คือเมื่อกำหนดค่าปริยายให้เฉพาะฝั่ง sandbox ทำให้เงื่อนไขฝั่ง cloud กลายเป็น NULL ส่งผลให้ทั้งนิพจน์เป็น NULL และคำสั่ง IF ไม่ทำงาน ด่านจึงเปิดโล่งโดยไม่มีสัญญาณเตือน ข้อผิดพลาดนี้ถูกพบและแก้ไขแล้วด้วยการใช้ COALESCE ทั้งสองฝั่ง แต่แสดงให้เห็นว่าโค้ดส่วนนี้ผิดพลาดได้โดยไม่มีอาการ'),
  para([run('สิ่งที่ต้องส่ง  ', { bold: true }), run('ข้อความยืนยันว่าตรวจแล้วรับได้ หรือรายการข้อทักท้วงพร้อมเหตุผล')]),
  para([run('ผลการทดสอบที่ทำไว้แล้ว  ', { bold: true }), run('ทดสอบบน container PostgreSQL 17 จำนวน 5 กรณี')]),
  table([6026, 3000], [
    ['กรณีทดสอบ', 'ผลลัพธ์'],
    ['ไม่ประกาศค่าใด และ postmaster ไม่ใช่ sandbox', 'ปฏิเสธ'],
    ['ประกาศ sandbox แต่ postmaster ไม่ใช่ sandbox', 'ปฏิเสธ'],
    ['ประกาศ project ref แต่ mode เป็น local', 'ปฏิเสธ'],
    ['ไม่ประกาศค่าใด และ postmaster เป็น sandbox (ทางเดิม)', 'ติดตั้งครบ 027 ถึง 048'],
    ['ประกาศ cloud และไม่มี cluster_name', 'ติดตั้งครบ 027 ถึง 048'],
  ], { align: [null, AlignmentType.CENTER] }),
  spacer(100),
  ...callout('ขอให้ตรวจทานในมุมของผู้ออกแบบว่ามีกรณีใดที่ยังไม่ได้ทดสอบหรือไม่'),

  heading('5. งานที่ยังไม่ส่งมอบในรอบนี้'),
  para('รายการต่อไปนี้ต้องตัดสินใจร่วมกันก่อน กรุณายังไม่เริ่มดำเนินการ และจะนัดหารือในรอบถัดไป'),
  ...numbered([
    'การรวม commit 78f0219 เข้ากับบรานช์ และการพิจารณาขอบเขตของ legacy-v1',
    'การพิจารณาว่า worker ใดควรทำงานบนคลาวด์',
    'การกำหนดเงื่อนไขการอนุมัติประมวลผล Google Earth Engine จริง',
  ]),
  ...callout('ข้อควรระวังหากเผลอเริ่มก่อน ค่า hash ที่ตรึงไว้ในขณะนี้ยังตรงกับไฟล์บนบรานช์ การปรับค่า hash ก่อนการรวมบรานช์จะทำให้ชุดทดสอบไม่ผ่านโดยไม่จำเป็น'),

  heading('6. เรื่องที่ควรทราบ'),
  para('ระบบตรวจอัตโนมัติ (CI) ไม่เคยทำงานกับบรานช์นี้มาก่อน เนื่องจากตั้งค่าให้ตรวจเฉพาะบรานช์ main และ pull request ซึ่งยังไม่เคยเปิด เมื่อนำมาทดลองรันพบว่าไม่ผ่านทุกขั้นตอน และได้แก้ไขเรียบร้อยแล้ว'),
  table([4026, 2500, 2500], [
    ['ขั้นตอนตรวจสอบ', 'ก่อนแก้ไข', 'หลังแก้ไข'],
    ['ruff check .', 'ไม่ผ่าน 769 รายการ', 'ผ่าน'],
    ['pytest tests/', 'หยุดตั้งแต่ขั้นรวบรวมไฟล์', 'ผ่าน 2,089 รายการ'],
    ['eslint src --max-warnings 0', 'ไม่ผ่าน 1 ข้อผิดพลาด 2 คำเตือน', 'ผ่าน'],
  ], { align: [null, AlignmentType.CENTER, AlignmentType.CENTER] }),
  spacer(100),
  para('ในจำนวน 769 รายการ มี 714 รายการเป็นรูปแบบการเขียนแบบรวบรัด (E701 และ E702) ซึ่งไม่ได้ปรับแก้โค้ดของท่าน แต่ประกาศข้อยกเว้นไว้ในไฟล์ ruff.toml พร้อมเหตุผล ส่วนที่เหลือเป็นการ import ที่ไม่ได้ใช้งาน'),

  ...signoff(['W3', 'W4', 'W6']),
];

const OUT = process.argv[2] || '.';
Promise.all([
  build(path.join(OUT, 'เอกสารส่งมอบงาน_1_สภาพแวดล้อมที่ทำซ้ำได้.docx'), doc1),
  build(path.join(OUT, 'เอกสารส่งมอบงาน_2_สัญญาวิธีคำนวณและการอนุมัติ.docx'), doc2),
]).catch(e => { console.error(e); process.exit(1); });
