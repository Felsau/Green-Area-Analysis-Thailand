"""สร้าง PDF รายงานการตรวจสอบความเกี่ยวข้องของบรรณานุกรมกับระบบ
(Bibliography Relevance Audit) — โครงการ NSC 28P14N00163

ไล่ตรวจอ้างอิงทั้ง 31 รายการเทียบกับโค้ดจริง + REQUIREMENTS.md แล้วจัดสถานะ:
  ใช้แล้ว (กลุ่ม A) · ใช้บางส่วน · แผนต่อยอด (กลุ่ม B)
"""
import os
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor, white
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
)

ROOT = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(ROOT)
FONT_DIR = os.path.join(REPO_ROOT, 'green-area-frontend', 'public', 'fonts')

pdfmetrics.registerFont(TTFont('Sarabun', os.path.join(FONT_DIR, 'Sarabun-Regular.ttf')))
pdfmetrics.registerFont(TTFont('Sarabun-Bold', os.path.join(FONT_DIR, 'Sarabun-Bold.ttf')))

# ── Colors ──────────────────────────────────────────────────────────────────
COL = {
    'primary':    HexColor('#1a73e8'),
    'green':      HexColor('#1e8e3e'),
    'green_deep': HexColor('#0e5c24'),
    'orange':     HexColor('#f97316'),
    'purple':     HexColor('#7c3aed'),
    'text':       HexColor('#202124'),
    'muted':      HexColor('#5f6368'),
    'border':     HexColor('#dadce0'),
    'light_blue': HexColor('#e8f0fe'),
    'light_green':HexColor('#e6f4ea'),
    'light_orange':HexColor('#fff2e6'),
    'light_purple':HexColor('#f3edfd'),
}

# สถานะ → (สี, ป้าย)
STATUS = {
    'used':    (COL['green'],  'ใช้แล้ว'),
    'partial': (COL['orange'], 'ใช้บางส่วน'),
    'roadmap': (COL['purple'], 'แผนต่อยอด'),
}

# ── Styles ──────────────────────────────────────────────────────────────────
def style(name, font='Sarabun', size=11, color=None, leading=None,
          space_after=4, space_before=0, align=TA_LEFT):
    return ParagraphStyle(
        name=name, fontName=font, fontSize=size,
        textColor=color or COL['text'],
        leading=leading or size * 1.5,
        spaceAfter=space_after, spaceBefore=space_before, alignment=align,
    )

S = {
    'h2':      style('h2', font='Sarabun-Bold', size=15, color=COL['primary'],
                     space_before=8, space_after=6, leading=20),
    'h3':      style('h3', font='Sarabun-Bold', size=12, color=COL['green_deep'],
                     space_before=6, space_after=4, leading=16),
    'p':       style('p', size=10.5, leading=16, space_after=4, align=TA_JUSTIFY),
    'p_ni':    style('p_ni', size=10.5, leading=16, space_after=4),
    'p_center':style('p_c', size=10, leading=14, space_after=2, align=TA_CENTER),
    'muted':   style('muted', size=9, color=COL['muted'], leading=13),
    'callout': style('callout', font='Sarabun-Bold', size=10.5,
                     color=COL['primary'], leading=15),
    'cell':    style('cell', size=8.3, leading=11),
    'cell_b':  style('cell_b', font='Sarabun-Bold', size=8.3, leading=11),
    'cell_h':  style('cell_h', font='Sarabun-Bold', size=8.6, color=white, leading=11),
    'box_num': style('box_num', font='Sarabun-Bold', size=22, align=TA_CENTER,
                     leading=24),
    'box_lbl': style('box_lbl', font='Sarabun-Bold', size=9.5, align=TA_CENTER,
                     leading=12),
}


def header_bar(title):
    p = Paragraph(f'<font color="white" face="Sarabun-Bold" size="16">{title}</font>',
                  S['p_ni'])
    t = Table([[p]], colWidths=[170 * mm])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), COL['primary']),
        ('LEFTPADDING', (0, 0), (-1, -1), 12),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    return t


def callout_box(text, color, bg):
    p = Paragraph(text, S['callout'])
    t = Table([[p]], colWidths=[170 * mm])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), bg),
        ('LINEBEFORE', (0, 0), (0, -1), 3, color),
        ('LEFTPADDING', (0, 0), (-1, -1), 12),
        ('RIGHTPADDING', (0, 0), (-1, -1), 12),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
    ]))
    return t


def stat_box(number, label, color, bg):
    num = Paragraph(str(number), ParagraphStyle(
        'n', fontName='Sarabun-Bold', fontSize=22, alignment=TA_CENTER,
        textColor=color, leading=24))
    lbl = Paragraph(label, ParagraphStyle(
        'l', fontName='Sarabun-Bold', fontSize=9.5, alignment=TA_CENTER,
        textColor=color, leading=12))
    t = Table([[num], [lbl]], colWidths=[54 * mm])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), bg),
        ('LINEABOVE', (0, 0), (-1, 0), 2.5, color),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    return t


