"""FastAPI application entry point."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.enrichment_routes import router as enrichment_router
from app.api.admin_routes import router as admin_router
from app.config.settings import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan – runs on startup and shutdown."""
    from app.db.session import engine, async_session_factory
    from app.db.models import Base
    from app.db import repository as repo
    from app.auth.local_auth import hash_password

    # Startup: ensure all tables exist (idempotent)
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

    yield

    # Shutdown: dispose engine
    await engine.dispose()


app = FastAPI(
    title="Marketing AI – Lead Enrichment Agent",
    description="Multi-agent lead enrichment system with admin control center",
    version="0.1.0",
    lifespan=lifespan,
)

# ── Mount static files ──
static_dir = Path(__file__).parent / "admin" / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# ── Register routers ──
app.include_router(enrichment_router)
app.include_router(admin_router)


@app.get("/health", tags=["infra"])
async def health():
    """Health check endpoint for ECS / ALB target groups."""
    return {"status": "ok"}


@app.get("/")
async def root():
    return {
        "service": "Marketing AI – Lead Enrichment Agent",
        "version": "0.1.0",
        "docs": "/docs",
        "admin": "/admin/login",
    }
