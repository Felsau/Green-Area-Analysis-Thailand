"""C11 (week 4): list every LDD land-use code in the 77 slim shapefiles made by C10. Read-only.

Reads LU_CODE and LU_DES_TH of every parcel with fiona, computes the planar area of each parcel
from its geometry in the layer's own projected CRS (metres; every slim layer is UTM 47N/48N) and
converts it to rai (1 rai = 1,600 m2). Codes are grouped the way the system does it:
"/".join(ldd_planting.split_code(code)); raw spellings that differ only in spaces/case are
counted together and listed in `note`.

Run from <clone-rec>/green-area-backend with the C10 venv so ldd_codes and ldd_planting import:
    python <c11>/c11_ldd_codes.py --slim <c10-work>/slim --out <c11>/c11-ldd-codes.csv \
        --stats <c11>/c11-stats.json

Area: shoelace formula on the stored rings (outer ring minus holes, summed over MultiPolygon
parts). Geometry is not repaired (shapely is not installed in this venv), so a self-intersecting
ring gives the planar shoelace value of the ring as stored.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import fiona
import numpy as np

sys.path.insert(0, os.getcwd())
import ldd_codes  # noqa: E402
import ldd_planting  # noqa: E402

RAI_M2 = 1600.0


def ring_area(ring) -> float:
    a = np.asarray(ring, dtype=float)
    if a.ndim != 2 or len(a) < 3:
        return 0.0
    x, y = a[:, 0], a[:, 1]
    return abs(float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))) / 2.0


def polygon_area(rings) -> float:
    if not rings:
        return 0.0
    return max(ring_area(rings[0]) - sum(ring_area(r) for r in rings[1:]), 0.0)


def geom_area(geom) -> float:
    if geom is None:
        return 0.0
    t, c = geom["type"], geom["coordinates"]
    if t == "Polygon":
        return polygon_area(c)
    if t == "MultiPolygon":
        return sum(polygon_area(p) for p in c)
    return 0.0


def scan(shp: str) -> dict:
    """Per layer: {key: [parcels, area_m2, Counter(raw), Counter(name)]} plus totals."""
    codes: dict[str, list] = {}
    n = no_geom = 0
    with fiona.open(shp, encoding="utf-8") as src:
        epsg = src.crs.to_epsg(confidence_threshold=20)
        units = getattr(src.crs, "linear_units", None)
        for feat in src:
            p = feat["properties"]
            raw = p.get("LU_CODE")
            raw = "" if raw is None else str(raw)
            key = "/".join(ldd_planting.split_code(raw))
            name = (p.get("LU_DES_TH") or "").strip()
            g = feat["geometry"]
            no_geom += g is None
            area = geom_area(g)
            e = codes.get(key)
            if e is None:
                e = codes[key] = [0, 0.0, Counter(), Counter()]
            e[0] += 1
            e[1] += area
            e[2][raw] += 1
            e[3][name] += 1
            n += 1
    return {"layer": Path(shp).stem, "epsg": epsg, "units": units, "parcels": n, "no_geometry": no_geom,
            "codes": {k: [v[0], v[1], dict(v[2]), dict(v[3])] for k, v in codes.items()}}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--slim", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--stats", type=Path, required=True)
    ap.add_argument("--jobs", type=int, default=6)
    a = ap.parse_args()

    shps = sorted(str(p) for p in a.slim.glob("*/*.shp"))
    print(f"layers: {len(shps)}", flush=True)
    with ProcessPoolExecutor(max_workers=a.jobs) as pool:
        layers = list(pool.map(scan, shps))

    legend = ldd_codes.LDD_LU_CODES
    agg: dict[str, dict] = defaultdict(lambda: {"parcels": 0, "area": 0.0, "raw": Counter(),
                                                "names": Counter(), "layers": set()})
    for L in layers:
        print(f"  {L['layer']}: {L['parcels']} parcels, epsg {L['epsg']}, {L['units']}", flush=True)
        for key, (cnt, area, raw, names) in L["codes"].items():
            e = agg[key]
            e["parcels"] += cnt
            e["area"] += area
            e["raw"].update(raw)
            e["names"].update(names)
            e["layers"].add(L["layer"])

    rows = []
    for key, e in agg.items():
        parts = ldd_planting.split_code(key)
        known = [p in legend for p in parts]
        notes = []
        variants = {r: c for r, c in e["raw"].items() if r != key}
        if variants:
            notes.append("raw spellings merged: " + "; ".join(f"{r!r} x{c}" for r, c in sorted(variants.items())))
        if "+" in key:
            notes.append("contains '+': split_code splits on '/' only, so this is classified as one part")
        if key == "":
            notes.append("empty LU_CODE")
        top_name = e["names"].most_common(1)[0][0] if e["names"] else ""
        if len(e["names"]) > 1:
            notes.append(f"{len(e['names'])} distinct LU_DES_TH values in data")
        if key in legend:
            name_th, src = legend[key][1], "ldd_codes"
            if top_name and top_name != name_th:
                notes.append(f"most common LU_DES_TH in data: {top_name}")
        else:
            name_th, src = top_name, "ข้อมูล"
        rows.append({
            "LU_CODE": key, "name_th": name_th, "province_count": len(e["layers"]),
            "parcel_count": e["parcels"], "area_rai": round(e["area"] / RAI_M2, 2),
            "in_ldd_codes": "yes" if key in legend else "no",
            "classify_code": ldd_planting.classify_code(key),
            "name_th_source": src,
            "is_composite": "yes" if ("/" in key or "+" in key) else "no",
            "parts_in_ldd_codes": "all" if parts and all(known) else ("some" if any(known) else "none"),
            "note": " | ".join(notes),
        })
    rows.sort(key=lambda r: (-r["area_rai"], r["LU_CODE"]))
    cols = ["LU_CODE", "name_th", "province_count", "parcel_count", "area_rai", "in_ldd_codes", "classify_code",
            "name_th_source", "is_composite", "parts_in_ldd_codes", "note"]
    with open(a.out, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)

    stats = {
        "layers": len(layers), "parcels_total": sum(L["parcels"] for L in layers),
        "no_geometry_total": sum(L["no_geometry"] for L in layers),
        "area_rai_total": round(sum(r["area_rai"] for r in rows), 2),
        "codes_total": len(rows), "codes_composite": sum(r["is_composite"] == "yes" for r in rows),
        "legend_codes": len(legend),
        "legend_codes_seen": sum(r["in_ldd_codes"] == "yes" for r in rows),
        "legend_codes_not_seen": sorted(set(legend) - {r["LU_CODE"] for r in rows}),
        "per_layer": {L["layer"]: {"parcels": L["parcels"], "epsg": L["epsg"], "units": L["units"],
                                   "no_geometry": L["no_geometry"]} for L in layers},
    }
    a.stats.write_text(json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in stats.items() if k != "per_layer"}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