def audit_table(rows):
    """rows = list ของ (rnum, citation, status, where)"""
    head = [
        Paragraph('R#', S['cell_h']),
        Paragraph('อ้างอิง (ผู้แต่ง · ปี · หัวข้อย่อ)', S['cell_h']),
        Paragraph('สถานะ', S['cell_h']),
        Paragraph('จุดที่ใช้ในระบบ', S['cell_h']),
    ]
    data = [head]
    for rnum, citation, status, where in rows:
        color, label = STATUS[status]
        data.append([
            Paragraph(rnum, S['cell_b']),
            Paragraph(citation, S['cell']),
            Paragraph(label, ParagraphStyle(
                'st', fontName='Sarabun-Bold', fontSize=8.3,
                textColor=color, leading=11)),
            Paragraph(where, S['cell']),
        ])

    t = Table(data, colWidths=[15 * mm, 80 * mm, 23 * mm, 52 * mm], repeatRows=1)
    ts = [
        ('BACKGROUND', (0, 0), (-1, 0), COL['primary']),
        ('GRID', (0, 0), (-1, -1), 0.4, COL['border']),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 5),
        ('RIGHTPADDING', (0, 0), (-1, -1), 5),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [white, HexColor('#f8f9fa')]),
    ]
    t.setStyle(TableStyle(ts))
    return t


# ── Page header/footer ───────────────────────────────────────────────────────
def on_page(canvas, doc):
    canvas.saveState()
    canvas.setFont('Sarabun', 8.5)
    canvas.setFillColor(COL['muted'])
    canvas.drawString(20 * mm, 287 * mm,
                      'Bibliography Relevance Audit · โครงการ 28P14N00163 · NSC 2026')
    canvas.drawRightString(190 * mm, 287 * mm, 'มหาวิทยาลัยพะเยา')
    canvas.setStrokeColor(COL['border'])
    canvas.setLineWidth(0.4)
    canvas.line(20 * mm, 284 * mm, 190 * mm, 284 * mm)
    canvas.drawString(20 * mm, 12 * mm,
                      'ตรวจสอบความเกี่ยวข้องของบรรณานุกรมกับระบบวิเคราะห์พื้นที่สีเขียวฯ')
    canvas.drawRightString(190 * mm, 12 * mm, f'หน้า {doc.page}')
    canvas.line(20 * mm, 15 * mm, 190 * mm, 15 * mm)
    canvas.restoreState()


# ── Reference data (31 รายการ) ───────────────────────────────────────────────
academic_rows = [
    ('R10', 'Bowler et al. (2010) — urban greening ลดความร้อนเมือง (meta-analysis)', 'used', 'impact.py — ΔLST −1.5°C'),
    ('R25', 'Chave et al. (2014) — pan-tropical allometric biomass model', 'used', 'impact.py — kg CO₂/ต้น'),
    ('R22', 'Dong et al. (2025) — remote sensing ของ urban tree carbon stocks', 'used', 'สนับสนุนวิธี CO₂ (FR-09)'),
    ('R27', 'Drusch et al. (2012) — ภารกิจดาวเทียม Sentinel-2', 'used', 'gee_utils.py, ndvi/compute.py'),
    ('R21', 'Fulton et al. (2025) — เปรียบเทียบเครื่องมือ equity mapping', 'roadmap', 'FR-21/22 (ยังไม่พัฒนา)'),
    ('R28', 'Gorelick et al. (2017) — Google Earth Engine', 'used', 'compute backend ทั้งระบบ'),
    ('R2',  'Konijnendijk (2023) — กฎ 3-30-300', 'roadmap', 'FR-17/18 (ยังไม่พัฒนา)'),
    ('R24', 'Lee et al. (2024) — validate NDVI จาก Sentinel-2', 'used', 'ยืนยันสูตร NDVI (B8/B4)'),
    ('R14', 'Malakar et al. (2018) — Landsat LST product (single-channel)', 'used', 'gee_utils.py — ST_B10'),
    ('R17', 'Mann (1945) / Kendall (1975) — Mann-Kendall trend test', 'used', 'stats_utils.py'),
    ('R16', 'Mehmood et al. (2024) — NDVI + Mann-Kendall trend', 'used', 'stats_utils.py'),
    ('R4',  'Nyelele et al. (2022) — เปรียบเทียบ framework จัดลำดับปลูกต้นไม้', 'used', 'scoring.py + plantable_mask'),
    ('R12', 'Pasquarella et al. (2023) — Cloud Score+', 'used', 'gee_utils.py — mask เมฆ'),
    ('R23', 'Rouse et al. (1973/74) — สูตร NDVI ต้นตำรับ', 'used', 'ndvi/compute.py'),
    ('R29', 'Tatem (2017) — WorldPop ข้อมูลประชากร', 'used', 'scoring.py — pop_need'),
    ('R3',  'Multi-objective DSS (2021) — จัดลำดับพื้นที่ปลูก', 'used', 'scoring.py — Priority Score'),
    ('R5',  'Right Tree, Right Place (2026) — เลือกพันธุ์/ตำแหน่งปลูก', 'used', 'species.py'),
    ('R7',  'i-Tree Eco / Forests (2024) — บริการนิเวศเต็มรูป', 'roadmap', 'FR-23/24/25 (ยังไม่พัฒนา)'),
    ('R8',  'Network-based accessibility 6 เมือง (2025)', 'partial', 'scoring.py — access_need (แบบง่าย)'),
    ('R9',  'GIS-based accessibility ระดับชั้น (2016)', 'partial', 'scoring.py — access_need (แบบง่าย)'),
    ('R18', 'G2SFCA พื้นที่สีเขียว Seoul (2026)', 'roadmap', 'FR-20 (2SFCA เต็ม, ยังไม่ทำ)'),
    ('R15', 'Suitability ของ satellite LST products (2024)', 'used', 'สนับสนุนวิธี LST/UHI'),
    ('R19', 'Cooling effect of green spaces review (2025)', 'used', 'สนับสนุน cooling (FR-09)'),
]

