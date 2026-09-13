"""Province → region mapping + per-region tree species recommendations.

บัญชีพันธุ์ไม้อยู่ใน `data/tree_species.json` (ไม่ได้เขียนคงที่ในโค้ดแล้ว) ทุกชนิด
แนบบล็อก `verification` ที่ตรวจกับ BGCI GlobalTreeSearch / Kew WCVP / GBIF ไว้ —
ดู refresh_species_verification.py สำหรับวิธีสร้างใหม่

ภาค (region) ของแต่ละจังหวัดอ่านจากตาราง `provinces` (single source of truth หลัง
migration 006) ผ่าน `_region_for()` ที่ cache ผลไว้ · `PROVINCE_REGION` ด้านล่างเป็น
ทั้ง seed ของตารางนั้นและ fallback กรณี DB ยังไม่มีข้อมูล/เชื่อมไม่ได้
"""
import json
import logging
import os
from collections import Counter
from functools import lru_cache

from landuse import LANDUSE_CATEGORIES

logger = logging.getLogger(__name__)

# จับจังหวัด → ภาค (ใช้แบ่งตามภูมิอากาศ/ดินที่เหมาะกับพันธุ์ไม้)
THAI_REGIONS = {
    "เหนือ": {
        "Chiang Mai", "Chiang Rai", "Lampang", "Lamphun", "Mae Hong Son",
        "Nan", "Phayao", "Phrae", "Uttaradit",
    },
    "อีสาน": {
        "Amnat Charoen", "Bueng Kan", "Buri Ram", "Chaiyaphum", "Kalasin",
        "Khon Kaen", "Loei", "Maha Sarakham", "Mukdahan", "Nakhon Phanom",
        "Nakhon Ratchasima", "Nong Bua Lam Phu", "Nong Khai", "Roi Et",
        "Sakon Nakhon", "Si Sa Ket", "Surin", "Ubon Ratchathani",
        "Udon Thani", "Yasothon",
    },
    "กลาง": {
        "Ang Thong", "Bangkok Metropolis", "Chai Nat", "Kamphaeng Phet",
        "Lop Buri", "Nakhon Nayok", "Nakhon Pathom", "Nakhon Sawan",
        "Nonthaburi", "Pathum Thani", "Phetchabun", "Phichit", "Phitsanulok",
        "Phra Nakhon Si Ayutthaya", "Samut Prakan", "Samut Sakhon",
        "Samut Songkhram", "Saraburi", "Sing Buri", "Sukhothai",
        "Suphan Buri", "Uthai Thani",
    },
    "ตะวันออก": {
        "Chachoengsao", "Chanthaburi", "Chon Buri", "Prachin Buri",
        "Rayong", "Sa Kaeo", "Trat",
    },
    "ตะวันตก": {
        "Kanchanaburi", "Phetchaburi", "Prachuap Khiri Khan",
        "Ratchaburi", "Tak",
    },
    "ใต้": {
        "Chumphon", "Krabi", "Nakhon Si Thammarat", "Narathiwat", "Pattani",
        "Phangnga", "Phatthalung", "Phuket", "Ranong", "Satun", "Songkhla",
        "Surat Thani", "Trang", "Yala",
    },
}
PROVINCE_REGION = {p: r for r, ps in THAI_REGIONS.items() for p in ps}
# บัญชีพันธุ์ไม้แนะนำต่อภาค — โหลดจาก data/tree_species.json ไม่ใช่เขียนคงที่ในโค้ด
# ไฟล์นั้นเก็บทั้งข้อมูลที่โครงงานกำหนดเอง (name_th/traits/purpose/height_m/reason)
# และบล็อก `verification` ที่สร้างอัตโนมัติจากฐานข้อมูลภายนอก 3 แหล่ง (BGCI
# GlobalTreeSearch, Kew WCVP, GBIF) ด้วย refresh_species_verification.py →
# ตอบได้ว่าพันธุ์แต่ละชนิด "มาจากไหน" และตรวจย้อนกลับได้ทุกชนิด
# verification ถูกส่งต่อไปกับคำตอบของ API ให้หน้าเว็บแสดงแหล่งอ้างอิงได้
SPECIES_DATA_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "tree_species.json")


