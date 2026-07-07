"""สร้าง PDF "เล่มเดียวจบ" — รวมฉบับเล่าให้ฟัง (ภาษาคน) + ภาคผนวกเทคนิค (ตาราง/สูตร/โค้ด)
(Bibliography Complete Book) — โครงการ NSC 28P14N00163

โครงสร้าง:
  สารบัญ → ภาค ๑ บทสรุป → ภาค ๒ เล่าให้ฟัง (8 หมวด · การ์ดภาษาคน)
  → ภาค ๓ ภาคผนวกเทคนิค (สูตรจริง + ตารางค่า/โค้ด) → ภาค ๔ บรรณานุกรมเต็ม + DOI

glyph: ไม่ใช้ Courier ในเนื้อเล่าเรื่อง · ในภาคเทคนิคใช้ mono() เฉพาะ ASCII เท่านั้น
ค่าทุกตัวสอบทานจาก impact.py · scoring.py · gee_utils.py · stats_utils.py
"""
import os
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor, white
from reportlab.lib.enums import TA_LEFT, TA_JUSTIFY
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether, PageBreak,
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
    'label_bg':   HexColor('#f1f3f4'),
    'intro_bg':   HexColor('#e8f0fe'),
    'formula_bg': HexColor('#eef6ff'),
    'light_green':HexColor('#e6f4ea'),
}
STATUS = {
    'used':    ('#1e8e3e', 'ใช้จริงแล้ว',   HexColor('#e6f4ea')),
    'partial': ('#f97316', 'ใช้ไปบางส่วน',  HexColor('#fff2e6')),
    'roadmap': ('#7c3aed', 'ยังเป็นแผนอยู่', HexColor('#f3edfd')),
}
STATUS_SHORT = {'used': ('#1e8e3e', 'ใช้แล้ว'),
                'partial': ('#f97316', 'ใช้บางส่วน'),
                'roadmap': ('#7c3aed', 'แผนต่อยอด')}


def pstyle(name, font='Sarabun', size=11, color=None, leading=None,
           space_after=3, align=TA_LEFT):
    return ParagraphStyle(name=name, fontName=font, fontSize=size,
                          textColor=color or COL['text'],
                          leading=leading or size * 1.5,
                          spaceAfter=space_after, alignment=align)

S = {
    'p':      pstyle('p', size=10.5, leading=16.5, align=TA_JUSTIFY),
    'p_ni':   pstyle('p_ni', size=10.5, leading=16),
    'muted':  pstyle('muted', size=9, color=COL['muted'], leading=12.5),
    'head':   pstyle('head', size=11.5, leading=15),
    'body':   pstyle('body', size=10, leading=15.5, align=TA_JUSTIFY),
    'intro':  pstyle('intro', size=10, leading=15.5, align=TA_JUSTIFY),
    'toc':    pstyle('toc', size=10.5, leading=17),
    'toc_sub':pstyle('toc_sub', size=9.5, color=COL['muted'], leading=14.5),
    'parth':  pstyle('parth', font='Sarabun-Bold', size=17, color=COL['primary'],
                     leading=22),
    'cell':   pstyle('cell', size=8.2, leading=11),
    'cell_h': pstyle('cell_h', font='Sarabun-Bold', size=8.5, color=white, leading=11),
    'formula':pstyle('formula', size=8.8, leading=13),
    'ref':    pstyle('ref', size=9, leading=13, space_after=4),
    'callout':pstyle('callout', font='Sarabun-Bold', size=10.5, color=COL['primary'],
                     leading=15),
    'boxnum': pstyle('boxnum', font='Sarabun-Bold', size=22, align=1, leading=24),
}


def mono(t):
    return f'<font face="Courier" size="8">{t}</font>'


def bar(title, bg, size=16, pad=9):
    p = Paragraph(f'<font color="white" face="Sarabun-Bold" size="{size}">{title}</font>',
                  S['p_ni'])
    t = Table([[p]], colWidths=[170 * mm])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), bg),
        ('LEFTPADDING', (0, 0), (-1, -1), 12),
        ('TOPPADDING', (0, 0), (-1, -1), pad),
        ('BOTTOMPADDING', (0, 0), (-1, -1), pad),
    ]))
    return t


def title_bar(title):    return bar(title, COL['primary'], 16, 9)
def section_bar(title):  return bar(title, COL['green_deep'], 13, 6)


def tint_box(text, color, bg, style='intro'):
    p = Paragraph(text, S[style])
    t = Table([[p]], colWidths=[170 * mm])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), bg),
        ('LINEBEFORE', (0, 0), (0, -1), 3, color),
        ('LEFTPADDING', (0, 0), (-1, -1), 11),
        ('RIGHTPADDING', (0, 0), (-1, -1), 10),
        ('TOPPADDING', (0, 0), (-1, -1), 7),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
    ]))
    return KeepTogether([t, Spacer(1, 7)])


def section_intro(text):
    return tint_box(text, COL['primary'], COL['intro_bg'])


def stat_box(number, label, hexc, bg):
    num = Paragraph(str(number), ParagraphStyle('n', fontName='Sarabun-Bold',
                    fontSize=22, alignment=1, textColor=HexColor(hexc), leading=24))
    lbl = Paragraph(label, ParagraphStyle('l', fontName='Sarabun-Bold', fontSize=9.5,
                    alignment=1, textColor=HexColor(hexc), leading=12))
    t = Table([[num], [lbl]], colWidths=[54 * mm])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), bg),
        ('LINEABOVE', (0, 0), (-1, 0), 2.5, HexColor(hexc)),
        ('TOPPADDING', (0, 0), (-1, -1), 6), ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    return t


def story_card(rnum, name, status, blocks):
    hexc, label, bg = STATUS[status]
    head = Paragraph(
        f'<font face="Sarabun-Bold" size="11.5" color="{hexc}">[{rnum}]</font> '
        f'<font face="Sarabun-Bold" size="11.5">{name}</font>'
        f'<font face="Sarabun-Bold" size="8.5" color="{hexc}">&nbsp;&nbsp;— {label}</font>',
        S['head'])
    body = []
    for i, (lead, text) in enumerate(blocks):
        if i:
            body.append(Spacer(1, 3))
        body.append(Paragraph(
            f'<font face="Sarabun-Bold" color="#0e5c24">{lead}</font>  {text}', S['body']))
    t = Table([[head], [body]], colWidths=[170 * mm])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, 0), bg),
        ('LINEBEFORE', (0, 0), (0, -1), 3, HexColor(hexc)),
        ('BOX', (0, 0), (-1, -1), 0.5, COL['border']),
        ('LINEBELOW', (0, 0), (0, 0), 0.4, COL['border']),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 9), ('RIGHTPADDING', (0, 0), (-1, -1), 9),
        ('TOPPADDING', (0, 0), (-1, -1), 6), ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    return KeepTogether([t, Spacer(1, 8)])


def formula_box(title, lines):
    rows = [[Paragraph(f'<font face="Sarabun-Bold" color="#0e5c24" size="9.5">{title}'
                       f'</font>', S['formula'])]]
    for ln in lines:
        rows.append([Paragraph(ln, S['formula'])])
    t = Table(rows, colWidths=[170 * mm])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), COL['formula_bg']),
        ('LINEBEFORE', (0, 0), (0, -1), 3, COL['primary']),
        ('LEFTPADDING', (0, 0), (-1, -1), 10), ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 3), ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]))
    return KeepTogether([t, Spacer(1, 8)])


def tech_table(rows):
    head = [Paragraph('R#', S['cell_h']), Paragraph('อ้างอิง', S['cell_h']),
            Paragraph('ค่า/สูตร/ข้อมูลที่ใช้', S['cell_h']),
            Paragraph('จุดในโค้ด · ค่าที่ตั้ง', S['cell_h'])]
    data = [head]
    for rnum, ref, status, extracted, where in rows:
        hexc, _ = STATUS_SHORT[status]
        data.append([
            Paragraph(rnum, ParagraphStyle('rn', fontName='Sarabun-Bold', fontSize=8.2,
                                           textColor=HexColor(hexc), leading=11)),
            Paragraph(ref, S['cell']), Paragraph(extracted, S['cell']),
            Paragraph(where, S['cell'])])
    t = Table(data, colWidths=[13 * mm, 33 * mm, 74 * mm, 50 * mm], repeatRows=1)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), COL['green_deep']),
        ('GRID', (0, 0), (-1, -1), 0.4, COL['border']),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 5), ('RIGHTPADDING', (0, 0), (-1, -1), 5),
        ('TOPPADDING', (0, 0), (-1, -1), 4), ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [white, HexColor('#f8f9fa')]),
    ]))
    return t


