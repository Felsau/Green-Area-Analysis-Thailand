# -*- coding: utf-8 -*-
"""สร้าง PDF สรุปงานวิจัยเชิงลึก (ภาษาไทย) พร้อมผลการทดลอง + อภิธานศัพท์

งานวิจัย: Moukomla, Meeprom & Intarat (2026)
"Impact of Impervious Surface Expansion on Urban Thermal Environment Across
 Tropical Southeast Asian Megacities..." Earth 7(3):76.
 https://doi.org/10.3390/earth7030076

เหตุผลที่ใช้ PyMuPDF (ไม่ใช่ reportlab):
  reportlab ไม่ทำ GPOS mark positioning ของไทย → พยางค์ที่มี พยัญชนะ+สระบน+
  วรรณยุกต์ (เช่น "พื้น" "ที่") วรรณยุกต์จะ "จม" ทับสระ. PyMuPDF Story ใช้
  harfbuzz shape ภาษาไทยถูกต้อง จึงยกวรรณยุกต์ขึ้นเหนือสระบนครบทุกพยางค์.

ผลผลิต: presentation/Earth_Paper_Summary_ISA_SUHI.pdf
"""
import os
import io
import fitz  # PyMuPDF

ROOT = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(ROOT)
FONT_DIR = os.path.join(REPO_ROOT, 'green-area-frontend', 'public', 'fonts')

# A4 (pt) + margins
PW, PH = 595.0, 842.0
ML, MR, MT, MB = 40.0, 40.0, 58.0, 46.0

arch = fitz.Archive()
arch.add(os.path.join(FONT_DIR, 'Sarabun-Regular.ttf'), 'sb.ttf')
arch.add(os.path.join(FONT_DIR, 'Sarabun-Bold.ttf'), 'sbb.ttf')

# หมายเหตุ glyph/rendering:
#  1) ทุก element ที่มีข้อความ (td/p/li/.sub/.cap ฯลฯ) ต้องกำหนด background ชัดเจน
#     มิฉะนั้น MuPDF Story จะดึงสี fill ค้าง (เขียวหัวตาราง) มาเลอะเป็นแถบ
#  2) ตารางใช้ border-collapse: separate + border-spacing: 0 (ห้ามใช้ collapse)
#     เพราะ collapse ทำให้ MuPDF echo พื้นตารางว่างเต็มหน้าสุดท้าย (phantom tables)
#  3) ความกว้างคอลัมน์กำหนดแบบ inline บนเซลล์ (px/%), CSS class ไม่มีผลกับ layout ตาราง
CSS = """
@font-face { font-family: sb; src: url(sb.ttf); }
@font-face { font-family: sb; font-weight: bold; src: url(sbb.ttf); }
* { font-family: sb; font-size: 10.5px; color: #202124; line-height: 1.5; }
p, li, .sub, .subb, .cap { background: #ffffff; }
p  { margin: 2px 0 6px 0; text-align: justify; }
b, .bold { font-weight: bold; }
.mono { font-family: sb; color: #0e5c24; }
.muted { color: #5f6368; font-size: 9px; }

.title { background: #1a73e8; color: #fff; padding: 11px 13px; }
.title .h { font-weight: bold; font-size: 16px; color: #fff; }
.title .s { font-size: 10px; color: #d6e4ff; }

.sec { background: #0e5c24; color: #fff; font-weight: bold; font-size: 12.5px;
       padding: 6px 10px; margin: 12px 0 7px 0; }

.card { border: 1px solid #dadce0; border-left: 3px solid #1a73e8; }
.card td { border-bottom: 1px solid #eceff1; padding: 4px 7px; vertical-align: top;
           font-size: 9.6px; }
.card td.k { background: #f1f3f4; color: #0e5c24; font-weight: bold; width: 21%;
             font-size: 9.3px; }

table.dt { border-collapse: separate; border-spacing: 0; width: 100%; margin: 2px 0 3px 0; }
table.dt th { background: #0e5c24; color: #fff; font-weight: bold; font-size: 8.8px;
              padding: 4px 4px; border: 1px solid #cfd8dc; text-align: center; }
table.dt td { padding: 3.5px 4px; border: 1px solid #dadce0; font-size: 8.8px;
              text-align: center; background: #ffffff; }
table.dt td.l { text-align: left; }
table.dt tr.alt td { background: #f6faf7; }
table.dt tr.hi td { background: #fff7e6; }
.cap { color: #5f6368; font-size: 8.6px; margin: 0 0 8px 0; text-align: left; }

table.co { border-collapse: separate; border-spacing: 0; width: 100%; margin: 3px 0 8px 0; }
table.co td { padding: 6px 10px; }
td.co-g { background: #e6f4ea; border-left: 3px solid #1e8e3e; }
td.co-o { background: #fff2e6; border-left: 3px solid #f97316; }
td.co-p { background: #f3edfd; border-left: 3px solid #7c3aed; }

.sub { font-weight: bold; color: #0e5c24; font-size: 10.5px; margin: 6px 0 2px 0; }
.subb { font-weight: bold; color: #1a73e8; font-size: 10px; margin: 6px 0 1px 0; }
ul { margin: 2px 0 6px 0; }
li { margin: 0 0 3px 0; text-align: justify; }

table.gl { border-collapse: separate; border-spacing: 0; width: 100%; margin: 1px 0 6px 0; }
table.gl td { border: 1px solid #dadce0; padding: 3.5px 7px; font-size: 9.3px;
              vertical-align: top; }
table.gl td.t { width: 27%; font-weight: bold; color: #0e5c24; background: #f6faf7; }
"""


