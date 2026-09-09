"""
One-time script — add `name_th` (Thai district name) into every feature of
green-area-frontend/public/thailand_districts.json.

Source: github.com/kongvut/thai-province-data (CC0)

Run:
    python add_district_th_names.py
"""
import json
import os
import re
import sys
import urllib.request

KONGVUT_PROVINCE = "https://raw.githubusercontent.com/kongvut/thai-province-data/refs/heads/master/api/latest/province.json"
KONGVUT_DISTRICT = "https://raw.githubusercontent.com/kongvut/thai-province-data/refs/heads/master/api/latest/district.json"

_HERE = os.path.dirname(os.path.abspath(__file__))
# ปลายทางเดียวกับ generate_districts.OUTPUT_PATHS — frontend/public (vite copy ลง
# build/ ให้ browser fetch ได้) + backend/data (อยู่ใน build context ของ Dockerfile
# จึงติดไปใน image) · สคริปต์นี้เป็นขั้นสุดท้ายของ pipeline จึงต้องเขียนครบทุกสำเนา
# ไม่งั้นสำเนาที่ไปกับ image จะไม่มีชื่อไทย
OUTPUT_PATHS = (
    os.path.normpath(os.path.join(_HERE, "..", "green-area-frontend", "public",
                                  "thailand_districts.json")),
    os.path.normpath(os.path.join(_HERE, "data", "thailand_districts.json")),
)

PROVINCE_EN_OVERRIDES = {
    "Bangkok":         "Bangkok Metropolis",
    "Buriram":         "Buri Ram",
    "Chonburi":        "Chon Buri",
    "Chainat":         "Chai Nat",
    "Lopburi":         "Lop Buri",
    "Nongbua Lam Phu": "Nong Bua Lam Phu",
    "Phangnga":        "Phangnga",
    "Phra Nakhon Si Ayutthaya": "Phra Nakhon Si Ayutthaya",
    "Prachinburi":     "Prachin Buri",
    "Singburi":        "Sing Buri",
    "Sisaket":         "Si Sa Ket",
    "Suphanburi":      "Suphan Buri",
    "Ubonratchathani": "Ubon Ratchathani",
    "Udonthani":       "Udon Thani",
    "Uthaithani":      "Uthai Thani",
}

# Generic prefixes — iteratively stripped after the K. handler below.
GENERIC_PREFIXES = ("khet", "mueang", "muang", "amphoe", "koh")


def strict(name: str) -> str:
    """Strict normalization that survives Thai romanization quirks.

    1. Strip GADM's "K." (king-amphoe / กิ่งอำเภอ) marker BEFORE we lose the dot.
    2. Strip whitespace/punct.
    3. Iteratively strip generic admin prefixes (so AmphoeMuangX → X).
    """
    s = name.lower().strip()
    if s.startswith(("k.", "k ")) and len(s) > 4:
        s = s[2:].lstrip()
    s = re.sub(r"[\s\-\.\(\)]+", "", s)
    while True:
        before = s
        for pre in GENERIC_PREFIXES:
            if s.startswith(pre) and len(s) > len(pre) + 2:
                s = s[len(pre):]
                break
        if s == before:
            return s


def loose(name: str) -> str:
    """Phonetic-loose normalization to bridge romanization variants."""
    s = strict(name)
    # Drop the aspiration "h" after p/t/k/c (Thai aspirated stops)
    s = re.sub(r"([ptkc])h", r"\1", s)
    # Vowel cluster simplifications
    s = (s
         .replace("uea", "ua")
         .replace("eo", "o")
         .replace("ae", "a")
         .replace("ue", "u")
         .replace("oey", "oi")
         .replace("oei", "oi")
         .replace("oy", "oi")
         .replace("ee", "i")
         .replace("ie", "i")
         .replace("ia", "i")
         .replace("ay", "ai")
         .replace("aw", "o")
         .replace("ow", "o")
         .replace("iu", "io"))
    # Drop trailing "r" inside consonant clusters (Sathorn → Sathon)
    s = re.sub(r"r([bcdfghjklmnpqstvwxyz])", r"\1", s)
    # Equivalence for final stops: d→t, b→p, g→k
    s = re.sub(r"d$", "t", s)
    s = re.sub(r"b$", "p", s)
    s = re.sub(r"g$", "k", s)
    # Collapse double letters
    s = re.sub(r"(.)\1+", r"\1", s)
    return s


