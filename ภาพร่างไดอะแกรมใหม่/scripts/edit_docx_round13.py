#!/usr/bin/env python3
"""แก้ `บทที่ 3.docx` รอบ 13 — ตามผลตรวจรีวิว Class Diagram จากภายนอกชุดที่ 4

สิ่งที่แก้ (ทั้งหมดยืนยันกับ migrations/ + routers/ + src/ แล้ว ดูบันทึกใน gen_class.py):
  1. ชนิดข้อมูลของ Boundary/Control/Service — ชนิด PostgreSQL → UML DataType
     bool→Boolean · text→String · int4→Integer · numeric/float8→Real · uuid→UUID
  2. พารามิเตอร์ snake_case → camelCase (เฉพาะเมธอด · ข้อความที่บรรยายการอ่าน/เขียน
     คอลัมน์จริงใน §3.6 ยังใช้ชื่อคอลัมน์เดิม เช่น "อ่านโปรไฟล์ตาม user_id")
  3. analyzeUrbanGreenShare(province, year) → (province, district, year)
     — urban.py:127 รับ district_name และ cache key คือ (urban, province, district, year)
  4. generatePlantingPoints(province, district) → (province, district, year)
     — endpoints.py:255,265 รับ year และตารางมี UNIQUE (province, district, year)
  5. exportReportData() → buildReportDocument() + แก้คำอธิบายให้แยกหน้าที่กับ
     AnalysisReportView.exportReport() ได้ชัด
  6. ฝังรูป Class Diagram + Sequence Diagram 8/9/10 ที่วาดใหม่ พร้อมแก้ <wp:extent>

วิธีรัน (ต้อง unzip .docx ไป /tmp/ch3/x และรัน merge_runs.py มาก่อน):
    green-area-backend/venv/bin/python ภาพร่างไดอะแกรมใหม่/scripts/edit_docx_round13.py
"""
import os
import re
import shutil
import zipfile

from PIL import Image

X = '/tmp/ch3/x'
DOC = f'{X}/word/document.xml'
HERE = os.path.dirname(os.path.abspath(__file__))
DRAFTS = os.path.join(HERE, '..')
PROJ = os.path.join(HERE, '..', '..')
SRC = os.path.join(PROJ, 'บทที่ 3.docx')
OUT = os.path.join(PROJ, 'บทที่ 3.docx')

d = open(DOC, encoding='utf-8').read()
_n = 0


def sub(old, new, count=1):
    """แทนที่แบบระบุจำนวนครั้งที่คาดไว้ — assert ทุกครั้ง กัน typo แล้วเงียบ"""
    global d, _n
    got = d.count(old)
    assert got == count, f'{old!r}: พบ {got} ครั้ง คาดว่า {count}'
    d = d.replace(old, new)
    _n += got


def set_type(attr, old, new, count=1):
    """แก้ชนิดข้อมูลในเซลล์ที่ 2 ของแถวที่คอลัมน์แรกคือ `- attr`

    ตาราง §3.5 มีสองแบบปนกัน: บางเซลล์เป็น <w:t>bool</w:t> บางเซลล์เป็น
    <w:t xml:space="preserve">bool</w:t> (มาจากคนละรอบการแก้) จึงต้องรับทั้งสองแบบ
    """
    global d, _n
    key = re.compile(r'<w:t(?: xml:space="preserve")?>- %s</w:t>' % re.escape(attr))
    tgt = re.compile(r'<w:t(?: xml:space="preserve")?>%s</w:t>' % re.escape(old))
    n, pos = 0, 0
    while True:
        km = key.search(d, pos)
        if not km:
            break
        tm = tgt.search(d, km.end())
        assert tm and tm.start() - km.end() < 1500, f'{attr}: ไม่เจอ {old} ในแถวเดียวกัน'
        d = d[:tm.start()] + f'<w:t>{new}</w:t>' + d[tm.end():]
        pos, n = tm.start(), n + 1
    assert n == count, f'{attr}: แก้ {n} ครั้ง คาดว่า {count}'
    _n += n


# ── 1) ชนิดข้อมูล: PostgreSQL → UML DataType ─────────────────────────────────
for _a in ('isLoaded', 'isDescending', 'isDrawingActive', 'cacheStatus', 'isSubmitting'):
    set_type(_a, 'bool', 'Boolean')
for _a in ('themeMode', 'activeLayer', 'reportType', 'selectedProvince', 'selectedDistrict',
           'recommendationEngineVersion', 'email', 'sessionToken', 'displayName',
           'organization'):
    set_type(_a, 'text', 'String')
for _a in ('mapZoom', 'currentYear'):
    set_type(_a, 'int4', 'Integer')
set_type('currentShapeArea', 'numeric', 'Real')
set_type('whoStandardThreshold', 'float8', 'Real')
set_type('currentUserId', 'uuid', 'UUID', count=2)   # SavedAreaManager + ProfileController

# ── 2) ลายเซ็นเมธอดในตาราง §3.5 ──────────────────────────────────────────────
sub('+ analyzeUrbanGreenShare(province, year)',
    '+ analyzeUrbanGreenShare(province, district, year)')