# ── helpers สร้าง HTML ──────────────────────────────────────────────────────
def esc(s):
    return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def sec(num, title):
    return f'<div class="sec">{num}&nbsp;&nbsp;{title}</div>'


def card(rows):
    body = ''.join(
        f'<tr><td class="k" style="width:120px">{k}</td><td>{v}</td></tr>'
        for k, v in rows)
    return f'<table class="card" style="width:100%">{body}</table>'


def dtable(headers, rows, widths, cap=None, hi=(), aligns=None):
    """widths: list %/col · hi: set แถวที่ไฮไลต์ (0-based) · aligns: 'l' ต่อคอลัมน์"""
    th = ''.join(
        f'<th style="width:{w}%">{h}</th>' for h, w in zip(headers, widths))
    body = f'<tr>{th}</tr>'
    for i, r in enumerate(rows):
        cls = ' class="hi"' if i in hi else (' class="alt"' if i % 2 == 1 else '')
        tds = ''
        for j, c in enumerate(r):
            cl = ' class="l"' if (j == 0 or (aligns and aligns[j] == 'l')) else ''
            tds += f'<td{cl}>{c}</td>'
        body += f'<tr{cls}>{tds}</tr>'
    out = f'<table class="dt">{body}</table>'
    if cap:
        out += f'<div class="cap">{cap}</div>'
    return out


def callout(text, kind='g'):
    return (f'<table class="co" style="width:100%"><tr>'
            f'<td class="co-{kind}">{text}</td></tr></table>')


def bullets(items):
    return '<ul>' + ''.join(f'<li>{i}</li>' for i in items) + '</ul>'


def gtable(rows):
    body = ''.join(
        f'<tr><td class="t" style="width:150px">{t}</td><td>{d}</td></tr>'
        for t, d in rows)
    return f'<table class="gl" style="width:100%">{body}</table>'


# ── เนื้อหา ─────────────────────────────────────────────────────────────────
H = []

H.append(
    '<div class="title"><span class="h">สรุปงานวิจัยเชิงลึก + ผลการทดลอง</span>'
    '<br/><span class="s">การขยายตัวของพื้นผิวทึบน้ำกับสภาพความร้อนเมืองใน 5 '
    'มหานครเขตร้อน SE Asia — ประเมินด้วย Foundation Model Embeddings '
    '(AlphaEarth)</span></div>')

# 1. บรรณานุกรม
H.append(sec('1', 'ข้อมูลบรรณานุกรม (Bibliographic Details)'))
H.append(card([
    ('ชื่อเรื่อง', 'Impact of Impervious Surface Expansion on Urban Thermal '
     'Environment Across Tropical Southeast Asian Megacities: Reliable '
     'Assessment Through Foundation Model Embeddings'),
    ('ผู้เขียน', 'Sitthisak Moukomla, Phurith Meeprom, Kritchayan Intarat'),
    ('สังกัด', 'ภาควิชาภูมิศาสตร์ / GRACE Lab / Capybara Geo Lab, คณะศิลปศาสตร์ '
     'มหาวิทยาลัยธรรมศาสตร์ · ภาควิชาภูมิสารสนเทศ มหาวิทยาลัยบูรพา (ทีมนักวิจัยไทย)'),
    ('วารสาร', '<b>Earth</b> (MDPI, open access CC BY) · 2026, เล่ม 7, ฉบับ 3, '
     'บทความที่ 76 · 25 หน้า'),
    ('DOI', 'https://doi.org/10.3390/earth7030076'),
    ('กำหนดการ', 'รับ 3 เม.ย. 2026 · แก้ไข 5 พ.ค. · ตอบรับ 7 พ.ค. · ตีพิมพ์ 8 พ.ค. 2026'),
    ('ทุน', 'คณะศิลปศาสตร์ มหาวิทยาลัยธรรมศาสตร์'),
    ('โค้ด + ข้อมูล (เปิด)', 'GitHub: github.com/SitthisakMoukomla/tropical-urban-'
     'AlphaEarth · Zenodo DOI: 10.5281/zenodo.19945781 · Python 3.11 + '
     'scikit-learn + earthengine-api'),
]))

# 2. ที่มา
H.append(sec('2', 'ที่มาของปัญหา &amp; คำถามวิจัย'))
H.append('<p>เอเชียตะวันออกเฉียงใต้เป็นภูมิภาคที่ขยายเมืองเร็วที่สุดในโลก '
         '(ประชากรเมืองจะเกิน 400 ล้านคนในปี 2030) การแทนที่พื้นที่พืชพรรณด้วย'
         'พื้นผิวทึบน้ำ (คอนกรีต/ยางมะตอย/หลังคา) เร่งปรากฏการณ์ <b>เกาะความร้อน'
         'เมือง (UHI)</b> เพิ่มน้ำท่วมฉับพลัน และลดการกักเก็บคาร์บอน แต่การติดตาม'
         'ด้วยดาวเทียมเชิงแสงถูกจำกัดด้วย <b>เมฆบัง 50–70%</b> ต่อปี ทำให้วิธี '
         'single-date แบบเดิม "ใช้งานจริงไม่ได้" ในเขตร้อน</p>')
