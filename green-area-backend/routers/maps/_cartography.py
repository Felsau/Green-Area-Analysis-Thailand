"""Cartographic helpers — colorbar, north arrow, scale bar, bbox math.

ใช้ภายในเท่านั้น (underscore prefix) — endpoint อยู่ใน thumbs.py
"""
import io
import math

import httpx
from fastapi import HTTPException

# Standard NDVI palette (vegetation: red→yellow→green)
NDVI_PALETTE = ['#a50026', '#d73027', '#f46d43', '#fdae61', '#fee08b',
                '#d9ef8b', '#a6d96a', '#66bd63', '#1a9850', '#006837']

# Thermal palette สำหรับ LST (cool→warm)
LST_PALETTE = ['#053061', '#2166ac', '#4393c3', '#92c5de', '#fddbc7',
               '#f4a582', '#d6604d', '#b2182b', '#67001f']


def fetch_thumb(url: str) -> bytes:
    """ดึง PNG จาก GEE thumb URL"""
    with httpx.Client(timeout=60.0) as client:
        r = client.get(url)
        if r.status_code != 200:
            raise HTTPException(status_code=502,
                detail=f"GEE thumb fetch failed: {r.status_code}")
        return r.content


def bbox_extent(geom_dict):
    """คืน (xmin, xmax, ymin, ymax) ของ bbox geometry"""
    coords = []

    def collect(g):
        t = g.get('type', '')
        c = g.get('coordinates', [])
        if t == 'Polygon':
            for ring in c:
                coords.extend(ring)
        elif t == 'MultiPolygon':
            for poly in c:
                for ring in poly:
                    coords.extend(ring)

    collect(geom_dict)
    if not coords:
        return 0, 1, 0, 1
    xs = [p[0] for p in coords]
    ys = [p[1] for p in coords]
    return min(xs), max(xs), min(ys), max(ys)


def km_per_deg(lat: float):
    """ระยะทาง km ต่อ 1 องศา (lng, lat) ที่ละติจูดที่กำหนด"""
    deg_lat_km = 110.574
    deg_lng_km = 111.320 * math.cos(math.radians(lat))
    return deg_lng_km, deg_lat_km


def bbox_dims(geom_dict, max_dim=512):
    """คำนวณ width/height สำหรับ thumb ให้ aspect ratio ตรงกับ geom"""
    coords = []

    def collect(g):
        t = g.get('type', '')
        c = g.get('coordinates', [])
        if t == 'Polygon':
            for ring in c:
                coords.extend(ring)
        elif t == 'MultiPolygon':
            for poly in c:
                for ring in poly:
                    coords.extend(ring)

    collect(geom_dict)
    if not coords:
        return max_dim, max_dim
    xs = [p[0] for p in coords]
    ys = [p[1] for p in coords]
    dx = max(xs) - min(xs)
    dy = max(ys) - min(ys)
    if dx <= 0 or dy <= 0:
        return max_dim, max_dim
    if dx >= dy:
        return max_dim, int(max_dim * dy / dx)
    return int(max_dim * dx / dy), max_dim


def _add_cartographic_decor(ax, geom_dict):
    """เติม north arrow + scale bar ลงบนภาพ matplotlib"""
    from matplotlib.patches import Rectangle, FancyArrowPatch

    xmin, xmax, ymin, ymax = bbox_extent(geom_dict)
    cy = (ymin + ymax) / 2

    # ── North arrow (มุมขวาบน) — สัญลักษณ์ใหญ่ขึ้นเหมาะกับรายงาน thesis
    arrow_x = 0.94
    arrow = FancyArrowPatch(
        (arrow_x, 0.83), (arrow_x, 0.97),
        transform=ax.transAxes, mutation_scale=28,
        arrowstyle='-|>', lw=2.4, color='#202124', zorder=12,
    )
    ax.add_patch(arrow)
    ax.text(arrow_x, 0.80, 'N', transform=ax.transAxes,
            ha='center', va='top', fontsize=14, fontweight='bold',
            color='#202124', zorder=12,
            bbox=dict(facecolor='white', edgecolor='#202124',
                      boxstyle='round,pad=0.18', linewidth=0.8))

    # ── Scale bar — เลือกความยาวที่อ่านง่าย (5/10/20/50 km)
    # แสดง 4 segments ดำ-ขาวสลับ + ป้าย 0 / กลาง / สุด เพื่อให้อ่านระยะกลางได้
    lng_km, _ = km_per_deg(cy)
    extent_km = (xmax - xmin) * lng_km
    target = extent_km / 4  # ~25% ของกว้างภาพ
    candidates = [1, 2, 5, 10, 20, 50, 100]
    bar_km = min(candidates, key=lambda k: abs(k - target))
    bar_deg = bar_km / lng_km

    bar_x0 = xmin + (xmax - xmin) * 0.05
    bar_y0 = ymin + (ymax - ymin) * 0.04
    bar_h = (ymax - ymin) * 0.014

    # 4 segments alternating black/white (cartographic convention)
    seg_count = 4
    seg_w = bar_deg / seg_count
    for i in range(seg_count):
        face = '#202124' if i % 2 == 0 else '#ffffff'
        ax.add_patch(Rectangle((bar_x0 + i * seg_w, bar_y0), seg_w, bar_h,
                               facecolor=face, edgecolor='#202124',
                               linewidth=0.8, zorder=10))

    def _label_km(km_val):
        return f'{km_val:g}' if km_val != int(km_val) else str(int(km_val))

    label_y = bar_y0 + bar_h * 2.2
    for frac in (0.0, 0.5, 1.0):
        x = bar_x0 + bar_deg * frac
        ax.plot([x, x], [bar_y0, bar_y0 + bar_h * 1.4],
                color='#202124', lw=0.8, zorder=11)
        text = '0' if frac == 0.0 else (
            f'{_label_km(bar_km)} km' if frac == 1.0 else _label_km(bar_km / 2))
        ax.text(x, label_y, text,
                ha='center', va='bottom', fontsize=8, color='#202124', zorder=11)