sub('+ evaluateWHOCriteria(green_m2_per_person)',
    '+ evaluateWHOCriteria(greenAreaM2PerPerson)')
sub('+ generatePlantingPoints(province, district)',
    '+ generatePlantingPoints(province, district, year)')
sub('+ getSavedAreas(user_id : uuid)', '+ getSavedAreas(userId : UUID)')
sub('+ validateOwner(id, user_id : uuid)', '+ validateOwner(id, userId : UUID)')
sub('+ changePassword(current, new)', '+ changePassword(currentPassword, newPassword)')
sub('+ getProfile(user_id)', '+ getProfile(userId)')
sub('+ updateProfile(display_name, organization)',
    '+ updateProfile(displayName, organization)')

# ── 3) แยกหน้าที่ส่งออกรายงานให้ชื่อบอกเองว่าใครทำอะไร ───────────────────────
# `ส่งออกข้อมูลรายงาน` มี 2 ที่ในเอกสาร — แก้เฉพาะแถวของ exportReportData()
_i = d.index('+ exportReportData()')
_j = d.index('ส่งออกข้อมูลรายงาน', _i)
d = d[:_j] + 'ประกอบเนื้อหารายงานเป็นเอกสารก่อนส่งออก' + d[_j + len('ส่งออกข้อมูลรายงาน'):]
_n += 1
sub('+ exportReportData()', '+ buildReportDocument()')
sub('สั่งส่งออกรายงานเป็นไฟล์', 'สั่งบันทึกเอกสารรายงานเป็นไฟล์ให้ผู้ใช้')

# ── 4) คำบรรยายขั้นตอนใน §3.6 (เฉพาะที่อ้างชื่อเมธอด ไม่ใช่ชื่อคอลัมน์) ──────
sub('เรียก analyzeUrbanGreenShare(province, year) ที่',
    'เรียก analyzeUrbanGreenShare(province, district, year) ที่')
sub('evaluateWHOCriteria(green_m2_per_person) ภายใน',
    'evaluateWHOCriteria(greenAreaM2PerPerson) ภายใน')
sub('เรียก generatePlantingPoints(province, district) ที่',
    'เรียก generatePlantingPoints(province, district, year) ที่')
sub('เรียก getProfile(user_id) ที่', 'เรียก getProfile(userId) ที่')
sub('เรียก updateProfile(display_name, organization) ที่',
    'เรียก updateProfile(displayName, organization) ที่')

# ── 5) ฝังรูปใหม่ + แก้ <wp:extent> และ <a:ext> ให้ตรงอัตราส่วนจริง ───────────
CX = 5220000                      # 14.50 ซม. — ความกว้างพิมพ์คงที่ทุกภาพในเล่ม
IMAGES = {                        # rId -> (ไฟล์ใน media, ไฟล์ต้นทางที่วาดใหม่)
    'rId19': ('diagram_class.png', 'class_new.png'),
    'rId54': ('diagram_seq08.png', 'Sequence Diagram 08 (ร่าง).png'),
    'rId55': ('diagram_seq09.png', 'Sequence Diagram 09 (ร่าง).png'),
    'rId56': ('diagram_seq10.png', 'Sequence Diagram 10 (ร่าง).png'),
}
for rid, (dst, src) in IMAGES.items():
    src_path = os.path.join(DRAFTS, src)
    shutil.copyfile(src_path, f'{X}/word/media/{dst}')
    w, h = Image.open(src_path).size
    cy = round(CX * h / w)
    # ขอบเขตของ <w:drawing> ที่มี r:embed ตัวนี้ — cx/cy โผล่ 2 ที่ (wp:extent + a:ext)
    i = d.index(f'r:embed="{rid}"')
    a, b = d.rindex('<w:drawing>', 0, i), d.index('</w:drawing>', i)
    blk = d[a:b]
    old_cy = re.search(r'cx="%d" cy="(\d+)"' % CX, blk).group(1)
    new_blk = blk.replace(f'cx="{CX}" cy="{old_cy}"', f'cx="{CX}" cy="{cy}"')
    assert new_blk.count(f'cy="{cy}"') == 2, f'{rid}: ต้องแก้ cy 2 จุด'
    d = d[:a] + new_blk + d[b:]
    print(f'  {rid} {dst:20s} {w}×{h}  cy {old_cy} → {cy}'
          f'  ({CX / 360000:.2f}×{cy / 360000:.2f} ซม.)'
          + ('' if old_cy != str(cy) else '  [เท่าเดิม]'))

open(DOC, 'w', encoding='utf-8').write(d)
print(f'แก้ข้อความ {_n} จุด')

# ── 6) rezip โดยเดินตาม infolist() ของไฟล์ต้นฉบับ ────────────────────────────
# ห้ามใช้ `zip -Xr` — zip cli ใส่ entry ไดเรกทอรีเพิ่ม ทำให้แพ็กเกจต่างจากเดิม
with zipfile.ZipFile(SRC) as z:
    order = [i.filename for i in z.infolist()]
tmp = OUT + '.tmp'
with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED) as z:
    for name in order:
        z.write(os.path.join(X, name), name)
os.replace(tmp, OUT)
print('เขียน', OUT)
