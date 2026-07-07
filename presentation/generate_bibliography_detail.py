"""สร้าง PDF ฉบับละเอียด — "เอาอะไรมาใช้ จากงานวิจัยส่วนไหน ไปใช้ตรงไหนในระบบ"
(Bibliography Extraction Detail) — โครงการ NSC 28P14N00163

ต่างจาก Bibliography_Relevance_Audit ตรงที่ลงรายละเอียดว่าดึง "ค่า/สูตร/ข้อมูล"
อะไรจากแต่ละงานวิจัย มาตั้งเป็นค่าคงที่/สูตรตรงจุดใดในโค้ด จัดกลุ่มตามโมดูลระบบ
ค่าทุกตัวสอบทานจากไฟล์จริง: impact.py · scoring.py · gee_utils.py · stats_utils.py
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
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether,
)

ROOT = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(ROOT)
FONT_DIR = os.path.join(REPO_ROOT, 'green-area-frontend', 'public', 'fonts')

pdfmetrics.registerFont(TTFont('Sarabun', os.path.join(FONT_DIR, 'Sarabun-Regular.ttf')))
pdfmetrics.registerFont(TTFont('Sarabun-Bold', os.path.join(FONT_DIR, 'Sarabun-Bold.ttf')))

COL = {
    'primary':    HexColor('#1a73e8'),
    'green':      HexColor('#1e8e3e'),
    'green_deep': HexColor('#0e5c24'),
    'orange':     HexColor('#f97316'),
    'purple':     HexColor('#7c3aed'),
    'text':       HexColor('#202124'),
    'muted':      HexColor('#5f6368'),
    'border':     HexColor('#dadce0'),
    'code_bg':    HexColor('#f1f3f4'),
    'light_green':HexColor('#e6f4ea'),
}

STATUS = {
    'used':    (COL['green'],  'ใช้แล้ว'),
    'partial': (COL['orange'], 'ใช้บางส่วน'),
    'roadmap': (COL['purple'], 'แผนต่อยอด'),
}


def pstyle(name, font='Sarabun', size=11, color=None, leading=None,
           space_after=4, align=TA_LEFT):
    return ParagraphStyle(name=name, fontName=font, fontSize=size,
                          textColor=color or COL['text'],
                          leading=leading or size * 1.5,
                          spaceAfter=space_after, alignment=align)

S = {
    'h3':    pstyle('h3', font='Sarabun-Bold', size=12.5, color=COL['green_deep'],
                    leading=17, space_after=3),
    'p':     pstyle('p', size=10.5, leading=16, align=TA_JUSTIFY),
    'p_ni':  pstyle('p_ni', size=10.5, leading=16),
    'muted': pstyle('muted', size=9, color=COL['muted'], leading=12.5),
    'cell':  pstyle('cell', size=8.2, leading=11),
    'cell_h':pstyle('cell_h', font='Sarabun-Bold', size=8.5, color=white, leading=11),
    'callout':pstyle('callout', font='Sarabun-Bold', size=10.5, color=COL['primary'],
                     leading=15),
}


def mono(t):
    """ข้อความสไตล์โค้ด — Courier เทา"""
    return f'<font face="Courier" size="7.8" color="#0e5c24">{t}</font>'


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


def detail_table(rows):
    """rows = list ของ (rnum, ref, status, extracted, where)
    R# ระบายสีตามสถานะ · คอลัมน์กลางคือ 'เอาอะไรมาใช้ จากงานวิจัยส่วนไหน'"""
    head = [
        Paragraph('R#', S['cell_h']),
        Paragraph('อ้างอิง', S['cell_h']),
        Paragraph('เอาอะไรมาใช้ · จากงานวิจัยส่วนไหน', S['cell_h']),
        Paragraph('ใช้ตรงไหนในระบบ · ค่าที่ตั้ง', S['cell_h']),
    ]
    data = [head]
    for rnum, ref, status, extracted, where in rows:
        color, _ = STATUS[status]
        data.append([
            Paragraph(rnum, ParagraphStyle('rn', fontName='Sarabun-Bold',
                                           fontSize=8.2, textColor=color, leading=11)),
            Paragraph(ref, S['cell']),
            Paragraph(extracted, S['cell']),
            Paragraph(where, S['cell']),
        ])
    t = Table(data, colWidths=[13 * mm, 35 * mm, 78 * mm, 44 * mm], repeatRows=1)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), COL['primary']),
        ('GRID', (0, 0), (-1, -1), 0.4, COL['border']),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 5),
        ('RIGHTPADDING', (0, 0), (-1, -1), 5),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [white, HexColor('#f8f9fa')]),
    ]))
    return t


