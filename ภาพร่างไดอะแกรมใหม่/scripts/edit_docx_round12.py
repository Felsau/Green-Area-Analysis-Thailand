#!/usr/bin/env python3
"""แก้ บทที่ 3.docx รอบ 12 — Class Diagram + Sequence Diagram ที่กระทบ

ทุกการแก้ค้นด้วยข้อความจริง ไม่ใช้ offset ตายตัว (offset ขยับทุกครั้งที่แก้)
"""
import random
import re
import pathlib

_minted = set()

X = pathlib.Path('/tmp/ch3/x/word/document.xml')
d = X.read_text(encoding='utf-8')
log = []


def _row_bounds(i):
    """ขอบเขต <w:tr> ที่ครอบตำแหน่ง i"""
    a = max(d.rfind('<w:tr ', 0, i), d.rfind('<w:tr>', 0, i))
    b = d.find('</w:tr>', i) + 7
    assert a != -1 and b > a, f'หา <w:tr> ไม่เจอที่ {i}'
    return a, b


def find_row(needle, occ=0):
    """คืนขอบเขตแถวที่มี <w:t> ตรงกับ needle พอดี"""
    hits = [m.start() for m in re.finditer(
        r'<w:t[^>]*>' + re.escape(needle) + r'</w:t>', d)]
    assert hits, f'ไม่เจอข้อความ: {needle!r}'
    return _row_bounds(hits[occ])


def set_text(old, new, count=None):
    global d
    pat = r'(<w:t[^>]*>)' + re.escape(old) + r'(</w:t>)'
    n = len(re.findall(pat, d))
    assert n, f'ไม่เจอข้อความ: {old!r}'
    if count is not None:
        assert n == count, f'{old!r} เจอ {n} ครั้ง (คาด {count})'
    d = re.sub(pat, lambda m: m.group(1) + new + m.group(2), d)
    log.append(f'ข้อความ  {old!r} → {new!r}  ({n} จุด)')


def del_row(needle):
    global d
    a, b = find_row(needle)
    d = d[:a] + d[b:]
    log.append(f'ลบแถว   {needle!r}')


def cut_row(needle):
    """ตัดแถวออกแล้วคืน XML ของแถวนั้น"""
    global d
    a, b = find_row(needle)
    row = d[a:b]
    d = d[:a] + d[b:]
    return row


def paste_after(needle, rows_xml):
    global d
    a, b = find_row(needle)
    d = d[:b] + rows_xml + d[b:]
    log.append(f'ย้ายแถว  {len(rows_xml)} ไบต์ ไปต่อจาก {needle!r}')


def _fresh_para_id():
    """paraId ใหม่ที่ไม่ซ้ำในเอกสาร · ต้อง < 0x80000000 ไม่งั้น Word/XSD ไม่รับ"""
    while True:
        v = '%08X' % random.getrandbits(31)
        if v != '00000000' and v not in _minted and f'"{v}"' not in d:
            _minted.add(v)
            return v


def clone_row(template_needle, col1, col2):
    """สร้างแถวใหม่จากแถวต้นแบบ (2 ช่อง) โดยเปลี่ยนข้อความทั้งสองช่อง
    paraId/textId ต้องสุ่มใหม่ทุกอัน — ซ้ำกันแล้ว Word จะรวมย่อหน้าเข้าด้วยกัน"""
    a, b = find_row(template_needle)
    row = d[a:b]
    for attr in ('w14:paraId', 'w14:textId'):
        row = re.sub(attr + r'="[0-9A-Fa-f]{8}"',
                     lambda m: f'{attr}="{_fresh_para_id()}"', row)
    ts = re.findall(r'<w:t[^>]*>[^<]*</w:t>', row)
    assert len(ts) == 2, f'แถวต้นแบบมี {len(ts)} ช่อง (ต้องการ 2)'
    for old, new in zip(ts, (col1, col2)):
        row = row.replace(old, re.sub(r'(<w:t[^>]*>)[^<]*(</w:t>)',
                                      lambda m: m.group(1) + new + m.group(2), old), 1)
    return row


def add_row_after(needle, col1, col2):
    global d
    row = clone_row(needle, col1, col2)
    a, b = find_row(needle)
    d = d[:b] + row + d[b:]
    log.append(f'เพิ่มแถว {col1!r} ต่อจาก {needle!r}')


# ── 1) GISDataService — tileServerUrl ไม่มีอยู่จริง · service ไม่ได้ render ────
del_row('- tileServerUrl')
set_text('+ renderMapTile(tile_url)', '+ getTileUrl(kind, province, year)', 1)
set_text('แสดงผลภาพ tile บนแผนที่', 'คืน URL ภาพ tile ให้หน้าจอแผนที่นำไปแสดง', 1)

