"""เครื่องมือวาดไดอะแกรม UML ด้วย Pillow — วาดที่ 3 เท่าแล้วย่อลงเพื่อให้ขอบเรียบ"""
from PIL import Image, ImageDraw, ImageFont
import math

FONT_DIR = '/Users/sunflower/Library/Fonts/'
S = 3                                    # supersample factor
BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
GREY = (240, 240, 240)


class Canvas:
    def __init__(self, w, h, bg=WHITE):
        self.w, self.h = w, h
        self.img = Image.new('RGB', (w * S, h * S), bg)
        self.d = ImageDraw.Draw(self.img)
        self._fonts = {}

    def font(self, size, bold=False):
        key = (size, bold)
        if key not in self._fonts:
            name = 'THSarabunNew Bold.ttf' if bold else 'THSarabunNew.ttf'
            self._fonts[key] = ImageFont.truetype(FONT_DIR + name, int(size * S))
        return self._fonts[key]

    # ---------------------------------------------------------------- ข้อความ
    def text(self, x, y, s, size=17, bold=False, anchor='mm', fill=BLACK):
        self.d.text((x * S, y * S), s, font=self.font(size, bold), fill=fill, anchor=anchor)

    def textw(self, s, size=17, bold=False):
        b = self.d.textbbox((0, 0), s, font=self.font(size, bold))
        return (b[2] - b[0]) / S

    def lines(self, x, y, rows, size=17, bold=False, lh=None):
        lh = lh or size * 1.05
        y0 = y - (len(rows) - 1) * lh / 2
        for i, r in enumerate(rows):
            self.text(x, y0 + i * lh, r, size, bold)

    # ---------------------------------------------------------------- รูปทรง
    def rect(self, x0, y0, x1, y1, width=1, fill=None, radius=0):
        box = [x0 * S, y0 * S, x1 * S, y1 * S]
        if radius:
            self.d.rounded_rectangle(box, radius=radius * S, outline=BLACK,
                                     width=int(width * S), fill=fill)
        else:
            self.d.rectangle(box, outline=BLACK, width=int(width * S), fill=fill)

    def ellipse(self, cx, cy, rx, ry, width=1, fill=WHITE):
        self.d.ellipse([(cx - rx) * S, (cy - ry) * S, (cx + rx) * S, (cy + ry) * S],
                       outline=BLACK, width=int(width * S), fill=fill)

    def line(self, x0, y0, x1, y1, width=1, dash=None):
        if not dash:
            self.d.line([x0 * S, y0 * S, x1 * S, y1 * S], fill=BLACK, width=int(width * S))
            return
        dx, dy = x1 - x0, y1 - y0
        ln = math.hypot(dx, dy)
        if ln == 0:
            return
        ux, uy = dx / ln, dy / ln
        on, off, t = dash
        pos = 0.0
        while pos < ln:
            a = pos
            b = min(pos + on, ln)
            self.d.line([(x0 + ux * a) * S, (y0 + uy * a) * S,
                         (x0 + ux * b) * S, (y0 + uy * b) * S],
                        fill=BLACK, width=int(width * S))
            pos += on + off

    def arrow_head(self, x, y, angle, size=9, hollow=False):
        a1 = angle + math.radians(158)
        a2 = angle - math.radians(158)
        p = [(x, y),
             (x + size * math.cos(a1), y + size * math.sin(a1)),
             (x + size * math.cos(a2), y + size * math.sin(a2))]
        pts = [(px * S, py * S) for px, py in p]
        if hollow:
            self.d.polygon(pts, outline=BLACK, fill=WHITE)
            self.d.line(pts + [pts[0]], fill=BLACK, width=int(1.2 * S))
        else:
            self.d.line([pts[0], pts[1]], fill=BLACK, width=int(1.4 * S))
            self.d.line([pts[0], pts[2]], fill=BLACK, width=int(1.4 * S))

    # ---------------------------------------------------------------- Actor
    def actor(self, cx, cy, label, size=17):
        r = 9
        self.d.ellipse([(cx - r) * S, (cy - 2 * r) * S, (cx + r) * S, cy * S],
                       outline=BLACK, width=int(1.4 * S), fill=WHITE)
        self.line(cx, cy, cx, cy + 26, 1.4)                 # ลำตัว
        self.line(cx - 16, cy + 9, cx + 16, cy + 9, 1.4)    # แขน
        self.line(cx, cy + 26, cx - 14, cy + 48, 1.4)       # ขา
        self.line(cx, cy + 26, cx + 14, cy + 48, 1.4)
        for i, row in enumerate(label.split('\n')):
            self.text(cx, cy + 62 + i * size * 1.05, row, size)

    def halo(self, cx, cy, rx, ry, pad=7):
        """ลบเส้นที่ลอดผ่านใกล้ ๆ วงรี ให้เห็นชัดว่าเป็นเส้นผ่าน ไม่ใช่เส้นเชื่อม"""
        self.d.ellipse([(cx - rx - pad) * S, (cy - ry - pad) * S,
                        (cx + rx + pad) * S, (cy + ry + pad) * S], fill=WHITE)

    def save(self, path):
        self.img.resize((self.w, self.h), Image.LANCZOS).save(path, dpi=(300, 300))
        return path
