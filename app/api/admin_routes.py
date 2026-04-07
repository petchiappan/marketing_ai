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
            "is_enabled": t.is_enabled,
            "health_status": t.health_status,
            "last_health_check": t.last_health_check.isoformat() if t.last_health_check else None,
            "env_configured": bool(settings.get_tool_config(t.tool_name).get("api_key")),
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
    if body.is_enabled is not None:
        update_data["is_enabled"] = body.is_enabled
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

    # Health check – resolve base_url from env then ping
    health = "unknown"
    env_config = settings.get_tool_config(tool_name)
    base_url = env_config.get("base_url")

    if base_url:
        import httpx
        try:
            async with httpx.AsyncClient(timeout=5.0, verify=False) as client:
                resp = await client.get(base_url)
                health = "healthy" if resp.status_code < 500 else "degraded"
        except Exception as e:
            print(f"An unexpected error occurred: {e}")
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
    pipeline_type: str | None = None,
    user: AdminUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List agent runs grouped by enrichment request (job)."""
    exclude_agent_name = None
    if pipeline_type == "crew":
        exclude_agent_name = "workflow_pipeline"
    elif pipeline_type == "workflow":
        agent_name = "workflow_pipeline"

    grouped = await repo.list_agent_runs_grouped(
        db, limit=limit, offset=offset, status=status_filter, agent_name=agent_name,
        exclude_agent_name=exclude_agent_name,
        request_id=uuid.UUID(request_id) if request_id else None,
    )
    return grouped


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
# System Settings (Pipeline Mode, etc.)
# ────────────────────────────────────────────────────────────────────────────

class SettingUpdate(BaseModel):
    value: str = Field(..., max_length=500)
    updated_by: str | None = None


@router.get("/admin/api/settings")
async def get_system_settings(
    user: AdminUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get all system settings — used by admin panel."""
    all_settings = await repo.get_all_system_settings(db)
    return {
        s.key: {
            "value": s.value,
            "description": s.description,
            "updated_by": s.updated_by,
            "updated_at": s.updated_at.isoformat() if s.updated_at else None,
        }
        for s in all_settings
    }


@router.put("/admin/api/settings/{key}")
async def update_system_setting(
    key: str,
    body: SettingUpdate,
    user: AdminUser = Depends(require_editor_or_above),
    db: AsyncSession = Depends(get_db),
):
    """Update a system setting (e.g., switch pipeline mode)."""
    # Validate known settings
    known_keys = {"enrichment_pipeline", "few_shot_limit"}
    if key not in known_keys:
        raise HTTPException(status_code=400, detail=f"Unknown setting key: {key}")

    # Validate enrichment_pipeline values
    if key == "enrichment_pipeline" and body.value not in ("crew", "workflow", "hybrid"):
        raise HTTPException(
            status_code=400,
            detail="enrichment_pipeline must be 'crew', 'workflow', or 'hybrid'",
        )

    await repo.upsert_system_setting(
        db, key, body.value, updated_by=body.updated_by or user.email,
    )
    await db.commit()
    return {"key": key, "value": body.value, "status": "updated"}

# ────────────────────────────────────────────────────────────────────────────
# Response Evaluations
# ────────────────────────────────────────────────────────────────────────────

@router.get("/admin/api/evaluations/summary")
async def evaluation_summary(
    days: int = 30,
    user: AdminUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get aggregated evaluation metrics for dashboard KPIs."""
    summary = await repo.get_evaluation_summary(db, days=days)
    return summary


@router.get("/admin/api/evaluations")
async def list_evaluations_route(
    limit: int = 50,
    offset: int = 0,
    agent_name: str | None = None,
    request_id: str | None = None,
    user: AdminUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List response evaluations with filters."""
    evals = await repo.list_evaluations(
        db, limit=limit, offset=offset, agent_name=agent_name,
        request_id=uuid.UUID(request_id) if request_id else None,
    )
    return [
        {
            "id": str(e.id),
            "request_id": str(e.request_id),
            "agent_run_id": str(e.agent_run_id) if e.agent_run_id else None,
            "agent_name": e.agent_name,
            "cache_hit": e.cache_hit,
            "cache_status": e.cache_status,
            "response_hash": e.response_hash[:12] + "…" if e.response_hash else None,
            "json_valid": e.json_valid,
            "schema_compliant": e.schema_compliant,
            "field_completeness_pct": float(e.field_completeness_pct) if e.field_completeness_pct else 0,
            "confidence_score_valid": e.confidence_score_valid,
            "determinism_score": float(e.determinism_score) if e.determinism_score is not None else None,
            "latency_ms": e.latency_ms,
            "created_at": e.created_at.isoformat() if e.created_at else None,
        }
        for e in evals
    ]


@router.get("/admin/api/evaluations/{eval_id}")
async def get_evaluation_detail_route(
    eval_id: uuid.UUID,
    user: AdminUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get detailed evaluation including full evaluation_details breakdown."""
    ev = await repo.get_evaluation_detail(db, eval_id)
    if not ev:
        raise HTTPException(status_code=404, detail="Evaluation not found")
    return {
        "id": str(ev.id),
        "request_id": str(ev.request_id),
        "agent_run_id": str(ev.agent_run_id) if ev.agent_run_id else None,
        "agent_name": ev.agent_name,
        "cache_hit": ev.cache_hit,
        "cache_status": ev.cache_status,
        "response_hash": ev.response_hash,
        "json_valid": ev.json_valid,
        "schema_compliant": ev.schema_compliant,
        "field_completeness_pct": float(ev.field_completeness_pct) if ev.field_completeness_pct else 0,
        "confidence_score_valid": ev.confidence_score_valid,
        "determinism_score": float(ev.determinism_score) if ev.determinism_score is not None else None,
        "latency_ms": ev.latency_ms,
        "evaluation_details": ev.evaluation_details,
        "created_at": ev.created_at.isoformat() if ev.created_at else None,
    }


# ────────────────────────────────────────────────────────────────────────────
# Cache Stats
# ────────────────────────────────────────────────────────────────────────────

@router.get("/admin/api/cache/stats")
async def cache_stats(
    user: AdminUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return LLM response cache statistics."""
    stats = await repo.get_cache_stats(db)
    stats["cache_enabled"] = settings.llm_cache_enabled
    stats["ttl_hours"] = settings.llm_cache_ttl_hours
    return stats


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