# Hand-curated rescue map for the long tail. Keys use strict() output.
# Each value is the canonical Thai district name (ราชบัณฑิตยสถาน-style).
MANUAL_OVERRIDES = {
    # "Chaloem Phra Kiat" — spelled "Chalermphrakiet" in GADM, appears in many provinces
    ("Buri Ram",            "chalermphrakiet"): "เฉลิมพระเกียรติ",
    ("Nakhon Ratchasima",   "chalermphrakiet"): "เฉลิมพระเกียรติ",
    ("Nakhon Si Thammarat", "chalermphrakiet"): "เฉลิมพระเกียรติ",
    ("Nan",                 "chalermphrakiet"): "เฉลิมพระเกียรติ",
    ("Saraburi",            "chalermphrakiet"): "เฉลิมพระเกียรติ",

    # Bangkok
    ("Bangkok Metropolis", "khannayao"):    "เขตคันนายาว",
    ("Bangkok Metropolis", "khlongsamwa"):  "เขตคลองสามวา",
    ("Bangkok Metropolis", "khlongsan"):    "เขตคลองสาน",

    # Long tail by province (alphabetical)
    ("Amnat Charoen",       "pathumratwongsa"):   "ปทุมราชวงศา",
    ("Buri Ram",            "banmaichaipho"):     "บ้านใหม่ไชยพจน์",
    ("Buri Ram",            "daenkong"):          "แคนดง",
    ("Buri Ram",            "nondindaeng"):       "โนนดินแดง",
    ("Chachoengsao",        "khlongkhuan"):       "คลองเขื่อน",
    ("Chaiyaphum",          "kaengkhlo"):         "แก้งคร้อ",
    ("Chaiyaphum",          "kasetsombon"):       "เกษตรสมบูรณ์",
    ("Chaiyaphum",          "nongbuarawae"):      "หนองบัวระเหว",
    ("Chaiyaphum",          "phakdichumphol"):    "ภักดีชุมพล",
    ("Chanthaburi",         "kaokichakut"):       "เขาคิชฌกูฏ",
    ("Chanthaburi",         "soydow"):            "สอยดาว",
    ("Chiang Rai",          "wiengchiang"):       "เวียงเชียงรุ้ง",
    ("Chon Buri",           "kochan"):            "เกาะจันทร์",
    ("Kalasin",             "kongchai"):          "ฆ้องชัย",
    ("Kalasin",             "nadu"):              "นาคู",
    ("Kamphaeng Phet",      "kosampinakhon"):     "โกสัมพีนคร",
    ("Kamphaeng Phet",      "klongkhlung"):       "คลองขลุง",
    ("Kamphaeng Phet",      "klonglan"):          "คลองลาน",
    ("Kanchanaburi",        "thongphaphum"):      "ทองผาภูมิ",
    ("Khon Kaen",           "khokphocha"):        "โคกโพธิ์ไชย",
    ("Lop Buri",            "sraboth"):           "สระโบสถ์",
    ("Maha Sarakham",       "chiangyun"):         "เชียงยืน",
    ("Maha Sarakham",       "kutrang"):           "กุดรัง",
    ("Nakhon Ratchasima",   "muangyang"):         "เมืองยาง",
    ("Nakhon Ratchasima",   "khamthalaso"):       "ขามทะเลสอ",
    ("Nakhon Ratchasima",   "wangnumkhiaw"):      "วังน้ำเขียว",
    # GADM spells it "NongBunnak"; kongvut has "Nong Bun Mak" — normalizers miss it.
    ("Nakhon Ratchasima",   "nongbunnak"):        "หนองบุญมาก",
    ("Nakhon Sawan",        "latyao"):            "ลาดยาว",
    ("Nakhon Sawan",        "thatako"):           "ท่าตะโก",
    ("Nakhon Si Thammarat", "chulaphon"):         "จุฬาภรณ์",
    ("Nakhon Si Thammarat", "ronphipun"):         "ร่อนพิบูลย์",
    ("Nan",                 "boklue"):            "บ่อเกลือ",
    ("Narathiwat",          "choirong"):          "เจาะไอร้อง",
    ("Nong Bua Lam Phu",    "suwankhuha"):        "สุวรรณคูหา",
    ("Phatthalung",         "srinakarin"):        "ศรีนครินทร์",
    ("Phetchabun",          "buangsamphan"):      "บึงสามพัน",
    ("Phichit",             "phoprathapchan"):    "โพธิ์ประทับช้าง",
    ("Prachin Buri",        "srimaharpho"):       "ศรีมหาโพธิ",
    ("Rayong",              "khaochamao"):        "เขาชะเมา",
    ("Rayong",              "nikhompattan"):      "นิคมพัฒนา",
    ("Roi Et",              "chaturaphakphim"):   "จตุรพักตรพิมาน",
    ("Roi Et",              "thungkaolua"):       "ทุ่งเขาหลวง",
    ("Roi Et",              "thawatchaburi"):     "ธวัชบุรี",
    ("Sa Kaeo",             "koksung"):           "โคกสูง",
    ("Sa Kaeo",             "kaochakan"):         "เขาฉกรรจ์",
    ("Sakon Nakhon",        "chareonsilp"):       "เจริญศิลป์",
    ("Sakon Nakhon",        "khoksrisupan"):      "โคกศรีสุพรรณ",
    ("Samut Prakan",        "bangsaothon"):       "บางเสาธง",
    ("Samut Prakan",        "phrasamutjadee"):    "พระสมุทรเจดีย์",
    ("Si Sa Ket",           "sriratana"):         "ศรีรัตนะ",
    ("Songkhla",            "krasaesinthu"):      "กระแสสินธุ์",
    ("Suphan Buri",         "doembangnangbua"):   "เดิมบางนางบวช",
    ("Surat Thani",         "wipawadi"):          "วิภาวดี",
    ("Surat Thani",         "khiriratthanikhom"): "คีรีรัฐนิคม",
    ("Surin",               "kwaosinarin"):       "เขวาสินรินทร์",
    ("Surin",               "srinarong"):         "ศรีณรงค์",
    ("Trang",               "kantrang"):          "กันตัง",
    ("Trang",               "rasada"):            "รัษฎา",
    ("Trat",                "kochang"):           "เกาะช้าง",
    ("Trat",                "kokut"):             "เกาะกูด",
    ("Ubon Ratchathani",    "sawangweeraw"):      "สว่างวีระวงศ์",
    ("Ubon Ratchathani",    "phosi"):             "โพธิ์ไทร",
    ("Ubon Ratchathani",    "sirinton"):          "สิรินธร",
    ("Udon Thani",          "kukaeo"):            "กู่แก้ว",
    ("Udon Thani",          "prachaksilapakhom"): "ประจักษ์ศิลปาคม",
    ("Yala",                "krongpinung"):       "กรงปินัง",
    ("Yasothon",            "yasothon"):          "เมืองยโสธร",

    # Final stragglers
    ("Bangkok Metropolis",  "nongkheam"):     "เขตหนองแขม",
    ("Bangkok Metropolis",  "pompramsattru"): "เขตป้อมปราบศัตรูพ่าย",
    ("Chai Nat",            "sanphaya"):      "สรรพยา",
    ("Nakhon Si Thammarat", "phrommakhiri"):  "พรหมคีรี",
    ("Narathiwat",          "janae"):         "จะแนะ",
    ("Yala",                "bannangstar"):   "บันนังสตา",
    ("Yala",                "batong"):        "เบตง",
    # "SongkhlaLake" is actually the lake polygon in GADM, not an amphoe.
    # Label it as the lake so users don't see "SongkhlaLake" in English.
    ("Phatthalung", "songkhlalake"): "ทะเลสาบสงขลา",
    ("Songkhla",    "songkhlalake"): "ทะเลสาบสงขลา",
}


