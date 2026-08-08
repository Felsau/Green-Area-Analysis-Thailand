"""Unit tests สำหรับ TTLCache (shared in-process tile-URL cache).

ครอบ: hit/miss, TTL expiry, size-bounded eviction, และ thread-safety ของ set()
(check→evict→insert ที่หลาย thread เรียกพร้อมกันใน threadpool ของ FastAPI —
เดิม impl ใน tiles.py ลืม lock จึง race เป็น KeyError/dict-changed-size)
รัน: cd green-area-backend && pytest tests/ -v
"""
import threading

import pytest

# conftest.py ตั้ง sys.path ให้ import จาก backend root ได้
from ttl_cache import TTLCache


# basic get/set
def test_get_miss_returns_none():
    cache = TTLCache(ttl_seconds=60, max_size=10)
    assert cache.get(("a", None, 2024)) is None


def test_set_then_get_hit():
    cache = TTLCache(ttl_seconds=60, max_size=10)
    cache.set(("a", None, 2024), "url-1")
    assert cache.get(("a", None, 2024)) == "url-1"


def test_set_overwrites_existing_key():
    cache = TTLCache(ttl_seconds=60, max_size=10)
    cache.set(("a", None, 2024), "url-old")
    cache.set(("a", None, 2024), "url-new")
    assert cache.get(("a", None, 2024)) == "url-new"


def test_distinct_tuple_keys_isolated():
    cache = TTLCache(ttl_seconds=60, max_size=10)
    cache.set(("ndvi", "Tak", None, 2024), "a")
    cache.set(("lst", "Tak", None, 2024), "b")
    assert cache.get(("ndvi", "Tak", None, 2024)) == "a"
    assert cache.get(("lst", "Tak", None, 2024)) == "b"


# TTL expiry (monkeypatch time เพื่อไม่ต้อง sleep จริง)
def test_entry_expires_after_ttl(monkeypatch):
    clock = {"t": 1000.0}
    monkeypatch.setattr("ttl_cache.time.time", lambda: clock["t"])
    cache = TTLCache(ttl_seconds=30, max_size=10)
    cache.set(("a",), "url")
    assert cache.get(("a",)) == "url"      # ยังไม่หมดอายุ
    clock["t"] += 31                        # เลย TTL
    assert cache.get(("a",)) is None        # หมดอายุ → miss


# size-bounded eviction
def test_evicts_expired_first_when_full(monkeypatch):
    clock = {"t": 1000.0}
    monkeypatch.setattr("ttl_cache.time.time", lambda: clock["t"])
    cache = TTLCache(ttl_seconds=30, max_size=2)
    cache.set(("old",), "x")     # expires at 1030
    clock["t"] += 31             # ("old",) หมดอายุแล้ว
    cache.set(("a",), "a")       # set รอบนี้เคลียร์ ("old",) ที่หมดอายุก่อน insert
    cache.set(("b",), "b")
    assert cache.get(("old",)) is None
    assert cache.get(("a",)) == "a"
    assert cache.get(("b",)) == "b"


def test_evicts_oldest_when_full_and_none_expired():
    cache = TTLCache(ttl_seconds=600, max_size=2)
    cache.set(("a",), "a")
    cache.set(("b",), "b")
    cache.set(("c",), "c")       # เต็ม + ไม่มีตัวหมดอายุ → evict ("a",) ที่เก่าสุด
    assert cache.get(("a",)) is None
    assert cache.get(("b",)) == "b"
    assert cache.get(("c",)) == "c"


def test_never_exceeds_max_size():
    cache = TTLCache(ttl_seconds=600, max_size=5)
    for i in range(50):
        cache.set((i,), f"url-{i}")
    assert len(cache._store) <= 5


# thread-safety: concurrent set() ต้องไม่ crash + ไม่เกิน max_size
def test_concurrent_set_no_crash_and_bounded():
    cache = TTLCache(ttl_seconds=600, max_size=20)
    errors = []

    def worker(base):
        try:
            for i in range(500):
                cache.set((base, i), f"url-{base}-{i}")
        except Exception as e:  # KeyError / RuntimeError จาก race = fail
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(b,)) for b in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"concurrent set() raised: {errors}"
    assert len(cache._store) <= 20


# clear()
def test_clear_empties_cache():
    cache = TTLCache(ttl_seconds=60, max_size=10)
    cache.set(("a",), "x")
    cache.clear()
    assert cache.get(("a",)) is None
    assert len(cache._store) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
