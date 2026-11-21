"""Endpoint-level tests for the LDD filter in the province recommend flow.
GEE and Supabase are faked; the flow under test is _run_recommendation_inner."""
from types import SimpleNamespace

import pytest

from dependencies import RECOMMEND_CACHE_VERSION
from routers.recommend import endpoints as ep

SRC = {"asset": "a", "year_be": 2568, "code_field": "LU_CODE", "name_field": "LU_DES_TH"}
_LDD = {"code": "A101", "name_th": "x", "rule": "neutral", "edition_year": 2568}


def _pt(with_ldd):
    p = {"lng": 100.0, "lat": 13.0, "score": 0.9}
    if with_ldd:
        p["ldd"] = dict(_LDD)
    return p


class FakeSupa:
    """Chainable stand-in for the supabase client; records executed operations
    as a list of verbs (e.g. ['planting_recommendations', 'delete', 'eq'])."""

    def __init__(self, rows):
        self.rows, self.ops, self._op = rows, [], []

    def table(self, name):
        self._op = [name]
        return self

    def __getattr__(self, attr):
        def step(*a, **k):
            self._op.append(attr)
            if attr == "execute":
                self.ops.append(list(self._op))
                data = self.rows if self._op[1] == "select" else []
                return SimpleNamespace(data=data)
            return self
        return step

    def count(self, verb):
        return sum(1 for o in self.ops if o[1] == verb)


@pytest.fixture
def env(monkeypatch):
    state = SimpleNamespace(supa=None, computed=0, source=None, compute_top=[],
                            stored=[], passed_source="unset")

    def setup(rows, source, compute_top):
        state.supa = FakeSupa(rows)
        state.source, state.compute_top = source, compute_top

    monkeypatch.setattr(ep, "supa_call", lambda fn, **kw: fn(state.supa))
    monkeypatch.setattr(ep, "_site_metrics", lambda *a: (30.0, 0.3))
    monkeypatch.setattr(ep, "get_recommended_species",
                        lambda *a: {"region": "x", "species": []})
    monkeypatch.setattr(ep, "rerank_species_for_spots", lambda s, *a: s)
    monkeypatch.setattr(ep, "ldd_source_for", lambda prov: state.source)
    monkeypatch.setattr(ep, "get_cached_tile_url", lambda *a: "tile")
    monkeypatch.setattr(ep, "store_tile_url", lambda *a: state.stored.append(a))
    monkeypatch.setattr(ep.ee, "Geometry", lambda g: g)

    def compute(geom, year, weights, species, lst, ndvi, ldd_source=None):
        state.computed += 1
        state.passed_source = ldd_source
        return "tile2", list(state.compute_top), {"impact": 1}, species

    monkeypatch.setattr(ep, "_compute_recommendation_payload", compute)
    state.setup = setup
    return state


def _run(prov="Bangkok Metropolis"):
    return ep._run_recommendation_inner(prov, None, {"type": "Polygon"}, 2025,
                                        *ep.normalize_weights(0.35, 0.25, 0.25, 0.15))


def _row(version, top):
    return {"id": 7, "cache_version": version, "top_locations": top,
            "impact": {"impact": 1}, "created_at": "t"}


class TestLddChecked:
    def test_no_source_always_checked(self):
        assert ep._ldd_checked([_pt(False)], None) is True

    def test_all_labelled(self):
        assert ep._ldd_checked([_pt(True), _pt(True)], SRC) is True

    def test_one_unlabelled(self):
        assert ep._ldd_checked([_pt(True), _pt(False)], SRC) is False

    def test_empty_with_source_counts_as_checked(self):
        assert ep._ldd_checked([], SRC) is True


class TestProvinceFlow:
    def test_fresh_compute_checked_has_meta_and_is_cached(self, env):
        env.setup([], SRC, [_pt(True)])
        r = _run()
        assert r["ldd_filter"]["edition_year"] == 2568
        assert r["from_cache"] is False
        assert env.passed_source == SRC
        assert env.supa.count("insert") == 1

    def test_failed_check_no_meta_and_no_insert(self, env):
        env.setup([], SRC, [_pt(True), _pt(False)])
        r = _run()
        assert "ldd_filter" not in r
        assert env.supa.count("insert") == 0
        assert env.stored == []
        assert len(r["top_locations"]) == 2

    def test_no_source_behaves_as_before(self, env):
        env.setup([], None, [_pt(False)])
        r = _run("Chonburi")
        assert "ldd_filter" not in r
        assert env.supa.count("insert") == 1

    def test_current_cache_with_ldd_served(self, env):
        env.setup([_row(RECOMMEND_CACHE_VERSION, [_pt(True)])], SRC, [])
        r = _run()
        assert r["from_cache"] is True and env.computed == 0
        assert r["ldd_filter"]["edition_year"] == 2568
        assert env.supa.count("delete") == 0

    def test_current_version_cache_without_ldd_is_stale_when_source_exists(self, env):
        assert RECOMMEND_CACHE_VERSION == 12
        env.setup([_row(12, [_pt(False)])], SRC, [_pt(True)])
        r = _run()
        assert env.supa.count("delete") == 1
        assert env.computed == 1 and r["from_cache"] is False
        assert r["ldd_filter"]["edition_year"] == 2568
        assert env.supa.count("insert") == 1

    def test_old_version_cache_deleted_and_recomputed(self, env):
        env.setup([_row(11, [_pt(True)])], SRC, [_pt(True)])
        _run()
        assert env.supa.count("delete") == 1 and env.computed == 1

    def test_no_source_cache_without_ldd_still_served(self, env):
        env.setup([_row(RECOMMEND_CACHE_VERSION, [_pt(False)])], None, [])
        r = _run("Chonburi")
        assert r["from_cache"] is True and env.computed == 0
        assert "ldd_filter" not in r
        assert env.supa.count("delete") == 0

    def test_stale_recompute_with_failed_check_leaves_no_row(self, env):
        env.setup([_row(12, [_pt(False)])], SRC, [_pt(False)])
        r = _run()
        assert env.supa.count("delete") == 1
        assert env.supa.count("insert") == 0 and "ldd_filter" not in r