H.append('<p><b>คำถามวิจัย 4 ข้อ:</b> (1) ISA ขยายตัวเท่าไรใน 5 เมือง ปี 2017–2024? '
         '(2) ISA สัมพันธ์กับ LST/SUHI แค่ไหน? (3) การเลือกวิธี classify อ่อนไหว'
         'ต่อสภาพเมฆแค่ไหน? (4) AlphaEarth embeddings ให้ค่า ISA ที่นิ่งพอสำหรับ'
         'ประเมินความร้อนเมืองได้หรือไม่ เมื่อวิธี single-date ขาดข้อมูล?</p>')
H.append(callout(
    '<b>แนวคิดหลัก:</b> ใช้ <b>AlphaEarth foundation-model embeddings</b> '
    '(embedding 64 มิติ ราย<b>ปี</b>) ที่มี cloud masking + เติมช่องว่าง + '
    'multi-temporal compositing มา<b>ในตัว</b> → ได้ข้อมูลครบทั้งปีไม่ว่าเมฆจะ'
    'บังแค่ไหน แล้วโยงกับ MODIS LST เพื่อวัดความร้อนเมือง', 'g'))

# 3. อภิธานศัพท์ (glossary) — ใหม่
H.append(sec('3', 'คำศัพท์ที่ควรรู้ (Glossary) — คำเฉพาะทางในงานวิจัย'))
H.append('<div class="subb">ก. แนวคิด / ปรากฏการณ์</div>')
H.append(gtable([
    ('ISA (Impervious Surface Area)', 'พื้นผิวทึบน้ำ — ผิวที่น้ำซึมผ่านไม่ได้ '
     '(คอนกรีต ยางมะตอย หลังคา ถนน ลานจอด) ตรงข้ามกับพืชพรรณ/ดินเปิด'),
    ('UHI (Urban Heat Island)', 'เกาะความร้อนเมือง — เมืองมีอุณหภูมิสูงกว่าพื้นที่'
     'รอบข้าง (วัดจากอุณหภูมิ<b>อากาศ</b>)'),
    ('SUHI (Surface UHI)', 'เกาะความร้อน<b>พื้นผิว</b>เมือง — วัดจากอุณหภูมิ'
     '<b>ผิว</b> (LST) ต่างจาก UHI ที่วัดอากาศ · ในงานนี้ = LST เมือง (ISA≥50%) '
     'ลบ LST ชนบท (ISA≤10%)'),
    ('LST (Land Surface Temperature)', 'อุณหภูมิพื้นผิวโลกที่วัดจากดาวเทียมแถบ'
     'ความร้อน (หน่วย °C/K)'),
    ('NDVI', 'ดัชนีพืชพรรณ = (NIR−Red)/(NIR+Red) · ค่าสูง = พืชพรรณหนาแน่น · '
     'ในเมืองเขตร้อนต้นไม้ให้ค่า 0.3–0.5 ทำให้ threshold เดี่ยวคลาดเคลื่อน'),
    ('Peri-urban / urbanizing fringe', 'พื้นที่ขอบเมือง / รอยต่อเมือง–ชนบทที่'
     'กำลังขยายตัว (จุดที่ความร้อนส่วนเพิ่มแรงสุด)'),
    ('Mixed pixel', 'พิกเซลที่มีทั้งพื้นผิวทึบและพืชพรรณปนกัน (ทำให้ classify ยาก)'),
    ('pp (percentage point)', 'จุดร้อยละ — ผลต่างของ % โดยตรง เช่น +11 pp คือ ISA '
     'เพิ่มจาก 36.7% เป็น 47.7% (ไม่ใช่เพิ่ม 11%)'),
]))
H.append('<div class="subb">ข. โมเดล / ข้อมูล / แพลตฟอร์ม</div>')
H.append(gtable([
    ('Foundation model embeddings', 'เวกเตอร์คุณลักษณะจากโมเดล "ตั้งต้น" ที่ '
     'pre-train ด้วยข้อมูลมหาศาล นำไปใช้ต่องานอื่นได้โดยไม่ต้อง train ใหม่ทั้งหมด'),
    ('AlphaEarth', 'โมเดล/ชุด embedding ของ Google (asset '
     '<span class="mono">GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL</span>) — '
     '64 มิติ ราย<b>ปี</b> ที่ 10 m คลุมปี 2017–2024'),
    ('Embedding 64 มิติ (A00–A63)', 'เวกเตอร์ 64 ค่าที่สรุปคุณสมบัติพื้นผิวเชิงเวลา '
     '— เป็นแกนที่โมเดล "เรียนรู้" ไม่ใช่ค่าแสงตรงๆ เหมือนแบนด์สเปกตรัม'),
    ('Sentinel-2', 'ดาวเทียมเชิงแสงความละเอียด 10 m ของ ESA (แบนด์ B2–B12) '
     'ใช้คำนวณ NDVI/ดัชนีต่างๆ'),
    ('MODIS (MOD11A2)', 'เซนเซอร์/ผลิตภัณฑ์ LST 1 km ราย 8 วัน (Terra) ใช้วัด'
     'ความร้อนผิวในงานนี้'),
    ('Dynamic World', 'ผลิตภัณฑ์ land cover 10 m near-real-time (deep learning) '
     'ใช้เป็น "ป้ายอ้างอิง" (built prob &gt; 0.5 = เมือง)'),
    ('JRC GHSL', 'Global Human Settlement Layer — ชั้นข้อมูลสิ่งปลูกสร้างของ EU '
     'ใช้ตรวจสอบข้ามแบบอิสระ'),
    ('GEE (Google Earth Engine)', 'แพลตฟอร์มประมวลผลภูมิสารสนเทศบนคลาวด์ '
     '(โปรเจกต์เราก็ใช้เป็น backend เช่นกัน)'),
]))
H.append('<div class="subb">ค. วิธีการ / สถิติ / ตัวชี้วัด</div>')
H.append(gtable([
    ('Random Forest (RF)', 'อัลกอริทึมจำแนกแบบ ensemble ของต้นไม้ตัดสินใจหลายต้น '
     '(งานนี้ 100 ต้น, depth 15)'),
    ('IoU (Intersection over Union)', 'TP/(TP+FP+FN) — ตัวชี้วัดความแม่นเชิงพื้นที่ '
     '<b>เข้มกว่า accuracy</b> (ลงโทษทั้ง over/under) · &gt;0.85 = คุณภาพใช้งานได้'),
    ('F1 / Precision / Recall', 'ตระกูลตัวชี้วัด classification · F1 = ค่าเฉลี่ย'
     'ฮาร์มอนิกของ precision (ความแม่นเมื่อทาย +) กับ recall (จับ + ได้ครบแค่ไหน)'),
    ('Ablation study', 'การทดลอง "ถอด/เทียบ" องค์ประกอบทีละส่วน เพื่อดูว่าอะไรทำให้'
     'ผลดีขึ้น (งานนี้เทียบ 4 วิธี classify)'),
    ('LOCO (Leave-One-City-Out)', 'cross-validation แบบตัด<b>ทีละเมือง</b>ออกไป'
     'ทดสอบ — วัดว่าโมเดล transfer ไปเมืองที่ไม่เคยเห็นได้ดีแค่ไหน'),
    ('Pearson r', 'สัมประสิทธิ์สหสัมพันธ์เชิงเส้น (−1 ถึง +1) · ใกล้ +1 = ยิ่ง '
     'ISA มาก ยิ่ง LST สูง'),
    ('95% CI (Confidence Interval)', 'ช่วงความเชื่อมั่น 95% — ช่วงที่ค่าจริงน่าจะ'
     'อยู่ (ยิ่งแคบยิ่งมั่นใจ)'),
    ('Theil–Sen slope', 'การประมาณความชันแนวโน้มแบบ robust (ทนค่าผิดปกติ) ใช้ยืนยัน'
     'อัตราการโต ISA'),
    ('Monte-Carlo', 'การจำลองสุ่มหลายพันรอบ (เช่น รบกวน LST ±1 K) เพื่อประเมินความ'
     'ไม่แน่นอนของผล'),
]))

