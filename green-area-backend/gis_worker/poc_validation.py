"""Local-only synthetic GIS PoC. Not production validation or application code.

No project imports, credentials, database clients, GEE clients or network calls.
ZIP contents are inspected in memory and never extracted to the filesystem.
"""
from __future__ import annotations

import codecs
import hashlib
import math
import re
import stat
import struct
import zipfile
from datetime import date
from io import BytesIO
from pathlib import Path, PurePosixPath
import unicodedata

import fiona
from fiona.io import ZipMemoryFile
import numpy as np
import rasterio
from rasterio.crs import CRS
from shapely.geometry import shape

ROOT = Path(__file__).resolve().parent
FIXTURES = ROOT / "fixtures"
KNOWN_CODES = {"U101": "U", "A101": "A", "U201/A401": "U", "A300/A400": "A"}
REQUIRED_FIELDS = ("LUL1_CODE", "LU_CODE", "Shape_Area")


class PocError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def require(condition: bool, code: str):
    if not condition:
        raise PocError(code)


def local_fixture(path: Path) -> Path:
    path = Path(path).resolve()
    require(path.is_relative_to(FIXTURES.resolve()), "FILE_OUTSIDE_SANDBOX")
    require(path.is_file(), "FILE_NOT_FOUND")
    return path


def sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def guarded_zip(path: Path, *, max_zip_bytes=5 * 1024**2,
                max_total_bytes=10 * 1024**2, max_member_bytes=5 * 1024**2,
                max_members=16, max_ratio=100) -> tuple[bytes, dict[str, bytes]]:
    path = local_fixture(path)
    require(path.stat().st_size <= max_zip_bytes, "ZIP_SIZE_LIMIT")
    raw = path.read_bytes()
    files = {}
    seen = set()
    try:
        with zipfile.ZipFile(BytesIO(raw)) as z:
            members = z.infolist()
            require(len(members) <= max_members, "ZIP_MEMBER_LIMIT")
            total = 0
            # Complete metadata checks BEFORE opening or decompressing any member.
            for item in members:
                name = item.filename
                parts = name.split("/")
                require(not name.startswith("/") and "\\" not in name
                        and ":" not in name and "\x00" not in name
                        and not any(p in (".", "..") for p in parts), "ZIP_PATH_UNSAFE")
                normalized = unicodedata.normalize("NFC", name).casefold()
                require(normalized not in seen, "ZIP_DUPLICATE_NAME")
                seen.add(normalized)
                mode = item.external_attr >> 16
                require(not stat.S_ISLNK(mode), "ZIP_SYMLINK")
                require(stat.S_IFMT(mode) in (0, stat.S_IFREG, stat.S_IFDIR), "ZIP_SPECIAL_FILE")
                require(not item.flag_bits & 1, "ZIP_ENCRYPTED")
                require(item.compress_type in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED),
                        "ZIP_COMPRESSION_UNSUPPORTED")
                require(item.file_size <= max_member_bytes, "ZIP_MEMBER_SIZE_LIMIT")
                total += item.file_size
                require(total <= max_total_bytes, "ZIP_EXPANDED_SIZE_LIMIT")
                if item.file_size:
                    require(item.compress_size > 0 and item.file_size / item.compress_size <= max_ratio,
                            "ZIP_COMPRESSION_RATIO")
            actual_total = 0
            for item in members:
                if item.is_dir():
                    continue
                chunks, actual = [], 0
                with z.open(item) as stream:
                    while chunk := stream.read(65536):
                        actual += len(chunk)
                        actual_total += len(chunk)
                        require(actual <= max_member_bytes and actual <= item.file_size,
                                "ZIP_MEMBER_SIZE_LIMIT")
                        require(actual_total <= max_total_bytes, "ZIP_EXPANDED_SIZE_LIMIT")
                        chunks.append(chunk)
                require(actual == item.file_size, "ZIP_SIZE_MISMATCH")
                files[item.filename] = b"".join(chunks)
    except PocError:
        raise
    except (zipfile.BadZipFile, EOFError, RuntimeError, OSError, NotImplementedError):
        raise PocError("ZIP_CORRUPT") from None
    return raw, files


