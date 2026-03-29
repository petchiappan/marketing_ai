"""FastAPI application entry point."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config.logging_config import setup_logging
from app.api.enrichment_routes import router as enrichment_router
from app.api.admin_routes import router as admin_router
from app.config.settings import settings

logger = logging.getLogger(__name__)

# Initialise file-based logging (logs/marketing_ai_YYYY-MM-DD.log)
setup_logging()

def _disable_ssl_verification():
    import os
    import httpx
    _orig_client = httpx.Client
    _orig_async = httpx.AsyncClient

    _proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")

    class NoVerifyClient(_orig_client):
        def __init__(self, *args, **kwargs):
            kwargs["verify"] = False
            if _proxy and "proxy" not in kwargs:
                kwargs["proxy"] = _proxy
            super().__init__(*args, **kwargs)

    class NoVerifyAsyncClient(_orig_async):
        def __init__(self, *args, **kwargs):
            kwargs["verify"] = False
            if _proxy and "proxy" not in kwargs:
                kwargs["proxy"] = _proxy
            super().__init__(*args, **kwargs)

    httpx.Client = NoVerifyClient
    httpx.AsyncClient = NoVerifyAsyncClient

if settings.disable_ssl_verification:
    _disable_ssl_verification()


async def _init_db() -> None:
    """Create tables and seed the default admin user.

    Isolated into its own coroutine so it can be wrapped with asyncio.wait_for.
    """
    from app.db.session import engine, async_session_factory
    from app.db.models import Base
    from app.db import repository as repo
    from app.auth.local_auth import hash_password

    # Ensure all tables exist (idempotent)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Seed default admin user (try/except handles race condition with multiple workers)
    async with async_session_factory() as db:
        existing = await repo.get_user_by_email(db, settings.default_admin_email)
        if not existing:
            try:
                await repo.create_admin_user(
                    db,
                    email=settings.default_admin_email,
                    username="admin",
                    display_name="Default Admin",
                    password_hash=hash_password(settings.default_admin_password),
                    auth_provider="local",
                    role="admin",
                )
                await db.commit()
            except Exception:
                await db.rollback()  # Another worker already inserted it


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan – runs on startup and shutdown."""
    # Attempt database initialisation with a hard timeout so the app can still
    # start (and pass healthchecks) even when the database is slow or
    # temporarily unavailable.
    try:
        await asyncio.wait_for(_init_db(), timeout=10)
        logger.info("Database initialisation completed successfully.")
    except asyncio.TimeoutError:
        logger.warning(
            "Database initialisation timed out after 10 s – "
            "the app will start without it and retry on first request."
        )
    except Exception as exc:
        logger.warning(
            "Database initialisation failed (%s: %s) – "
            "the app will start without it and retry on first request.",
            type(exc).__name__,
            exc,
        )

    yield

    # Shutdown: dispose engine
    from app.db.session import engine
    await engine.dispose()


app = FastAPI(
    title="Marketing AI – Lead Enrichment Agent",
    description="Multi-agent lead enrichment system with admin control center",
    version="0.1.0",
    lifespan=lifespan,
)

import os
os.environ["SSL_VERIFY"] = "False"

# ── Mount static files ──
static_dir = Path(__file__).parent / "admin" / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# ── Register routers ──
app.include_router(enrichment_router)
app.include_router(admin_router)


@app.get("/health", tags=["infra"])
async def health():
    """Health check endpoint for Railway / load balancer."""
    return {"status": "ok"}


@app.get("/")
async def root():
    return {
        "service": "Marketing AI – Lead Enrichment Agent",
        "version": "0.1.0",
        "docs": "/docs",
        "admin": "/admin/login",
    }