# ── 2) SavedAreaManager — createSavedArea รับ year ด้วย ──────────────────────
set_text('+ createSavedArea(label, geometry, province)',
         '+ createSavedArea(label, geometry, province, year)')

# ── 3) AnalysisReportView — เพิ่ม exportReport() ให้ exportReportData() มีคนเรียก ─
add_row_after('+ sortData(criteria)', '+ exportReport()', 'สั่งส่งออกรายงานเป็นไฟล์')

# ── 4) LoginView → AuthView (ครอบทั้งเข้าสู่ระบบ/สมัคร/ตั้งรหัสผ่านใหม่) ──────
set_text('ตาราง 57 Class Description : LoginView (Attribute)',
         'ตาราง 57 Class Description : AuthView (Attribute)', 1)
set_text('ตาราง 58 Class Description : LoginView (Method)',
         'ตาราง 58 Class Description : AuthView (Method)', 1)
set_text('Class Name : LoginView', 'Class Name : AuthView', 2)
set_text('Description : หน้าจอเข้าสู่ระบบและสมัครสมาชิก',
         'Description : หน้าจอยืนยันตัวตน เข้าสู่ระบบ สมัครสมาชิก และตั้งรหัสผ่านใหม่', 2)
set_text('+ submitLogin()', '+ submitSignIn()', 1)
set_text('ส่งข้อมูลเข้าสู่ระบบไปตรวจสอบ', 'ส่งอีเมลและรหัสผ่านไปตรวจสอบ', 1)
set_text('+ requestPasswordReset()', '+ submitForgotPassword()', 1)
add_row_after('+ submitForgotPassword()', '+ submitNewPassword()',
              'ส่งรหัสผ่านใหม่หลังกดลิงก์ที่ได้รับทางอีเมล')

# ── 5) ProfileView — เพิ่ม submitEmailChange() ให้ตรงกับ AccountModal ────────
add_row_after('+ submitPasswordChange()', '+ submitEmailChange()',
              'ส่งอีเมลใหม่ไปเปลี่ยนอีเมลของบัญชี')

# ── 6) ย้ายเมธอดที่แก้ข้อมูลยืนยันตัวตน ProfileController → AuthController ────
#     ของจริงอยู่ใน src/hooks/useAuth.js โมดูลเดียวกับ signIn/signUp ทั้งหมด
_cp = cut_row('+ changePassword(current, new)')
_ce = cut_row('+ changeEmail(newEmail)')
_da = cut_row('+ deleteAccount()')
_so = cut_row('+ signOut()')                      # ย้ายไปท้ายสุดให้เรียงตามภาพ
paste_after('+ resetPassword(newPassword)', _cp + _ce + _da + _so)

set_text('Description : ตัวควบคุมการยืนยันตัวตนของผู้ใช้งาน',
         'Description : ตัวควบคุมการยืนยันตัวตนและข้อมูลบัญชีผู้ใช้งาน', 2)
set_text('Description : ตัวควบคุมการจัดการบัญชีและโปรไฟล์',
         'Description : ตัวควบคุมข้อมูลโปรไฟล์ผู้ใช้งาน', 2)

# ── 7) §3.6 คำอธิบาย Sequence Diagram 1–2 และ 7 ─────────────────────────────
n = d.count('หน้าจอเข้าสู่ระบบ (LoginView)')
assert n == 8, f'คาด 8 จุด เจอ {n}'
d = d.replace('หน้าจอเข้าสู่ระบบ (LoginView)', 'หน้าจอยืนยันตัวตน (AuthView)')
log.append(f'ข้อความ  หน้าจอเข้าสู่ระบบ (LoginView) → หน้าจอยืนยันตัวตน (AuthView)  ({n} จุด)')
assert 'LoginView' not in d, 'ยังเหลือ LoginView'

# ── 8) ขนาดภาพ Class Diagram 1682×1518 → 1707×1614 ──────────────────────────
CX, OLD_CY, NEW_CY = 5220000, 4711034, 4935606
i = d.find('rId19')
a = d.rfind('<w:drawing>', 0, i)
b = d.find('</w:drawing>', i) + 12
blk = d[a:b]
assert blk.count(f'cy="{OLD_CY}"') == 2, blk.count(f'cy="{OLD_CY}"')
d = d[:a] + blk.replace(f'cy="{OLD_CY}"', f'cy="{NEW_CY}"') + d[b:]
log.append(f'ขนาดภาพ Class Diagram cy {OLD_CY} → {NEW_CY} '
           f'({CX/360000:.2f} × {NEW_CY/360000:.2f} ซม.)')

X.write_text(d, encoding='utf-8')
print('\n'.join(log))
print(f'\nเขียนแล้ว {len(d)} ไบต์')
