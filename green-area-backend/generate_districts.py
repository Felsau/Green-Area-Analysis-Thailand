"""
One-time script to generate thailand_districts.json.

Strategy (tries in order):
  1. Download GADM 4.1 directly (latest, ~928 districts)
  2. GEE GAUL 2015 via fast batch fetch (813 districts)

Run:
    cd green-area-backend
    pip install requests
    python generate_districts.py

SQL to create Supabase tables (run in Supabase SQL editor):

CREATE TABLE district_ndvi_annual (
  id BIGSERIAL PRIMARY KEY,
  province TEXT NOT NULL,
  district TEXT NOT NULL,
  year INTEGER NOT NULL,
  ndvi_mean FLOAT,
  ndvi_min FLOAT,
  ndvi_max FLOAT,
  green_area_pct FLOAT,
  green_area_km2 FLOAT,
  total_area_km2 FLOAT,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(province, district, year)
);

CREATE TABLE district_ndvi_monthly (
  id BIGSERIAL PRIMARY KEY,
  province TEXT NOT NULL,
  district TEXT NOT NULL,
  year INTEGER NOT NULL,
  monthly_data JSONB,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(province, district, year)
);
"""
import json
import os
import subprocess
import sys

import requests
import ee
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Load GADM province names from existing thailand.json for name matching
# ---------------------------------------------------------------------------
thailand_json_path = os.path.join(
    os.path.dirname(__file__), '..', 'green-area-frontend', 'public', 'thailand.json'
)
with open(thailand_json_path, encoding='utf-8') as f:
    thailand_json = json.load(f)

gadm_index = {
    feat['properties']['name'].lower().replace(' ', '').replace('-', ''): feat['properties']['name']
    for feat in thailand_json['features']
}


def match_province(name: str) -> str:
    norm = name.lower().replace(' ', '').replace('-', '')
    if norm in gadm_index:
        return gadm_index[norm]
    for key, matched in gadm_index.items():
        if key in norm or norm in key:
            return matched
    print(f"  ⚠️  No match for province: '{name}' — using as-is")
    return name


# ปลายทางสองที่ ต้องเขียนพร้อมกันทุกครั้ง — ไม่ใช่ที่เดียวแล้ว
#   1) frontend/public/  → vite copy ลง build/ ให้ browser fetch('/thailand_districts.json')
#   2) backend/data/     → อยู่ใน build context ของ Dockerfile (COPY . .) จึงติดไปใน image
#                          ด้วย · dependencies.py หาที่นี่ก่อน legacy path
# เขียนที่เดียวแล้วอีกที่ค้างของเก่า = สองฝั่งเห็นชุดอำเภอไม่ตรงกัน (tests/
# test_geodata_assets.py กัน drift นี้ไว้ใน CI)
OUTPUT_PATHS = (
    os.path.join(os.path.dirname(__file__), '..', 'green-area-frontend', 'public',
                 'thailand_districts.json'),
    os.path.join(os.path.dirname(__file__), 'data', 'thailand_districts.json'),
)
# คงชื่อเดิมไว้ให้สคริปต์/คนที่อ้างถึงตัวแปรนี้ (สำเนาหลัก = frontend/public)
OUTPUT_PATH = OUTPUT_PATHS[0]


def write_districts(geojson: dict, source_label: str) -> None:
    """เขียน GeoJSON ลงปลายทางทุกที่ใน OUTPUT_PATHS ด้วย byte เดียวกัน"""
    payload = json.dumps(geojson, ensure_ascii=False, separators=(',', ':'))
    for path in OUTPUT_PATHS:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(payload)
    size_mb = len(payload.encode('utf-8')) / 1024 / 1024
    print(f"✅ {source_label}: Saved {len(geojson['features'])} districts "
          f"({size_mb:.1f} MB) → {len(OUTPUT_PATHS)} ปลายทาง")
    for path in OUTPUT_PATHS:
        print(f"     · {os.path.relpath(path, os.path.dirname(__file__))}")