def _load_species_data(path: str = SPECIES_DATA_PATH) -> tuple[dict, dict]:
    """อ่านบัญชีพันธุ์ไม้จากไฟล์ข้อมูล → ({ภาค: [พันธุ์...]}, metadata).

    ไฟล์นี้เป็น asset ที่ระบบต้องมี (เหมือน data/thailand.json) — ถ้าหายให้ล้มทันที
    พร้อมข้อความที่บอกวิธีสร้างใหม่ ดีกว่าปล่อยให้ endpoint คืนรายการว่างเงียบ ๆ
    """
    try:
        with open(path, encoding="utf-8") as f:
            payload = json.load(f)
    except FileNotFoundError:
        raise RuntimeError(
            f"ไม่พบไฟล์บัญชีพันธุ์ไม้ {path} — สร้างใหม่ด้วย "
            "`python refresh_species_verification.py`") from None
    meta = {k: v for k, v in payload.items() if k != "regions"}
    return payload["regions"], meta


TREE_SPECIES_BY_REGION, SPECIES_DATA_META = _load_species_data()


@lru_cache(maxsize=1)
def _db_region_map() -> dict:
    """โหลด {name_en: region} จากตาราง provinces (normalized source) — cache ไว้ครั้งเดียว.

    คืน {} ถ้า DB ยังไม่มีข้อมูล/migration 006 ยังไม่รัน/เชื่อมไม่ได้ → caller fallback
    ไป PROVINCE_REGION (hardcoded) · import supa_call แบบ lazy กัน import-time DB coupling
    """
    try:
        from dependencies import supa_call
        rows = supa_call(lambda s: s.table("provinces")
                         .select("name_en,region").execute()).data
        return {r["name_en"]: r["region"] for r in rows} if rows else {}
    except Exception as e:
        logger.warning("⚠️  provinces lookup failed — fallback to hardcoded region map: %s", e)
        return {}


def _region_for(province_name: str) -> str | None:
    """ภาคของจังหวัด — DB (provinces) เป็นหลัก, fallback hardcoded PROVINCE_REGION"""
    return _db_region_map().get(province_name) or PROVINCE_REGION.get(province_name)


# Site-aware ranking
# จัดอันดับพันธุ์ภายในภาคตามสภาพจุดจริง (LST ร้อน / NDVI เสื่อมโทรม / เขียวพอควร)
# ดันพันธุ์ที่ traits ตรงความต้องการของพื้นที่ขึ้นก่อน · ไม่มี signal = ลำดับภาคเดิม
HOT_LST_C = 35.0   # LST เฉลี่ย >= นี้ = ร้อน → ดันพันธุ์ร่มเงา/ลดความร้อน
LOW_NDVI = 0.35    # NDVI เฉลี่ย < นี้ = เสื่อมโทรม/ขาดพืช → ดันพันธุ์ทนทาน/บุกเบิก
HIGH_NDVI = 0.50   # NDVI เฉลี่ย >= นี้ = เขียวพอควร → ดันพันธุ์พื้นถิ่น/หลากหลาย

_SHADE_KEYWORDS = ("ร่มเงา", "ลดความร้อน", "ทรงพุ่ม")
_HARDY_KEYWORDS = ("ทนแล้ง", "โตเร็ว", "ตรึงไนโตรเจน", "ฟื้นฟูดิน", "ดินเสื่อม",
                   "ดินไม่ดี", "ทนมลพิษ", "ดักฝุ่น")
_BIODIV_KEYWORDS = ("พื้นถิ่น", "อายุยืน", "ผลกินได้", "ผลใช้ประโยชน์", "นกชอบ",
                    "ใกล้สูญพันธุ์", "เฉพาะถิ่น")

