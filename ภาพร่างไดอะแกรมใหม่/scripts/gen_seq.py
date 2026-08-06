#!/usr/bin/env python3
"""ตัวสร้าง Sequence Diagram — สไตล์เดียวกับรูปเดิม (actor + lifeline + activation bar)"""
import os, sys, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from diagram import Canvas, BLACK, WHITE

B, C, E, S = 'boundary', 'control', 'entity', 'service'
CALL, RET, SELF = 'call', 'ret', 'self'

FS = 21           # ขนาดข้อความข้อความส่ง
FSN = 22          # ชื่อ lifeline
PAD = 34          # ระยะขอบซ้าย/ขวา
TOP = 118         # ระยะจากขอบบนถึงเส้น lifeline แรก
ROW = 60          # ระยะห่างระหว่างข้อความ
BAR = 13          # ความกว้าง activation bar
MAXLBL = 200      # ความกว้างสูงสุดของป้ายข้อความก่อนตัดบรรทัด


def split_label(probe, t):
    """ตัดป้ายข้อความยาวเป็น 2 บรรทัด — เลี่ยงไม่ให้ lifeline ห่างกันเกินไป
    (ยิ่งรูปกว้าง ตัวอักษรตอนพิมพ์ยิ่งเล็ก) · ตัดได้ที่ช่องว่าง วงเล็บเปิด หรือคอมมา"""
    if probe.textw(t, FS) <= MAXLBL:
        return [t]
    cuts = [i + 1 for i, ch in enumerate(t) if ch in ' (']
    cuts += [i + 2 for i, ch in enumerate(t) if ch == ',' and i + 1 < len(t)]
    best = None
    for i in sorted(set(cuts)):
        head, tail = t[:i].rstrip(), t[i:].lstrip()
        if not head or not tail:
            continue
        wide = max(probe.textw(head, FS), probe.textw(tail, FS))
        if best is None or wide < best[0]:
            best = (wide, [head, tail])
    return best[1] if best else [t]


def icon(c, cx, cy, kind, r=17):
    """ไอคอนหัว lifeline ตามแบบ robustness: boundary / control / entity / service"""
    c.d.ellipse([(cx - r) * 3, (cy - r) * 3, (cx + r) * 3, (cy + r) * 3],
                outline=BLACK, width=4, fill=WHITE)
    if kind == B:
        c.line(cx - r - 11, cy - r, cx - r - 11, cy + r, 1.4)
        c.line(cx - r - 11, cy, cx - r, cy, 1.4)
    elif kind == C:
        c.line(cx - 5, cy - r - 4, cx + 4, cy - r + 1, 1.4)
        c.line(cx - 5, cy - r - 4, cx - 3, cy - r + 6, 1.4)
    elif kind == E:
        c.line(cx - r, cy + r + 5, cx + r, cy + r + 5, 1.4)
    else:                                   # service = สามเหลี่ยมเล็กบนวงกลม
        c.line(cx - 6, cy - r + 2, cx + 6, cy - r + 2, 1.4)
        c.line(cx - 6, cy - r + 2, cx, cy - r - 8, 1.4)
        c.line(cx + 6, cy - r + 2, cx, cy - r - 8, 1.4)


def build(title, actor, parts, msgs, out, prefix=None):
    """parts = [(ชื่อ, ชนิด)] · msgs = [(จาก, ถึง, ข้อความ, ชนิด)] ; index -1 = actor"""
    probe = Canvas(10, 10)
    lbl = {i: split_label(probe, m[2]) for i, m in enumerate(msgs)}
    lblw = {i: max(probe.textw(x, FS) for x in v) for i, v in lbl.items()}
    labels = [actor] + [p[0] for p in parts]
    widths = [max(probe.textw(l, FSN), 96) for l in labels]

    xs, x = [], PAD
    for i, w in enumerate(widths):
        gap = 0
        if i:                                # เว้นให้พอสำหรับข้อความที่ยาวที่สุดในช่วงนี้
            need = 130
            for j, (a, b, t, k) in enumerate(msgs):
                lo, hi = sorted(((a + 1), (b + 1)))
                if k != SELF and lo < i <= hi:
                    need = max(need, lblw[j] + 34)
                elif k == SELF and (a + 1) == i - 1:
                    need = max(need, lblw[j] + 120)
            gap = need
        x += gap + (widths[i - 1] / 2 if i else widths[0] / 2)
        xs.append(x)
    W = int(xs[-1] + widths[-1] / 2 + PAD)

    ys, y = [], TOP + 104
    for i in range(len(msgs)):
        ys.append(y)
        y += ROW + (22 if len(lbl.get(i + 1, [''])) > 1 else 0)
    H = int(ys[-1] + 120) if msgs else TOP + 200

    c = Canvas(W, H)
    c.text(W / 2, 34, title, 24, bold=True)

    # ---- ช่วง activation ของแต่ละ lifeline (แถวแรกที่ถูกเรียก → แถวสุดท้ายที่เกี่ยวข้อง)
    span = {}
    for i, (a, b, t, k) in enumerate(msgs):
        for p in ({a, b} if k != SELF else {a}):
            lo, hi = span.get(p, (i, i))
            span[p] = (min(lo, i), max(hi, i))

    # ---- lifeline
    for i, (name, kind) in enumerate(parts):
        px = xs[i + 1]
        icon(c, px, TOP, kind)
        c.text(px, TOP + 38, name, FSN)
        c.line(px, TOP + 54, px, H - 46, 1.0, dash=(6, 6, 0))

    c.actor(xs[0], TOP - 12, actor, FSN)

    # ---- activation bar
    for p, (lo, hi) in span.items():
        if p < 0:
            continue
        px = xs[p + 1]
        y0, y1 = ys[lo] - 16, ys[hi] + 16
        c.d.rectangle([(px - BAR / 2) * 3, y0 * 3, (px + BAR / 2) * 3, y1 * 3],
                      fill=WHITE, outline=BLACK, width=3)

    # ---- ข้อความ
    for i, (a, b, t, k) in enumerate(msgs):
        y = ys[i]
        num = f'{prefix}.{i + 1} ' if prefix else f'{i + 1}. '
        if k == SELF:
            px = xs[a + 1] + BAR / 2
            w, h = 46, 22
            c.line(px, y - h / 2, px + w, y - h / 2, 1.1)
            c.line(px + w, y - h / 2, px + w, y + h / 2, 1.1)
            c.line(px + w, y + h / 2, px + 2, y + h / 2, 1.1)
            c.arrow_head(px + 2, y + h / 2, math.pi, size=10)
            rows = lbl[i]
            rows = [num + rows[0]] + rows[1:]
            for r, txt in enumerate(rows):
                c.text(px + w + 12, y - h / 2 - 2 + (r - (len(rows) - 1) / 2) * 24,
                       txt, FS, anchor='lm')
        else:
            x0 = xs[a + 1] + (BAR / 2 if a >= 0 else 20)
            x1 = xs[b + 1] - (BAR / 2 if b >= 0 else 0)
            back = x1 < x0
            if back:
                x0, x1 = xs[a + 1] - BAR / 2, xs[b + 1] + BAR / 2
            c.line(x0, y, x1, y, 1.1, dash=((7, 5, 0) if k == RET else None))
            c.arrow_head(x1, y, math.pi if back else 0, size=11)
            rows = lbl[i]
            rows = [num + rows[0]] + rows[1:]
            for r, txt in enumerate(rows):
                c.text((x0 + x1) / 2, y - 15 - (len(rows) - 1 - r) * 24, txt, FS)

    c.save(out)
    return W, H