def on_page(canvas, doc):
    canvas.saveState()
    canvas.setFont('Sarabun', 8.5)
    canvas.setFillColor(COL['muted'])
    canvas.drawString(20 * mm, 287 * mm,
                      'บรรณานุกรมฉบับสมบูรณ์ · โครงการ 28P14N00163 · NSC 2026')
    canvas.drawRightString(190 * mm, 287 * mm, 'มหาวิทยาลัยพะเยา')
    canvas.setStrokeColor(COL['border'])
    canvas.setLineWidth(0.4)
    canvas.line(20 * mm, 284 * mm, 190 * mm, 284 * mm)
    canvas.drawString(20 * mm, 12 * mm,
                      'งานวิจัยแต่ละชิ้น เราเอามาใช้ทำอะไร — เล่มรวม')
    canvas.drawRightString(190 * mm, 12 * mm, f'หน้า {doc.page}')
    canvas.line(20 * mm, 15 * mm, 190 * mm, 15 * mm)
    canvas.restoreState()


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  ข้อมูลเนื้อหา                                                            ║
# ╚══════════════════════════════════════════════════════════════════════════╝
Q1, Q2, Q3, Q4, QN = ('งานวิจัยนี้เล่าเรื่องอะไร:', 'เราหยิบอะไรของเขามา:',
                      'ไปโผล่ตรงไหนในระบบ:', 'ทำไมถึงเลือกแบบนี้:', 'เกร็ดที่ควรรู้:')