def fetch_json(url: str):
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    geojson_path = OUTPUT_PATHS[0]

    if not os.path.exists(geojson_path):
        print(f"X Not found: {geojson_path}", file=sys.stderr)
        sys.exit(1)

    print("Fetching reference data ...")
    provinces = fetch_json(KONGVUT_PROVINCE)
    districts = fetch_json(KONGVUT_DISTRICT)
    print(f"  - {len(provinces)} provinces, {len(districts)} districts")

    pid_to_en = {}
    for p in provinces:
        en = p["name_en"].strip()
        en = PROVINCE_EN_OVERRIDES.get(en, en)
        pid_to_en[p["id"]] = en

    strict_lookup = {}
    loose_lookup  = {}
    for d in districts:
        prov_en = pid_to_en.get(d["province_id"])
        if not prov_en:
            continue
        strict_lookup[(prov_en, strict(d["name_en"]))] = d["name_th"]
        loose_lookup[(prov_en, loose(d["name_en"]))]   = d["name_th"]

    print(f"  - strict lookup: {len(strict_lookup)} entries")
    print(f"  - loose  lookup: {len(loose_lookup)} entries\n")

    with open(geojson_path, "r", encoding="utf-8") as f:
        geo = json.load(f)

    total           = 0
    matched_manual  = 0
    matched_strict  = 0
    matched_loose   = 0
    matched_global  = 0
    unmatched       = []

    for feat in geo["features"]:
        total += 1
        props    = feat["properties"]
        prov_en  = props.get("province", "")
        dist_en  = props.get("name", "")
        key_strict = (prov_en, strict(dist_en))
        key_loose  = (prov_en, loose(dist_en))

        thai = MANUAL_OVERRIDES.get(key_strict)
        if thai:
            matched_manual += 1
        else:
            thai = strict_lookup.get(key_strict)
            if thai:
                matched_strict += 1
            else:
                thai = loose_lookup.get(key_loose)
                if thai:
                    matched_loose += 1
                else:
                    cands = {v for (p, n), v in loose_lookup.items() if n == key_loose[1]}
                    if len(cands) == 1:
                        thai = next(iter(cands))
                        matched_global += 1

        if thai:
            props["name_th"] = thai
        else:
            props["name_th"] = dist_en  # graceful fallback
            unmatched.append(f"{prov_en} :: {dist_en}")

    # เขียนกลับทุกสำเนา ไม่ใช่แค่ไฟล์ที่อ่านมา — สคริปต์นี้เป็นขั้น *สุดท้าย* ของ
    # pipeline (generate_districts.py แล้วต่อด้วยตัวนี้) ถ้าเขียนแต่ frontend/public
    # สำเนาใน backend/data ที่ไปกับ Docker image จะไม่มีชื่อไทยเลย
    payload = json.dumps(geo, ensure_ascii=False, separators=(",", ":"))
    for path in OUTPUT_PATHS:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(payload)

    matched_total = matched_manual + matched_strict + matched_loose + matched_global
    print(f"OK  Patched {matched_total}/{total} districts with Thai names")
    print(f"      manual={matched_manual}  strict={matched_strict}  loose={matched_loose}  global={matched_global}  unmatched={len(unmatched)}")
    for path in OUTPUT_PATHS:
        print(f"      File: {path}")
    if unmatched:
        print("\nUnmatched (kept English):")
        for u in unmatched:
            print(f"   - {u}")


if __name__ == "__main__":
    main()
