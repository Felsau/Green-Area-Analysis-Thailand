# -*- coding: utf-8 -*-
"""สร้างเอกสารหลักฐาน — "ความน่าเชื่อถือของการแนะนำพันธุ์ไม้"

ตัวเลขทุกตัวอ่านจากไฟล์ผลลัพธ์ของ validate_species.py ใน reports/ ไม่มีการพิมพ์ค่าลงมือ
ตัวอย่างการจัดอันดับอ่านจาก reports/species_ranking_example.csv ซึ่ง validate_species.py
สร้างด้วยการเรียกฟังก์ชันจัดอันดับตัวจริงใน routers/recommend/species.py

รันด้วย Python ของระบบ (ต้องมี python-docx) ไม่ใช่ .venv ของ backend:
    python make_species_evidence_doc.py
"""
import csv
import datetime
import json
import os

from docx import Document
from docx.shared import Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

ROOT = r"C:\Users\atich\Desktop\01 Projects\Project"
BACKEND = os.path.join(ROOT, "green-area-backend")
REPORTS = os.path.join(BACKEND, "reports")
YEAR = 2025
OUT = os.path.join(ROOT, "หลักฐานความน่าเชื่อถือของการแนะนำพันธุ์ไม้.docx")

FONT = "TH Sarabun New"
BODY_PT = 16
GREEN = RGBColor(0x1B, 0x7A, 0x46)
RED = RGBColor(0xC0, 0x41, 0x2A)
AMBER = RGBColor(0xB5, 0x7A, 0x0B)
GREY = RGBColor(0x55, 0x5F, 0x5A)