# ── ภาค ๒: เนื้อเล่าให้ฟัง (8 หมวด) ──────────────────────────────────────────
NARR = [
 ('หมวด A — การวัด "ความเขียว" (NDVI)',
  'เวลาเราบอกว่าที่ไหน "เขียว" มากน้อยแค่ไหน เราวัดด้วยตัวเลขชื่อ NDVI — คิดง่าย ๆ ว่าเป็น '
  'คะแนนความเขียวที่อ่านจากภาพดาวเทียม ยิ่งเข้าใกล้ 1 ยิ่งมีต้นไม้หนาแน่น ยิ่งเข้าใกล้ 0 '
  'ยิ่งโล่งเตียน สามชิ้นในหมวดนี้คือที่มาของ "วิธีวัด" และ "ตาที่ใช้มอง"', [
   ('R23', 'ต้นตำรับสูตรวัดความเขียว (Rouse และคณะ ปี 1973)', 'used', [
     (Q1, 'เมื่อ 50 กว่าปีก่อน นักวิจัยกลุ่มนี้ใช้ดาวเทียมยุคแรก ๆ ของ NASA คิดวิธีจับความเขียวของพืช '
      'จากภาพถ่าย โดยอาศัยว่าใบไม้สะท้อนแสงอินฟราเรด (ที่ตาเรามองไม่เห็น) ออกมาแรงมาก แต่ดูดกลืน '
      'แสงสีแดงไว้ พอเอาสองค่านี้มาเทียบกันก็รู้ว่าตรงนั้นมีพืชแค่ไหน'),
     (Q2, 'เอาสูตรมาตรง ๆ เลยครับ คือ (อินฟราเรด ลบ แดง) หารด้วย (อินฟราเรด บวก แดง) ได้ค่า NDVI'),
     (Q3, 'ทุกครั้งที่ระบบคำนวณความเขียวของจังหวัดหรืออำเภอ ก็ใช้สูตรนี้แหละ และเราตั้งเส้นไว้ว่า '
      'ถ้าคะแนนเกิน 0.3 ให้ถือว่าเป็น "พื้นที่สีเขียว"')]),
   ('R27', 'ดาวเทียมที่เป็นตาให้เรา (Sentinel-2 / Drusch ปี 2012)', 'used', [
     (Q1, 'Sentinel-2 เป็นดาวเทียมของยุโรปที่บินถ่ายภาพโลกซ้ำ ๆ ทุกไม่กี่วัน ภาพละเอียดระดับ 10 เมตร '
      '(ประมาณว่ามองเห็นของขนาดเท่าสนามบาสได้) และเปิดให้ใช้ฟรี'),
     (Q2, 'เอาตัวภาพมาใช้ และเอาความรู้ว่าช่องแสงไหนคืออินฟราเรด (เรียกว่า B8) ช่องไหนคือสีแดง (B4) '
      'เพื่อป้อนเข้าสูตร NDVI ให้ถูกช่อง'),
     (Q3, 'ระบบดึงภาพ Sentinel-2 ทั้งปีมาเฉลี่ยกันก่อนคำนวณ และคัดเฉพาะภาพที่เมฆบังไม่เกิน 80%')]),
   ('R24', 'คนที่ไปตรวจว่าดาวเทียมวัดแม่นจริงไหม (Lee และคณะ ปี 2024)', 'used', [
     (Q1, 'กลุ่มนี้ในเกาหลีเอาค่าความเขียวจาก Sentinel-2 ไปเทียบกับเครื่องวัดจริงบนพื้นดิน 8 จุด '
      'เพื่อดูว่าค่าจากฟ้ากับค่าจากพื้นตรงกันไหม'),
     (Q2, 'เราไม่ได้เอาตัวเลขมาตั้งค่า แต่เอา "ความมั่นใจ" มา — เขายืนยันว่าวิธีวัดแบบเดียวกับที่เราใช้ '
      'ให้ค่าที่เชื่อถือได้'),
     (Q3, 'ใช้เป็นหลักฐานอ้างอิงว่าการวัดความเขียวของเราไม่ได้มั่ว มีคนพิสูจน์มาแล้ว')]),
  ]),
 ('หมวด B — การวัด "ความร้อน" (LST)',
  'อีกครึ่งของเรื่องคือความร้อน เราดูอุณหภูมิผิวพื้น (พื้นถนน หลังคา พื้นดิน ร้อนแค่ไหน) จาก '
  'ดาวเทียมอีกดวงชื่อ Landsat เพื่อจับปรากฏการณ์ "เมืองร้อนกว่าชนบทรอบข้าง" หรือเกาะความร้อนเมือง', [
   ('R14', 'สูตรแปลงภาพความร้อนของ Landsat (Malakar และคณะ ปี 2018)', 'used', [
     (Q1, 'Landsat มีกล้องจับรังสีความร้อน แต่กว่าจะกลายเป็นอุณหภูมิจริงต้องผ่านการคำนวณหลายขั้น '
      'กลุ่มนี้คือคนที่ออกแบบวิธีคำนวณนั้นให้ USGS ใช้ผลิตข้อมูลอุณหภูมิสำเร็จรูป'),
     (Q2, 'เราไม่ต้องคำนวณเอง แต่ไปดึง "ชั้นข้อมูลอุณหภูมิ" ที่ผลิตด้วยวิธีของเขามาใช้ตรง ๆ'),
     (Q3, 'ระบบรวมภาพจาก Landsat 8 และ 9 คัดเฉพาะภาพเมฆน้อย แล้วอ่านชั้นอุณหภูมินี้')]),
   ('R31', 'คู่มือที่บอกวิธีเปลี่ยนตัวเลขดิบเป็นองศา (USGS ปี 2022)', 'used', [
     (Q1, 'ข้อมูลที่ดาวเทียมส่งมาเป็น "ตัวเลขดิบ" ยังไม่ใช่องศา ต้องเอาไปคูณและบวกด้วยค่าคงที่ '
      'ตามคู่มือของ USGS ก่อน ถึงจะได้อุณหภูมิจริง'),
     (Q2, 'เอาค่าคงที่มาเป๊ะ ๆ สองตัว คือ คูณด้วย 0.00341802 แล้วบวก 149 (ได้หน่วยเคลวิน) จากนั้น '
      'ลบ 273.15 เพื่อเปลี่ยนเป็นองศาเซลเซียส'),
     (Q3, 'ในไฟล์ gee_utils.py ทุกภาพความร้อนถูกแปลงด้วยขั้นตอนนี้ก่อนนำไปใช้'),
     (Q4, 'ถ้าใช้ค่าคูณผิดแม้แต่นิดเดียว อุณหภูมิจะเพี้ยนทั้งภาพ เลยต้องยึดตามคู่มืออย่างเคร่งครัด')]),
   ('R15', 'งานที่ยืนยันว่าเราเลือกข้อมูลถูกตัว (ปี 2024)', 'used', [
     (Q1, 'ทุกวันนี้มีข้อมูลอุณหภูมิจากดาวเทียมให้เลือกหลายเจ้า งานนี้เอามาเทียบกัน (ใช้เมือง Madrid '
      'กับ Paris เป็นกรณีศึกษา) ว่าแบบไหนเหมาะกับการศึกษาเกาะความร้อนเมือง'),
     (Q2, 'เอาข้อสรุปมาว่าแบบที่เราเลือก (Landsat) เหมาะกับงานลักษณะนี้'),
     (Q3, 'ใช้เป็นเหตุผลรองรับการตัดสินใจ ไม่ได้เป็นค่าตัวเลขในโค้ด')]),
  ]),
 ('หมวด C — การ "ลบเมฆ" ออกจากภาพ',
  'ปัญหาใหญ่ของภาพดาวเทียมคือเมฆบัง โดยเฉพาะบ้านเราที่ฝนเยอะ ถ้าปล่อยให้เมฆปนเข้าไป ค่าความเขียว '
  'จะเพี้ยนต่ำกว่าจริง เราเลยต้องมีตัวช่วยลบเมฆออกก่อนคำนวณ', [
   ('R12', 'ตัวช่วยลบเมฆอัจฉริยะจาก Google (Cloud Score+ / Pasquarella ปี 2023)', 'used', [
     (Q1, 'Google ฝึกปัญญาประดิษฐ์ให้ดูภาพดาวเทียมแล้วให้ "คะแนนความใส" กับทุกจุดในภาพ ตั้งแต่ 0 '
      '(เมฆทึบ) ถึง 1 (ใสแจ๋ว)'),
     (Q2, 'เอาคะแนนความใสนี้มา (เรียกว่า cs) พร้อมคำแนะนำของ Google ว่าควรตัดที่ประมาณ 0.5 ถึง 0.65'),
     (Q3, 'ระบบตัดจุดภาพที่คะแนนความใสต่ำกว่า 0.6 ทิ้ง เหลือแต่ภาพใส ๆ มาคำนวณ'),
     (QN, 'เมื่อก่อนใช้วิธีลบเมฆแบบเก่า แต่ช่วงต้นปี 2565 ถึงต้นปี 2567 ยุโรปหยุดเติมข้อมูลตัวเก่า '
      'ทำให้วิธีเดิมแทบไม่ทำงาน เลยเปลี่ยนมาใช้ตัวนี้แทน')]),
  ]),
 ('หมวด D — คะแนน "ควรไปปลูกตรงไหนก่อน" (หัวใจของระบบ)',
  'นี่คือหัวใจของระบบ เราให้คะแนนความควรปลูกกับทุกจุดบนแผนที่ แล้วชี้ 10 จุดที่ควรปลูกที่สุด '
  'คะแนนนี้รวม 4 เรื่องแล้วถ่วงน้ำหนัก: ขาดต้นไม้แค่ไหน (35%) · ร้อนแค่ไหน (25%) · คนหนาแน่นแค่ไหน '
  '(25%) · ไกลจากสีเขียวเดิมแค่ไหน (15%) ผู้ใช้ปรับน้ำหนักเองได้ และระบบจะไม่แนะนำให้ปลูกบนน้ำ '
  'อาคาร ป่าเดิม หรือที่ลาดชันเกินไป', [
   ('R3', 'แนวคิด "อย่ามองแค่ปัจจัยเดียว" (Multi-objective DSS ปี 2021)', 'used', [
     (Q1, 'งานนี้เสนอว่าเวลาจะเลือกจุดปลูกต้นไม้ในเมือง อย่าดูแค่เรื่องเดียว ให้เอาหลายเรื่องมาชั่ง '
      'น้ำหนักรวมกันเป็นคะแนนเดียว จะได้คำตอบที่รอบด้านกว่า'),
     (Q2, 'เอาวิธีคิดแบบ "รวมหลายปัจจัยแล้วถ่วงน้ำหนัก" มาเป็นแกน'),
     (Q3, 'เป็นโครงของสูตรคะแนนควรปลูกทั้งหมด อยู่ในไฟล์ scoring.py')]),
   ('R4', 'งานที่เตือนว่าต้อง "ปลูกได้จริง" ด้วย (Nyelele และคณะ ปี 2022)', 'used', [
     (Q1, 'เขาเอาเครื่องมือจัดลำดับปลูกต้นไม้หลายตัวมาเทียบกัน แล้วชี้ว่าปัจจัยสำคัญที่หลายคนลืม '
      'คือ "ตรงนั้นปลูกได้จริงหรือเปล่า"'),
     (Q2, 'เอาแนวคิดว่าต้องกรองจุดที่ปลูกไม่ได้ออกก่อน'),
     (Q3, 'ระบบตัดพื้นที่น้ำ อาคาร ป่าเดิม และที่ลาดชันเกิน 30 องศา ออกก่อนแนะนำ'),
     (QN, 'คะแนนของเรายังเป็นแค่การประเมินจากภาพถ่าย ปลูกจริงต้องลงไปสำรวจหน้างานอีกที')]),
   ('R29', 'ข้อมูลว่า "คนอยู่ตรงไหนหนาแน่น" (WorldPop / Tatem ปี 2017)', 'used', [
     (Q1, 'WorldPop เป็นฐานข้อมูลที่ประเมินว่าในแต่ละตารางขนาด 100x100 เมตร มีคนอยู่ประมาณกี่คน'),
     (Q2, 'เอาตัวเลขความหนาแน่นประชากรมาใช้'),
     (Q3, 'ยิ่งคนอยู่เยอะ ยิ่งควรได้ต้นไม้ก่อน เพราะคนได้ประโยชน์มากกว่า เราแปลงจำนวนคนเป็นคะแนน 0 ถึง 1'),
     (Q4, 'เราแปลงแบบ "ลอการิทึม" เพราะบางที่คนแน่นกว่าที่อื่นเป็นพันเท่า ถ้าใช้ตรง ๆ ที่อื่นจะถูกกลบ '
      'จนเหลือแทบเป็นศูนย์')]),
   ('R13', 'แผนที่บอกว่า "ตรงไหนเป็นอะไร" (ESA WorldCover / Zanaga ปี 2022)', 'used', [
     (Q1, 'เป็นแผนที่ทั้งโลกที่แบ่งพื้นดินออกเป็นประเภท เช่น ต้นไม้ อาคาร น้ำ ทุ่งหญ้า นาข้าว ระดับ 10 เมตร'),
     (Q2, 'เอาความรู้ว่าจุดไหนเป็นประเภทอะไรมาใช้'),
     (Q3, 'ใช้ 3 อย่าง — กันไม่ให้แนะนำปลูกบนน้ำ/อาคาร/ป่าเดิม · ใช้พื้นที่ต้นไม้เดิมเป็นหมุดวัดว่าคน '
      'อยู่ไกลสีเขียวแค่ไหน · ตัดเอาเฉพาะเขตเมืองมาเทียบเกณฑ์ WHO'),
     (QN, 'เป็นข้อมูลของปี 2564 เราใช้เป็นตัวแทนของทุกปีที่วิเคราะห์')]),
   ('R8', 'เรื่อง "ระยะเดินถึงสวน" (การเข้าถึงพื้นที่สีเขียว ปี 2025)', 'partial', [
     (Q1, 'งานนี้วัดการเข้าถึงพื้นที่สีเขียวใน 6 เมืองใหญ่ ว่าคนต้องเดินไกลแค่ไหนกว่าจะถึงสวน'),
     (Q2, 'เอาแนวคิดว่า "คนที่อยู่ไกลจากสีเขียว ควรได้ปลูกก่อน" เพื่อความเป็นธรรม'),
     (Q3, 'เราใส่ปัจจัย "ระยะห่างจากต้นไม้ใกล้สุด" เข้าไปในคะแนน (15%) ถ้าไกลเกิน 1 กิโลเมตรถือว่าขาดแคลนเต็มที่'),
     (QN, 'เราทำแบบง่ายก่อน คือวัดระยะเส้นตรง ยังไม่ใช่ระยะเดินตามถนนจริง (ดูแผนเต็มที่ R18)')]),
   ('R9', 'อีกงานเรื่องการเข้าถึงพื้นที่สีเขียว (ปี 2016)', 'partial', [
     (Q1, 'งานนี้วางวิธีวิเคราะห์การเข้าถึงพื้นที่สีเขียวแบบหลายระดับด้วยเครื่องมือแผนที่ (GIS)'),
     (Q2, 'เอามาเสริมเหตุผลของปัจจัย "ระยะห่าง" ที่เราใส่ในคะแนน'),
     (Q3, 'หนุนแนวคิดเดียวกับ R8 ส่วนวิธีเต็มรูปแบบยังอยู่ในแผน')]),
  ]),
 ('หมวด E — ดู "แนวโน้ม" ว่าดีขึ้นหรือแย่ลง',
  'ระบบดูย้อนหลังหลายปีได้ว่าความเขียวหรือความร้อนของแต่ละที่ดีขึ้นหรือแย่ลง แต่การจะฟันธงว่า '
  'เป็นแนวโน้มจริง ไม่ใช่ความบังเอิญของปีใดปีหนึ่ง ต้องอาศัยสถิติมาช่วยตัดสิน', [
   ('R17', 'วิธีทดสอบว่าแนวโน้ม "จริงหรือบังเอิญ" (Mann-Kendall ปี 1945)', 'used', [
     (Q1, 'เป็นวิธีทางสถิติเก่าแก่ตั้งแต่ปี 1945 ที่ดูว่าตัวเลขซึ่งเรียงตามเวลามีทิศทางขึ้นหรือลงจริงไหม '
      'โดยไม่ต้องสมมติว่าข้อมูลต้องเป็นเส้นตรงสวย ๆ'),
     (Q2, 'เอาตัวสูตรทดสอบมาทั้งชุด หลักคิดคือนับว่าปีหลัง ๆ มากกว่าหรือน้อยกว่าปีก่อน ๆ กี่คู่ แล้วดูว่า '
      'โดยรวมเอนไปทางไหน และเอนแรงพอจะเชื่อได้ไหม'),
     (Q3, 'ใช้บอกว่าความเขียว/ความร้อน "เพิ่มขึ้น / ลดลง / ยังไม่มีแนวโน้มชัด" ตัดสินที่ความเชื่อมั่น 95% '
      'อยู่ในไฟล์ stats_utils.py'),
     (QN, 'เราเขียนสูตรนี้เองด้วยคณิตศาสตร์พื้นฐาน ไม่ต้องพึ่งไลบรารีหนัก ๆ เลยตรวจสอบง่าย')]),
   ('R16', 'ตัวอย่างว่าคนอื่นก็ใช้วิธีนี้กับความเขียว (Mehmood และคณะ ปี 2024)', 'used', [
     (Q1, 'เป็นงานปี 2024 ที่เอาวิธี Mann-Kendall ไปดูแนวโน้มสุขภาพพืชตามฤดูกาลและภูมิภาค'),
     (Q2, 'เอามาเป็นตัวอย่างอ้างอิงว่าการใช้วิธีนี้จับแนวโน้มความเขียวเป็นเรื่องที่วงวิชาการยอมรับ'),
     (Q3, 'รูปแบบการใช้เหมือนที่ระบบเราทำ — R17 คือที่มาของสูตร ส่วน R16 คือตัวอย่างการใช้จริงกับ NDVI')]),
  ]),
 ('หมวด F — ประเมินว่า "ปลูกแล้วได้อะไรกลับมา"',
  'พอชี้จุดปลูกได้แล้ว ระบบจะประเมินต่อว่าถ้าปลูกจริงจะได้อะไร — ดูดคาร์บอนกี่ตันต่อปี เทียบเท่า '
  'เอารถออกจากถนนกี่คัน และช่วยลดความร้อนกี่องศา ตัวเลขเหล่านี้มาจากงานวิจัย 6 ชิ้นนี้', [
   ('R11', 'คู่มือระดับโลกว่าต้นไม้ดูดคาร์บอนเท่าไร (IPCC ปี 2019)', 'used', [
     (Q1, 'IPCC (คณะกรรมการเรื่องการเปลี่ยนแปลงสภาพภูมิอากาศของสหประชาชาติ) มีคู่มือกลางบอกว่า '
      'ป่าเขตร้อนสะสมคาร์บอนได้ประมาณเท่าไรต่อพื้นที่ต่อปี'),
     (Q2, 'เอาค่ากลาง ๆ ราว 3.6 ตันคาร์บอนต่อเฮกตาร์ต่อปี ซึ่งพอคิดต่อต้น (ที่ความหนาแน่น 400 ต้น/เฮกตาร์) '
      'จะได้ประมาณ 22 กิโลกรัม CO₂ ต่อต้นต่อปี'),
     (Q3, 'ในไฟล์ impact.py ใช้เป็นค่าเริ่มต้นเวลาระบบไม่รู้ว่าเป็นต้นไม้ชนิดไหน'),
     (QN, 'เป็นตัวเลขประมาณการระดับหลักการของต้นไม้โตเต็มที่ (ราว 10 ถึง 15 ปี) ไม่ใช่ค่าตายตัว')]),
   ('R25', 'สมการเดาน้ำหนักต้นไม้เขตร้อน (Chave และคณะ ปี 2014)', 'used', [
     (Q1, 'กลุ่มนี้ปรับปรุงสมการที่ใช้ประเมินมวลเนื้อไม้ของต้นไม้เขตร้อน จากขนาดลำต้น ความสูง และ '
      'ความแน่นของเนื้อไม้ ให้แม่นขึ้น'),
     (Q2, 'เอาหลักการนี้มาตั้งค่าดูดคาร์บอน "แยกตามชนิด" แทนที่จะใช้ค่ากลางตัวเดียวกับทุกต้น'),
     (Q3, 'impact.py มีตารางค่าต่อชนิด เช่น ยางนา (ต้นใหญ่) ราว 32 กิโลกรัมต่อปี · จามจุรี ราว 28 · '
      'มังคุด (ต้นเล็กกว่า) ราว 12'),
     (Q4, 'ทำให้ผลแม่นขึ้น เพราะต้นใหญ่กับต้นเล็กดูดคาร์บอนไม่เท่ากัน')]),
   ('R10', 'งานรวมหลักฐานว่าต้นไม้ทำเมืองเย็นลงแค่ไหน (Bowler และคณะ ปี 2010)', 'used', [
     (Q1, 'งานนี้รวบรวมผลการทดลองจากทั่วโลกมาสรุปว่า พื้นที่สีเขียวทำให้เย็นลงเฉลี่ยราว 1 องศา และ '
      'ถ้าร่มไม้หนา ๆ เย็นได้ถึงราว 3 องศา'),
     (Q2, 'เอาตัวเลขการลดอุณหภูมินี้มา'),
     (Q3, 'impact.py ตั้งไว้ว่าปลูกจนโตเต็มที่จะช่วยลดอุณหภูมิผิวพื้นราว 1.5 องศา'),
     (Q4, 'เราเลือกเลข 1.5 (ค่ากลาง ๆ ค่อนไปทางระวังไว้ก่อน) เพื่อไม่ให้ตัวเลขดูโม้เกินจริง')]),
   ('R26', 'ตัวช่วยเทียบ CO₂ เป็น "จำนวนรถ" (EPA ปี 2023)', 'used', [
     (Q1, 'หน่วยงานสิ่งแวดล้อมสหรัฐ (EPA) มีตัวเลขว่ารถยนต์ทั่วไปปล่อย CO₂ ราว 4.6 ตันต่อคันต่อปี'),
     (Q2, 'เอาเลข 4.6 ตันมา'),
     (Q3, 'ระบบเอาปริมาณ CO₂ ที่ต้นไม้ดูดได้ หารด้วย 4.6 เพื่อบอกว่า "เท่ากับเอารถออกจากถนนกี่คัน"'),
     (Q4, 'ช่วยให้คนทั่วไปเห็นภาพง่ายกว่าบอกเป็นตันคาร์บอนเฉย ๆ')]),
   ('R22', 'งานทบทวนวิธีนับคาร์บอนต้นไม้เมืองด้วยดาวเทียม (Dong และคณะ ปี 2025)', 'used', [
     (Q1, 'รวบรวมวิธีต่าง ๆ ที่ใช้ภาพดาวเทียมประเมินปริมาณคาร์บอนที่ต้นไม้ในเมืองเก็บไว้'),
     (Q2, 'ใช้เป็นแหล่งยืนยันว่าการประมาณคาร์บอนแบบเรามีพื้นฐานทางวิชาการรองรับ'),
     (Q3, 'หนุนความน่าเชื่อถือของการคำนวณ (เสริมค่าจาก IPCC และ Chave)')]),
   ('R19', 'งานรวมหลักฐานเรื่องความเย็น ฉบับอัปเดต (ปี 2025)', 'used', [
     (Q1, 'รวมงานวิจัยถึง 84 ชิ้น (ปี 2014 ถึง 2024) สรุปว่าพื้นที่สีเขียวช่วยลดความร้อนได้ในช่วง '
      '1 ถึง 7 องศา'),
     (Q2, 'เอาหลักฐานอัปเดตนี้มายืนยันค่าการลดความร้อน'),
     (Q3, 'ใช้เสริมและยืนยันค่าที่ได้จากงานของ Bowler อีกชั้นหนึ่ง')]),
  ]),
 ('หมวด G — มาตรฐาน เครื่องมือ และขอบเขต',
  'กลุ่มนี้คือพื้นฐานที่ทำให้ระบบทำงานได้ครอบคลุมทั้งประเทศ — เกณฑ์ที่ใช้ตัดสิน เครื่องมือที่ใช้ '
  'ประมวลผล และเส้นขอบเขตจังหวัด/อำเภอ', [
   ('R1', 'เกณฑ์ 9 ตารางเมตรต่อคน (WHO ปี 2017)', 'used', [
     (Q1, 'องค์การอนามัยโลกแนะนำว่าคนเมืองควรมีพื้นที่สีเขียวที่เข้าถึงได้อย่างน้อย 9 ตารางเมตรต่อคน'),
     (Q2, 'เอาเส้นมาตรฐาน 9 ตารางเมตรต่อคนมา'),
     (Q3, 'ระบบเทียบทุกจังหวัดกับเส้นนี้ว่า "ผ่าน" หรือ "ไม่ผ่าน"'),
     (QN, 'เป็นไม้บรรทัดหลักของทั้งระบบเลยก็ว่าได้')]),
   ('R28', 'โรงงานประมวลผลภาพดาวเทียมของ Google (Earth Engine / Gorelick ปี 2017)', 'used', [
     (Q1, 'Google Earth Engine คือระบบคลาวด์ที่เก็บภาพดาวเทียมทั้งโลกไว้ พร้อมพลังประมวลผลมหาศาล '
      'เปิดให้นักวิจัยใช้ฟรี'),
     (Q2, 'เอาทั้งภาพและพลังคำนวณมาใช้'),
     (Q3, 'การคำนวณความเขียว ความร้อน และคะแนนควรปลูก ทั้งหมดรันอยู่บน Google Earth Engine'),
     (Q4, 'ทำให้เราวิเคราะห์ได้ทั้งประเทศโดยไม่ต้องลงทุนซื้อเซิร์ฟเวอร์แพง ๆ เอง')]),
   ('R30', 'เส้นขอบจังหวัดและอำเภอ (GADM รุ่น 4.1 / Hijmans ปี 2021)', 'used', [
     (Q1, 'GADM เป็นฐานข้อมูลเส้นขอบเขตการปกครองของทั้งโลก'),
     (Q2, 'เอารูปร่างขอบเขต 77 จังหวัด 928 อำเภอของไทยมา'),
     (Q3, 'ใช้ "ตัด" ภาพดาวเทียมให้ตรงกับพื้นที่ของแต่ละจังหวัดและอำเภอ')]),
   ('R5', 'แนวคิดปลูกให้ "ถูกที่ถูกต้น" (Right Tree Right Place ปี 2026)', 'used', [
     (Q1, 'เป็นงานทบทวนวิธีและเครื่องมือช่วยเลือกพันธุ์ไม้ให้เหมาะกับพื้นที่'),
     (Q2, 'เอากรอบคิดการจับคู่ "ต้นไม้กับสภาพพื้นที่" มา'),
     (Q3, 'ระบบแนะนำพันธุ์ไม้พื้นถิ่นแยกตาม 6 ภูมิภาค (รวม 22 ชนิด) พร้อมเหตุผลทางนิเวศ อยู่ในไฟล์ species.py')]),
  ]),
 ('หมวด H — ทิศทางที่อยากต่อยอด (ยังไม่ได้ทำ)',
  'ห้าชิ้นสุดท้ายนี้เราอ้างอิงไว้เพราะเป็นทิศทางที่อยากพัฒนาต่อ แต่ขอบอกตรง ๆ ว่าตอนนี้ '
  '"ยังไม่ได้ทำ" ในระบบ เพื่อไม่ให้เข้าใจผิดว่ามีแล้ว หากถูกถามในการนำเสนอ ให้ตอบตามนี้ได้เลย', [
   ('R2', 'กฎ 3-30-300 (Konijnendijk ปี 2023)', 'roadmap', [
     (Q1, 'กฎง่าย ๆ ที่จำง่าย คือ มองจากบ้านควรเห็นต้นไม้อย่างน้อย 3 ต้น · ย่านควรมีร่มไม้ปกคลุม 30% · '
      'และควรมีสวนสาธารณะอยู่ภายในระยะ 300 เมตร'),
     (Q2, 'เอาตัวเลขเกณฑ์เหล่านี้มาเป็นเป้าหมาย'),
     (Q3, 'เป็นแผนจะเพิ่มตัวชี้วัดร่มไม้ปกคลุม 30% และสัดส่วนคนที่อยู่ใกล้สวนใน 300 เมตร — ยังไม่ได้ทำ')]),
   ('R6, R20', 'คะแนนความเป็นธรรมเรื่องต้นไม้ (Tree Equity Score / American Forests)', 'roadmap', [
     (Q1, 'ในอเมริกามีการให้คะแนนความเป็นธรรมเรื่องต้นไม้ 0 ถึง 100 ต่อย่าน โดยรวมเรื่องสังคมเข้าไป '
      'เช่น รายได้ สุขภาพ อายุ และระดับความร้อนของย่าน'),
     (Q2, 'เอาสูตรและแนวคิดการให้คะแนนแบบนี้มา'),
     (Q3, 'เป็นแผนจะคำนวณคะแนนทำนองนี้ต่ออำเภอ และเพิ่มปัจจัยความเปราะบางเข้าคะแนนควรปลูก — ยังไม่ได้ทำ'),
     (QN, 'คำว่า "equity" ที่เห็นในโค้ดตอนนี้ เป็นแค่ชื่อเรียกปัจจัยระยะห่าง ยังไม่ใช่คะแนนเต็มรูปแบบ')]),
   ('R21', 'งานเทียบเครื่องมือหา "ที่ที่ต้องการต้นไม้ที่สุด" (Fulton และคณะ ปี 2025)', 'roadmap', [
     (Q1, 'เอาเครื่องมือหลายตัวที่ใช้ชี้ว่าต้นไม้ควรไปตรงไหนที่คนต้องการมากที่สุดมาเทียบกัน โดยใช้ '
      'เมือง Austin เป็นกรณีศึกษา'),
     (Q2, 'เอาวิธีเปรียบเทียบและตรวจสอบเครื่องมือมา'),
     (Q3, 'เป็นแผนประกอบการทำคะแนนความเป็นธรรม — ยังไม่ได้ทำ')]),
   ('R7', 'โมเดลตีมูลค่าต้นไม้เต็มรูป (i-Tree Eco ปี 2024)', 'roadmap', [
     (Q1, 'i-Tree Eco เป็นเครื่องมือที่ประเมินคุณค่าของต้นไม้แบบครบ ทั้งการดูดฝุ่น (เช่น PM2.5) '
      'การช่วยลดน้ำท่วมจากฝน และตีออกมาเป็นมูลค่าเงิน'),
     (Q2, 'เอาชุดสูตรการตีมูลค่านี้มา'),
     (Q3, 'เป็นแผนจะขยายการประเมินผลกระทบให้ครอบคลุมเรื่องฝุ่น น้ำฝน และมูลค่าเงิน — ยังไม่ได้ทำ'),
     (QN, 'ที่เห็นคำว่า "ช่วยลด PM2.5" ในระบบตอนนี้ เป็นแค่คำบรรยายคุณสมบัติพันธุ์ไม้ ไม่ใช่การคำนวณจริง')]),
   ('R18', 'วิธีวัดการเข้าถึงสวนแบบละเอียด (2SFCA เมืองโซล ปี 2026)', 'roadmap', [
     (Q1, 'เป็นวิธีวัดการเข้าถึงพื้นที่สีเขียวที่ละเอียดกว่าเดิม โดยชั่งทั้งขนาดของสวนและจำนวนคนที่จะ '
      'มาใช้พร้อมกัน'),
     (Q2, 'เอาวิธีการนี้มาเป็นเป้าหมาย'),
     (Q3, 'เป็นแผนจะยกระดับปัจจัยระยะห่างที่ตอนนี้ทำแบบง่าย ให้เป็นแบบเต็มรูปแบบ — ยังไม่ได้ทำ'),
     (QN, 'พูดง่าย ๆ คือนี่เป็นเวอร์ชันเต็มของแนวคิดที่ R8 และ R9 วางไว้')]),
  ]),
]