# 4. พื้นที่ศึกษา
H.append(sec('4', 'พื้นที่ศึกษา — 5 มหานครเขตร้อน (ตารางที่ 1)'))
H.append(dtable(
    ['เมือง', 'ประชากร (ล้าน)', 'พื้นที่ (km²)', 'ความหนาแน่น (พัน/km²)',
     'เมฆบัง (%)', 'รูปแบบเมือง'],
    [
        ['กรุงเทพฯ (ไทย)', '10.5', '1,569', '6.7', '50–51', 'แผ่กว้าง, ผสม'],
        ['จาการ์ตา (อินโดฯ)', '10.6', '664', '16.0', '54–63', 'หนาแน่น, แนวตั้ง'],
        ['มะนิลา (ฟิลิปปินส์)', '13.9', '619', '22.5', '53–59', 'แน่นมาก, สลัม'],
        ['กัวลาลัมเปอร์ (มาเลย์)', '1.8', '243', '7.4', '67–71', 'วางผัง, ควบคุม'],
        ['โฮจิมินห์ (เวียดนาม)', '9.0', '2,095', '4.3', '55–61', 'กำลังขยาย, ผสม'],
    ],
    [22, 14, 13, 17, 12, 22],
    cap='ตารางที่ 1 — ครอบคลุมละติจูด 20° (6.2°S–14.6°N) ประชากร 1.8–13.9 ล้านคน '
        'เมฆบัง 50–71% (กัวลาลัมเปอร์เมฆหนาสุดจากพายุฝนบ่ายทั้งปี)',
    hi={0}, aligns=[None, None, None, None, None, 'l']))

