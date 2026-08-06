#!/usr/bin/env python3
"""Use Case Diagram — ระบบแดชบอร์ดติดตามพื้นที่สีเขียวและเกาะความร้อนในเขตเมือง
21 use case · 2 คอลัมน์ (เยื้องแถวกันเพื่อให้เส้นเชื่อมลอดผ่านช่องว่าง)"""
import os, sys, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from diagram import Canvas, WHITE

G, R, A = 'guest', 'reg', 'admin'

COL_A = [
    (['เข้าสู่ระบบ'], G),
    (['สมัครสมาชิก'], G),
    (['ดูอันดับพื้นที่สีเขียว', 'ระดับประเทศ'], G),
    (['ค้นหาตำแหน่ง'], R),
    (['ดูข้อมูล NDVI'], R),
    (['เปรียบเทียบพื้นที่'], R),
    (['ดูข้อมูล LST'], R),
    (['วิเคราะห์แนวโน้ม', 'และพยากรณ์'], R),
    (['ดูเลเยอร์การใช้', 'ประโยชน์ที่ดิน'], R),
    (['ดูภาพเคลื่อนไหวย้อนหลัง', '(Time-lapse)'], R),
    (['ดูสถิติเขตเมือง'], R),
]
COL_B = [
    (['บันทึกพื้นที่โปรด'], R),
    (['ขอคำแนะนำปลูกต้นไม้'], R),
    (['ดูคำแนะนำพันธุ์ไม้'], R),
    (['ดูรายงานผลกระทบ', 'และมูลค่าระบบนิเวศ'], R),
    (['ปรับน้ำหนักปัจจัย', 'จัดลำดับความสำคัญ'], R),
    (['ส่งออกรายงาน'], R),
    (['จัดการข้อมูลโปรไฟล์'], R),
    (['เปลี่ยนรหัสผ่าน'], R),
    (['ลบบัญชี'], R),
    (['จัดการข้อมูล/แคช'], A),
]
# (คอลัมน์, จาก, ไป, ชนิด, เลน, ตำแหน่งป้าย)
REL = [
    ('A', 5, 4, 'include', 0, 0.5),    # เปรียบเทียบพื้นที่ -> ดูข้อมูล NDVI
    ('A', 5, 6, 'include', 0, 0.5),    # เปรียบเทียบพื้นที่ -> ดูข้อมูล LST
    ('B', 1, 2, 'include', 0, 0.5),    # ขอคำแนะนำปลูกต้นไม้ -> ดูคำแนะนำพันธุ์ไม้
    ('B', 1, 3, 'include', 1, 0.80),   # ขอคำแนะนำปลูกต้นไม้ -> ดูรายงานผลกระทบ
    ('B', 4, 1, 'extend', 2, 0.26),     # ปรับน้ำหนักปัจจัย -> ขอคำแนะนำปลูกต้นไม้
]

RX, RY = 132, 30
PITCH = 92
AX = 68
BX0, BX1 = 138, 928
XA, XB = 290, 650
Y0A, Y0B = 112, 158
LANE_A = [462]
LANE_B = [808, 845, 882]

ysA = [Y0A + i * PITCH for i in range(len(COL_A))]
ysB = [Y0B + i * PITCH for i in range(len(COL_B))]
H = max(ysA[-1], ysB[-1]) + RY + 74
W = 962
c = Canvas(W, H)

c.rect(BX0, 44, BX1, H - 34, width=1.4)
c.text((BX0 + BX1) / 2, 66,
       'ระบบแดชบอร์ดติดตามพื้นที่สีเขียวและเกาะความร้อนในเขตเมือง', 18, bold=True)

guest_y, reg_y, admin_y = ysA[0] + 2, ysA[4] + 16, ysA[9] + 10
c.actor(AX, guest_y, 'ผู้เยี่ยมชมทั่วไป')
c.actor(AX, reg_y, 'ผู้ใช้ลงทะเบียน')
c.actor(AX, admin_y, 'ผู้ดูแลระบบ')


def generalize(y_from, y_to):
    c.line(AX, y_from - 26, AX, y_to + 92, 1.2)
    c.arrow_head(AX, y_to + 80, -math.pi / 2, size=13, hollow=True)


generalize(reg_y - 24, guest_y)
generalize(admin_y - 24, reg_y)


def edge(cx, cy, tx, ty):
    dx, dy = tx - cx, ty - cy
    k = math.hypot(dx / RX, dy / RY)
    return (cx + dx / k, cy + dy / k) if k else (cx, cy)


SRC = {G: (AX, guest_y + 12), R: (AX, reg_y + 12), A: (AX, admin_y + 12)}
COLS = (('A', XA, ysA, COL_A), ('B', XB, ysB, COL_B))

# 1) เส้น association วาดก่อน
for _, xs, ys, items in COLS:
    for (rows, who), y in zip(items, ys):
        sx, sy = SRC[who]
        ex, ey = edge(xs, y, sx, sy)
        c.line(sx + 18, sy, ex, ey, 1.0)

# 2) halo แล้วค่อยวงรี — เส้นที่ลอดผ่านจะถูกเว้นระยะให้เห็นชัดว่าไม่ได้เชื่อมกัน
for _, xs, ys, items in COLS:
    for (rows, who), y in zip(items, ys):
        c.halo(xs, y, RX, RY)
    for (rows, who), y in zip(items, ys):
        c.ellipse(xs, y, RX, RY, width=1.2)
        c.lines(xs, y, rows, 18)

# 3) include / extend
for col, frm, to, kind, lane, frac in REL:
    ys = ysA if col == 'A' else ysB
    xs = XA if col == 'A' else XB
    lx = (LANE_A if col == 'A' else LANE_B)[lane]
    y1, y2 = ys[frm], ys[to]
    c.line(xs + RX, y1, lx, y1, 1.0, dash=(7, 5, 0))
    c.line(lx, y1, lx, y2, 1.0, dash=(7, 5, 0))
    c.line(lx, y2, xs + RX + 12, y2, 1.0, dash=(7, 5, 0))
    c.arrow_head(xs + RX + 2, y2, math.pi, size=10)
    label = '«include»' if kind == 'include' else '«extend»'
    ym = y1 + (y2 - y1) * frac
    tw = c.textw(label, 15)
    c.d.rectangle([(lx - tw / 2 - 3) * 3, (ym - 11) * 3,
                   (lx + tw / 2 + 3) * 3, (ym + 11) * 3], fill=WHITE)
    c.text(lx, ym, label, 15)

c.save('/tmp/uc_new.png')
print('saved', (W, H), 'aspect 1:%.3f' % (H / W),
      '· พิมพ์กว้าง 14.65 ซม. → สูง %.1f ซม.' % (14.65 * H / W))