# ── ภาค ๓: ตารางเทคนิค (ค่า/โค้ด) ────────────────────────────────────────────
TECH = [
 ('หมวด A — NDVI', [
   ('R23', 'Rouse et al. (1973/74)', 'used', 'สูตร NDVI = (NIR−Red)/(NIR+Red)',
    'ndvi/compute.py — ' + mono("normalizedDifference(['B8','B4'])")),
   ('R27', 'Drusch et al. (2012)', 'used', 'Sentinel-2: B8=NIR, B4=Red, 10 ม.',
    'ภาพ ' + mono('COPERNICUS/S2_SR_HARMONIZED')),
   ('R24', 'Lee et al. (2024)', 'used', 'validate NDVI เทียบเซนเซอร์พื้นดิน',
    'สนับสนุนเกณฑ์ NDVI มากกว่า 0.3'),
 ]),
 ('หมวด B — LST', [
   ('R14', 'Malakar et al. (2018)', 'used', 'single-channel LST → band ST_B10',
    'gee_utils.py — ' + mono('get_lst_col')),
   ('R31', 'USGS (2022)', 'used', 'scale 0.00341802, offset 149.0 K',
    'scale_lst(): คูณ 0.00341802 บวก 149.0 ลบ 273.15'),
   ('R15', '(2024) LST suitability', 'used', 'Landsat C2 ST เหมาะกับ SUHI',
    'สนับสนุนการเลือก ST_B10'),
 ]),
 ('หมวด C — Cloud masking', [
   ('R12', 'Pasquarella et al. (2023)', 'used', 'band cs (0–1); แนะนำ 0.5–0.65',
    'gee_utils.py — ' + mono('CLOUD_SCORE_PLUS') + ', cs 0.6 ขึ้นไป'),
 ]),
 ('หมวด D — Priority Score', [
   ('R3', 'Multi-objective DSS (2021)', 'used', 'ถ่วงน้ำหนักหลายปัจจัย',
    'scoring.py — 0.35·ndvi + 0.25·lst + 0.25·pop + 0.15·access'),
   ('R4', 'Nyelele et al. (2022)', 'used', 'feasibility ปลูกได้จริง',
    'plantable_mask ตัดน้ำ/อาคาร/ป่า/ลาดชันเกิน 30°'),
   ('R29', 'Tatem (2017) WorldPop', 'used', 'ประชากร 100 ม.',
    'pop_need = ln(pop+1)/ln(1000)'),
   ('R13', 'Zanaga et al. (2022) WorldCover', 'used', 'land cover 10 ม. (10=ต้นไม้ 50=อาคาร)',
    'plantable_mask · access_need · urban subset'),
   ('R8', 'Network accessibility (2025)', 'partial', 'วัดการเข้าถึงด้วยระยะทาง',
    'access_need (distance-transform, cap 1000 ม.)'),
   ('R9', 'GIS accessibility (2016)', 'partial', 'network/hierarchical',
    'เสริม access_need (ยังไม่เต็ม)'),
 ]),
 ('หมวด E — Trend', [
   ('R17', 'Mann (1945) / Kendall (1975)', 'used', 'Mann-Kendall: S, tau, z, p-value',
    'stats_utils.py — ' + mono('mann_kendall(alpha=0.05)')),
   ('R16', 'Mehmood et al. (2024)', 'used', 'precedent MK กับ NDVI',
    'timeseries — increasing/decreasing'),
 ]),
 ('หมวด F — Impact (CO₂ + Cooling)', [
   ('R11', 'IPCC (2019)', 'used', '~3.6 t C/ha/ปี → ~22 กก. CO₂/ต้น ที่ 400 ต้น/ha',
    'impact.py — ' + mono('default_kg_co2=22.0')),
   ('R25', 'Chave et al. (2014)', 'used', 'allometry pan-tropical',
    'impact.py — ' + mono('TREE_CO2_PER_YEAR') + ' 12–32 กก.'),
   ('R10', 'Bowler et al. (2010)', 'used', 'cooling เฉลี่ย ~1°C สูงสุด ~3°C',
    'impact.py — ' + mono('delta_lst_c') + ' = −1.5°C'),
   ('R26', 'U.S. EPA (2023)', 'used', 'รถ ~4.6 ตัน CO₂/คัน/ปี',
    'impact.py — ' + mono('car_co2_t_per_year=4.6')),
   ('R22', 'Dong et al. (2025)', 'used', 'ทบทวน RS carbon stock',
    'สนับสนุนการประมาณ CO₂'),
   ('R19', '(2025) Cooling review', 'used', 'สังเคราะห์ 84 งาน cooling 1–7°C',
    'เสริมค่า cooling'),
 ]),
 ('หมวด G — มาตรฐาน/แพลตฟอร์ม', [
   ('R1', 'WHO (2017)', 'used', 'เกณฑ์อย่างน้อย 9 ม²/คน', 'ranking m²/คน + urban subset'),
   ('R28', 'Gorelick et al. (2017) GEE', 'used', 'แพลตฟอร์ม planetary-scale',
    'compute backend ทุก endpoint'),
   ('R30', 'Hijmans et al. (2021) GADM', 'used', 'ขอบเขตจังหวัด/อำเภอ',
    '77 จังหวัด/928 อำเภอ (generate_districts.py)'),
   ('R5', 'Right Tree Right Place (2026)', 'used', 'เลือกพันธุ์/ตำแหน่งปลูก',
    'species.py — 6 ภูมิภาค 22 ชนิด'),
 ]),
 ('หมวด H — แผนต่อยอด (ยังไม่พัฒนา)', [
   ('R2', 'Konijnendijk (2023)', 'roadmap', 'กฎ 3-30-300', 'แผน FR-17/18'),
   ('R6, R20', 'American Forests TES', 'roadmap', 'TES = 100(1−GapScore·E), 7 ตัวแปร', 'แผน FR-21/22'),
   ('R21', 'Fulton et al. (2025)', 'roadmap', 'เทียบเครื่องมือ equity mapping', 'แผน FR-21/22'),
   ('R7', 'i-Tree Eco (2024)', 'roadmap', 'PM2.5/O₃, stormwater, มูลค่าเงิน', 'แผน FR-23/24/25'),
   ('R18', 'G2SFCA Seoul (2026)', 'roadmap', '2SFCA ถ่วง supply/demand', 'แผน FR-20'),
 ]),
]

