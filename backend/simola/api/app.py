"""FastAPI application: REST /api/v1, /health (liveness), /ready (database + migrations)."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException

from simola.api.deps import ApiError, problem_response
from simola.api.routers import admin, auth, internal, public
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


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="SIMOLA API",
        version=settings.version,
        lifespan=lifespan,
        docs_url=None,  # interactive docs are Admin-only (API-02); enabled with accounts in R2
        redoc_url=None,
        openapi_url="/api/v1/openapi.json" if settings.environment != "production" else None,
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
    return app


# Run with: uvicorn --factory simola.api.app:create_app