# Land-use fit (การใช้ที่ดินเด่นของจุดแนะนำ → บริบทการปลูก)
# ที่ดินแต่ละประเภทต้องการพันธุ์ต่างกัน: ชุมชนต้องทนมลพิษ เกษตรควรได้ไม้ผล/วนเกษตร
# ที่เบ็ดเตล็ด (ที่ว่าง/ทุ่งหญ้า) เหมาะไม้บุกเบิกฟื้นฟู · code ตาม schema 5 ประเภท
# LDD (landuse.LANDUSE_CATEGORIES) · additive ต่อสัญญาณ LST/NDVI เดิม — ไม่แทนที่
LANDUSE_KEYWORDS = {
    "U": (("ทนมลพิษ", "ริมถนน", "ดักฝุ่น", "ในเมือง", "ชุมชน", "PM2.5", "เทศบาล"),
          "เหมาะกับเขตชุมชน — การใช้ที่ดินเด่นของจุดแนะนำ"),
    "A": (("ผลไม้", "ผลกินได้", "ผลใช้ประโยชน์", "ผลผลิต", "เศรษฐกิจ",
           "ตรึงไนโตรเจน", "รายได้"),
          "เหมาะปลูกแซมพื้นที่เกษตร (วนเกษตร)"),
    "F": (("พื้นถิ่น", "ฟื้นฟูป่า", "อายุยืน", "หลากหลาย"),
          "เหมาะปลูกเสริมป่าเดิม"),
    "W": (("ทนน้ำท่วม", "ริมน้ำ", "ริมแหล่งน้ำ", "ที่ลุ่ม"),
          "เหมาะพื้นที่ริมน้ำ/ทนน้ำท่วม"),
    "M": (("ฟื้นฟู", "โตเร็ว", "ดินเสื่อม", "ดินไม่ดี", "ทนแล้ง"),
          "เหมาะฟื้นฟูพื้นที่ว่าง/ที่ดินเบ็ดเตล็ด"),
}
LANDUSE_FIT_SCORE = 2

# เกณฑ์ "การใช้ที่ดินเด่น" ของชุดจุดแนะนำ — ประเภทที่พบมากสุดต้องมีอย่างน้อย
# DOMINANT_MIN_COUNT จุด และครอบคลุม ≥ DOMINANT_MIN_SHARE ของจุดที่มีป้าย
# ไม่ผ่านเกณฑ์ = สัญญาณไม่ชัด → ไม่ boost (คืนลำดับตาม LST/NDVI เดิม)
DOMINANT_MIN_SHARE = 0.4
DOMINANT_MIN_COUNT = 2


def dominant_spot_landuse(top_locations: list | None) -> str | None:
    """code การใช้ที่ดินเด่น (U/A/F/W/M) ของจุด top-locations — None ถ้าสัญญาณไม่ชัด.

    อ่านจากป้าย `landuse` ที่ scoring ติดมาต่อจุด · จุดจาก cache รุ่นเก่า (ก่อน v7)
    ไม่มีป้าย → ถูกข้าม · pure function ทดสอบได้โดยไม่แตะ GEE
    """
    codes = [loc["landuse"].get("code") for loc in (top_locations or [])
             if isinstance(loc, dict) and isinstance(loc.get("landuse"), dict)]
    codes = [c for c in codes if c]
    if not codes:
        return None
    code, count = Counter(codes).most_common(1)[0]
    if count >= DOMINANT_MIN_COUNT and count / len(codes) >= DOMINANT_MIN_SHARE:
        return code
    return None