FORMULAS = [
 formula_box('สูตร Priority Score จริงใน scoring.py (กริด ~100 ม.)', [
   '<font face="Sarabun-Bold">priority = 0.35·ndvi_deficit + 0.25·lst_heat '
   '+ 0.25·pop_need + 0.15·access_need</font>',
   'ndvi_deficit = clamp( (0.3 − NDVI) / 0.3 , 0..1 )   ยิ่ง NDVI ต่ำ = ยิ่งขาดต้นไม้',
   'lst_heat = clamp( (LST − ค่าเฉลี่ยพื้นที่) / 6.0 , 0..1 )   ร้อนกว่าเฉลี่ย +6°C = เต็ม',
   'pop_need = clamp( ln(pop+1) / ln(1000) , 0..1 )   WorldPop 100 ม. (log-scaled)',
   'access_need = clamp( ระยะถึงต้นไม้ใกล้สุด / 1000 , 0..1 )   หน่วยเมตร',
 ]),
 formula_box('สูตรประมาณการผลกระทบจริงใน impact.py', [
   'trees_total = ( plantable_area_m² / 10,000 ) · 400 ต้น/ha        [R11]',
   'annual_co2_kg = ผลรวม( จำนวนต้นแต่ละชนิด · kg CO₂ต่อต้น )     [R25/R11]  (12–32 หรือ 22)',
   'co2_expected = annual_co2 · อัตรารอด 0.80 (ช่วง 0.65–0.90)     [FAO]',
   'equivalent_cars = annual_co2_tonnes / 4.6                      [R26]',
   'ΔLST = −1.5 °C ที่เรือนยอดโตเต็มที่ (~10 ปี)                   [R10]',
 ]),
 formula_box('สูตร Mann-Kendall จริงใน stats_utils.py', [
   'S = ผลรวมของ sign(x_j − x_i) ทุกคู่ i&lt;j',
   'Var(S) = [ n(n−1)(2n+5) − ผลรวม t(t−1)(2t+5) ] / 18   (แก้ค่า tie)',
   'z = (S−1)/sqrt(Var) เมื่อ S&gt;0 ;  (S+1)/sqrt(Var) เมื่อ S&lt;0',
   'tau = S / [ n(n−1)/2 ] ;   p = 2·( 1 − CDF_ปกติ(|z|) )',
   'trend = increasing / decreasing เมื่อ p &lt; 0.05',
 ]),
]

