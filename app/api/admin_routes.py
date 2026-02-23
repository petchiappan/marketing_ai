"""Admin Control Center API – authentication, tool config, agent monitoring."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_admin, require_editor_or_above
from app.auth.local_auth import create_access_token, hash_password, verify_password
from app.config.settings import settings
from app.db import repository as repo
from app.db.models import AdminUser
from app.db.session import get_db

router = APIRouter(tags=["admin"])


# ────────────────────────────────────────────────────────────────────────────
# Static page serving
# ────────────────────────────────────────────────────────────────────────────

@router.get("/admin/login", response_class=HTMLResponse)
async def login_page():
    """Serve the admin login page."""
    with open("app/admin/templates/login.html", "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())


@router.get("/admin", response_class=HTMLResponse)
async def admin_dashboard(user: AdminUser = Depends(get_current_user)):
    """Serve the main admin dashboard."""
    with open("app/admin/templates/dashboard.html", "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())


# ────────────────────────────────────────────────────────────────────────────
# Authentication endpoints
# ────────────────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    email: str
    password: str


@router.post("/admin/auth/login")
async def local_login(body: LoginRequest, response: Response, db: AsyncSession = Depends(get_db)):
    """Authenticate with email + password and set JWT cookie."""
    user = await repo.get_user_by_email(db, body.email)
    if not user or not user.password_hash or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account deactivated")

    token = create_access_token({"sub": user.email, "role": user.role})
    await repo.update_user_login(db, user.id)

    response = JSONResponse(content={"message": "Login successful", "role": user.role})
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        secure=False,  # Set True in production with HTTPS
        samesite="lax",
        max_age=settings.jwt_expire_hours * 3600,
    )
    return response


@router.get("/admin/auth/azure")
async def azure_login(request: Request):
    """Redirect to Azure AD for OIDC authentication."""
    from app.auth.oidc_auth import get_auth_url

    if not settings.azure_ad_tenant_id:
        raise HTTPException(status_code=501, detail="Azure AD not configured")

    auth_url, flow = get_auth_url()
    # Store flow in session (simplified – use server-side session in production)
    request.state.azure_flow = flow
    return RedirectResponse(url=auth_url)


@router.get("/admin/auth/azure/callback")
async def azure_callback(
    request: Request,
    code: str = Query(...),
    state: str = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Handle Azure AD OIDC callback – exchange code for tokens."""
    from app.auth.oidc_auth import exchange_code_for_token, get_user_info

    flow = getattr(request.state, "azure_flow", None)
    if not flow:
        raise HTTPException(status_code=400, detail="Invalid auth flow")

    result = exchange_code_for_token(flow, dict(request.query_params))
    if not result:
        raise HTTPException(status_code=401, detail="Azure AD authentication failed")

    user_info = get_user_info(result)
    user = await repo.get_user_by_email(db, user_info["email"])

    # Auto-provision first-time Azure AD user
    if not user:
        user = await repo.create_admin_user(
            db,
            email=user_info["email"],
            display_name=user_info["display_name"],
            azure_oid=user_info["azure_oid"],
            auth_provider="azure_ad",
            role="viewer",
        )

    token = create_access_token({"sub": user.email, "role": user.role})
    await repo.update_user_login(db, user.id)

    response = RedirectResponse(url="/admin")
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        secure=False,
        samesite="lax",
        max_age=settings.jwt_expire_hours * 3600,
    )
    return response


@router.post("/admin/auth/logout")
async def logout(response: Response):
    """Clear the JWT cookie."""
    response = JSONResponse(content={"message": "Logged out"})
    response.delete_cookie("access_token")
    return response


@router.get("/admin/auth/me")
async def current_user(user: AdminUser = Depends(get_current_user)):
    """Return the current authenticated user's info."""
    return {
        "id": str(user.id),
        "email": user.email,
        "display_name": user.display_name,
        "role": user.role,
        "auth_provider": user.auth_provider,
    }


# ────────────────────────────────────────────────────────────────────────────
# Tool Configuration CRUD
# ────────────────────────────────────────────────────────────────────────────

class ToolConfigUpdate(BaseModel):
    display_name: str | None = None
    agent_name: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    auth_type: str | None = None
    extra_headers: dict | None = None
    extra_config: dict | None = None
    is_enabled: bool | None = None


