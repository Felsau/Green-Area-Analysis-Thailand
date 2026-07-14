"""Tree planting impact coefficients — CO₂ sequestration + cooling + i-Tree
ecosystem services (air-pollution removal, stormwater interception, ฿ value).

References:
  - IPCC 2019 Refinement to 2006 GL, Vol.4 Ch.4 — tropical secondary forest
    above-ground biomass increment ~3.6 t C/ha/yr (≈ 22 kg CO₂/tree/yr
    at 400 trees/ha standard reforestation density)
  - Chave et al. 2014 (Global Change Biology) — pan-tropical allometric model
  - Bowler et al. 2010 (Landscape & Urban Planning) — meta-analysis of urban
    cooling: green sites cool ~1.0°C on average, up to 3°C in dense canopy
  - EPA 2023 — passenger vehicle average ≈ 4.6 t CO₂/year
  - US Forest Service i-Tree Eco — ecosystem-service quantification & valuation
    framework (air pollution removal, avoided stormwater runoff, ฿/year value)
  - Nowak D.J. et al. 2014 (Environmental Pollution 193:119–129) — air-pollution
    removal and value by urban trees across the United States
  - Thai Royal Forest Department species records + local growth studies

ค่าทุกตัวเป็น *steady-state* ของต้นไม้โตเต็มที่ (≈ 10–15 ปี) ในเขตร้อน
ใช้เป็น order-of-magnitude estimate — ขึ้นกับดิน ระยะปลูก ภูมิอากาศ ฤดูกาล
ไม่ใช่ค่าตายตัว
"""

# kg CO₂ sequestered per mature tree per year — species keyed by scientific name
TREE_CO2_PER_YEAR: dict[str, float] = {
    # ── ภาคกลาง ──────────────────────────────────────────────────────────────
    "Samanea saman":            28.0,  # จามจุรี — large canopy, urban shade
    "Pterocarpus indicus":      22.0,  # ประดู่บ้าน — medium-large hardwood
    "Mimusops elengi":          14.0,  # พิกุล — smaller urban
    "Lagerstroemia floribunda": 16.0,  # ตะแบกนา — medium ornamental
    "Delonix regia":            18.0,  # หางนกยูงฝรั่ง — medium-large
    # ── ภาคเหนือ ─────────────────────────────────────────────────────────────
    "Tectona grandis":          24.0,  # สัก — fast-growing economic forest
    "Alstonia scholaris":       20.0,  # พญาสัตบรรณ — fast-growing
    "Afzelia xylocarpa":        26.0,  # มะค่าโมง — long-lived hardwood
    "Syzygium cumini":          17.0,  # หว้า — fruit + shade
    "Chukrasia tabularis":      22.0,  # ยมหิน — hardwood
    # ── อีสาน ────────────────────────────────────────────────────────────────
    "Pterocarpus macrocarpus":  23.0,  # ประดู่ป่า — drought-tolerant native
    "Tamarindus indica":        15.0,  # มะขาม — fruit tree
    "Dalbergia cochinchinensis": 21.0, # พะยูง — endangered hardwood
    "Sindora siamensis":        18.0,  # มะค่าแต้ — native dry forest
    "Hopea odorata":            25.0,  # ตะเคียนทอง — long-lived shade
    # ── ตะวันออก ─────────────────────────────────────────────────────────────
    "Dipterocarpus alatus":     32.0,  # ยางนา — large emergent forest
    "Sandoricum koetjape":      16.0,  # กระท้อน — fruit + shade
    # ── ตะวันตก ──────────────────────────────────────────────────────────────
    "Acacia auriculiformis":    20.0,  # กระถินณรงค์ — N-fixer
    # ── ใต้ ──────────────────────────────────────────────────────────────────
    "Cotylelobium melanoxylon": 28.0,  # เคี่ยม — native S. Thailand
    "Garcinia mangostana":      12.0,  # มังคุด — fruit tree, smaller
    "Barringtonia acutangula":  15.0,  # จิกน้ำ — riparian medium
}

