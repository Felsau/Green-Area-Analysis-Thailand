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
  HeightRule,
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

function heading(text, o = {}) {
  return new Paragraph({
    children: [run(text, { size: 28, bold: true })],
    // pageBreakBefore rather than a separate break paragraph: the empty
    // paragraph left a blank page whenever the previous section happened to
    // end near the bottom of one.
    pageBreakBefore: !!o.newPage,
    spacing: { before: o.newPage ? 0 : 300, after: 130, line: 300 },
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
      // Keep a row whole: a fill-in row split across a page break leaves an
      // empty half that reads as a row with no label.
      cantSplit: true,
      children: cells.map((c, i) => cell(c, {
        width: widths[i],
        bold: r === 0 && !o.noHeader,
        fill: r === 0 && !o.noHeader ? HEAD_FILL : undefined,
        align: o.align && o.align[i],
      })),
    })),
  });
}

// A bordered empty box to paste a screenshot into, with a caption saying what
// has to be visible in it. Without naming that, what comes back is a picture of
// whatever the sender happened to have on screen.
function imageSlot(number, title, mustShow, heightCm = 7) {
  return [
    new Paragraph({
      children: [run(`ภาพที่ ${number}  `, { bold: true }), run(title, { bold: true })],
      spacing: { before: 260, after: 60, line: 300 },
    }),
    new Paragraph({
      children: [run('ในภาพต้องเห็น: ' + mustShow, { size: 20, color: MUTED })],
      spacing: { after: 100, line: 280 },
    }),
    new Table({
      columnWidths: [CONTENT],
      width: { size: CONTENT, type: WidthType.DXA },
      borders: {
        top: { style: BorderStyle.DASHED, size: 6, color: '9A9A9A' },
        bottom: { style: BorderStyle.DASHED, size: 6, color: '9A9A9A' },
        left: { style: BorderStyle.DASHED, size: 6, color: '9A9A9A' },
        right: { style: BorderStyle.DASHED, size: 6, color: '9A9A9A' },
      },
      rows: [new TableRow({
        cantSplit: true,
        height: { value: Math.round(heightCm * 567), rule: HeightRule.ATLEAST },
        children: [new TableCell({
          width: { size: CONTENT, type: WidthType.DXA },
          children: [new Paragraph({
            children: [run('วางภาพหน้าจอที่นี่', { size: 20, color: 'A0A0A0' })],
            alignment: AlignmentType.CENTER,
            spacing: { before: 1400, after: 60, line: 280 },
          })],
        })],
      })],
    }),
  ];
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

// แบบฟอร์มให้ผู้รับมอบกรอกแล้วส่งกลับ แถวซ้ายคือสิ่งที่ถาม แถวขวาเว้นให้เติม
const BLANK = '..........................................';

function formBlock(heading, rows) {
  return [
    subheading(heading),
    table([4200, 4826], [['รายการ', 'คำตอบ'], ...rows]),
    spacer(120),
  ];
}

function evidenceForm(sectionNumber, blocks) {
  return [
    heading(sectionNumber + '. แบบฟอร์มส่งหลักฐาน (ผู้รับมอบกรอกและส่งกลับ)'),
    para('ขอให้กรอกช่องว่างและแนบหลักฐานตามที่ระบุ แล้วส่งกลับภายในวันพฤหัสบดีที่ 12 พฤศจิกายน 2569'),
    ...blocks.flatMap(b => formBlock(b[0], b[1])),
    subheading('ลงนาม'),
    spacer(120),
    para('ผู้รับมอบ ...................................................... วันที่ ......... / ......... / .........'),
    spacer(200),
    para('ผู้ส่งมอบ ...................................................... วันที่ ......... / ......... / .........'),
  ];
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
// ฉบับที่ 1: สำหรับผู้ดูแลเรื่องสภาพแวดล้อม
// ─────────────────────────────────────────────────────────────────────────
const doc1 = [
  title('เอกสารส่งมอบงาน ฉบับที่ 1'),
  para([run('สัปดาห์ที่ 9 ถึง 13 พฤศจิกายน 2569', { size: 26, bold: true, color: MUTED })],
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

  subheading('W1. ตรวจสอบความพร้อมของฐานข้อมูล Supabase'),
  para([run('สิ่งที่ต้องทำ  ', { bold: true }), run('เปิดแดชบอร์ดของโครงการบน Supabase แล้วตอบสองคำถาม')]),
  ...numbered([
    'ฐานข้อมูลเป็น PostgreSQL รุ่น 17 ขึ้นไปหรือไม่',
    'บัญชีที่ใช้งานมีสิทธิ์สร้าง role (คำสั่ง CREATE ROLE) หรือไม่',
  ]),
  para([run('เหตุผล  ', { bold: true }), run('สคริปต์ติดตั้งฐานข้อมูล migrations/027_gis_foundation.sql กำหนดเงื่อนไขไว้ว่า server_version_num ต้องไม่ต่ำกว่า 170000 หากรุ่นต่ำกว่านี้จะติดตั้งไม่ได้ทั้งชุด และแผนงานส่วนที่เหลือต้องทบทวนใหม่ ส่วนคำสั่ง CREATE ROLE ปรากฏใน migration หมายเลข 027 และ 043 ถึง 047 สำหรับสร้าง gis_owner, gis_worker, gis_native_worker และ authenticator')]),
  para([run('สิ่งที่ต้องส่ง  ', { bold: true }), run('คำตอบสองข้อ ใช่หรือไม่ใช่ พร้อมภาพหน้าจอประกอบ')]),
  para([run('เกณฑ์ว่าเสร็จ  ', { bold: true }), run('ทีมทราบคำตอบทั้งสองข้ออย่างชัดเจน')]),
  ...callout('ยังไม่ต้องติดตั้ง migration และยังไม่ต้องแก้ไขฐานข้อมูลใด ๆ ในสัปดาห์นี้'),

  subheading('W2. บันทึกค่า digest ของ container image ลงคลังโค้ด'),
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

  subheading('W5. สร้าง Dockerfile ของ worker'),
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

  ...evidenceForm('6', [
    ['W1. ความพร้อมของฐานข้อมูล Supabase', [
      ['ผู้รับผิดชอบ', BLANK],
      ['วันที่ตรวจ', '......... / ......... / .........'],
      ['รุ่น PostgreSQL ที่อ่านได้จากแดชบอร์ด', BLANK],
      ['รุ่น 17 ขึ้นไปหรือไม่', 'ใช่ / ไม่ใช่'],
      ['บัญชีสร้าง role ได้หรือไม่', 'ได้ / ไม่ได้ / ยังไม่แน่ใจ'],
      ['แนบภาพหน้าจอหน้าตั้งค่าฐานข้อมูล', 'แนบแล้ว / ยังไม่แนบ'],
      ['ปัญหาที่พบ', BLANK],
    ]],
    ['W2. บันทึกค่า digest ลงคลังโค้ด', [
      ['ผู้รับผิดชอบ', BLANK],
      ['วันที่ทำเสร็จ', '......... / ......... / .........'],
      ['commit hash ที่เพิ่มไฟล์ images.json', BLANK],
      ['จำนวน digest ที่บันทึกได้', '......... จาก 6 รายการ'],
      ['รายการที่ยังขาด (ถ้ามี)', BLANK],
      ['ผลการสั่ง docker compose up บนเครื่องที่ไม่เคยรันมาก่อน', 'สำเร็จ / ไม่สำเร็จ'],
      ['หากไม่สำเร็จ ข้อความผิดพลาดที่ได้', BLANK],
    ]],
    ['W5. Dockerfile ของ worker', [
      ['ผู้รับผิดชอบ', BLANK],
      ['วันที่ทำเสร็จ', '......... / ......... / .........'],
      ['ที่อยู่ของไฟล์ Dockerfile', BLANK],
      ['คำสั่งที่ใช้ build', BLANK],
      ['ผลรัน pytest tests/test_ldd_policy_native.py ภายใน image', 'ผ่าน ......... ข้อ / ไม่ผ่าน ......... ข้อ'],
      ['ข้อ test_v1_artifacts_of_existing_fixtures_are_byte_identical', 'ผ่าน / ไม่ผ่าน / ยังถูกข้าม'],
      ['แนบผลรันแบบข้อความเต็ม', 'แนบแล้ว / ยังไม่แนบ'],
      ['ปัญหาที่พบ', BLANK],
    ]],
  ]),

  heading('7. ภาคผนวก ภาพหลักฐาน', { newPage: true }),
  para('วางภาพหน้าจอลงในกรอบด้านล่าง กรอบใดไม่มีภาพให้เขียนเหตุผลกำกับไว้แทน'),
  ...imageSlot(1, 'รุ่นของฐานข้อมูล (งาน W1)', 'หน้าแดชบอร์ด Supabase ส่วนที่ระบุรุ่น PostgreSQL โดยเห็นชื่อโครงการประกอบด้วย'),
  ...imageSlot(2, 'สิทธิ์สร้าง role (งาน W1)', 'ผลการตรวจสอบสิทธิ์ หรือข้อความผิดพลาดที่ได้เมื่อทดลองสร้าง role'),
  ...imageSlot(3, 'ผลการสั่ง docker compose up (งาน W2)', 'บรรทัดคำสั่งที่ใช้ และสถานะของคอนเทนเนอร์ทุกตัวหลังสั่ง'),
  ...imageSlot(4, 'ผลรันชุดทดสอบภายใน image (งาน W5)', 'บรรทัดสรุปท้ายของ pytest ที่ระบุจำนวนข้อที่ผ่าน ไม่ผ่าน และถูกข้าม'),
];

// ─────────────────────────────────────────────────────────────────────────
// ฉบับที่ 2: สำหรับผู้พัฒนาบรานช์เดิม
// ─────────────────────────────────────────────────────────────────────────
const doc2 = [
  title('เอกสารส่งมอบงาน ฉบับที่ 2'),
  para([run('สัปดาห์ที่ 9 ถึง 13 พฤศจิกายน 2569', { size: 26, bold: true, color: MUTED })],
    { align: AlignmentType.CENTER, after: 280 }),
  header('.............................................. (ผู้พัฒนาบรานช์ feature/gis-data-management)'),
  spacer(),

  heading('1. ขอบเขตของเอกสารฉบับนี้'),
  para('เอกสารนี้ครอบคลุมเฉพาะงานของสัปดาห์ที่ 9 ถึง 13 พฤศจิกายน 2569 เท่านั้น ยังมีเรื่องที่ต้องตัดสินใจอีกหลายข้อในระบบ GIS แต่ยังไม่ส่งมอบในรอบนี้'),
  ...callout('ขอความร่วมมือ กรุณาทำเฉพาะสี่รายการด้านล่าง และยังไม่ต้องเริ่มงานส่วนอื่น'),

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
    ['W6', 'ตรวจทานการแก้ไขด่านความปลอดภัยใน migration 027', 'ภายในพฤหัสบดี 12 พ.ย.', '1 ถึง 2 ชม.'],
    ['W7', 'เคาะขอบเขตของ legacy-v1 (เอกสาร ไม่ต้องแก้โค้ด)', 'ภายในพฤหัสบดี 12 พ.ย.', '1 ถึง 2 ชม.'],
  ], { align: [AlignmentType.CENTER, null, null, AlignmentType.CENTER] }),

  heading('4. รายละเอียดงาน'),

  subheading('W3. ส่งค่า digest ของ container image ทั้ง 6 รายการ'),
  para([run('สิ่งที่ต้องทำ  ', { bold: true }), run('ส่งค่า digest ที่ใช้งานอยู่จริงบนเครื่องของท่าน')]),
  table([4000, 5026], IMAGE_ROWS),
  spacer(100),
  para([run('เหตุผล  ', { bold: true }), run('ค่าทั้งหมดไม่มีบันทึกอยู่ในคลังโค้ด จากการตรวจสอบบนเครื่องของผู้จัดทำเอกสารพบว่า image ทั้งสองรายการของ worker ไม่มีอยู่ และค้นทั้งคลังโค้ดแล้วไม่พบค่าของตัวแปรทั้งสี่รายการแรก ขณะนี้จึงมีเพียงเครื่องของท่านเพียงเครื่องเดียวที่ประกอบระบบขึ้นมาได้')]),
  para([run('สิ่งที่ต้องส่ง  ', { bold: true }), run('ค่า digest ทั้ง 6 รายการ ส่งเป็นข้อความได้')]),
  para([run('เกณฑ์ว่าเสร็จ  ', { bold: true }), run('ผู้รับผิดชอบงาน W2 นำไปบันทึกลงคลังโค้ดได้')]),
  ...callout('นี่คืองานที่เร่งด่วนที่สุดในสัปดาห์นี้ หากเครื่องของท่านเสียหายก่อนส่งมอบ จะไม่มีวิธีสร้างสภาพแวดล้อมเดิมขึ้นใหม่ได้เลย'),

  subheading('W4. สร้าง sandbox T0 ขึ้นใหม่'),
  para([run('สิ่งที่ต้องทำ  ', { bold: true }), run('ดึงบรานช์ gis-unlock มาแล้วสร้าง T0 ขึ้นใหม่ตามขั้นตอนเดิมของท่าน')]),
  para([run('เหตุผล  ', { bold: true }), run('ตามข้อ 2 ค่า checksum ถูกคำนวณใหม่ ledger เดิมจึงไม่ตรงกับไฟล์ปัจจุบัน โค้ดและสคริปต์ของท่านไม่ต้องแก้ไข กระทบเฉพาะฐานข้อมูลเท่านั้น')]),
  para([run('สิ่งที่ต้องส่ง  ', { bold: true }), run('ผลการรันที่ยืนยันว่า gis_readiness() รายงานค่าถูกต้อง')]),
  para([run('เกณฑ์ว่าเสร็จ  ', { bold: true }), run('ชุดทดสอบบนเครื่องของท่านผ่านครบ')]),

  subheading('W6. ตรวจทานการแก้ไขด่านความปลอดภัยใน migration 027'),
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

  subheading('W7. เคาะขอบเขตของ legacy-v1'),
  para([run('สิ่งที่ต้องทำ  ', { bold: true }), run('ตัดสินใจและบันทึกเป็นลายลักษณ์อักษรว่า ค่าที่แก้ไขให้ถูกต้องแล้วใน commit 78f0219 ยังถือเป็นวิธีคำนวณ legacy-v1 เดิมอยู่หรือไม่ ไม่ต้องแก้โค้ด')]),
  para([run('ปัญหา  ', { bold: true }), run('commit 78f0219 บนบรานช์ main แก้การ mask เมฆของ Landsat จาก bit (3, 4) เป็น (1, 2, 3, 4) ทำให้อุณหภูมิที่รายงานขยับขึ้นประมาณ 0.10 ถึง 0.43 องศาเซลเซียส ขณะที่ gis_worker/method_registry.py ประกาศไว้ว่า lst_mask_bits เท่ากับ (3, 4) และ gis_worker/processing_provider.py อ่านค่านี้จากซอร์สจริงด้วย ast แล้วบังคับให้ตรงกัน เมื่อรวมบรานช์ ระบบจะปฏิเสธทันที')]),
  para('นอกจากค่าตัวเลขแล้ว โครงสร้างที่ตัวอ่านคาดหวังยังเปลี่ยนไปอีก 3 จุด'),
  table([2600, 3300, 3126], [
    ['จุดตรวจสอบ', 'รูปแบบที่ตัวอ่านคาดหวัง', 'รูปแบบหลังการรวม'],
    ['_mask_landsat_clouds', 'bitwiseAnd(1 << n)', 'bitwiseAnd(_LANDSAT_CLOUD_BITMASK) ซึ่งไม่ใช่ ast.BinOp'],
    ['S2_CLOUD_FILTER_PCT ใน compute.py', 'ค่าคงที่ระดับโมดูล', 'เปลี่ยนเป็น from gee_utils import ...'],
    ['ฟิลเตอร์เมฆใน _compute_ndvi_monthly', 'CLOUDY_PIXEL_PERCENTAGE ภายในฟังก์ชัน', 'ย้ายไปอยู่ใน s2_clean_collection()'],
  ]),
  spacer(100),
  para([run('ทางเลือกที่ต้องเคาะ', { bold: true })]),
  ...numbered([
    'ยังเป็น legacy-v1 โดยแก้ค่าที่ประกาศไว้และแก้ตัวอ่าน ast ให้รับโครงสร้างใหม่ ผลที่ตามมาคือ งานที่บันทึกไว้ก่อนหน้าว่าใช้ legacy-v1 จะมีตัวเลขคนละชุดกับงานใหม่ ทั้งที่ระบุชื่อวิธีเดียวกัน',
    'กำหนดเป็นวิธีใหม่ เช่น legacy-v2 โดยคงนิยาม legacy-v1 ไว้ตามเดิม ผลที่ตามมาคือ งานเก่ายังสืบย้อนได้ว่าคำนวณด้วยสูตรใด แต่มีงานเพิ่มในการตั้งนิยามใหม่',
  ]),
  para([run('สิ่งที่ต้องส่ง  ', { bold: true }), run('เอกสารความยาวประมาณครึ่งหน้า ระบุว่าเลือกทางใด เพราะเหตุใด และหากเลือกทางที่ 2 ให้ระบุชื่อเวอร์ชัน และแนวทางจัดการกับงานที่บันทึกไว้แล้ว')]),
  para([run('เกณฑ์ว่าเสร็จ  ', { bold: true }), run('มีคำตอบเป็นลายลักษณ์อักษรที่นำไปปฏิบัติต่อได้')]),
  ...callout('ยังไม่ต้องแก้โค้ดและยังไม่ต้องรวมบรานช์ในสัปดาห์นี้ ขอเพียงข้อสรุป เพื่อให้ดำเนินการต่อได้ในช่วงสุดสัปดาห์'),

  heading('5. งานที่ยังไม่ส่งมอบในรอบนี้'),
  para('รายการต่อไปนี้ต้องตัดสินใจร่วมกันก่อน กรุณายังไม่เริ่มดำเนินการ และจะนัดหารือในรอบถัดไป'),
  ...numbered([
    'การแก้โค้ดและการรวม commit 78f0219 เข้ากับบรานช์จริง (รอผลของงาน W7)',
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

  heading('8. แบบฟอร์มส่งหลักฐาน (ผู้รับมอบกรอกและส่งกลับ)'),
  para('ขอให้กรอกช่องว่างและแนบหลักฐานตามที่ระบุ แล้วส่งกลับภายในวันพฤหัสบดีที่ 12 พฤศจิกายน 2569'),
  subheading('W3. ค่า digest ของ container image'),
  table([4200, 4826], [
    ['ตัวแปร', 'ค่า digest'],
    ['GIS_LOCAL_DB_IMAGE', BLANK],
    ['GIS_LOCAL_AUTH_IMAGE', BLANK],
    ['GIS_LOCAL_REST_IMAGE', BLANK],
    ['GIS_LOCAL_GATEWAY_IMAGE', BLANK],
    ['WORKER_IMAGE', BLANK],
    ['GEE_MOCK_WORKER_IMAGE', BLANK],
    ['วันที่ส่ง', '......... / ......... / .........'],
  ]),
  spacer(120),
  ...formBlock('W4. สร้าง sandbox T0 ขึ้นใหม่', [
    ['วันที่ทำเสร็จ', '......... / ......... / .........'],
    ['gis_readiness() รายงาน cluster_name ว่า', BLANK],
    ['gis_readiness() รายงาน mode ว่า', BLANK],
    ['หมายเลข migration สูงสุดที่ติดตั้งได้', BLANK],
    ['ผลรันชุดทดสอบบนเครื่อง', 'ผ่าน ......... ข้อ / ไม่ผ่าน ......... ข้อ'],
    ['ปัญหาที่พบ', BLANK],
  ]),
  ...formBlock('W6. ตรวจทานด่านความปลอดภัยใน migration 027', [
    ['วันที่ตรวจ', '......... / ......... / .........'],
    ['ผลการตรวจ', 'รับได้ / มีข้อทักท้วง'],
    ['ข้อทักท้วงที่ 1', BLANK],
    ['ข้อทักท้วงที่ 2', BLANK],
    ['กรณีที่ควรทดสอบเพิ่ม แต่ยังไม่ได้ทดสอบ', BLANK],
  ]),
  ...formBlock('W7. ขอบเขตของ legacy-v1', [
    ['วันที่ตัดสินใจ', '......... / ......... / .........'],
    ['เลือกทางใด', 'ทางที่ 1 ยังเป็น legacy-v1 / ทางที่ 2 กำหนดเป็นวิธีใหม่'],
    ['หากเลือกทางที่ 2 ชื่อเวอร์ชันใหม่คือ', BLANK],
    ['เหตุผลโดยย่อ', BLANK],
    ['งานที่บันทึกไว้แล้วจะจัดการอย่างไร', BLANK],
    ['แนบเอกสารการตัดสินใจฉบับเต็ม', 'แนบแล้ว / ยังไม่แนบ'],
  ]),
  subheading('ลงนาม'),
  spacer(120),
  para('ผู้รับมอบ ...................................................... วันที่ ......... / ......... / .........'),
  spacer(200),
  para('ผู้ส่งมอบ ...................................................... วันที่ ......... / ......... / .........'),

  heading('9. ภาคผนวก ภาพหลักฐาน', { newPage: true }),
  para('วางภาพหน้าจอลงในกรอบด้านล่าง กรอบใดไม่มีภาพให้เขียนเหตุผลกำกับไว้แทน'),
  ...imageSlot(1, 'ค่า digest ที่ใช้งานอยู่จริง (งาน W3)', 'ผลของคำสั่ง docker images ที่แสดง digest ของ image ที่ใช้อยู่ หรือหน้าไฟล์ตั้งค่าที่เก็บค่าเหล่านั้น'),
  ...imageSlot(2, 'ผลลัพธ์ของ gis_readiness() (งาน W4)', 'ค่า cluster_name, mode และรายการหมายเลข migration ที่ติดตั้งแล้ว'),
  ...imageSlot(3, 'ผลรันชุดทดสอบหลังสร้าง T0 ใหม่ (งาน W4)', 'บรรทัดสรุปท้ายของ pytest ที่ระบุจำนวนข้อที่ผ่านและไม่ผ่าน'),
];

// ─────────────────────────────────────────────────────────────────────────
// ฉบับที่ 3: คำอธิบายแบบเข้าใจง่าย ใช้เล่าให้เพื่อนฟัง ไม่ใช่เอกสารลงนาม
// ─────────────────────────────────────────────────────────────────────────
const doc3 = [
  title('เล่าให้ฟังแบบสั้น ๆ'),
  para([run('ตอนนี้เรื่องมันเป็นยังไง และสัปดาห์หน้าใครต้องทำอะไร', { size: 26, bold: true, color: MUTED })],
    { align: AlignmentType.CENTER, after: 300 }),

  heading('1. ปัญหาคืออะไร'),
  para('ระบบจัดการข้อมูล GIS ที่ทำกันไว้ ใช้งานได้จริงและผ่านการทดสอบเกือบสองพันรายการ แต่มันทำงานได้เฉพาะบนเครื่องของคนที่เขียนเท่านั้น'),
  para('ไม่ใช่ว่าเขาทำพลาดนะ ตอนที่เขาทำ เป้าหมายคือให้มันปลอดภัยและรันในเครื่องก่อน มันเลยถูกออกแบบให้ปฏิเสธทุกอย่างที่ไม่ใช่เครื่องตัวเอง ซึ่งถูกต้องแล้วสำหรับเป้าหมายตอนนั้น'),
  para('แต่ตอนนี้เราอยากให้คนอื่นใช้ได้ด้วย เป้าหมายเลยเปลี่ยน ของที่เคยถูกจึงต้องรื้อ'),
  ...callout('เปรียบง่าย ๆ คือ ร้านอาหารที่ทำอร่อยมาก แต่สูตรอยู่ในหัวเชฟคนเดียว วันไหนเชฟไม่มา ร้านก็เปิดไม่ได้'),

  heading('2. ทำอะไรไปแล้วบ้าง'),
  para('ประตูที่ล็อกไว้มี 5 ชั้น ตอนนี้เปิดไปแล้ว 3 ชั้น'),
  table([5500, 1800, 1726], [
    ['ชั้น', 'เดิม', 'ตอนนี้'],
    ['ฐานข้อมูล', 'ลงได้เฉพาะเครื่องตัวเอง', 'เปิดแล้ว'],
    ['ตัวเซิร์ฟเวอร์', 'ปฏิเสธทุกคำขอ', 'เปิดแล้ว'],
    ['หน้าเว็บ', 'ใช้ได้เฉพาะเปิดจากเครื่องตัวเอง', 'เปิดแล้ว'],
    ['ตัวประมวลผลเบื้องหลัง', 'ผูกกับเครื่องตัวเอง', 'ยังไม่เปิด'],
    ['ที่เก็บไฟล์ที่อัปโหลด', 'เก็บในเครื่อง หายเมื่อรีสตาร์ต', 'ยังไม่เปิด'],
  ], { align: [null, null, AlignmentType.CENTER] }),
  spacer(120),
  para('สองชั้นที่เหลือไม่ได้ติดที่การเขียนโค้ด แต่ติดที่ยังไม่มีใครตัดสินใจว่าจะเอายังไง'),

  heading('3. เรื่องที่น่าห่วงที่สุดที่เจอ'),
  para('ระบบต้องใช้โปรแกรมสำเร็จรูป 6 ตัวในการทำงาน แต่ในโค้ดไม่ได้เขียนไว้ว่าเป็นตัวไหน มีแต่รหัสอ้างอิงยาว ๆ และตัวจริงมีอยู่แค่ในเครื่องของคนที่เขียนเท่านั้น'),
  para('ลองค้นทั้งโปรเจกต์แล้วไม่เจอ ลองเรียกบนเครื่องอื่นก็ขึ้นว่าไม่มี'),
  ...callout('แปลว่าถ้าเครื่องเขาพัง หรือเผลอล้างเครื่อง ระบบส่วนนั้นสร้างกลับมาไม่ได้อีกเลย นี่คือเหตุผลที่งานชิ้นแรกของเขาคือส่งรหัส 6 ตัวนี้มา และขอให้ทำตั้งแต่วันจันทร์'),

  heading('4. สัปดาห์หน้าใครทำอะไร'),
  para('งานคนละประมาณ 1 วัน ไม่ใช่ทั้งสัปดาห์ เพราะสัปดาห์นี้เป็นสัปดาห์หาคำตอบ ยังไม่ใช่สัปดาห์ลงมือเต็มที่'),
  table([1000, 3800, 4226], [
    ['', 'คนดูแลสภาพแวดล้อม', 'คนที่เขียนระบบ GIS'],
    ['จันทร์', 'เปิดดูว่าฐานข้อมูลที่เราเช่าอยู่ รุ่นใหม่พอหรือยัง', 'ส่งรหัสโปรแกรม 6 ตัวมาให้'],
    ['อังคาร ถึง พุธ', 'เอารหัสนั้นมาเก็บไว้ในโปรเจกต์ ให้คนอื่นใช้ได้', 'สร้างฐานข้อมูลในเครื่องตัวเองใหม่'],
    ['พุธ ถึง พฤหัส', 'เขียนสูตรสร้างโปรแกรมตัวประมวลผล ให้ใครก็สร้างได้', 'ตรวจทานส่วนที่เราไปแก้ และเคาะเรื่องสูตรคำนวณ'],
  ]),
  spacer(120),
  ...callout('ทุกอย่างต้องเสร็จภายในพฤหัสบดี เพราะบ่ายวันศุกร์ต้องส่งอาจารย์'),

  heading('5. ทำไมต้องรีบสองเรื่องนี้'),
  ...numbered([
    'เรื่องรุ่นของฐานข้อมูล ถ้ารุ่นเก่าเกินไป สิ่งที่เราทำไปทั้งหมดจะใช้กับของจริงไม่ได้ ต้องวางแผนใหม่ ยิ่งรู้เร็วยิ่งดี รู้ตอนธันวาคมคือสายเกินไป',
    'เรื่องรหัสโปรแกรม 6 ตัว ถ้าเครื่องเขาพังก่อนส่ง ก็จบ สร้างใหม่ไม่ได้ เป็นความเสี่ยงที่ปิดได้ภายในชั่วโมงเดียว',
  ]),

  heading('6. ขอให้ยังไม่ทำอะไรเกินกว่านี้'),
  para('ในเอกสารจะเขียนกำกับไว้ว่างานไหนยังไม่ต้องเริ่ม ไม่ใช่เพราะกั๊กงาน แต่เพราะงานที่เหลือขึ้นอยู่กับคำตอบสองข้อข้างบน ถ้าเริ่มก่อนแล้วคำตอบออกมาอีกแบบ ก็ต้องรื้อทำใหม่ เสียเวลาเปล่า'),
  para('ส่วนเอกสารฉบับเต็มของแต่ละคน จะมีรายละเอียดว่าต้องส่งอะไร ตรวจยังไงว่าเสร็จ และมีช่องให้กรอกผลกับวางภาพหน้าจอไว้ให้แล้ว'),
];

const OUT = process.argv[2] || '.';
Promise.all([
  build(path.join(OUT, 'เอกสารส่งมอบงาน_1_สภาพแวดล้อมที่ทำซ้ำได้.docx'), doc1),
  build(path.join(OUT, 'เอกสารส่งมอบงาน_2_สัญญาวิธีคำนวณและการอนุมัติ.docx'), doc2),
  build(path.join(OUT, 'เล่าให้ฟังแบบสั้นๆ_อธิบายเพื่อน.docx'), doc3),
]).catch(e => { console.error(e); process.exit(1); });