@router.get("/admin/api/tools")
async def list_tools(
    user: AdminUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all configured tools."""
    tools = await repo.list_tool_configs(db)
    return [
        {
            "tool_name": t.tool_name,
            "display_name": t.display_name,
            "agent_name": t.agent_name,
            "base_url": t.base_url,
            "auth_type": t.auth_type,
            "is_enabled": t.is_enabled,
            "health_status": t.health_status,
            "last_health_check": t.last_health_check.isoformat() if t.last_health_check else None,
            "has_api_key": bool(t.api_key_encrypted),
        }
        for t in tools
    ]


@router.put("/admin/api/tools/{tool_name}")
async def update_tool(
    tool_name: str,
    body: ToolConfigUpdate,
    user: AdminUser = Depends(require_editor_or_above),
    db: AsyncSession = Depends(get_db),
):
    """Update a tool configuration."""
    update_data: dict[str, Any] = {}
    if body.display_name is not None:
        update_data["display_name"] = body.display_name
    if body.agent_name is not None:
        update_data["agent_name"] = body.agent_name
    if body.base_url is not None:
        update_data["base_url"] = body.base_url
    if body.auth_type is not None:
        update_data["auth_type"] = body.auth_type
    if body.extra_headers is not None:
        update_data["extra_headers"] = body.extra_headers
    if body.extra_config is not None:
        update_data["extra_config"] = body.extra_config
    if body.is_enabled is not None:
        update_data["is_enabled"] = body.is_enabled
    if body.api_key is not None:
        # In production, encrypt before storing:
        # from cryptography.fernet import Fernet
        # f = Fernet(settings.tool_secret_encryption_key)
        # update_data["api_key_encrypted"] = f.encrypt(body.api_key.encode()).decode()
        update_data["api_key_encrypted"] = body.api_key  # TODO: encrypt
    update_data["updated_by"] = user.email

    tool = await repo.upsert_tool_config(db, tool_name, **update_data)
    return {"message": f"Tool '{tool_name}' updated", "tool_name": tool.tool_name}


@router.post("/admin/api/tools/{tool_name}/health")
async def check_tool_health(
    tool_name: str,
    user: AdminUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Trigger a health check for a specific tool."""
    tool = await repo.get_tool_config(db, tool_name)
    if not tool:
        raise HTTPException(status_code=404, detail="Tool not found")

    # Placeholder health check – ping the base_url
    health = "unknown"
    if tool.base_url:
        import httpx

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(tool.base_url)
                health = "healthy" if resp.status_code < 500 else "degraded"
        except Exception:
            health = "down"

    await repo.upsert_tool_config(
        db,
        tool_name,
        health_status=health,
        last_health_check=datetime.utcnow(),
    )
    return {"tool_name": tool_name, "health_status": health}


# ────────────────────────────────────────────────────────────────────────────
# Rate Limits
# ────────────────────────────────────────────────────────────────────────────

class RateLimitUpdate(BaseModel):
    requests_per_min: int | None = None
    burst_limit: int | None = None
    daily_quota: int | None = None
    is_enabled: bool | None = None


@router.get("/admin/api/rate-limits")
async def list_rate_limits(
    user: AdminUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all rate limit configurations."""
    limits = await repo.list_rate_limits(db)
    return [
        {
            "provider_name": rl.provider_name,
            "requests_per_min": rl.requests_per_min,
            "burst_limit": rl.burst_limit,
            "daily_quota": rl.daily_quota,
            "is_enabled": rl.is_enabled,
        }
        for rl in limits
    ]


@router.put("/admin/api/rate-limits/{provider}")
async def update_rate_limit(
    provider: str,
    body: RateLimitUpdate,
    user: AdminUser = Depends(require_editor_or_above),
    db: AsyncSession = Depends(get_db),
):
    """Update rate limit settings for a provider."""
    update_data: dict[str, Any] = {}
    if body.requests_per_min is not None:
        update_data["requests_per_min"] = body.requests_per_min
    if body.burst_limit is not None:
        update_data["burst_limit"] = body.burst_limit
    if body.daily_quota is not None:
        update_data["daily_quota"] = body.daily_quota
    if body.is_enabled is not None:
        update_data["is_enabled"] = body.is_enabled
    update_data["updated_by"] = user.email

    rl = await repo.update_rate_limit(db, provider, **update_data)
    if not rl:
        raise HTTPException(status_code=404, detail="Provider not found")
    return {"message": f"Rate limit for '{provider}' updated"}


# ────────────────────────────────────────────────────────────────────────────
# LLM Token Usage
# ────────────────────────────────────────────────────────────────────────────

@router.get("/admin/api/token-usage")
async def get_token_usage(
    days: int = 30,
    user: AdminUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get aggregated LLM token usage statistics."""
    summary = await repo.get_token_usage_summary(db, days=days)
    return summary


# ────────────────────────────────────────────────────────────────────────────
# Agent Runs
# ────────────────────────────────────────────────────────────────────────────

@router.get("/admin/api/agent-runs")
async def list_agent_runs(
    limit: int = 50,
    offset: int = 0,
    status_filter: str | None = None,
    agent_name: str | None = None,
    request_id: str | None = None,
    user: AdminUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List agent runs with optional filters."""
    runs = await repo.list_agent_runs(
        db, limit=limit, offset=offset, status=status_filter, agent_name=agent_name,
        request_id=uuid.UUID(request_id) if request_id else None,
    )
    return [
        {
            "id": str(r.id),
            "request_id": str(r.request_id),
            "agent_name": r.agent_name,
            "status": r.status,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "completed_at": r.completed_at.isoformat() if r.completed_at else None,
            "duration_ms": r.duration_ms,
            "error_type": r.error_type,
            "error_message": r.error_message,
        }
        for r in runs
    ]


@router.get("/admin/api/agent-runs/{run_id}")
async def get_agent_run_detail(
    run_id: uuid.UUID,
    user: AdminUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get detailed agent run including traceback for debugging."""
    run = await repo.get_agent_run(db, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Agent run not found")
    return {
        "id": str(run.id),
        "request_id": str(run.request_id),
        "agent_name": run.agent_name,
        "status": run.status,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "duration_ms": run.duration_ms,
        "input_summary": run.input_summary,
        "output_summary": run.output_summary,
        "error_type": run.error_type,
        "error_message": run.error_message,
        "error_traceback": run.error_traceback,
        "retry_count": run.retry_count,
        "metadata": run.metadata_,
    }


# ────────────────────────────────────────────────────────────────────────────
# Dashboard KPIs
# ────────────────────────────────────────────────────────────────────────────

@router.get("/admin/api/dashboard-kpis")
async def dashboard_kpis(
    user: AdminUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return key metrics for the admin dashboard home."""
    from sqlalchemy import func, select
    from app.db.models import EnrichmentRequest, AgentRun, LLMTokenUsage, ToolConfig

    # Total requests
    total_requests = (await db.execute(select(func.count(EnrichmentRequest.id)))).scalar() or 0

    # Requests by status
    status_counts = {}
    rows = await db.execute(
        select(EnrichmentRequest.status, func.count())
        .group_by(EnrichmentRequest.status)
    )
    for row in rows:
        status_counts[row[0]] = row[1]

    # Active agent runs
    active_runs = (
        await db.execute(
            select(func.count(AgentRun.id)).where(AgentRun.status.in_(["queued", "running"]))
        )
    ).scalar() or 0

    # Total tokens (last 24h)
    tokens_24h = (
        await db.execute(
            select(func.coalesce(func.sum(LLMTokenUsage.total_tokens), 0)).where(
                LLMTokenUsage.created_at >= datetime.utcnow() - timedelta(hours=24)
            )
        )
    ).scalar() or 0

    # Tool health summary
    tools = await repo.list_tool_configs(db)
    health_summary = {
        "healthy": sum(1 for t in tools if t.health_status == "healthy"),
        "degraded": sum(1 for t in tools if t.health_status == "degraded"),
        "down": sum(1 for t in tools if t.health_status == "down"),
        "unknown": sum(1 for t in tools if t.health_status == "unknown"),
    }

    return {
        "total_requests": total_requests,
        "status_counts": status_counts,
        "active_agent_runs": active_runs,
        "tokens_last_24h": tokens_24h,
        "tool_health": health_summary,
        "llm": {
            "provider": settings.llm_provider,
            "model": settings.llm_model,
            "identifier": settings.llm_identifier,
        },
    }


# ────────────────────────────────────────────────────────────────────────────
# Trigger Enrichment
# ────────────────────────────────────────────────────────────────────────────

@router.post("/admin/api/trigger-enrichment/{request_id}", status_code=status.HTTP_202_ACCEPTED)
async def trigger_enrichment(
    request_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    user: AdminUser = Depends(require_editor_or_above),
    db: AsyncSession = Depends(get_db),
):
    """Manually trigger enrichment processing for a queued request."""
    req = await repo.get_request(db, request_id)
    if not req:
        raise HTTPException(status_code=404, detail="Enrichment request not found")
    if req.status not in ("pending", "failed"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot trigger enrichment for request with status '{req.status}'. Only 'pending' or 'failed' requests can be triggered.",
        )

    # Mark as processing immediately
    await repo.update_request_status(db, request_id, "processing")
    await db.commit()

    # Kick off the pipeline in the background
    from app.agents.pipeline import run_enrichment_pipeline

    background_tasks.add_task(run_enrichment_pipeline, request_id)

    return {
        "message": f"Enrichment triggered for '{req.company_name}'",
        "request_id": str(request_id),
        "status": "processing",
    }