IMPACT_DEFAULTS = {
    "priority_threshold": 0.5,         # priority score > นี้ = "ควรปลูกจริง"
    "trees_per_ha":       400,         # standard reforestation density (FAO)
    "default_kg_co2":     22.0,        # IPCC Tier 1 fallback
    "delta_lst_c":        -1.5,        # °C cooling at mature canopy (Bowler 2010)
    "maturity_years":     10,          # ปีที่ canopy ให้ค่า cooling เต็มที่
    "car_co2_t_per_year": 4.6,         # ตัน — EPA 2023 passenger vehicle
}

# Uncertainty model — annual_co2_tonnes เดิมคือ "ศักยภาพเต็ม" (สมมติรอด 100% +
# ใช้ coefficient กลาง) · ความจริงต้นกล้าไม่รอดทุกต้น และการกักเก็บ/ต้นแปรผันตาม
# ดิน/สภาพ/สายพันธุ์ → รายงานเป็น "ช่วง" ที่สมจริงคู่กับศักยภาพ (ไม่แตะ field เดิม)
#   survival: 65–90% (FAO/restoration survival-to-maturity, กลาง 80%)
#   per-tree sequestration variance: ±25%
SURVIVAL_RATE = 0.80
SURVIVAL_LOW = 0.65
SURVIVAL_HIGH = 0.90
SEQUESTRATION_VARIANCE = 0.25

# ── i-Tree ecosystem services (FR-23/24/25) — additive to CO₂ + cooling ───────
# ค่าเฉลี่ยต่อ "ต้นโตเต็มที่" ต่อปี ในบริบทเมืองเขตร้อน — order-of-magnitude ตาม
# ระเบียบวิธี i-Tree Eco (US Forest Service) + Nowak et al. 2014 · เป็นค่ากลาง
# ปรับได้ตาม canopy/LAI/ความเข้มมลพิษพื้นที่ ไม่ใช่ค่าตายตัว · additive: เติมบริการ
# นิเวศใหม่เข้ากับ CO₂+cooling เดิม ไม่แตะ/ลด field ใด

# 1) การดูดซับมลพิษอากาศ (kg/ต้น/ปี) — dry deposition บนผิวใบ (Nowak et al. 2014)
AIR_POLLUTANT_KG_PER_TREE = {
    "pm25": 0.020,   # PM2.5 — อนุภาคเล็ก ผลกระทบสุขภาพสูงสุด
    "o3":   0.050,   # O₃ — โอโซนระดับผิวดิน (ดูดซับมากสุดในกลุ่ม)
    "no2":  0.018,   # NO₂ — จากการจราจร
}

# 2) ดักน้ำฝน/ลด runoff (m³/ต้น/ปี) — interception + ลดการไหลบ่า (i-Tree Hydro)
#    ต้นเมืองโตเต็มที่ดัก ~2–4 m³/ปี · ใช้ค่ากลางเชิงอนุรักษ์
STORMWATER_M3_PER_TREE = 2.5

# 3) การตีมูลค่าเป็นเงิน (บาท) — externality/damage & avoided-cost
#    หมายเหตุ: เป็น "ค่ากลางเชิงนโยบาย" ไม่ใช่ราคาตลาดตายตัว — เลือกค่าเชิงอนุรักษ์
#    CO₂: อยู่ระหว่างราคาตลาด T-VER ไทย (~฿100–300/t) กับ social cost of carbon
#         (~$50–185/t) → ใช้ ~$43/t · PM2.5 ค่าความเสียหายสุขภาพสูงสุดต่อ kg
CARBON_VALUE_THB_PER_TONNE = 1500.0
VALUATION_THB = {
    "pm25_per_kg":       3600.0,   # PM2.5 — damage cost สุขภาพ (เชิงอนุรักษ์)
    "o3_per_kg":         220.0,    # O₃
    "no2_per_kg":        180.0,    # NO₂
    "stormwater_per_m3": 20.0,     # ต้นทุนบำบัด/จัดการน้ำที่หลีกเลี่ยงได้
}