# ── ภาค ๔: บรรณานุกรมเต็ม + DOI (R1–R31) ─────────────────────────────────────
CITATIONS = [
 ('R1', 'World Health Organization, Regional Office for Europe (2016–2017). Urban green '
  'spaces and health / Urban green spaces: a brief for action. Copenhagen: WHO Europe.'),
 ('R2', 'Konijnendijk, C.C. (2023). Evidence-based guidelines... Introducing the 3–30–300 '
  'rule. Journal of Forestry Research, 34, 821–830. doi:10.1007/s11676-022-01523-z'),
 ('R3', 'A multi-objective decision support framework to prioritize tree planting locations '
  'in urban areas. (2021). Landscape and Urban Planning.'),
 ('R4', 'Nyelele, C., et al. (2022). A comparison of tree planting prioritization frameworks. '
  'USDA Forest Service / Urban Forestry & Urban Greening.'),
 ('R5', 'Towards "Right Tree, Right Place" in urban environments: A systematic review of '
  'decision-support methods and tools. (2026). Urban Forestry & Urban Greening.'),
 ('R6', 'American Forests. Tree Equity Score — nationwide scores. '
  'https://www.americanforests.org/ · https://www.treeequityscore.org/'),
 ('R7', 'US Forest Service. i-Tree Eco. · Quantifying Regulating Ecosystem Services of Urban '
  'Trees using i-Tree Eco. Forests, 15(8), 1446 (2024).'),
 ('R8', 'Network-based assessment of urban forest and green space accessibility in six major '
  'cities. (2025). Urban Forestry & Urban Greening.'),
 ('R9', 'GIS-based analysis for assessing the accessibility at hierarchical levels of urban '
  'green spaces. (2016). Urban Forestry & Urban Greening.'),
 ('R10', 'Bowler, D.E., Buyung-Ali, L., Knight, T.M., & Pullin, A.S. (2010). Urban greening to '
  'cool towns and cities. Landscape and Urban Planning, 97(3), 147–155. '
  'doi:10.1016/j.landurbplan.2010.05.006'),
 ('R11', 'IPCC (2019). 2019 Refinement to the 2006 IPCC Guidelines, Vol.4 (AFOLU), Ch.4 '
  'Forest Land. Geneva: IPCC.'),
 ('R12', 'Pasquarella, V.J., Brown, C.F., Czerwinski, W., & Rucklidge, W.J. (2023). '
  'Comprehensive Quality Assessment of Optical Satellite Imagery Using Weakly Supervised '
  'Video Learning. IEEE/CVF CVPR Workshops, 2125–2135. doi:10.1109/CVPRW59228.2023.00206 '
  '(Cloud Score+)'),
 ('R13', 'Zanaga, D., et al. (2022). ESA WorldCover 10 m 2021 v200. Zenodo. '
  'doi:10.5281/zenodo.7254221'),
 ('R14', 'Malakar, N.K., Hulley, G.C., Hook, S.J., et al. (2018). An Operational Land Surface '
  'Temperature Product for Landsat Thermal Data. IEEE TGRS, 56(10), 5717–5735. '
  'doi:10.1109/TGRS.2018.2824828'),
 ('R15', 'On the Suitability of Different Satellite Land Surface Temperature Products to Study '
  'Surface Urban Heat Islands. (2024). Remote Sensing, 16(20), 3765. doi:10.3390/rs16203765'),
 ('R16', 'Mehmood, K., Anees, S.A., et al. (2024). Analyzing vegetation health dynamics... '
  'through NDVI and climatic variables. Scientific Reports, 14, 11775. '
  'doi:10.1038/s41598-024-62464-7'),
 ('R17', 'Mann, H.B. (1945). Nonparametric Tests Against Trend. Econometrica, 13(3), 245–259. '
  '· Kendall, M.G. (1975). Rank Correlation Methods (4th ed.). London: Griffin.'),
 ('R18', 'An Application of the Grid-Based Two-Step Floating Catchment Area Method... Green '
  'Spaces in Seoul. (2026). ISPRS IJGI, 15(2), 71. doi:10.3390/ijgi15020071'),
 ('R19', 'The cooling effect of urban green spaces as nature-based solutions... a decade-long '
  'systematic review. (2025). Climate Risk Management, e00731.'),
 ('R20', 'American Forests (2024). Tree Equity Score Methodology. '
  'https://www.treeequityscore.org/methodology'),
 ('R21', 'Fulton, A.J., Ries, P.D., & Riley, G.E. (2025). Where Are the Benefits of Trees '
  'Needed Most? A Comparison of Equity-Based Mapping Tools in Austin, Texas. Arboriculture & '
  'Urban Forestry, 52(4). doi:10.48044/jauf.2025.020'),
 ('R22', 'Dong, H., Tang, L., Liu, J., Hu, X., & Shao, G. (2025). Remote sensing of urban tree '
  'carbon stocks: A methodological review. ISPRS Journal of Photogrammetry and Remote '
  'Sensing, 227.'),
 ('R23', 'Rouse, J.W. Jr., Haas, R.H., Schell, J.A., & Deering, D.W. (1973/74). Monitoring '
  'Vegetation Systems in the Great Plains with ERTS. NASA SP-351, 309–317.'),
 ('R24', 'Lee, J., Lim, J., Lee, J., Park, J., & Won, M. (2024). Ground-Based NDVI Network: '
  'Early Validation Practice with Sentinel-2 in South Korea. Sensors, 24(6), 1892. '
  'doi:10.3390/s24061892'),
 ('R25', 'Chave, J., Réjou-Méchain, M., Búrquez, A., et al. (2014). Improved allometric models '
  'to estimate the aboveground biomass of tropical trees. Global Change Biology, 20(10), '
  '3177–3190. doi:10.1111/gcb.12629'),
 ('R26', 'U.S. Environmental Protection Agency (2023). Greenhouse Gas Emissions from a Typical '
  'Passenger Vehicle. EPA-420-F-23-014. Washington, DC: U.S. EPA.'),
 ('R27', "Drusch, M., Del Bello, U., Carlier, S., et al. (2012). Sentinel-2: ESA's Optical "
  'High-Resolution Mission for GMES. Remote Sensing of Environment, 120, 25–36. '
  'doi:10.1016/j.rse.2011.11.026'),
 ('R28', 'Gorelick, N., Hancher, M., Dixon, M., et al. (2017). Google Earth Engine: '
  'Planetary-scale geospatial analysis for everyone. Remote Sensing of Environment, 202, '
  '18–27. doi:10.1016/j.rse.2017.06.031'),
 ('R29', 'Tatem, A.J. (2017). WorldPop, open data for spatial demography. Scientific Data, 4, '
  '170004. doi:10.1038/sdata.2017.4'),
 ('R30', 'Hijmans, R.J., Garcia, N., & Wieczorek, J. (2021). GADM database of Global '
  'Administrative Areas, version 4.1. University of California, Berkeley.'),
 ('R31', 'U.S. Geological Survey (2022). Landsat 8-9 Collection 2 Level 2 Science Product '
  'Guide, v5.0. Sioux Falls, SD: USGS EROS Center.'),
]


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  ประกอบเล่ม                                                               ║
# ╚══════════════════════════════════════════════════════════════════════════╝
story = []