# 5. ข้อมูล & วิธีการ
H.append(sec('5', 'ข้อมูลและวิธีการ (Data &amp; Methods)'))
H.append('<div class="sub">แหล่งข้อมูลหลัก (Google Earth Engine asset)</div>')
H.append(bullets([
    '<b>AlphaEarth</b> — <span class="mono">GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL'
    '</span> · 64 แบนด์ (A00–A63) ราย<b>ปี</b> ที่ 10 m (2017–2024)',
    '<b>LST/ความร้อน</b> — MODIS <span class="mono">MOD11A2</span> '
    '(LST_Day_1km, 8-day) ฤดูแล้ง (ธ.ค.–เม.ย.) แปลง K→°C ด้วย scale 0.02',
    '<b>Reference label</b> — Dynamic World <span class="mono">'
    'GOOGLE/DYNAMICWORLD/V1</span> (built prob &gt; 0.5) + ตรวจข้ามกับ JRC GHSL '
    'Built-up (2018)',
    '<b>ขอบเขตเมือง</b> — FAO GAUL 2015 Level-1 · <b>Sentinel-2</b> '
    '<span class="mono">COPERNICUS/S2_SR_HARMONIZED</span> (สำหรับ baseline)',
]))
H.append('<div class="sub">เปรียบเทียบ 4 วิธี classify (ablation) + baseline ที่ยุติธรรมด้านมิติ</div>')
H.append(dtable(
    ['วิธี', 'ฟีเจอร์', 'แนวคิด'],
    [
        ['① AlphaEarth (เสนอ)', 'embedding 64 มิติ + RF', 'multi-temporal, cloud-resilient'],
        ['② Best single-date S2', '5 ดัชนี + RF', 'เลือกภาพเมฆน้อยสุด (best-case)'],
        ['③ Random single-date S2', '5 ดัชนี + RF', 'ภาพกลาง list (operational reality)'],
        ['④ NDVI threshold', 'NDVI &lt; 0.2', 'baseline ดั้งเดิม ไม่ใช้ ML'],
        ['(เสริม) S2 annual 15-feat', '10 แบนด์ + 5 ดัชนี + RF', 'baseline แข็งขึ้น แก้ข้อกังขาเรื่องมิติ'],
    ],
    [26, 30, 44],
    cap='RF = Random Forest (100 ต้น, depth 15, seed 42) · ตัวชี้วัดหลัก IoU '
        '(เข้มกว่า accuracy) + F1 + Overall Accuracy',
    hi={0}, aligns=['l', 'l', 'l']))
H.append(callout(
    '<b>นิยาม SUHI:</b> ความต่างของ LST ระหว่างพิกเซลเมือง (ISA ≥ 50%) กับพิกเซล'
    'ชนบท (ISA ≤ 10%) ตามเกณฑ์ Imhoff et al. (2010) · <b>การประเมินความไม่แน่นอน:'
    '</b> Wilson CI + Fisher-z + Theil–Sen + Monte-Carlo 1000 รอบ (perturb LST '
    '±1 K)', 'p'))

# 6. ผลการทดลอง
H.append(sec('6', 'ผลการทดลอง (Results) — แนบตารางจากงานวิจัยจริง'))

H.append('<div class="sub">6.1 สถิติเมฆบัง — ยืนยันความล้มเหลวของ single-date (ตารางที่ 2)</div>')
H.append(dtable(
    ['เมือง', 'เมฆเฉลี่ย (%)', 'ภาพใช้ได้ (%)', 'ภาพดีสุด (%)', 'ภาพทั้งหมด'],
    [
        ['กัวลาลัมเปอร์', '68.9', '6.0', '6.3', '296'],
        ['จาการ์ตา', '58.8', '19.1', '0.7', '572'],
        ['โฮจิมินห์', '58.1', '18.6', '0.0', '872'],
        ['มะนิลา', '55.8', '16.7', '1.6', '291'],
        ['กรุงเทพฯ', '50.9', '27.4', '0.0', '442'],
        ['เฉลี่ย', '58.5', '17.6', '1.7', '2,473'],
    ],
    [28, 20, 20, 18, 14],
    cap='ตารางที่ 2 — วิธี single-date (เกณฑ์เมฆ &lt;20%) ใช้ภาพได้เฉลี่ยเพียง '
        '17.6% → ล้มเหลว 82.5% · กรุงเทพฯ แม้เมฆน้อยสุดยัง fail acquisition 98.5% '
        '· กัวลาลัมเปอร์ใช้ได้แค่ ~22 วัน/ปี',
    hi={4, 5}))

H.append('<div class="sub">6.2 ประสิทธิภาพ AlphaEarth รายเมือง — ไม่ขึ้นกับเมฆ (ตารางที่ 4)</div>')
H.append(dtable(
    ['เมือง', 'เมฆ (%)', 'ภาพใช้ได้ (%)', 'IoU (%)', 'F1 (%)', 'ตัวอย่าง'],
    [
        ['มะนิลา', '55.8', '16.7', '93.7', '96.8', '5,992'],
        ['จาการ์ตา', '58.8', '19.1', '93.1', '96.4', '6,000'],
        ['กัวลาลัมเปอร์', '68.9', '6.0', '88.2', '93.8', '6,000'],
        ['กรุงเทพฯ', '50.9', '27.4', '87.9', '93.5', '3,392'],
        ['โฮจิมินห์', '58.1', '18.6', '83.1', '90.8', '3,794'],
        ['เฉลี่ย', '58.5', '17.6', '89.2', '94.3', '25,178'],
    ],
    [24, 15, 19, 14, 14, 14],
    cap='ตารางที่ 4 — IoU 83–94% แม้เมฆต่างกันมาก · ความสัมพันธ์เมฆ↔IoU '
        'r = −0.069, p = 0.851 (ไม่มีนัยสำคัญ) → AlphaEarth ทนเมฆ เหมาะเขตร้อน',
    hi={3, 5}))

H.append('<div class="sub">6.3 เปรียบเทียบวิธี (ablation, repeated holdout) (ตารางที่ 6)</div>')
H.append(dtable(
    ['วิธี', 'Mean IoU', 'Std IoU', 'Mean F1', 'Mean Acc', 'สำเร็จ (เมือง)'],
    [
        ['① AlphaEarth', '0.904', '0.054', '0.949', '0.939', '100% (5/5)'],
        ['② Best single S2 (RF)', '0.842', '0.076', '0.913', '0.882', '60% (3/5)'],
        ['③ Random single S2 (RF)', '0.777', '0.078', '0.873', '0.821', '80% (4/5)'],
        ['④ NDVI threshold', '0.624', '0.195', '0.753', '0.737', '100% (5/5)'],
    ],
    [28, 15, 14, 14, 14, 15],
    cap='ตารางที่ 6 — AlphaEarth ชนะทุกด้าน · robust holdout: AlphaEarth IoU '
        '0.866 (95%CI 0.857–0.875) เทียบ S2 annual 15-feat 0.758 และ single-date '
        '0.686 → เหนือกว่าแม้เทียบ baseline ที่แข็งขึ้น',
    hi={0}, aligns=['l', None, None, None, None, None]))

