"""Unit tests ของบัญชีพันธุ์ไม้ (data/tree_species.json)
รัน: cd green-area-backend && pytest tests/test_species_data.py -v

เดิมบัญชีพันธุ์ไม้ถูกเขียนคงที่ในโค้ดโดยไม่มีแหล่งอ้างอิงรายชนิด — ตอบไม่ได้ว่า
"ข้อมูลต้นไม้มาจากไหน" · ตอนนี้ย้ายมาเป็นไฟล์ข้อมูลที่แนบผลตรวจจากฐานข้อมูลภายนอก
ไฟล์นี้คือด่านที่กันไม่ให้บัญชีหลุดมาตรฐานนั้นอีก ทุกชนิดต้อง

  1. เป็นไม้ยืนต้นจริง ตาม BGCI GlobalTreeSearch
  2. ใช้ชื่อวิทยาศาสตร์ที่ยอมรับ ตาม GBIF Backbone (EXACT + ACCEPTED)
  3. มีลิงก์อ้างอิงกลับไปยัง GBIF
  4. ถ้าคำบรรยายอ้างว่าเป็น "พันธุ์พื้นถิ่น" ต้องตรงกับ Kew WCVP จริง
  5. มีสัมประสิทธิ์ CO₂ ใน impact.py (ไม่ตกไปใช้ค่าเฉลี่ยกลางโดยไม่ตั้งใจ)

ทั้งหมดอ่านจากไฟล์ที่ commit ไว้ ไม่เรียกเน็ต — สร้างไฟล์ใหม่ด้วย
refresh_species_verification.py เมื่อต้องการอัปเดตผลตรวจ
"""
import pytest

from impact import TREE_CO2_PER_YEAR
from routers.recommend.species import (SPECIES_DATA_META, THAI_REGIONS,
                                       TREE_SPECIES_BY_REGION)

# คำที่ถือว่า "อ้างความเป็นพันธุ์พื้นถิ่นของไทย" — ต้องตรงกับ WCVP
NATIVE_CLAIM_KEYWORDS = ("พื้นถิ่น", "เฉพาะถิ่น", "พันธุ์เด่นของป่า")
CURATED_KEYS = ("name_th", "scientific", "purpose", "height_m", "traits", "reason")

ALL_SPECIES = [(region, sp)
               for region, lst in sorted(TREE_SPECIES_BY_REGION.items())
               for sp in lst]
SPECIES_IDS = ["%s/%s" % (r, sp["scientific"]) for r, sp in ALL_SPECIES]


def _claims_native(sp):
    text = (" ".join(sp.get("traits", [])) + " " + sp.get("purpose", "")
            + " " + sp.get("reason", ""))
    return any(k in text for k in NATIVE_CLAIM_KEYWORDS)


class TestDataFileShape:
    def test_covers_every_region_used_by_province_map(self):
        assert set(TREE_SPECIES_BY_REGION) == set(THAI_REGIONS)

    def test_every_region_has_species(self):
        for region, lst in TREE_SPECIES_BY_REGION.items():
            assert lst, "ภาค %s ไม่มีพันธุ์ไม้เลย" % region

    def test_no_duplicate_species_within_a_region(self):
        for region, lst in TREE_SPECIES_BY_REGION.items():
            names = [sp["scientific"] for sp in lst]
            assert len(names) == len(set(names)), "ภาค %s มีพันธุ์ซ้ำ" % region

    def test_metadata_records_when_and_from_where(self):
        assert SPECIES_DATA_META.get("generated_at")
        sources = SPECIES_DATA_META.get("sources") or {}
        for key in ("bgci", "wcvp", "gbif_backbone", "gbif_occurrence"):
            assert sources.get(key), "ไม่มีคำอ้างอิงของแหล่ง %s" % key


@pytest.mark.parametrize("region,sp", ALL_SPECIES, ids=SPECIES_IDS)
class TestEverySpecies:
    def test_has_all_curated_fields(self, region, sp):
        for key in CURATED_KEYS:
            assert sp.get(key), "%s ขาดฟิลด์ %s" % (sp.get("scientific"), key)

    def test_has_verification_block(self, region, sp):
        assert sp.get("verification"), "%s ไม่มีบล็อก verification" % sp["scientific"]

    def test_is_a_real_tree_per_bgci(self, region, sp):
        # ข้อ 1 — กันไม่ให้มีไม้พุ่ม/ไม้ล้มลุกหลุดเข้ามาในคำแนะนำ "ปลูกต้นไม้"
        assert sp["verification"]["bgci_is_tree"] is True

    def test_scientific_name_is_accepted(self, region, sp):
        # ข้อ 2 — ชื่อต้องตรงตัวและเป็นชื่อที่ยอมรับ ไม่ใช่ชื่อพ้องหรือสะกดผิด
        v = sp["verification"]
        assert v["gbif_match_type"] == "EXACT"
        assert v["gbif_name_status"] == "ACCEPTED"

    def test_has_traceable_source_link(self, region, sp):
        # ข้อ 3 — ต้องชี้กลับไปยังระเบียนต้นทางได้เสมอ
        assert str(sp["verification"]["gbif_url"] or "").startswith(
            "https://www.gbif.org/species/")

    def test_native_claim_matches_kew(self, region, sp):
        # ข้อ 4 — ห้ามเขียนว่า "พันธุ์พื้นถิ่น" ถ้าฐานข้อมูลสากลไม่ยืนยัน
        if not _claims_native(sp):
            return
        v = sp["verification"]
        assert v["wcvp_thailand"] == "NATIVE", (
            "%s เขียนว่าเป็นพันธุ์พื้นถิ่น แต่ WCVP ระบุ %s"
            % (sp["name_th"], v["wcvp_thailand"]))
        assert v["bgci_native_to_thailand"] is True

    def test_has_co2_coefficient(self, region, sp):
        # ข้อ 5 — ถ้าขาด ระบบจะเงียบ ๆ ใช้ค่าเฉลี่ยกลางแทนโดยไม่มีใครรู้
        assert sp["scientific"] in TREE_CO2_PER_YEAR

    def test_exotic_species_records_its_native_range(self, region, sp):
        # พันธุ์ที่ไม่ใช่ไม้ยืนต้นของไทยต้องบอกได้ว่าถิ่นกำเนิดอยู่ที่ไหน
        v = sp["verification"]
        if v["bgci_native_to_thailand"]:
            return
        assert v["bgci_native_range"], (
            "%s ไม่ใช่ไม้ยืนต้นของไทย แต่ไม่มีข้อมูลถิ่นกำเนิด" % sp["name_th"])
