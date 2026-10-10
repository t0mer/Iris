"""FastAPI app factory."""

import asyncio
import hmac
from collections.abc import AsyncIterator, MutableMapping
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from loguru import logger
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Receive, Scope, Send

from app.api import (
    alerts,
    auth,
    classify,
    database,
    instances,
    jobs,
    learning,
    media,
    messages,
    operations,
    pairing,
    setup,
    stats,
    system,
    users,
)
from app.api import (
    events as events_api,
)
from app.api import settings as settings_api
from app.audit import AuditMiddleware
from app.audit import install as install_audit
from app.config import get_settings
from app.db import events_hook
from app.db.engine import make_engine, make_session_factory
from app.db.migrate import upgrade_head
from app.db.models import User
from app.db.url import DbConfigError
from app.db.url import resolve as resolve_database
from app.events import bus
from app.ingest import webhooks
from app.jobs.handlers import Deps
from app.jobs.worker import WorkerPool
from app.logging import setup_logging
from app.metrics import render as render_metrics
from app.providers import Providers
from app.security.auth import admin_user, bootstrap_admin
from app.version import VERSION

STATIC_DIR = Path(__file__).parent / "static"
_CSP = (
    "default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; "
    "img-src 'self' data:; style-src 'self' 'unsafe-inline'"
)
_DOCS_CSP = (
    "default-src 'self'; img-src 'self' data: https://fastapi.tiangolo.com; "
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net"
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    setup_logging(settings.log_level, settings.log_json)
    try:
        db_config, db_source = resolve_database(settings)
    except DbConfigError as exc:
        logger.error("{}", exc)
        raise
    logger.info("database: {} ({})", db_config.describe(), db_source)
    # Bring the schema up to date (cheap when it already is), so a database chosen in Settings
    # works on the first start, with or without the container entrypoint.
    try:
        await asyncio.to_thread(upgrade_head)
    except Exception as exc:
        # Starting on another database would hide the data, so stop and say what to do.
        logger.error(
            "cannot reach {} ({}). Start the database, or delete database.json in the data "
            "folder to use SQLite again.",
            db_config.describe(),
            exc.__class__.__name__,
        )
        raise
    events_hook.install()
    install_audit()
    engine = make_engine(config=db_config)
    app.state.engine = engine
    app.state.db_running, app.state.db_source = db_config.with_defaults(), db_source
    app.state.session_factory = make_session_factory(engine)
    async with app.state.session_factory() as session:
        await bootstrap_admin(session, settings)
        from app.alerts.bootstrap import bootstrap_notifications

        await bootstrap_notifications(session, settings)
        from app.settings_store import reload_runtime_settings

        await reload_runtime_settings(session)
        settings = get_settings()
        if settings.local_safety_mode:
            from app.legacy_review import quarantine_legacy_unknowns
            from app.settings_store import get_setting, set_setting

            if not await get_setting(session, "alerts.review_notify_since"):
                await set_setting(
                    session, "alerts.review_notify_since", datetime.now(UTC).isoformat()
                )
            await quarantine_legacy_unknowns(session)
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
    pairing_cleanup = asyncio.create_task(pairing.cleanup_loop(app.state.session_factory))
    yield
    pairing_cleanup.cancel()
    await asyncio.gather(pairing_cleanup, return_exceptions=True)
    await bus.close_all()  # end every open live stream so shutdown is not held up
    await pool.stop()
    await providers.aclose()
    await engine.dispose()


class SecurityHeaders:
    """Adds the security headers to every response. Pure ASGI, so streaming responses (live
    updates) are passed through untouched and a closed connection reaches the endpoint at once."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope["path"]

        async def send_with_headers(message: MutableMapping[str, Any]) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                if "Content-Security-Policy" not in headers:  # kept media sets a stricter one
                    headers["Content-Security-Policy"] = _DOCS_CSP if path == "/api/docs" else _CSP
                headers["X-Content-Type-Options"] = "nosniff"
                headers["Referrer-Policy"] = "no-referrer"
                # Only the authenticated QR viewer may be embedded by this Iris origin.
                qr_frame = (
                    path.startswith("/pairing/qr/") and path.removeprefix("/pairing/qr/").isdigit()
                )
                headers["X-Frame-Options"] = "SAMEORIGIN" if qr_frame else "DENY"
                if qr_frame:
                    headers["Content-Security-Policy"] = _CSP + "; frame-ancestors 'self'"
                    headers["Cache-Control"] = "no-store"
            await send(message)

        await self.app(scope, receive, send_with_headers)


def create_app() -> FastAPI:
    app = FastAPI(
        title="Iris",
        version=VERSION,
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,  # served below, behind the login, like /api/docs
    )

    app.add_middleware(SecurityHeaders)
    app.add_middleware(AuditMiddleware)

    app.include_router(system.router)
    app.include_router(setup.router)
    app.include_router(auth.router)
    app.include_router(users.router)
    app.include_router(instances.router)
    app.include_router(pairing.router)
    app.include_router(messages.router)
    app.include_router(jobs.router)
    app.include_router(alerts.router)
    app.include_router(stats.router)
    app.include_router(settings_api.router)
    app.include_router(classify.router)
    app.include_router(learning.router)
    app.include_router(database.router)
    app.include_router(media.router)
    app.include_router(events_api.router)
    app.include_router(operations.router)
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
    async def openapi_schema(_: Annotated[User, Depends(admin_user)]) -> JSONResponse:
        return JSONResponse(app.openapi())

    @app.get("/api/docs", include_in_schema=False)
    async def docs(_: Annotated[User, Depends(admin_user)]) -> HTMLResponse:
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
        if path.startswith("assets/"):
            # A tab opened before an update may request an obsolete hashed chunk.
            # HTML is not a valid JavaScript response; do not hide this as SPA routing.
            raise HTTPException(status_code=404)
        index = STATIC_DIR / "index.html"
        if index.is_file():
            return FileResponse(index, headers={"Cache-Control": "no-store"})
        return JSONResponse({"detail": "UI not built"}, status_code=404)

    return app


app = create_app()