def _shapefile_record_count(shp: bytes, shx: bytes, dbf: bytes) -> int:
    require(len(shp) >= 100 and len(shx) >= 100 and len(dbf) >= 33, "SHAPEFILE_TRUNCATED")
    for data in (shp, shx):
        require(struct.unpack_from(">i", data, 0)[0] == 9994, "SHAPEFILE_HEADER")
        require(struct.unpack_from(">i", data, 24)[0] * 2 == len(data), "SHAPEFILE_LENGTH")
    offsets, cursor = [], 100
    while cursor < len(shp):
        require(cursor + 8 <= len(shp), "SHAPEFILE_TRUNCATED")
        words = struct.unpack_from(">i", shp, cursor + 4)[0]
        require(words >= 2 and cursor + 8 + words * 2 <= len(shp), "SHAPEFILE_TRUNCATED")
        offsets.append((cursor // 2, words))
        cursor += 8 + words * 2
    require(cursor == len(shp) and (len(shx) - 100) == len(offsets) * 8,
            "SHAPEFILE_COUNT_MISMATCH")
    for i, expected in enumerate(offsets):
        require(struct.unpack_from(">ii", shx, 100 + i * 8) == expected, "SHX_INDEX_MISMATCH")
    count = struct.unpack_from("<I", dbf, 4)[0]
    header_len, record_len = struct.unpack_from("<HH", dbf, 8)
    require(count == len(offsets), "DBF_COUNT_MISMATCH")
    require(header_len >= 33 and record_len > 0
            and len(dbf) >= header_len + count * record_len, "DBF_TRUNCATED")
    require(all(dbf[header_len + i * record_len] != 42 for i in range(count)),
            "DELETED_DBF_RECORD")
    return count


def validate_ldd_zip(path: Path, *, aoi, expected_epsg=32647,
                     encoding_override=None, **zip_limits) -> dict:
    raw, files = guarded_zip(path, **zip_limits)
    shapes = [name for name in files if PurePosixPath(name).suffix.lower() == ".shp"]
    require(len(shapes) == 1, "SHAPEFILE_DATASET_COUNT")
    shp_name = shapes[0]
    stem = str(PurePosixPath(shp_name).with_suffix("")).casefold()
    components = {}
    for name, data in files.items():
        p = PurePosixPath(name)
        require(p.suffix.lower() in (".shp", ".shx", ".dbf", ".prj", ".cpg"),
                "UNSUPPORTED_ZIP_MEMBER")
        require(str(p.with_suffix("")).casefold() == stem, "SHAPEFILE_COMPONENT_STEM")
        components[p.suffix.lower()] = data
    for ext in (".shp", ".dbf", ".shx", ".prj"):
        require(ext in components, "MISSING_COMPONENT_" + ext[1:].upper())
    expected_count = _shapefile_record_count(components[".shp"], components[".shx"],
                                             components[".dbf"])
    try:
        crs = CRS.from_wkt(components[".prj"].decode("utf-8-sig", errors="strict"))
    except Exception:
        raise PocError("CRS_INVALID") from None
    require(crs.to_epsg() == expected_epsg, "CRS_MISMATCH")
    require(crs.is_projected and math.isclose(crs.linear_units_factor[1], 1),
            "PROJECTED_METRE_CRS_REQUIRED_IN_POC")
    declared_encoding = encoding_override
    if not declared_encoding and components.get(".cpg"):
        try:
            declared_encoding = components[".cpg"].decode("ascii").strip()
        except UnicodeError:
            raise PocError("ENCODING_INVALID") from None
    require(bool(declared_encoding), "ENCODING_UNSPECIFIED")
    try:
        encoding = codecs.lookup(declared_encoding).name
    except LookupError:
        raise PocError("ENCODING_INVALID") from None
    require(encoding in ("utf-8", "cp874", "tis-620"), "ENCODING_UNSUPPORTED")
    # Reject undecodable DBF text rather than relying on a permissive GDAL fallback.
    dbf = components[".dbf"]
    header_len, record_len = struct.unpack_from("<HH", dbf, 8)
    fields, descriptor, offset = [], 32, 1
    while descriptor + 32 <= header_len and dbf[descriptor] != 13:
        field_type = chr(dbf[descriptor + 11])
        width = dbf[descriptor + 16]
        require(width > 0, "DBF_FIELD_LAYOUT_INVALID")
        fields.append((field_type, offset, width))
        offset += width
        descriptor += 32
    require(descriptor < len(dbf) and dbf[descriptor] == 13
            and offset == record_len, "DBF_FIELD_LAYOUT_INVALID")
    try:
        for i in range(expected_count):
            row = dbf[header_len + i * record_len:header_len + (i + 1) * record_len]
            for field_type, off, width in fields:
                if field_type == "C":
                    row[off:off + width].decode(encoding, errors="strict")
    except UnicodeError:
        raise PocError("ENCODING_INVALID") from None

    records, errors, unknown = [], [], []
    totals = {k: 0.0 for k in "UAFWM"}
    total_area, unknown_area = 0.0, 0.0
    try:
        with fiona.Env(GDAL_PAM_ENABLED="NO", GDAL_VRT_ENABLE_PYTHON="NO"):
            with ZipMemoryFile(raw) as memory:
                with memory.open(shp_name, enabled_drivers=["ESRI Shapefile"],
                                 encoding=declared_encoding) as collection:
                    keys = {k.casefold(): k for k in collection.schema["properties"]}
                    require(all(k.casefold() in keys for k in REQUIRED_FIELDS), "ATTRIBUTES_MISSING")
                    for feature in collection:
                        props = dict(feature["properties"])
                        values = {k: props[keys[k.casefold()]] for k in REQUIRED_FIELDS}
                        for value in props.values():
                            require(not isinstance(value, bytes)
                                    and not (isinstance(value, str) and "\ufffd" in value),
                                    "ENCODING_INVALID")
                        index = len(records)
                        records.append(props)
                        def record_error(code):
                            errors.append({"code": code, "feature_index": index})
                        geom_json = feature["geometry"]
                        if geom_json is None:
                            record_error("GEOMETRY_EMPTY")
                        else:
                            geom = shape(geom_json)
                            if geom.is_empty:
                                record_error("GEOMETRY_EMPTY")
                            elif geom.geom_type not in ("Polygon", "MultiPolygon"):
                                record_error("GEOMETRY_TYPE")
                            elif not geom.is_valid:
                                record_error("GEOMETRY_INVALID")
                            elif not all(math.isfinite(v) for v in geom.bounds):
                                record_error("COORDINATES_INVALID")
                            elif not aoi.covers(geom):
                                record_error("OUTSIDE_SYNTHETIC_AOI")
                        area = values["Shape_Area"]
                        if not isinstance(area, (float, int)) or not math.isfinite(area) or area < 0:
                            record_error("AREA_INVALID")
                            continue
                        total_area += area
                        if geom_json is not None:
                            geom = shape(geom_json)
                            if geom.is_valid and not geom.is_empty and crs.is_projected:
                                if not math.isclose(geom.area, area, rel_tol=1e-6, abs_tol=0.01):
                                    record_error("AREA_MISMATCH")
                        code, main = values["LU_CODE"], values["LUL1_CODE"]
                        if not isinstance(code, str) or not code.strip() or main not in totals:
                            record_error("CODE_INVALID")
                        elif code not in KNOWN_CODES:
                            unknown.append({"code": code, "feature_index": index, "area_m2": area})
                            unknown_area += area
                            record_error("UNKNOWN_CODE_REVIEW_REQUIRED")
                        elif KNOWN_CODES[code] != main:
                            record_error("CODE_CLASS_MISMATCH")
                        else:
                            totals[main] += area
    except PocError:
        raise
    except Exception:
        raise PocError("SHAPEFILE_READ_ERROR") from None
    require(len(records) == expected_count, "FEATURE_COUNT_MISMATCH")
    return {"synthetic": True, "valid": not errors, "feature_count": len(records),
            "crs_epsg": crs.to_epsg(), "encoding": encoding, "records": records,
            "errors": errors, "unknown_codes": unknown, "unknown_area_m2": unknown_area,
            "area_by_main_m2": totals, "total_area_m2": total_area,
            "source_sha256": hashlib.sha256(raw).hexdigest(),
            "boundary_reference": "synthetic rectangle; not an official province boundary"}


def inspect_and_process_raster(path: Path, *, max_pixels=1_000_000,
                               max_bytes=10 * 1024**2) -> dict:
    path = local_fixture(path)
    require(path.stat().st_size <= max_bytes, "RASTER_FILE_SIZE_LIMIT")
    with path.open("rb") as stream:
        require(stream.read(4) in (b"II*\x00", b"MM\x00*", b"II+\x00", b"MM\x00+"),
                "NOT_A_TIFF")
    try:
        with rasterio.Env(GDAL_PAM_ENABLED="NO", GDAL_VRT_ENABLE_PYTHON="NO",
                          GDAL_NUM_THREADS="1"):
            with rasterio.open(path, driver="GTiff") as dataset:
                require(dataset.crs is not None, "RASTER_CRS_MISSING")
                require(dataset.width * dataset.height <= max_pixels, "RASTER_PIXEL_LIMIT")
                require(0 < dataset.count <= 8, "RASTER_BAND_LIMIT")
                require(all(math.isfinite(v) and v > 0 for v in dataset.res), "RASTER_RESOLUTION")
                require(dataset.transform.b == 0 and dataset.transform.d == 0,
                        "ROTATED_GRID_UNSUPPORTED_IN_POC")
                require(dataset.nodata is not None, "NODATA_POLICY_MISSING")
                tags = dataset.tags()
                kind = tags.get("DATA_KIND")
                require(tags.get("SYNTHETIC") == "true", "NOT_DECLARED_SYNTHETIC")
                acquisition = tags.get("ACQUISITION_DATE", "")
                require(bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", acquisition)), "ACQUISITION_DATE_MISSING")
                try:
                    date.fromisoformat(acquisition)
                except ValueError:
                    raise PocError("ACQUISITION_DATE_INVALID") from None
                require(bool(tags.get("UNITS")), "UNITS_MISSING")
                names = [str(d or "").upper() for d in dataset.descriptions]
                require(all(names) and len(set(names)) == len(names), "BAND_MAPPING_MISSING_OR_AMBIGUOUS")
                bands = {name: i + 1 for i, name in enumerate(names)}
                def band(name):
                    require(name in bands, "BAND_MISSING_" + name)
                    return dataset.read(bands[name], masked=True).astype("float64")
                def calibration(name, scale, offset):
                    require(name in bands, "BAND_MISSING_" + name)
                    i = bands[name] - 1
                    require(math.isclose(dataset.scales[i], scale, rel_tol=1e-9)
                            and math.isclose(dataset.offsets[i], offset, abs_tol=1e-9),
                            "SCALE_OFFSET_CONFLICT")
                if kind == "S2_SR_DN":
                    require(tags["UNITS"] == "DN" and tags.get("SENSOR") == "Sentinel-2",
                            "PRODUCT_UNITS_CONFLICT")
                    calibration("B8", 0.0001, 0)
                    calibration("B4", 0.0001, 0)
                    nir, red = band("B8") * 0.0001, band("B4") * 0.0001
                    mask = np.ma.getmaskarray(nir) | np.ma.getmaskarray(red)
                    valid = band("VALID_MASK").filled(0) == 1
                    denom = nir.filled(0) + red.filled(0)
                    mask |= ~valid | (np.abs(denom) <= 1e-12)
                    values = np.ma.array(np.divide(nir.filled(0) - red.filled(0), denom,
                                                   out=np.zeros(denom.shape), where=~mask), mask=mask)
                    output_units = "dimensionless"
                elif kind == "LANDSAT_C2_L2_ST_DN":
                    require(tags.get("PROCESSING_LEVEL") == "L2SP", "LANDSAT_SURFACE_TEMPERATURE_UNAVAILABLE")
                    require(tags["UNITS"] == "DN", "PRODUCT_UNITS_CONFLICT")
                    calibration("ST_B10", 0.00341802, 149)
                    raw = band("ST_B10")
                    require("QA_PIXEL" in bands, "BAND_MISSING_QA_PIXEL")
                    # QA clear value zero must not be mistaken for ST's global NoData=0.
                    qa = dataset.read(bands["QA_PIXEL"]).astype("uint32")
                    mask = np.ma.getmaskarray(raw) | ((qa & ((1 << 0) | (1 << 3) | (1 << 4))) != 0)
                    values = np.ma.array(raw.filled(0) * 0.00341802 + 149 - 273.15, mask=mask)
                    output_units = "degC"
                elif kind in ("NDVI_FLOAT", "LST_CELSIUS", "LST_KELVIN"):
                    name = "NDVI" if kind == "NDVI_FLOAT" else "LST"
                    require(dataset.count == 1, "PRECOMPUTED_BAND_COUNT")
                    calibration(name, 1, 0)
                    expected_units = {"NDVI_FLOAT": "1", "LST_CELSIUS": "degC", "LST_KELVIN": "K"}[kind]
                    require(tags["UNITS"] == expected_units, "PRODUCT_UNITS_CONFLICT")
                    values = band(name)
                    if kind == "LST_KELVIN":
                        values = values - 273.15
                    if kind == "NDVI_FLOAT":
                        require(not np.any((values.compressed() < -1) | (values.compressed() > 1)),
                                "NDVI_RANGE")
                    output_units = "dimensionless" if kind == "NDVI_FLOAT" else "degC"
                else:
                    raise PocError("DATA_KIND_UNSUPPORTED")
                values = np.ma.masked_invalid(values)
                count = int(values.count())
                metadata = {"data_kind": kind, "crs_epsg": dataset.crs.to_epsg(),
                            "width": dataset.width, "height": dataset.height,
                            "bands": names, "dtypes": list(dataset.dtypes),
                            "resolution": list(dataset.res), "nodata": dataset.nodata,
                            "source_units": tags["UNITS"], "output_units": output_units,
                            "scales": list(dataset.scales), "offsets": list(dataset.offsets),
                            "acquisition_date": acquisition, "synthetic": True}
                return {"metadata": metadata, "valid": count > 0,
                        "errors": [] if count else ["ALL_NODATA"],
                        "stats": {"valid_pixels": count, "mean": float(values.mean()) if count else None,
                                  "min": float(values.min()) if count else None,
                                  "max": float(values.max()) if count else None},
                        "values": [[None if masked else float(value) for value, masked in zip(row, maskrow)]
                                   for row, maskrow in zip(values.data, np.ma.getmaskarray(values))]}
    except PocError:
        raise
    except Exception:
        raise PocError("RASTER_READ_ERROR") from None
