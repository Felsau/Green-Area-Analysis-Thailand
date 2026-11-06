"""Local demo composition only: original read routes, no dotenv or live GEE.

Never import this through production main.py. The human demo launcher supplies
the existing attested local operator; original formulas and Auth stay unchanged.
"""
from __future__ import annotations

import copy
from contextlib import asynccontextmanager
from functools import lru_cache
import importlib
import os
import sys
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.routing import APIRoute
import httpx
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse
from starlette.routing import request_response
from supabase import ClientOptions, create_client


LOCAL_URL = "http://127.0.0.1:55421"
TABLES = frozenset({
    "profiles", "provinces", "districts", "province_population", "saved_areas",
    "ndvi_annual", "ndvi_monthly", "district_ndvi_annual", "district_ndvi_monthly",
    "province_lst_annual", "province_lst_monthly", "district_lst_annual",
    "district_lst_monthly", "urban_ndvi_annual",
})
LEGACY_MODULES = ("main", "dependencies", "gee_utils", "ldd", "landuse",
    "routers.ndvi", "routers.lst", "routers.recommend", "routers.maps",
    "routers.account", "routers.saved")

# Exact identity/path/method allowlist. Unknown/future handlers default closed.
READ_ROUTES = frozenset({
    ("/health", "main", "health"), ("/", "main", "read_root"),
    ("/compare", "main", "compare_provinces"),
    ("/cache/ndvi-latest", "main", "get_latest_ndvi_cache"),
    ("/cache", "main", "get_cache"),
    ("/cache/districts", "main", "get_district_cache"),
    ("/timelapse/ndvi/provinces", "main", "get_timelapse_ndvi"),
    ("/timelapse/lst/provinces", "main", "get_timelapse_lst"),
    ("/analysis/ranking", "main", "get_ranking"),
    ("/account/me", "routers.account", "get_me"),
    ("/saved-areas", "routers.saved", "list_saved_areas"),
    ("/saved-areas/{area_id}", "routers.saved", "get_saved_area"),
    ("/ndvi/{province_name}/compare", "routers.ndvi.endpoints", "get_ndvi_compare"),
    ("/analysis/context/{province_name}", "routers.maps.analysis.context", "get_context"),
    ("/analysis/districts/{province_name}", "routers.maps.analysis.districts", "get_district_summary"),
    ("/analysis/cooling/{province_name}", "routers.maps.analysis.cooling", "get_cooling_analysis"),
    ("/analysis/timeseries/{province_name}", "routers.maps.analysis.timeseries", "get_timeseries"),
})
# Served by cached_ndvi_handler, never by the original endpoint: that one deletes rows it
# considers stale and computes through GEE. The Trend tab reads this route year by year.
CACHED_NDVI_ROUTE = ("/ndvi/{province_name}", "routers.ndvi.endpoints", "get_ndvi")


def dependency_error(code="LOCAL_GEE_BLOCKED"):
    message = ("Local Demo อ่านข้อมูลเดิมได้อย่างเดียว ไม่อนุญาตแก้บัญชีหรือ Cache"
        if code == "LOCAL_READ_ONLY" else
        "ฟีเจอร์นี้ต้องใช้ Live GEE ซึ่งยังไม่เปิดใน Local Demo ไม่มีการคำนวณหรือสร้างผลแทน")
    return HTTPException(503, detail={"code": code, "message": message, "fields": []})


class ReadOnlyLocalTransport(httpx.BaseTransport):
    """Deny DML/RPC/redirects/remote targets before any network I/O."""
    def __init__(self, attest, inner=None):
        self.attest = attest
        self.inner = inner or httpx.HTTPTransport(retries=0)

    def handle_request(self, request):
        url = request.url
        if (url.scheme != "http" or url.host != "127.0.0.1" or url.port != 55421
                or url.userinfo or url.fragment or request.method != "GET"
                or url.path not in {"/auth/v1/user", *("/rest/v1/" + t for t in TABLES)}):
            raise dependency_error("LOCAL_READ_ONLY")
        self.attest()
        return self.inner.handle_request(request)

    def close(self):
        self.inner.close()


def _fresh_import_required():
    if any(name == prefix or name.startswith(prefix + ".")
            for name in sys.modules for prefix in LEGACY_MODULES):
        raise RuntimeError("LOCAL_LEGACY_REQUIRES_FRESH_PROCESS")