# ── หน้าปก + สารบัญ ──
story.append(title_bar('งานวิจัยแต่ละชิ้น เราเอามาใช้ทำอะไร — ฉบับสมบูรณ์'))
story.append(Spacer(1, 4))
story.append(Paragraph(
    'ระบบวิเคราะห์พื้นที่สีเขียวและแนะนำพื้นที่ปลูกต้นไม้อัจฉริยะของประเทศไทย · '
    'โครงการ NSC 28P14N00163 · จัดทำ 6 กรกฎาคม 2569', S['muted']))
story.append(Spacer(1, 8))
story.append(tint_box(
    'เล่มนี้รวมทุกมุมมองของบรรณานุกรมไว้ในที่เดียว: เริ่มจากบทสรุปสั้น ๆ ว่าอ้างอิงทั้ง 31 รายการ '
    'เกี่ยวข้องกับระบบอย่างไร ตามด้วยคำอธิบาย "ภาษาคน" ทีละชิ้น (เหมาะสำหรับอ่านทำความเข้าใจหรือ '
    'นำเสนอปากเปล่า) แล้วปิดท้ายด้วยภาคเทคนิค (สูตร/ค่า/โค้ดจริง) และบรรณานุกรมเต็มพร้อม DOI '
    'สำหรับผู้อ่านสายวิชาการ', COL['green'], COL['light_green']))