technical_rows = [
    ('R6, R20', 'American Forests — Tree Equity Score (nationwide + methodology)', 'roadmap', 'FR-21/22 (ยังไม่พัฒนา)'),
    ('R12', 'Google — Cloud Score+ dataset documentation', 'used', 'gee_utils.py — mask เมฆ'),
    ('R30', 'Hijmans et al. (2021) — GADM v4.1 ขอบเขตการปกครอง', 'used', 'generate_districts.py'),
    ('R11', 'IPCC (2019) — carbon sequestration guidelines', 'used', 'impact.py — CO₂ coefficient'),
    ('R26', 'U.S. EPA (2023) — passenger vehicle CO₂ baseline', 'used', 'impact.py — equivalent_cars'),
    ('R31', 'USGS (2022) — Landsat C2 L2 product guide', 'used', 'gee_utils.py — ST_B10'),
    ('R1',  'WHO (2017) — พื้นที่สีเขียว ~9 ม²/คน', 'used', 'ranking m²/คน'),
    ('R13', 'Zanaga et al. (2022) — ESA WorldCover 10 m v200', 'used', 'urban.py, plantable_mask, access'),
]


# ── Build story ──────────────────────────────────────────────────────────────
story = []

story.append(header_bar('รายงานการตรวจสอบความเกี่ยวข้องของบรรณานุกรมกับระบบ'))
story.append(Spacer(1, 3))
story.append(Paragraph(
    'Bibliography Relevance Audit — ระบบวิเคราะห์พื้นที่สีเขียวและแนะนำพื้นที่ปลูกต้นไม้'
    'อัจฉริยะของประเทศไทย · โครงการ NSC 28P14N00163 · ตรวจ ณ วันที่ 6 กรกฎาคม 2569',
    S['muted']))
story.append(Spacer(1, 8))

# ── บทสรุป ──
story.append(callout_box(
    'ผลการตรวจ: บรรณานุกรมทั้ง 31 รายการ "เกี่ยวข้องกับระบบทั้งหมด" ไม่มีรายการใด'
    'หลุดออกนอกขอบเขตงาน และทุกรายการมี traceability ไปยัง requirement ที่ชัดเจน '
    'ความเกี่ยวข้องแบ่งเป็น 3 ระดับตามการนำไปใช้จริงในโค้ดที่พัฒนาแล้ว',
    COL['green'], COL['light_green']))
story.append(Spacer(1, 8))

# ── กล่องสรุปจำนวน ──
boxes = Table([[
    stat_box(24, 'ใช้แล้ว (กลุ่ม A)', COL['green'], COL['light_green']),
    stat_box(2, 'ใช้บางส่วน', COL['orange'], COL['light_orange']),
    stat_box(5, 'แผนต่อยอด (กลุ่ม B)', COL['purple'], COL['light_purple']),
]], colWidths=[56 * mm, 56 * mm, 56 * mm])
boxes.setStyle(TableStyle([
    ('LEFTPADDING', (0, 0), (-1, -1), 2),
    ('RIGHTPADDING', (0, 0), (-1, -1), 2),
    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
]))
story.append(boxes)
story.append(Spacer(1, 6))

