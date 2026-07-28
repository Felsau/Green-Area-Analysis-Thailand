"""Raster thumbnail endpoints — NDVI, LST, Thailand mini-map (สำหรับ PDF report)."""
import io
import logging

import ee
from fastapi import APIRouter, HTTPException, Response

from dependencies import (get_province_geom, get_district_geom,
                          CURRENT_YEAR, YearParam, load_thailand_geojson_raw)
from gee_utils import clean_s2_collection, get_lst_col

from ._cartography import (NDVI_PALETTE, LST_PALETTE,
                           fetch_thumb, bbox_dims, render_with_legend)

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/maps/{province_name}/ndvi-thumb")
def ndvi_thumb(province_name: str, year: YearParam = CURRENT_YEAR,
               district_name: str | None = None):
    """NDVI raster thumbnail พร้อม colorbar + north arrow + scale bar"""
    if district_name:
        raw_geom = get_district_geom(province_name, district_name)
        label = f"NDVI · {district_name}, {province_name} · {year}"
    else:
        raw_geom = get_province_geom(province_name)
        label = f"NDVI · {province_name} · {year}"

    geom = ee.Geometry(raw_geom)
    col = clean_s2_collection(
        ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
        .filterBounds(geom)
        .filterDate(f'{year}-01-01', f'{year + 1}-01-01')  # end exclusive — รวม 31 ธ.ค.
        .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 80)))

    if col.size().getInfo() == 0:
        raise HTTPException(status_code=404, detail="ไม่พบภาพดาวเทียม")

    ndvi = col.median().clip(geom).normalizedDifference(['B8', 'B4']).rename('NDVI')

    w, h = bbox_dims(raw_geom, max_dim=700)
    region = geom.bounds().getInfo()['coordinates']

    url = ndvi.getThumbURL({
        'min': -0.2, 'max': 0.8,
        'palette': NDVI_PALETTE,
        'dimensions': f'{w}x{h}',
        'region': region,
        'format': 'png',
    })
    raw_png = fetch_thumb(url)
    composed = render_with_legend(
        raw_geom, raw_png, NDVI_PALETTE,
        vmin=-0.2, vmax=0.8,
        label=label, unit='NDVI (Sentinel-2, 10 m)',
    )
    return Response(content=composed, media_type='image/png')


@router.get("/maps/{province_name}/lst-thumb")
def lst_thumb(province_name: str, year: YearParam = CURRENT_YEAR,
              district_name: str | None = None):
    """LST raster thumbnail พร้อม colorbar + north arrow + scale bar"""
    if district_name:
        raw_geom = get_district_geom(province_name, district_name)
        label = f"Land Surface Temperature · {district_name}, {province_name} · {year}"
    else:
        raw_geom = get_province_geom(province_name)
        label = f"Land Surface Temperature · {province_name} · {year}"

    geom = ee.Geometry(raw_geom)
    col = get_lst_col(geom, year)
    if col.size().getInfo() == 0:
        raise HTTPException(status_code=404, detail="ไม่พบภาพ Landsat")

    lst = col.median().clip(geom)

    w, h = bbox_dims(raw_geom, max_dim=700)
    region = geom.bounds().getInfo()['coordinates']

    url = lst.getThumbURL({
        'min': 20, 'max': 45,
        'palette': LST_PALETTE,
        'dimensions': f'{w}x{h}',
        'region': region,
        'format': 'png',
    })
    raw_png = fetch_thumb(url)
    composed = render_with_legend(
        raw_geom, raw_png, LST_PALETTE,
        vmin=20, vmax=45,
        label=label, unit='°C (Landsat 8/9, 30 m)',
    )
    return Response(content=composed, media_type='image/png')


# ── Thailand mini-map with province highlighted ──────────────────────────────
_THAILAND_GEOJSON = None


def _load_thailand_geojson():
    """Cache GeoJSON ใน memory — ใช้ helper จาก dependencies.py (path validated)"""
    global _THAILAND_GEOJSON
    if _THAILAND_GEOJSON is None:
        _THAILAND_GEOJSON = load_thailand_geojson_raw()
    return _THAILAND_GEOJSON


@router.get("/maps/thailand-thumb")
def thailand_thumb(province: str | None = None):
    """Mini-map ไทยทั้งประเทศ + highlight จังหวัด (ถ้าระบุ).
    ไม่ใช้ GEE — render ผ่าน matplotlib เพื่อความเร็ว"""
    try:
        # OO API ไม่ใช่ pyplot — เหตุผลเดียวกับ _cartography.render_with_legend
        # (pyplot มี global "current figure" ที่ไม่ thread-safe ใน threadpool ของ FastAPI)
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        from matplotlib.collections import PatchCollection
        from matplotlib.figure import Figure
        from matplotlib.patches import Polygon as MplPolygon
    except ImportError:
        raise HTTPException(status_code=500,
            detail="matplotlib ไม่ติดตั้ง — รัน: pip install matplotlib")

    geojson = _load_thailand_geojson()
    if not geojson:
        raise HTTPException(status_code=500, detail="thailand.json ไม่พบ")

    fig = Figure(figsize=(3.5, 4.5), dpi=150)
    FigureCanvasAgg(fig)   # ผูก Agg canvas ตรงๆ — ไม่พึ่ง global backend ของ matplotlib
    ax = fig.add_subplot(111)
    ax.set_facecolor('#f8f9fa')

    base_patches = []
    highlight_patches = []

    for feat in geojson['features']:
        name = feat['properties'].get('name', '')
        geom = feat['geometry']
        is_highlight = (province and name == province)

        def add_polys(coords_list, target):
            for ring in coords_list:
                target.append(MplPolygon([(p[0], p[1]) for p in ring]))

        t = geom['type']
        c = geom['coordinates']
        target = highlight_patches if is_highlight else base_patches
        if t == 'Polygon':
            add_polys(c, target)
        elif t == 'MultiPolygon':
            for poly in c:
                add_polys(poly, target)

    base_pc = PatchCollection(base_patches, facecolor='#e8eaed',
                              edgecolor='#9aa0a6', linewidths=0.4)
    ax.add_collection(base_pc)

    if highlight_patches:
        hi_pc = PatchCollection(highlight_patches, facecolor='#1e8e3e',
                                edgecolor='#0e5c24', linewidths=0.8)
        ax.add_collection(hi_pc)

    # Bounds of Thailand (rough)
    ax.set_xlim(97, 106)
    ax.set_ylim(5.5, 21)
    ax.set_aspect('equal')
    ax.set_xticks([])
    ax.set_yticks([])
    for s in ax.spines.values():
        s.set_visible(False)

    buf = io.BytesIO()
    fig.savefig(buf, format='png', bbox_inches='tight', pad_inches=0.05,
                facecolor='white')
    buf.seek(0)
    return Response(content=buf.read(), media_type='image/png')