CITATIONS = [
    "IPCC 2019 Refinement to 2006 Guidelines, Vol.4 Ch.4 (tropical biomass)",
    "Bowler D.E. et al. 2010, Landscape & Urban Planning (urban cooling meta-analysis)",
    "Chave J. et al. 2014, Global Change Biology (pan-tropical allometry)",
    "U.S. EPA 2023 (passenger vehicle CO₂ baseline)",
    "US Forest Service i-Tree Eco (ecosystem-service valuation framework)",
    "Nowak D.J. et al. 2014, Environmental Pollution (air-pollution removal by urban trees)",
]


def estimate_impact(plantable_area_m2: float, species_list: list[dict]) -> dict:
    """คำนวณ impact ของการปลูกในพื้นที่ที่กำหนด + species mix ที่แนะนำ.

    Args:
        plantable_area_m2: พื้นที่ปลูกได้จริง (m²) — มาจาก priority > threshold
        species_list: list ของ species dict (มี key 'scientific', 'name_th')
                      ปกติคือ recommended_species["species"]

    Returns:
        dict ที่มี trees_total, annual_co2_tonnes, equivalent_cars_off_road,
        expected_delta_lst_c, species_breakdown (per-species count + CO₂)
    """
    plantable_ha = plantable_area_m2 / 10_000
    plantable_km2 = plantable_area_m2 / 1_000_000
    trees_total = int(plantable_ha * IMPACT_DEFAULTS["trees_per_ha"])

    species_breakdown = []
    if species_list and trees_total > 0:
        per_species = trees_total // len(species_list)
        # เศษที่เหลือ (modulo) — โยนเพิ่มให้ species แรก
        remainder = trees_total - per_species * len(species_list)
        co2_total_kg = 0.0
        for i, sp in enumerate(species_list):
            count = per_species + (remainder if i == 0 else 0)
            kg_per_tree = TREE_CO2_PER_YEAR.get(
                sp.get("scientific", ""), IMPACT_DEFAULTS["default_kg_co2"])
            sp_co2 = count * kg_per_tree
            co2_total_kg += sp_co2
            species_breakdown.append({
                "name_th":         sp.get("name_th", ""),
                "scientific":      sp.get("scientific", ""),
                "trees":           count,
                "kg_co2_per_tree": kg_per_tree,
                "annual_co2_kg":   round(sp_co2, 0),
            })
    else:
        # ไม่มี species mix → ใช้ค่าเฉลี่ย IPCC
        co2_total_kg = trees_total * IMPACT_DEFAULTS["default_kg_co2"]

    annual_co2_tonnes = co2_total_kg / 1000
    car_co2 = IMPACT_DEFAULTS["car_co2_t_per_year"]
    equivalent_cars = annual_co2_tonnes / car_co2

    # ช่วงที่สมจริง = ศักยภาพเต็ม × อัตรารอด × ความแปรปรวนการกักเก็บต่อต้น
    # central (expected) ใช้ survival กลาง · low/high รวม survival + variance สองทาง
    co2_expected = annual_co2_tonnes * SURVIVAL_RATE
    co2_low = annual_co2_tonnes * SURVIVAL_LOW * (1 - SEQUESTRATION_VARIANCE)
    co2_high = annual_co2_tonnes * SURVIVAL_HIGH * (1 + SEQUESTRATION_VARIANCE)

    # ── i-Tree ecosystem services (additive: air pollution + stormwater + ฿) ──
    # คิดจาก trees_total (ศักยภาพเต็ม) ให้สอดคล้องกับ annual_co2_tonnes · มี
    # *_expected ที่คูณอัตรารอดไว้คู่กันเช่นเดียวกับ CO₂
    air_removal_kg = {p: trees_total * kg
                      for p, kg in AIR_POLLUTANT_KG_PER_TREE.items()}
    air_total_kg = sum(air_removal_kg.values())
    stormwater_m3 = trees_total * STORMWATER_M3_PER_TREE

    value_co2 = annual_co2_tonnes * CARBON_VALUE_THB_PER_TONNE
    value_pm25 = air_removal_kg["pm25"] * VALUATION_THB["pm25_per_kg"]
    value_o3 = air_removal_kg["o3"] * VALUATION_THB["o3_per_kg"]
    value_no2 = air_removal_kg["no2"] * VALUATION_THB["no2_per_kg"]
    value_air = value_pm25 + value_o3 + value_no2
    value_stormwater = stormwater_m3 * VALUATION_THB["stormwater_per_m3"]
    value_total = value_co2 + value_air + value_stormwater

    ecosystem_services = {
        "air_pollution_removal_kg": {
            "pm25":  round(air_removal_kg["pm25"], 1),
            "o3":    round(air_removal_kg["o3"], 1),
            "no2":   round(air_removal_kg["no2"], 1),
            "total": round(air_total_kg, 1),
        },
        "stormwater_runoff_m3": round(stormwater_m3, 0),
        "annual_value_thb": {
            "co2":           round(value_co2, 0),
            "air_pollution": round(value_air, 0),
            "stormwater":    round(value_stormwater, 0),
            "total":         round(value_total, 0),
        },
        # มูลค่ารวมที่คาดจริง (คูณอัตรารอด) — คู่กับ annual_co2_tonnes_expected
        "annual_value_thb_expected": round(value_total * SURVIVAL_RATE, 0),
    }

    return {
        "plantable_area_km2":       round(plantable_km2, 2),
        "plantable_area_ha":        round(plantable_ha, 1),
        "trees_total":              trees_total,
        "annual_co2_tonnes":        round(annual_co2_tonnes, 1),
        "annual_co2_kg":            round(co2_total_kg, 0),
        "equivalent_cars_off_road": round(equivalent_cars, 1),
        # ── Uncertainty range (สมจริง รวมอัตรารอด + ความแปรปรวน) ──
        "annual_co2_tonnes_expected": round(co2_expected, 1),
        "annual_co2_tonnes_low":      round(co2_low, 1),
        "annual_co2_tonnes_high":     round(co2_high, 1),
        "equivalent_cars_expected":   round(co2_expected / car_co2, 1),
        "survival_rate":              SURVIVAL_RATE,
        "expected_delta_lst_c":     IMPACT_DEFAULTS["delta_lst_c"],
        "maturity_years":           IMPACT_DEFAULTS["maturity_years"],
        # ── i-Tree ecosystem services (FR-23/24/25) — additive ──
        "ecosystem_services":       ecosystem_services,
        "species_breakdown":        species_breakdown,
        "methodology": {
            "priority_threshold": IMPACT_DEFAULTS["priority_threshold"],
            "trees_per_ha":       IMPACT_DEFAULTS["trees_per_ha"],
            "survival_rate":      SURVIVAL_RATE,
            "survival_range":     [SURVIVAL_LOW, SURVIVAL_HIGH],
            "sequestration_variance": SEQUESTRATION_VARIANCE,
            "ecosystem_valuation": {
                "air_pollutant_kg_per_tree": AIR_POLLUTANT_KG_PER_TREE,
                "stormwater_m3_per_tree":    STORMWATER_M3_PER_TREE,
                "carbon_value_thb_per_tonne": CARBON_VALUE_THB_PER_TONNE,
                "valuation_thb":             VALUATION_THB,
                "note": "ค่ากลางเชิงนโยบาย (order-of-magnitude) ตามระเบียบวิธี "
                        "i-Tree Eco — ปรับได้ ไม่ใช่ราคาตลาดตายตัว",
            },
            "sources":            CITATIONS,
        },
    }
