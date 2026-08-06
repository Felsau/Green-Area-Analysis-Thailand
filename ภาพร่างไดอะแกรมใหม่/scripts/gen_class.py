#!/usr/bin/env python3
"""Class Diagram — ระบบแดชบอร์ดพื้นที่สีเขียวและเกาะความร้อนในเขตเมือง

29 คลาส · ชั้น Boundary → Control → Service → Entity

⚠️ ก่อนแก้ไฟล์นี้ ให้เปิด green-area-backend/migrations/ + routers/ อ่านของจริงเสมอ
   (กฎเดียวกับ gen_er.py) — เคยมีรอบที่ไดอะแกรมโชว์ `SavedArea.owner_token` ซึ่งถูกตัดไป
   ตั้งแต่ migration 019 และเมธอด `calculateUHIIntensity()` ซึ่งไม่มีอยู่ในระบบเลย

── ทำไม Entity ถึงไม่มีช่อง attribute ──────────────────────────────────────────
ตารางในสคีมามี 15 ตาราง (+ auth.users) ถ้าใส่คอลัมน์ครบทุกกล่องเหมือนเดิม ภาพจะต้อง
กว้าง 6 คอลัมน์ → ย่อลงหน้ากระดาษ 14.65 ซม. แล้วตัวอักษรเหลือ ~4.2pt อ่านไม่ออก
UML อนุญาตให้ซ่อน attribute compartment ได้ จึงแสดง Entity เป็นชื่อคลาสอย่างเดียว
รายละเอียดคอลัมน์อยู่ใน ER Diagram + ตาราง Data Dictionary ของบทที่ 3 อยู่แล้ว
ไม่ต้องวาดซ้ำ · สิ่งที่ภาพนี้ต้องตอบคือ "ชั้น Service เขียน/อ่าน entity ตัวไหน"
ซึ่งเส้น «use» ทำหน้าที่นั้นครบ

── กฎการตั้งชื่อ/ชนิดข้อมูลในภาพนี้ ──────────────────────────────────────────
ชั้น Boundary/Control/Service ใช้สัญกรณ์ UML ล้วน: ชนิดข้อมูลเป็น UML DataType
(Boolean/Integer/Real/String · UUID เป็น DataType ที่นิยามเอง) และพารามิเตอร์เป็น
camelCase ทั้งหมด · **ห้ามใช้ชนิดของ PostgreSQL (int4/float8/numeric/text) หรือชื่อ
คอลัมน์แบบ snake_case ในภาพนี้** — ชื่อและชนิดจริงของคอลัมน์อยู่ใน ER Diagram
กับ Data Dictionary §3.3 ซึ่งเป็นคนละระดับของแบบจำลอง

รัน: python "ภาพร่างไดอะแกรมใหม่/scripts/gen_class.py"
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from diagram import Canvas, BLACK, WHITE          # noqa: E402

# ── นิยามคลาส: ชื่อ -> (stereotype, attributes, methods) ───────────────────────
# Entity = ชื่ออย่างเดียว (attrs/methods ว่าง) → กล่องเตี้ยแค่ส่วนหัว
CLS = {
 'MainDashboardView': ('Boundary',
   ['- isLoaded : Boolean', '- themeMode : String'],
   ['+ renderOverview()', '+ updateCharts()']),
 'MapViewComponent': ('Boundary',
   ['- mapZoom : Integer', '- activeLayer : String'],
   ['+ initializeMap()', '+ switchLayer(layerName)', '+ drawGeometry()']),
 # แบ่งหน้าที่ส่งออกรายงานเป็นสองฝั่งให้ชื่อบอกเองว่าใครทำอะไร:
 #   AnalysisReportView.exportReport()      = ปุ่มบนหน้าจอ + สั่งบันทึกไฟล์ให้ผู้ใช้
 #                                            (ExportBar — src/components/ui/ExportBar.js)
 #   DashboardController.buildReportDocument() = ประกอบเนื้อรายงานเป็นเอกสารก่อนส่งออก
 #                                            (utils/reportPdf/build*Report() + fetchStatsData)
 # เดิมชื่อ exportReportData() ซึ่งอ่านแล้วแยกไม่ออกว่าต่างจาก exportReport() ตรงไหน
 'AnalysisReportView': ('Boundary',
   ['- reportType : String', '- isDescending : Boolean'],
   ['+ displayReport()', '+ sortData(criteria)', '+ exportReport()']),
 'CustomAreaWorkspace': ('Boundary',
   ['- isDrawingActive : Boolean', '- currentShapeArea : Real'],
   ['+ openWorkspace()', '+ clearCanvas()', '+ triggerAnalysis()']),
 # AuthView ไม่ใช่ LoginView — ของจริงคือ 4 หน้าจอหลัง AuthGate: SignInScreen /
 # SignUpScreen / ForgotPasswordScreen / ResetPasswordScreen (src/components/auth/)
 # ชื่อ "LoginView" ครอบทั้งสมัครสมาชิกและรีเซ็ตรหัสผ่านไม่ได้
 'AuthView': ('Boundary',
   ['- email : String', '- isSubmitting : Boolean'],
   ['+ submitSignIn()', '+ submitSignUp()', '+ submitForgotPassword()',
    '+ submitNewPassword()']),
 'ProfileView': ('Boundary',
   ['- displayName : String', '- organization : String'],
   ['+ showProfile()', '+ submitProfileUpdate()', '+ submitPasswordChange()',
    '+ submitEmailChange()', '+ confirmDeleteAccount()']),

 'DashboardController': ('Control',
   ['- currentYear : Integer', '- selectedProvince : String', '- selectedDistrict : String'],
   ['+ getOverviewStats()', '+ changeFilter(province, district, year)',
    '+ buildReportDocument()']),
 # year รับมาจาก request จริง (SavedAreaCreate.year — routers/saved.py:42) ส่วน
 # area_km2 ไม่ใช่พารามิเตอร์ เพราะคำนวณเองด้วย validate_drawn_polygon() (saved.py:70)
 # และ province ถูก validate ทิ้งเป็น NULL ถ้าไม่รู้จัก (saved.py:73)
 'SavedAreaManager': ('Control',
   ['- currentUserId : UUID'],
   ['+ createSavedArea(label, geometry, province, year)',
    '+ getSavedAreas(userId : UUID)',
    '+ deleteSavedArea(id)', '+ validateOwner(id, userId : UUID)',
    '+ generateCustomAnalysis(id)']),
 # เมธอดที่แก้ "ข้อมูลยืนยันตัวตน" (รหัสผ่าน/อีเมล/ลบบัญชี) รวมไว้ที่นี่ทั้งหมด —
 # ของจริงอยู่ในโมดูลเดียวกันหมดคือ src/hooks/useAuth.js ที่เรียก Supabase Auth
 # (GoTrue) ตรง · ProfileController เหลือหน้าที่เดียวคือแถวในตาราง profiles
 'AuthController': ('Control',
   ['- sessionToken : String'],
   ['+ authenticateUser(email, password)', '+ registerUser(email, password, profile)',
    '+ requestPasswordReset(email)', '+ resetPassword(newPassword)',
    '+ changePassword(currentPassword, newPassword)', '+ changeEmail(newEmail)',
    '+ deleteAccount()', '+ signOut()']),
 'ProfileController': ('Control',
   ['- currentUserId : UUID'],
   ['+ getProfile(userId)', '+ updateProfile(displayName, organization)']),

 # ⚠️ เดิมมี attribute `tileServerUrl : text` ซึ่ง **ไม่มีอยู่จริงในระบบเลย** — ไม่มี
 # env var ไม่มี config ตัว URL ของ tile มาจาก GEE ต่อ request ด้วย
 # getMapId(vis)['tile_fetcher'].url_format แล้ว cache ในหน่วยความจำ 30 นาที
 # (routers/maps/tiles.py:97,113) · และ service ไม่ได้ "render" อะไร มันคืน URL
 # ให้ MapViewComponent เอาไปวาดเอง จึงเป็น getTileUrl() ไม่ใช่ renderMapTile()
 'GISDataService': ('Service',
   ['- cacheStatus : Boolean'],
   ['+ fetchNDVIData(province, district, year)', '+ fetchLSTData(province, district, year)',
    '+ fetchProvinceList()', '+ fetchDistrictList(province)',
    '+ getTileUrl(kind, province, year)']),
 # analyzeCoolingEffect แทน calculateUHIIntensity เดิมที่ไม่มีอยู่จริง — ของจริงคือ
 # GET /analysis/cooling/{province} (routers/maps/analysis/cooling.py) ที่ fit เส้นถดถอย
 # LST ต่อ NDVI ระดับอำเภอจาก district_ndvi_annual + district_lst_annual
 # analyzeUrbanGreenShare ต้องรับ district ด้วย — endpoint จริงคือ
 # GET /analysis/urban-subset/{province}?district_name=… (urban.py:127) ที่รับอำเภอเป็น
 # optional และใช้ cache key ("urban", province, district, year) ตรงกับ UNIQUE
 # (province, district, year) ของตาราง urban_ndvi_annual · ถ้าเขียนแค่ (province, year)
 # จะอธิบายไม่ได้ว่าแถวระดับอำเภอในตารางเกิดจากอะไร
 # ส่วน analyzeCoolingEffect(province, year) ถูกแล้ว — GET /analysis/cooling/{province}
 # รับแค่จังหวัดกับปี แล้ว *อ่าน* district_ndvi_annual + district_lst_annual ทุกอำเภอ
 # ในจังหวัดนั้นมา fit เส้นถดถอย (cooling.py:34) อำเภอเป็นหน่วยของข้อมูล ไม่ใช่พารามิเตอร์
 'UrbanAnalysisService': ('Service',
   ['- whoStandardThreshold : Real'],
   ['+ analyzeUrbanGreenShare(province, district, year)',
    '+ evaluateWHOCriteria(greenAreaM2PerPerson)', '+ analyzeCoolingEffect(province, year)']),
 # generatePlantingPoints ต้องรับ year ด้วย — ทั้ง GET /recommend/{province} และ
 # /recommend/{province}/districts/{district} รับ year (endpoints.py:255,265) และตาราง
 # planting_recommendations มี UNIQUE (province, district, year)
 # ⚠️ ชื่อ/พารามิเตอร์ของเมธอดในคลาสนี้ปรากฏใน Sequence Diagram ด้วย (seq_specs.py) —
 # แก้ที่นี่แล้วต้องแก้ seq_specs.py + วาด SD ใหม่ + แก้ข้อความ §3.6 พร้อมกันเสมอ
 'PlantingAdvisor': ('Service',
   ['- recommendationEngineVersion : String'],
   ['+ generatePlantingPoints(province, district, year)',
    '+ predictCoolingImpact(geometry)']),
}

# Entity — 1 คลาสต่อ 1 ตารางในสคีมา (ดู gen_er.py) · ชื่อเอกพจน์แบบ PascalCase
ENTITIES = [
    ('Province', 'provinces'), ('District', 'districts'),
    ('ProvincePopulation', 'province_population'),
    ('NDVIAnnual', 'ndvi_annual'), ('NDVIMonthly', 'ndvi_monthly'),
    ('DistrictNDVIAnnual', 'district_ndvi_annual'),
    ('DistrictNDVIMonthly', 'district_ndvi_monthly'),
    ('ProvinceLSTAnnual', 'province_lst_annual'),
    ('ProvinceLSTMonthly', 'province_lst_monthly'),
    ('DistrictLSTAnnual', 'district_lst_annual'),
    ('DistrictLSTMonthly', 'district_lst_monthly'),
    ('UrbanNDVIAnnual', 'urban_ndvi_annual'),
    ('PlantingRecommendation', 'planting_recommendations'),
    ('SavedArea', 'saved_areas'), ('Profile', 'profiles'),
    # auth.users จัดการโดย Supabase Auth (GoTrue) ไม่ได้อยู่ใน migrations ของโปรเจกต์
    # วางไว้ท้ายสุดของคอลัมน์เพื่อให้ note อธิบายที่มาห้อยใต้กล่องได้โดยไม่ตัดผ่านเส้นอื่น
    ('AuthUser', 'auth.users'),
]
# «Entity, external» ไม่ใช่การซ้อน stereotype ที่ UML รองรับ — ใช้ «Entity» เหมือนตัวอื่น
# แล้วบอกที่มาด้วย note แทน (NOTE ด้านล่าง)
for _n, _t in ENTITIES:
    CLS[_n] = ('Entity', [], [])

COLS = [
    ['MainDashboardView', 'MapViewComponent', 'AnalysisReportView',
     'CustomAreaWorkspace', 'AuthView', 'ProfileView'],
    ['DashboardController', 'SavedAreaManager', 'AuthController', 'ProfileController'],
    ['GISDataService', 'UrbanAnalysisService', 'PlantingAdvisor'],
    [n for n, _ in ENTITIES],
]
BWS = [306, 306, 306, 246]          # Entity แคบกว่าเพราะไม่มีช่อง attribute

# ── เส้นข้ามคอลัมน์: (จาก, ไป, ชนิด, เลน, ป้าย, mult ต้นทาง, mult ปลายทาง, ฝั่งเลน)
#   ชนิด  assoc = เส้นทึบ · dep = เส้นประหัวลูกศรเปิด («use»)
#   ฝั่งเลน 'dst' = สันแนวตั้งชิดคอลัมน์ปลายทาง (เส้นยาวอยู่ที่ระดับ *ต้นทาง* จึงอ่านออก
#           ว่าออกมาจากกล่องไหน — เดิมวางชิดต้นทางทำให้เส้นยาวไปโผล่ที่ระดับปลายทาง
#           แล้วดูเหมือนงอกออกจากกล่องอื่นที่บังเอิญอยู่แถวนั้น)
#           'src' = ชิดต้นทาง ใช้กับเส้นที่ข้ามคอลัมน์ (ต้องให้เส้นยาวลอดใต้คอลัมน์กลาง)
LINKS = [
    ('MainDashboardView', 'DashboardController', 'assoc', 0, 'ควบคุม', '1', '1', 'dst'),
    ('MapViewComponent', 'DashboardController', 'assoc', 1, 'ขอชั้นข้อมูล', '1', '1', 'dst'),
    ('AnalysisReportView', 'DashboardController', 'assoc', 2, 'ขอผลวิเคราะห์', '1', '1', 'dst'),
    ('CustomAreaWorkspace', 'SavedAreaManager', 'assoc', 3, 'ส่งขอบเขต', '1', '1', 'dst'),
    ('AuthView', 'AuthController', 'assoc', 4, 'ยืนยันตัวตน', '1', '1', 'dst'),
    ('ProfileView', 'ProfileController', 'assoc', 5, 'จัดการโปรไฟล์', '1', '1', 'dst'),
    # AccountModal เรียกทั้ง auth.updateProfile และ auth.changePassword/changeEmail/
    # deleteAccount → หน้าจอเดียวผูกกับสอง Control ตามหน้าที่ที่แยกกัน
    ('ProfileView', 'AuthController', 'assoc', 6, 'แก้รหัสผ่าน/อีเมล', '1', '1', 'dst'),

    ('DashboardController', 'GISDataService', 'dep', 0, '«use»', '', '', 'dst'),
    ('DashboardController', 'UrbanAnalysisService', 'dep', 1, '«use»', '', '', 'dst'),
    ('SavedAreaManager', 'GISDataService', 'dep', 2, '«use»', '', '', 'dst'),
    ('SavedAreaManager', 'PlantingAdvisor', 'dep', 3, '«use»', '', '', 'dst'),

    # Control → Entity ข้ามคอลัมน์ Service — วางปลายทางไว้ท้ายคอลัมน์ Entity เพื่อให้
    # เส้นแนวนอนลอดใต้กล่อง Service ได้โดยไม่ทับอะไร
    # ⚠️ ต้องเป็น «use» เส้นประเหมือน Control → Service และ Service → Entity — เดิมวาด
    # เป็นเส้นทึบมี multiplicity ทำให้ภาพเดียวกันใช้สองสัญกรณ์กับความสัมพันธ์ชนิดเดียวกัน
    ('SavedAreaManager', 'SavedArea', 'dep', 0, '«use»', '', '', 'src'),
    ('AuthController', 'AuthUser', 'dep', 1, '«use»', '', '', 'src'),
    ('ProfileController', 'Profile', 'dep', 2, '«use»', '', '', 'src'),
]

# ── เส้นแบบต้นไม้: ต้นทางเดียวแตกไปหลายปลายทาง (สันเดียว + กิ่ง) ──────────────
# ใช้กับ Service → Entity ที่ตัวเดียวอ่าน/เขียนหลายตาราง — ถ้าลากเส้นเดี่ยวทีละคู่
# จะได้สันแนวตั้งขนาน 16 เส้นจนอ่านไม่ออกว่าเส้นไหนไปไหน
#   (ต้นทาง, [ปลายทาง...], ชนิด, ระยะสันจากขอบขวาคอลัมน์ Service, ป้าย)
TREES = [
    # ProvincePopulation อยู่กับ GISDataService ไม่ใช่ UrbanAnalysisService —
    # ตารางนี้ถูกอ่านที่เดียวคือ dependencies.py::get_population ซึ่งถูกเรียกจาก
    # routers/ndvi/endpoints.py (คำนวณ green_area_m2_per_person) · ส่วน population_urban
    # ของ urban.py มาจาก WorldPop raster บน GEE ไม่ได้แตะตารางนี้เลย
    ('GISDataService',
     ['Province', 'District', 'ProvincePopulation', 'NDVIAnnual', 'NDVIMonthly',
      'DistrictNDVIAnnual', 'DistrictNDVIMonthly', 'ProvinceLSTAnnual',
      'ProvinceLSTMonthly', 'DistrictLSTAnnual', 'DistrictLSTMonthly'], 'dep', 106, '«use»'),
    # analyzeCoolingEffect อ่านคู่ NDVI/LST ระดับอำเภอ (cooling.py) ·
    # analyzeUrbanGreenShare อ่าน/เขียน urban_ndvi_annual (urban.py)
    ('UrbanAnalysisService',
     ['DistrictNDVIAnnual', 'DistrictLSTAnnual', 'UrbanNDVIAnnual'], 'dep', 70, '«use»'),
    # _site_metrics() อ่าน ndvi/lst ระดับจังหวัดมาจัดอันดับพันธุ์ไม้ แล้วเขียนผลลง
    # planting_recommendations (routers/recommend/endpoints.py)
    ('PlantingAdvisor', ['NDVIAnnual', 'ProvinceLSTAnnual', 'PlantingRecommendation'],
     'dep', 34, '«use»'),
]

# ── Composition: MainDashboardView ประกอบด้วยแผงย่อย 3 ตัว ───────────────────
# เดิมวาดเป็นเส้นตรงลงมาในคอลัมน์เดียวกัน แล้วกล่อง MapViewComponent (ซึ่งวาดทีหลัง)
# ทับเส้นที่ลอดผ่านตรงกลาง ทำให้ *ดู* เป็นลูกโซ่ Main ◆— Map —— Report ทั้งที่โมเดล
# ถูกอยู่แล้ว · เปลี่ยนมาเดินสันทางซ้ายนอกกล่องแทน จึงไม่มีอะไรมาทับ
COMPOSITION = ('MainDashboardView',
               ['MapViewComponent', 'AnalysisReportView', 'CustomAreaWorkspace'],
               'ประกอบด้วย')

# ── ความสัมพันธ์ระหว่าง Entity (วาดทางขวาของคอลัมน์สุดท้าย) ──────────────────
# ตรงกับ FK จริง: districts.province → provinces · profiles.id → auth.users (1:1)
# · saved_areas.user_id → auth.users (many-to-one)  ← ไม่ใช่ profiles ตามที่เคยวาดผิด
#
# ⚠️ ทำไมต้องมี "เลน" กับ "ตำแหน่งป้าย" — รีวิวจากภายนอก **4 รอบติดกัน** อ่านภาพนี้ผิด
# เป็น "SavedArea 0..* — 1 Profile" ทั้งที่โมเดลถูกมาตั้งแต่รอบ 11 · สาเหตุคือเดิมทุกเส้น
# ใช้สันแนวตั้งเส้นเดียวกัน (ex+22) และวางป้ายไว้กึ่งกลางสันเสมอ · Profile อยู่ระหว่าง
# SavedArea กับ AuthUser พอดี กึ่งกลางของสัน SavedArea↔AuthUser จึงตกที่ **ระดับเดียวกับ
# กล่อง Profile เป๊ะ** → คำว่า "เป็นเจ้าของ" ไปจ่ออยู่ข้างกล่อง Profile และป้าย '1' ของ
# สองเส้นก็ทับกันที่ขอบ AuthUser · แก้โดยแยกเลน + เลื่อนป้ายออกจากกึ่งกลาง
#   (จาก, ไป, ป้าย, mult ต้นทาง, mult ปลายทาง, เลน, ตำแหน่งป้ายบนสัน 0..1)
ELINKS = [('Province', 'District', 'ประกอบด้วย', '1', '0..*', 0, 0.50),
          ('SavedArea', 'AuthUser', 'เป็นเจ้าของ', '0..*', '1', 1, 0.22),
          ('AuthUser', 'Profile', 'มีโปรไฟล์', '1', '1', 0, 0.50)]
ELANE0, ELANEW = 26, 30             # ระยะสันเลนแรกจากขอบกล่อง · ระยะห่างระหว่างเลน

ROW, HDR, GAP, PAD, EGAP = 32, 52, 30, 12, 24
FS = 24
# ช่องว่างคอลัมน์แรก 140: Boundary → Control มี 7 เส้น (ProfileView ผูก 2 Control)
# เลนสุดท้ายอยู่ที่ XS[1]-30-6*15 = ขอบขวาคอลัมน์ Boundary + 20 พอดี
COLGAP = [140, 115, 140]            # ช่องว่างระหว่างคอลัมน์ (เลน/สันต้นไม้)

XS = [40]
for i, g in enumerate(COLGAP):
    XS.append(XS[i] + BWS[i] + g)

c0 = Canvas(10, 10)
pos = {}                            # ชื่อ -> (x, y, คอลัมน์)

# ที่ว่างขวาสุดสำหรับเลน + ป้ายความสัมพันธ์ของ Entity — คำนวณจากป้ายที่ยาวที่สุดจริง
# แทนการฝังตัวเลขไว้ ไม่งั้นเพิ่มเลนแล้วป้ายจะถูกขอบภาพตัด
RMARGIN = int(ELANE0 + max(l for *_, l, _f in ELINKS) * ELANEW + 10
              + max(c0.textw(n, FS - 8) for _a, _b, n, *_ in ELINKS) + 16)


def wrap(t, maxw):
    if c0.textw(t, FS) <= maxw:
        return [t]
    for sep in (', ', '('):
        if sep in t:
            i = t.index(sep) + len(sep)
            head, tail = t[:i], '    ' + t[i:]
            if c0.textw(head, FS) <= maxw and c0.textw(tail, FS) <= maxw:
                return [head, tail]
    return [t]


def wrapped(n):
    _, a, m = CLS[n]
    maxw = BWS[pos[n][2]] - 2 * PAD if n in pos else BWS[0] - 2 * PAD
    return ([w for t in a for w in wrap(t, maxw)],
            [w for t in m for w in wrap(t, maxw)])


def height(n):
    a, m = wrapped(n)
    if not a and not m:
        return HDR                  # Entity: เฉพาะส่วนหัว (stereotype + ชื่อคลาส)
    return HDR + ROW * (len(a) + len(m)) + (8 if m else 4)


for ci, names in enumerate(COLS):
    y = 40
    for n in names:
        pos[n] = (XS[ci], y, ci)
        y += height(n) + (EGAP if ci == 3 else GAP)

H = max(pos[n][1] + height(n) for n in CLS) + 40
W = XS[3] + BWS[3] + RMARGIN
c = Canvas(W, H)


def bw(n):
    return BWS[pos[n][2]]


def mid(n):
    x, y, ci = pos[n]
    return x, y + height(n) / 2, ci


def box(n):
    x, y, ci = pos[n]
    st = CLS[n][0]
    attrs, meths = wrapped(n)
    w, h = BWS[ci], height(n)
    c.d.rectangle([x * 3, y * 3, (x + w) * 3, (y + h) * 3], fill=WHITE)
    c.rect(x, y, x + w, y + h, width=1.3)
    c.text(x + w / 2, y + 15, f'«{st}»', FS - 4)
    c.text(x + w / 2, y + 37, n, FS, bold=True)
    if not attrs and not meths:
        return
    c.line(x, y + HDR, x + w, y + HDR, 1.1)
    yy = y + HDR + 4
    for a in attrs:
        c.text(x + PAD, yy + ROW / 2, a, FS, anchor='lm')
        yy += ROW
    if meths:
        c.line(x, yy, x + w, yy, 1.1)
        for m in meths:
            c.text(x + PAD, yy + ROW / 2, m, FS, anchor='lm')
            yy += ROW


def tag(x, y, s, dx=0, dy=0, fs=None):
    """ข้อความบนพื้นขาว — เจาะเส้นที่ลอดผ่านให้อ่านออก"""
    if not s:
        return
    fs = fs or FS - 5
    w = c.textw(s, fs)
    c.d.rectangle([(x + dx - w / 2 - 3) * 3, (y + dy - 12) * 3,
                   (x + dx + w / 2 + 3) * 3, (y + dy + 12) * 3], fill=WHITE)
    c.text(x + dx, y + dy, s, fs)


# ── จุดต่อเส้นบนขอบกล่อง ─────────────────────────────────────────────────────
# กล่องหนึ่งอาจมีหลายเส้นเข้า/ออก (DashboardController รับจาก Boundary 3 ตัว ·
# DistrictNDVIAnnual ถูกใช้โดยทั้ง GISDataService และ UrbanAnalysisService) ถ้าทุกเส้น
# จ่อกลางขอบเดียวกันหมด เส้นจะทับกันสนิทจนนับไม่ออกว่ามีกี่เส้น และป้าย multiplicity
# ก็ซ้อนกัน → กระจายจุดต่อตามแนวตั้ง เรียงตามความสูงของกล่องปลายอีกฝั่งเพื่อไม่ให้ไขว้
_OUT, _IN = {}, {}


def _reg(d, name, key, ref_y):
    d.setdefault(name, []).append((ref_y, key))


def _resolve(d):
    off = {}
    for name, items in d.items():
        items.sort()
        n = len(items)
        h = height(name)
        step = 30 if h >= 200 else 18 if h >= 100 else 14   # ≥30 = ป้าย multiplicity ไม่ซ้อน
        for k, (_, key) in enumerate(items):
            off[(name, key)] = (k - (n - 1) / 2) * step
    return off


for _i, (_a, _b, *_r) in enumerate(LINKS):
    _reg(_OUT, _a, _i, mid(_b)[1])
    _reg(_IN, _b, _i, mid(_a)[1])
for _i, (_s, _ds, *_r) in enumerate(TREES):
    _reg(_OUT, _s, ('T', _i), mid(_ds[0])[1])
    for _d in _ds:
        _reg(_IN, _d, ('T', _i), mid(_s)[1])
# composition ออกทาง *ซ้าย* ของกล่อง whole จึงไม่ต้องแย่งจุดต่อกับเส้นฝั่งขวา
for _p in COMPOSITION[1]:
    _reg(_IN, _p, 'C', mid(COMPOSITION[0])[1])

OUTY = _resolve(_OUT)
INY = _resolve(_IN)


# ── 1) เส้นทั้งหมดก่อน แล้วค่อยวาดกล่องทับ (กล่องคือพื้นหลังทึบของตัวเอง) ──────
DASH = (8, 6, 0)
LCLEAR = 20                         # ระยะขั้นต่ำจากขอบกล่องต้นทางถึงขอบซ้ายของป้าย

# เรขาคณิตของทุกเส้นก่อน — ต้องรู้ตำแหน่งสันของ *ทุก* เส้นก่อนถึงจะเลือกที่วางป้ายได้
GEO = []
for i, (a, b, kind, lane, name, ma, mb, side) in enumerate(LINKS):
    xa, ya, ca = mid(a)
    xb, yb, cb = mid(b)
    ya += OUTY[(a, i)]
    yb += INY[(b, i)]
    lx = XS[cb] - 30 - lane * 15 if side == 'dst' else XS[ca] + BWS[ca] + 26 + lane * 14
    GEO.append(dict(kind=kind, lane=lane, name=name, ma=ma, mb=mb, ca=ca, cb=cb,
                    ya=ya, yb=yb, lx=lx, x0=xa + BWS[ca], x1=XS[cb]))


# ── เลือกความสูงของป้ายชื่อความสัมพันธ์ (เฉพาะเส้นทึบ assoc) ─────────────────
# เดิมวางกึ่งกลางสันเสมอ (f = 0.5) ซึ่งพังเมื่อกึ่งกลางไปตรงกับของคนอื่นพอดี:
# สัน ProfileView→AuthController ยาวคร่อมทั้งคอลัมน์ กึ่งกลางของมันตกที่ *ระดับเดียวกับ
# ช่วงแนวนอนที่ออกจากกล่อง AuthView* → ป้าย "แก้รหัสผ่าน/อีเมล" ไปนั่งจ่อขอบกล่อง
# AuthView แล้วพื้นขาวของป้ายเจาะสันที่ลอดผ่านพร้อมกันหลายเส้น อ่านเป็นเส้นขาดหมด
# (อาการเดียวกับที่ ELINKS เคยเจอ — คนละที่แต่รากเดียวกันคือ "กึ่งกลางไม่ใช่ที่ว่างเสมอ")
#
# แทนที่จะไล่ปรับ f ทีละเส้นด้วยมือ ให้ไล่หาความสูงบนสันของตัวเองที่ชนของคนอื่นน้อยที่สุด
# แล้วค่อย tie-break ด้วยความใกล้กึ่งกลาง (ธรรมเนียม UML ยังคงอยู่ถ้าตรงกลางว่าง)
def label_slot(g, taken):
    lw = c.textw(g['name'], FS - 8)
    lxl = max(g['lx'], XS[g['ca']] + BWS[g['ca']] + LCLEAR + lw / 2)
    bx0, bx1 = lxl - lw / 2 - 4, lxl + lw / 2 + 4
    lo, hi = sorted((g['ya'], g['yb']))
    lo, hi = lo + 36, hi - 36        # เว้นหัวท้ายไว้ ไม่ให้ป้ายไปทับมุมหักของเส้น
    if hi <= lo:
        return lxl, (lo + hi) / 2
    # กล่องในคอลัมน์ต้นทาง — ใช้เลือก "ช่องว่างระหว่างกล่อง" ซึ่งเป็นที่ที่อ่านง่ายที่สุด
    boxes = [(pos[n][1], pos[n][1] + height(n)) for n in COLS[g['ca']]]
    mid_y, best = (lo + hi) / 2, None
    for y in range(int(lo), int(hi) + 1, 4):
        cost = abs(y - mid_y) / 500.0
        for h in GEO:
            if h is g:
                continue
            if bx0 <= h['lx'] <= bx1 and min(h['ya'], h['yb']) <= y <= max(h['ya'], h['yb']):
                cost += 3            # พื้นขาวของป้ายจะเจาะสันของเส้นอื่น
            for hy, hx0, hx1 in ((h['ya'], h['x0'], h['lx']), (h['yb'], h['lx'], h['x1'])):
                # 30 = ครึ่งความสูงกรอบป้าย (12) + ระยะที่ยังอ่านแยกออกว่าเป็นคนละเส้น
                # เดิมตั้งไว้ 18 ซึ่งแคบไป — ป้ายไปนั่งห่างเส้นอื่นแค่ 21px ดูเป็นป้ายของเส้นนั้น
                if abs(hy - y) < 30 and hx0 - 8 <= bx1 and bx0 <= hx1 + 8:
                    cost += 5        # ระดับเดียวกับช่วงแนวนอนของเส้นอื่น = อ่านสลับเส้นได้
            # ป้าย multiplicity ของเส้นอื่น (วาดก่อน) — ถ้ากรอบขาวของป้ายชื่อคร่อมมัน
            # เลข '1' จะถูกฝานหายครึ่งตัว เพราะ tag() ทาพื้นขาวทับของที่วาดไว้ก่อนหน้า
            for tx, ty, tt in ((h['x0'] + 22, h['ya'] - 15, h['ma']),
                               (h['x1'] - 18, h['yb'] - 15, h['mb'])):
                if not tt:
                    continue
                tw = c.textw(tt, FS - 5) / 2 + 3
                if abs(ty - y) < 26 and tx - tw <= bx1 and bx0 <= tx + tw:
                    cost += 5
        for ty in taken:
            if abs(ty - y) < 40:
                cost += 6            # ป้ายสองอันชิดกันเกินไป
        for top, bot in boxes:
            if abs(y - top) < 14 or abs(y - bot) < 14:
                cost += 3            # เสมอขอบบน/ล่างของกล่องพอดี ดูเหมือนป้ายของกล่อง
            elif top < y < bot:
                cost += 2            # อยู่ข้างกล่อง — ยอมได้ แต่ช่องว่างระหว่างกล่องดีกว่า
        if best is None or cost < best[0]:
            best = (cost, y)
    return lxl, best[1]


LABEL_AT, _taken = {}, []
for _i, _g in enumerate(GEO):
    if _g['kind'] == 'assoc' and abs(_g['ya'] - _g['yb']) >= 60:
        LABEL_AT[_i] = label_slot(_g, _taken)
        _taken.append(LABEL_AT[_i][1])

# ⚠️ ต้องวาด *เส้นทุกเส้นให้ครบก่อน* แล้วค่อยวาดป้ายทั้งหมด — เดิมวาดสลับกันไปทีละเส้น
# ทำให้สันของเส้นที่วาดทีหลังพาดทับป้าย multiplicity ของเส้นก่อนหน้า (เลข '1' ของ
# AuthView โดนสันเลน 6 ของ ProfileView→AuthController ขีดผ่านกลางจนเหลือแต่ขีดตั้ง)
for g in GEO:
    dash = DASH if g['kind'] == 'dep' else None
    ya, yb, lx = g['ya'], g['yb'], g['lx']
    c.line(g['x0'], ya, lx, ya, 1.1, dash=dash)
    c.line(lx, ya, lx, yb, 1.1, dash=dash)
    c.line(lx, yb, g['x1'], yb, 1.1, dash=dash)
    if g['kind'] == 'dep':
        c.arrow_head(g['x1'], yb, 0, size=12)

for i, g in enumerate(GEO):
    ya, yb, lx = g['ya'], g['yb'], g['lx']
    tag(g['x0'], ya, g['ma'], dx=22, dy=-15)
    tag(g['x1'], yb, g['mb'], dx=-18, dy=-15)
    if i in LABEL_AT:
        lxl, ly = LABEL_AT[i]
        tag(lxl, ly, g['name'], fs=FS - 8)
    elif abs(ya - yb) < 60:
        # เส้นเกือบตรง ไม่มีช่วงแนวตั้งให้วางป้าย — ย้ายไปใต้ช่วงแนวนอนฝั่งต้นทาง
        tag((g['x0'] + lx) / 2, ya, g['name'], dy=18, fs=FS - 8)
    else:
        # «use» ทุกเส้นเขียนเหมือนกัน ถ้าวางกลางช่วงแนวตั้งเท่ากันหมดจะซ้อนกันเอง
        # เมื่อสองเส้นอยู่ในเลนติดกัน → เลื่อนตำแหน่งตามเลข lane ให้ไม่ตรงกัน
        f = 0.32 + 0.18 * (g['lane'] % 3)
        # เลนท้าย ๆ อยู่ชิดคอลัมน์ต้นทาง ป้ายที่วางกลางเลนจะล้ำเข้าไปในกล่อง แล้วถูก
        # box() ที่วาดทีหลังทับหายไปครึ่งคำ → ดันป้ายให้ขอบซ้ายพ้นกล่องเสมอ
        lw = c.textw(g['name'], FS - 8)
        tag(max(lx, XS[g['ca']] + BWS[g['ca']] + LCLEAR + lw / 2),
            ya + (yb - ya) * f, g['name'], fs=FS - 8)

for ti, (src, dsts, kind, off, name) in enumerate(TREES):
    xs, ys, cs = mid(src)
    ys += OUTY[(src, ('T', ti))]
    tx = XS[cs] + BWS[cs] + off
    dash = DASH if kind == 'dep' else None
    yds = [mid(d)[1] + INY[(d, ('T', ti))] for d in dsts]
    c.line(xs + BWS[cs], ys, tx, ys, 1.1, dash=dash)              # ต้นทาง → สัน
    c.line(tx, min(yds + [ys]), tx, max(yds + [ys]), 1.1, dash=dash)   # สันแนวตั้ง
    for d, yd in zip(dsts, yds):
        cd = pos[d][2]
        c.line(tx, yd, XS[cd], yd, 1.1, dash=dash)                # กิ่ง → ปลายทาง
        if kind == 'dep':
            c.arrow_head(XS[cd], yd, 0, size=12)
    tag(tx, ys, name, dy=-16, fs=FS - 8)

# Composition — สันเดินนอกกล่องทางซ้าย ไม่ลอดผ่านกล่องอื่น
whole, parts, cname = COMPOSITION
xw, yw, cw = mid(whole)
tx = XS[cw] - 16
c.line(XS[cw], yw, tx, yw, 1.1)
c.line(tx, yw, tx, max(mid(p)[1] + INY[(p, 'C')] for p in parts), 1.1)
d = 9
c.d.polygon([(XS[cw] * 3, yw * 3), ((XS[cw] - d) * 3, (yw - d) * 3),
             ((XS[cw] - 2 * d) * 3, yw * 3), ((XS[cw] - d) * 3, (yw + d) * 3)], fill=BLACK)
tag(XS[cw], yw, '1', dx=-32, dy=-15)
for p in parts:
    yp = mid(p)[1] + INY[(p, 'C')]
    c.line(tx, yp, XS[pos[p][2]], yp, 1.1)
    tag(XS[pos[p][2]], yp, '1', dx=-24, dy=-15)
# ป้ายวางในช่องว่างใต้กล่อง whole และเยื้องขวาของสัน — ชิดขอบซ้ายกระดาษเกินไปจะถูกตัด
_cw = c.textw(cname, FS - 8)
tag(tx + _cw / 2 + 8, pos[whole][1] + height(whole) + GAP / 2, cname, fs=FS - 8)

# Entity ↔ Entity — เดินทางขวาของคอลัมน์สุดท้าย (ซ้ายเป็นทางเข้าของเส้น «use»)
# กล่องที่มีหลายเส้นต่อ (AuthUser มี 2) ต้องกระจายจุดต่อตามแนวตั้ง ไม่งั้นเส้นและป้าย
# multiplicity ทับกันสนิท · ลำดับ: เลนที่อยู่ *นอก* กว่าให้ต่อฝั่งตรงข้ามกับทิศที่มันวิ่งมา
# — ถ้าสลับกัน ช่วงแนวนอนของเลนนอกจะตัดผ่านสันแนวตั้งของเลนใน
_ETMP = {}
for _i, (_a, _b, _n, _ma, _mb, _ln, _f) in enumerate(ELINKS):
    _ETMP.setdefault(_a, []).append((_i, _ln, 1 if mid(_b)[1] > mid(_a)[1] else -1))
    _ETMP.setdefault(_b, []).append((_i, _ln, 1 if mid(_a)[1] > mid(_b)[1] else -1))
EOFF = {}
for _e, _its in _ETMP.items():
    _its.sort(key=lambda t: -t[1] * t[2])
    for _k, (_li, _, _) in enumerate(_its):
        EOFF[(_e, _li)] = (_k - (len(_its) - 1) / 2) * 13

for i, (a, b, name, ma, mb, lane, f) in enumerate(ELINKS):
    _, ya, ca = mid(a)
    _, yb, cb = mid(b)
    ya += EOFF[(a, i)]
    yb += EOFF[(b, i)]
    ex = XS[ca] + BWS[ca]
    lx = ex + ELANE0 + lane * ELANEW
    c.line(ex, ya, lx, ya, 1.1)
    c.line(lx, ya, lx, yb, 1.1)
    c.line(lx, yb, ex, yb, 1.1)
    # ป้าย multiplicity เกาะ *สัน* ของเส้นตัวเอง ไม่ใช่ขอบกล่อง — สองเส้นที่เข้ากล่อง
    # เดียวกันคนละเลนจึงไม่ทับกัน และอ่านออกว่าเลขไหนเป็นของเส้นไหน
    tag(lx, ya, ma, dx=-14, dy=-14)
    tag(lx, yb, mb, dx=-14, dy=-14)
    tag(lx + c.textw(name, FS - 8) / 2 + 10, ya + (yb - ya) * f, name, fs=FS - 8)

for n in CLS:
    box(n)

# ── Note: ที่มาของ AuthUser ──────────────────────────────────────────────────
# แทน stereotype «Entity, external» เดิม ซึ่งไม่ใช่การซ้อน stereotype ที่ UML รองรับ
NOTE = ['ตารางของ Supabase Auth (GoTrue)', 'ไม่ได้อยู่ใน migrations ของโปรเจกต์']
_ax, _ay, _ac = pos['AuthUser']
_ah, _nfs, _fold = height('AuthUser'), FS - 4, 16
_nw = max(c.textw(t, _nfs) for t in NOTE) + 30 + _fold   # +fold กันมุมพับทับตัวอักษร
_nh = 26 * len(NOTE) + 22
_n0 = _ax + (BWS[_ac] - _nw) / 2
_ny0 = _ay + _ah + 52
c.line(_ax + BWS[_ac] / 2, _ay + _ah, _ax + BWS[_ac] / 2, _ny0, 1.0, dash=DASH)
c.d.polygon([(_n0 * 3, _ny0 * 3), ((_n0 + _nw - _fold) * 3, _ny0 * 3),
             ((_n0 + _nw) * 3, (_ny0 + _fold) * 3),
             ((_n0 + _nw) * 3, (_ny0 + _nh) * 3), (_n0 * 3, (_ny0 + _nh) * 3)],
            fill=WHITE, outline=BLACK, width=3)
c.line(_n0 + _nw - _fold, _ny0, _n0 + _nw - _fold, _ny0 + _fold, 1.0)
c.line(_n0 + _nw - _fold, _ny0 + _fold, _n0 + _nw, _ny0 + _fold, 1.0)
for _i, _t in enumerate(NOTE):
    c.text(_n0 + _nw / 2, _ny0 + 21 + _i * 26, _t, _nfs)

HERE = os.path.dirname(os.path.abspath(__file__))
c.save(os.path.join(HERE, '..', 'class_new.png'))
print('saved', (W, H), 'aspect 1:%.3f' % (H / W),
      '· พิมพ์กว้าง 14.65 ซม. → สูง %.1f ซม.' % (14.65 * H / W),
      '· ตัวอักษร ≈ %.1f pt' % (FS * 415 / W),
      '·', len(CLS), 'คลาส')
