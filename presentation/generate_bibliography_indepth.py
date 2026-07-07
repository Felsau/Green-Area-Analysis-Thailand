"""สร้าง PDF เชิงลึกหลายหน้า — การ์ดต่อ 1 อ้างอิง (31 รายการ)
(Bibliography In-Depth Dossier) — โครงการ NSC 28P14N00163

แต่ละการ์ด: citation เต็ม + DOI · เอาอะไรมาใช้ · จากงานวิจัยส่วนไหน ·
ใช้ตรงไหนในโค้ด (พร้อม snippet) · หมายเหตุ/เหตุผล
คั่นแต่ละโมดูลด้วยกล่องสูตรจริง (Priority Score / Impact / Mann-Kendall)

ข้อควรระวัง glyph: ฟอนต์ Courier (builtin) มีเฉพาะ Latin → ใส่ ASCII เท่านั้นใน mono()
ตัวอักษรพิเศษ (− ² ₂ ° · ~) ให้อยู่ในฟอนต์ Sarabun ซึ่งรองรับครบ
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
    'label_bg':   HexColor('#f1f3f4'),
    'formula_bg': HexColor('#eef6ff'),
    'light_green':HexColor('#e6f4ea'),
}

# status → (hex สำหรับ font tag, ป้าย, สีพื้นหัวการ์ด)
STATUS = {
    'used':    ('#1e8e3e', 'ใช้แล้ว',      HexColor('#e6f4ea')),
    'partial': ('#f97316', 'ใช้บางส่วน',   HexColor('#fff2e6')),
    'roadmap': ('#7c3aed', 'แผนต่อยอด',    HexColor('#f3edfd')),
}


def pstyle(name, font='Sarabun', size=11, color=None, leading=None,
           space_after=3, align=TA_LEFT):
    return ParagraphStyle(name=name, fontName=font, fontSize=size,
                          textColor=color or COL['text'],
                          leading=leading or size * 1.5,
                          spaceAfter=space_after, alignment=align)

S = {
    'p':       pstyle('p', size=10.5, leading=16, align=TA_JUSTIFY),
    'p_ni':    pstyle('p_ni', size=10.5, leading=16),
    'muted':   pstyle('muted', size=9, color=COL['muted'], leading=12.5),
    'head':    pstyle('head', size=11.3, leading=15),
    'flabel':  pstyle('flabel', font='Sarabun-Bold', size=8.6, color=COL['muted'],
                      leading=11.5),
    'fbody':   pstyle('fbody', size=9.2, leading=13, align=TA_JUSTIFY),
    'formula': pstyle('formula', size=8.8, leading=13),
    'toc':     pstyle('toc', size=9.5, leading=15),
}


def mono(t):
    """โค้ด — Courier เขียวเข้ม · ใส่ ASCII เท่านั้น (Courier builtin ไม่มี glyph พิเศษ)"""
    return f'<font face="Courier" size="8">{t}</font>'


def section_bar(title):
    p = Paragraph(f'<font color="white" face="Sarabun-Bold" size="13">{title}</font>',
                  S['p_ni'])
    t = Table([[p]], colWidths=[170 * mm])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), COL['green_deep']),
        ('LEFTPADDING', (0, 0), (-1, -1), 10),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    return t


def title_bar(title):
    p = Paragraph(f'<font color="white" face="Sarabun-Bold" size="16">{title}</font>',
                  S['p_ni'])
    t = Table([[p]], colWidths=[170 * mm])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), COL['primary']),
        ('LEFTPADDING', (0, 0), (-1, -1), 12),
        ('TOPPADDING', (0, 0), (-1, -1), 9),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 9),
    ]))
    return t


def formula_box(title, lines):
    rows = [[Paragraph(f'<font face="Sarabun-Bold" color="#0e5c24" size="9.5">'
                       f'{title}</font>', S['fbody'])]]
    for ln in lines:
        rows.append([Paragraph(ln, S['formula'])])
    t = Table(rows, colWidths=[170 * mm])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), COL['formula_bg']),
        ('LINEBEFORE', (0, 0), (0, -1), 3, COL['primary']),
        ('LEFTPADDING', (0, 0), (-1, -1), 10),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]))
    return KeepTogether([t, Spacer(1, 8)])


def ref_card(rnum, name, status, citation, extracted, source_part, used_in, note=None):
    hexc, label, bg = STATUS[status]
    head = Paragraph(
        f'<font face="Sarabun-Bold" size="11.5" color="{hexc}">[{rnum}]</font> '
        f'<font face="Sarabun-Bold" size="11.5">{name}</font>'
        f'<font face="Sarabun-Bold" size="8.5" color="{hexc}">'
        f'&nbsp;&nbsp;·&nbsp;&nbsp;{label}</font>',
        S['head'])

    def field(lbl, content):
        body = content if hasattr(content, 'wrap') else Paragraph(content, S['fbody'])
        return [Paragraph(lbl, S['flabel']), body]

    rows = [[head, '']]
    rows.append(field('อ้างอิง', citation))
    rows.append(field('เอาอะไรมาใช้', extracted))
    rows.append(field('จากงานวิจัยส่วนไหน', source_part))
    rows.append(field('ใช้ตรงไหนในระบบ', used_in))
    if note:
        rows.append(field('หมายเหตุ / เหตุผล', note))

    t = Table(rows, colWidths=[30 * mm, 140 * mm])
    t.setStyle(TableStyle([
        ('SPAN', (0, 0), (1, 0)),
        ('BACKGROUND', (0, 0), (1, 0), bg),
        ('BACKGROUND', (0, 1), (0, -1), COL['label_bg']),
        ('LINEBEFORE', (0, 0), (0, -1), 3, HexColor(hexc)),
        ('BOX', (0, 0), (-1, -1), 0.5, COL['border']),
        ('INNERGRID', (0, 1), (-1, -1), 0.3, COL['border']),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 7),
        ('RIGHTPADDING', (0, 0), (-1, -1), 7),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    return KeepTogether([t, Spacer(1, 7)])


def on_page(canvas, doc):
    canvas.saveState()
    canvas.setFont('Sarabun', 8.5)
    canvas.setFillColor(COL['muted'])
    canvas.drawString(20 * mm, 287 * mm,
                      'Bibliography In-Depth Dossier · โครงการ 28P14N00163 · NSC 2026')
    canvas.drawRightString(190 * mm, 287 * mm, 'มหาวิทยาลัยพะเยา')
    canvas.setStrokeColor(COL['border'])
    canvas.setLineWidth(0.4)
    canvas.line(20 * mm, 284 * mm, 190 * mm, 284 * mm)
    canvas.drawString(20 * mm, 12 * mm,
                      'รายละเอียดเชิงลึก: การนำงานวิจัยแต่ละชิ้นมาใช้ในระบบ')
    canvas.drawRightString(190 * mm, 12 * mm, f'หน้า {doc.page}')
    canvas.line(20 * mm, 15 * mm, 190 * mm, 15 * mm)
    canvas.restoreState()


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  DATA — 8 โมดูล · 31 การ์ด                                                ║
# ╚══════════════════════════════════════════════════════════════════════════╝
PRIORITY_FORMULA = formula_box('สูตร Priority Score จริงใน scoring.py (กริด ~100 ม.)', [
    '<font face="Sarabun-Bold">priority = 0.35·ndvi_deficit + 0.25·lst_heat '
    '+ 0.25·pop_need + 0.15·access_need</font>',
    'ndvi_deficit = clamp( (0.3 − NDVI) / 0.3 , 0..1 )   ยิ่ง NDVI ต่ำ = ยิ่งขาดต้นไม้',
    'lst_heat&nbsp;&nbsp;&nbsp;&nbsp; = clamp( (LST − ค่าเฉลี่ยพื้นที่) / 6.0 , 0..1 )   '
    'ร้อนกว่าเฉลี่ย +6°C = เต็ม',
    'pop_need&nbsp;&nbsp;&nbsp;&nbsp; = clamp( ln(pop+1) / ln(1000) , 0..1 )   '
    'WorldPop 100 ม. (log-scaled)',
    'access_need&nbsp; = clamp( ระยะถึงต้นไม้ใกล้สุด / 1000 , 0..1 )   หน่วยเมตร',
    '<font color="#5f6368">น้ำหนักปรับได้ผ่าน UI แล้ว normalize ให้รวม = 1.0 · '
    'กรองจุดแนะนำด้วย plantable_mask (ตัดน้ำ/อาคาร/ป่าเดิม/ลาดชันเกิน 30°)</font>',
])

IMPACT_FORMULA = formula_box('สูตรประมาณการผลกระทบจริงใน impact.py', [
    'trees_total&nbsp;&nbsp; = ( plantable_area_m² / 10,000 ) · 400 ต้น/ha        [R11 density]',
    'annual_co2_kg = ผลรวม( จำนวนต้นแต่ละชนิด · kg CO₂ต่อต้น )                [R25 / R11]',
    '&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;'
    'kg CO₂ต่อต้น = 12–32 (ตามชนิด) หรือ 22 (ค่า default IPCC)',
    'co2_expected&nbsp; = annual_co2 · อัตรารอด 0.80 (ช่วง 0.65–0.90)          [FAO]',
    'equivalent_cars = annual_co2_tonnes / 4.6                              [R26]',
    'ΔLST&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; = −1.5 °C ที่เรือนยอด'
    'โตเต็มที่ (~10 ปี)                        [R10]',
])

MANNKENDALL_FORMULA = formula_box('สูตร Mann-Kendall trend test จริงใน stats_utils.py', [
    'S&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; = ผลรวมของ sign(x_j − x_i) ทุกคู่ i&lt;j',
    'Var(S) = [ n(n−1)(2n+5) − ผลรวม t(t−1)(2t+5) ] / 18   (แก้ค่า tie)',
    'z&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; = (S−1)/sqrt(Var) เมื่อ S&gt;0 ;  (S+1)/sqrt(Var) เมื่อ S&lt;0',
    'tau&nbsp;&nbsp;&nbsp; = S / [ n(n−1)/2 ] ;   p = 2·( 1 − CDF_ปกติ(|z|) )',
    'trend = increasing / decreasing เมื่อ p &lt; 0.05 (alpha) · ต้องมีอย่างน้อย 3 จุด',
])

MODULES = [
 ('A. ข้อมูลพืชพรรณ (NDVI) — Sentinel-2', None, [
   ref_card('R23', 'Rouse et al. (1973/74)', 'used',
     'Rouse, J.W. Jr., Haas, R.H., Schell, J.A., & Deering, D.W. (1973/74). '
     'Monitoring Vegetation Systems in the Great Plains with ERTS. NASA SP-351, '
     '309–317.',
     'สูตร NDVI = (NIR − Red) / (NIR + Red) ซึ่งเป็นดัชนีพืชพรรณต้นตำรับ',
     'จากบทความที่นิยาม normalized difference vegetation index ครั้งแรก '
     '(งานติดตามพืชพรรณทุ่งหญ้าด้วยดาวเทียม ERTS-1)',
     'ndvi/compute.py คำนวณตรงด้วย ' + mono("normalizedDifference(['B8','B4'])") +
     ' บนภาพ median รายปี',
     'เกณฑ์ NDVI มากกว่า 0.3 = "พื้นที่สีเขียว" ที่ระบบใช้ตัดสิน green area %'),
   ref_card('R27', 'Drusch et al. (2012) — Sentinel-2', 'used',
     "Drusch, M., Del Bello, U., Carlier, S., Colin, O., et al. (2012). Sentinel-2: "
     "ESA's Optical High-Resolution Mission for GMES. Remote Sensing of Environment, "
     '120, 25–36. doi:10.1016/j.rse.2011.11.026',
     'คุณสมบัติเซนเซอร์ MSI: band B8 = ช่วงคลื่นใกล้อินฟราเรด (NIR), '
     'B4 = สีแดง (Red), ความละเอียดเชิงพื้นที่ 10 เมตร',
     'จากส่วนสเปกของภารกิจ (spectral bands + spatial resolution) ที่กำหนดว่าจะเอา '
     'แบนด์ไหนมาเข้าสูตร NDVI',
     'ใช้คลัง ' + mono('COPERNICUS/S2_SR_HARMONIZED') + ' บน GEE, filter '
     + mono('CLOUDY_PIXEL_PERCENTAGE < 80') + ' ก่อนทำ median',
     None),
   ref_card('R24', 'Lee et al. (2024)', 'used',
     'Lee, J., Lim, J., Lee, J., Park, J., & Won, M. (2024). Ground-Based NDVI '
     'Network: Early Validation Practice with Sentinel-2 in South Korea. Sensors, '
     '24(6), 1892. doi:10.3390/s24061892',
     'หลักฐานยืนยันความแม่นยำของค่า NDVI ที่คำนวณจาก Sentinel-2 (B8/B4)',
     'จากผลการ validate เทียบ NDVI ดาวเทียมกับเซนเซอร์ภาคพื้นดิน 8 สถานี',
     'ใช้เป็นหลักฐานสนับสนุนความน่าเชื่อถือของสูตร/แบนด์ที่ระบบเลือก '
     '(ไม่ได้ตั้งเป็นค่าคงที่)',
     'ชุดข้อมูลเดียวกัน (Sentinel-2, B8/B4) กับที่ระบบใช้ → อ้างอิงตรงบริบท'),
 ]),
 ('B. อุณหภูมิผิวพื้น (LST) — Landsat 8/9', None, [
   ref_card('R14', 'Malakar et al. (2018)', 'used',
     'Malakar, N.K., Hulley, G.C., Hook, S.J., Laraby, K., Cook, M., & Schott, J.R. '
     '(2018). An Operational Land Surface Temperature Product for Landsat Thermal '
     'Data. IEEE TGRS, 56(10), 5717–5735. doi:10.1109/TGRS.2018.2824828',
     'อัลกอริทึม single-channel ที่ USGS ใช้ผลิต band ST_B10 (Surface Temperature) '
     'ของ Landsat Collection 2 Level-2',
     'จากส่วน methodology + validation ของ operational LST product (ระบบไม่ได้ '
     'คำนวณ LST เอง แต่ดึงผลลัพธ์ ST_B10 ที่ผลิตด้วยวิธีนี้มาใช้)',
     'gee_utils.py — ' + mono('get_lst_col') + ' รวม ' + mono('LANDSAT/LC08/C02/T1_L2')
     + ' + ' + mono('LC09') + ', filter ' + mono('CLOUD_COVER < 40'),
     None),
   ref_card('R31', 'USGS (2022) Product Guide', 'used',
     'U.S. Geological Survey (2022). Landsat 8-9 Collection 2 Level 2 Science '
     'Product Guide, v5.0. Sioux Falls, SD: USGS EROS Center.',
     'ค่าคงที่สเกลของ band ST_B10: multiplicative scale 0.00341802 และ '
     'additive offset 149.0 เคลวิน',
     'จากตารางสเกล/ออฟเซ็ตของ Collection 2 Level-2 product (แปลง digital number '
     'เป็นอุณหภูมิจริง)',
     'gee_utils.py — ' + mono('scale_lst()') + ': ST_B10 คูณ 0.00341802 บวก 149.0 '
     'ลบ 273.15 = °C · mask เมฆด้วย ' + mono('QA_PIXEL') + ' bit 3,4',
     'ค่าตายตัวจากเอกสาร USGS โดยตรง — หากใช้ผิดสเกล อุณหภูมิจะคลาดทั้งภาพ'),
   ref_card('R15', '(2024) Suitability of satellite LST products', 'used',
     'On the Suitability of Different Satellite Land Surface Temperature Products '
     'to Study Surface Urban Heat Islands. (2024). Remote Sensing, 16(20), 3765. '
     'doi:10.3390/rs16203765',
     'ข้อสรุปว่าผลิตภัณฑ์ Landsat Collection 2 ST เหมาะกับการศึกษา Surface UHI',
     'จากผลเปรียบเทียบผลิตภัณฑ์ LST 5 แบบ (กรณีศึกษา Madrid/Paris)',
     'สนับสนุนการตัดสินใจเลือก ST_B10 มาวิเคราะห์เกาะความร้อน (UHI risk)',
     None),
 ]),
 ('C. การกรองเมฆ (Cloud Masking)', None, [
   ref_card('R12', 'Pasquarella et al. (2023) — Cloud Score+', 'used',
     'Pasquarella, V.J., Brown, C.F., Czerwinski, W., & Rucklidge, W.J. (2023). '
     'Comprehensive Quality Assessment of Optical Satellite Imagery Using Weakly '
     'Supervised Video Learning. IEEE/CVF CVPR Workshops (EarthVision), 2125–2135. '
     'doi:10.1109/CVPRW59228.2023.00206',
     'band ' + mono('cs') + ' (คะแนนความใสต่อ pixel 0–1) และ threshold ที่ Google '
     'แนะนำ 0.5–0.65',
     'จากโมเดล Cloud Score+ (weakly-supervised video learning) และคู่มือ dataset',
     'gee_utils.py — link ' + mono('GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED') +
     ', mask pixel ที่ cs น้อยกว่า 0.6 ทิ้ง (เลือก 0.6 กลางช่วงที่แนะนำ)',
     'แทน QA60 เดิม — ESA หยุดเติม QA60 ช่วง ม.ค.2022–ก.พ.2024 ทำให้ mask '
     'กลายเป็น no-op เมฆปนเข้า median'),
 ]),
 ('D. คะแนนความสำคัญพื้นที่ปลูก (AI Priority Score)', [PRIORITY_FORMULA], [
   ref_card('R3', 'Multi-objective DSS (2021)', 'used',
     'A multi-objective decision support framework to prioritize tree planting '
     'locations in urban areas. (2021). Landscape and Urban Planning.',
     'แนวคิดการถ่วงน้ำหนักหลายวัตถุประสงค์ (multi-objective weighting) เพื่อจัด '
     'ลำดับพื้นที่ควรปลูก',
     'จากกรอบ decision-support ที่รวมหลายปัจจัยเป็นคะแนนเดียว',
     'scoring.py — priority = 0.35·ndvi_deficit + 0.25·lst_heat + 0.25·pop_need '
     '+ 0.15·access_need (ดูกล่องสูตรด้านบน) · ปรับน้ำหนักผ่าน UI ได้',
     'ใช้ใน FR-06/07/14 · ปัจจัยเป็นแบบ additive (เติมได้ ไม่ลด) ตามหลักการ '
     'ของโปรเจกต์'),
   ref_card('R4', 'Nyelele et al. (2022)', 'used',
     'Nyelele, C., et al. (2022). A comparison of tree planting prioritization '
     'frameworks (i-Tree Landscape vs. spatial decision support tool). USDA Forest '
     'Service / Urban Forestry & Urban Greening.',
     'ข้อสรุปว่า "ความเป็นไปได้ในการปลูกจริง (feasibility)" เป็นองค์ประกอบสำคัญ '
     'ของการจัดลำดับ',
     'จากการเปรียบเทียบสอง framework และวิเคราะห์องค์ประกอบที่ควรมี',
     'scoring.py — ' + mono('plantable_mask') + ' ตัด ESA class 10/50/70/80/90/95/100 '
     'และความชันเกิน 30° (SRTM) ก่อนเลือก top-N',
     'ยังเป็น proxy จาก remote sensing — การปลูกจริงต้องสำรวจหน้างาน '
     '(ที่มาของ FR-26 กลุ่ม B)'),
   ref_card('R29', 'Tatem (2017) — WorldPop', 'used',
     'Tatem, A.J. (2017). WorldPop, open data for spatial demography. Scientific '
     'Data, 4, 170004. doi:10.1038/sdata.2017.4',
     'ชุดข้อมูลความหนาแน่นประชากรเชิงพื้นที่ (gridded population) ความละเอียด 100 ม.',
     'จาก dataset WorldPop ที่บทความนี้อธิบายวิธีสร้าง',
     'scoring.py — ' + mono("WorldPop/GP/100m/pop") + ' (country THA), '
     'pop_need = ln(pop+1) / ln(1000) แล้ว clamp 0..1',
     'เลือก log-scale เพราะประชากรไทยเหลื่อมกันหลาย order of magnitude'),
   ref_card('R13', 'Zanaga et al. (2022) — ESA WorldCover', 'used',
     'Zanaga, D., et al. (2022). ESA WorldCover 10 m 2021 v200. Zenodo. '
     'doi:10.5281/zenodo.7254221',
     'ระบบชั้นการปกคลุมดิน (land cover) 11 คลาส ความละเอียด 10 ม. '
     '(เช่น 10 = ต้นไม้, 50 = สิ่งปลูกสร้าง)',
     'จากผลิตภัณฑ์ WorldCover v200 (ปี 2021) + รายงานความถูกต้อง',
     'ใช้ 3 จุด: (1) ' + mono('plantable_mask') + ' ตัดคลาสปลูกไม่ได้ · '
     '(2) ' + mono('access_need') + ' ใช้ class 10 เป็นพื้นที่สีเขียวเดิม · '
     '(3) urban subset เทียบ WHO เฉพาะเขตเมือง',
     'เป็น snapshot ปี 2021 ใช้เป็น proxy เขตเมืองทุกปีที่วิเคราะห์'),
   ref_card('R8', 'Network-based accessibility (2025)', 'partial',
     'Network-based assessment of urban forest and green space accessibility in '
     'six major cities (London, New York, Paris, Tokyo, Seoul, Beijing). (2025). '
     'Urban Forestry & Urban Greening.',
     'แนวคิดการวัด "การเข้าถึงพื้นที่สีเขียว" เป็นมิติหนึ่งของความเป็นธรรม',
     'จากกรอบการประเมิน accessibility ด้วยระยะทางถึงพื้นที่สีเขียว',
     'scoring.py — ' + mono('access_need_image()') + ' คำนวณระยะถึงต้นไม้ใกล้สุด '
     '(fastDistanceTransform) cap ที่ 1000 ม. เป็นปัจจัย 15% ใน Priority',
     'ใช้บางส่วน — เป็น distance-transform (Euclidean) ยังไม่ใช่ network '
     'distance เต็มรูป (ดู R18)'),
   ref_card('R9', 'GIS-based accessibility (2016)', 'partial',
     'GIS-based analysis for assessing the accessibility at hierarchical levels '
     'of urban green spaces. (2016). Urban Forestry & Urban Greening.',
     'แนวทางวิเคราะห์การเข้าถึงพื้นที่สีเขียวแบบหลายระดับ (network analysis / '
     'hierarchical)',
     'จากกรอบเชิงวิธี (methodological framework) ของ accessibility ด้วย GIS',
     'เสริมเหตุผลของปัจจัย access_need ใน Priority Score',
     'ใช้บางส่วน — วิธีเต็ม (network/hierarchical) อยู่ในแผน FR-19'),
 ]),
 ('E. การวิเคราะห์แนวโน้ม (Trend Analysis)', [MANNKENDALL_FORMULA], [
   ref_card('R17', 'Mann (1945) / Kendall (1975)', 'used',
     'Mann, H.B. (1945). Nonparametric Tests Against Trend. Econometrica, 13(3), '
     '245–259. · Kendall, M.G. (1975). Rank Correlation Methods (4th ed.). London: '
     'Griffin.',
     'สถิติทดสอบแนวโน้มแบบไม่อิงพารามิเตอร์ (Mann-Kendall): ค่า S, tau, z, p-value '
     'พร้อม tie correction',
     'จากนิยามสถิติ S และการประมาณด้วย normal approximation (บทความต้นตำรับ)',
     'stats_utils.py — ' + mono('mann_kendall(alpha=0.05)') + ' (ดูกล่องสูตร) '
     'ใช้กับอนุกรม NDVI/LST รายปีใน endpoint timeseries',
     'เขียนด้วย stdlib math ล้วน (ไม่มี numpy/scipy) → unit-test ง่าย'),
   ref_card('R16', 'Mehmood et al. (2024)', 'used',
     'Mehmood, K., Anees, S.A., et al. (2024). Analyzing vegetation health dynamics '
     'across seasons and regions through NDVI and climatic variables. Scientific '
     'Reports, 14, 11775. doi:10.1038/s41598-024-62464-7',
     'แบบแผนการประยุกต์ Mann-Kendall กับอนุกรม NDVI ระดับภูมิภาค/ฤดูกาล',
     'จากส่วน methods ที่ใช้ MK วิเคราะห์แนวโน้มสุขภาพพืชพรรณ',
     'เป็น precedent เชิงวิชาการของการใช้ MK กับ NDVI รายปีในระบบ '
     '(รูปแบบเดียวกับ stats_utils.py)',
     'R17 = ที่มาของสถิติ · R16 = ตัวอย่างการใช้กับ NDVI จริง'),
 ]),
 ('F. ประมาณการผลกระทบ (CO₂ Sequestration + Cooling)', [IMPACT_FORMULA], [
   ref_card('R11', 'IPCC (2019) Vol.4 Ch.4', 'used',
     'IPCC (2019). 2019 Refinement to the 2006 IPCC Guidelines for National '
     'Greenhouse Gas Inventories, Vol.4 (AFOLU), Ch.4 Forest Land. Geneva: IPCC.',
     'อัตราการสะสมมวลชีวภาพเหนือดินของป่าทุติยภูมิเขตร้อน ~3.6 t C/ha/ปี → '
     'คิดเป็น ~22 กก. CO₂/ต้น/ปี ที่ความหนาแน่น 400 ต้น/ha',
     'จากค่า default (Tier 1) ของ above-ground biomass increment ใน Ch.4',
     'impact.py — ' + mono('default_kg_co2=22.0') + ', ' + mono('trees_per_ha=400') +
     ' (ใช้เมื่อไม่มีค่ารายชนิด)',
     'เป็น order-of-magnitude estimate ที่ steady-state (~10–15 ปี) ไม่ใช่ค่าตายตัว'),
   ref_card('R25', 'Chave et al. (2014)', 'used',
     'Chave, J., Réjou-Méchain, M., Búrquez, A., et al. (2014). Improved allometric '
     'models to estimate the aboveground biomass of tropical trees. Global Change '
     'Biology, 20(10), 3177–3190. doi:10.1111/gcb.12629',
     'โมเดล allometry แบบ pan-tropical (มวลชีวภาพจากเส้นผ่านศูนย์กลาง ความสูง '
     'และความหนาแน่นเนื้อไม้)',
     'จากสมการ allometric ที่ปรับปรุงใหม่สำหรับต้นไม้เขตร้อน',
     'impact.py — ฐานคำนวณ ' + mono('TREE_CO2_PER_YEAR') + ' รายชนิด เช่น ยางนา 32, '
     'จามจุรี 28, มังคุด 12 กก./ต้น/ปี',
     'ให้ค่าต่างรายชนิด แม่นกว่าใช้ค่ากลาง IPCC อย่างเดียว'),
   ref_card('R10', 'Bowler et al. (2010)', 'used',
     'Bowler, D.E., Buyung-Ali, L., Knight, T.M., & Pullin, A.S. (2010). Urban '
     'greening to cool towns and cities: A systematic review. Landscape and Urban '
     'Planning, 97(3), 147–155. doi:10.1016/j.landurbplan.2010.05.006',
     'ค่าการลดอุณหภูมิของพื้นที่สีเขียว: เย็นลงเฉลี่ย ~1°C สูงสุด ~3°C ในเรือนยอดหนาแน่น',
     'จากผล meta-analysis ของหลักฐานเชิงประจักษ์ (systematic review)',
     'impact.py — ' + mono('delta_lst_c') + ' = −1.5 °C ที่เรือนยอดโตเต็มที่ '
     '(maturity ~10 ปี)',
     'เลือก −1.5°C (ค่อนไปทางระมัดระวัง กลางช่วง 1–3°C) เป็นค่า ΔLST'),
   ref_card('R26', 'U.S. EPA (2023)', 'used',
     'U.S. Environmental Protection Agency (2023). Greenhouse Gas Emissions from a '
     'Typical Passenger Vehicle. EPA-420-F-23-014. Washington, DC: U.S. EPA.',
     'ค่าอ้างอิงการปล่อยของรถยนต์นั่งเฉลี่ย ~4.6 ตัน CO₂/คัน/ปี',
     'จากตัวเลข baseline ของ typical passenger vehicle',
     'impact.py — ' + mono('car_co2_t_per_year=4.6') + ' → ' +
     mono('equivalent_cars_off_road') + ' = CO₂ที่ดูดซับ / 4.6',
     'ใช้แปลงผลเป็น "เทียบเท่ารถยนต์ที่ลดได้" ให้ผู้ใช้เข้าใจง่าย'),
   ref_card('R22', 'Dong et al. (2025)', 'used',
     'Dong, H., Tang, L., Liu, J., Hu, X., & Shao, G. (2025). Remote sensing of '
     'urban tree carbon stocks: A methodological review. ISPRS Journal of '
     'Photogrammetry and Remote Sensing, 227.',
     'ภาพรวมวิธี remote-sensing สำหรับประเมิน carbon stock ของต้นไม้ในเมือง',
     'จากบทวิจารณ์เชิงวิธี (methodological review)',
     'สนับสนุนความน่าเชื่อถือของแนวทางประมาณ CO₂ (เสริมมุมมอง remote sensing '
     'ให้ค่า IPCC/Chave)',
     None),
   ref_card('R19', '(2025) Cooling effect review', 'used',
     'The cooling effect of urban green spaces as nature-based solutions for '
     'mitigating urban heat: insights from a decade-long systematic review. (2025). '
     'Climate Risk Management, e00731.',
     'ช่วงค่า cooling ที่อัปเดต: 1–7°C จากการสังเคราะห์งาน 84 ฉบับ (2014–2024)',
     'จากผลสังเคราะห์ของ systematic review รอบทศวรรษ',
     'อัปเดตหลักฐานเชิงปริมาณของค่า cooling (เสริม/ยืนยันค่า ΔLST จาก Bowler)',
     None),
 ]),
 ('G. มาตรฐาน แพลตฟอร์ม และขอบเขต', None, [
   ref_card('R1', 'WHO (2017)', 'used',
     'World Health Organization, Regional Office for Europe (2016–2017). Urban '
     'green spaces and health / Urban green spaces: a brief for action. Copenhagen: '
     'WHO Europe.',
     'เกณฑ์พื้นที่สีเขียวเข้าถึงได้ อย่างน้อย 9 ตารางเมตรต่อประชากรหนึ่งคน',
     'จากข้อเสนอแนะเชิงนโยบายของ WHO Europe',
     'ใช้เป็นเส้นเทียบใน ranking m²/คน และ urban subset (เทียบเฉพาะเขตเมือง)',
     'เกณฑ์หลักที่ระบบใช้ตัดสิน "ผ่าน/ไม่ผ่าน" มาตรฐานสากล'),
   ref_card('R28', 'Gorelick et al. (2017) — GEE', 'used',
     'Gorelick, N., Hancher, M., Dixon, M., Ilyushchenko, S., Thau, D., & Moore, R. '
     '(2017). Google Earth Engine: Planetary-scale geospatial analysis for everyone. '
     'Remote Sensing of Environment, 202, 18–27. doi:10.1016/j.rse.2017.06.031',
     'แพลตฟอร์มประมวลผลภูมิสารสนเทศระดับ planetary-scale (คลังข้อมูล + compute)',
     'จากบทความแนะนำระบบ GEE',
     'เป็น compute backend ของทุก endpoint — NDVI, LST, priority, urban subset '
     'ถูกคำนวณบน GEE ทั้งหมด',
     'ทำให้วิเคราะห์ทั่วประเทศได้โดยไม่ต้องลงทุนโครงสร้างพื้นฐานเอง'),
   ref_card('R30', 'Hijmans et al. (2021) — GADM v4.1', 'used',
     'Hijmans, R.J., Garcia, N., & Wieczorek, J. (2021). GADM database of Global '
     'Administrative Areas, version 4.1. University of California, Berkeley.',
     'ขอบเขตเชิงเรขาคณิต (polygon) ของหน่วยการปกครองระดับจังหวัดและอำเภอ',
     'จากฐานข้อมูล GADM v4.1 (administrative boundaries)',
     'generate_districts.py — ให้ขอบเขต 77 จังหวัด / 928 อำเภอ ที่ระบบใช้ clip '
     'ทุกการคำนวณเชิงพื้นที่',
     None),
   ref_card('R5', 'Right Tree, Right Place (2026)', 'used',
     'Towards "Right Tree, Right Place" in urban environments: A systematic review '
     'of decision-support methods and tools for urban tree planting. (2026). Urban '
     'Forestry & Urban Greening.',
     'กรอบแนวคิดการเลือก "พันธุ์ไม้ที่เหมาะกับพื้นที่" (species-site matching)',
     'จาก systematic review ของวิธี/เครื่องมือช่วยตัดสินใจปลูกต้นไม้ในเมือง',
     'species.py — ระบบแนะนำพันธุ์ไม้พื้นถิ่นแยกตาม 6 ภูมิภาค (22 ชนิด) '
     'พร้อมเหตุผลทางนิเวศ',
     None),
 ]),
 ('H. ข้อเสนอต่อยอด (กลุ่ม B — งานวิจัยรองรับ แต่ยังไม่พัฒนา)', None, [
   ref_card('R2', 'Konijnendijk (2023)', 'roadmap',
     'Konijnendijk, C.C. (2023). Evidence-based guidelines for greener, healthier, '
     'more resilient neighbourhoods: Introducing the 3–30–300 rule. Journal of '
     'Forestry Research, 34, 821–830. doi:10.1007/s11676-022-01523-z',
     'กฎ 3-30-300: เห็นต้นไม้ 3 ต้นจากบ้าน · เรือนยอดปกคลุม 30% · '
     'สวนสาธารณะภายใน 300 เมตร',
     'จากข้อเสนอแนะเชิงประจักษ์ (evidence-based guideline) ของบทความ',
     'แผน FR-17/18 — เพิ่มตัวชี้วัด 30% canopy และ % ประชากรใน 300 ม. '
     '(ยังไม่พัฒนา)',
     'จะเสริมมาตรฐาน WHO เดิม เป็น benchmark ระดับย่านที่ใหม่กว่า'),
   ref_card('R6, R20', 'American Forests — Tree Equity Score', 'roadmap',
     'American Forests. Tree Equity Score — methodology & nationwide scores (2024). '
     'https://www.treeequityscore.org/methodology',
     'สูตร Tree Equity Score = 100 × (1 − GapScore × E) จาก 7 ตัวแปรสังคม '
     '(อายุ รายได้ สุขภาพ ความร้อน การจ้างงาน ภาษา เชื้อชาติ)',
     'จากเอกสารระเบียบวิธีของ TES',
     'แผน FR-21/22 — คำนวณ Green/Tree Equity Score ต่ออำเภอ + เพิ่มปัจจัย '
     'ความเปราะบางเข้า Priority (ยังไม่พัฒนา)',
     'คำว่า "equity" ในโค้ดปัจจุบันเป็นเพียง label ของ access factor ยังไม่ใช่ TES เต็ม'),
   ref_card('R21', 'Fulton et al. (2025)', 'roadmap',
     'Fulton, A.J., Ries, P.D., & Riley, G.E. (2025). Where Are the Benefits of '
     'Trees Needed Most? A Comparison of Equity-Based Mapping Tools in Austin, '
     'Texas. Arboriculture & Urban Forestry, 52(4). doi:10.48044/jauf.2025.020',
     'วิธีเปรียบเทียบเครื่องมือ equity-mapping สำหรับจัดลำดับพื้นที่ที่ต้องการ '
     'ต้นไม้มากที่สุด',
     'จากกรณีศึกษาจริง (Austin, Texas) เทียบ TES กับเครื่องมืออื่น',
     'แผน FR-21/22 — อ้างอิงวิธี validate/เทียบเครื่องมือ equity (ยังไม่พัฒนา)',
     None),
   ref_card('R7', 'i-Tree Eco (2024)', 'roadmap',
     'US Forest Service. i-Tree Eco. · กรณีศึกษา: Quantifying Regulating Ecosystem '
     'Services of Urban Trees using i-Tree Eco. Forests, 15(8), 1446 (2024). '
     'https://www.mdpi.com/1999-4907/15/8/1446',
     'โมเดลตีมูลค่าบริการนิเวศเต็มรูป: ดูดซับมลพิษอากาศ (PM2.5/O₃/NO₂), '
     'ลด stormwater runoff, และตีมูลค่าเป็นเงิน',
     'จากชุดสมการ/coefficient ของ i-Tree Eco',
     'แผน FR-23/24/25 — ขยาย estimate_impact ให้ครอบคลุมมลพิษ/น้ำฝน/มูลค่าเงิน '
     '(ยังไม่พัฒนา)',
     'ปัจจุบัน "ลด PM2.5" ในโค้ดเป็นเพียงข้อความบรรยายพันธุ์ไม้ ไม่ใช่การคำนวณ'),
   ref_card('R18', 'G2SFCA Seoul (2026)', 'roadmap',
     'An Application of the Grid-Based Two-Step Floating Catchment Area Method to '
     'Assess the Spatial Accessibility of Green Spaces in Seoul, South Korea. (2026). '
     'ISPRS IJGI, 15(2), 71. doi:10.3390/ijgi15020071',
     'วิธี Two-Step Floating Catchment Area (2SFCA) แบบ grid-based ที่ถ่วงทั้ง '
     'supply (ขนาดสวน) และ demand (ความหนาแน่นประชากร)',
     'จากวิธี G2SFCA ที่ปรับปรุงจาก 2SFCA มาตรฐาน',
     'แผน FR-20 — ยกระดับ access_need ปัจจุบันเป็น accessibility เต็มรูปด้วย 2SFCA '
     '(ยังไม่พัฒนา)',
     'เป็นเวอร์ชันเต็มของแนวคิดที่ R8/R9 วางไว้ (ตอนนี้ทำแบบ distance-transform)'),
 ]),
]


# ── Build story ──────────────────────────────────────────────────────────────
story = []
story.append(title_bar('บรรณานุกรมเชิงลึก: เอางานวิจัยแต่ละชิ้นมาใช้ตรงไหนในระบบ'))
story.append(Spacer(1, 4))
story.append(Paragraph(
    'Bibliography In-Depth Dossier — ระบบวิเคราะห์พื้นที่สีเขียวและแนะนำพื้นที่ปลูกต้นไม้'
    'อัจฉริยะของประเทศไทย · โครงการ NSC 28P14N00163 · จัดทำ 6 กรกฎาคม 2569',
    S['muted']))
story.append(Spacer(1, 6))
story.append(Paragraph(
    'เอกสารนี้ลงรายละเอียดทีละอ้างอิง (31 รายการ R1–R31) ว่าดึง "ค่า/สูตร/ข้อมูล" '
    'อะไรมาจากงานวิจัยส่วนไหน แล้วนำไปตั้งเป็นค่าคงที่หรือสูตรตรงจุดใดในโค้ด '
    'ค่าทุกตัวสอบทานจากไฟล์จริง (impact.py · scoring.py · gee_utils.py · '
    'stats_utils.py) จัดกลุ่มตามโมดูลของระบบ 8 หมวด และมีกล่องสูตรจริงประกอบ '
    'ในหมวดคะแนนความสำคัญ ผลกระทบ และแนวโน้ม',
    S['p']))
story.append(Spacer(1, 5))
story.append(Paragraph(
    '<font face="Sarabun-Bold">สถานะ (สีของรหัส R#):</font> '
    '<font face="Sarabun-Bold" color="#1e8e3e">ใช้แล้ว</font> = มีในโค้ดจริง (กลุ่ม A) · '
    '<font face="Sarabun-Bold" color="#f97316">ใช้บางส่วน</font> = แนวคิดถูกใช้บางส่วน · '
    '<font face="Sarabun-Bold" color="#7c3aed">แผนต่อยอด</font> = กลุ่ม B ยังไม่พัฒนา',
    S['muted']))
story.append(Spacer(1, 6))

# สารบัญโมดูล
toc_lines = '  ·  '.join(t.split(' — ')[0] for t, _, _ in MODULES)
story.append(Paragraph(f'<font face="Sarabun-Bold">สารบัญโมดูล:</font> {toc_lines}',
                       S['toc']))
story.append(Spacer(1, 10))

for title, intro, cards in MODULES:
    block = [section_bar(title), Spacer(1, 6)]
    story.append(KeepTogether(block))
    if intro:
        for fl in intro:
            story.append(fl)
    for c in cards:
        story.append(c)
    story.append(Spacer(1, 4))

story.append(Spacer(1, 4))
story.append(Paragraph(
    'เอกสารประกอบชุดเดียวกัน: REQUIREMENTS.md §6–7 (รายการเต็ม + traceability) · '
    'Bibliography_Relevance_Audit.pdf (สรุปสถานะภาพรวม) · '
    'Bibliography_Extraction_Detail.pdf (ตารางย่อ) · '
    'Proposal_28P14N00163_GreenAreaThailand.pdf ข้อ 8 (บรรณานุกรมในเล่ม)',
    S['muted']))

out_path = os.path.join(ROOT, 'Bibliography_InDepth_Dossier.pdf')
doc = SimpleDocTemplate(
    out_path, pagesize=A4,
    leftMargin=20 * mm, rightMargin=20 * mm,
    topMargin=22 * mm, bottomMargin=20 * mm,
    title='บรรณานุกรมเชิงลึก — 28P14N00163',
    author='อติชาติ ผาแสนเถิน',
    subject='Bibliography In-Depth Dossier — NSC 2026',
)
doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
print(f'[OK] Generated: {out_path}')
print(f'     Size: {os.path.getsize(out_path):,} bytes')