def module_section(title, rows):
    """หัวข้อโมดูล + ตาราง — พยายามไม่ให้หัวข้อหลุดจากตาราง"""
    return [Paragraph(title, S['h3']), Spacer(1, 3), detail_table(rows), Spacer(1, 9)]


def on_page(canvas, doc):
    canvas.saveState()
    canvas.setFont('Sarabun', 8.5)
    canvas.setFillColor(COL['muted'])
    canvas.drawString(20 * mm, 287 * mm,
                      'Bibliography Extraction Detail · โครงการ 28P14N00163 · NSC 2026')
    canvas.drawRightString(190 * mm, 287 * mm, 'มหาวิทยาลัยพะเยา')
    canvas.setStrokeColor(COL['border'])
    canvas.setLineWidth(0.4)
    canvas.line(20 * mm, 284 * mm, 190 * mm, 284 * mm)
    canvas.drawString(20 * mm, 12 * mm,
                      'เอาอะไรจากงานวิจัยมาใช้ตรงไหนในระบบ — รายละเอียดเชิงลึก')
    canvas.drawRightString(190 * mm, 12 * mm, f'หน้า {doc.page}')
    canvas.line(20 * mm, 15 * mm, 190 * mm, 15 * mm)
    canvas.restoreState()


# ── ข้อมูล: (rnum, ref, status, extracted, where) ────────────────────────────
MODULES = [
 ('A. ข้อมูลพืชพรรณ (NDVI) — Sentinel-2', [
   ('R23', 'Rouse et al. (1973/74)', 'used',
    'สูตร NDVI = (NIR−Red)/(NIR+Red) ต้นตำรับ จากงานติดตามพืชพรรณด้วยดาวเทียม ERTS',
    'ndvi/compute.py — ' + mono("normalizedDifference(['B8','B4'])")),
   ('R27', 'Drusch et al. (2012) — Sentinel-2', 'used',
    'คุณสมบัติภารกิจ Sentinel-2: band B8 = NIR, B4 = Red, ความละเอียด 10 เมตร',
    'ใช้ภาพ ' + mono('COPERNICUS/S2_SR_HARMONIZED')),
   ('R24', 'Lee et al. (2024)', 'used',
    'ผล validate ค่า NDVI จาก Sentinel-2 (B8/B4) เทียบเซนเซอร์ภาคพื้นดิน 8 จุด — ยืนยันความแม่นของแบนด์/สูตร',
    'สนับสนุนเกณฑ์ NDVI มากกว่า 0.3 = พื้นที่สีเขียว'),
 ]),
 ('B. อุณหภูมิผิวพื้น (LST) — Landsat 8/9', [
   ('R14', 'Malakar et al. (2018)', 'used',
    'อัลกอริทึม single-channel ที่ USGS ใช้ผลิต band ST_B10 (Landsat Collection 2 Level-2) พร้อมการ validate',
    'gee_utils.py — ' + mono('get_lst_col') + ' ดึง ST_B10'),
   ('R31', 'USGS (2022) Product Guide', 'used',
    'ค่าคงที่แปลง digital number → เคลวิน ของ ST_B10: scale 0.00341802, offset 149.0 K',
    'scale_lst(): คูณ 0.00341802 บวก 149.0 ลบ 273.15 = °C'),
   ('R15', '(2024) Suitability of LST products', 'used',
    'ยืนยันว่า Landsat C2 Surface Temperature เหมาะกับงาน Surface UHI (กรณี Madrid/Paris)',
    'สนับสนุนการเลือกใช้ ST_B10 กับการวิเคราะห์เกาะความร้อน'),
 ]),
 ('C. การกรองเมฆ (Cloud Masking)', [
   ('R12', 'Pasquarella et al. (2023) — Cloud Score+', 'used',
    'band cs (คะแนนความใส 0–1) จาก weakly-supervised video learning; Google แนะนำ threshold 0.5–0.65',
    'gee_utils.py — ' + mono('GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED') + ', cs ตั้งแต่ 0.6 = ใส'),
 ]),
 ('D. คะแนนความสำคัญพื้นที่ปลูก (AI Priority Score)', [
   ('R3', 'Multi-objective DSS (2021)', 'used',
    'แนวคิดถ่วงน้ำหนักหลายปัจจัย (multi-objective) เพื่อจัดลำดับพื้นที่ปลูกต้นไม้',
    'scoring.py — priority = 0.35·NDVIdeficit + 0.25·LSTheat + 0.25·popNeed + 0.15·accessNeed'),
   ('R4', 'Nyelele et al. (2022)', 'used',
    'เปรียบเทียบ framework จัดลำดับ ชี้ว่า "ความเป็นไปได้ในการปลูกจริง (feasibility)" เป็นองค์ประกอบสำคัญ',
    'plantable_mask ตัดน้ำ/อาคาร/ป่าเดิม/ลาดชันเกิน 30°'),
   ('R29', 'Tatem (2017) — WorldPop', 'used',
    'ชุดข้อมูลประชากรเชิงพื้นที่ ความละเอียด 100 เมตร',
    'scoring.py — ' + mono('WorldPop/GP/100m/pop') + ', popNeed = ln(pop+1)/ln(1000)'),
   ('R13', 'Zanaga et al. (2022) — ESA WorldCover', 'used',
    'ระบบชั้น land cover 10 เมตร (10 = ต้นไม้, 50 = สิ่งปลูกสร้าง ฯลฯ)',
    'ใช้ 3 จุด: plantable_mask · access_need (class 10) · urban subset'),
   ('R8', 'Network-based accessibility (2025)', 'partial',
    'แนวคิดวัด "การเข้าถึงพื้นที่สีเขียว" ด้วยระยะทางถึงสวน/ต้นไม้',
    'access_need = ระยะถึงต้นไม้ใกล้สุด (distance-transform แบบง่าย, cap 1000 ม.)'),
   ('R9', 'GIS-based accessibility (2016)', 'partial',
    'แนวทาง network analysis + การเข้าถึงแบบระดับชั้น (hierarchical)',
    'เสริมแนวคิด access_need — ยังไม่ถึง network distance เต็มรูป'),
 ]),
 ('E. การวิเคราะห์แนวโน้ม (Trend Analysis)', [
   ('R17', 'Mann (1945) / Kendall (1975)', 'used',
    'Mann-Kendall trend test: สถิติ S, tau, ค่า z, p-value (nonparametric monotonic)',
    'stats_utils.py — ' + mono('mann_kendall(alpha=0.05)') + ' + tie correction'),
   ('R16', 'Mehmood et al. (2024)', 'used',
    'precedent การใช้ Mann-Kendall กับอนุกรม NDVI รายปี ระดับจังหวัด',
    'timeseries — ตัดสินแนวโน้ม increasing/decreasing/no trend'),
 ]),
 ('F. ประมาณการผลกระทบ (CO₂ Sequestration + Cooling)', [
   ('R11', 'IPCC (2019) Vol.4 Ch.4', 'used',
    'biomass increment ป่าทุติยภูมิเขตร้อน ~3.6 t C/ha/ปี → คิดเป็น ~22 กก. CO₂/ต้น/ปี ที่ 400 ต้น/ha',
    'impact.py — ' + mono('default_kg_co2=22.0') + ', ' + mono('trees_per_ha=400')),
   ('R25', 'Chave et al. (2014)', 'used',
    'pan-tropical allometric model (มวลชีวภาพจากเส้นผ่านศูนย์กลาง/ความสูง/ความหนาแน่นเนื้อไม้)',
    'impact.py — ฐานคำนวณ per-species kg CO₂ (' + mono('TREE_CO2_PER_YEAR') + ' 12–32 กก.)'),
   ('R10', 'Bowler et al. (2010)', 'used',
    'meta-analysis: พื้นที่สีเขียวทำให้เย็นลงเฉลี่ย ~1°C สูงสุด ~3°C ในเรือนยอดหนาแน่น',
    'impact.py — ' + mono('delta_lst_c = −1.5') + ' °C ที่ canopy โตเต็มที่'),
   ('R26', 'U.S. EPA (2023)', 'used',
    'รถยนต์นั่งเฉลี่ยปล่อย ~4.6 ตัน CO₂/คัน/ปี',
    'impact.py — ' + mono('car_co2_t_per_year=4.6') + ' → equivalent_cars'),
   ('R22', 'Dong et al. (2025)', 'used',
    'ทบทวนวิธี remote-sensing ประเมิน carbon stock ของต้นไม้ในเมือง',
    'สนับสนุนความน่าเชื่อถือของการประมาณ CO₂ (เสริม IPCC)'),
   ('R19', '(2025) Cooling effect review', 'used',
    'สังเคราะห์ 84 งานวิจัย (2014–2024) รายงานช่วง cooling 1–7°C',
    'อัปเดตหลักฐานเชิงปริมาณของค่า cooling (เสริม Bowler)'),
 ]),
 ('G. มาตรฐาน แพลตฟอร์ม และขอบเขต', [
   ('R1', 'WHO (2017)', 'used',
    'เกณฑ์พื้นที่สีเขียวเข้าถึงได้ อย่างน้อย 9 ตารางเมตรต่อคน',
    'ranking m²/คน + urban subset เทียบเกณฑ์'),
   ('R28', 'Gorelick et al. (2017) — GEE', 'used',
    'แพลตฟอร์มประมวลผลภูมิสารสนเทศระดับ planetary-scale',
    'compute backend ของทุก endpoint (NDVI/LST/priority)'),
   ('R30', 'Hijmans et al. (2021) — GADM v4.1', 'used',
    'ขอบเขตการปกครองระดับจังหวัด/อำเภอของโลก',
    '77 จังหวัด / 928 อำเภอ, ใช้ clip ทุกการคำนวณ (generate_districts.py)'),
   ('R5', 'Right Tree, Right Place (2026)', 'used',
    'systematic review วิธี/เครื่องมือเลือกพันธุ์และตำแหน่งปลูกในเมือง',
    'species.py — กรอบแนะนำพันธุ์ไม้ 6 ภูมิภาค (22 ชนิด)'),
 ]),
 ('H. ข้อเสนอต่อยอด (กลุ่ม B — งานวิจัยรองรับ แต่ยังไม่พัฒนา)', [
   ('R2', 'Konijnendijk (2023)', 'roadmap',
    'กฎ 3-30-300 (เห็นต้นไม้ 3 ต้นจากบ้าน · canopy 30% · สวนสาธารณะใน 300 ม.)',
    'แผน FR-17/18 — ยังไม่พัฒนา'),
   ('R6, R20', 'American Forests — Tree Equity Score', 'roadmap',
    'สูตร Tree Equity Score = 100(1 − GapScore·E) จาก 7 ตัวแปรสังคม (อายุ รายได้ สุขภาพ ความร้อน ฯลฯ)',
    'แผน FR-21/22 — ยังไม่พัฒนา'),
   ('R21', 'Fulton et al. (2025)', 'roadmap',
    'เปรียบเทียบเครื่องมือ equity-mapping สำหรับจัดลำดับความต้องการต้นไม้ (กรณี Austin)',
    'แผน FR-21/22 — ยังไม่พัฒนา'),
   ('R7', 'i-Tree Eco (2024)', 'roadmap',
    'โมเดลตีมูลค่าบริการนิเวศ: ดูดซับมลพิษ (PM2.5/O₃/NO₂), ลด stormwater, ตีมูลค่าเป็นเงิน',
    'แผน FR-23/24/25 — ยังไม่พัฒนา'),
   ('R18', 'G2SFCA Seoul (2026)', 'roadmap',
    'วิธี Two-Step Floating Catchment Area ถ่วงทั้ง supply (ขนาดสวน) และ demand (ความหนาแน่นประชากร)',
    'แผน FR-20 accessibility เต็มรูป — ยังไม่พัฒนา'),
 ]),
]