# ---------------------------------------------------------------------------
# Strategy 1: Download GADM 4.1 directly (no GEE needed)
# ---------------------------------------------------------------------------
def try_gadm_direct() -> bool:
    """Download Thailand GADM 4.1 level-2 GeoJSON from gadm.org."""
    url = "https://geodata.ucdavis.edu/gadm/gadm4.1/json/gadm41_THA_2.json"
    print("⏳ Downloading GADM 4.1 directly from geodata.ucdavis.edu ...")
    try:
        r = requests.get(url, timeout=60, stream=True)
        r.raise_for_status()
        total = int(r.headers.get('content-length', 0))
        downloaded = 0
        chunks = []
        for chunk in r.iter_content(chunk_size=1024 * 256):
            chunks.append(chunk)
            downloaded += len(chunk)
            if total:
                pct = downloaded / total * 100
                print(f"\r  Downloading... {pct:.0f}%", end='', flush=True)
        print()
        raw = json.loads(b''.join(chunks))
    except Exception as e:
        print(f"  ✗ Direct download failed: {e}")
        return False

    result_features = []
    for feat in raw.get('features', []):
        props = feat.get('properties', {})
        province_raw = props.get('NAME_1', '')
        district_name = props.get('NAME_2', '')
        if not province_raw or not district_name:
            continue
        result_features.append({
            "type": "Feature",
            "properties": {
                "name":     district_name,
                "province": match_province(province_raw),
            },
            "geometry": feat['geometry'],
        })

    if not result_features:
        print("  ✗ No features parsed from GADM download")
        return False

    geojson = {"type": "FeatureCollection", "features": result_features}
    write_districts(geojson, "GADM 4.1")
    return True


# ---------------------------------------------------------------------------
# Strategy 2: GEE GAUL 2015 via fast batch fetch
# ---------------------------------------------------------------------------
def try_gee_gaul() -> bool:
    """Fetch from GEE GAUL 2015 using batched getInfo() — fast & reliable."""
    print("⏳ Fetching from GEE GAUL 2015 (batch mode)...")
    gee_project = os.getenv('GEE_PROJECT')
    if not gee_project:
        print("  ✗ GEE_PROJECT ไม่ถูกตั้งใน .env — strategy นี้ใช้งานไม่ได้")
        return False
    try:
        ee.Initialize(project=gee_project)
        districts_fc = (
            ee.FeatureCollection("FAO/GAUL/2015/level2")
            .filter(ee.Filter.eq('ADM0_NAME', 'Thailand'))
            .map(lambda f: f.simplify(maxError=500))
            .select(['ADM1_NAME', 'ADM2_NAME'])
        )
        size = districts_fc.size().getInfo()
        print(f"📍 GAUL 2015: Found {size} districts — fetching in batches of 100...")
    except Exception as e:
        print(f"  ✗ GEE init failed: {e}")
        return False

    BATCH = 100
    result_features = []
    features_list = districts_fc.toList(size)

    for start in range(0, size, BATCH):
        end = min(start + BATCH, size)
        try:
            batch_fc = ee.FeatureCollection(features_list.slice(start, end))
            batch_info = batch_fc.getInfo()
            for feat in batch_info['features']:
                props = feat['properties']
                result_features.append({
                    "type": "Feature",
                    "properties": {
                        "name":     props.get('ADM2_NAME', ''),
                        "province": match_province(props.get('ADM1_NAME', '')),
                    },
                    "geometry": feat['geometry'],
                })
        except Exception as e:
            print(f"  ⚠️  Batch {start}-{end} failed: {e} — skipping")
            continue
        print(f"  Processed {end}/{size}")

    if not result_features:
        return False

    geojson = {"type": "FeatureCollection", "features": result_features}
    write_districts(geojson, "GAUL 2015")
    return True


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
if try_gadm_direct() or try_gee_gaul():
    # GADM/GAUL carry English names only — immediately patch in Thai district
    # names so on-map labels read in Thai ("เขตทุ่งครุ", not "Thungkru").
    # Chained here so a regen can never silently drop name_th again.
    print("⏳ Adding Thai district names (name_th) ...")
    rc = subprocess.run(
        [sys.executable, os.path.join(os.path.dirname(__file__), "add_district_th_names.py")]
    ).returncode
    if rc != 0:
        print("  ⚠️  Thai-name patch failed — labels fall back to English. "
              "Re-run `python add_district_th_names.py` once network is available.")
    print("Done. Restart the backend to load the new district boundaries.")
else:
    print("❌ All strategies failed. Check your internet connection and try again.")
