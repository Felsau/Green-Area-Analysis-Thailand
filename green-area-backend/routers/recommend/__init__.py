"""Recommend package — re-export `router` เพื่อให้ `from routers import recommend` ทำงานเหมือนเดิม.

Re-export internal helpers ด้วยชื่อเดิม (`_normalize_weights`, weight constants)
เพื่อให้ tests ที่ import ตรงจาก `routers.recommend` ยังทำงานได้.
"""
from .endpoints import router
from .scoring import (
    W_NDVI, W_LST, W_POP, W_ACCESS,
    TOP_MIN_SEPARATION_M, NATIVE_CHECK_SCALE_M,
    normalize_weights as _normalize_weights,
    _haversine_m, _space_out, _drop_non_plantable,
)

__all__ = ["router", "_normalize_weights", "W_NDVI", "W_LST", "W_POP", "W_ACCESS",
           "TOP_MIN_SEPARATION_M", "NATIVE_CHECK_SCALE_M",
           "_haversine_m", "_space_out", "_drop_non_plantable"]