H.append('<div class="sub">6.4 IoU รายวิธี × เมือง — ความจริงเชิงปฏิบัติ (ตารางที่ 7)</div>')
H.append(dtable(
    ['เมือง', 'AlphaEarth', 'Best S2', 'Random S2', 'NDVI'],
    [
        ['จาการ์ตา', '94.05%', '90.22%', 'ล้มเหลว †', '84.14%'],
        ['มะนิลา', '93.89%', '89.96%', '89.12%', '72.07%'],
        ['กรุงเทพฯ', '92.42%', 'ล้มเหลว †', '71.98%', '46.23%'],
        ['กัวลาลัมเปอร์', '90.46%', '82.17%', '75.61%', '71.62%'],
        ['โฮจิมินห์', '81.00%', '74.29%', '73.97%', '37.68%'],
        ['เฉลี่ย', '90.36%', '84.16%', '77.67%', '62.35%'],
    ],
    [24, 20, 19, 19, 18],
    cap='ตารางที่ 7 — † ล้มเหลว = สุ่มตัวอย่างได้ &lt;100 จุด train ไม่ได้ · '
        'NDVI พังหนักในเมืองเขตร้อน (กรุงเทพฯ 46%, โฮจิมินห์ 38%) เพราะต้นไม้ใน'
        'เมืองให้ NDVI 0.3–0.5 สูงเกิน threshold',
    hi={2}))

H.append('<div class="sub">6.5 ★ การขยายตัว ISA + ความเข้ม SUHI ปี 2017–2024 (ตารางที่ 10)</div>')
H.append(dtable(
    ['เมือง', 'ISA เปลี่ยน 2017–2024', 'ISA slope (pp/ปี; 95%CI)',
     'SUHI เฉลี่ย (°C; 95%CI)'],
    [
        ['กรุงเทพฯ', '+7.4 pp', '1.27 (0.85–1.69)', '4.01 (3.68–4.34)'],
        ['จาการ์ตา', '+4.1 pp', '0.63 (0.41–0.85)', '6.42 (5.87–6.96)'],
        ['มะนิลา', '+4.7 pp', '0.52 (0.32–0.73)', '8.51 (8.10–8.92)'],
        ['กัวลาลัมเปอร์', '+3.3 pp', '0.79 (−0.34–1.92)', '8.07 (7.69–8.44)'],
        ['โฮจิมินห์', '+11.0 pp', '1.48 (1.06–1.91)', '4.17 (3.88–4.46)'],
    ],
    [18, 22, 30, 30],
    cap='ตารางที่ 10 — โฮจิมินห์ ISA โตเร็วสุด (+11 pp) · กรุงเทพฯ ISA สัมบูรณ์'
        'สูงสุด (65.1%) แต่ SUHI ต่ำ (4.01°C) เพราะแม่น้ำเจ้าพระยา+คลองช่วยระบาย'
        'ความร้อน · มะนิลา SUHI สูงสุด 8.51°C',
    hi={0}))
H.append(callout(
    '<b>ISA ↔ LST สัมพันธ์บวกชัดทุกเมือง</b> Pearson r = 0.748–0.900 (มีนัยสำคัญ) '
    '· <b>ข้อค้นพบเชิงพื้นที่:</b> แยกตามความ "ทึบ" ของพิกเซล — pervious (r=0.65) '
    'และ mixed (r=0.51) สัมพันธ์แรง แต่ <b>อิ่มตัว (saturate)</b> ที่พิกเซลทึบเต็ม '
    '(r=−0.14 ไม่ significant) → ความร้อนส่วนเพิ่มมากสุดอยู่ที่ <b>ขอบเมืองกำลัง'
    'ขยาย (pervious→mixed)</b> ไม่ใช่ใจกลางเมืองที่ทึบอยู่แล้ว', 'o'))

H.append('<div class="sub">6.6 ตรวจสอบข้ามชุดข้อมูลอิสระ — AlphaEarth vs JRC GHSL (ตารางที่ 11)</div>')
H.append(dtable(
    ['เมือง', 'Pearson r (95%CI)', 'ความสอดคล้องรวม (95%CI)', 'RMSE'],
    [
        ['จาการ์ตา', '0.936 (0.928–0.943)', '73.3% (70.4–76.0)', '0.429'],
        ['มะนิลา', '0.930 (0.921–0.938)', '84.5% (82.1–86.6)', '0.338'],
        ['กัวลาลัมเปอร์', '0.908 (0.897–0.918)', '72.3% (69.5–75.0)', '0.381'],
        ['กรุงเทพฯ', '0.907 (0.895–0.917)', '59.2% (56.1–62.2)', '0.472'],
        ['โฮจิมินห์', '0.866 (0.849–0.881)', '75.9% (73.1–78.4)', '0.376'],
    ],
    [20, 32, 34, 14],
    cap='ตารางที่ 11 — สอดคล้องเชิงพื้นที่สูง (r=0.87–0.94) · AlphaEarth ISA &gt; '
        'GHSL building เสมอ (bias +0.20 ถึง +0.39) เพราะ ISA รวมถนน/ลานจอด ไม่ใช่'
        'แค่อาคาร (กรุงเทพฯ bias สูงสุดจากโครงข่ายถนนกว้าง)',
    hi={3}))
