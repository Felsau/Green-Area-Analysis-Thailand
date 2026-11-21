"""Prepare LDD land-use shapefiles and upload them to Google Earth Engine, one
FeatureCollection asset per province, then register them for the backend.

    cd green-area-backend
    python data/ldd/upload_ldd_to_gee.py --src D:/ldd/ภาคกลาง            # dry run
    python data/ldd/upload_ldd_to_gee.py --src D:/ldd --upload --wait    # real

What it does for every province package it finds (directory, region ZIP,
province ZIP, or a ZIP inside a ZIP):

1. picks the land-use layer (``LU_<ABBR>_<YEAR>.shp``, never the _Amp/_Pro/_Tam
   boundary layers) and extracts only its .shp/.shx/.dbf/.prj/.cpg files;
2. decides the DBF encoding (.cpg, then a Thai-text check on LU_DES_TH);
3. writes a slim UTF-8 shapefile with LU_CODE, LU_DES_TH (+ LU_ID_L1 when
   numeric) and zips it;
4. validates it, prints a summary and writes ldd_upload_report.csv;
5. with --upload: ``earthengine upload table``; with --wait: polls the task and
   records the asset in gee_assets.json (the file ldd.py reads).

Without --upload nothing is sent to Earth Engine. Pure helpers need only the
standard library; fiona is imported lazily, ee only for --wait.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Callable, Iterator

BACKEND_DIR = Path(__file__).resolve().parents[2]
DEFAULT_REGISTRY = Path(__file__).resolve().parent / "gee_assets.json"

THAI_RE = re.compile("[\u0e00-\u0e7f]")
THAI_OK_WARN_PCT = 95.0
SIDECARS = (".shp", ".shx", ".dbf", ".prj", ".cpg")

# Thai province name -> English name exactly as the system spells it
# (data/thailand.json "name" / get_province_geom).
_TH_TO_EN = {
    'อำนาจเจริญ': 'Amnat Charoen',
    'อ่างทอง': 'Ang Thong',
    'กรุงเทพมหานคร': 'Bangkok Metropolis',
    'บึงกาฬ': 'Bueng Kan',
    'บุรีรัมย์': 'Buri Ram',
    'ฉะเชิงเทรา': 'Chachoengsao',
    'ชัยนาท': 'Chai Nat',
    'ชัยภูมิ': 'Chaiyaphum',
    'จันทบุรี': 'Chanthaburi',
    'เชียงใหม่': 'Chiang Mai',
    'เชียงราย': 'Chiang Rai',
    'ชลบุรี': 'Chon Buri',
    'ชุมพร': 'Chumphon',
    'กาฬสินธุ์': 'Kalasin',
    'กำแพงเพชร': 'Kamphaeng Phet',
    'กาญจนบุรี': 'Kanchanaburi',
    'ขอนแก่น': 'Khon Kaen',
    'กระบี่': 'Krabi',
    'ลำปาง': 'Lampang',
    'ลำพูน': 'Lamphun',
    'เลย': 'Loei',
    'ลพบุรี': 'Lop Buri',
    'แม่ฮ่องสอน': 'Mae Hong Son',
    'มหาสารคาม': 'Maha Sarakham',
    'มุกดาหาร': 'Mukdahan',
    'นครนายก': 'Nakhon Nayok',
    'นครปฐม': 'Nakhon Pathom',
    'นครพนม': 'Nakhon Phanom',
    'นครราชสีมา': 'Nakhon Ratchasima',
    'นครสวรรค์': 'Nakhon Sawan',
    'นครศรีธรรมราช': 'Nakhon Si Thammarat',
    'น่าน': 'Nan',
    'นราธิวาส': 'Narathiwat',
    'หนองบัวลำภู': 'Nong Bua Lam Phu',
    'หนองคาย': 'Nong Khai',
    'นนทบุรี': 'Nonthaburi',
    'ปทุมธานี': 'Pathum Thani',
    'ปัตตานี': 'Pattani',
    'พังงา': 'Phangnga',
    'พัทลุง': 'Phatthalung',
    'พะเยา': 'Phayao',
    'เพชรบูรณ์': 'Phetchabun',
    'เพชรบุรี': 'Phetchaburi',
    'พิจิตร': 'Phichit',
    'พิษณุโลก': 'Phitsanulok',
    'พระนครศรีอยุธยา': 'Phra Nakhon Si Ayutthaya',
    'แพร่': 'Phrae',
    'ภูเก็ต': 'Phuket',
    'ปราจีนบุรี': 'Prachin Buri',
    'ประจวบคีรีขันธ์': 'Prachuap Khiri Khan',
    'ระนอง': 'Ranong',
    'ราชบุรี': 'Ratchaburi',
    'ระยอง': 'Rayong',
    'ร้อยเอ็ด': 'Roi Et',
    'สระแก้ว': 'Sa Kaeo',
    'สกลนคร': 'Sakon Nakhon',
    'สมุทรปราการ': 'Samut Prakan',
    'สมุทรสาคร': 'Samut Sakhon',
    'สมุทรสงคราม': 'Samut Songkhram',
    'สระบุรี': 'Saraburi',
    'สตูล': 'Satun',
    'ศรีสะเกษ': 'Si Sa Ket',
    'สิงห์บุรี': 'Sing Buri',
    'สงขลา': 'Songkhla',
    'สุโขทัย': 'Sukhothai',
    'สุพรรณบุรี': 'Suphan Buri',
    'สุราษฎร์ธานี': 'Surat Thani',
    'สุรินทร์': 'Surin',
    'ตาก': 'Tak',
    'ตรัง': 'Trang',
    'ตราด': 'Trat',
    'อุบลราชธานี': 'Ubon Ratchathani',
    'อุดรธานี': 'Udon Thani',
    'อุทัยธานี': 'Uthai Thani',
    'อุตรดิตถ์': 'Uttaradit',
    'ยะลา': 'Yala',
    'ยโสธร': 'Yasothon',
}

_EN_ALIASES = {"bangkok": "Bangkok Metropolis"}
_EN_TO_TH = {en: th for th, en in _TH_TO_EN.items()}


class RegistryConflict(Exception):
    """The province already has a registry entry and --overwrite was not given."""


# --------------------------------------------------------------------------
# Pure helpers (no GEE, no network, no fiona)
# --------------------------------------------------------------------------

def _letters(text: str) -> str:
    return re.sub(r"[^a-z]", "", text.casefold())


_EN_KEYS = {_letters(en): en for en in _EN_TO_TH}
_EN_KEYS.update(_EN_ALIASES)
_TH_BY_LEN = sorted(_TH_TO_EN, key=len, reverse=True)
_EN_BY_LEN = sorted((k for k in _EN_KEYS if len(k) >= 5), key=len, reverse=True)


def lookup_province(text: str) -> tuple[str, str] | None:
    """Thai or English province name (or a file/folder name containing one)
    -> (province_th, province_en), or None. Digits, 'จังหวัด', file extensions
    and 'ปีล่าสุด' are ignored."""
    if not text:
        return None
    stem = re.sub(r"\.(zip|shp)$", "", text.strip(), flags=re.I)
    thai_tokens = [t.replace("ปีล่าสุด", "").removeprefix("จังหวัด")
                   for t in re.findall("[฀-๿]+", stem)]
    thai_tokens = [t for t in thai_tokens if t]
    for tok in thai_tokens:
        if tok in _TH_TO_EN:
            return tok, _TH_TO_EN[tok]
    joined = "".join(thai_tokens)
    for th in _TH_BY_LEN:
        if th in joined:
            return th, _TH_TO_EN[th]
    letters = _letters(stem)
    if letters in _EN_KEYS:
        en = _EN_KEYS[letters]
        return _EN_TO_TH[en], en
    for key in _EN_BY_LEN:
        if key in letters:
            en = _EN_KEYS[key]
            return _EN_TO_TH[en], en
    return None


_LAYER_RE = re.compile(r"^LU[_\-\s]?([A-Za-z]{2,6})[_\-\s]?(25\d{2})", re.I)
_BOUNDARY_RE = re.compile(
    r"(^|[_\s\-])(amp|amphoe|pro|prov|province|tam|tambon)([_\s\-\d]|$)", re.I)
_LANDUSE_HINT_RE = re.compile(r"(^|[_\s\-])lu|land[_\s\-]?use|การใช้", re.I)


def parse_layer_name(name: str) -> tuple[str | None, int | None]:
    """'LU_KRI_2568.shp' -> ('KRI', 2568); anything else -> (None, None)."""
    stem = PurePosixPath(name.replace("\\", "/")).name
    if stem.lower().endswith(".shp"):
        stem = stem[:-4]
    m = _LAYER_RE.match(stem)
    return (m.group(1).upper(), int(m.group(2))) if m else (None, None)


def year_from_text(text: str) -> int | None:
    years = [int(y) for y in re.findall(r"(?<!\d)(25\d{2})(?!\d)", text or "")]
    return max(years) if years else None


def is_boundary_layer(stem: str) -> bool:
    return bool(_BOUNDARY_RE.search(stem)) or any(
        w in stem for w in ("ตำบล", "อำเภอ", "จังหวัด"))


def select_lu_layer(names: list[str]) -> str | None:
    """Pick the land-use .shp among package member names; ignore the
    _Amp/_Pro/_Tam boundary layers. Prefers LU_<ABBR>_<YEAR> and the newest year."""
    best = None
    for name in names:
        norm = name.replace("\\", "/")
        if not norm.lower().endswith(".shp") or norm.startswith("__MACOSX/"):
            continue
        stem = PurePosixPath(norm).stem
        abbr, year = parse_layer_name(norm)
        strict = abbr is not None
        if not strict and (is_boundary_layer(stem) or not _LANDUSE_HINT_RE.search(stem)):
            continue
        key = (strict, year or 0, -len(norm))
        if best is None or key > best[0]:
            best = (key, name)
    return best[1] if best else None


def encoding_from_cpg(text: str | None) -> str | None:
    """.cpg text -> python codec name, or None when missing/unknown."""
    t = (text or "").strip().strip("\x00").casefold()
    if not t:
        return None
    if "utf" in t or t == "65001":
        return "utf-8"
    if "874" in t or "tis" in t or "thai" in t:
        return "cp874"
    return None


def candidate_encodings(cpg_encoding: str | None) -> list[str]:
    if cpg_encoding == "cp874":
        return ["cp874", "utf-8"]
    return ["utf-8", "cp874"]


def thai_share(values) -> float:
    """Share (0..1) of values that contain at least one Thai character."""
    n = hits = 0
    for v in values:
        n += 1
        if isinstance(v, str) and THAI_RE.search(v):
            hits += 1
    return hits / n if n else 0.0


def pick_encoding(order: list[str], share_fn: Callable[[str], float]) -> tuple[str, float]:
    """First encoding in `order` whose LU_DES_TH Thai share is >= 95 %;
    otherwise the one with the highest share (ties -> earlier in `order`)."""
    best_enc, best_share = order[0], -1.0
    for enc in order:
        share = share_fn(enc)
        if share * 100 >= THAI_OK_WARN_PCT:
            return enc, share
        if share > best_share:
            best_enc, best_share = enc, share
    return best_enc, max(best_share, 0.0)


def plan_asset_id(asset_root: str, abbr: str, year_be: int) -> str:
    return f"{asset_root.rstrip('/')}/LU_{abbr}_{year_be}"


def merge_registry(data: dict, province_en: str, asset: str, year_be: int,
                   overwrite: bool = False) -> dict:
    """Return a copy of the registry with the province added/replaced.
    Keeps `_comment` and any code_field/name_field on a replaced entry."""
    out = json.loads(json.dumps(data))
    provinces = out.setdefault("provinces", {})
    if province_en in provinces and not overwrite:
        raise RegistryConflict(f"{province_en} is already registered "
                               f"({provinces[province_en].get('asset')}); use --overwrite")
    entry = dict(provinces.get(province_en) or {})
    entry.update({"asset": asset, "year_be": int(year_be)})
    provinces[province_en] = entry
    out["provinces"] = dict(sorted(provinces.items()))
    return out


def registry_text(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def load_registry(path: Path) -> dict:
    if not Path(path).exists():
        return {"provinces": {}}
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    data.setdefault("provinces", {})
    return data


def save_registry(path: Path, data: dict) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(registry_text(data))


def parse_task_id(output: str) -> str | None:
    """Task id from `earthengine upload` output (format differs by CLI
    version: 'Started upload task with ID: XXXX' / '... task ID: XXXX')."""
    m = re.search(r"\bID:?\s*([A-Z0-9]{16,})\b", output or "")
    if m:
        return m.group(1)
    m = re.search(r"\b([A-Z0-9]{20,})\b", output or "")
    return m.group(1) if m else None


# --------------------------------------------------------------------------
# Finding packages
# --------------------------------------------------------------------------

def member_name(info: zipfile.ZipInfo) -> str:
    """Decoded member name (non-UTF-8 ZIPs from Windows Thai are cp874)."""
    name = info.filename
    if not info.flag_bits & 0x800:
        try:
            name = name.encode("cp437").decode("cp874")
        except UnicodeError:
            pass
    return name.replace("\\", "/")


@dataclass
class Package:
    chain: list[str]                       # outer -> inner container names
    layer: str                             # path of the .shp inside the package
    open_zip: Callable[[], zipfile.ZipFile] | None = None
    directory: Path | None = None

    def name_hints(self) -> list[str]:
        """Names to look the province up in, innermost first."""
        inner = list(PurePosixPath(self.layer).parts[:-1])
        return list(reversed(inner)) + list(reversed(self.chain))

    def extract(self, dest: Path) -> tuple[Path, bool]:
        """Return (path of the .shp, is_temporary). Zip members are written
        to dest/src.<ext> (only the five shapefile parts)."""
        stem = self.layer[:-4].replace("\\", "/")
        if self.directory is not None:
            return self.directory / PurePosixPath(self.layer).name, False
        dest.mkdir(parents=True, exist_ok=True)
        with self.open_zip() as z:
            wanted = {(stem + ext).casefold(): ext for ext in SIDECARS}
            for info in z.infolist():
                ext = wanted.get(member_name(info).casefold())
                if ext is None or info.is_dir():
                    continue
                with z.open(info) as src, open(dest / f"src{ext}", "wb") as dst:
                    shutil.copyfileobj(src, dst, 1 << 20)
        return dest / "src.shp", True


def _nested_factory(parent: Callable[[], zipfile.ZipFile], raw_name: str):
    def factory() -> zipfile.ZipFile:
        with parent() as z:
            data = z.read(raw_name)
        return zipfile.ZipFile(io.BytesIO(data))
    return factory


def scan_zip(factory: Callable[[], zipfile.ZipFile], chain: list[str],
             errors: list[str]) -> Iterator[Package]:
    try:
        with factory() as z:
            infos = [(member_name(i), i.filename) for i in z.infolist() if not i.is_dir()]
    except (zipfile.BadZipFile, OSError) as exc:
        errors.append(f"{' > '.join(chain)}: cannot read ZIP ({exc})")
        return
    layer = select_lu_layer([n for n, _ in infos])
    if layer:
        yield Package(chain, layer, open_zip=factory)
        return
    for name, raw in infos:
        if name.lower().endswith(".zip") and not name.startswith("__MACOSX/"):
            yield from scan_zip(_nested_factory(factory, raw),
                                chain + [PurePosixPath(name).name], errors)


def discover(paths: list[Path], errors: list[str]) -> Iterator[Package]:
    for root in paths:
        root = Path(root)
        if root.is_file():
            if root.suffix.lower() == ".zip":
                yield from scan_zip(lambda p=root: zipfile.ZipFile(p), [root.name], errors)
            elif root.suffix.lower() == ".shp":
                yield Package([root.parent.name], root.name, directory=root.parent)
            continue
        if not root.is_dir():
            errors.append(f"{root}: not found")
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames.sort()
            here = Path(dirpath)
            rel = [root.name] + list(here.relative_to(root).parts)
            layer = select_lu_layer(filenames)
            if layer:
                yield Package(rel, layer, directory=here)
            for fn in sorted(filenames):
                if fn.lower().endswith(".zip"):
                    yield from scan_zip(lambda p=here / fn: zipfile.ZipFile(p),
                                        rel + [fn], errors)


def resolve_package(pkg: Package) -> tuple[str | None, str | None, int | None, str | None]:
    """(province_th, province_en, year_be, abbr) for a package."""
    th = en = None
    for hint in pkg.name_hints():
        found = lookup_province(hint)
        if found:
            th, en = found
            break
    abbr, year = parse_layer_name(pkg.layer)
    if year is None:
        for hint in pkg.name_hints():
            year = year_from_text(hint)
            if year:
                break
    return th, en, year, abbr


# --------------------------------------------------------------------------
# Slim shapefile (needs fiona)
# --------------------------------------------------------------------------

def _sibling(shp: Path, ext: str) -> Path | None:
    for p in shp.parent.iterdir():
        if p.name.lower() == shp.stem.lower() + ext:
            return p
    return None


def read_cpg_text(shp: Path) -> str | None:
    p = _sibling(shp, ".cpg")
    if p is None:
        return None
    raw = p.read_bytes()
    for enc in ("utf-8", "cp874", "latin-1"):
        try:
            return raw.decode(enc).strip()
        except UnicodeDecodeError:
            continue
    return None


def _as_int(value) -> int | None:
    try:
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


@dataclass
class SlimResult:
    features: int = 0
    encoding: str = ""
    cpg: str = ""
    thai_ok_pct: float = 0.0
    lu_code_ok_pct: float = 0.0
    distinct_codes: int = 0
    compound_pct: float = 0.0
    has_lu_id_l1: bool = False
    crs: str = ""
    zip_path: Path | None = None
    zip_mb: float = 0.0
    warnings: list[str] = field(default_factory=list)


def _sample_thai_share(shp: Path, encoding: str, limit: int = 500) -> float:
    import fiona
    try:
        with fiona.open(shp, encoding=encoding) as src:
            key = {k.upper(): k for k in src.schema["properties"]}.get("LU_DES_TH")
            if key is None:
                return 0.0
            values = []
            for i, feat in enumerate(src):
                if i >= limit:
                    break
                values.append(feat["properties"].get(key))
            return thai_share(values)
    except Exception:  # undecodable bytes etc. -> this encoding is not usable
        return 0.0


def slim_shapefile(src_shp: Path, out_dir: Path, out_stem: str) -> SlimResult:
    """Write a slim UTF-8 shapefile (LU_CODE, LU_DES_TH, LU_ID_L1 if numeric)
    next to out_dir/out_stem.shp, zip it, validate it. Raises ValueError on a
    hard validation failure."""
    import fiona
    from itertools import islice

    res = SlimResult()
    src_shp = Path(src_shp)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cpg_text = read_cpg_text(src_shp)
    res.cpg = cpg_text if cpg_text is not None else "none"
    enc, _ = pick_encoding(candidate_encodings(encoding_from_cpg(cpg_text)),
                           lambda e: _sample_thai_share(src_shp, e))
    res.encoding = enc
    cpg_enc = encoding_from_cpg(cpg_text)
    if cpg_enc and cpg_enc != enc:
        res.warnings.append(f".cpg says {cpg_enc} but {enc} decodes Thai better")

    dst_shp = out_dir / f"{out_stem}.shp"
    with fiona.open(src_shp, encoding=enc) as src:
        keys = {k.upper(): k for k in src.schema["properties"]}
        missing = [f for f in ("LU_CODE", "LU_DES_TH") if f not in keys]
        if missing:
            raise ValueError(f"missing field(s) {missing}; has {sorted(keys)}")
        code_key, name_key, id_key = keys["LU_CODE"], keys["LU_DES_TH"], keys.get("LU_ID_L1")
        geom_type = src.schema["geometry"]
        if "polygon" not in str(geom_type).lower():
            raise ValueError(f"geometry type is {geom_type}, expected polygons")
        n_src = len(src)
        if id_key is not None:
            sample = [_as_int(f["properties"].get(id_key)) for f in islice(src, 1000)]
            id_key = id_key if any(v is not None for v in sample) else None
        res.has_lu_id_l1 = id_key is not None
        props = {"LU_CODE": "str:32", "LU_DES_TH": "str:254"}
        if id_key is not None:
            props["LU_ID_L1"] = "int"
        res.crs = (src.crs.to_string() if src.crs else "") or ""

        n = code_ok = thai_ok = compound = truncated = null_geom = 0
        codes: set[str] = set()
        batch: list[dict] = []
        with fiona.open(dst_shp, "w", driver="ESRI Shapefile",
                        schema={"geometry": geom_type, "properties": props},
                        crs_wkt=src.crs_wkt, encoding="utf-8") as dst:
            for feat in src:
                p = feat["properties"]
                code = (p.get(code_key) or "").strip() if isinstance(p.get(code_key), str) \
                    else ("" if p.get(code_key) is None else str(p.get(code_key)).strip())
                name = p.get(name_key)
                name = name if isinstance(name, str) else ("" if name is None else str(name))
                n += 1
                if code:
                    code_ok += 1
                    codes.add(code)
                    compound += "/" in code
                thai_ok += bool(THAI_RE.search(name))
                truncated += len(name) > 254 or len(code) > 32
                null_geom += feat["geometry"] is None
                rec = {"LU_CODE": code[:32], "LU_DES_TH": name[:254]}
                if id_key is not None:
                    rec["LU_ID_L1"] = _as_int(p.get(id_key))
                batch.append({"geometry": feat["geometry"], "properties": rec})
                if len(batch) >= 5000:
                    dst.writerecords(batch)
                    batch = []
            if batch:
                dst.writerecords(batch)

    with fiona.open(dst_shp) as chk:
        n_out = len(chk)
    if n != n_src or n_out != n_src:
        raise ValueError(f"feature count mismatch: source {n_src}, read {n}, written {n_out}")
    if n == 0:
        raise ValueError("source has no features")

    res.features = n
    res.lu_code_ok_pct = round(100 * code_ok / n, 2)
    res.thai_ok_pct = round(100 * thai_ok / n, 2)
    res.distinct_codes = len(codes)
    res.compound_pct = round(100 * compound / n, 2)
    if code_ok == 0:
        raise ValueError("LU_CODE is empty in every feature")
    if res.thai_ok_pct < THAI_OK_WARN_PCT:
        res.warnings.append(f"only {res.thai_ok_pct}% of LU_DES_TH contain Thai text")
    if truncated:
        res.warnings.append(f"{truncated} values truncated (LU_CODE 32 / LU_DES_TH 254)")
    if null_geom:
        res.warnings.append(f"{null_geom} features have no geometry")

    cpg_out = dst_shp.with_suffix(".cpg")
    if not cpg_out.exists() or "utf" not in cpg_out.read_text(errors="ignore").lower():
        cpg_out.write_text("UTF-8", encoding="ascii")
    prj_out = dst_shp.with_suffix(".prj")
    if not prj_out.exists():
        prj_src = _sibling(src_shp, ".prj")
        if prj_src is not None:
            shutil.copyfile(prj_src, prj_out)

    zip_path = out_dir.parent / f"{out_stem}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for ext in SIDECARS:
            part = dst_shp.with_suffix(ext)
            if part.exists():
                z.write(part, part.name)
    res.zip_path = zip_path
    res.zip_mb = round(zip_path.stat().st_size / 1024 ** 2, 2)
    return res


# --------------------------------------------------------------------------
# Earth Engine (only used with --upload / --wait)
# --------------------------------------------------------------------------

def ee_cli() -> str:
    exe = Path(sys.executable).parent / ("earthengine.exe" if os.name == "nt" else "earthengine")
    if exe.exists():
        return str(exe)
    found = shutil.which("earthengine")
    if not found:
        raise RuntimeError("earthengine CLI not found next to the Python executable or on PATH")
    return found


def run_ee(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run([ee_cli(), *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def _short(cp: subprocess.CompletedProcess) -> str:
    return " ".join(((cp.stdout or "") + " " + (cp.stderr or "")).split())[:400]


def ensure_folder(asset_root: str) -> None:
    cp = run_ee(["create", "folder", asset_root])
    if cp.returncode != 0 and "exist" not in _short(cp).lower():
        raise RuntimeError(f"create folder {asset_root} failed: {_short(cp)}")


def upload_table(asset_id: str, zip_path: Path, overwrite: bool = False) -> str:
    """Start the ingestion task and return its id."""
    if overwrite:
        rm = run_ee(["rm", asset_id])  # fails harmlessly when it does not exist
        if rm.returncode == 0:
            print(f"   removed existing asset {asset_id}")
    cp = run_ee(["upload", "table", f"--asset_id={asset_id}", str(zip_path)])
    out = (cp.stdout or "") + "\n" + (cp.stderr or "")
    if cp.returncode != 0:
        raise RuntimeError(f"upload failed: {_short(cp)}")
    task_id = parse_task_id(out)
    if not task_id:
        raise RuntimeError(f"upload started but no task id found in output: {_short(cp)}")
    return task_id


def init_ee(project: str | None) -> None:
    import ee
    ee.Initialize(project=project) if project else ee.Initialize()


def get_task_states(task_ids: list[str]) -> dict[str, tuple[str, str]]:
    import ee
    out = {}
    for tid, st in zip(task_ids, ee.data.getTaskStatus(task_ids)):
        out[tid] = (st.get("state", "UNKNOWN"), st.get("error_message", "") or "")
    return out


def wait_for_tasks(pending: dict[str, "Row"], on_done: Callable[["Row", str, str], None],
                   poll_seconds: float = 30, timeout_seconds: float = 4 * 3600,
                   get_states: Callable[[list[str]], dict] = get_task_states,
                   sleep: Callable[[float], None] = time.sleep) -> None:
    """Poll until every task is COMPLETED/FAILED/CANCELLED or the timeout passes."""
    deadline = time.monotonic() + timeout_seconds
    pending = dict(pending)
    while pending:
        states = get_states(list(pending))
        for tid, (state, msg) in states.items():
            if state in ("COMPLETED", "FAILED", "CANCELLED"):
                on_done(pending.pop(tid), state, msg)
        if not pending:
            return
        if time.monotonic() > deadline:
            for row in pending.values():
                row.status = "TIMEOUT waiting (task still running; check Tasks tab)"
            return
        print(f"   waiting for {len(pending)} task(s) ...")
        sleep(poll_seconds)


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------

REPORT_COLUMNS = ["province_en", "province_th", "year_be", "features", "encoding", "cpg",
                  "thai_ok_pct", "lu_code_ok_pct", "distinct_codes", "compound_pct",
                  "slim_zip_mb", "asset_id", "status", "notes"]


@dataclass
class Row:
    province_en: str = ""
    province_th: str = ""
    year_be: int | str = ""
    features: int | str = ""
    encoding: str = ""
    cpg: str = ""
    thai_ok_pct: float | str = ""
    lu_code_ok_pct: float | str = ""
    distinct_codes: int | str = ""
    compound_pct: float | str = ""
    slim_zip_mb: float | str = ""
    asset_id: str = ""
    status: str = ""
    notes: str = ""
    task_id: str = ""

    def as_dict(self) -> dict:
        return {c: getattr(self, c) for c in REPORT_COLUMNS}


def print_table(rows: list[Row]) -> None:
    cols = [("province_en", "province", 20), ("year_be", "year", 5), ("features", "feat", 7),
            ("encoding", "enc", 6), ("thai_ok_pct", "thai%", 6), ("lu_code_ok_pct", "code%", 6),
            ("distinct_codes", "codes", 5), ("compound_pct", "cmpd%", 6),
            ("slim_zip_mb", "MB", 6), ("status", "status", 40)]
    print("  ".join(h.ljust(w) for _, h, w in cols))
    for r in rows:
        print("  ".join(str(getattr(r, k)).ljust(w)[:w if k != "status" else 200]
                        for k, _, w in cols))


def write_report(path: Path, rows: list[Row]) -> None:
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=REPORT_COLUMNS, lineterminator="\n")
        w.writeheader()
        w.writerows(r.as_dict() for r in rows)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--src", nargs="+", required=True, type=Path,
                    help="directories, region ZIPs, province ZIPs or .shp files (walked recursively)")
    ap.add_argument("--province", action="append", default=[],
                    help="only this province (Thai or English); repeatable")
    ap.add_argument("--asset-root", default=None,
                    help="default projects/<GEE_PROJECT>/assets/ldd")
    ap.add_argument("--workdir", type=Path, default=None,
                    help="work/output folder (default: a new temp dir)")
    ap.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    ap.add_argument("--upload", action="store_true",
                    help="really upload to Earth Engine (default: dry run)")
    ap.add_argument("--wait", action="store_true",
                    help="poll the tasks and register finished assets in the registry")
    ap.add_argument("--overwrite", action="store_true",
                    help="allow replacing an existing registry entry; also deletes the "
                         "existing asset with the planned id before uploading")
    ap.add_argument("--poll-seconds", type=float, default=30)
    ap.add_argument("--wait-timeout-hours", type=float, default=4)
    return ap.parse_args(argv)


def _load_env() -> None:
    try:
        from dotenv import load_dotenv
        load_dotenv(BACKEND_DIR / ".env")
    except ImportError:
        pass


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    args = parse_args(argv)
    _load_env()
    project = os.getenv("GEE_PROJECT")
    asset_root = args.asset_root or f"projects/{project or '<GEE_PROJECT>'}/assets/ldd"
    if args.upload and ("<" in asset_root):
        print("GEE_PROJECT is not set (.env) and --asset-root was not given", file=sys.stderr)
        return 2
    if args.wait and not args.upload:
        print("--wait needs --upload", file=sys.stderr)
        return 2

    wanted: set[str] = set()
    for text in args.province:
        found = lookup_province(text)
        if not found:
            print(f"unknown province: {text}", file=sys.stderr)
            return 2
        wanted.add(found[1])

    workdir = args.workdir or Path(tempfile.mkdtemp(prefix="ldd_upload_"))
    workdir.mkdir(parents=True, exist_ok=True)
    print(f"mode      : {'UPLOAD' if args.upload else 'dry run (nothing sent to Earth Engine)'}")
    print(f"asset root: {asset_root}")
    print(f"workdir   : {workdir}")

    errors: list[str] = []
    by_province: dict[str, list[tuple[Package, str, int | None, str | None]]] = {}
    rows: list[Row] = []
    for pkg in discover(args.src, errors):
        th, en, year, abbr = resolve_package(pkg)
        if not en:
            rows.append(Row(status="skipped: province not recognised",
                            notes=" > ".join(pkg.chain + [pkg.layer])))
            continue
        if wanted and en not in wanted:
            continue
        by_province.setdefault(en, []).append((pkg, th or "", year, abbr))
    for msg in errors:
        rows.append(Row(status="error: " + msg))
    if wanted and (missing := wanted - set(by_province)):
        for en in sorted(missing):
            rows.append(Row(province_en=en, province_th=_EN_TO_TH.get(en, ""),
                            status="error: no land-use layer found"))

    registry = load_registry(args.registry)
    pending: dict[str, Row] = {}
    folder_ready = False
    for en in sorted(by_province):
        cands = sorted(by_province[en], key=lambda c: c[2] or 0, reverse=True)
        pkg, th, year, abbr = cands[0]
        row = Row(province_en=en, province_th=th, year_be=year or "")
        rows.append(row)
        for other in cands[1:]:
            rows.append(Row(province_en=en, province_th=th, year_be=other[2] or "",
                            status=f"skipped: older edition than {year}",
                            notes=" > ".join(other[0].chain)))
        print(f"\n[{en}] {' > '.join(pkg.chain)} :: {pkg.layer}")
        try:
            if not year:
                raise ValueError("no Buddhist-era year (25xx) in the layer or package name")
            abbr = abbr or re.sub(r"[^A-Za-z]", "", en).upper()
            row.asset_id = plan_asset_id(asset_root, abbr, year)
            registered = en in registry["provinces"]
            if registered and not args.overwrite and args.upload:
                row.status = (f"skipped: already registered "
                              f"({registry['provinces'][en].get('asset')}); use --overwrite")
                continue
            slug = f"LU_{abbr}_{year}"
            shp, is_temp = pkg.extract(workdir / "_extract" / slug)
            try:
                res = slim_shapefile(shp, workdir / "slim" / slug, slug)
            finally:
                if is_temp:
                    shutil.rmtree(workdir / "_extract" / slug, ignore_errors=True)
            row.features, row.encoding, row.cpg = res.features, res.encoding, res.cpg
            row.thai_ok_pct, row.lu_code_ok_pct = res.thai_ok_pct, res.lu_code_ok_pct
            row.distinct_codes, row.compound_pct = res.distinct_codes, res.compound_pct
            row.slim_zip_mb = res.zip_mb
            row.notes = "; ".join(res.warnings)
            if not args.upload:
                row.status = "dry-run ok" + (" (already registered)" if registered else "")
                if res.warnings:
                    row.status = "dry-run WARN"
                continue
            if not folder_ready:
                ensure_folder(asset_root)
                folder_ready = True
            row.task_id = upload_table(row.asset_id, res.zip_path, args.overwrite)
            row.status = f"upload started (task {row.task_id})"
            print(f"   task id: {row.task_id}")
            pending[row.task_id] = row
        except Exception as exc:
            row.status = f"error: {exc}"
            print(f"   ERROR: {exc}")

    if args.wait and pending:
        def on_done(r: Row, state: str, msg: str) -> None:
            if state != "COMPLETED":
                r.status = f"{state}: {msg}".strip(": ")
                return
            try:
                data = merge_registry(load_registry(args.registry), r.province_en,
                                      r.asset_id, int(r.year_be), args.overwrite)
                save_registry(args.registry, data)
                r.status = "COMPLETED, registered"
            except RegistryConflict as exc:
                r.status = f"COMPLETED, not registered: {exc}"
        init_ee(project)
        wait_for_tasks(pending, on_done, args.poll_seconds, args.wait_timeout_hours * 3600)

    print()
    print_table(rows)
    report = workdir / "ldd_upload_report.csv"
    write_report(report, rows)
    print(f"\nreport: {report}")
    bad = [r for r in rows if r.status.startswith(("error", "FAILED", "CANCELLED", "TIMEOUT"))]
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
