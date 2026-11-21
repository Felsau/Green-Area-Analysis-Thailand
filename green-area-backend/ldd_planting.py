"""กติกาการใช้รหัสการใช้ที่ดิน LDD ตัดสินจุดแนะนำปลูกต้นไม้ (pure ทดสอบได้โดยไม่แตะ GEE).

ระบบแนะนำเลือกจุดจากภาพดาวเทียม (ESA WorldCover + ความชัน) ซึ่งแยกได้แค่ "อาคาร/หญ้า/
ต้นไม้" จึงเคยแนะนำจุดในสนามบินดอนเมือง (ผลตรวจ R7 ข้อ A3) · ข้อมูลกรมพัฒนาที่ดินบอก
การใช้ที่ดินจริงเป็นรหัส (LU_CODE เช่น U401 สนามบิน) จึงใช้ตัดจุดที่ดาวเทียมมองไม่ออก

ผลของแต่ละรหัสมี 3 แบบ:
    exclude  ไม่แนะนำให้ปลูก ตัดจุดทิ้ง
    prefer   ที่ว่าง/ที่ร้าง เหมาะเป็นพื้นที่ปลูก (ตอนนี้แค่ติดป้าย ยังไม่ขยับลำดับคะแนน)
    neutral  ที่เหลือทั้งหมด รวมจุดที่ไม่มีแปลง LDD รองรับ

PROVISIONAL: ตารางด้านล่างเป็นค่าชั่วคราวที่ทีมตั้งเอง รอความเห็นผู้ชำนาญการ
(นัด 23 พ.ย. 2569) ก่อนใช้อ้างอิงในเล่ม · แก้ที่นี่ที่เดียวแล้ว bump
RECOMMEND_CACHE_VERSION (dependencies.py) ให้ผลที่ cache ไว้คำนวณใหม่
"""

EXCLUDE = "exclude"
PREFER = "prefer"
NEUTRAL = "neutral"

# รหัสที่ตัดทิ้ง จับแบบ prefix (เช่น "U4" = ทุกรหัส U4xx) · ประเภทหลัก LDD:
# U ชุมชนและสิ่งปลูกสร้าง · A เกษตรกรรม · F ป่าไม้ · W แหล่งน้ำ · M เบ็ดเตล็ด
EXCLUDE_PREFIXES: tuple[str, ...] = (
    "U1",    # ตัวเมืองและย่านการค้า
    "U4",    # คมนาคม: สนามบิน สถานีรถไฟ สถานีขนส่ง ท่าเรือ ถนน ทางรถไฟ
    "U501",  # นิคมอุตสาหกรรม
    "U502",  # โรงงานอุตสาหกรรม
    "W",     # แหล่งน้ำ
    "A9",    # สถานที่เพาะเลี้ยงสัตว์น้ำ (บ่อปลา บ่อกุ้ง)
    "F",     # ป่าไม้ที่มีอยู่แล้ว
)

# ที่ว่างหรือที่ถูกทิ้งร้าง จับแบบรหัสเต็มเท่านั้น
PREFER_CODES: frozenset[str] = frozenset({
    "A100",  # นาร้าง
    "A300",  # ไม้ยืนต้นร้าง/เสื่อมโทรม
    "A400",  # ไม้ผลร้าง/เสื่อมโทรม
    "U200",  # หมู่บ้าน/ที่ดินจัดสรรร้าง
    "U500",  # พื้นที่อุตสาหกรรมร้าง
    "U700",  # สนามกอล์ฟร้าง
    "M101",  # ทุ่งหญ้าธรรมชาติ
    "M102",  # ทุ่งหญ้าสลับไม้พุ่ม/ไม้ละเมาะ
    "M300",  # เหมืองเก่า บ่อขุดเก่า
    "M405",  # พื้นที่ถม
})


def split_code(code: str | None) -> list[str]:
    """แยกรหัสผสม เช่น 'A405/A411' → ['A405', 'A411'] · ค่าว่าง/None → []."""
    if not code:
        return []
    return [part.strip().upper() for part in str(code).split("/") if part.strip()]


def _classify_part(part: str) -> str:
    if part.startswith(EXCLUDE_PREFIXES):
        return EXCLUDE
    if part in PREFER_CODES:
        return PREFER
    return NEUTRAL


def classify_code(code: str | None) -> str:
    """ตัดสินรหัส LU_CODE หนึ่งแปลง → exclude / prefer / neutral.

    รหัสผสม (31–59% ของชนิดรหัส แต่แค่ราว 0.1–11% ของจำนวนแปลง วัด 25 จังหวัดภาคกลาง)
    ใช้กติกาแบบระวังไว้ก่อน: มีส่วนใดเป็น
    exclude → ตัดทั้งแปลง · ไม่มี exclude แต่มี prefer → prefer · นอกนั้น neutral
    (PROVISIONAL รอผู้ชำนาญการยืนยันเช่นเดียวกับตาราง) · ไม่มีรหัส → neutral
    """
    results = {_classify_part(p) for p in split_code(code)}
    if EXCLUDE in results:
        return EXCLUDE
    if PREFER in results:
        return PREFER
    return NEUTRAL


def apply_ldd_codes(candidates: list[dict], codes_by_idx: dict[int, dict],
                    edition_year: int) -> tuple[list[dict], int]:
    """ติดป้าย LDD ให้ candidate ทุกจุดแล้วตัดจุด exclude ทิ้ง → (จุดที่เหลือ, จำนวนที่ตัด).

    codes_by_idx = {index ใน candidates: {'code', 'name_th'}} จาก ldd.ldd_codes_at_points ·
    index ที่ไม่มีใน dict = จุดไม่ตกในแปลงใด (ช่องว่างระหว่างแปลง/นอกเขตข้อมูล) →
    neutral ไม่ตัด เพราะ "ไม่รู้" ไม่ใช่ "ห้าม" · ทุกจุดที่เหลือได้ key 'ldd' เสมอ
    (code None ถ้าไม่มีแปลง) เพื่อให้ endpoint แยกได้ว่าการตรวจ LDD สำเร็จครบทุกจุด
    ลำดับเดิม (เรียงคะแนน) คงไว้ — ใช้ก่อน _space_out เหมือน _drop_non_plantable
    """
    kept: list[dict] = []
    dropped = 0
    for i, c in enumerate(candidates):
        hit = codes_by_idx.get(i) or {}
        code = hit.get("code")
        rule = classify_code(code)
        if rule == EXCLUDE:
            dropped += 1
            continue
        kept.append({**c, "ldd": {"code": code, "name_th": hit.get("name_th"),
                                  "rule": rule, "edition_year": edition_year}})
    return kept, dropped
