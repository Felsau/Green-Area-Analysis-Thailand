"""สร้าง PDF ข้อเสนอโครงการ NSC 28P14N00163 (หน้า 2-9)
หน้าปก (หน้า 1) ใช้ไฟล์ของ NSC ที่มีอยู่แล้ว — เอกสารนี้คือเนื้อหาที่เหลือ
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
    KeepTogether, Image,
)

ROOT = os.path.dirname(os.path.abspath(__file__))          # presentation/ — screenshots & outputs live here
REPO_ROOT = os.path.dirname(ROOT)                          # repo root — shared app assets
FONT_DIR = os.path.join(REPO_ROOT, 'green-area-frontend', 'public', 'fonts')

pdfmetrics.registerFont(TTFont('Sarabun', os.path.join(FONT_DIR, 'Sarabun-Regular.ttf')))
pdfmetrics.registerFont(TTFont('Sarabun-Bold', os.path.join(FONT_DIR, 'Sarabun-Bold.ttf')))

# ── Colors ──────────────────────────────────────────────────────────────────
COL = {
    'primary':    HexColor('#1a73e8'),
    'green':      HexColor('#1e8e3e'),
    'green_deep': HexColor('#0e5c24'),
    'red':        HexColor('#dc2626'),
    'orange':     HexColor('#f97316'),
    'purple':     HexColor('#7c3aed'),
    'text':       HexColor('#202124'),
    'muted':      HexColor('#5f6368'),
    'border':     HexColor('#dadce0'),
    'light':      HexColor('#f1f3f4'),
    'light_blue': HexColor('#e8f0fe'),
    'light_green':HexColor('#e6f4ea'),
}

# ── Styles ──────────────────────────────────────────────────────────────────
def style(name, font='Sarabun', size=11, color=None, leading=None,
          space_after=4, space_before=0, align=TA_LEFT, left=0, first_line=0):
    return ParagraphStyle(
        name=name, fontName=font, fontSize=size,
        textColor=color or COL['text'],
        leading=leading or size * 1.55,
        spaceAfter=space_after, spaceBefore=space_before,
        alignment=align, leftIndent=left, firstLineIndent=first_line,
    )

S = {
    'h1':       style('h1', font='Sarabun-Bold', size=20, color=white,
                      space_after=2, leading=24),
    'h1_sub':   style('h1_sub', size=11, color=HexColor('#e8f0fe'), leading=14),
    'h2':       style('h2', font='Sarabun-Bold', size=15, color=COL['primary'],
                      space_before=8, space_after=6, leading=20),
    'h3':       style('h3', font='Sarabun-Bold', size=12.5, color=COL['green_deep'],
                      space_before=6, space_after=4, leading=17),
    'h4':       style('h4', font='Sarabun-Bold', size=11, color=COL['text'],
                      space_before=4, space_after=2, leading=15),
    'p':        style('p', size=10.5, leading=16.5, space_after=4,
                      align=TA_JUSTIFY, first_line=14),
    'p_no_indent': style('p_ni', size=10.5, leading=16.5, space_after=4,
                         align=TA_JUSTIFY),
    'p_center': style('p_c', size=10.5, leading=16, space_after=4, align=TA_CENTER),
    'p_muted':  style('p_m', size=9.5, color=COL['muted'], leading=13.5),
    'li':       style('li', size=10.5, leading=15.5, space_after=2, left=16),
    'li_sub':   style('li_sub', size=10, color=COL['muted'], leading=14.5,
                      space_after=2, left=32),
    'callout':  style('callout', font='Sarabun-Bold', size=10.5,
                      color=COL['primary'], leading=15, space_after=4),
    'tag':      style('tag', font='Sarabun-Bold', size=9, color=white, align=TA_CENTER),
    'ref':      style('ref', size=10, leading=14, space_after=4, left=16,
                      first_line=-16),
}

# ── Helpers ─────────────────────────────────────────────────────────────────
def b(t):
    return f'<font face="Sarabun-Bold">{t}</font>'

def code(t):
    return f'<font face="Courier" size="9.5" color="#5f6368">{t}</font>'

def header_bar(num, title, color=None):
    """หัวข้อใหญ่ของแต่ละข้อ — กล่องมี number ซ้าย"""
    color = color or COL['primary']
    num_cell = Paragraph(f'<font color="white" face="Sarabun-Bold" size="20">{num}</font>',
                         S['p_center'])
    title_cell = Paragraph(title, S['h2'])
    t = Table([[num_cell, title_cell]], colWidths=[18 * mm, 152 * mm])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, 0), color),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (0, 0), 4),
        ('RIGHTPADDING', (0, 0), (0, 0), 4),
        ('TOPPADDING', (0, 0), (0, 0), 6),
        ('BOTTOMPADDING', (0, 0), (0, 0), 6),
        ('LEFTPADDING', (1, 0), (1, 0), 10),
        ('LINEBELOW', (1, 0), (1, 0), 1.2, color),
    ]))
    return t

def sub_header(text, color=None):
    """หัวย่อย 7.1, 7.2 ฯลฯ"""
    color = color or COL['primary']
    p = Paragraph(text, S['h3'])
    t = Table([[p]], colWidths=[170 * mm])
    t.setStyle(TableStyle([
        ('LINEBEFORE', (0, 0), (0, -1), 2.5, color),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
    ]))
    return t

def callout_box(text, color=None, bg=None):
    color = color or COL['primary']
    bg = bg or COL['light_blue']
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

def info_table(rows, col_widths=None, header_color=None, header_white=True):
    header_color = header_color or COL['primary']
    cw = col_widths or [55 * mm, 115 * mm]
    t = Table(rows, colWidths=cw, repeatRows=1)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), header_color),
        ('TEXTCOLOR', (0, 0), (-1, 0), white if header_white else COL['text']),
        ('FONTNAME', (0, 0), (-1, 0), 'Sarabun-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('FONTNAME', (0, 1), (-1, -1), 'Sarabun'),
        ('FONTSIZE', (0, 1), (-1, -1), 9.5),
        ('GRID', (0, 0), (-1, -1), 0.4, COL['border']),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 7),
        ('RIGHTPADDING', (0, 0), (-1, -1), 7),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [white, HexColor('#f8f9fa')]),
    ]))
    return t

def tag_pill(text, color):
    """กล่อง keyword สีๆ"""
    p = Paragraph(text, S['tag'])
    t = Table([[p]], colWidths=[None])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), color),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]))
    return t

def keyword_row(keywords):
    """แถวของ keyword pills"""
    colors = [COL['primary'], COL['green'], COL['orange'], COL['purple'], COL['red'],
              COL['green_deep'], HexColor('#0891b2'), HexColor('#be185d'),
              HexColor('#7c2d12'), HexColor('#15803d')]
    cells = []
    for i, k in enumerate(keywords):
        cells.append(tag_pill(k, colors[i % len(colors)]))
    rows = []
    cols_per_row = 4
    for i in range(0, len(cells), cols_per_row):
        row = cells[i:i + cols_per_row]
        while len(row) < cols_per_row:
            row.append('')
        rows.append(row)
    cw = [42 * mm] * cols_per_row
    t = Table(rows, colWidths=cw)
    t.setStyle(TableStyle([
        ('LEFTPADDING', (0, 0), (-1, -1), 2),
        ('RIGHTPADDING', (0, 0), (-1, -1), 2),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    return t

# ── Page header / footer ────────────────────────────────────────────────────
def on_page(canvas, doc):
    canvas.saveState()
    # Top header
    canvas.setFont('Sarabun', 8.5)
    canvas.setFillColor(COL['muted'])
    canvas.drawString(20 * mm, 287 * mm,
                      'ข้อเสนอโครงการ · รหัส 28P14N00163 · NSC 2026')
    canvas.drawRightString(190 * mm, 287 * mm,
                           'มหาวิทยาลัยพะเยา')
    canvas.setStrokeColor(COL['border'])
    canvas.setLineWidth(0.4)
    canvas.line(20 * mm, 284 * mm, 190 * mm, 284 * mm)

    # Footer
    canvas.setFont('Sarabun', 8.5)
    canvas.setFillColor(COL['muted'])
    canvas.drawString(20 * mm, 12 * mm,
                      'ระบบวิเคราะห์พื้นที่สีเขียวฯ ด้วยข้อมูลดาวเทียมและปัญญาประดิษฐ์')
    canvas.drawRightString(190 * mm, 12 * mm, f'หน้า {doc.page + 1}')
    canvas.setStrokeColor(COL['border'])
    canvas.line(20 * mm, 15 * mm, 190 * mm, 15 * mm)
    canvas.restoreState()


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║                          CONTENT START                                    ║
# ╚══════════════════════════════════════════════════════════════════════════╝
story = []

# ── ข้อ 2. สาระสำคัญของโครงการ ────────────────────────────────────────────────
story.append(header_bar('2', 'สาระสำคัญของโครงการ และคำสำคัญ (Keywords)',
                        color=COL['primary']))
story.append(Spacer(1, 6))

story.append(Paragraph(b('ชื่อโครงการ (ภาษาไทย):') + ' ระบบวิเคราะห์พื้นที่สีเขียวและแนะนำพื้นที่ปลูกต้นไม้อัจฉริยะของประเทศไทย ด้วยข้อมูลดาวเทียมและปัญญาประดิษฐ์', S['p_no_indent']))
story.append(Paragraph(b('Title (English):') + ' An Intelligent Satellite-Driven Geospatial Decision Support System for Green Space Analysis and AI-Powered Tree Planting Prioritization across Thailand', S['p_no_indent']))
story.append(Spacer(1, 4))

story.append(Paragraph(b('สาระสำคัญ (Abstract)'), S['h4']))
story.append(Paragraph(
    'ปรากฏการณ์เกาะความร้อนเมือง (Urban Heat Island, UHI) และปริมาณพื้นที่สีเขียว '
    'ต่อประชากรที่ต่ำกว่ามาตรฐาน 9 ตารางเมตรต่อคนขององค์การอนามัยโลก (WHO) '
    'เป็นปัญหาสำคัญที่กระทบต่อคุณภาพชีวิตของประชาชนในเขตเมืองทั่วประเทศไทย '
    'อย่างไรก็ตาม หน่วยงานปกครองส่วนท้องถิ่นและภาคประชาสังคมยังขาดเครื่องมือกลาง '
    'ที่ใช้ข้อมูลภูมิสารสนเทศประกอบการตัดสินใจวางแผนการปลูกต้นไม้ในระดับพื้นที่ '
    'โครงการนี้พัฒนาระบบสนับสนุนการตัดสินใจเชิงภูมิสารสนเทศบนเว็บแอปพลิเคชัน '
    'ที่บูรณาการข้อมูลดาวเทียมแบบเปิด ได้แก่ Sentinel-2 (NDVI ความละเอียด 10 เมตร) '
    'Landsat 8/9 (Land Surface Temperature 30 เมตร) WorldPop (ประชากร 100 เมตร) '
    'และ ESA WorldCover เข้ากับแพลตฟอร์ม Google Earth Engine '
    'จากนั้นประยุกต์ใช้ปัญญาประดิษฐ์คำนวณคะแนนความสำคัญ (Priority Score) '
    'เพื่อจัดอันดับพื้นที่ที่ควรปลูกต้นไม้ภายในจังหวัดและอำเภอ '
    'พร้อมแนะนำพันธุ์ไม้พื้นถิ่นที่เหมาะสมตามภูมิภาคและประมาณการณ์ผลกระทบ '
    'ทั้งในด้านการดูดซับคาร์บอนไดออกไซด์และการลดอุณหภูมิผิวพื้น ระบบครอบคลุม '
    'ทั่วประเทศไทย 77 จังหวัด 928 อำเภอ รองรับการวิเคราะห์ย้อนหลังตั้งแต่ปี '
    'พ.ศ. 2558 จนถึงปัจจุบัน และสามารถส่งออกรายงานเชิงวิชาการในรูปแบบ PDF',
    S['p']))

story.append(Spacer(1, 4))
story.append(Paragraph(b('คำสำคัญ (Keywords)'), S['h4']))
story.append(keyword_row([
    'NDVI', 'LST', 'Urban Heat Island', 'Google Earth Engine',
    'GIS', 'Decision Support', 'AI Recommendation', 'พื้นที่สีเขียว',
    'Remote Sensing', 'Sentinel-2', 'CO2 Sequestration', 'Smart City',
]))
story.append(Spacer(1, 8))


# ── ข้อ 3. หลักการและเหตุผล ───────────────────────────────────────────────────
story.append(header_bar('3', 'หลักการและเหตุผล', color=COL['primary']))
story.append(Spacer(1, 6))

story.append(Paragraph(
    'การขยายตัวของชุมชนเมืองในประเทศไทยอย่างรวดเร็วในช่วง 30 ปีที่ผ่านมา '
    'ส่งผลให้พื้นที่ปกคลุมด้วยสิ่งปลูกสร้างเพิ่มขึ้นจนเกิดปรากฏการณ์ '
    'เกาะความร้อนเมือง (Urban Heat Island, UHI) ซึ่งทำให้เมืองมีอุณหภูมิ '
    'สูงกว่าพื้นที่ชนบทโดยรอบประมาณ 1 ถึง 3 องศาเซลเซียส (Bowler et al., 2010) '
    'สิ่งนี้ส่งผลกระทบโดยตรงต่อสุขภาพประชาชน คุณภาพอากาศ การใช้พลังงาน '
    'เครื่องปรับอากาศ และความเปราะบางต่อการเปลี่ยนแปลงสภาพภูมิอากาศ',
    S['p']))

story.append(Paragraph(
    'องค์การอนามัยโลกแนะนำให้พื้นที่ในเขตเมืองมีพื้นที่สีเขียวเข้าถึงได้ '
    'อย่างน้อย 9 ตารางเมตรต่อประชากรหนึ่งคน (WHO, 2017) แต่จากการสำรวจของ '
    'กรุงเทพมหานคร พบว่ามีพื้นที่สีเขียวเฉลี่ยเพียงประมาณ 3 ตารางเมตรต่อคน '
    'ซึ่งต่ำกว่ามาตรฐานสากลอย่างมาก ในขณะเดียวกัน หัวเมืองสำคัญหลายแห่ง '
    'ของประเทศก็มีสถิติคล้ายคลึงกัน อย่างไรก็ตาม การจะเพิ่มพื้นที่สีเขียว '
    'อย่างมีประสิทธิภาพและตอบโจทย์ความต้องการของชุมชนอย่างแท้จริง '
    'จำเป็นต้องมีข้อมูลภูมิสารสนเทศที่แม่นยำ และเครื่องมือที่ใช้ '
    'ตัดสินใจร่วมกันระหว่างเทศบาล ภาคประชาสังคม และนักวิจัย',
    S['p']))

story.append(Paragraph(
    'ปัจจุบัน แพลตฟอร์มประมวลผลข้อมูลดาวเทียมระดับโลกอย่าง Google Earth Engine '
    '(Gorelick et al., 2017) ได้เปิดให้นักวิจัยและสาธารณะใช้งานได้ฟรี '
    'พร้อมข้อมูลเปิดอย่าง Sentinel-2 (Drusch et al., 2012) ที่ให้ภาพ '
    'หลายช่วงคลื่นความละเอียด 10 เมตร และ Landsat 8/9 ของ USGS ที่ให้ข้อมูล '
    'อุณหภูมิผิวพื้นที่ความละเอียด 30 เมตร ทำให้การพัฒนาเครื่องมือ '
    'วิเคราะห์เชิงพื้นที่ครอบคลุมทั่วประเทศเป็นไปได้โดยไม่ต้องลงทุน '
    'โครงสร้างพื้นฐานราคาแพง โครงการนี้จึงมุ่งใช้ประโยชน์จากโครงสร้าง '
    'ที่มีอยู่ ผนวกกับเทคนิคปัญญาประดิษฐ์และระบบเว็บที่ทันสมัย พัฒนาเป็น '
    'เครื่องมือกลางสำหรับการวางแผนเพิ่มพื้นที่สีเขียวระดับชาติ',
    S['p']))
story.append(Spacer(1, 6))


# ── ข้อ 4. วัตถุประสงค์ ──────────────────────────────────────────────────────
story.append(header_bar('4', 'วัตถุประสงค์', color=COL['green']))
story.append(Spacer(1, 6))

objectives = [
    ('พัฒนาเว็บแอปพลิเคชันที่แสดงผลค่าดัชนีพืชพรรณ (NDVI) และอุณหภูมิ '
     'ผิวพื้น (LST) ระดับจังหวัดและอำเภอครอบคลุมประเทศไทยทั้ง 77 จังหวัด '
     '928 อำเภอ บนแผนที่แบบโต้ตอบ 3 มิติ'),
    ('พัฒนาอัลกอริทึมจัดอันดับความสำคัญของพื้นที่ปลูกต้นไม้ (Priority Score) '
     'โดยการถ่วงน้ำหนักดัชนีการขาดพืชพรรณ ความร้อนผิวพื้น และความหนาแน่น '
     'ประชากร เพื่อแนะนำพิกัดที่ควรปลูกต้นไม้มากที่สุด 10 อันดับแรก'),
    ('พัฒนาระบบแนะนำพันธุ์ไม้พื้นถิ่นที่เหมาะสมแยกตาม 6 ภูมิภาคของไทย '
     '(เหนือ อีสาน กลาง ตะวันออก ตะวันตก และใต้) ครอบคลุมพันธุ์ไม้ 22 ชนิด '
     'พร้อมเหตุผลทางนิเวศและการใช้ประโยชน์'),
    ('ประมาณการณ์ผลกระทบของการปลูกในพื้นที่ที่แนะนำ ทั้งปริมาณก๊าซ '
     'คาร์บอนไดออกไซด์ที่ดูดซับได้ต่อปี และผลในการลดอุณหภูมิผิวพื้น '
     'อิงตามแนวทางของ IPCC 2019 และ Bowler et al. 2010'),
    ('พัฒนาฟีเจอร์ Time-lapse แสดงพัฒนาการของพื้นที่สีเขียวย้อนหลัง '
     'ตั้งแต่ปี 2558 ถึงปัจจุบัน (มากกว่า 10 ปี) เพื่อให้ผู้ใช้เห็น '
     'แนวโน้มการเปลี่ยนแปลงในเชิงเวลา'),
    ('พัฒนาระบบส่งออกรายงาน PDF คุณภาพระดับวิทยานิพนธ์ ที่รวมแผนที่ '
     'NDVI/LST ตารางเปรียบเทียบ กราฟแนวโน้ม วิธีวิทยา ข้อจำกัด '
     'และบรรณานุกรม ไว้ในไฟล์เดียว'),
    ('เปรียบเทียบค่าพื้นที่สีเขียวต่อคนของแต่ละจังหวัดกับมาตรฐาน WHO '
     '9 ตารางเมตรต่อคน และคำนวณค่า Urban Subset ที่จำกัดเฉพาะเขตเมือง '
     '(Built-up area) เพื่อให้เปรียบเทียบกับมาตรฐานได้อย่างถูกต้อง'),
]
for i, obj in enumerate(objectives, 1):
    story.append(Paragraph(
        f'<font color="#1e8e3e" face="Sarabun-Bold">{i}.</font> {obj}',
        S['li']))
story.append(Spacer(1, 8))


# ── ข้อ 5. ปัญหาหรือประโยชน์ ─────────────────────────────────────────────────
story.append(header_bar('5', 'ปัญหาหรือประโยชน์ที่เป็นเหตุผลให้ควรพัฒนาโปรแกรม',
                        color=COL['red']))
story.append(Spacer(1, 6))

story.append(sub_header('5.1 ปัญหาที่โครงการมุ่งแก้ไข', color=COL['red']))
story.append(Spacer(1, 4))

problems = [
    ('ขาดข้อมูลกลางที่ครอบคลุมทั่วประเทศ', 'หน่วยงานท้องถิ่นแต่ละแห่ง '
     'เก็บข้อมูลพื้นที่สีเขียวในรูปแบบของตนเอง ไม่มีฐานข้อมูลกลาง '
     'ที่เปรียบเทียบกันได้ทั่วประเทศ ทำให้การวางนโยบายในระดับชาติ '
     'ขาดข้อมูลสนับสนุนที่เป็นกลาง'),
    ('พื้นที่สีเขียวต่ำกว่ามาตรฐาน WHO', 'กรุงเทพมหานครและหัวเมือง '
     'ส่วนใหญ่มีพื้นที่สีเขียวต่อประชากรต่ำกว่า 9 ตารางเมตรต่อคน '
     'ตามมาตรฐาน WHO ส่งผลต่อสุขภาพ คุณภาพอากาศ และคุณภาพชีวิต'),
    ('ปรากฏการณ์เกาะความร้อนเมือง (UHI)', 'เมืองในไทยร้อนกว่าชนบท '
     'รอบข้าง 1 ถึง 3 องศาเซลเซียส (Bowler et al., 2010) ทำให้ '
     'การใช้พลังงานเครื่องปรับอากาศและความเสี่ยงต่อสุขภาพเพิ่มขึ้น'),
    ('ขาดเครื่องมือตัดสินใจอย่างเป็นระบบ', 'การปลูกต้นไม้ในเขตเมือง '
     'ปัจจุบันยังขึ้นกับการตัดสินใจของบุคคลหรือพื้นที่ที่ว่างอยู่ '
     'มากกว่าการวิเคราะห์ข้อมูลเชิงพื้นที่เพื่อหาจุดที่ควรปลูกมากที่สุด'),
    ('ขาดความรู้เรื่องพันธุ์ไม้ที่เหมาะสม', 'หลายเทศบาลปลูกต้นไม้ '
     'ที่ไม่เหมาะกับสภาพดินและภูมิอากาศของพื้นที่ ทำให้ต้นไม้ตาย '
     'หรือไม่เติบโต ส่งผลให้งบประมาณสูญเปล่า'),
]
for title, desc in problems:
    story.append(Paragraph(f'<font color="#dc2626">▸</font> {b(title)}',
                           S['h4']))
    story.append(Paragraph(desc, S['p_no_indent']))
    story.append(Spacer(1, 2))

story.append(Spacer(1, 6))
story.append(sub_header('5.2 ประโยชน์ที่คาดว่าจะได้รับ', color=COL['green']))
story.append(Spacer(1, 4))

benefits = [
    ('ภาครัฐและองค์กรปกครองส่วนท้องถิ่น', 'ใช้เป็นเครื่องมือวางแผน '
     'นโยบายเพิ่มพื้นที่สีเขียว จัดสรรงบประมาณการปลูกต้นไม้ '
     'และกำหนดเขต Green Buffer Zone อย่างมีหลักฐานเชิงข้อมูล'),
    ('ภาคประชาสังคมและเครือข่ายชุมชน', 'ตรวจสอบสถานะพื้นที่สีเขียว '
     'ของบ้านเกิด เปรียบเทียบกับจังหวัดอื่น และนำเสนอข้อเรียกร้อง '
     'ต่อหน่วยงานท้องถิ่นโดยอ้างอิงข้อมูลที่เป็นกลาง'),
    ('นักวิจัยและสถาบันการศึกษา', 'นำข้อมูลที่ได้ไปวิเคราะห์ต่อ '
     'ในงานวิจัยด้าน UHI การเปลี่ยนแปลงภูมิอากาศ และนิเวศวิทยาเมือง '
     'รวมทั้งใช้ระบบเป็นกรณีศึกษาในวิชาภูมิสารสนเทศ'),
    ('ภาคเอกชนและ CSR', 'องค์กรที่ทำกิจกรรมความรับผิดชอบต่อสังคม '
     'ด้านการปลูกป่าและคืนพื้นที่สีเขียว ใช้ระบบเลือกพื้นที่ '
     'และพันธุ์ไม้ที่ให้ผลกระทบสูงสุดต่องบประมาณที่จำกัด'),
    ('นโยบายระดับชาติและพันธกิจสากล', 'สนับสนุนเป้าหมายการพัฒนา '
     'ที่ยั่งยืน (SDGs) เป้าหมายที่ 11 เมืองยั่งยืน เป้าหมายที่ 13 '
     'ปฏิบัติการเรื่องสภาพภูมิอากาศ และพันธสัญญาคาร์บอนสุทธิเป็นศูนย์ '
     'ของไทยภายในปี ค.ศ. 2065'),
]
for title, desc in benefits:
    story.append(Paragraph(f'<font color="#1e8e3e">▸</font> {b(title)}',
                           S['h4']))
    story.append(Paragraph(desc, S['p_no_indent']))
    story.append(Spacer(1, 2))

story.append(Spacer(1, 8))


# ── ข้อ 6. เป้าหมายและขอบเขตของโครงการ ────────────────────────────────────────
story.append(header_bar('6', 'เป้าหมายและขอบเขตของโครงการ', color=COL['purple']))
story.append(Spacer(1, 6))

story.append(sub_header('6.1 เป้าหมาย (Goals)', color=COL['purple']))
story.append(Spacer(1, 4))
goals = [
    'พัฒนาเว็บแอปพลิเคชันที่พร้อมใช้งานจริง (Production-Ready) เปิดให้สาธารณะใช้ฟรี',
    'ครอบคลุมพื้นที่ 77 จังหวัด 928 อำเภอ ของประเทศไทย',
    'รองรับการวิเคราะห์ตั้งแต่ปี พ.ศ. 2558 จนถึงปัจจุบัน (มากกว่า 10 ปี)',
    'ความแม่นยำของพื้นที่สีเขียวต้องสอดคล้องกับข้อมูล ESA WorldCover (ภายใน ±10%)',
    'เวลาตอบสนองของ API สำหรับข้อมูลที่อยู่ใน cache ต้องน้อยกว่า 2 วินาที',
    'รองรับภาษาไทยและภาษาอังกฤษเต็มรูปแบบ ทั้งในระบบและรายงาน PDF',
    'รายงาน PDF ที่ส่งออกต้องมีคุณภาพเทียบเท่ารายงานวิทยานิพนธ์ (มีแผนที่ ตาราง กราฟ บรรณานุกรม)',
]
for g in goals:
    story.append(Paragraph(f'• {g}', S['li']))

story.append(Spacer(1, 6))
story.append(sub_header('6.2 ขอบเขต (Scope)', color=COL['purple']))
story.append(Spacer(1, 4))

story.append(info_table([
    ['มิติ', 'ขอบเขต'],
    ['พื้นที่ทางภูมิศาสตร์', 'ประเทศไทย ใช้ขอบเขตการปกครองจาก GADM v4.1 (จังหวัดและอำเภอ)'],
    ['ช่วงเวลา', 'พ.ศ. 2558 ถึงปัจจุบัน (จุดเริ่มต้นของ Sentinel-2)'],
    ['ความละเอียดเชิงพื้นที่', 'NDVI 10 ม., LST 30 ม., ประชากร 100 ม., Priority 100 ม.'],
    ['ดัชนีและข้อมูล', 'NDVI, LST, Green Area %, m²/คน, Priority Score, CO2 และ Cooling impact'],
    ['พันธุ์ไม้แนะนำ', '22 ชนิด แบ่งตาม 6 ภูมิภาคของไทย'],
    ['ภาษา', 'ภาษาไทยและภาษาอังกฤษ'],
    ['แพลตฟอร์ม', 'เว็บแอปพลิเคชัน (Responsive, รองรับ Desktop และ Mobile)'],
    ['การ Deploy', 'Frontend บน Vercel, Backend บน Render/Railway'],
], col_widths=[45 * mm, 125 * mm], header_color=COL['purple']))
story.append(Spacer(1, 8))


# ── ข้อ 7. รายละเอียดของการพัฒนา ─────────────────────────────────────────────
story.append(header_bar('7', 'รายละเอียดของการพัฒนา', color=COL['orange']))
story.append(Spacer(1, 6))

# 7.1 Story board
story.append(sub_header('7.1 เนื้อเรื่องย่อ (Story Board) และสถาปัตยกรรมระบบ',
                        color=COL['orange']))
story.append(Spacer(1, 4))
story.append(Paragraph(
    'ระบบประกอบด้วยสามส่วนหลัก คือส่วนหน้าเว็บ (Frontend) ส่วนหลังเว็บ '
    '(Backend) และบริการภายนอก (External Services) ซึ่งทำงานร่วมกัน '
    'ในรูปแบบ Three-tier Architecture ดังภาพแนวคิดต่อไปนี้',
    S['p']))

# ASCII diagram
diagram = Paragraph(
    '<font face="Courier" size="9">'
    '┌─────────────────────┐&nbsp;&nbsp;&nbsp;HTTP&nbsp;&nbsp;┌──────────────────┐&nbsp;&nbsp;REST&nbsp;&nbsp;┌──────────────────┐<br/>'
    '│&nbsp;React 19 + Deck.GL&nbsp;&nbsp;│&lt;─────&gt;│&nbsp;&nbsp;FastAPI Backend&nbsp;│&lt;─────&gt;│&nbsp;&nbsp;Google Earth&nbsp;&nbsp;&nbsp;│<br/>'
    '│&nbsp;MapLibre GL + jsPDF │&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;│&nbsp;&nbsp;&nbsp;&nbsp;(Uvicorn)&nbsp;&nbsp;&nbsp;&nbsp;│&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;│&nbsp;&nbsp;Engine&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;│<br/>'
    '└─────────────────────┘&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;└────────┬─────────┘&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;└──────────────────┘<br/>'
    '&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;│ supabase-py<br/>'
    '&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;▼<br/>'
    '&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;┌──────────────────┐<br/>'
    '&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;│ Supabase (DB)&nbsp;&nbsp;&nbsp;│<br/>'
    '&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;│ Cache 11 ตาราง&nbsp;&nbsp;│<br/>'
    '&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;└──────────────────┘'
    '</font>',
    S['p_no_indent'])
story.append(diagram)
story.append(Spacer(1, 6))

story.append(Paragraph(b('ลำดับการใช้งานทั่วไป (User Flow)'), S['h4']))
flow_steps = [
    'ผู้ใช้เปิดหน้าเว็บ ระบบโหลดแผนที่ประเทศไทยพร้อมขอบเขตจังหวัดทั้ง 77 จังหวัด',
    'ผู้ใช้คลิกเลือกจังหวัดใดจังหวัดหนึ่งบนแผนที่ ระบบดึงข้อมูลจาก Backend',
    'Backend ตรวจสอบในฐานข้อมูล Supabase ก่อนหากพบ cache จะส่งกลับทันที '
    'หากไม่พบจะเรียก Google Earth Engine คำนวณค่า NDVI และ LST ใหม่ '
    'แล้วบันทึก cache ก่อนตอบกลับ',
    'หน้าเว็บแสดงข้อมูล Statistics ของจังหวัด พร้อมเทียบมาตรฐาน WHO',
    'ผู้ใช้สามารถสลับ Tab ไปดู Trend (ย้อนหลังหลายปี) Compare (เปรียบเทียบจังหวัด) '
    'Districts (รายอำเภอ) หรือ Recommend (AI แนะนำพื้นที่ปลูก)',
    'หากเลือก Tab Recommend ระบบจะแสดง Heatmap ของ Priority Score 10 จุดที่สำคัญ '
    'พันธุ์ไม้แนะนำตามภูมิภาค และค่าประมาณการณ์ CO2 และ Cooling',
    'ผู้ใช้กดปุ่ม Export PDF ระบบสร้างรายงานคุณภาพระดับวิทยานิพนธ์ พร้อมแผนที่ ตาราง '
    'กราฟ และบรรณานุกรม ดาวน์โหลดทันที',
]
for i, s in enumerate(flow_steps, 1):
    story.append(Paragraph(
        f'<font color="#f97316" face="Sarabun-Bold">{i}.</font> {s}',
        S['li']))
story.append(Spacer(1, 8))

# ── User Flow Diagram (flowchart) ───────────────────────────────────────────
diagram_path = os.path.join(ROOT, 'user_flow_diagram.png')
if os.path.exists(diagram_path):
    flow_img = Image(diagram_path, width=170 * mm, height=99 * mm,
                     kind='proportional')
    # Caption above the image
    caption = Paragraph(
        '<font face="Sarabun-Bold" color="#5f6368">'
        'รูปที่ 7.1 — แผนภาพลำดับการใช้งานระบบ (User Flow Diagram)'
        '</font>',
        S['p_center'])
    # Wrap image + caption together so they don't break across pages
    story.append(KeepTogether([
        caption,
        Spacer(1, 4),
        flow_img,
    ]))
    story.append(Spacer(1, 4))
    story.append(Paragraph(
        'ภาพแสดงลำดับขั้น 7 ขั้นตอนแบบ Serpentine '
        '(แถวบน: ขั้น 1–4 ไหลจากซ้ายไปขวา · แถวล่าง: ขั้น 5–7 ไหลย้อนจากขวาไปซ้าย) '
        'โดยกล่องสีเขียวคือขั้นที่เรียกบริการภายนอก (Google Earth Engine) '
        'กล่องสีฟ้าอ่อนคือขั้นแสดงผล และกล่องสีม่วงคือผลลัพธ์สุดท้าย '
        '(PDF Report) ค่าบนกล่อง Cache hit < 2 วินาที เทียบกับ Cache miss '
        '30–60 วินาที สะท้อนผลของการออกแบบ Caching Layer ที่ช่วยลด GEE round-trip',
        S['p']))
    story.append(Spacer(1, 8))


# ── 7.1.1 Actual screenshots of working prototype ──────────────────────────
story.append(sub_header('7.1.1 ตัวอย่างหน้าจอจากระบบที่พัฒนาแล้ว (Working Prototype)',
                        color=COL['green_deep']))
story.append(Spacer(1, 4))
story.append(Paragraph(
    'ปัจจุบันระบบได้พัฒนาไปแล้วประมาณ 85% ของขอบเขตที่กำหนด ครอบคลุมทั้งส่วน Frontend '
    '(React + Deck.gl 3D Map + 4 Tabs: ข้อมูล/แนวโน้ม/เปรียบเทียบ/AI แนะนำ) Backend '
    '(FastAPI + Google Earth Engine + Supabase Cache 11 ตาราง) และระบบ Export PDF Report '
    'ระดับวิทยานิพนธ์ที่ใช้งานได้จริง ภาพหน้าจอ 11 ภาพต่อไปนี้ถ่ายจากระบบที่กำลังทำงานบน '
    'localhost ด้วยข้อมูลจริงจาก Sentinel-2 และ Landsat 8/9 ปี พ.ศ. 2569 โดยใช้กรณีศึกษา '
    'จังหวัดตาก พร้อมแสดงการ drill-down ลงไประดับอำเภอ (แม่สอด) เพื่อสาธิตความละเอียด '
    'เชิงพื้นที่ของระบบ และตัวอย่างไฟล์ PDF Report ที่ระบบ generate ออกมาจริง',
    S['p']))
story.append(Spacer(1, 6))

# Helper: image + caption
def screenshot_block(filename, caption_num, caption_text, description):
    path = os.path.join(ROOT, 'screenshots', filename)
    if not os.path.exists(path):
        return None
    img = Image(path, width=170 * mm, height=100 * mm, kind='proportional')
    caption = Paragraph(
        f'<font face="Sarabun-Bold" color="#0e5c24">รูปที่ {caption_num} — {caption_text}</font>',
        S['p_center'])
    desc = Paragraph(description, S['p'])
    return KeepTogether([caption, Spacer(1, 3), img, Spacer(1, 4), desc, Spacer(1, 10)])

# Screenshot 7.2: Initial map view (with basemap)
block1 = screenshot_block(
    '01.png', '7.2',
    'หน้าจอแรกของระบบ (Initial Map View)',
    'แสดงแผนที่ประเทศไทย 77 จังหวัด ที่ใช้ Deck.gl 3D extrusion วาดบน MapLibre GL JS '
    'พร้อม basemap ของ CARTO จังหวัดที่มีสีเขียวเข้ม (ภาคเหนือและภาคตะวันตก) คือจังหวัด '
    'ที่มีข้อมูล NDVI อยู่ใน Supabase cache แล้ว (18 จังหวัด) ส่วนสีเทาคือยังไม่มี cache '
    'แถบสถานะมุมขวาบนระบุแหล่งข้อมูล Sentinel-2 ผ่าน Google Earth Engine '
    'ฝั่งซ้ายเป็น Sidebar สำหรับเลือกปีและกดโหลดอันดับ ปุ่ม Time-lapse '
    'ที่มุมขวาล่างเปิดโหมดดูพัฒนาการย้อนหลัง')
if block1:
    story.append(block1)

# Screenshot 7.3: Province NDVI Detail (Tak)
block2 = screenshot_block(
    '02.jpg', '7.3',
    'หน้ารายละเอียดจังหวัด — Tab "ข้อมูล" (NDVI ระดับจังหวัด)',
    'เมื่อผู้ใช้คลิกจังหวัดบนแผนที่ (ภาพแสดงจังหวัดตาก) Sidebar เปลี่ยนเป็น Tab "ข้อมูล" '
    'แสดง NDVI ค่าเฉลี่ยทั้งปี 0.6115 (พืชพรรณหนาแน่นมาก) ค่าต่ำสุด 0 ค่าสูงสุด 0.9141 '
    'พื้นที่จังหวัด 17,268.36 km² พื้นที่สีเขียว (NDVI > 0.3) 96% หรือ 16,520.59 km² '
    'พื้นที่สีเขียวต่อหัวประชากร 28,831.7 m² (ผ่านมาตรฐาน WHO 9 m²/คน) '
    'กราฟ NDVI รายเดือนแสดงการเปลี่ยนแปลงตามฤดูกาล '
    'ในแผนที่แสดงจังหวัดตากเป็น 3D extrusion พร้อม basemap รายละเอียดอำเภอ')
if block2:
    story.append(block2)

# Screenshot 7.4: LST Detail + Urban Heat Island
block3 = screenshot_block(
    '03.jpg', '7.4',
    'หน้ารายละเอียดจังหวัด — Tab "ข้อมูล" (LST + Urban Heat Island)',
    'หน้าจอเดียวกันเลื่อนลงดู Land Surface Temperature (LST) จาก Landsat 8/9 '
    'อุณหภูมิผิวพื้นเฉลี่ย 31.18°C (ระดับปานกลาง) ค่าต่ำสุด 15.32°C ค่าสูงสุด 48.59°C '
    'กราฟแท่ง LST รายเดือนใช้สีแสดงระดับอุณหภูมิ (น้ำเงิน → แดง) '
    'กล่อง Urban Heat Island ประเมินความเสี่ยงเกาะความร้อนเป็น "เสี่ยงต่ำ" '
    'จากการรวม NDVI 0.612 และ LST 31.18°C ส่วนล่างของ Sidebar มีปุ่มส่งออกข้อมูล '
    'เป็น CSV, PNG, PDF และ PNG + แผนที่')
if block3:
    story.append(block3)

# Screenshot 7.5: District NDVI Detail (Mae Sot)
block_dist_ndvi = screenshot_block(
    '06.jpg', '7.5',
    'การ Drill-Down ระดับอำเภอ — NDVI ของอำเภอแม่สอด',
    'ระบบรองรับการวิเคราะห์ลงลึกถึงระดับอำเภอ (928 อำเภอทั่วประเทศจาก GADM v4.1) '
    'ภาพแสดงการคลิกเลือก "อำเภอแม่สอด" จากจังหวัดตาก พื้นที่อำเภอ 1,741.24 km² '
    'NDVI เฉลี่ยทั้งปี 0.5359 (พืชพรรณหนาแน่น แต่ต่ำกว่าค่าเฉลี่ยจังหวัดที่ 0.6115 '
    'เพราะเป็นเขตเมืองชายแดน) ค่าต่ำสุด 0 ค่าสูงสุด 0.934 '
    'พื้นที่สีเขียว (NDVI > 0.3) 85.9% หรือ 1,491.32 km² '
    'ในแผนที่ ระบบแสดงอำเภอแม่สอดด้วยสีฟ้าเข้ม (highlight) เพื่อแยกจากอำเภออื่นในจังหวัดเดียวกัน '
    'ที่ยังคงสีเขียวตามค่า NDVI เดิม ทำให้ผู้ใช้เห็นบริบทรอบข้างได้ด้วย')
if block_dist_ndvi:
    story.append(block_dist_ndvi)

# Screenshot 7.6: District LST Detail (Mae Sot)
block_dist_lst = screenshot_block(
    '07.jpg', '7.6',
    'การ Drill-Down ระดับอำเภอ — LST ของอำเภอแม่สอด',
    'หน้าจอเดียวกัน Tab "ข้อมูล" เลื่อนลงดู LST ระดับอำเภอ อุณหภูมิผิวพื้นเฉลี่ย 32.25°C '
    '(สูงกว่าค่าเฉลี่ยจังหวัด 31.18°C เนื่องจากเป็นเขตเมือง) ค่าต่ำสุด 22.07°C ค่าสูงสุด 49.93°C '
    'กราฟแท่งรายเดือนแสดงแนวโน้มร้อนขึ้นจาก ม.ค. (สีน้ำเงิน 28°C) '
    'ถึง เม.ย. (สีแดง 38°C) สะท้อนรูปแบบฤดูร้อนของไทย ที่ด้านล่างของ Sidebar '
    'มีข้อมูล NDVI ของจังหวัดตากเทียบให้ดูพร้อมกัน (0.6115) เพื่อให้เปรียบเทียบ '
    'ข้อมูลระดับจังหวัดและอำเภอได้ในมุมมองเดียว')
if block_dist_lst:
    story.append(block_dist_lst)

# Screenshot 7.7: AI Recommend - Priority Score Top 10
block4 = screenshot_block(
    '04.jpg', '7.7',
    'Tab "AI แนะนำ" — Priority Score Top 10 + Impact Projection',
    'หัวใจสำคัญของระบบ — Tab "AI แนะนำ" แสดง Priority Score ที่คำนวณจาก NDVI deficit, '
    'LST heat และความหนาแน่นประชากร (WorldPop) จุดที่ควรปลูกสูงสุด TOP 10 พร้อมพิกัด '
    'ละติจูด/ลองจิจูดและคะแนน Priority (0.53-0.47) คลิกพิกัดเปิด Google Maps เพื่อ '
    'ดูตำแหน่งจริง ส่วนล่างคำนวณผลกระทบที่คาดการณ์ — ปลูกครบทั้งพื้นที่ priority สูง '
    'จะได้ต้นไม้รวม 1,606,694 ต้น ดูดซับ CO₂ ได้ประมาณ 30,527.2 ตันต่อปี '
    '(อิงสัมประสิทธิ์ IPCC 2019)')
if block4:
    story.append(block4)

# Screenshot 7.8: Species Recommendation
block5 = screenshot_block(
    '05.jpg', '7.8',
    'Tab "AI แนะนำ" — พันธุ์ไม้แนะนำตามภูมิภาค',
    'หน้าจอเลื่อนลงต่อจากรูปที่ 7.7 แสดงพันธุ์ไม้แนะนำสำหรับภาคตะวันตก (จังหวัดตาก) '
    'คัด 5 ชนิดที่เหมาะกับสภาพภูมิอากาศและดินของภาค ได้แก่ ประดู่ป่า (Pterocarpus macrocarpus), '
    'มะขาม (Tamarindus indica), กระถินณรงค์ (Acacia auriculiformis), '
    'พะยูง (Dalbergia cochinchinensis) และตะแบกนา (Lagerstroemia floribunda) '
    'แต่ละชนิดมีข้อมูลความสูงโตเต็มที่ คุณสมบัติเด่น และเหตุผลทางนิเวศที่เหมาะกับพื้นที่')
if block5:
    story.append(block5)

# Screenshot 7.9: Timelapse Player
block6 = screenshot_block(
    '04_timelapse_player.png', '7.9',
    'ฟีเจอร์ Time-lapse — ดูพัฒนาการพื้นที่สีเขียวย้อนหลังหลายปี',
    'เมื่อกดปุ่ม Time-lapse ระบบเปิดแถบควบคุมด้านล่างของแผนที่ ผู้ใช้ลาก slider '
    'เลือกปี พ.ศ. 2563-2569 หรือกดปุ่ม Play เพื่อให้แผนที่อนิเมตการเปลี่ยนแปลง '
    'ค่า NDVI ในแต่ละปี ในภาพแสดงปี พ.ศ. 2563 ซึ่งมีข้อมูล cache เฉพาะ '
    'บางจังหวัดในภาคเหนือ ฟีเจอร์นี้ช่วยให้เห็นแนวโน้มการเสื่อมโทรมหรือฟื้นฟู '
    'ของพื้นที่สีเขียวในระยะ 10+ ปี')
if block6:
    story.append(block6)

# Screenshot 7.10: Stats Report Cover (PDF Export sample)
block7 = screenshot_block(
    '08_stats_report_cover.png', '7.10',
    'ตัวอย่าง PDF Report ที่ระบบสร้าง — หน้าปก + แผนที่ NDVI',
    'ตัวอย่างหน้า 1 ของไฟล์ PDF Report ที่ระบบ Export ออกมาจริง สำหรับจังหวัดตาก '
    'ปี พ.ศ. 2569 (ใช้ jsPDF + html2canvas สร้างฝั่ง Client) มีโครงสร้างคล้าย '
    'งานวิทยานิพนธ์ ประกอบด้วยหน้าปกระบุ "Green Area Report" + ชื่อจังหวัด '
    'ภาพประกอบ thumbnail ของประเทศไทยที่ highlight จังหวัด ตารางภาพรวม '
    '(จังหวัด/ชื่อทางการ/ปี/พื้นที่) และแผนที่ NDVI ของจังหวัดที่ render ผ่าน '
    'matplotlib พร้อม colorbar, ทิศเหนือ, scale bar และ palette อธิบายระดับสี '
    'ไฟล์ขนาดประมาณ 600 KB จำนวน 8 หน้า')
if block7:
    story.append(block7)

# Screenshot 7.11: Stats Report LST Page
block8 = screenshot_block(
    '09_stats_report_lst.png', '7.11',
    'ตัวอย่าง PDF Report — หน้า LST (Land Surface Temperature)',
    'หน้าที่ 3 ของรายงานเดียวกัน แสดงแผนที่ LST ที่ render ด้วย matplotlib '
    'พร้อม colorbar ระดับ 20-45°C (น้ำเงิน → แดง) ทิศเหนือ และ scale bar 30 km '
    'ตารางสรุปค่า LST Mean 31.2°C, Min 15.3°C, Max 48.6°C (pixel ร้อนสุด) '
    'พร้อมกราฟแท่ง LST รายเดือนปี 2569 ที่แสดงค่า median รายเดือน '
    'ม.ค.-เม.ย. (26.0°C → 38.4°C) แสดงให้เห็นรูปแบบฤดูร้อน '
    'หน้ารายงานทั้งหมดออกแบบให้พิมพ์เป็นเล่มได้ทันที')
if block8:
    story.append(block8)

# Screenshot 7.12: AI Recommend Report
block9 = screenshot_block(
    '10_recommend_report.png', '7.12',
    'ตัวอย่าง PDF Report — รายงาน AI Recommendation',
    'ไฟล์ PDF แยกต่างหากสำหรับ AI Recommendation (recommend_report_Tak.pdf) '
    'ขนาด 2 หน้า ระบุ "วิธีการวิเคราะห์" (3 ปัจจัยพร้อมน้ำหนัก: NDVI 40%, LST 30%, '
    'ประชากรหนาแน่น 30%) ตาราง Top 10 จุดที่ควรปลูกต้นไม้พร้อมพิกัด Latitude/Longitude '
    'และคะแนน Priority Score (0.531-0.498) ระดับความเร่งด่วน "เร่งด่วน/ปานกลาง" '
    'และส่วนล่างเป็นพันธุ์ไม้แนะนำ ภาคตะวันตก เริ่มจากประดู่ป่า (Pterocarpus macrocarpus) '
    'รายงานนี้ใช้ส่งให้หน่วยงานท้องถิ่นนำไปวางแผนปลูกได้ทันที')
if block9:
    story.append(block9)

# Note about remaining work
story.append(callout_box(
    'ส่วนที่กำลังพัฒนาเพิ่มเติม: '
    '(1) Heatmap Layer ของ Priority Score บนแผนที่ (ปัจจุบันแสดงแค่ Top 10 พิกัดและ '
    'รายงาน PDF — ยังไม่ overlay บนแผนที่หลัก) · '
    '(2) Tab "เปรียบเทียบ" สำหรับเปรียบเทียบ NDVI/LST ระหว่างหลายจังหวัดในกราฟเดียว · '
    '(3) Urban Subset ที่ clip ด้วย ESA WorldCover Built-up เพื่อเปรียบเทียบ WHO '
    'เฉพาะเขตเมือง · '
    '(4) ระบบ Time-lapse สำหรับ LST (ปัจจุบันรองรับเฉพาะ NDVI) · '
    '(5) การ Deploy ขึ้น Production บน Vercel และ Render พร้อมตั้งค่า CORS + Rate Limiting',
    color=COL['orange'], bg=HexColor('#fff7ed'),
))
story.append(Spacer(1, 8))


# 7.2 Techniques
story.append(sub_header('7.2 เทคนิคหรือเทคโนโลยีที่ใช้', color=COL['orange']))
story.append(Spacer(1, 4))

story.append(Paragraph(b('7.2.1 ดัชนีพืชพรรณ NDVI (Normalized Difference Vegetation Index)'),
                       S['h4']))
story.append(Paragraph(
    'NDVI เป็นดัชนีมาตรฐานที่บ่งชี้ความสมบูรณ์ของพืชพรรณ (Tucker, 1979) '
    'คำนวณจากค่าการสะท้อนของช่วงคลื่น Near-Infrared (NIR) และ Red '
    'ตามสูตรดังนี้:',
    S['p_no_indent']))
story.append(Paragraph(
    '<para align="center"><font face="Courier" size="12">'
    'NDVI = (NIR - RED) / (NIR + RED)</font></para>',
    S['p_no_indent']))
story.append(Paragraph(
    'ค่า NDVI อยู่ในช่วง -1 ถึง 1 โดยค่าใกล้ 1 หมายถึงพืชพรรณหนาแน่น '
    'ค่าใกล้ 0 หมายถึงพื้นที่โล่งหรือสิ่งปลูกสร้าง และค่าติดลบหมายถึงน้ำ '
    'ในระบบ ใช้ข้อมูล Sentinel-2 SR Harmonized โดยกำหนดเกณฑ์ NDVI '
    'มากกว่า 0.3 ว่าเป็นพื้นที่สีเขียว และ NDVI มากกว่า 0.5 ว่าเป็นป่าหนาแน่น '
    'ระบบใช้ Cloud Masking ผ่าน band QA60 เพื่อกรองภาพที่ปกคลุมด้วยเมฆออก',
    S['p']))
story.append(Spacer(1, 3))

story.append(Paragraph(b('7.2.2 อุณหภูมิผิวพื้น LST (Land Surface Temperature)'),
                       S['h4']))
story.append(Paragraph(
    'LST วัดจาก Thermal Band ของ Landsat 8 และ Landsat 9 (band ST_B10) '
    'ในระบบ Collection 2 Level 2 Science Product (USGS, 2022) แปลงเป็น '
    'องศาเซลเซียสด้วยสูตร:',
    S['p_no_indent']))
story.append(Paragraph(
    '<para align="center"><font face="Courier" size="12">'
    'LST (°C) = ST_B10 × 0.00341802 + 149.0 - 273.15</font></para>',
    S['p_no_indent']))
story.append(Paragraph(
    'ระบบใช้ Cloud Mask จาก band QA_PIXEL กรอง pixel ที่เป็นเมฆและ '
    'เงาเมฆออก กรองภาพที่มี cloud cover เกิน 40 เปอร์เซ็นต์ออกก่อนคำนวณ '
    'ค่ามัธยฐาน เพื่อให้ได้ภาพ Composite ที่สะอาดในช่วงปีที่กำหนด',
    S['p']))
story.append(Spacer(1, 3))

story.append(Paragraph(b('7.2.3 อัลกอริทึมจัดอันดับความสำคัญ (Priority Score)'),
                       S['h4']))
story.append(Paragraph(
    'นวัตกรรมหลักของโครงการคือการพัฒนา Priority Score ที่นำสามมิติของ '
    'ปัจจัยมาประกอบกัน เพื่อหาพื้นที่ที่ "ควรปลูกต้นไม้มากที่สุด" ตามสูตร:',
    S['p_no_indent']))
story.append(Paragraph(
    '<para align="center"><font face="Courier" size="11">'
    'Priority = w<sub>1</sub>·NDVI_deficit + w<sub>2</sub>·LST_heat + w<sub>3</sub>·population_need</font></para>',
    S['p_no_indent']))
story.append(Paragraph(
    'โดยค่าน้ำหนักเริ่มต้น w<sub>1</sub>=0.40, w<sub>2</sub>=0.30, w<sub>3</sub>=0.30 (ปรับได้ผ่าน UI) '
    'แต่ละมิติ Normalize เป็นช่วง [0, 1] ด้วยสูตรดังนี้:',
    S['p_no_indent']))
story.append(Paragraph(
    '• <font face="Sarabun-Bold">NDVI_deficit</font> = clamp((0.3 - NDVI) / 0.3, 0, 1) — '
    'พื้นที่ที่ NDVI ต่ำกว่า 0.3 ถือว่าขาดต้นไม้', S['li']))
story.append(Paragraph(
    '• <font face="Sarabun-Bold">LST_heat</font> = clamp((LST - 25) / 15, 0, 1) — '
    'พื้นที่ที่อุณหภูมิ 25 ถึง 40°C ถูก scale เป็น 0 ถึง 1', S['li']))
story.append(Paragraph(
    '• <font face="Sarabun-Bold">population_need</font> = clamp(ln(pop + 1) / ln(1000), 0, 1) — '
    'ใช้ log scale เนื่องจากความหนาแน่นประชากรในไทยกระจายหลาย order of magnitude', S['li']))
story.append(Paragraph(
    'หลังคำนวณ Priority image ที่ความละเอียด 100 เมตร ระบบจะ sample 2000 จุด '
    'แล้วคัดเลือก top 10 ที่มี score สูงสุดเพื่อแสดงเป็นพิกัดแนะนำ '
    'ส่วน Heatmap layer ใช้ XYZ tile ที่ render ผ่าน Google Earth Engine '
    'พร้อมจานสี (green to red) สำหรับให้ผู้ใช้เห็นภาพรวม',
    S['p']))
story.append(Spacer(1, 3))

story.append(Paragraph(b('7.2.4 ระบบแนะนำพันธุ์ไม้ตามภูมิภาค'), S['h4']))
story.append(Paragraph(
    'โครงการแบ่งประเทศไทยออกเป็น 6 ภูมิภาค (เหนือ อีสาน กลาง ตะวันออก ตะวันตก ใต้) '
    'ตามสภาพภูมิอากาศและพันธุ์ไม้พื้นถิ่น แล้วคัดเลือกพันธุ์ไม้ 5 ชนิดต่อภูมิภาค '
    '(รวม 22 ชนิดทั่วประเทศ) โดยพิจารณาจากเกณฑ์: ความทนทาน การให้ร่มเงา '
    'การฟื้นฟูดิน การให้ผลผลิต และการอนุรักษ์พันธุ์พื้นถิ่น พันธุ์ไม้แต่ละชนิด '
    'มีข้อมูลประกอบ ได้แก่ ชื่อไทย ชื่อวิทยาศาสตร์ ความสูงโตเต็มที่ '
    'จุดประสงค์การใช้งาน คุณสมบัติเด่น และเหตุผลทางนิเวศ',
    S['p']))
story.append(Spacer(1, 3))

story.append(Paragraph(b('7.2.5 การประมาณการณ์ผลกระทบ (Impact Projection)'), S['h4']))
story.append(Paragraph(
    'หลังคำนวณพื้นที่ที่มี Priority score สูงกว่าเกณฑ์ 0.5 ระบบจะประมาณการณ์ '
    'ผลกระทบเชิงปริมาณตามแนวทาง IPCC 2019 และ Bowler et al. 2010 ดังนี้:',
    S['p']))
story.append(info_table([
    ['ตัวชี้วัด', 'สูตร / ค่าอ้างอิง'],
    ['ความหนาแน่นการปลูก', '400 ต้นต่อเฮกตาร์ (FAO standard reforestation)'],
    ['CO₂ ดูดซับต่อต้นต่อปี', 'แตกต่างตามชนิด 12 ถึง 32 กก. (อิง IPCC Tier 1)'],
    ['ผลในการลดอุณหภูมิ', '−1.5°C ที่ Canopy maturity (Bowler et al. 2010)'],
    ['เทียบเท่ารถยนต์ออกถนน', 'CO₂ ตัน หารด้วย 4.6 (EPA 2023 baseline)'],
    ['ระยะเวลาเติบโต', '10 ถึง 15 ปี (เขตร้อน)'],
], col_widths=[60 * mm, 110 * mm], header_color=COL['green']))
story.append(Spacer(1, 6))

story.append(Paragraph(b('7.2.6 โครงสร้างข้อมูลและกลไกการ Cache'), S['h4']))
story.append(Paragraph(
    'ระบบใช้ฐานข้อมูล PostgreSQL ผ่าน Supabase รวม 11 ตาราง แบ่งเป็นกลุ่ม '
    'NDVI (รายปีและรายเดือน ระดับจังหวัดและอำเภอ) กลุ่ม LST รูปแบบเดียวกัน '
    'ตาราง urban_ndvi_annual สำหรับ Urban subset ตาราง planting_recommendations '
    'เก็บผล AI Recommend และ ตาราง province_population เก็บข้อมูลประชากร '
    'นอกจากนี้ Backend มี in-process TTL Cache สำหรับ Tile URL ของ Google Earth '
    'Engine (อายุ 30 นาที จุประสงค์เพื่อลดเวลา Cache Hit จาก 30 วินาที ลงเหลือต่ำกว่า 50 มิลลิวินาที)',
    S['p']))

story.append(Spacer(1, 6))


# 7.3 Tools
story.append(sub_header('7.3 เครื่องมือที่ใช้ในการพัฒนา', color=COL['orange']))
story.append(Spacer(1, 4))

story.append(Paragraph(b('ภาษาโปรแกรม'), S['h4']))
story.append(Paragraph(
    '• <font face="Sarabun-Bold">Python 3.12</font> — สำหรับ Backend API และ data pipeline', S['li']))
story.append(Paragraph(
    '• <font face="Sarabun-Bold">JavaScript ES2022</font> — สำหรับ Frontend (React 19)', S['li']))
story.append(Paragraph(
    '• <font face="Sarabun-Bold">SQL (PostgreSQL)</font> — สำหรับ Schema และ Query ฐานข้อมูล', S['li']))
story.append(Paragraph(
    '• <font face="Sarabun-Bold">Earth Engine API (JavaScript Style)</font> — สำหรับ remote sensing pipeline', S['li']))
story.append(Spacer(1, 4))

story.append(Paragraph(b('Backend Frameworks และ Libraries'), S['h4']))
story.append(info_table([
    ['Library', 'หน้าที่'],
    ['FastAPI 0.110+', 'Web framework แบบ async ที่มี OpenAPI ในตัว'],
    ['Uvicorn', 'ASGI server สำหรับ production'],
    ['earthengine-api', 'Python client ของ Google Earth Engine'],
    ['supabase-py', 'Client สำหรับเชื่อมต่อ Supabase Postgres'],
    ['matplotlib + Pillow', 'สร้าง Thumbnail แผนที่ NDVI/LST พร้อม colorbar และ legend'],
    ['slowapi', 'Rate limiting (60 requests ต่อ IP ต่อนาที)'],
    ['httpx', 'HTTP client async สำหรับเรียก thumbnail จาก GEE'],
    ['pytest', 'Test framework สำหรับ unit tests'],
], col_widths=[50 * mm, 120 * mm]))
story.append(Spacer(1, 4))

story.append(Paragraph(b('Frontend Frameworks และ Libraries'), S['h4']))
story.append(info_table([
    ['Library', 'หน้าที่'],
    ['React 19', 'UI framework หลัก'],
    ['Deck.gl 9.3', 'WebGL2 visualization สำหรับ 3D extrusion map'],
    ['MapLibre GL JS', 'Open-source basemap (positron-gl-style)'],
    ['react-map-gl', 'React wrapper สำหรับ MapLibre'],
    ['Turf.js', 'Geospatial calculations (centroid, bbox, area)'],
    ['Recharts', 'กราฟ NDVI/LST รายเดือนและรายปี'],
    ['jsPDF + html2canvas', 'สร้าง PDF Report ในฝั่ง Client'],
    ['jspdf-autotable', 'ตารางใน PDF'],
], col_widths=[50 * mm, 120 * mm]))
story.append(Spacer(1, 4))

story.append(Paragraph(b('Infrastructure และ Services'), S['h4']))
story.append(Paragraph(
    '• <font face="Sarabun-Bold">Google Earth Engine</font> — Compute platform สำหรับ remote sensing', S['li']))
story.append(Paragraph(
    '• <font face="Sarabun-Bold">Supabase</font> — Postgres + Storage + Authentication (ใช้ service role key)', S['li']))
story.append(Paragraph(
    '• <font face="Sarabun-Bold">Vercel</font> — Static hosting สำหรับ Frontend', S['li']))
story.append(Paragraph(
    '• <font face="Sarabun-Bold">Render / Railway</font> — Container hosting สำหรับ Backend', S['li']))
story.append(Paragraph(
    '• <font face="Sarabun-Bold">Git + GitHub</font> — Version control', S['li']))

story.append(Spacer(1, 4))
story.append(Paragraph(b('Development Tools'), S['h4']))
story.append(Paragraph(
    '• Visual Studio Code, PyCharm — IDE หลัก', S['li']))
story.append(Paragraph(
    '• Postman, Swagger UI — ทดสอบ API', S['li']))
story.append(Paragraph(
    '• Chrome DevTools, React DevTools — Debug Frontend', S['li']))
story.append(Paragraph(
    '• Figma — ออกแบบ UI/UX', S['li']))

story.append(Spacer(1, 6))


# 7.4 Software Specification
story.append(sub_header('7.4 รายละเอียดโปรแกรมที่จะพัฒนา (Software Specification)',
                        color=COL['orange']))
story.append(Spacer(1, 4))

story.append(Paragraph(b('7.4.1 Input Specification'), S['h4']))
story.append(info_table([
    ['Parameter', 'ชนิด', 'หมายเหตุ'],
    ['province', 'String (English)', 'ชื่อจังหวัด เช่น "Bangkok Metropolis"'],
    ['district', 'String (Optional)', 'ชื่ออำเภอ ใช้สำหรับ analysis รายอำเภอ'],
    ['year', 'Integer (2015-current)', 'ปีที่ต้องการวิเคราะห์'],
    ['start_year, end_year', 'Integer', 'ใช้สำหรับ Time-lapse และ Time-series'],
    ['w_ndvi, w_lst, w_pop', 'Float [0-1]', 'น้ำหนัก Priority Score (optional)'],
], col_widths=[40 * mm, 50 * mm, 80 * mm]))
story.append(Spacer(1, 4))

story.append(Paragraph(b('7.4.2 Output Specification'), S['h4']))
story.append(info_table([
    ['Field', 'ชนิด', 'หมายเหตุ'],
    ['ndvi_mean, ndvi_min, ndvi_max', 'Float [-1, 1]', 'สถิติ NDVI'],
    ['green_area_pct, green_area_km2', 'Float', 'พื้นที่สีเขียวเป็น % และ km²'],
    ['green_area_m2_per_person', 'Float', 'พื้นที่สีเขียวต่อคน'],
    ['who_status', 'String', 'ผ่าน/ไม่ผ่านมาตรฐาน WHO 9 m²/คน'],
    ['lst_mean, lst_min, lst_max', 'Float (°C)', 'สถิติอุณหภูมิ'],
    ['tile_url', 'String (URL)', 'XYZ tile URL ของ Heatmap'],
    ['top_locations', 'Array', '10 พิกัด (lng, lat, score) ที่ priority สูงสุด'],
    ['recommended_species', 'Object', 'พันธุ์ไม้แนะนำตามภาค (5 ชนิด)'],
    ['impact', 'Object', 'trees_total, CO₂ tonnes, equivalent cars, ΔLST'],
], col_widths=[60 * mm, 35 * mm, 75 * mm]))
story.append(Spacer(1, 6))

story.append(Paragraph(b('7.4.3 Functional Requirements'), S['h4']))
frs = [
    ('FR-01', 'คำนวณค่า NDVI รายปีและรายเดือน ระดับจังหวัดและอำเภอ'),
    ('FR-02', 'คำนวณค่า LST รายปีและรายเดือน ระดับจังหวัดและอำเภอ'),
    ('FR-03', 'แสดงแผนที่ NDVI/LST แบบ 3D extrusion ผ่าน Deck.gl'),
    ('FR-04', 'เปรียบเทียบจังหวัดได้พร้อมกันหลายจังหวัด'),
    ('FR-05', 'จัดอันดับจังหวัดตามค่าพื้นที่สีเขียวต่อคน'),
    ('FR-06', 'คำนวณ AI Priority Score และแสดงเป็น Heatmap layer'),
    ('FR-07', 'แสดง 10 พิกัดที่ควรปลูกต้นไม้มากที่สุด พร้อม priority score'),
    ('FR-08', 'แนะนำพันธุ์ไม้ตามภูมิภาค พร้อมข้อมูลประกอบและเหตุผลทางนิเวศ'),
    ('FR-09', 'ประมาณการณ์ CO₂ sequestration และ cooling effect'),
    ('FR-10', 'Time-lapse animation แสดง NDVI ย้อนหลังหลายปี'),
    ('FR-11', 'Time-series chart แสดงแนวโน้มย้อนหลัง 5 ปี'),
    ('FR-12', 'Urban Subset ที่ clip ด้วย ESA WorldCover Built-up'),
    ('FR-13', 'ส่งออก PDF Report คุณภาพระดับวิทยานิพนธ์'),
    ('FR-14', 'รองรับการปรับ Weight ของ Priority Score ผ่าน UI'),
    ('FR-15', 'Cache invalidation (admin only) ด้วย ADMIN_TOKEN'),
    ('FR-16', 'Rate limiting 60 requests ต่อ IP ต่อนาที'),
]
for fr_id, desc in frs:
    story.append(Paragraph(
        f'<font color="#1a73e8" face="Sarabun-Bold">{fr_id}:</font> {desc}',
        S['li']))
story.append(Spacer(1, 4))

story.append(Paragraph(b('7.4.4 Non-Functional Requirements'), S['h4']))
nfrs = [
    ('NFR-01 Performance', 'API response time น้อยกว่า 2 วินาที สำหรับ cache hit '
     'และไม่เกิน 60 วินาทีสำหรับ cache miss (รวมการคำนวณ GEE)'),
    ('NFR-02 Scalability', 'รองรับ concurrent users พร้อมกันอย่างน้อย 100 sessions '
     'ผ่าน Rate Limiting และ Caching layer'),
    ('NFR-03 Usability', 'UI ออกแบบให้ผู้ใช้ที่ไม่มีพื้นฐาน GIS ใช้งานได้ '
     'รองรับภาษาไทยและอังกฤษ มี Tooltip อธิบายค่า NDVI/LST'),
    ('NFR-04 Reliability', 'Cache fallback หาก GEE quota หมด, retry-on-disconnect '
     'สำหรับ Supabase, comprehensive logging ทุก endpoint'),
    ('NFR-05 Security', 'CORS configuration, Admin endpoints มี Token-based auth, '
     'service role key เก็บใน environment variables ไม่อยู่ใน source code'),
    ('NFR-06 Maintainability', 'Code separation ระหว่าง routers, helpers, '
     'และ business logic, Type-hinted Python และ Pydantic schemas, '
     'OpenAPI documentation อัตโนมัติผ่าน /docs'),
]
for title, desc in nfrs:
    story.append(Paragraph(b(title), S['h4']))
    story.append(Paragraph(desc, S['p_no_indent']))
    story.append(Spacer(1, 2))
story.append(Spacer(1, 4))

story.append(Paragraph(b('7.4.5 Design (Architecture)'), S['h4']))
story.append(Paragraph(
    'ระบบใช้ Three-tier architecture: '
    '<font face="Sarabun-Bold">Presentation Tier</font> '
    '(React 19 Single Page Application) สื่อสารกับ '
    '<font face="Sarabun-Bold">Application Tier</font> '
    '(FastAPI REST API) ที่จัดการ business logic ทั้งหมด ส่วน '
    '<font face="Sarabun-Bold">Data Tier</font> ประกอบด้วย Supabase '
    'Postgres สำหรับ cache และ Google Earth Engine สำหรับ raw remote '
    'sensing data การออกแบบเน้น loose coupling ระหว่าง tier โดยใช้ '
    'JSON over HTTPS เป็น contract ตามมาตรฐาน OpenAPI 3.0',
    S['p']))
story.append(Paragraph(
    'โครงสร้างไฟล์ของระบบจัดเป็น Monorepo ที่แยก Frontend และ Backend '
    'ออกจากกันชัดเจน แต่ละโมดูลมี responsibility ที่ชัดเจน เช่น Backend '
    'มี routers แบ่งเป็น ndvi.py / lst.py / recommend.py / maps.py '
    'helper modules เช่น gee_utils.py สำหรับ cloud masking และ '
    'dependencies.py สำหรับ Supabase client และ geometry loading',
    S['p']))

story.append(Spacer(1, 6))


# 7.5 Limitations
story.append(sub_header('7.5 ขอบเขตและข้อจำกัดของโปรแกรมที่พัฒนา',
                        color=COL['orange']))
story.append(Spacer(1, 4))

limitations = [
    ('Cloud Cover ของภาพดาวเทียม', 'ภาคใต้และพื้นที่ฝนชุก อาจมีภาพ '
     'Sentinel-2 ที่ผ่าน cloud filter น้อย ทำให้ค่า NDVI ในบางเดือน '
     'มีความไม่แน่นอนสูง ระบบจะ fallback ไปใช้ภาพที่ cloud cover '
     'ไม่เกิน 80% หากภาพคุณภาพดีกว่านี้ไม่พอ'),
    ('ความครอบคลุมของ WorldPop', 'ข้อมูลประชากร WorldPop GP/100m '
     'ของไทยปัจจุบันมีถึงปี 2021 ทำให้การเปรียบเทียบกับมาตรฐาน WHO '
     'ในปีปัจจุบันอาจคลาดเคลื่อนเล็กน้อยจาก demographic change'),
    ('GEE Quota และความเร็ว', 'การ Compute ครั้งแรกของจังหวัดหนึ่ง '
     'ใช้เวลา 30-60 วินาที (ขึ้นกับขนาดจังหวัด) ระบบจึงต้องพึ่ง cache '
     'layer อย่างหนัก รุ่น Free tier ของ GEE มี quota 25 ขอนำเข้า '
     'ต่อนาที — ระบบจึงตั้ง rate limit 60 req/min'),
    ('Priority Score เป็น Proxy ไม่ใช่ Ground Truth', 'คะแนน Priority '
     'เป็นการประมาณการณ์ที่อิง remote sensing เท่านั้น ไม่ได้พิจารณา '
     'ปัจจัยอื่น เช่น สิทธิ์การถือครองที่ดิน การใช้ประโยชน์ที่ดิน '
     'หรือข้อจำกัดทางวิศวกรรม การปลูกจริงต้องสำรวจหน้างานเพิ่ม'),
    ('Cooling Effect เป็นค่าเฉลี่ย', 'ค่า -1.5°C ที่ใช้ประมาณ ΔLST '
     'เป็นค่าเฉลี่ยจาก meta-analysis ของ Bowler et al. 2010 '
     'ในพื้นที่จริงค่า cooling จะแปรผันตามชนิดต้นไม้ ความหนาแน่น '
     'ของ canopy และ microclimate รอบข้าง'),
    ('ESA WorldCover เป็น Snapshot', 'ข้อมูล Built-up area '
     'จาก ESA WorldCover v200 เป็นภาพถ่ายปี 2021 ใช้เป็น proxy '
     'ของเขตเมืองในทุกปีที่วิเคราะห์ ทำให้ Urban Subset ของปี 2025 '
     'อาจไม่สะท้อนการขยายตัวของเมืองหลังปี 2021'),
    ('ภาษาและประเทศ', 'ระบบรองรับเฉพาะภาษาไทยและภาษาอังกฤษ '
     'และวิเคราะห์เฉพาะพื้นที่ในประเทศไทยเท่านั้น (GADM v4.1 boundaries)'),
    ('Browser Requirements', 'การแสดงแผนที่ 3D ต้องใช้ Browser '
     'ที่รองรับ WebGL2 (Chrome / Firefox / Edge รุ่นใหม่) '
     'อาจมีปัญหาบนเครื่องที่กราฟิกเก่ามาก'),
]
for title, desc in limitations:
    story.append(Paragraph(b(title), S['h4']))
    story.append(Paragraph(desc, S['p_no_indent']))
    story.append(Spacer(1, 3))

story.append(Spacer(1, 8))


# ── ข้อ 8. บรรณานุกรม ───────────────────────────────────────────────────────
story.append(header_bar('8', 'บรรณานุกรม (Bibliography)', color=COL['primary']))
story.append(Spacer(1, 6))

story.append(Paragraph(
    'บรรณานุกรมนี้รวบรวมแหล่งอ้างอิงทั้งทางวิชาการและทางเทคนิคที่ใช้ในการพัฒนาระบบ '
    'รวมทั้งสิ้น 31 รายการ (วิชาการ 23 + มาตรฐาน/เทคนิค 8) '
    'รายการเต็มพร้อม traceability ไปยังแต่ละ requirement และไฟล์โค้ดที่เกี่ยวข้อง '
    'ดูได้ใน REQUIREMENTS.md §6-7 ของโปรเจกต์', S['p_no_indent']))
story.append(Spacer(1, 6))

story.append(Paragraph(b('แหล่งอ้างอิงทางวิชาการ (Academic Sources)'), S['h4']))

refs_academic = [
    'Bowler, D. E., Buyung-Ali, L., Knight, T. M., & Pullin, A. S. (2010). '
    'Urban greening to cool towns and cities: A systematic review of the empirical '
    'evidence. Landscape and Urban Planning, 97(3), 147-155. '
    'https://doi.org/10.1016/j.landurbplan.2010.05.006',

    'Chave, J., Réjou-Méchain, M., Búrquez, A., et al. (2014). Improved allometric '
    'models to estimate the aboveground biomass of tropical trees. Global Change '
    'Biology, 20(10), 3177-3190. https://doi.org/10.1111/gcb.12629',

    'Dong, H., Tang, L., Liu, J., Hu, X., & Shao, G. (2025). Remote sensing of '
    'urban tree carbon stocks: A methodological review. ISPRS Journal of '
    'Photogrammetry and Remote Sensing, 227.',

    'Drusch, M., Del Bello, U., Carlier, S., Colin, O., et al. (2012). Sentinel-2: '
    "ESA's Optical High-Resolution Mission for GMES Operational Services. Remote "
    'Sensing of Environment, 120, 25-36. https://doi.org/10.1016/j.rse.2011.11.026',

    'Fulton, A. J., Ries, P. D., & Riley, G. E. (2025). Where Are the Benefits of '
    'Trees Needed Most? A Comparison of Equity-Based Mapping Tools in Austin, '
    'Texas. Arboriculture & Urban Forestry, 52(4). '
    'https://doi.org/10.48044/jauf.2025.020',

    'Gorelick, N., Hancher, M., Dixon, M., Ilyushchenko, S., Thau, D., & Moore, R. '
    '(2017). Google Earth Engine: Planetary-scale geospatial analysis for everyone. '
    'Remote Sensing of Environment, 202, 18-27. '
    'https://doi.org/10.1016/j.rse.2017.06.031',

    'Konijnendijk, C. C. (2023). Evidence-based guidelines for greener, healthier, '
    'more resilient neighbourhoods: Introducing the 3-30-300 rule. Journal of '
    'Forestry Research, 34, 821-830. https://doi.org/10.1007/s11676-022-01523-z',

    'Lee, J., Lim, J., Lee, J., Park, J., & Won, M. (2024). Ground-Based NDVI '
    'Network: Early Validation Practice with Sentinel-2 in South Korea. Sensors, '
    '24(6), 1892. https://doi.org/10.3390/s24061892',

    'Malakar, N. K., Hulley, G. C., Hook, S. J., Laraby, K., Cook, M., & '
    'Schott, J. R. (2018). An Operational Land Surface Temperature Product for '
    'Landsat Thermal Data: Methodology and Validation. IEEE Transactions on '
    'Geoscience and Remote Sensing, 56(10), 5717-5735. '
    'https://doi.org/10.1109/TGRS.2018.2824828',

    'Mann, H. B. (1945). Nonparametric Tests Against Trend. Econometrica, 13(3), '
    '245-259. https://www.jstor.org/stable/1907187 ; Kendall, M. G. (1975). Rank '
    'Correlation Methods (4th ed.). London: Griffin.',

    'Mehmood, K., Anees, S. A., Muhammad, S., Hussain, K., Shahzad, F., Liu, Q., '
    'Ansari, M. J., Alharbi, S. A., & Khan, W. R. (2024). Analyzing vegetation '
    'health dynamics across seasons and regions through NDVI and climatic '
    'variables. Scientific Reports, 14, 11775. '
    'https://doi.org/10.1038/s41598-024-62464-7',

    'Nyelele, C., et al. (2022). A comparison of tree planting prioritization '
    'frameworks (i-Tree Landscape vs. spatial decision support tool). Urban '
    'Forestry & Urban Greening / USDA Forest Service. '
    'https://www.fs.usda.gov/nrs/pubs/jrnl/2022/nrs_2022_nyelele_001.pdf',

    'Pasquarella, V. J., Brown, C. F., Czerwinski, W., & Rucklidge, W. J. (2023). '
    'Comprehensive Quality Assessment of Optical Satellite Imagery Using Weakly '
    'Supervised Video Learning. IEEE/CVF CVPR Workshops (EarthVision), 2125-2135. '
    'https://doi.org/10.1109/CVPRW59228.2023.00206',

    'Rouse, J. W. Jr., Haas, R. H., Schell, J. A., & Deering, D. W. (1973/1974). '
    'Monitoring Vegetation Systems in the Great Plains with ERTS. Third Earth '
    'Resources Technology Satellite-1 Symposium, NASA SP-351, 309-317. '
    'https://ntrs.nasa.gov/citations/19740022614',

    'Tatem, A. J. (2017). WorldPop, open data for spatial demography. '
    'Scientific Data, 4, 170004. https://doi.org/10.1038/sdata.2017.4',

    'A multi-objective decision support framework to prioritize tree planting '
    'locations in urban areas. (2021). Landscape and Urban Planning. '
    'https://www.sciencedirect.com/science/article/abs/pii/S0169204621001353',

    'Towards "Right Tree, Right Place" in urban environments: A systematic review '
    'of decision-support methods and tools for urban tree planting. (2026). Urban '
    'Forestry & Urban Greening. '
    'https://www.sciencedirect.com/science/article/pii/S1618866726000750',

    'Quantifying Regulating Ecosystem Services of Urban Trees using i-Tree Eco. '
    '(2024). Forests, 15(8), 1446. https://www.mdpi.com/1999-4907/15/8/1446',

    'Network-based assessment of urban forest and green space accessibility in '
    'six major cities (London, New York, Paris, Tokyo, Seoul, Beijing). (2025). '
    'Urban Forestry & Urban Greening. '
    'https://www.sciencedirect.com/science/article/abs/pii/S1618866725001153',

    'GIS-based analysis for assessing the accessibility at hierarchical levels of '
    'urban green spaces. (2016). Urban Forestry & Urban Greening. '
    'https://www.sciencedirect.com/science/article/abs/pii/S161886671630019X',

    'An Application of the Grid-Based Two-Step Floating Catchment Area Method to '
    'Assess the Spatial Accessibility of Green Spaces in Seoul, South Korea. '
    '(2026). ISPRS International Journal of Geo-Information, 15(2), 71. '
    'https://doi.org/10.3390/ijgi15020071',

    'On the Suitability of Different Satellite Land Surface Temperature Products '
    'to Study Surface Urban Heat Islands. (2024). Remote Sensing, 16(20), 3765. '
    'https://doi.org/10.3390/rs16203765',

    'The cooling effect of urban green spaces as nature-based solutions for '
    'mitigating urban heat: insights from a decade-long systematic review. '
    '(2025). Climate Risk Management, e00731.',
]
for ref in refs_academic:
    story.append(Paragraph(ref, S['ref']))

story.append(Spacer(1, 4))
story.append(Paragraph(b('แหล่งอ้างอิงด้านมาตรฐานและรายงานทางเทคนิค'), S['h4']))
refs_technical = [
    'American Forests. (2024). Tree Equity Score: Methodology. '
    'https://www.treeequityscore.org/methodology',

    'Google. Cloud Score+ S2_HARMONIZED V1 [dataset documentation]. Google Earth '
    'Engine Data Catalog. '
    'https://developers.google.com/earth-engine/datasets/catalog/'
    'GOOGLE_CLOUD_SCORE_PLUS_V1_S2_HARMONIZED',

    'Hijmans, R. J., Garcia, N., & Wieczorek, J. (2021). GADM database of Global '
    'Administrative Areas, version 4.1. University of California, Berkeley.',

    'Intergovernmental Panel on Climate Change. (2019). 2019 Refinement to the 2006 '
    'IPCC Guidelines for National Greenhouse Gas Inventories, Volume 4: Agriculture, '
    'Forestry and Other Land Use, Chapter 4: Forest Land. Geneva: IPCC.',

    'U.S. Environmental Protection Agency. (2023). Greenhouse Gas Emissions from a '
    'Typical Passenger Vehicle. EPA-420-F-23-014. Washington, D.C.: U.S. EPA.',

    'U.S. Geological Survey. (2022). Landsat 8-9 Collection 2 Level 2 Science '
    'Product Guide. Version 5.0. Sioux Falls, SD: USGS EROS Center.',

    'World Health Organization, Regional Office for Europe. (2017). Urban green '
    'spaces: a brief for action. Copenhagen: WHO Regional Office for Europe.',

    'Zanaga, D., Van De Kerchove, R., Daems, D., et al. (2022). ESA WorldCover '
    '10 m 2021 v200. Zenodo. https://doi.org/10.5281/zenodo.7254221',
]
for ref in refs_technical:
    story.append(Paragraph(ref, S['ref']))

story.append(Spacer(1, 8))


# ── ข้อ 9. ประวัติและผลงานด้านวิชาการ ────────────────────────────────────────
story.append(header_bar('9', 'ประวัติและผลงานด้านวิชาการของผู้พัฒนาโครงการ',
                        color=COL['green_deep']))
story.append(Spacer(1, 6))

story.append(Paragraph(
    'ทีมพัฒนาประกอบด้วยนิสิตชั้นปีที่ 3 สาขาวิทยาการคอมพิวเตอร์ '
    'คณะเทคโนโลยีสารสนเทศและการสื่อสาร มหาวิทยาลัยพะเยา จำนวน 3 คน '
    'มีความเชี่ยวชาญและสามารถใช้เครื่องมือพัฒนาที่จำเป็นได้ครบถ้วน',
    S['p']))

# Member 1
story.append(Paragraph(b('9.1 นาย อติชาติ ผาแสนเถิน (หัวหน้าทีม)'), S['h3']))
story.append(Paragraph(b('การศึกษา:') + ' กำลังศึกษาปริญญาตรีปีที่ 3 '
                       'สาขาวิทยาการคอมพิวเตอร์ คณะเทคโนโลยีสารสนเทศและการสื่อสาร '
                       'มหาวิทยาลัยพะเยา', S['p_no_indent']))
story.append(Paragraph(b('ทักษะหลัก:'), S['p_no_indent']))
story.append(Paragraph(
    '• Full-stack development — React 19, FastAPI, PostgreSQL', S['li']))
story.append(Paragraph(
    '• Remote Sensing และ Geospatial Analysis — Google Earth Engine, GIS', S['li']))
story.append(Paragraph(
    '• System Architecture — RESTful API design, Caching strategies, Database design', S['li']))
story.append(Paragraph(
    '• DevOps พื้นฐาน — Git, CI/CD, Deployment บน Vercel และ Render', S['li']))
story.append(Paragraph(b('บทบาทในโครงการ:'), S['p_no_indent']))
story.append(Paragraph(
    '• ออกแบบสถาปัตยกรรมระบบ และพัฒนา Backend ทั้งหมด (FastAPI + GEE Pipeline)', S['li']))
story.append(Paragraph(
    '• พัฒนา AI Priority Score algorithm และระบบแนะนำพันธุ์ไม้', S['li']))
story.append(Paragraph(
    '• ออกแบบ Database Schema สำหรับ Supabase (11 ตาราง พร้อม Cache versioning)', S['li']))
story.append(Paragraph(
    '• พัฒนาฟีเจอร์ Time-lapse และ Impact projection', S['li']))
story.append(Spacer(1, 4))

# Member 2
story.append(Paragraph(b('9.2 นาย ชยากร เตชะพัฒนาวงศ์ (ผู้ร่วมทีม)'), S['h3']))
story.append(Paragraph(b('การศึกษา:') + ' กำลังศึกษาปริญญาตรีปีที่ 3 '
                       'สาขาวิทยาการคอมพิวเตอร์ คณะเทคโนโลยีสารสนเทศและการสื่อสาร '
                       'มหาวิทยาลัยพะเยา', S['p_no_indent']))
story.append(Paragraph(b('ทักษะหลัก:'), S['p_no_indent']))
story.append(Paragraph(
    '• Backend Development — Python, FastAPI, REST API', S['li']))
story.append(Paragraph(
    '• Database Design — PostgreSQL, Schema Migration', S['li']))
story.append(Paragraph(
    '• API Testing — Postman, Pytest', S['li']))
story.append(Paragraph(b('บทบาทในโครงการ:'), S['p_no_indent']))
story.append(Paragraph(
    '• พัฒนา endpoint สำหรับ NDVI/LST monthly data', S['li']))
story.append(Paragraph(
    '• พัฒนาระบบ rate limiting และ admin authentication', S['li']))
story.append(Paragraph(
    '• ทดสอบและ optimize query ของ Supabase', S['li']))
story.append(Spacer(1, 4))

# Member 3
story.append(Paragraph(b('9.3 นาย รัชชานนท์ รัตนสุวรรณ (ผู้ร่วมทีม)'), S['h3']))
story.append(Paragraph(b('การศึกษา:') + ' กำลังศึกษาปริญญาตรีปีที่ 3 '
                       'สาขาวิทยาการคอมพิวเตอร์ คณะเทคโนโลยีสารสนเทศและการสื่อสาร '
                       'มหาวิทยาลัยพะเยา', S['p_no_indent']))
story.append(Paragraph(b('ทักษะหลัก:'), S['p_no_indent']))
story.append(Paragraph(
    '• Frontend Development — React, JavaScript ES2022, CSS', S['li']))
story.append(Paragraph(
    '• Data Visualization — Deck.gl, MapLibre GL JS, Recharts', S['li']))
story.append(Paragraph(
    '• UI/UX Design — Figma, Responsive Design', S['li']))
story.append(Paragraph(b('บทบาทในโครงการ:'), S['p_no_indent']))
story.append(Paragraph(
    '• พัฒนา UI ส่วน Sidebar, Tabs (Stats, Trend, Compare, Recommend)', S['li']))
story.append(Paragraph(
    '• พัฒนาระบบ Map Visualization ด้วย Deck.gl 3D extrusion', S['li']))
story.append(Paragraph(
    '• พัฒนาระบบ Export PDF ฝั่ง Frontend (jsPDF + html2canvas)', S['li']))
story.append(Spacer(1, 6))

# Advisor (not part of dev profile but contextual)
story.append(callout_box(
    'อาจารย์ที่ปรึกษาโครงการ: นาย ธรรมรัตน์ ธรรมา (ปริญญาโท) '
    'สังกัด มหาวิทยาลัยพะเยา · '
    'ทำหน้าที่ให้คำปรึกษาด้านวิธีวิทยา การวิเคราะห์ข้อมูล '
    'และการนำเสนอผลงาน ตลอดระยะเวลาการพัฒนาโครงการ',
    color=COL['green_deep'], bg=COL['light_green'],
))


# ── Build PDF ───────────────────────────────────────────────────────────────
out_path = os.path.join(ROOT, 'Proposal_28P14N00163_GreenAreaThailand.pdf')
doc = SimpleDocTemplate(
    out_path, pagesize=A4,
    leftMargin=20 * mm, rightMargin=20 * mm,
    topMargin=22 * mm, bottomMargin=20 * mm,
    title='ข้อเสนอโครงการ 28P14N00163 — ระบบวิเคราะห์พื้นที่สีเขียวฯ',
    author='อติชาติ ผาแสนเถิน, ชยากร เตชะพัฒนาวงศ์, รัชชานนท์ รัตนสุวรรณ',
    subject='NSC 2026 Project Proposal',
)
doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
print(f'[OK] Generated: {out_path}')
print(f'     Size: {os.path.getsize(out_path):,} bytes')
