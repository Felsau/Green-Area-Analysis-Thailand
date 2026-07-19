"""Generate ../../ldd_codes.py จาก DBF ของ shapefile LDD (pure stdlib, ไม่มี dep).

legend (LU_CODE → ประเภทหลัก 1–5 + ชื่อ TH/EN) ควร generate จากข้อมูลต้นทางเสมอ
เพื่อกันพิมพ์ผิด — รันใหม่เมื่อชุดข้อมูล LDD เปลี่ยน

    cd green-area-backend/data/ldd
    python generate_ldd_codes.py path/to/LU_BKK_2566.dbf
"""
import struct
import sys
from pathlib import Path

_L1_VALUE = {"U": 1, "A": 2, "F": 3, "W": 4, "M": 5}
_OUT = Path(__file__).resolve().parents[2] / "ldd_codes.py"


def read_dbf_codes(dbf_path: str) -> dict[str, tuple[int, str, str]]:
    """อ่าน DBF → {LU_CODE: (l1_value, name_th, name_en)} (encoding UTF-8 ตาม .cpg)"""
    with open(dbf_path, "rb") as f:
        header = f.read(32)
        n_records = struct.unpack("<I", header[4:8])[0]
        header_len = struct.unpack("<H", header[8:10])[0]
        record_len = struct.unpack("<H", header[10:12])[0]

        fields, offset = [], 1
        while True:
            fd = f.read(32)
            if fd[0:1] == b"\r" or len(fd) < 32:
                break
            name = fd[0:11].split(b"\x00")[0].decode("latin1")
            length = fd[16]
            fields.append((name, offset, length))
            offset += length

        def decode(raw: bytes) -> str:
            try:
                return raw.decode("utf-8").strip()
            except UnicodeDecodeError:
                return raw.decode("latin1").strip()

        f.seek(header_len)
        codes: dict[str, tuple[int, str, str]] = {}
        for _ in range(n_records):
            rec = f.read(record_len)
            if len(rec) < record_len:
                break
            row = {name: decode(rec[off:off + length]) for name, off, length in fields}
            code = row["LU_CODE"]
            if code and code not in codes:
                codes[code] = (_L1_VALUE[row["LUL1_CODE"]],
                               row["LU_DES_TH"], row["LU_DES_EN"])
        return codes


def emit_module(codes: dict[str, tuple[int, str, str]]) -> None:
    lines = [
        '"""LDD detailed land-use legend — 96 codes (LU_CODE) → main type + TH/EN name.',
        "",
        "AUTO-GENERATED from LU_BKK_2566.dbf (LDD Bangkok 2566). Do not hand-edit;",
        "regenerate via data/ldd/generate_ldd_codes.py if the classification changes.",
        '"""',
        "",
        "# LU_CODE -> (l1_value 1-5, name_th, name_en). l1_value ยึด LUL1_CODE (U/A/F/W/M).",
        "LDD_LU_CODES = {",
    ]
    for code in sorted(codes):
        l1, th, en = codes[code]
        th = th.replace('"', '\\"')
        en = en.replace('"', '\\"')
        lines.append(f'    "{code}": ({l1}, "{th}", "{en}"),')
    lines.append("}")
    _OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python generate_ldd_codes.py path/to/LU_BKK_2566.dbf")
    parsed = read_dbf_codes(sys.argv[1])
    emit_module(parsed)
    print(f"wrote {_OUT} — {len(parsed)} codes")