def cached_ndvi_handler(dependencies):
    """Read one annual row from the local cache: no GEE, no write, no staleness delete.

    A row this version would not trust (older cache_version, such as fixtures) or a missing
    row would need GEE, so both keep the demo's existing LOCAL_GEE_BLOCKED answer.
    """
    async def handler(request):
        await run_in_threadpool(dependencies.require_user, request.headers.get("authorization"))
        province = request.path_params["province_name"]
        raw_year = request.query_params.get("year")
        try:
            year = dependencies.resolve_year(int(raw_year) if raw_year is not None else None)
        except ValueError:
            raise HTTPException(422, detail="year ต้องเป็นตัวเลข") from None
        if not dependencies.YEAR_MIN <= year <= dependencies.YEAR_MAX:
            raise HTTPException(422, detail=f"year ต้องอยู่ใน {dependencies.YEAR_MIN}–{dependencies.YEAR_MAX}")

        def read():
            dependencies.ensure_province(province)
            return dependencies.supa_call(lambda s: s.table("ndvi_annual").select("*")
                .eq("province", province).eq("year", year).limit(1).execute()).data

        rows = await run_in_threadpool(read)
        row = rows[0] if rows else None
        if row is None or row.get("cache_version", 1) < dependencies.CURRENT_CACHE_VERSION:
            error = dependency_error()
            return JSONResponse({"detail": error.detail}, status_code=error.status_code)
        body = {k: v for k, v in row.items() if k not in {"id", "created_at", "cache_version"}}
        return JSONResponse({**body, "province": province, "year": year,
            "from_cache": True, "cached_at": row.get("created_at")})
    return handler


def mount_legacy(app, legacy, dependencies):
    mounted = []
    for route in legacy.app.routes:
        if not isinstance(route, APIRoute) or route.path == "/gis" or route.path.startswith("/gis/"):
            continue
        item = copy.copy(route)
        identity = (route.path, route.endpoint.__module__, route.endpoint.__name__)
        cached = route.methods == {"GET"} and identity == CACHED_NDVI_ROUTE
        allowed = route.methods == {"GET"} and identity in READ_ROUTES
        if cached:
            item.app = request_response(cached_ndvi_handler(dependencies))
        elif not allowed:
            async def blocked(request):
                # Same original Auth verification; no header/body actor authority.
                await run_in_threadpool(dependencies.require_user, request.headers.get("authorization"))
                code = "LOCAL_GEE_BLOCKED" if request.method == "GET" or request.url.path in {
                    "/analysis/custom-area", "/recommend/custom-area"} else "LOCAL_READ_ONLY"
                error = dependency_error(code)
                return JSONResponse({"detail": error.detail}, status_code=error.status_code)
            item.app = request_response(blocked)
        app.router.routes.append(item)
        mounted.append({"path": route.path, "methods": sorted(route.methods),
            "mode": "read_only_cache" if cached else "read_only" if allowed else "blocked_local_dependency"})
    app.state.local_legacy_routes = mounted


def create_app(local):
    """Called once, in the existing demo process, after strict target attestation."""
    _fresh_import_required()
    local.attest()
    local.gis_runtime.require_ready()
    _, service_key = local.local_keys()
    clients = []

    @lru_cache(maxsize=1)
    def read_client():
        transport = httpx.Client(trust_env=False, follow_redirects=False, timeout=10,
            transport=ReadOnlyLocalTransport(local.attest))
        clients.append(transport)
        return create_client(LOCAL_URL, service_key, ClientOptions(auto_refresh_token=False,
            persist_session=False, httpx_client=transport, postgrest_client_timeout=10))

    # No inherited app config or credential paths; dotenv is suppressed BEFORE
    # dependencies/router/main imports. The original HS256 Auth fallback calls
    # get_user on this fixed local client; no JWT/Auth implementation is changed.
    safe_env = {k: v for k, v in os.environ.items() if k.upper() in {
        "PATH", "SYSTEMROOT", "SYSTEMDRIVE", "TEMP", "TMP", "COMSPEC", "PATHEXT"}}
    with patch.dict(os.environ, safe_env, clear=True), patch("dotenv.load_dotenv", return_value=False):
        dependencies = importlib.import_module("dependencies")
        dependencies.get_supabase = read_client
        legacy = importlib.import_module("main")
    if dependencies.SUPABASE_URL is not None or legacy.GEE_PROJECT is not None:
        raise RuntimeError("LOCAL_LEGACY_INHERITED_CONFIG_REJECTED")
    from gis_app import create_app as gis_app
    app = gis_app(local.gis_runtime, ldd_store=local.store, geotiff_store=local.geotiff_store,
        prepared_store=getattr(local, 'prepared_store', None))
    app.state.gis_ldd_publication = getattr(local, 'publication', None)
    app.state.gis_geotiff_prepared_store = getattr(local, 'geotiff_prepared_store', None)
    app.state.gis_geotiff_publication = getattr(local,'geotiff_publication',None)
    mount_legacy(app, legacy, dependencies)

    previous_lifespan = app.router.lifespan_context
    @asynccontextmanager
    async def local_lifespan(application):
        try:
            async with previous_lifespan(application) as state:
                yield state
        finally:
            for client in clients:
                client.close()
    app.router.lifespan_context = local_lifespan
    return app