H.append('<p><b>Cross-city transfer (LOCO):</b> train 4 เมือง → ทดสอบเมืองที่ 5 IoU '
         'ตกเฉลี่ยเพียง −3.4% (กรุงเทพฯ = 87.9%) → โมเดล generalize ข้ามเมืองได้ · '
         '<b>SUHI ลดลงทุกเมือง 2017–2024 แม้ ISA โต</b> — ไม่ใช่เมืองเย็นลง แต่ชนบท'
         'รอบเมืองร้อนขึ้นเร็วกว่า (rural baseline warming)</p>')

# 7. ข้อค้นพบสำคัญ
H.append(sec('7', 'ข้อค้นพบสำคัญ (Key Findings)'))
H.append(bullets([
    'AlphaEarth embeddings ให้ ISA ที่ <b>ทนเมฆ</b> — IoU 0.87–0.90 คงที่แม้เมฆ '
    '50–71% (ดีกว่า NDVI 44.9%, ลด misclassification 74.5%)',
    'พื้นผิวทึบน้ำ (ISA) สัมพันธ์บวกกับความร้อนผิว (LST) <b>อย่างชัดเจนทุกเมือง</b> '
    '(r=0.75–0.90) — ยืนยันว่า ISA เป็นตัวขับ UHI',
    '<b>ความร้อนส่วนเพิ่มสูงสุดที่ขอบเมืองกำลังขยาย</b> (pervious→mixed) และอิ่มตัว'
    'ในใจกลางเมือง → มาตรการลดความร้อน (เช่นปลูกต้นไม้) ควรเน้น peri-urban',
    'การเลือกวิธี classify ส่งผลต่อค่า ISA มหาศาล (มะนิลาต่างกันถึง 58 pp) → วิธีที่'
    'ไม่น่าเชื่อถือทำให้ตีความนโยบายผิดพลาด',
    'โมเดลถ่ายโอนข้ามเมืองได้ (LOCO −3.4%) → ใช้กับเมืองที่ไม่มีข้อมูล train ในพื้นที่'
    'ได้ เหมาะกับภูมิภาคข้อมูลจำกัด',
    '<b>ข้อจำกัด:</b> Dynamic World เป็น deep-learning label (ไม่ใช่ ground-truth) '
    'และแชร์สายพันธุ์ Sentinel-2 กับ AlphaEarth → ควรมี ground-truth อิสระ '
    '(ภาพถ่ายทางอากาศ/LiDAR) และ 10 m ยังหยาบเกินระดับแปลง/อาคาร',
]))

# 8. การนำมาใช้
H.append(sec('8', 'การนำมาใช้กับโปรเจกต์ Green Area Thailand (28P14N00163)'))
for head, body in [
    ('a) เพิ่มปัจจัย ISA เข้า recommend scoring (แบบ additive)',
     'เพิ่ม "สัดส่วนพื้นผิวทึบน้ำ" เป็นปัจจัยใหม่ใน priority score: ISA สูง + LST '
     'สูง + สีเขียวต่ำ = ควรปลูกต้นไม้สูง — เสริมโมเดลโดยไม่ลดมิติ/ความคม (scoring.py '
     'ใช้ LST anomaly เป็น heat island อยู่แล้ว)'),
    ('b) Logic เลือกจุดปลูกจาก insight peri-urban',
     'งานนี้พบว่าความร้อนส่วนเพิ่มแรงสุดที่ขอบเมืองกำลังขยาย (pervious→mixed) และ'
     'อิ่มตัวในใจกลางเมือง → ใส่ weighting ให้จุดปลูกที่ peri-urban fringe ได้ผลลด'
     'ความร้อนต่อหน่วยมากกว่า'),
    ('c) AlphaEarth เป็นทางเลือกเสริม Cloud Score+ (R12)',
     'สำหรับจังหวัดไทยเมฆหนา (ภาคใต้/ฤดูฝน) ที่ Cloud Score+ ยังได้พิกเซลน้อย '
     'พิจารณาใช้ embedding รายปีที่ gap-filling มาในตัวเป็น input สำรอง'),
    ('d) คำเตือนต่อการใช้ NDVI ของเรา',
     'NDVI threshold เดี่ยวๆ ประเมิน "พื้นที่สีเขียว" เกินจริงในเมืองเขตร้อน '
     '(ต้นไม้ในเมือง NDVI 0.3–0.5) — ควรใช้ร่วมกับดัชนี/บริบทอื่น ไม่พึ่ง threshold '
     'ค่าเดียว'),
    ('e) เมธอด/นิยาม + โค้ดที่อ้างอิงได้ทันที',
     'นิยาม SUHI (urban ISA≥50% / rural ≤10%, Imhoff 2010) ยืนยันกล่อง UHI · โค้ด '
     'GEE เปิดหมด (GitHub + Zenodo) ทำซ้ำ/ต่อยอดได้ · ตัวเลขกรุงเทพฯ (ISA 65%, '
     'SUHI 4°C) ใช้เป็น benchmark ตรวจความสมเหตุสมผลของระบบ'),
]:
    H.append(f'<div class="sub">{head}</div><p>{body}</p>')

