"""Safe local GIS app factory. Does not import legacy startup, dotenv or GEE."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

from gis_runtime import GISRuntime, read_proof_scope
from gis_service import GisService
from routers.gis import router
from gis_ldd_storage import UPLOAD_PATH
from gis_geotiff_storage import UPLOAD_PATH as GEOTIFF_UPLOAD_PATH
from routers.ldd_prepare import router as ldd_prepare_router
from routers.ldd_publication import router as ldd_publication_router
from routers.geotiff_prepare import router as geotiff_prepare_router
from routers.geotiff_publication import router as geotiff_publication_router
from routers.gee_mock import router as gee_mock_router


def gis_rate_limit_handler(request, exception):
    if request.url.path == "/gis" or request.url.path.startswith("/gis/"):
        return JSONResponse({"detail": {"code": "GIS_RATE_LIMITED", "message": "Too many GIS requests", "fields": []}},
            status_code=429, headers={"Retry-After": "60"})
    # Preserve the original handler for every existing endpoint.
    return _rate_limit_exceeded_handler(request, exception)


class GISBodyLimit:
    def __init__(self, app, limit=65536):
        self.app, self.limit = app, limit

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not (scope["path"] == "/gis" or scope["path"].startswith("/gis/")):
            return await self.app(scope, receive, send)
        if scope.get("method") == "POST" and (UPLOAD_PATH.fullmatch(scope["path"]) or GEOTIFF_UPLOAD_PATH.fullmatch(scope["path"])):
            # Upload route authorizes before reading. It streams under its own
            # byte/quota/time limits; never buffer a ZIP in the JSON middleware.
            return await self.app(scope, receive, send)
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if len(body) > self.limit:
                return await JSONResponse({"detail": {"code": "GIS_INVALID_PAYLOAD", "message": "Request body is too large", "fields": []}}, status_code=422)(scope, receive, send)
            if not message.get("more_body", False):
                break
        used = False
        async def replay():
            nonlocal used
            if not used:
                used = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()
        return await self.app(scope, replay, send)


class GISReadProofScope:
    """One target proof per GET/HEAD /gis request (docs/gis/w5-ldd-publication-design.md 6.4).

    Each read request gets its own scope, removed when the request ends. Other methods (all mutations),
    other paths, workers and CLI code still prove the target before every Auth/SQL call.
    """
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not (scope["path"] == "/gis" or scope["path"].startswith("/gis/")):
            return await self.app(scope, receive, send)
        with read_proof_scope(scope.get("method") in ("GET", "HEAD")):
            return await self.app(scope, receive, send)


def mount_gis(app: FastAPI, runtime: GISRuntime | None = None, *, ldd_store=None, geotiff_store=None, prepared_store=None, gee_mock_catalog=None):
    app.state.gis_service = GisService(runtime or GISRuntime())
    app.state.gis_ldd_store = ldd_store
    app.state.gis_geotiff_store = geotiff_store
    app.state.gis_prepared_store = prepared_store
    app.state.gis_gee_mock = None
    if gee_mock_catalog is not None:
        from gis_gee_mock import LocalGeeMock
        app.state.gis_gee_mock = LocalGeeMock(app.state.gis_service, gee_mock_catalog)
    app.include_router(router)
    app.include_router(ldd_prepare_router)
    app.include_router(ldd_publication_router)
    app.include_router(geotiff_prepare_router)
    app.include_router(geotiff_publication_router)
    app.include_router(gee_mock_router)
    app.add_middleware(GISBodyLimit)
    app.add_middleware(GISReadProofScope)


def create_app(runtime: GISRuntime | None = None, *, rate_limit="60/minute", ldd_store=None, geotiff_store=None, prepared_store=None, gee_mock_catalog=None) -> FastAPI:
    app = FastAPI(title="Local synthetic GIS API", docs_url=None, redoc_url=None)
    app.state.limiter = Limiter(key_func=get_remote_address, default_limits=[rate_limit])
    app.add_exception_handler(RateLimitExceeded, gis_rate_limit_handler)
    app.add_middleware(SlowAPIMiddleware)
    mount_gis(app, runtime, ldd_store=ldd_store, geotiff_store=geotiff_store, prepared_store=prepared_store, gee_mock_catalog=gee_mock_catalog)
    app.add_middleware(CORSMiddleware,
        allow_origins=["http://127.0.0.1:3000", "http://localhost:3000"],
        allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key"])
    return app
