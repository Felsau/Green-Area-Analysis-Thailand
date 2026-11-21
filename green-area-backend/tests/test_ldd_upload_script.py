"""Tests for data/ldd/upload_ldd_to_gee.py: pure helpers + one tiny end-to-end
slim-shapefile round trip. No GEE, no network, no large files."""
import importlib.util
import sys
import json
import zipfile
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "data" / "ldd" / "upload_ldd_to_gee.py"
_spec = importlib.util.spec_from_file_location("upload_ldd_to_gee", _SCRIPT)
u = importlib.util.module_from_spec(_spec)
sys.modules["upload_ldd_to_gee"] = u
_spec.loader.exec_module(u)


def test_thai_to_en_covers_all_77_and_matches_frontend_names():
    assert len(u._TH_TO_EN) == 77 and len(set(u._TH_TO_EN.values())) == 77
    assert u._TH_TO_EN["มุกดาหาร"] == "Mukdahan"
    assert u._TH_TO_EN["ชัยภูมิ"] == "Chaiyaphum"
    assert "" not in u._TH_TO_EN
    geo = _SCRIPT.parents[2] / "data" / "thailand.json"
    names = {f["properties"]["name"]
             for f in json.loads(geo.read_text(encoding="utf-8"))["features"]}
    assert set(u._TH_TO_EN.values()) == names


@pytest.mark.parametrize("text,en", [
    ("กาญจนบุรี2568.zip", "Kanchanaburi"),
    ("จังหวัดมุกดาหาร ปีล่าสุด 2566", "Mukdahan"),
    ("Landuse_Bangkok_2566_.zip", "Bangkok Metropolis"),
    ("กรุงเทพมหานคร", "Bangkok Metropolis"),
    ("Chiang Mai", "Chiang Mai"),
    ("เพชรบุรี2568", "Phetchaburi"),
    ("เพชรบูรณ์2568", "Phetchabun"),
])
def test_lookup_province(text, en):
    assert u.lookup_province(text)[1] == en


def test_lookup_province_unknown():
    assert u.lookup_province("ภาคกลาง") is None
    assert u.lookup_province("LU_KRI_2568") is None
    assert u.lookup_province("") is None


def test_parse_layer_name_and_year():
    assert u.parse_layer_name("LU_KRI_2568.shp") == ("KRI", 2568)
    assert u.parse_layer_name("Landuse_X/LU_BKK_2566.shp") == ("BKK", 2566)
    assert u.parse_layer_name("KRI_Pro.shp") == (None, None)
    assert u.year_from_text("กาญจนบุรี2568") == 2568
    assert u.year_from_text("abc") is None
    assert u.plan_asset_id("projects/p/assets/ldd/", "KRI", 2568) == \
        "projects/p/assets/ldd/LU_KRI_2568"


def test_select_lu_layer_ignores_boundary_layers():
    names = ["a/KRI_Pro.shp", "a/KRI_Amp.shp", "a/KRI_Tam.shp",
             "a/LU_KRI_2568.shp", "a/LU_KRI_2568.dbf", "a/LUCODE.xls"]
    assert u.select_lu_layer(names) == "a/LU_KRI_2568.shp"
    assert u.select_lu_layer(["x/Amp_KRI.shp", "x/Tam_KRI.shp"]) is None
    assert u.select_lu_layer(["x/LU_AAA_2566.shp", "x/LU_AAA_2568.shp"]) == "x/LU_AAA_2568.shp"


def test_encoding_from_cpg_and_pick():
    assert u.encoding_from_cpg("UTF-8") == "utf-8"
    assert u.encoding_from_cpg("ANSI 874") == "cp874"
    assert u.encoding_from_cpg("874") == "cp874"
    assert u.encoding_from_cpg("TIS-620") == "cp874"
    assert u.encoding_from_cpg("") is None and u.encoding_from_cpg(None) is None
    assert u.encoding_from_cpg("ANSI 1252") is None
    assert u.candidate_encodings("cp874") == ["cp874", "utf-8"]
    assert u.candidate_encodings(None) == ["utf-8", "cp874"]
    shares = {"utf-8": 0.0, "cp874": 0.99}
    assert u.pick_encoding(["utf-8", "cp874"], shares.get) == ("cp874", 0.99)
    shares = {"utf-8": 0.5, "cp874": 0.2}
    assert u.pick_encoding(["utf-8", "cp874"], shares.get)[0] == "utf-8"
    assert u.thai_share(["นา", "x", None, "ป่า"]) == 0.5


