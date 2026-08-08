"""Unit tests สำหรับ pure stat helpers — ไม่แตะ GEE/Supabase
รัน: cd green-area-backend && pytest tests/test_stats_utils.py -v
"""
import pytest

from stats_utils import forecast_linear, linregress, mann_kendall


# linregress
class TestLinregress:
    def test_perfect_positive_line(self):
        fit = linregress([1, 2, 3, 4], [2, 4, 6, 8])  # y = 2x
        assert fit["slope"] == pytest.approx(2.0)
        assert fit["intercept"] == pytest.approx(0.0)
        assert fit["r"] == pytest.approx(1.0)
        assert fit["r2"] == pytest.approx(1.0)
        assert fit["n"] == 4

    def test_perfect_negative_line_is_cooling(self):
        # NDVI สูง → LST ต่ำ (ยิ่งเขียวยิ่งเย็น)
        fit = linregress([0.2, 0.6], [34.0, 28.0])
        assert fit["slope"] < 0
        assert fit["r"] == pytest.approx(-1.0)

    def test_fewer_than_two_points_returns_none(self):
        assert linregress([1], [2]) is None
        assert linregress([], []) is None

    def test_zero_x_variance_returns_none(self):
        # x คงที่ทุกจุด → fit ไม่ได้
        assert linregress([3, 3, 3], [1, 2, 3]) is None

    def test_mismatched_lengths_returns_none(self):
        assert linregress([1, 2, 3], [1, 2]) is None

    def test_constant_y_gives_zero_slope_and_r(self):
        fit = linregress([1, 2, 3], [5, 5, 5])
        assert fit["slope"] == pytest.approx(0.0)
        assert fit["r"] == pytest.approx(0.0)

    def test_r_stays_within_bounds(self):
        fit = linregress([1, 2, 3, 4], [1.1, 1.9, 3.2, 3.8])
        assert -1.0 <= fit["r"] <= 1.0
        assert 0.0 <= fit["r2"] <= 1.0


# mann_kendall
class TestMannKendall:
    def test_monotonic_increasing_is_significant(self):
        mk = mann_kendall([1, 2, 3, 4, 5, 6, 7, 8])
        assert mk["s"] > 0
        assert mk["tau"] == pytest.approx(1.0)
        assert mk["trend"] == "increasing"
        assert mk["p_value"] < 0.05

    def test_monotonic_decreasing_is_significant(self):
        mk = mann_kendall([8, 7, 6, 5, 4, 3, 2, 1])
        assert mk["s"] < 0
        assert mk["tau"] == pytest.approx(-1.0)
        assert mk["trend"] == "decreasing"
        assert mk["p_value"] < 0.05

    def test_flat_series_has_no_trend(self):
        mk = mann_kendall([5, 5, 5, 5, 5])
        assert mk["s"] == 0
        assert mk["trend"] == "no trend"

    def test_noisy_series_not_significant(self):
        # ขึ้นๆ ลงๆ ไม่มีทิศชัด → ไม่ควรเคลมแนวโน้ม
        mk = mann_kendall([3, 1, 4, 1, 5, 2])
        assert mk["trend"] == "no trend"

    def test_fewer_than_three_points_returns_none(self):
        assert mann_kendall([1, 2]) is None
        assert mann_kendall([1]) is None

    def test_tau_within_bounds(self):
        mk = mann_kendall([1, 3, 2, 4, 5])
        assert -1.0 <= mk["tau"] <= 1.0
        assert mk["n"] == 5

    def test_handles_ties_without_error(self):
        # ค่าซ้ำ (ties) ต้องไม่ทำให้ variance พังหรือ p เกินช่วง
        mk = mann_kendall([2, 2, 3, 3, 4, 4])
        assert 0.0 <= mk["p_value"] <= 1.0


# forecast_linear
class TestForecastLinear:
    def test_perfect_line_projects_exactly(self):
        # y = 2x — residual ศูนย์ → คาดการณ์ตรงเส้น, ช่วงความเชื่อมั่นแคบมาก
        fc = forecast_linear([2020, 2021, 2022, 2023], [2.0, 4.0, 6.0, 8.0],
                             horizon=2)
        assert fc["slope"] == pytest.approx(2.0)
        assert fc["n"] == 4
        assert [p["x"] for p in fc["points"]] == [2024, 2025]
        assert fc["points"][0]["value"] == pytest.approx(10.0)
        assert fc["points"][1]["value"] == pytest.approx(12.0)
        assert fc["points"][0]["lo"] == pytest.approx(10.0, abs=1e-6)
        assert fc["points"][0]["hi"] == pytest.approx(10.0, abs=1e-6)

    def test_interval_widens_with_horizon(self):
        # ยิ่ง extrapolate ไกล ช่วงคาดการณ์ยิ่งกว้าง
        fc = forecast_linear([2019, 2020, 2021, 2022, 2023],
                             [0.30, 0.34, 0.31, 0.36, 0.35], horizon=3)
        widths = [p["hi"] - p["lo"] for p in fc["points"]]
        assert widths[0] < widths[1] < widths[2]

    def test_interval_contains_point_estimate(self):
        fc = forecast_linear([2020, 2021, 2022, 2023],
                             [0.40, 0.42, 0.41, 0.44], horizon=3)
        for p in fc["points"]:
            assert p["lo"] <= p["value"] <= p["hi"]

    def test_clamp_keeps_values_in_range(self):
        # NDVI ใกล้เพดาน + แนวโน้มขึ้นชัน → ค่าคาดการณ์/ช่วงต้องไม่ทะลุ 1.0
        fc = forecast_linear([2020, 2021, 2022], [0.7, 0.85, 0.99],
                             horizon=3, clamp=(-1.0, 1.0))
        for p in fc["points"]:
            assert -1.0 <= p["lo"] <= p["value"] <= p["hi"] <= 1.0

    def test_fewer_than_three_points_returns_none(self):
        # 2 จุดลากเส้นได้เสมอ (residual=0) — ไม่มีข้อมูลพอประเมินความไม่แน่นอน
        assert forecast_linear([2022, 2023], [0.3, 0.4]) is None
        assert forecast_linear([2023], [0.3]) is None
        assert forecast_linear([], []) is None

    def test_mismatched_lengths_returns_none(self):
        assert forecast_linear([2021, 2022, 2023], [0.3, 0.4]) is None

    def test_zero_x_variance_returns_none(self):
        assert forecast_linear([2023, 2023, 2023], [1.0, 2.0, 3.0]) is None

    def test_small_n_uses_wider_t_than_normal(self):
        # n=3 (df=1) → t=12.706 ไม่ใช่ z=1.96 — ช่วงต้องกว้างกว่า ±1.96·se มาก
        fc = forecast_linear([2021, 2022, 2023], [0.30, 0.36, 0.31], horizon=1)
        p = fc["points"][0]
        assert (p["hi"] - p["lo"]) > 0.1  # กว้างจริงเมื่อข้อมูลน้อย+noisy