# 9. references
H.append(sec('9', 'สรุปเอกสารอ้างอิงในงาน (38 รายการ — กลุ่มสำคัญ)'))
for head, body in [
    ('★ เกี่ยวกับเราโดยตรง / กรุงเทพฯ',
     '[4] Puttanapong, …, <b>Moukomla</b> (2025) 36-Year SUHI กรุงเทพฯ '
     '(Geogr. Sustain.) · [26] Arifwidodo &amp; Tanaka (2015) UHI กรุงเทพฯ · '
     '[27] Iamtrakul et al. (2024) urban growth→SUHI กรุงเทพฯ (Atmosphere) · '
     '[6] Kuang et al. (2021) map impervious + green space ทั่วโลกด้วย GEE'),
    ('AlphaEarth / Foundation models',
     '[25] Brown et al. (2025, arXiv:2507.22291) <b>AlphaEarth Foundations</b> '
     '(ต้นตำรับ) · [1] Cai et al. (2025) cropland SE Asia · [21] tea plantation · '
     '[22] biomass+GEDI · [24] air quality Quito · [23] Foundations of Earth '
     'Foundation Models'),
    ('ข้อมูล/แพลตฟอร์มที่เราใช้ร่วมกัน',
     '[32] Gorelick et al. (2017) Google Earth Engine (= R28 ของเรา) · '
     '[33] Brown et al. (2022) Dynamic World · [37] Pesaresi et al. (2024) JRC '
     'GHSL · [38] Imhoff et al. (2010) นิยาม SUHI · [35] Olofsson et al. (2014) '
     'good-practice accuracy · [34] Breiman (2001) Random Forest'),
    ('ISA mapping / เมฆในเขตร้อน (บริบทปัญหา)',
     '[10] GISD30 · [19] GAIA · [8] cloud-free LST reconstruction (MODIS) · '
     '[12] Lasko tropical ISA · [11] S2 impervious comparison · [18] Shi et al. '
     '(2023) SUHI จาก ISA · [20] Xu (2010) NDISI'),
]:
    H.append(f'<div class="subb">{head}</div><p>{body}</p>')

H.append('<p class="muted">จัดทำสรุปจากไฟล์ต้นฉบับ earth-07-00076-v2 (25 หน้า) · '
         'สถานะในระบบ: งานที่เกี่ยวข้อง [RW1] — ยังไม่ได้นำมาใช้ (related work) · '
         'อ้างอิงเต็ม: Moukomla, S., Meeprom, P., &amp; Intarat, K. (2026). Earth, '
         '7(3), 76. https://doi.org/10.3390/earth7030076</p>')

HTML = '<html><body>' + ''.join(H) + '</body></html>'


# ── flow เป็นหลายหน้า (เขียนผ่าน memory buffer ไม่แตะไฟล์ tmp บนดิสก์) ───────
buf = io.BytesIO()
writer = fitz.DocumentWriter(buf)
story = fitz.Story(html=HTML, archive=arch, user_css=CSS)
mediabox = fitz.Rect(0, 0, PW, PH)
where = fitz.Rect(ML, MT, PW - MR, PH - MB)
more = 1
while more:
    dev = writer.begin_page(mediabox)
    more, _ = story.place(where)
    story.draw(dev)
    writer.end_page()
writer.close()

# ── หัว/ท้ายกระดาษ (ใช้ insert_htmlbox เพื่อ shape ไทยถูกต้อง) ───────────────
doc = fitz.open(stream=buf.getvalue(), filetype='pdf')
n = doc.page_count
hf_css = ('@font-face{font-family:sb;src:url(sb.ttf);} '
          '*{font-family:sb;font-size:8.3px;color:#5f6368;}'
          '.r{text-align:right;}')
for i, page in enumerate(doc):
    page.insert_htmlbox(
        fitz.Rect(ML, 22, PW - MR, 34),
        '<table style="width:100%"><tr>'
        '<td>สรุปงานวิจัย · Earth 7(3):76 (2026) · ISA × SUHI · AlphaEarth</td>'
        '<td class="r">โครงการ 28P14N00163 · NSC 2026</td></tr></table>',
        css=hf_css, archive=arch)
    page.insert_htmlbox(
        fitz.Rect(ML, PH - 30, PW - MR, PH - 18),
        '<table style="width:100%"><tr>'
        '<td>Moukomla, Meeprom &amp; Intarat (2026) · doi:10.3390/earth7030076</td>'
        f'<td class="r">หน้า {i + 1} / {n}</td></tr></table>',
        css=hf_css, archive=arch)
    page.draw_line(fitz.Point(ML, 37), fitz.Point(PW - MR, 37),
                   color=(0.855, 0.859, 0.863), width=0.4)
    page.draw_line(fitz.Point(ML, PH - 33), fitz.Point(PW - MR, PH - 33),
                   color=(0.855, 0.859, 0.863), width=0.4)

out_path = os.path.join(ROOT, 'Earth_Paper_Summary_ISA_SUHI.pdf')
doc.set_metadata({
    'title': 'สรุปงานวิจัย Earth 7(3):76 — ISA × SUHI (AlphaEarth)',
    'author': 'โครงการ 28P14N00163 · NSC 2026',
    'subject': 'Summary of Moukomla et al. 2026 (Earth 7:76)'})
doc.save(out_path, garbage=4, deflate=True)
doc.close()
print('WROTE', out_path, '·', n, 'pages')