story.append(Paragraph(
    '<font face="Sarabun-Bold" color="#1e8e3e">ใช้แล้ว</font> = มีในโค้ดที่รันได้จริง '
    '(กลุ่ม A) · '
    '<font face="Sarabun-Bold" color="#f97316">ใช้บางส่วน</font> = แนวคิดถูกนำมาใช้'
    'บางส่วน ส่วนเต็มเป็นแผนต่อยอด · '
    '<font face="Sarabun-Bold" color="#7c3aed">แผนต่อยอด</font> = งานวิจัยรองรับ'
    'ข้อเสนอกลุ่ม B ที่ยังไม่พัฒนา',
    S['muted']))
story.append(Spacer(1, 10))

# ── ตารางวิชาการ ──
story.append(Paragraph('1. แหล่งอ้างอิงทางวิชาการ (Academic Sources) — 23 รายการ',
                       S['h3']))
story.append(Spacer(1, 4))
story.append(audit_table(academic_rows))
story.append(Spacer(1, 10))

# ── ตารางเทคนิค ──
story.append(Paragraph('2. แหล่งอ้างอิงมาตรฐาน/เทคนิค (Standards & Technical) — 8 รายการ',
                       S['h3']))
story.append(Spacer(1, 4))
story.append(audit_table(technical_rows))
story.append(Spacer(1, 12))

# ── ข้อสังเกต ──
story.append(Paragraph('3. ข้อสังเกตและหมายเหตุ', S['h3']))
story.append(Spacer(1, 2))
notes = [
    'อ้างอิงกลุ่ม <b>แผนต่อยอด</b> (R2, R6, R7, R18, R20, R21) ผูกกับฟีเจอร์กลุ่ม B '
    'ใน REQUIREMENTS.md ที่ยัง<b>ไม่ได้พัฒนา</b> เช่น กฎ 3-30-300, Tree Equity Score, '
    'i-Tree (PM2.5/stormwater/มูลค่าเงิน) และ 2SFCA เต็มรูป — หากถูกถามในการนำเสนอ '
    'ให้ตอบตรงว่าเป็น "งานวิจัยรองรับแผนต่อยอด" ไม่ใช่ฟีเจอร์ที่มีแล้ว',

    'อ้างอิง <b>ใช้บางส่วน</b> (R8, R9) — ระบบมีปัจจัย accessibility ใน Priority Score '
    'จริง (access_need, น้ำหนัก 15%) แต่ใช้ระยะ distance-transform แบบง่าย '
    'ยังไม่ถึง network distance / 2SFCA เต็มตามงานวิจัยต้นทาง',

    'การจับคู่รหัสที่ตั้งใจไว้: American Forests ใช้ <b>[R6, R20]</b> รวมกัน '
    '(nationwide + methodology เป็นแหล่งเดียว) และ Cloud Score+ dataset ใช้ '
    '<b>[R12]</b> ร่วมกับเปเปอร์ Pasquarella — สอดคล้องกับ REQUIREMENTS.md',

    'R27–R31 (Sentinel-2, GEE, WorldPop, GADM, Landsat guide) เป็นแหล่งข้อมูล/'
    'แพลตฟอร์มหลักที่ระบบใช้จริงทั้งหมด เพิ่งได้รับรหัส R# เพื่อให้ตรงกับบรรณานุกรม'
    'ในเล่มข้อเสนอครบ 31 รายการ',
]
for n in notes:
    story.append(Paragraph(f'<font color="#1a73e8">▸</font> {n}', S['p']))

story.append(Spacer(1, 8))
story.append(Paragraph(
    'อ้างอิงรายการเต็ม + traceability ไปยัง requirement และไฟล์โค้ด: REQUIREMENTS.md '
    '§6–7 · บรรณานุกรมพร้อมป้ายสถานะในเล่มข้อเสนอ: '
    'presentation/Proposal_28P14N00163_GreenAreaThailand.pdf ข้อ 8',
    S['muted']))


# ── Build PDF ────────────────────────────────────────────────────────────────
out_path = os.path.join(ROOT, 'Bibliography_Relevance_Audit.pdf')
doc = SimpleDocTemplate(
    out_path, pagesize=A4,
    leftMargin=20 * mm, rightMargin=20 * mm,
    topMargin=22 * mm, bottomMargin=20 * mm,
    title='รายงานตรวจสอบความเกี่ยวข้องของบรรณานุกรม — 28P14N00163',
    author='อติชาติ ผาแสนเถิน',
    subject='Bibliography Relevance Audit — NSC 2026',
)
doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
print(f'[OK] Generated: {out_path}')
print(f'     Size: {os.path.getsize(out_path):,} bytes')
