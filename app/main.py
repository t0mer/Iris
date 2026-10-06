"""FastAPI app factory."""

import asyncio
import hmac
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from loguru import logger

from app.api import alerts, auth, classify, database, instances, jobs, messages, stats, system
from app.api import settings as settings_api
from app.config import get_settings
from app.db.engine import make_engine, make_session_factory
from app.db.migrate import upgrade_head
from app.db.models import User
from app.db.url import resolve as resolve_database
from app.ingest import webhooks
from app.jobs.handlers import Deps
from app.jobs.worker import WorkerPool
from app.logging import setup_logging
from app.metrics import render as render_metrics
from app.providers import Providers
from app.retention import retention_loop
from app.security.auth import bootstrap_admin, current_user
from app.version import VERSION

STATIC_DIR = Path(__file__).parent / "static"
_CSP = "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'"
_DOCS_CSP = (
    "default-src 'self'; img-src 'self' data: https://fastapi.tiangolo.com; "
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net"
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    setup_logging(settings.log_level, settings.log_json)
    db_config, db_source = resolve_database(settings)
    logger.info("database: {} ({})", db_config.describe(), db_source)
    # Bring the schema up to date (cheap when it already is), so a database chosen in Settings
    # works on the first start, with or without the container entrypoint.
    await asyncio.to_thread(upgrade_head)
    engine = make_engine(config=db_config)
    app.state.engine = engine
    app.state.db_running, app.state.db_source = db_config.with_defaults(), db_source
    app.state.session_factory = make_session_factory(engine)
    async with app.state.session_factory() as session:
        await bootstrap_admin(session, settings)
    providers = Providers()
    pool = WorkerPool(
        Deps(
            app.state.session_factory,
            providers,
            settings.key_bytes,
            settings.data_dir,
            settings.public_base_url,
        ),
        settings.workers,
    )
    app.state.workers = pool
    await pool.start()
    cleanup = (
        asyncio.create_task(retention_loop(app.state.session_factory)) if settings.workers else None
    )
    yield
    if cleanup is not None:
        cleanup.cancel()
        await asyncio.gather(cleanup, return_exceptions=True)
    await pool.stop()
    await providers.aclose()
    await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Iris",
        version=VERSION,
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,  # served below, behind the login, like /api/docs
    )

    @app.middleware("http")
    async def security_headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            _DOCS_CSP if request.url.path == "/api/docs" else _CSP
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        return response

    app.include_router(system.router)
    app.include_router(auth.router)
    app.include_router(instances.router)
    app.include_router(messages.router)
    app.include_router(jobs.router)
    app.include_router(alerts.router)
    app.include_router(stats.router)
    app.include_router(settings_api.router)
    app.include_router(classify.router)
    app.include_router(database.router)
    app.include_router(webhooks.router)

    @app.get("/metrics", include_in_schema=False)
    async def metrics(request: Request) -> Response:
        # Open by default (Prometheus scrape); IRIS_METRICS_TOKEN makes it require a bearer token.
        token = get_settings().metrics_token
        if token and not hmac.compare_digest(
            request.headers.get("authorization", ""), f"Bearer {token}"
        ):
            raise HTTPException(status_code=401, headers={"WWW-Authenticate": "Bearer"})
        async with request.app.state.session_factory() as db:
            body = await render_metrics(db)
        return Response(body, media_type="text/plain; version=0.0.4; charset=utf-8")

    @app.get("/api/openapi.json", include_in_schema=False)
    async def openapi_schema(_: Annotated[User, Depends(current_user)]) -> JSONResponse:
        return JSONResponse(app.openapi())

    @app.get("/api/docs", include_in_schema=False)
    async def docs(_: Annotated[User, Depends(current_user)]) -> HTMLResponse:
        return get_swagger_ui_html(openapi_url="/api/openapi.json", title="Iris API")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str) -> Response:
        if path.startswith(("api/", "webhooks/", "metrics")) or path in ("api", "webhooks"):
            raise HTTPException(status_code=404)
        try:
            candidate = (STATIC_DIR / path).resolve()
            is_asset = (
                bool(path) and candidate.is_file() and STATIC_DIR.resolve() in candidate.parents
            )
        except ValueError:  # embedded NUL byte
            raise HTTPException(status_code=404) from None
        if is_asset:
            return FileResponse(candidate)
        index = STATIC_DIR / "index.html"
        if index.is_file():
            return FileResponse(index)
        return JSONResponse({"detail": "UI not built"}, status_code=404)

    return app


app = create_app()
