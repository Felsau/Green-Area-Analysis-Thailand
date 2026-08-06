#!/usr/bin/env python3
"""Sequence Diagram ทั้ง 11 แผนภาพ — ใช้ชื่อคลาสเอกพจน์ตาม Class Diagram
Entity ไม่มีเมธอดแล้ว ข้อความที่ยิงเข้า Entity จึงเขียนเป็นการเข้าถึงข้อมูล ไม่ใช่การเรียกเมธอด"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gen_seq import build, B, C, E, S, CALL, RET, SELF

GUEST, REG, ADMIN = 'ผู้เยี่ยมชมทั่วไป', 'ผู้ใช้ลงทะเบียน', 'ผู้ดูแลระบบ'
A = -1                                     # index ของ actor

SDS = [
 ('การเข้าสู่ระบบ', GUEST,
  [('AuthView', B), ('AuthController', C), ('Profile', E)],
  [(A, 0, 'กรอกอีเมลและรหัสผ่าน', CALL),
   (0, 1, 'authenticateUser(email, password)', CALL),
   (1, 2, 'อ่านโปรไฟล์และสิทธิ์ตาม user_id', CALL),
   (2, 1, 'คืน display_name, role', RET),
   (1, 0, 'คืน Session Token และสิทธิ์การใช้งาน', RET),
   (0, 0, 'เปิดหน้าจอแดชบอร์ดหลัก', SELF)]),

 ('การสมัครสมาชิก', GUEST,
  [('AuthView', B), ('AuthController', C), ('Profile', E)],
  [(A, 0, 'กรอกข้อมูลสมัครและยอมรับเงื่อนไข', CALL),
   (0, 1, 'registerUser(email, password, profile)', CALL),
   (1, 2, 'สร้างโปรไฟล์ใหม่ พร้อม role และเวลายอมรับเงื่อนไข', CALL),
   (2, 1, 'ยืนยันการสร้างบัญชี', RET),
   (1, 0, 'แจ้งผลการสมัครสำเร็จ', RET),
   (0, 0, 'เปลี่ยนไปหน้าจอเข้าสู่ระบบ', SELF)]),

 ('การดูข้อมูล LST', REG,
  [('MainDashboardView', B), ('DashboardController', C), ('GISDataService', S),
   ('Province', E)],
  [(A, 0, 'เลือกชั้นข้อมูล LST และช่วงปี', CALL),
   (0, 1, 'changeFilter(province, district, year)', CALL),
   (1, 2, 'fetchLSTData(province, district, year)', CALL),
   (2, 3, 'อ่านขอบเขตและชื่อจังหวัด', CALL),
   (3, 2, 'คืนข้อมูลจังหวัด', RET),
   (2, 1, 'คืนค่าสถิติ LST และ URL ภาพ tile', RET),
   (1, 0, 'ส่งข้อมูลไปแสดงผล', RET),
   (0, 0, 'updateCharts()', SELF)]),

 ('การดูข้อมูล NDVI', REG,
  [('MainDashboardView', B), ('DashboardController', C), ('GISDataService', S),
   ('NDVIAnnual', E)],
  [(A, 0, 'เลือกชั้นข้อมูล NDVI และช่วงปี', CALL),
   (0, 1, 'changeFilter(province, district, year)', CALL),
   (1, 2, 'fetchNDVIData(province, district, year)', CALL),
   (2, 3, 'อ่านค่าดัชนีพืชพรรณรายปีจากแคช', CALL),
   (3, 2, 'คืน ndvi_mean, green_area_km2, canopy', RET),
   (2, 1, 'คืนชุดข้อมูลและ URL ภาพ tile', RET),
   (1, 0, 'ส่งข้อมูลไปแสดงผล', RET),
   (0, 0, 'updateCharts()', SELF)]),

 ('การเปรียบเทียบพื้นที่', REG,
  [('AnalysisReportView', B), ('DashboardController', C), ('GISDataService', S),
   ('NDVIAnnual', E)],
  [(A, 0, 'เลือกจังหวัดตั้งแต่ 2 พื้นที่ขึ้นไป', CALL),
   (0, 1, 'getOverviewStats()', CALL),
   (1, 2, 'fetchNDVIData() ของแต่ละพื้นที่  «include»', CALL),
   (2, 3, 'อ่านค่ารายปีของทุกพื้นที่ที่เลือก', CALL),
   (3, 2, 'คืนชุดข้อมูลรายพื้นที่', RET),
   (2, 1, 'คืนข้อมูลสำหรับเปรียบเทียบ', RET),
   (1, 0, 'ส่งผลเปรียบเทียบไปแสดงผล', RET),
   (0, 0, 'displayReport()', SELF)]),

 ('การค้นหาตำแหน่ง', REG,
  [('MapViewComponent', B), ('DashboardController', C), ('GISDataService', S),
   ('Province', E), ('District', E)],
  [(A, 0, 'พิมพ์ชื่อจังหวัดหรืออำเภอ', CALL),
   (0, 1, 'changeFilter(province, district, year)', CALL),
   (1, 2, 'fetchProvinceList()', CALL),
   (2, 3, 'อ่านรายชื่อและขอบเขตจังหวัด', CALL),
   (3, 2, 'คืนจังหวัดที่ตรงกับคำค้น', RET),
   (2, 4, 'อ่านรายชื่ออำเภอในจังหวัดที่เลือก', CALL),
   (4, 2, 'คืนรายชื่ออำเภอ', RET),
   (2, 1, 'คืนพิกัดศูนย์กลางและเส้นขอบเขต', RET),
   (1, 0, 'ส่งข้อมูลไปแสดงผล', RET),
   (0, 0, 'drawGeometry()', SELF)]),

 ('การบันทึกพื้นที่โปรด', REG,
  [('CustomAreaWorkspace', B), ('SavedAreaManager', C), ('SavedArea', E)],
  [(A, 0, 'วาดขอบเขตพื้นที่บนแผนที่', CALL),
   (0, 0, 'triggerAnalysis()', SELF),
   (0, 1, 'createSavedArea(label, geometry, province, year)', CALL),
   (1, 2, 'บันทึกแถวใหม่พร้อม user_id ของผู้ใช้', CALL),
   (2, 1, 'คืนรหัสพื้นที่ที่บันทึก', RET),
   (1, 0, 'แจ้งผลการบันทึกสำเร็จ', RET),
   (0, 0, 'clearCanvas()', SELF)]),

 ('การขอคำแนะนำปลูกต้นไม้', REG,
  [('AnalysisReportView', B), ('DashboardController', C), ('PlantingAdvisor', S),
   ('NDVIAnnual', E)],
  [(A, 0, 'เลือกพื้นที่แล้วเปิดเมนูคำแนะนำปลูกต้นไม้', CALL),
   (0, 1, 'getOverviewStats()', CALL),
   (1, 2, 'generatePlantingPoints(province, district, year)', CALL),
   (2, 3, 'อ่านค่า NDVI และพื้นที่สีเขียวของพื้นที่เป้าหมาย', CALL),
   (3, 2, 'คืนค่าดัชนีรายปี', RET),
   (2, 2, 'predictCoolingImpact(geometry)', SELF),
   (2, 1, 'คืนพิกัด 10 อันดับแรกและผลกระทบที่คาดการณ์', RET),
   (1, 0, 'ส่งผลไปแสดงผล', RET),
   (0, 0, 'displayReport()', SELF)]),

 ('การดูสถิติเขตเมือง', REG,
  [('AnalysisReportView', B), ('DashboardController', C), ('UrbanAnalysisService', S),
   ('UrbanNDVIAnnual', E)],
  [(A, 0, 'เลือกเมนูสถิติเขตเมืองและเลือกอำเภอ', CALL),
   (0, 1, 'getOverviewStats()', CALL),
   (1, 2, 'analyzeUrbanGreenShare(province, district, year)', CALL),
   (2, 3, 'อ่านสัดส่วนพื้นที่เมืองและพื้นที่สีเขียว', CALL),
   (3, 2, 'คืนค่าสถิติเขตเมือง', RET),
   (2, 2, 'evaluateWHOCriteria(greenAreaM2PerPerson)', SELF),
   (2, 1, 'คืนผลประเมินเทียบเกณฑ์ WHO', RET),
   (1, 0, 'ส่งผลไปแสดงผล', RET),
   (0, 0, 'sortData(criteria)', SELF)]),

 ('การจัดการข้อมูลโปรไฟล์', REG,
  [('ProfileView', B), ('ProfileController', C), ('Profile', E)],
  [(A, 0, 'เปิดหน้าจอบัญชีผู้ใช้', CALL),
   (0, 1, 'getProfile(userId)', CALL),
   (1, 2, 'อ่านข้อมูลโปรไฟล์ตาม user_id', CALL),
   (2, 1, 'คืน display_name, organization, role', RET),
   (1, 0, 'ส่งข้อมูลไปแสดงผล', RET),
   (A, 0, 'แก้ไขข้อมูลแล้วกดบันทึก', CALL),
   (0, 1, 'updateProfile(displayName, organization)', CALL),
   (1, 2, 'เขียนทับข้อมูลและเวลาปรับปรุงล่าสุด', CALL),
   (2, 1, 'ยืนยันการบันทึก', RET),
   (1, 0, 'แจ้งผลการแก้ไขสำเร็จ', RET)]),

 ('การจัดการข้อมูล/แคช', ADMIN,
  [('MainDashboardView', B), ('DashboardController', C), ('GISDataService', S),
   ('NDVIAnnual', E)],
  [(A, 0, 'เลือกล้างแคชของพื้นที่ที่ต้องการ', CALL),
   (0, 1, 'changeFilter(province, district, year)', CALL),
   (1, 2, 'ล้างแคชและเพิ่มค่า cache_version', CALL),
   (2, 3, 'ปรับปรุง cache_version ของแถวที่เกี่ยวข้อง', CALL),
   (3, 2, 'ยืนยันการปรับปรุง', RET),
   (2, 1, 'แจ้งผลการล้างแคชสำเร็จ', RET),
   (1, 0, 'สั่งโหลดข้อมูลใหม่', RET),
   (0, 0, 'updateCharts()', SELF)]),
]

if __name__ == '__main__':
    # เขียนลงโฟลเดอร์ร่างใน repo โดยตรง — เดิมเขียน /tmp/sd_XX.png แล้วต้องคัดลอกเอง
    # ซึ่งหายทุกครั้งที่รีบูต และเคยทำให้ "รันแล้ว" กับ "ไฟล์บนดิสก์" ไม่ตรงกันเงียบ ๆ
    HERE = os.path.dirname(os.path.abspath(__file__))
    DRAFTS = os.path.join(HERE, '..')
    only = int(sys.argv[1]) if len(sys.argv) > 1 else None
    for i, (title, actor, parts, msgs) in enumerate(SDS, 1):
        if only and i != only:
            continue
        out = os.path.join(DRAFTS, f'Sequence Diagram {i:02d} (ร่าง).png')
        w, h = build(f'Sequence Diagram : {title}', actor, parts, msgs, out, prefix=i)
        print(f'{i:2d}. {title:34s} {w}×{h}  → พิมพ์ {14.5:.1f}×{14.5*h/w:.1f} ซม.')