story.append(Spacer(1, 6))
story.append(Paragraph('<font face="Sarabun-Bold" size="13" color="#1a73e8">สารบัญ</font>',
                       S['p_ni']))
story.append(Spacer(1, 4))
toc = [
    ('ภาค ๑', 'บทสรุป — ภาพรวมและสถานะการใช้งาน'),
    ('ภาค ๒', 'เล่าให้ฟัง (ภาษาคน) — 8 หมวด · 31 อ้างอิง'),
    ('ภาค ๓', 'ภาคผนวกเทคนิค — สูตรจริง + ตารางค่า/โค้ด'),
    ('ภาค ๔', 'บรรณานุกรมเต็ม + DOI (R1–R31)'),
]
for part, desc in toc:
    story.append(Paragraph(
        f'<font face="Sarabun-Bold" color="#1a73e8">{part}</font>&nbsp;&nbsp;{desc}', S['toc']))
story.append(Paragraph(
    '<font color="#5f6368">หมวดในภาค ๒–๓: A ความเขียว · B ความร้อน · C ลบเมฆ · '
    'D คะแนนควรปลูก · E แนวโน้ม · F ผลกระทบ · G มาตรฐาน · H แผนต่อยอด</font>', S['toc_sub']))
story.append(PageBreak())

# ── ภาค ๑ บทสรุป ──
story.append(Paragraph('ภาค ๑ — บทสรุป', S['parth']))
story.append(Spacer(1, 6))
story.append(tint_box(
    'ผลการตรวจ: บรรณานุกรมทั้ง 31 รายการเกี่ยวข้องกับระบบทั้งหมด ไม่มีรายการใดหลุดออกนอกขอบเขตงาน '
    'และทุกรายการมี traceability ไปยัง requirement ที่ชัดเจน ความเกี่ยวข้องแบ่งเป็น 3 ระดับ '
    'ตามการนำไปใช้จริงในโค้ด', COL['green'], COL['light_green'], style='callout'))
story.append(Spacer(1, 6))
boxes = Table([[
    stat_box(24, 'ใช้จริงแล้ว (กลุ่ม A)', '#1e8e3e', COL['light_green']),
    stat_box(2, 'ใช้ไปบางส่วน', '#f97316', HexColor('#fff2e6')),
    stat_box(5, 'ยังเป็นแผนอยู่ (กลุ่ม B)', '#7c3aed', HexColor('#f3edfd')),
]], colWidths=[56 * mm, 56 * mm, 56 * mm])
boxes.setStyle(TableStyle([('LEFTPADDING', (0, 0), (-1, -1), 2),
                           ('RIGHTPADDING', (0, 0), (-1, -1), 2),
                           ('VALIGN', (0, 0), (-1, -1), 'MIDDLE')]))
story.append(boxes)
story.append(Spacer(1, 8))
story.append(Paragraph(
    'วิธีอ่านเล่มนี้: ภาค ๒ เล่าแต่ละงานวิจัยด้วยภาษาคน 4 คำถาม (เล่าเรื่องอะไร · หยิบอะไรมา · '
    'ไปโผล่ตรงไหน · ทำไมเลือกแบบนี้) · ภาค ๓ ให้ค่าตัวเลข/สูตร/ตำแหน่งในโค้ดแบบกระชับ · '
    'ภาค ๔ คือรายการอ้างอิงเต็มพร้อม DOI', S['p']))
story.append(PageBreak())

# ── ภาค ๒ เล่าให้ฟัง ──
story.append(Paragraph('ภาค ๒ — เล่าให้ฟัง (ภาษาคน)', S['parth']))
story.append(Spacer(1, 6))
for sec_title, sec_intro, cards in NARR:
    story.append(KeepTogether([section_bar(sec_title), Spacer(1, 6)]))
    story.append(section_intro(sec_intro))
    for rnum, name, status, blocks in cards:
        story.append(story_card(rnum, name, status, blocks))
    story.append(Spacer(1, 4))
story.append(PageBreak())

# ── ภาค ๓ ภาคผนวกเทคนิค ──
story.append(Paragraph('ภาค ๓ — ภาคผนวกเทคนิค (สูตร · ค่า · โค้ด)', S['parth']))
story.append(Spacer(1, 6))
story.append(Paragraph('สูตรหลักของระบบ (ค่าจริงจากไฟล์โค้ด)', ParagraphStyle(
    'sf', fontName='Sarabun-Bold', fontSize=12, textColor=COL['green_deep'], leading=16)))
story.append(Spacer(1, 4))
for f in FORMULAS:
    story.append(f)
story.append(Spacer(1, 4))
story.append(Paragraph('ตารางสรุป: เอาค่า/ข้อมูลอะไรไปใช้ตรงไหน (แยกตามหมวด)', ParagraphStyle(
    'st', fontName='Sarabun-Bold', fontSize=12, textColor=COL['green_deep'], leading=16)))
story.append(Spacer(1, 5))
for mod_title, rows in TECH:
    story.append(Paragraph(f'<font face="Sarabun-Bold" color="#0e5c24">{mod_title}</font>',
                           S['p_ni']))
    story.append(Spacer(1, 3))
    story.append(tech_table(rows))
    story.append(Spacer(1, 8))
story.append(PageBreak())

# ── ภาค ๔ บรรณานุกรมเต็ม ──
story.append(Paragraph('ภาค ๔ — บรรณานุกรมเต็ม (R1–R31 พร้อม DOI)', S['parth']))
story.append(Spacer(1, 6))
story.append(Paragraph(
    'รายการเดียวกับ REQUIREMENTS.md §7 ของโปรเจกต์ · บางรายการที่ยังไม่ทราบชื่อผู้แต่ง/เลขหน้า '
    'ครบ ให้เปิดลิงก์ DOI ยืนยันก่อนลงบรรณานุกรมฉบับสมบูรณ์', S['muted']))
story.append(Spacer(1, 6))
for rnum, cite in CITATIONS:
    story.append(Paragraph(
        f'<font face="Sarabun-Bold" color="#1a73e8">[{rnum}]</font> {cite}', S['ref']))

story.append(Spacer(1, 10))
story.append(Paragraph(
    'เอกสารนี้เป็นฉบับรวมเล่มเดียวจบ · เอกสารต้นทางในโปรเจกต์: REQUIREMENTS.md §6–7 · '
    'บรรณานุกรมในเล่มข้อเสนอ: Proposal_28P14N00163_GreenAreaThailand.pdf ข้อ 8', S['muted']))


out_path = os.path.join(ROOT, 'Bibliography_Complete_Book.pdf')
doc = SimpleDocTemplate(
    out_path, pagesize=A4,
    leftMargin=20 * mm, rightMargin=20 * mm, topMargin=22 * mm, bottomMargin=20 * mm,
    title='บรรณานุกรมฉบับสมบูรณ์ (รวมเล่มเดียว) — 28P14N00163',
    author='อติชาติ ผาแสนเถิน',
    subject='Bibliography Complete Book — NSC 2026',
)
doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
print(f'[OK] Generated: {out_path}')
print(f'     Size: {os.path.getsize(out_path):,} bytes')