def test_merge_registry_keeps_comment_sorts_and_refuses_overwrite():
    data = {"_comment": "keep me", "provinces": {"Tak": {"asset": "a", "year_be": 2568}}}
    out = u.merge_registry(data, "Bangkok Metropolis", "b", 2566)
    assert list(out["provinces"]) == ["Bangkok Metropolis", "Tak"]
    assert out["_comment"] == "keep me" and "Bangkok Metropolis" not in data["provinces"]
    with pytest.raises(u.RegistryConflict):
        u.merge_registry(out, "Tak", "c", 2569)
    again = u.merge_registry(out, "Tak", "c", 2569, overwrite=True)
    assert again["provinces"]["Tak"] == {"asset": "c", "year_be": 2569}
    text = u.registry_text(again)
    assert text.endswith("}\n") and json.loads(text) == again


def test_save_registry_uses_lf_and_unicode(tmp_path):
    p = tmp_path / "r.json"
    u.save_registry(p, {"_comment": "ภาษาไทย", "provinces": {}})
    raw = p.read_bytes()
    assert b"\r" not in raw and "ภาษาไทย".encode() in raw


def test_parse_task_id():
    assert u.parse_task_id("Started upload task with ID: ABCDEFGHIJKLMNOPQRSTUVWX") == \
        "ABCDEFGHIJKLMNOPQRSTUVWX"
    assert u.parse_task_id("Asset ingestion started with task ID: 3J4K5L6M7N8P9Q0R1S2T3U4V") \
        == "3J4K5L6M7N8P9Q0R1S2T3U4V"
    assert u.parse_task_id("nothing here") is None


def test_wait_for_tasks_calls_on_done_and_handles_timeout():
    rows = {"T1": u.Row(province_en="A"), "T2": u.Row(province_en="B")}
    seq = iter([{"T1": ("RUNNING", ""), "T2": ("COMPLETED", "")},
                {"T1": ("FAILED", "bad geometry")}])
    done = []
    u.wait_for_tasks(rows, lambda r, s, m: done.append((r.province_en, s, m)),
                     get_states=lambda ids: next(seq), sleep=lambda s: None)
    assert done == [("B", "COMPLETED", ""), ("A", "FAILED", "bad geometry")]
    stuck = {"T9": u.Row()}
    u.wait_for_tasks(stuck, lambda *a: None, timeout_seconds=-1,
                     get_states=lambda ids: {"T9": ("RUNNING", "")}, sleep=lambda s: None)
    assert stuck["T9"].status.startswith("TIMEOUT")


def _write_source(path: Path, encoding: str, with_id=True):
    import fiona
    from fiona.crs import CRS
    props = {"LU_CODE": "str:20", "LU_DES_TH": "str:80", "OTHER": "str:10"}
    if with_id:
        props["LU_ID_L1"] = "str:4"
    rows = [("A101", "นาข้าว", "3"), (" A405/A411 ", "สวนผสม", "2"), ("U101", "ชุมชน", "x")]
    with fiona.open(path, "w", driver="ESRI Shapefile",
                    schema={"geometry": "Polygon", "properties": props},
                    crs=CRS.from_epsg(32647), encoding=encoding) as dst:
        for i, (code, des, lid) in enumerate(rows):
            x = i * 10.0
            p = {"LU_CODE": code, "LU_DES_TH": des, "OTHER": "z"}
            if with_id:
                p["LU_ID_L1"] = lid
            dst.write({"geometry": {"type": "Polygon", "coordinates": [[
                (x, 0), (x + 5, 0), (x + 5, 5), (x, 0)]]}, "properties": p})