# ── Build story ──────────────────────────────────────────────────────────────
story = []
story.append(header_bar('รายละเอียด: เอาอะไรจากงานวิจัยมาใช้ตรงไหนในระบบ'))
story.append(Spacer(1, 3))
story.append(Paragraph(
    'Bibliography Extraction Detail — ระบุ "ค่า/สูตร/ข้อมูล" ที่ดึงจากแต่ละงานวิจัย '
    'มาตั้งเป็นค่าคงที่/สูตรตรงจุดใดในโค้ด · โครงการ NSC 28P14N00163 · '
    'ค่าทุกตัวสอบทานจาก impact.py · scoring.py · gee_utils.py · stats_utils.py',
    S['muted']))
story.append(Spacer(1, 8))

story.append(callout_box(
    'อ่านตารางอย่างไร: คอลัมน์ "เอาอะไรมาใช้" คือค่า/สูตร/ข้อมูลที่ดึงจากงานวิจัยนั้น '
    'ส่วน "ใช้ตรงไหนในระบบ" คือไฟล์โค้ดและค่าคงที่จริงที่ตั้งไว้ · '
    'สี R# = สถานะการใช้งาน',
    COL['green'], COL['light_green']))
story.append(Spacer(1, 4))
story.append(Paragraph(
    '<font face="Sarabun-Bold" color="#1e8e3e">R# เขียว = ใช้แล้ว</font> (มีในโค้ดจริง) · '
    '<font face="Sarabun-Bold" color="#f97316">R# ส้ม = ใช้บางส่วน</font> (แนวคิดถูกใช้บางส่วน) · '
    '<font face="Sarabun-Bold" color="#7c3aed">R# ม่วง = แผนต่อยอด</font> (ยังไม่พัฒนา)',
    S['muted']))
story.append(Spacer(1, 10))

for title, rows in MODULES:
    story.extend(module_section(title, rows))

story.append(Paragraph(
    'อ้างอิงรายการเต็ม: REQUIREMENTS.md §7 · สรุปสถานะภาพรวม: '
    'Bibliography_Relevance_Audit.pdf · บรรณานุกรมในเล่มข้อเสนอ: '
    'Proposal_28P14N00163_GreenAreaThailand.pdf ข้อ 8',
    S['muted']))

out_path = os.path.join(ROOT, 'Bibliography_Extraction_Detail.pdf')
doc = SimpleDocTemplate(
    out_path, pagesize=A4,
    leftMargin=20 * mm, rightMargin=20 * mm,
    topMargin=22 * mm, bottomMargin=20 * mm,
    title='รายละเอียดการนำงานวิจัยมาใช้ — 28P14N00163',
    author='อติชาติ ผาแสนเถิน',
    subject='Bibliography Extraction Detail — NSC 2026',
)
doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
print(f'[OK] Generated: {out_path}')
print(f'     Size: {os.path.getsize(out_path):,} bytes')