def _site_fit(sp: dict, *, hot: bool, degraded: bool, green: bool,
              landuse_code: str | None = None) -> tuple[int, str | None]:
    """คืน (score, reason) ของพันธุ์ 1 ชนิดเทียบสภาพพื้นที่ — match keyword ใน traits/purpose/reason"""
    text = " ".join(sp.get("traits", [])) + " " + sp.get("purpose", "") + " " + sp.get("reason", "")
    score, reasons = 0, []
    if hot and any(k in text for k in _SHADE_KEYWORDS):
        score += 2
        reasons.append("ให้ร่มเงาในพื้นที่ร้อน")
    if degraded and any(k in text for k in _HARDY_KEYWORDS):
        score += 2
        reasons.append("ทนทาน เหมาะพื้นที่เสื่อมโทรม")
    if green and any(k in text for k in _BIODIV_KEYWORDS):
        score += 1
        reasons.append("เสริมความหลากหลายพันธุ์พื้นถิ่น")
    if landuse_code in LANDUSE_KEYWORDS:
        keywords, why = LANDUSE_KEYWORDS[landuse_code]
        if any(k in text for k in keywords):
            score += LANDUSE_FIT_SCORE
            reasons.append(why)
    return score, (" · ".join(reasons) if reasons else None)


def rank_species_by_site(species: list, lst_mean=None, ndvi_mean=None,
                         landuse_code: str | None = None) -> list:
    """จัดอันดับพันธุ์ตามสภาพพื้นที่ — คืน list ใหม่ของ dict ที่เติม key 'site_fit'
    (เหตุผล หรือ None) · ไม่มี signal เลย (ทั้ง lst/ndvi/landuse) → คืนลำดับเดิม.

    ไม่กลายพันธุ์ (mutate) species เดิม · sort เสถียร คะแนนเท่ากันคงลำดับภาคไว้
    """
    if lst_mean is None and ndvi_mean is None and landuse_code is None:
        return species
    hot = lst_mean is not None and lst_mean >= HOT_LST_C
    degraded = ndvi_mean is not None and ndvi_mean < LOW_NDVI
    green = ndvi_mean is not None and ndvi_mean >= HIGH_NDVI
    scored = []
    for sp in species:
        score, reason = _site_fit(sp, hot=hot, degraded=degraded, green=green,
                                  landuse_code=landuse_code)
        scored.append((score, {**sp, "site_fit": reason}))
    # key=score เท่านั้น (ไม่เทียบ dict) · reverse=True ยัง stable → ตีเสมอคงลำดับภาค
    scored.sort(key=lambda t: t[0], reverse=True)
    return [sp for _, sp in scored]


def rerank_species_for_spots(species_info: dict, top_locations: list | None,
                             lst_mean=None, ndvi_mean=None) -> dict:
    """Re-rank พันธุ์ตามการใช้ที่ดินเด่นของจุดแนะนำ — additive ต่อ ranking LST/NDVI.

    เรียกหลังได้ top_locations (คำนวณสดหรือจาก cache) · สัญญาณไม่ชัด/ไม่มีป้าย →
    คืน species_info เดิมไม่แตะ · เมื่อ boost แล้วเติม `landuse_context` {code, name_th}
    ให้ UI บอกได้ว่าจัดอันดับโดยคำนึงถึงที่ดินแบบไหน · ไม่ mutate ของเดิม
    """
    code = dominant_spot_landuse(top_locations)
    if code is None or not species_info.get("species"):
        return species_info
    ranked = rank_species_by_site(species_info["species"], lst_mean, ndvi_mean,
                                  landuse_code=code)
    cat = next((c for c in LANDUSE_CATEGORIES if c["code"] == code), None)
    return {**species_info, "species": ranked,
            "landuse_context": {"code": code,
                                "name_th": cat["name_th"] if cat else code}}


def get_recommended_species(province_name: str, lst_mean=None, ndvi_mean=None):
    """คืนพันธุ์ไม้แนะนำตามภาค + จัดอันดับตามสภาพพื้นที่ (ถ้าส่ง lst_mean/ndvi_mean)"""
    region = _region_for(province_name)
    if not region:
        return {"region": None, "species": []}
    species = rank_species_by_site(
        TREE_SPECIES_BY_REGION.get(region, []), lst_mean, ndvi_mean)
    return {"region": region, "species": species}
