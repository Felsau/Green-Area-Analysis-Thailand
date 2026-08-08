#!/usr/bin/env python3
"""Entity-Relationship Diagram — สร้างจากสคีมาจริงใน green-area-backend/migrations

รัน: python "ภาพร่างไดอะแกรมใหม่/scripts/gen_er.py"
ต้องมี Pillow (อยู่ใน green-area-backend/requirements.txt) + ฟอนต์ THSarabunNew.ttf

⚠️ ก่อนแก้ไฟล์นี้ ให้เปิด migrations/ อ่านของจริงเสมอ — เคยมีรอบที่ไดอะแกรมวาด FK
ที่ไม่มีอยู่จริงในฐานข้อมูล เพราะเดาจากชื่อคอลัมน์ว่า "น่าจะมี"
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from diagram import Canvas, BLACK, WHITE          # noqa: E402,F401

P, F, _ = 'PK', 'FK', ''
TABLES = {
    # จัดการโดย Supabase Auth (GoTrue) — ไม่ได้อยู่ใน migrations ของโปรเจกต์ แต่ต้อง
    # แสดงไว้เพราะ profiles.id และ saved_areas.user_id อ้างถึงตารางนี้จริง
    'auth.users': [(P, 'id'), (_, 'email'), (_, 'created_at')],
    'provinces': [(P, 'name_en'), (_, 'name_th'), (_, 'region'), (_, 'worldcover_green_pct')],
    'districts': [(P, 'id'), (F, 'province'), (_, 'name_en'), (_, 'name_th'), (_, 'area_km2')],
    'province_population': [(P, 'id'), (F, 'province'), (_, 'year'), (_, 'population')],
    'ndvi_annual': [
        (P, 'id'), (F, 'province'), (_, 'year'), (_, 'ndvi_mean'), (_, 'ndvi_min'),
        (_, 'ndvi_max'), (_, 'green_area_pct'), (_, 'green_area_km2'), (_, 'dense_area_pct'),
        (_, 'dense_area_km2'), (_, 'total_area_km2'), (_, 'green_area_m2_per_person'),
        (_, 'population'), (_, 'population_year'), (_, 'who_status'), (_, 'data_quality'),
        (_, 'canopy'), (_, 'validation'), (_, 'created_at'), (_, 'cache_version')],
    'ndvi_monthly': [(P, 'id'), (F, 'province'), (_, 'year'), (_, 'monthly_data'),
                     (_, 'created_at'), (_, 'cache_version')],
    'province_lst_annual': [(P, 'id'), (F, 'province'), (_, 'year'), (_, 'lst_mean'),
                            (_, 'lst_min'), (_, 'lst_max'), (_, 'created_at'), (_, 'cache_version')],
    'province_lst_monthly': [(P, 'id'), (F, 'province'), (_, 'year'), (_, 'monthly_data'),
                             (_, 'created_at'), (_, 'cache_version')],
    'district_ndvi_annual': [
        (P, 'id'), (F, 'province'), (F, 'district'), (_, 'year'), (_, 'ndvi_mean'),
        (_, 'ndvi_min'), (_, 'ndvi_max'), (_, 'green_area_pct'), (_, 'green_area_km2'),
        (_, 'dense_area_pct'), (_, 'dense_area_km2'), (_, 'total_area_km2'),
        (_, 'data_quality'), (_, 'canopy'), (_, 'created_at'), (_, 'cache_version')],
    'district_ndvi_monthly': [(P, 'id'), (F, 'province'), (F, 'district'), (_, 'year'),
                              (_, 'monthly_data'), (_, 'created_at'), (_, 'cache_version')],
    'district_lst_annual': [(P, 'id'), (F, 'province'), (F, 'district'), (_, 'year'),
                            (_, 'lst_mean'), (_, 'lst_min'), (_, 'lst_max'),
                            (_, 'created_at'), (_, 'cache_version')],
    'district_lst_monthly': [(P, 'id'), (F, 'province'), (F, 'district'), (_, 'year'),
                             (_, 'monthly_data'), (_, 'created_at'), (_, 'cache_version')],
    # district ไม่ใช่ FK — migration 007 สร้าง composite FK ให้เฉพาะ 4 ตาราง district_*
    # ตารางนี้ปล่อย district เป็น NULL ได้ (= แถวระดับจังหวัด) จึงไม่ผูก FK ไว้
    # tile_url ถูกตัดใน migration 020 — ย้ายไป in-process TTL cache ตั้งแต่ 004 แล้ว
    'planting_recommendations': [(P, 'id'), (F, 'province'), (_, 'district'), (_, 'year'),
                                 (_, 'top_locations'), (_, 'impact'),
                                 (_, 'created_at'), (_, 'cache_version')],
    # who_urban_pass ถูกตัดใน migration 023 — ไม่มีโค้ดอ่าน (verdict ผ่าน/ไม่ผ่านซ้ำ
    # แบบเดียวกับ who_status เดิม แต่ไม่มีใครแตะเลยตั้งแต่สร้าง)
    'urban_ndvi_annual': [
        (P, 'id'), (F, 'province'), (_, 'district'), (_, 'year'), (_, 'worldcover_year'),
        (_, 'worldpop_year'), (_, 'total_area_km2'), (_, 'urban_area_km2'),
        (_, 'urban_share_pct'), (_, 'ndvi_mean_urban'), (_, 'green_in_urban_km2'),
        (_, 'green_share_in_urban_pct'), (_, 'population_urban'), (_, 'm2_per_person_urban'),
        (_, 'created_at'), (_, 'cache_version')],
    # id เป็นทั้ง PK และ FK — 1 แถวต่อ 1 บัญชี โดยใช้ auth.users.id เป็นคีย์ตรง ๆ
    'profiles': [('PK,FK', 'id'), (_, 'display_name'), (_, 'role'), (_, 'organization'),
                 (_, 'accepted_terms_at'), (_, 'created_at'), (_, 'updated_at')],
    # owner_token ถูกตัดออกใน migration 019 — user_id เป็นทางเดียวที่ระบุเจ้าของ
    'saved_areas': [(P, 'id'), (F, 'user_id'), (_, 'label'), (_, 'geometry'), (_, 'year'),
                    (_, 'area_km2'), (F, 'province'), (_, 'analysis'), (_, 'recommendation'),
                    (_, 'created_at')],
}

# (ตารางต้นทาง, คอลัมน์ FK, ตารางปลายทาง, คอลัมน์ปลายทาง[, cardinality])
# คอลัมน์เป็น tuple = composite FK → วาดเป็นเส้นเดียวที่คร่อมสองแถว
# cardinality 'one' = ฝั่งต้นทางเป็นหนึ่ง (1:1) · ไม่ระบุ = many-to-one (ตีนกา)
FKS = [('districts', 'province', 'provinces', 'name_en'),
       ('province_population', 'province', 'provinces', 'name_en'),
       ('ndvi_annual', 'province', 'provinces', 'name_en'),
       ('ndvi_monthly', 'province', 'provinces', 'name_en'),
       ('province_lst_annual', 'province', 'provinces', 'name_en'),
       ('province_lst_monthly', 'province', 'provinces', 'name_en'),
       # migration 007: FOREIGN KEY (province, district) REFERENCES districts (province, name_en)
       # name_en ไม่ unique เดี่ยว ๆ ("Mueang" มีหลายจังหวัด) จึงต้องเป็น composite
       ('district_ndvi_annual', ('province', 'district'), 'districts', ('province', 'name_en')),
       ('district_ndvi_monthly', ('province', 'district'), 'districts', ('province', 'name_en')),
       ('district_lst_annual', ('province', 'district'), 'districts', ('province', 'name_en')),
       ('district_lst_monthly', ('province', 'district'), 'districts', ('province', 'name_en')),
       ('planting_recommendations', 'province', 'provinces', 'name_en'),
       ('urban_ndvi_annual', 'province', 'provinces', 'name_en'),
       # migration 010 / 013 — ทั้งคู่ชี้ auth.users ไม่ใช่ชี้หากันเอง
       # profiles เป็น 1:1 (id คือ auth.users.id) ส่วน saved_areas เป็น many-to-one
       ('profiles', 'id', 'auth.users', 'id', 'one'),
       ('saved_areas', 'user_id', 'auth.users', 'id'),
       ('saved_areas', 'province', 'provinces', 'name_en')]

# ป้ายกำกับ referential action บนเส้น FK — เขียนเฉพาะเส้นที่ไม่ใช่ค่าปริยาย (NO ACTION)
# ทั้งสองเส้นชี้ auth.users และเป็น CASCADE จริง (migration 010 / 013) ซึ่งเป็นสิ่งที่
# ทำให้ ProfileController.deleteAccount() ลบพื้นที่ที่บันทึกไว้ตามไปด้วยได้
ON_DELETE = {('profiles', 'id'): 'ON DELETE\nCASCADE',
             ('saved_areas', 'user_id'): 'ON DELETE\nCASCADE'}

# business unique key ที่มีอยู่จริงใน migrations
UNIQ = {
    'auth.users': None, 'provinces': None, 'profiles': None, 'saved_areas': None,
    'districts': 'UNIQUE (province, name_en)',
    'province_population': 'UNIQUE (province, year)',
    'ndvi_annual': 'UNIQUE (province, year)',
    'ndvi_monthly': 'UNIQUE (province, year)',
    'province_lst_annual': 'UNIQUE (province, year)',
    'province_lst_monthly': 'UNIQUE (province, year)',
    'district_ndvi_annual': 'UNIQUE (province, district, year)',
    'district_ndvi_monthly': 'UNIQUE (province, district, year)',
    'district_lst_annual': 'UNIQUE (province, district, year)',
    'district_lst_monthly': 'UNIQUE (province, district, year)',
    # migration 017 — NULL ของ district (= ระดับจังหวัด) ต้องถือว่าเท่ากัน
    'urban_ndvi_annual': 'UNIQUE NULLS NOT DISTINCT (province, district, year)',
    'planting_recommendations': 'UNIQUE NULLS NOT DISTINCT (province, district, year)',
}

COL1 = ['ndvi_annual', 'urban_ndvi_annual', 'province_lst_annual', 'province_population']
COL2 = ['provinces', 'districts', 'ndvi_monthly', 'province_lst_monthly',
        'auth.users', 'profiles', 'saved_areas']
COL3 = ['district_ndvi_annual', 'district_ndvi_monthly', 'district_lst_annual',
        'district_lst_monthly', 'planting_recommendations']

BW, ROW, HDR, GAP = 236, 22, 30, 30
KEYW = 32                      # ความกว้างช่อง PK/FK
X1, X2, X3 = 40, 430, 820
LANE_1 = [288, 302, 316, 330, 344]   # ตารางคอลัมน์ซ้าย -> คอลัมน์กลาง
LANE_2 = [356, 370, 384, 398]        # ตารางคอลัมน์กลาง -> คอลัมน์กลาง
LANE_3 = [686, 700, 714, 728, 742]   # ตารางคอลัมน์ขวา -> คอลัมน์กลาง

pos = {}
FOOT = 26


def height(name):
    return HDR + ROW * len(TABLES[name]) + (FOOT if UNIQ.get(name) else 0)


def layout(names, x, y0):
    y = y0
    for n in names:
        pos[n] = (x, y)
        y += height(n) + GAP
    return y


yend = max(layout(COL1, X1, 60), layout(COL2, X2, 60), layout(COL3, X3, 60))
W, H = X3 + BW + 40, yend + 10
c = Canvas(W, H)


def draw(name):
    x, y = pos[name]
    rows = TABLES[name]
    h = height(name)
    c.d.rectangle([x * 3, y * 3, (x + BW) * 3, (y + HDR) * 3], fill=(238, 238, 238))
    c.rect(x, y, x + BW, y + h, width=1.2)
    c.line(x, y + HDR, x + BW, y + HDR, 1.2)
    c.line(x + KEYW, y + HDR, x + KEYW, y + HDR + ROW * len(rows), 0.8)
    c.text(x + BW / 2, y + HDR / 2, name, 16, bold=True)
    for i, (k, col) in enumerate(rows):
        ry = y + HDR + ROW * i + ROW / 2
        if k:
            ks = 13                              # ย่อลงถ้าป้ายยาว (เช่น "PK,FK") ล้นช่อง
            while ks > 8 and c.textw(k, ks) > KEYW - 3:
                ks -= 1
            c.text(x + KEYW / 2, ry, k, ks, bold=True)
        c.text(x + KEYW + 8, ry, col, 15, anchor='lm')
        if k.startswith('PK'):                   # ครอบคลุม 'PK,FK' ด้วย
            w = c.textw(col, 15)
            c.line(x + KEYW + 8, ry + 9, x + KEYW + 8 + w, ry + 9, 0.8)
    if UNIQ.get(name):
        fy = y + HDR + ROW * len(rows)
        c.line(x, fy, x + BW, fy, 0.8)
        fs = 13                                  # ย่อฟอนต์ถ้าข้อความยาวเกินกล่อง
        while fs > 9 and c.textw(UNIQ[name], fs) > BW - 12:
            fs -= 1
        c.text(x + BW / 2, fy + FOOT / 2, UNIQ[name], fs)


def row_y(name, col):
    x, y = pos[name]
    i = [cc for _, cc in TABLES[name]].index(col)
    return y + HDR + ROW * i + ROW / 2


for n in TABLES:
    draw(n)


def bracket(x_edge, ys, direction):
    """คร่อมหลายแถวเข้าเป็นจุดเดียว (composite FK) — คืน x ของสันที่ใช้ต่อเส้น

    ขีดสั้นออกจากแต่ละแถวแล้วเชื่อมด้วยสันแนวตั้ง ทำให้เห็นชัดว่าสองคอลัมน์นี้
    ทำงานร่วมกันเป็น key เดียว ไม่ใช่ FK แยกกันสองตัว (ซึ่งสร้าง constraint ไม่ได้จริง)
    """
    bx = x_edge + 8 * direction
    c.line(bx, min(ys), bx, max(ys), 0.9)
    for yy in ys:
        c.line(x_edge, yy, bx, yy, 0.9)
    return bx


# ---- เส้น FK: ออกจากคอลัมน์ FK ไปเข้า PK ของตารางปลายทาง (เลี่ยงวิ่งทับกล่อง)
use = {1: 0, 2: 0, 3: 0}
notes = []
for fk in FKS:
    src, col, dst, dcol = fk[:4]
    card = fk[4] if len(fk) > 4 else 'many'
    sx, _sy0 = pos[src]
    dx, _dy0 = pos[dst]
    scols = col if isinstance(col, tuple) else (col,)
    dcols = dcol if isinstance(dcol, tuple) else (dcol,)
    srows = [row_y(src, cc) for cc in scols]
    drows = [row_y(dst, cc) for cc in dcols]

    group = 1 if sx < X2 else (2 if sx < X3 else 3)
    lanes = {1: LANE_1, 2: LANE_2, 3: LANE_3}[group]
    lx = lanes[use[group] % len(lanes)]
    use[group] += 1

    x_from = sx + BW if group == 1 else sx      # คอลัมน์กลาง/ขวา ออกทางซ้าย
    x_to = dx if group != 3 else dx + BW
    outward = 1 if group == 1 else -1           # ทิศที่เส้นออกจากกล่องต้นทาง
    inward = -1 if group != 3 else 1

    # composite → คร่อมแถวก่อน แล้วค่อยเดินเส้นเดียวจากสันวงเล็บ
    x_s = bracket(x_from, srows, outward) if len(srows) > 1 else x_from
    x_d = bracket(x_to, drows, inward) if len(drows) > 1 else x_to
    sy = sum(srows) / len(srows)
    dy = sum(drows) / len(drows)

    c.line(x_s, sy, lx, sy, 0.9)
    c.line(lx, sy, lx, dy, 0.9)
    c.line(lx, dy, x_d, dy, 0.9)
    if card == 'one':
        c.line(x_s + 7 * outward, sy - 6, x_s + 7 * outward, sy + 6, 0.9)   # ขีดเดียว = one
    else:
        # ตีนกา (many) — ปลายแหลมอยู่นอกกล่อง สามง่ามแตะขอบกล่องฝั่งต้นทาง
        c.line(x_s + 10 * outward, sy, x_s, sy - 6, 0.9)
        c.line(x_s + 10 * outward, sy, x_s, sy + 6, 0.9)
    c.line(x_d + 7 * inward, dy - 6, x_d + 7 * inward, dy + 6, 0.9)   # ขีดเดียว = one

    # ป้าย referential action — วางชิดสันแนวตั้งของเลน ด้านตรงข้ามกล่องต้นทาง
    # (ช่องว่างระหว่างคอลัมน์ซ้ายกับเลนกว้างพอ · เส้นละ 2 บรรทัดกันล้นไปทับกล่อง)
    # เก็บไว้วาดหลังจบลูป ไม่งั้นเส้น FK ของรอบถัด ๆ ไปจะพาดทับพื้นขาวของป้าย
    note = ON_DELETE.get((src, col if isinstance(col, str) else col[0]))
    if note:
        notes.append((lx + (max(c.textw(r, 12) for r in note.split('\n')) / 2 + 5) * outward,
                      (sy + dy) / 2, note.split('\n')))

# ---- ป้ายกำกับวาดทับเส้นทั้งหมด (พื้นขาวเจาะเส้นที่ลอดผ่านให้อ่านออก)
for nx, my, rows in notes:
    nw = max(c.textw(r, 12) for r in rows)
    c.d.rectangle([(nx - nw / 2 - 2) * 3, (my - len(rows) * 6 - 2) * 3,
                   (nx + nw / 2 + 2) * 3, (my + len(rows) * 6 + 2) * 3], fill=WHITE)
    for i, r in enumerate(rows):
        c.text(nx, my - (len(rows) - 1) * 6 + i * 12, r, 12)

HERE = os.path.dirname(os.path.abspath(__file__))
out_png = os.path.join(HERE, '..', 'er_new.png')
c.save(out_png)
print('saved', (W, H), 'aspect 1:%.3f' % (H / W),
      '· พิมพ์กว้าง 14.65 ซม. → สูง %.1f ซม.' % (14.65 * H / W))