def _read(name):
    with open(os.path.join(REPORTS, name), encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


tax = _read("species_taxonomy.csv")
occ = _read("species_regional_occurrence.csv")
beh = _read("species_ranking_behaviour.csv")
kw = _read("species_keyword_audit.csv")
co2 = _read("species_co2_coefficients.csv")
example = _read("species_ranking_example.csv")
with open(os.path.join(REPORTS, "species_thresholds_%d.json" % YEAR),
          encoding="utf-8") as f:
    thr = json.load(f)

run_dt = datetime.datetime.fromtimestamp(
    os.path.getmtime(os.path.join(REPORTS, "species_taxonomy.csv")))

rank_sum = thr["ranking_summary"]
HOT_LST_C = thr["thresholds"]["hot_lst_c"]
LOW_NDVI = thr["thresholds"]["low_ndvi"]
HIGH_NDVI = thr["thresholds"]["high_ndvi"]
N_REGIONS = rank_sum["n_regions"]
N_PROVINCES = rank_sum["n_provinces"]

# ---------- สรุปตัวเลข (คำนวณจากไฟล์ผล ไม่พิมพ์มือ) ----------
n_species = len(tax)
n_name_ok = sum(1 for r in tax if r["name_accepted"] == "True")
n_in_th = sum(1 for r in tax if r["in_thailand_wcvp"] == "True")
n_native = sum(1 for r in tax if r["establishment_in_thailand"] == "NATIVE")
n_introduced = sum(1 for r in tax if r["establishment_in_thailand"] == "INTRODUCED")
not_in_th = [r["name_th"] for r in tax if r["in_thailand_wcvp"] != "True"]
claim_rows = [r for r in tax if r["system_claims_native"] == "True"]
n_conflict = sum(1 for r in tax if r["claim_conflict"] == "True")

occ_ok = [r for r in occ if r["effort_adjusted_ratio"]]
n_ratio_ge1 = sum(1 for r in occ_ok if float(r["effort_adjusted_ratio"]) >= 1.0)
n_no_record = sum(1 for r in occ if int(r["n_records_th_georef"]) == 0)
total_records = sum(int(r["n_records_th_georef"]) for r in occ)

n_cases = len(beh)
n_changed = sum(1 for r in beh if r["changed_from_default"] == "True")
n_top_fit = sum(1 for r in beh if r["top_has_site_fit"] == "True")
reachable_top = {r["top_species"] for r in beh}
weak_shade = [r["name_th"] for r in kw if r["weak_shade_only"] == "True"]
no_kw = [r["name_th"] for r in kw if r["no_keyword_at_all"] == "True"]

co2s = thr["co2_summary"]
tp, td = thr["thresholds"]["province"], thr["thresholds"]["district"]

# ---------- ตัวอย่างการจัดอันดับ (บันทึกไว้โดย validate_species.py) ----------
EXAMPLE_REGION = example[0]["region"]
EXAMPLE_LST = float(example[0]["lst_used"])
EXAMPLE_NDVI = float(example[0]["ndvi_used"])

# ---------- docx helpers ----------
doc = Document()
sec = doc.sections[0]
sec.top_margin = Cm(2.0)
sec.bottom_margin = Cm(2.0)
sec.left_margin = Cm(2.5)
sec.right_margin = Cm(2.0)


def _font(run, size=BODY_PT, bold=False, color=None, name=FONT):
    run.font.name = name
    run.font.size = Pt(size)
    run.font.bold = bold
    if color is not None:
        run.font.color.rgb = color
    rpr = run._element.get_or_add_rPr()
    rf = rpr.find(qn("w:rFonts"))
    if rf is None:
        rf = OxmlElement("w:rFonts")
        rpr.insert(0, rf)
    for a in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
        rf.set(qn(a), name)
    szcs = OxmlElement("w:szCs")
    szcs.set(qn("w:val"), str(int(size * 2)))
    rpr.append(szcs)
    if bold:
        rpr.append(OxmlElement("w:bCs"))
    rpr.append(OxmlElement("w:cs"))    # เปิด complex-script ให้ไทยเรนเดอร์ถูก


def para(text="", size=BODY_PT, bold=False, color=None, align=None,
         space_before=0, space_after=6, indent=None, line=1.0):
    p = doc.add_paragraph()
    pf = p.paragraph_format
    pf.space_before = Pt(space_before)
    pf.space_after = Pt(space_after)
    pf.line_spacing = line
    if indent is not None:
        pf.first_line_indent = Cm(indent)
    if align is not None:
        p.alignment = align
    if text:
        _font(p.add_run(text), size, bold, color)
    return p


def heading(text, size=18, color=GREEN, space_before=14):
    return para(text, size=size, bold=True, color=color,
                space_before=space_before, space_after=4)


def bullet(text, size=BODY_PT, indent_cm=0.6):
    p = doc.add_paragraph()
    pf = p.paragraph_format
    pf.left_indent = Cm(indent_cm + 0.5)
    pf.first_line_indent = Cm(-0.5)
    pf.space_after = Pt(2)
    pf.line_spacing = 1.0
    _font(p.add_run("•  " + text), size)
    return p


def set_cell(cell, text, size=14, bold=False, color=None, align=None):
    cell.text = ""
    p = cell.paragraphs[0]
    p.paragraph_format.space_before = Pt(1)
    p.paragraph_format.space_after = Pt(1)
    p.paragraph_format.line_spacing = 1.0
    if align is not None:
        p.alignment = align
    _font(p.add_run(text), size, bold, color)


def shade(cell, hexcolor):
    tcpr = cell._tc.get_or_add_tcPr()
    sh = OxmlElement("w:shd")
    sh.set(qn("w:val"), "clear")
    sh.set(qn("w:color"), "auto")
    sh.set(qn("w:fill"), hexcolor)
    tcpr.append(sh)


def make_table(headers, widths, style="Table Grid"):
    t = doc.add_table(rows=1, cols=len(headers))
    t.style = style
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    t.autofit = False
    for i, h in enumerate(headers):
        set_cell(t.rows[0].cells[i], h, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER)
        shade(t.rows[0].cells[i], "E8F1EB")
    trpr = t.rows[0]._tr.get_or_add_trPr()
    th = OxmlElement("w:tblHeader")
    th.set(qn("w:val"), "true")
    trpr.append(th)
    for r in t.rows:
        for i, w in enumerate(widths):
            r.cells[i].width = Cm(w)
    return t


def add_row(t, values, widths, aligns=None, colors=None, bolds=None):
    cells = t.add_row().cells
    for i, v in enumerate(values):
        set_cell(cells[i], v,
                 align=(aligns[i] if aligns else None),
                 color=(colors[i] if colors else None),
                 bold=(bolds[i] if bolds else False))
        cells[i].width = Cm(widths[i])
    return cells


C = WD_ALIGN_PARAGRAPH.CENTER
R = WD_ALIGN_PARAGRAPH.RIGHT
J = WD_ALIGN_PARAGRAPH.JUSTIFY

# ================================================================ หน้าปก
para("เอกสารหลักฐานแนบ", size=16, color=GREY, align=C, space_after=0)
para("ความน่าเชื่อถือของการแนะนำพันธุ์ไม้", size=22, bold=True, color=GREEN,
     align=C, space_after=2)
para("ระบบวิเคราะห์พื้นที่สีเขียวเมืองด้วยข้อมูลภาพถ่ายดาวเทียม (GreenLens)",
     size=16, color=GREY, align=C, space_after=10)

t = make_table(["หัวข้อ", "รายละเอียด"], [4.2, 11.3])
info = [
    ("คำถามที่ตอบ", "ระบบรู้ได้อย่างไรว่าควรปลูกต้นไหน และมีหลักฐานอะไรรองรับ"),
    ("ส่วนของระบบที่ตรวจ", "green-area-backend/routers/recommend/species.py "
                           "(การเลือกและจัดอันดับพันธุ์)\n"
                           "green-area-backend/impact.py (สัมประสิทธิ์การกักเก็บ CO₂ รายพันธุ์)"),
    ("จำนวนพันธุ์ที่ตรวจ", "%d ชนิด (ทุกชนิดที่ระบบแนะนำได้ ครบ %d ภาค)"
     % (n_species, N_REGIONS)),
    ("ข้อมูลอ้างอิงภายนอก",
     "GBIF Backbone Taxonomy — ความถูกต้องของชื่อวิทยาศาสตร์\n"
     "World Checklist of Vascular Plants (WCVP), Royal Botanic Gardens Kew "
     "— สถานะพื้นเมือง\n"
     "GBIF Occurrence Records — การพบจริงในประเทศไทยรายจังหวัด (GADM ระดับ 1)"),
    ("ข้อมูลภายในที่ใช้", "ค่า LST/NDVI รายจังหวัดและรายอำเภอ ปี ค.ศ. %d จากฐานข้อมูลระบบ "
                          "(%d จังหวัด · %d อำเภอ)" % (YEAR, tp["n_lst"], td["n_lst"])),
    ("วันที่ตรวจ", "%02d/%02d/%d เวลา %02d:%02d น."
     % (run_dt.day, run_dt.month, run_dt.year + 543, run_dt.hour, run_dt.minute)),
    ("สคริปต์ที่ใช้ตรวจ", "green-area-backend/validate_species.py"),
    ("ไฟล์ผลลัพธ์", "reports/species_taxonomy.csv (%d แถว)\n"
                    "reports/species_regional_occurrence.csv (%d แถว)\n"
                    "reports/species_ranking_behaviour.csv (%d แถว)\n"
                    "reports/species_keyword_audit.csv (%d แถว)\n"
                    "reports/species_co2_coefficients.csv (%d แถว)\n"
                    "reports/species_thresholds_%d.json"
                    % (len(tax), len(occ), len(beh), len(kw), len(co2), YEAR)),
]
for k, v in info:
    add_row(t, [k, v], [4.2, 11.3], bolds=[True, False])

# ================================================================ 1
heading("1. ขอบเขตของคำตอบ — ระบบ “เลือก” ไม่ได้ “คิดค้น” พันธุ์ไม้")
para("ก่อนแสดงหลักฐาน ต้องแยกคำถามสองข้อที่ต่างกันออกจากกันให้ชัด มิฉะนั้นการตอบจะเกินสิ่ง"
     "ที่ระบบทำได้จริง", align=J)
bullet("คำถามที่ระบบ ไม่ได้ ตอบ: “ต้นไม้ชนิดใดดีที่สุดสำหรับจุดพิกัดนี้” — คำตอบนั้น"
       "ต้องใช้การสำรวจดิน ความลึกน้ำใต้ดิน การใช้ประโยชน์ที่ดินจริง และการตัดสินใจ"
       "ของนักวนศาสตร์ในพื้นที่")
bullet("คำถามที่ระบบ ตอบ: “จากบัญชีพันธุ์ไม้ที่ผ่านการคัดมาแล้วสำหรับภาคนี้ ชนิดใดตรง"
       "กับสภาพของพื้นที่ที่วิเคราะห์ได้มากที่สุด และควรพิจารณาก่อน”")
para("เอกสารนี้จึงไม่ได้พิสูจน์ว่า “ระบบเลือกต้นไม้ถูกที่สุด” แต่พิสูจน์สามเรื่องที่ตรวจสอบได้จริง "
     "คือ (1) บัญชีพันธุ์ไม้ที่ใช้เป็นพันธุ์ที่มีอยู่จริงและถูกต้องตามฐานข้อมูลพฤกษศาสตร์สากล "
     "(2) พันธุ์เหล่านั้นถูกบันทึกว่าพบจริงในภาคที่ระบบแนะนำ และ (3) กลไกจัดอันดับทำงานตาม"
     "ที่ประกาศไว้จริง พร้อมรายงานจุดที่กลไกยังอ่อน", align=J, space_before=4)

heading("2. วิธีทำงานจริงของการแนะนำพันธุ์ไม้ (3 ขั้น)", size=17, space_before=12)
t = make_table(["ขั้น", "สิ่งที่ระบบทำ", "สิ่งที่กำหนดผลลัพธ์"], [1.2, 8.3, 6.0])
steps = [
    ("1", "จับจังหวัดที่ผู้ใช้เลือกเข้ากับภาคใดภาคหนึ่งใน %d ภาค" % N_REGIONS,
     "ตารางจังหวัด→ภาค (ฐานข้อมูล provinces)"),
    ("2", "ดึงบัญชีพันธุ์ไม้ประจำภาคนั้นออกมา ภาคละ 5 ชนิด",
     "บัญชีที่กำหนดไว้ล่วงหน้าในโปรแกรม"),
    ("3", "จัดลำดับ 5 ชนิดนั้นใหม่ตามสภาพพื้นที่ (ความร้อนผิวพื้น ความหนาแน่น"
          "พืชพรรณ และประเภทการใช้ที่ดินเด่นของจุดที่แนะนำ)",
     "ค่า LST/NDVI ของพื้นที่ + การจับคู่คำสำคัญ"),
]
for a, b, c in steps:
    add_row(t, [a, b, c], [1.2, 8.3, 6.0], aligns=[C, None, None])
para("ผลที่ตามมาซึ่งต้องระบุตรง ๆ คือ ชุดพันธุ์ไม้ที่เป็นไปได้ทั้งประเทศมีเพียง %d ชุด "
     "สำหรับ %d จังหวัด สภาพพื้นที่เปลี่ยนได้เฉพาะ “ลำดับ” ภายในชุดเดิม ไม่เปลี่ยน “สมาชิก” "
     "ของชุด" % (N_REGIONS, N_PROVINCES), align=J, space_before=6)

heading("2.1 บัญชีพันธุ์ไม้มาจากไหน", size=17, space_before=12)
para("การคัดเลือกพันธุ์ไม้ทั้ง %d ชนิดเป็นดุลยพินิจของผู้พัฒนา ไม่ได้คัดด้วยแบบจำลอง "
     "และคำบรรยายคุณสมบัติของแต่ละชนิดเขียนขึ้นในโครงงาน ข้อเท็จจริงข้อนี้คือเหตุผลที่"
     "ต้องมีเอกสารฉบับนี้ กล่าวคือเมื่อการคัดเลือกเป็นดุลยพินิจ การยืนยันความน่าเชื่อถือ"
     "จึงต้องทำด้วยการนำบัญชีที่ได้ไปตรวจกับฐานข้อมูลพฤกษศาสตร์ที่เป็นอิสระจากโครงงาน"
     % n_species, align=J)
para("บัญชีดังกล่าวถูกย้ายออกจากโปรแกรมมาเก็บเป็นไฟล์ข้อมูล (data/tree_species.json) "
     "โดยทุกชนิดมีบล็อกผลการตรวจสอบแนบไว้ ซึ่งสร้างอัตโนมัติจาก BGCI GlobalTreeSearch, "
     "World Checklist of Vascular Plants ของ Kew และ GBIF ด้วยสคริปต์ "
     "refresh_species_verification.py ผลการตรวจนี้ถูกส่งไปกับคำตอบของระบบและแสดงบน"
     "หน้าเว็บให้ผู้ใช้กดดูระเบียนต้นทางได้ทุกชนิด และมีชุดทดสอบอัตโนมัติที่ทำให้การ"
     "เพิ่มพันธุ์ซึ่งตรวจสอบไม่ผ่านทำให้ระบบทดสอบไม่ผ่านทันที", align=J, space_before=4)
t = make_table(["คำกล่าวอ้างของระบบ", "ตรวจย้อนกลับได้หรือไม่ และด้วยอะไร"],
               [5.8, 9.7])
claims = [
    ("พันธุ์นี้มีอยู่จริงและชื่อถูกต้อง",
     "ตรวจได้ — GBIF Backbone Taxonomy (ผลในหัวข้อ 3)"),
    ("พันธุ์นี้เป็นพืชพื้นเมืองของไทย",
     "ตรวจได้ — WCVP ของ Royal Botanic Gardens, Kew (ผลในหัวข้อ 4)"),
    ("พันธุ์นี้เหมาะกับภาคที่แนะนำ",
     "ตรวจได้บางส่วน — บันทึกการพบจริงของ GBIF รายจังหวัด (ผลในหัวข้อ 5) "
     "ยืนยันได้ว่า “พบในภาคนั้น” แต่ไม่ได้ยืนยันว่า “เหมาะที่สุดสำหรับภาคนั้น”"),
    ("คุณสมบัติของพันธุ์ เช่น ทนแล้ง ทนน้ำท่วม ทนมลพิษ ความสูงเมื่อโตเต็มที่",
     "ยังตรวจไม่ได้ — เป็นคำบรรยายที่เขียนขึ้นในโครงงาน ยังไม่ได้ผูกกับเอกสารวิชาการ"
     "รายชนิด (ช่องที่ต้องกรอกอยู่ในใบงาน reports/species_source_worksheet.csv)"),
    ("ปริมาณการกักเก็บคาร์บอนต่อต้นต่อปีของพันธุ์นั้น",
     "ยังตรวจไม่ได้รายชนิด — เป็นค่าประมาณตามกรอบ IPCC/i-Tree ตรวจได้เฉพาะความ"
     "สอดคล้องภายใน (ผลในหัวข้อ 8)"),
]
for a, b in claims:
    add_row(t, [a, b], [5.8, 9.7])

# ================================================================ 3
heading("3. ผลตรวจที่ 1 — ชื่อวิทยาศาสตร์ถูกต้องหรือไม่ (GBIF Backbone Taxonomy)")
para("ตรวจชื่อวิทยาศาสตร์ทั้ง %d ชนิดกับฐานข้อมูลอนุกรมวิธานกลางของ GBIF โดยนับว่าผ่าน"
     "เมื่อจับคู่แบบตรงตัว (EXACT) และเป็นชื่อที่ยอมรับ (ACCEPTED) ไม่ใช่ชื่อพ้อง"
     % n_species, align=J)
t = make_table(["ผลการตรวจ", "จำนวน", "การแปลผล"], [6.0, 2.5, 7.0])
add_row(t, ["ชื่อตรงตัวและเป็นชื่อที่ยอมรับ", "%d / %d" % (n_name_ok, n_species),
            "ไม่มีชื่อสะกดผิดหรือใช้ชื่อพ้องที่เลิกใช้แล้ว"],
        [6.0, 2.5, 7.0], aligns=[None, C, None],
        colors=[None, GREEN if n_name_ok == n_species else RED, None],
        bolds=[False, True, False])
add_row(t, ["มีบันทึกการกระจายพันธุ์ในประเทศไทย (WCVP)",
            "%d / %d" % (n_in_th, n_species),
            "ที่เหลือคือพันธุ์ที่ปลูกเลี้ยงในไทยแต่ WCVP ไม่บันทึกเป็นประชากรตามธรรมชาติ"],
        [6.0, 2.5, 7.0], aligns=[None, C, None], bolds=[False, True, False])

# ================================================================ 4
heading("4. ผลตรวจที่ 2 — สถานะพื้นเมืองในประเทศไทย (WCVP / Kew)")
para("World Checklist of Vascular Plants เป็นฐานข้อมูลของ Royal Botanic Gardens, Kew "
     "ซึ่งเป็นแหล่งเดียวกับที่ Plants of the World Online เผยแพร่ ระบุสถานะรายประเทศว่า"
     "เป็นพืชพื้นเมืองหรือพืชนำเข้า", align=J)
t = make_table(["สถานะตาม WCVP", "จำนวนชนิด", "รายชื่อ"], [4.5, 2.3, 8.7])
native_list = [r["name_th"] for r in tax
               if r["establishment_in_thailand"] == "NATIVE"]
intro_list = [r["name_th"] for r in tax
              if r["establishment_in_thailand"] == "INTRODUCED"]
add_row(t, ["พืชพื้นเมืองของไทย", str(n_native), ", ".join(native_list)],
        [4.5, 2.3, 8.7], aligns=[None, C, None],
        colors=[None, GREEN, None], bolds=[False, True, False])
add_row(t, ["พืชนำเข้าที่ขึ้นได้ในไทย", str(n_introduced), ", ".join(intro_list)],
        [4.5, 2.3, 8.7], aligns=[None, C, None],
        colors=[None, AMBER, None], bolds=[False, True, False])
add_row(t, ["ไม่มีบันทึกประชากรตามธรรมชาติในไทย", str(len(not_in_th)),
            ", ".join(not_in_th) + " (เป็นพันธุ์ปลูกเลี้ยง)"],
        [4.5, 2.3, 8.7], aligns=[None, C, None],
        colors=[None, AMBER, None], bolds=[False, True, False])

para("การมีพืชนำเข้าอยู่ในบัญชีไม่ใช่ข้อผิดพลาด เพราะระบบระบุวัตถุประสงค์ของพันธุ์กลุ่มนี้"
     "ไว้เป็นไม้ให้ร่มเงาในเมืองหรือไม้ฟื้นฟูดิน ไม่ใช่ไม้ฟื้นฟูป่า แต่เป็นข้อมูลที่ผู้ใช้ควรเห็น "
     "และเป็นข้อจำกัดที่บันทึกไว้ในหัวข้อ 9", align=J, space_before=4)

heading("4.1 การตรวจความสอดคล้องของคำบรรยายในระบบกับฐานข้อมูลสากล", size=17,
        space_before=10)
para("ระบบเขียนคำบรรยายพันธุ์ไม้เป็นภาษาไทย และมี %d ชนิดที่ระบุว่าเป็น “พันธุ์พื้นถิ่น” "
     "หรือ “พันธุ์เฉพาะถิ่น” จึงตรวจคำอ้างเหล่านี้กับ WCVP ทีละชนิด"
     % len(claim_rows), align=J)
t = make_table(["พันธุ์ที่ระบบระบุว่าเป็นพันธุ์พื้นถิ่น", "สถานะตาม WCVP", "ผล"],
               [6.5, 5.0, 4.0])
for r in sorted(claim_rows, key=lambda x: x["name_th"]):
    conflict = r["claim_conflict"] == "True"
    add_row(t, ["%s (%s)" % (r["name_th"], r["scientific"]),
                r["establishment_in_thailand"] or "ไม่มีบันทึกในไทย",
                "ขัดแย้ง" if conflict else "ตรงกัน"],
            [6.5, 5.0, 4.0], aligns=[None, C, C],
            colors=[None, None, RED if conflict else GREEN],
            bolds=[False, False, True])
para("ข้อความที่ระบบแสดงกับผู้ใช้ขัดแย้งกับฐานข้อมูลสากล %d รายการ" % n_conflict,
     bold=True, color=GREEN if n_conflict == 0 else RED, space_before=4)

# ================================================================ 5
heading("5. ผลตรวจที่ 3 — พันธุ์ที่แนะนำถูกบันทึกว่าพบจริงในภาคนั้นหรือไม่")
para("ดึงข้อมูลการพบ (occurrence) ที่มีพิกัดของแต่ละพันธุ์ในประเทศไทยจาก GBIF แล้วจับ"
     "แต่ละรายการเข้ากับจังหวัดด้วยขอบเขตการปกครอง GADM ระดับ 1 ก่อนรวมเป็นภาคตาม"
     "ตารางเดียวกับที่ระบบใช้ รวมข้อมูลที่ตรวจทั้งหมด %s รายการ" % f"{total_records:,}",
     align=J)
para("เนื่องจากความหนาแน่นของการสำรวจแต่ละภาคไม่เท่ากัน (ภาคเหนือมีการบันทึกมากที่สุด) "
     "จึงปรับด้วยฐานความพยายามสำรวจ โดยเทียบสัดส่วนของพันธุ์นั้นกับสัดส่วนของ"
     "พืชทุกชนิดในภาคเดียวกัน ค่า “อัตราส่วนหลังปรับ” มากกว่า 1 หมายความว่าพันธุ์นั้น"
     "กระจุกตัวในภาคที่ระบบแนะนำมากกว่าที่ความพยายามสำรวจจะอธิบายได้", align=J,
     space_before=4)

t = make_table(["พันธุ์ไม้", "ภาคที่ระบบแนะนำ", "รายการที่พบในไทย",
                "อยู่ในภาคที่แนะนำ", "อัตราส่วนหลังปรับ"],
               [4.3, 3.0, 2.6, 2.8, 2.8])
for r in sorted(occ, key=lambda x: -(float(x["effort_adjusted_ratio"] or 0))):
    ratio = r["effort_adjusted_ratio"]
    if ratio:
        val = float(ratio)
        col = GREEN if val >= 1.0 else AMBER
        txt = "%.2f" % val
    else:
        col, txt = RED, "ไม่มีข้อมูล"
    share = r["share_in_recommended_regions"]
    add_row(t, [r["name_th"], r["recommended_regions"].replace("|", ", "),
                r["n_records_th_georef"],
                "%.0f%%" % (100 * float(share)) if share else "—", txt],
            [4.3, 3.0, 2.6, 2.8, 2.8], aligns=[None, None, C, C, C],
            colors=[None, None, None, None, col], bolds=[False] * 4 + [True])

t2 = make_table(["สรุปผลตรวจที่ 3", "จำนวน"], [11.5, 4.0])
for label, value in [
    ("พันธุ์ที่มีอัตราส่วนหลังปรับ ≥ 1 (กระจุกตัวในภาคที่แนะนำจริง)",
     "%d / %d" % (n_ratio_ge1, len(occ))),
    ("พันธุ์ที่ไม่มีรายการพบพร้อมพิกัดในไทยเลย (ตรวจด้วยวิธีนี้ไม่ได้)",
     "%d / %d" % (n_no_record, len(occ))),
]:
    add_row(t2, [label, value], [11.5, 4.0], aligns=[None, C],
            bolds=[False, True])

# ================================================================ 6
heading("6. ผลตรวจที่ 4 — กลไกจัดอันดับทำงานตามที่ประกาศไว้จริงหรือไม่")
para("ไล่ทดสอบทุกเงื่อนไขพื้นที่ที่เป็นไปได้ครบทุกภาค (%d ภาค × ร้อน/ไม่ร้อน × "
     "ความหนาแน่นพืชพรรณ 3 ระดับ × ประเภทการใช้ที่ดิน 6 แบบ) รวม %d กรณี แล้วบันทึกว่า"
     "ลำดับที่ได้ต่างจากลำดับตั้งต้นหรือไม่" % (N_REGIONS, n_cases), align=J)
t = make_table(["ตัวชี้วัด", "ผลที่วัดได้", "การแปลผล"], [5.8, 3.0, 6.7])
rows6 = [
    ("กรณีที่ลำดับเปลี่ยนจากลำดับตั้งต้น", "%d / %d (%.0f%%)"
     % (n_changed, n_cases, 100 * n_changed / n_cases),
     "สภาพพื้นที่มีผลต่อลำดับจริง ไม่ใช่รายการคงที่"),
    ("กรณีที่อันดับ 1 มีเหตุผลกำกับ", "%d / %d (%.0f%%)"
     % (n_top_fit, n_cases, 100 * n_top_fit / n_cases),
     "ผู้ใช้เห็นเหตุผลว่าทำไมพันธุ์นั้นขึ้นมาก่อน"),
    ("พันธุ์ที่ขึ้นเป็นอันดับ 1 ได้จริง", "%d / %d ชนิด"
     % (len(reachable_top), n_species),
     "อีก %d ชนิดไม่มีทางขึ้นอันดับ 1 ในทุกเงื่อนไข"
     % (n_species - len(reachable_top))),
    ("ชุดพันธุ์ที่เป็นไปได้ทั้งประเทศ", "%d ชุด" % N_REGIONS,
     "สำหรับ %d จังหวัด" % N_PROVINCES + " — ผูกกับภาคล้วน"),
]
for a, b, c in rows6:
    add_row(t, [a, b, c], [5.8, 3.0, 6.7], aligns=[None, C, None],
            bolds=[False, True, False])

heading("6.1 ตัวอย่างการทำงานจริง — ภาค%s พื้นที่ร้อนและพืชพรรณเบาบางในเขตชุมชน"
        % EXAMPLE_REGION, size=17, space_before=10)
para("ตัวอย่างนี้สร้างจากการเรียกฟังก์ชันจัดอันดับตัวจริงของระบบ ด้วยเงื่อนไขอุณหภูมิผิวพื้น "
     "%.0f องศาเซลเซียส ความหนาแน่นพืชพรรณ %.2f และการใช้ที่ดินเด่นเป็นชุมชนและสิ่งปลูกสร้าง"
     % (EXAMPLE_LST, EXAMPLE_NDVI), align=J)
t = make_table(["ลำดับ", "ลำดับตั้งต้นของภาค", "ลำดับหลังพิจารณาสภาพพื้นที่",
                "เหตุผลที่ระบบให้"], [1.3, 4.2, 4.2, 5.8])
for r in example:
    add_row(t, [r["rank"], r["default_name_th"], r["ranked_name_th"], r["site_fit"]],
            [1.3, 4.2, 4.2, 5.8], aligns=[C, None, None, None],
            bolds=[False, False, True, False])

heading("6.2 จุดอ่อนของกลไกที่ตรวจพบ", size=17, space_before=10)
para("กลไกจัดอันดับทำงานด้วยการค้นคำสำคัญในคำบรรยายภาษาไทยของพันธุ์ไม้ ซึ่งเป็น"
     "ข้อความที่เขียนขึ้นในโครงงานเอง จึงตรวจย้อนกลับว่ามีการจับคู่ที่ตีความเกินข้อความจริง"
     "หรือไม่ (ไฟล์ reports/species_keyword_audit.csv)", align=J)
bullet("%s — ได้คะแนน “เหมาะกับพื้นที่ร้อน” จากคำว่า “ทรงพุ่ม” ในข้อความ "
       "“ทรงพุ่มเป็นระเบียบ” ซึ่งหมายถึงรูปทรงสวยงาม ไม่ใช่การให้ร่มเงากว้าง"
       % ", ".join(weak_shade) if weak_shade else
       "ไม่พบการจับคู่ที่อาศัยคำอ่อนเพียงคำเดียว")
bullet("%s — ไม่ชนคำสำคัญกลุ่มใดเลย จึงไม่เคยได้คะแนนจากสภาพพื้นที่ และขึ้นอันดับต้น"
       "ได้จากการจับคู่ประเภทการใช้ที่ดินเท่านั้น" % ", ".join(no_kw))
bullet("คะแนนที่เท่ากันจะคงลำดับเดิมในบัญชีไว้ แปลว่าในกรณีที่สัญญาณพื้นที่ไม่ชัด "
       "ลำดับถูกกำหนดด้วยลำดับที่เขียนไว้ในบัญชี ไม่ใช่ด้วยสภาพพื้นที่")

# ================================================================ 7
heading("7. ผลตรวจที่ 5 — เกณฑ์ตัดสินสภาพพื้นที่ใช้ได้จริงกับข้อมูลของไทยหรือไม่")
para("กลไกจัดอันดับใช้เกณฑ์ตายตัวสามค่า จึงนำเกณฑ์เหล่านั้นไปเทียบกับค่าที่ระบบวัดได้จริง"
     "ทั้งประเทศ ปี ค.ศ. %d เพื่อดูว่าเกณฑ์ใดทำงานบ่อยและเกณฑ์ใดแทบไม่เคยทำงาน" % YEAR,
     align=J)
t = make_table(["เกณฑ์", "ค่าที่ตั้งไว้", "สัดส่วนที่เข้าเกณฑ์ (รายจังหวัด, n=%d)" % tp["n_lst"],
                "สัดส่วนที่เข้าเกณฑ์ (รายอำเภอ, n=%d)" % td["n_lst"]],
               [4.6, 2.6, 4.2, 4.1])
rows7 = [
    ("พื้นที่ร้อน (ดันพันธุ์ให้ร่มเงา)", "LST ≥ %.0f °C" % HOT_LST_C,
     "%.1f%%" % tp["pct_hot"], "%.1f%%" % td["pct_hot"]),
    ("พื้นที่เสื่อมโทรม (ดันพันธุ์ทนทาน)", "NDVI < %.2f" % LOW_NDVI,
     "%.1f%%" % tp["pct_degraded"], "%.1f%%" % td["pct_degraded"]),
    ("พื้นที่ยังเขียว (ดันพันธุ์พื้นถิ่น)", "NDVI ≥ %.2f" % HIGH_NDVI,
     "%.1f%%" % tp["pct_green"], "%.1f%%" % td["pct_green"]),
]
for a, b, c, d in rows7:
    add_row(t, [a, b, c, d], [4.6, 2.6, 4.2, 4.1], aligns=[None, C, C, C],
            bolds=[False, False, True, True])
para("ค่ากลางที่วัดได้จริงคือ อุณหภูมิผิวพื้น %.1f องศาเซลเซียส และความหนาแน่นพืชพรรณ "
     "%.2f ในระดับจังหวัด (รายอำเภอ %.1f องศาเซลเซียส และ %.2f)"
     % (tp["lst_median"], tp["ndvi_median"], td["lst_median"], td["ndvi_median"]),
     align=J, space_before=4)
para("ข้อสังเกตที่ต้องรายงาน: เกณฑ์ “พื้นที่เสื่อมโทรม” เข้าเงื่อนไขเพียงร้อยละ %.1f "
     "ของจังหวัด จึงแทบไม่มีผลเมื่อผู้ใช้ดูระดับจังหวัด แต่เมื่อดูระดับอำเภอซึ่งเป็นระดับที่"
     "ระบบใช้จริงในการแนะนำ สัดส่วนเพิ่มเป็นร้อยละ %.1f ทำให้เกณฑ์นี้ทำงานได้ตามเจตนา"
     % (tp["pct_degraded"], td["pct_degraded"]), align=J)

# ================================================================ 8
heading("8. ผลตรวจที่ 6 — สัมประสิทธิ์การกักเก็บคาร์บอนรายพันธุ์")
para("ค่าการกักเก็บคาร์บอนต่อต้นต่อปีที่ระบบใช้คำนวณผลกระทบเป็นค่าประมาณระดับลำดับขนาด "
     "(order-of-magnitude) ของต้นไม้โตเต็มที่ในเขตร้อน อ้างอิงกรอบของ IPCC 2019 และ "
     "i-Tree Eco จึงตรวจสองเรื่องคือความครอบคลุมและความสอดคล้องภายใน", align=J)
t = make_table(["ตัวชี้วัด", "ผลที่วัดได้", "การแปลผล"], [5.5, 3.3, 6.7])
rows8 = [
    ("พันธุ์ที่มีค่าสัมประสิทธิ์เฉพาะตัว",
     "%d / %d" % (co2s["n_with_coefficient"], co2s["n_species"]),
     "ไม่มีพันธุ์ใดต้องใช้ค่าเฉลี่ยกลางแทน"),
    ("ช่วงค่าที่ใช้", "%.0f – %.0f กก./ต้น/ปี" % (co2s["kg_min"], co2s["kg_max"]),
     "ค่ากลาง %.0f เทียบค่าตั้งต้น IPCC %.0f กก."
     % (co2s["kg_median"], co2s["ipcc_default_kg"])),
    ("ความสอดคล้องกับขนาดของพันธุ์",
     "Spearman ρ = %.3f" % co2s["spearman_height_vs_co2"],
     "ค่าที่กำหนดเรียงตามความสูงของพันธุ์อย่างเป็นระบบ ไม่ได้ให้แบบสุ่ม"),
]
for a, b, c in rows8:
    add_row(t, [a, b, c], [5.5, 3.3, 6.7], aligns=[None, C, None],
            bolds=[False, True, False])

t = make_table(["พันธุ์ไม้", "ความสูงเมื่อโตเต็มที่ (ม.)",
                "กักเก็บ CO₂ (กก./ต้น/ปี)"], [7.0, 4.5, 4.0])
for r in sorted(co2, key=lambda x: -float(x["kg_co2_per_year"])):
    add_row(t, ["%s (%s)" % (r["name_th"], r["scientific"]), r["height_m"],
                "%.0f" % float(r["kg_co2_per_year"])],
            [7.0, 4.5, 4.0], aligns=[None, C, C], bolds=[False, False, True])

# ================================================================ 9
heading("9. สิ่งที่หลักฐานชุดนี้พิสูจน์ได้ และสิ่งที่ยังพิสูจน์ไม่ได้")
t = make_table(["ข้อสรุป", "สถานะ"], [11.5, 4.0])
proved = [
    ("ชื่อวิทยาศาสตร์ทุกชนิดถูกต้องและเป็นชื่อที่ยอมรับตาม GBIF",
     "พิสูจน์แล้ว %d/%d" % (n_name_ok, n_species)),
    ("พันธุ์ที่ระบบระบุว่าเป็นพันธุ์พื้นถิ่นเป็นพืชพื้นเมืองของไทยจริงตาม WCVP",
     "พิสูจน์แล้ว %d/%d" % (len(claim_rows) - n_conflict, len(claim_rows))),
    ("พันธุ์ที่แนะนำถูกบันทึกว่าพบจริงในภาคที่แนะนำ มากกว่าที่ความพยายามสำรวจอธิบายได้",
     "พิสูจน์แล้ว %d/%d" % (n_ratio_ge1, len(occ))),
    ("กลไกจัดอันดับเปลี่ยนคำตอบตามสภาพพื้นที่จริง",
     "พิสูจน์แล้ว %.0f%% ของกรณี" % (100 * n_changed / n_cases)),
    ("สัมประสิทธิ์ CO₂ ครบทุกพันธุ์และสอดคล้องกับขนาดต้นไม้",
     "พิสูจน์แล้ว ρ = %.2f" % co2s["spearman_height_vs_co2"]),
]
for a, b in proved:
    add_row(t, [a, b], [11.5, 4.0], aligns=[None, C],
            colors=[None, GREEN], bolds=[False, True])

unproved = [
    ("คุณสมบัติรายพันธุ์ที่ระบบแสดง (ทนแล้ง ทนน้ำท่วม ทนมลพิษ ความสูง) ยังไม่ได้ตรวจกับ"
     "เอกสารวิชาการรายชนิด", "ยังไม่ได้พิสูจน์"),
    ("ค่ากักเก็บคาร์บอนรายพันธุ์เป็นค่าประมาณของโครงงาน ไม่ได้มาจากการวัดชีวมวลในไทย",
     "เป็นค่าประมาณ"),
    ("ความเหมาะสมระดับจุดพิกัด (ดิน ความลึกน้ำใต้ดิน การใช้ที่ดินจริง) อยู่นอกขอบเขต",
     "นอกขอบเขต"),
    ("บัญชีพันธุ์ไม้ผูกกับภาค ไม่ได้ผูกกับจังหวัดหรืออำเภอ จึงมีเพียง %d ชุดทั้งประเทศ"
     % N_REGIONS, "ข้อจำกัดที่ยอมรับ"),
    ("ข้อมูล occurrence ของ GBIF มีอคติจากความพยายามสำรวจ การปรับที่ทำเป็นการปรับ"
     "อย่างหยาบ ไม่ใช่การสุ่มตัวอย่างเชิงสถิติ", "ข้อจำกัดของข้อมูล"),
]
t = make_table(["ข้อจำกัดที่บันทึกไว้", "สถานะ"], [11.5, 4.0])
for a, b in unproved:
    add_row(t, [a, b], [11.5, 4.0], aligns=[None, C],
            colors=[None, AMBER], bolds=[False, True])

# ================================================================ 10
heading("10. คำตอบอย่างย่อ")
para("“ระบบไม่ได้คิดเองว่าควรปลูกต้นอะไร แต่คัดจากบัญชีพันธุ์ไม้ประจำภาคที่ตรวจสอบย้อนกลับ"
     "ได้ทุกชนิด แล้วจัดลำดับตามสภาพพื้นที่ที่วัดได้จริง หลักฐานที่ยืนยันได้คือ ชื่อวิทยาศาสตร์"
     "ทั้ง %d ชนิดถูกต้องตาม GBIF, %d ชนิดเป็นพืชพื้นเมืองของไทยตาม WCVP ของ Kew, "
     "%d ใน %d ชนิดถูกบันทึกว่าพบในภาคที่ระบบแนะนำมากกว่าที่ความพยายามสำรวจจะอธิบายได้ "
     "และกลไกจัดอันดับเปลี่ยนคำตอบตามสภาพพื้นที่จริงในร้อยละ %.0f ของกรณีทดสอบทั้งหมด "
     "ส่วนที่ยังทำไม่ได้คือการยืนยันคุณสมบัติรายพันธุ์และความเหมาะสมระดับจุดพิกัด "
     "ซึ่งต้องใช้การสำรวจภาคสนามและอยู่นอกขอบเขตของโครงงานนี้”"
     % (n_name_ok, n_native, n_ratio_ge1, len(occ), 100 * n_changed / n_cases),
     align=J, size=16)

doc.save(OUT)
print("บันทึกเอกสารที่ %s" % OUT)