@pytest.mark.parametrize("encoding,cpg", [("utf-8", "UTF-8"), ("cp874", "ANSI 874")])
def test_slim_shapefile_round_trip(tmp_path, encoding, cpg):
    import fiona
    src = tmp_path / "src" / "LU_TST_2568.shp"
    src.parent.mkdir()
    _write_source(src, encoding)
    res = u.slim_shapefile(src, tmp_path / "slim" / "LU_TST_2568", "LU_TST_2568")
    assert res.features == 3 and res.encoding == encoding
    assert res.thai_ok_pct == 100.0 and res.lu_code_ok_pct == 100.0
    assert res.distinct_codes == 3 and round(res.compound_pct, 2) == 33.33
    assert res.has_lu_id_l1 and not res.warnings
    with zipfile.ZipFile(res.zip_path) as z:
        names = set(z.namelist())
        assert {"LU_TST_2568.shp", "LU_TST_2568.shx", "LU_TST_2568.dbf",
                "LU_TST_2568.prj", "LU_TST_2568.cpg"} <= names
        assert z.read("LU_TST_2568.cpg").decode().strip().lower().replace("-", "") == "utf8"
        z.extractall(tmp_path / "unz")
    with fiona.open(tmp_path / "unz" / "LU_TST_2568.shp", encoding="utf-8") as chk:
        assert set(chk.schema["properties"]) == {"LU_CODE", "LU_DES_TH", "LU_ID_L1"}
        feats = list(chk)
        assert chk.crs.to_epsg() == 32647
    assert [f["properties"]["LU_DES_TH"] for f in feats] == ["นาข้าว", "สวนผสม", "ชุมชน"]
    assert [f["properties"]["LU_CODE"] for f in feats] == ["A101", "A405/A411", "U101"]
    assert [f["properties"]["LU_ID_L1"] for f in feats] == [3, 2, None]


def test_slim_shapefile_omits_lu_id_l1_when_absent(tmp_path):
    import fiona
    src = tmp_path / "LU_TST_2568.shp"
    _write_source(src, "utf-8", with_id=False)
    res = u.slim_shapefile(src, tmp_path / "o" / "LU_TST_2568", "LU_TST_2568")
    assert not res.has_lu_id_l1
    with fiona.open(tmp_path / "o" / "LU_TST_2568" / "LU_TST_2568.shp") as chk:
        assert set(chk.schema["properties"]) == {"LU_CODE", "LU_DES_TH"}


def test_discover_nested_zip_and_end_to_end_dry_run(tmp_path, capsys):
    src = tmp_path / "s"
    src.mkdir()
    shp = src / "LU_TAK_2568.shp"
    _write_source(shp, "utf-8")
    inner = tmp_path / "ตาก2568.zip"
    with zipfile.ZipFile(inner, "w") as z:
        for ext in u.SIDECARS:
            if (src / f"LU_TAK_2568{ext}").exists():
                z.write(src / f"LU_TAK_2568{ext}", f"Pack/LU_TAK_2568{ext}")
        z.writestr("Pack/TAK_Pro.shp", b"x")
    outer = tmp_path / "ภาคเหนือ.zip"
    with zipfile.ZipFile(outer, "w") as z:
        z.write(inner, inner.name)
    errors = []
    pkgs = list(u.discover([outer], errors))
    assert not errors and len(pkgs) == 1
    th, en, year, abbr = u.resolve_package(pkgs[0])
    assert (en, year, abbr) == ("Tak", 2568, "TAK")
    registry = tmp_path / "gee_assets.json"
    work = tmp_path / "work"
    rc = u.main(["--src", str(outer), "--workdir", str(work), "--registry", str(registry),
                 "--asset-root", "projects/p/assets/ldd"])
    assert rc == 0 and not registry.exists()
    report = (work / "ldd_upload_report.csv").read_text(encoding="utf-8-sig")
    assert "Tak" in report and "projects/p/assets/ldd/LU_TAK_2568" in report
    assert "dry-run ok" in report
