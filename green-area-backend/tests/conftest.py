"""Pytest config — เพิ่ม backend root เข้า sys.path เพื่อ import โดยตรง
ตัวอย่าง: from routers.ndvi import _is_stale"""
import os
import sys

# backend root = parent ของ tests/
BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

# tests/ เองก็ต้อง import ได้ เพราะ test_gee_credential_boundary.py ใช้ fixture
# จาก test_gee_genuine_foundation.py ด้วยชื่อโมดูลเปล่า ๆ (ไม่มี tests. นำหน้า)
TESTS_ROOT = os.path.dirname(os.path.abspath(__file__))
if TESTS_ROOT not in sys.path:
    sys.path.insert(0, TESTS_ROOT)