def render_with_legend(geom_dict, gee_thumb_bytes, palette, vmin, vmax,
                       label, unit):
    """Compose: GEE raster + colorbar + north arrow + scale bar → PNG.

    Figure dimensions คำนวณจาก *geometry bounds* (ไม่ใช่ pixel ของ thumb)
    เพื่อให้ NDVI กับ LST ของพื้นที่เดียวกัน = ขนาดภาพเท่ากันเป๊ะ
    """
    # ใช้ OO API (Figure + FigureCanvasAgg) ไม่ใช่ pyplot — pyplot เก็บ "current
    # figure" ไว้ใน global registry ที่ไม่ thread-safe และ plt.savefig() เซฟ *current*
    # figure ไม่ใช่ตัวที่ถือใน fig · endpoint พวกนี้เป็น sync def → FastAPI รันใน
    # threadpool ดังนั้นสอง request ที่ขอ thumb พร้อมกันจะแย่ง gcf() กัน แล้วได้ภาพ
    # ของอีก request หนึ่งกลับไปเงียบๆ · Figure() เป็น local ล้วน ไม่มี global ให้ชน
    import matplotlib.cm as mcm
    import matplotlib.colors as mcolors
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure
    from PIL import Image

    img = Image.open(io.BytesIO(gee_thumb_bytes))

    # Aspect ratio ที่ถูกต้องของพื้นที่จริง — แก้ aspect distortion จาก lng/lat
    xmin, xmax, ymin, ymax = bbox_extent(geom_dict)
    cy = (ymin + ymax) / 2
    lng_km, lat_km = km_per_deg(cy)
    width_km = (xmax - xmin) * lng_km
    height_km = (ymax - ymin) * lat_km
    geo_aspect = height_km / width_km if width_km > 0 else 1.0
    geo_aspect = max(0.55, min(geo_aspect, 1.6))  # clamp กันรูปยาว/แบนเกิน

    # ขนาด figure ที่คงที่: width 6.5" + height ตาม aspect + 1.6" สำหรับ title/colorbar
    fig_w = 6.5
    fig_h = fig_w * geo_aspect + 1.6

    fig = Figure(figsize=(fig_w, fig_h), dpi=150)
    FigureCanvasAgg(fig)   # ผูก Agg canvas ตรงๆ — ไม่พึ่ง global backend ของ matplotlib
    # height_ratios ปรับให้ colorbar มี breathing room มากขึ้น (กัน label ทับ ticks)
    gs = fig.add_gridspec(2, 1, height_ratios=[18, 1.0], hspace=0.32)
    ax = fig.add_subplot(gs[0])
    ax_cb = fig.add_subplot(gs[1])

    ax.imshow(img, extent=[xmin, xmax, ymin, ymax], aspect='auto')
    ax.set_xlim(xmin, xmax)
    ax.set_ylim(ymin, ymax)
    ax.set_xticks([])
    ax.set_yticks([])
    for s in ax.spines.values():
        s.set_edgecolor('#9aa0a6')
        s.set_linewidth(0.6)

    ax.set_title(label, fontsize=11, fontweight='bold', loc='left',
                 color='#202124', pad=6)

    _add_cartographic_decor(ax, geom_dict)

    # Colorbar (gradient) — labelpad ปรับให้ label ไม่ทับเลข tick
    cmap = mcolors.LinearSegmentedColormap.from_list('thumb', palette)
    norm = mcolors.Normalize(vmin=vmin, vmax=vmax)
    sm = mcm.ScalarMappable(cmap=cmap, norm=norm)
    sm.set_array([])
    cb = fig.colorbar(sm, cax=ax_cb, orientation='horizontal')
    cb.set_label(unit, fontsize=9, color='#202124', labelpad=10)
    cb.ax.tick_params(labelsize=8, colors='#5f6368', pad=3)
    cb.outline.set_edgecolor('#9aa0a6')

    buf = io.BytesIO()
    fig.savefig(buf, format='png', bbox_inches='tight', pad_inches=0.12,
                facecolor='white')
    # ไม่ต้อง close() — Figure ไม่ได้ลงทะเบียนใน registry ของ pyplot, GC เก็บเอง
    buf.seek(0)
    return buf.read()
