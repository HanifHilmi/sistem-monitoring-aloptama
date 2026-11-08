"""FastAPI application: REST /api/v1, /health (liveness), /ready (database + migrations)."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException

from simola.api.deps import ApiError, problem_response
from simola.api.routers import (
    admin,
    admin_ops,
    alarms,
    auth,
    dq,
    exports,
    flags,
    internal,
    public,
    records,
    reports,
)
from simola.api.security import principal
from simola.core.config import get_settings
from simola.core.db import get_engine, set_engine
from simola.core.logging import setup_logging
from simola.migrations.runner import pending

logger = logging.getLogger(__name__)
_problem = problem_response


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    setup_logging(settings.log_level)
    yield
    engine = get_engine()
    await engine.dispose()
    set_engine(None)


async def session_first(request: Request) -> None:
    """Looks up the signed-in user before a route takes its database connection.

    The lookup uses a short connection of its own and caches the result for the request. Done later, inside a
    route that already holds a connection, a page load of ~20 signed-in requests can leave every pooled connection
    waiting for a second one until the pool times out (30 s). Done first, a request never holds two at once.
    """
    await principal(request)


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="SIMOLA API",
        version=settings.version,
        lifespan=lifespan,
        docs_url=None,  # interactive docs are Admin-only (API-02); enabled with accounts in R2
        redoc_url=None,
        openapi_url="/api/v1/openapi.json" if settings.environment != "production" else None,
        dependencies=[Depends(session_first)],  # before every route's own dependencies
    )

    @app.exception_handler(ApiError)
    async def _api_error(_req: Request, exc: ApiError) -> JSONResponse:
        return _problem(exc.status_code, exc.code, str(exc.detail))

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_req: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = "not_found" if exc.status_code == 404 else "http_error"
        return _problem(exc.status_code, code, str(exc.detail))

    @app.exception_handler(RequestValidationError)
    async def _validation(_req: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [{"loc": list(e.get("loc", [])), "msg": e.get("msg")} for e in exc.errors()]
        return _problem(422, "validation_error", "Request validation failed", errors)

    @app.exception_handler(Exception)
    async def _unhandled(_req: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled error", exc_info=exc)
        return _problem(500, "internal_error", "Internal server error")  # never leak internals (NFR-SEC-007)

    @app.get("/health", tags=["health"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready", tags=["health"])
    async def ready() -> JSONResponse:
        try:
            async with get_engine().connect() as conn:
                await conn.execute(text("SELECT 1"))
            missing = await pending(settings.asyncpg_dsn)
        except Exception:
            return _problem(503, "not_ready", "Database unavailable")
        if missing:
            return _problem(503, "not_ready", "Migrations pending", missing)
        return JSONResponse({"status": "ready"})

    app.include_router(public.router)
    app.include_router(internal.router)
    app.include_router(auth.router)
    app.include_router(admin.router)
    app.include_router(admin_ops.router)
    app.include_router(flags.router)
    app.include_router(flags.admin_router)
    app.include_router(dq.router)
    app.include_router(dq.admin_router)
    app.include_router(records.router)
    app.include_router(records.admin_router)
    app.include_router(alarms.router)
    app.include_router(alarms.admin_router)
    app.include_router(reports.router)
    app.include_router(exports.router)
    return app


# Run with: uvicorn --factory simola.api.app:create_app
