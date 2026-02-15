"""Repository pattern – CRUD operations for all database entities."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any, Sequence

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AdminUser,
    AgentRun,
    ContactResult,
    EnrichedLead,
    EnrichmentAuditLog,
    EnrichmentRequest,
    FinancialResult,
    LLMTokenUsage,
    NewsResult,
    ProviderRateLimit,
    ToolConfig,
)


# ---------------------------------------------------------------------------
# Enrichment Requests
# ---------------------------------------------------------------------------

async def create_request(
    db: AsyncSession,
    company_name: str,
    source: str = "api",
    salesforce_lead_id: str | None = None,
    additional_fields: dict | None = None,
    requested_by: str | None = None,
) -> EnrichmentRequest:
    req = EnrichmentRequest(
        company_name=company_name,
        source=source,
        salesforce_lead_id=salesforce_lead_id,
        additional_fields=additional_fields or {},
        requested_by=requested_by,
    )
    db.add(req)
    await db.flush()
    return req


async def get_request(db: AsyncSession, request_id: uuid.UUID) -> EnrichmentRequest | None:
    return await db.get(EnrichmentRequest, request_id)


async def update_request_status(db: AsyncSession, request_id: uuid.UUID, status: str) -> None:
    await db.execute(
        update(EnrichmentRequest)
        .where(EnrichmentRequest.id == request_id)
        .values(status=status, updated_at=datetime.utcnow())
    )


async def list_requests(
    db: AsyncSession, *, limit: int = 50, offset: int = 0, status: str | None = None
) -> Sequence[EnrichmentRequest]:
    stmt = select(EnrichmentRequest).order_by(EnrichmentRequest.created_at.desc())
    if status:
        stmt = stmt.where(EnrichmentRequest.status == status)
    stmt = stmt.limit(limit).offset(offset)
    result = await db.execute(stmt)
    return result.scalars().all()


# ---------------------------------------------------------------------------
# Agent Results (Stage 2)
# ---------------------------------------------------------------------------

async def save_contact_result(db: AsyncSession, **kwargs: Any) -> ContactResult:
    obj = ContactResult(**kwargs)
    db.add(obj)
    await db.flush()
    return obj


async def save_news_result(db: AsyncSession, **kwargs: Any) -> NewsResult:
    obj = NewsResult(**kwargs)
    db.add(obj)
    await db.flush()
    return obj


async def save_financial_result(db: AsyncSession, **kwargs: Any) -> FinancialResult:
    obj = FinancialResult(**kwargs)
    db.add(obj)
    await db.flush()
    return obj


# ---------------------------------------------------------------------------
# Enriched Leads (Stage 3)
# ---------------------------------------------------------------------------

async def save_enriched_lead(db: AsyncSession, **kwargs: Any) -> EnrichedLead:
    obj = EnrichedLead(**kwargs)
    db.add(obj)
    await db.flush()
    return obj


async def get_enriched_lead(db: AsyncSession, request_id: uuid.UUID) -> EnrichedLead | None:
    stmt = select(EnrichedLead).where(EnrichedLead.request_id == request_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def list_enriched_leads(
    db: AsyncSession, *, limit: int = 50, offset: int = 0
) -> Sequence[EnrichedLead]:
    stmt = (
        select(EnrichedLead)
        .order_by(EnrichedLead.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(stmt)
    return result.scalars().all()


# ---------------------------------------------------------------------------
# Audit Log
# ---------------------------------------------------------------------------

async def log_audit(
    db: AsyncSession,
    request_id: uuid.UUID,
    stage: str,
    action: str,
    agent_name: str | None = None,
    details: dict | None = None,
) -> EnrichmentAuditLog:
    entry = EnrichmentAuditLog(
        request_id=request_id,
        stage=stage,
        agent_name=agent_name,
        action=action,
        details=details or {},
    )
    db.add(entry)
    await db.flush()
    return entry


# ---------------------------------------------------------------------------
# Tool Configs
# ---------------------------------------------------------------------------

async def list_tool_configs(db: AsyncSession) -> Sequence[ToolConfig]:
    result = await db.execute(select(ToolConfig).order_by(ToolConfig.tool_name))
    return result.scalars().all()


async def get_tool_config(db: AsyncSession, tool_name: str) -> ToolConfig | None:
    stmt = select(ToolConfig).where(ToolConfig.tool_name == tool_name)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def upsert_tool_config(db: AsyncSession, tool_name: str, **kwargs: Any) -> ToolConfig:
    existing = await get_tool_config(db, tool_name)
    if existing:
        for k, v in kwargs.items():
            setattr(existing, k, v)
        existing.updated_at = datetime.utcnow()
        await db.flush()
        return existing
    obj = ToolConfig(tool_name=tool_name, **kwargs)
    db.add(obj)
    await db.flush()
    return obj


# ---------------------------------------------------------------------------
# Rate Limits
# ---------------------------------------------------------------------------

async def list_rate_limits(db: AsyncSession) -> Sequence[ProviderRateLimit]:
    result = await db.execute(select(ProviderRateLimit).order_by(ProviderRateLimit.provider_name))
    return result.scalars().all()


async def get_rate_limit(db: AsyncSession, provider: str) -> ProviderRateLimit | None:
    stmt = select(ProviderRateLimit).where(ProviderRateLimit.provider_name == provider)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def update_rate_limit(db: AsyncSession, provider: str, **kwargs: Any) -> ProviderRateLimit | None:
    rl = await get_rate_limit(db, provider)
    if not rl:
        return None
    for k, v in kwargs.items():
        setattr(rl, k, v)
    rl.updated_at = datetime.utcnow()
    await db.flush()
    return rl


# ---------------------------------------------------------------------------
# LLM Token Usage
# ---------------------------------------------------------------------------

async def log_token_usage(db: AsyncSession, **kwargs: Any) -> LLMTokenUsage:
    obj = LLMTokenUsage(**kwargs)
    db.add(obj)
    await db.flush()
    return obj


async def get_token_usage_summary(
    db: AsyncSession, *, days: int = 30
) -> list[dict[str, Any]]:
    since = datetime.utcnow() - timedelta(days=days)
    stmt = (
        select(
            LLMTokenUsage.agent_name,
            LLMTokenUsage.model_name,
            func.sum(LLMTokenUsage.prompt_tokens).label("total_prompt"),
            func.sum(LLMTokenUsage.completion_tokens).label("total_completion"),
            func.sum(LLMTokenUsage.total_tokens).label("total_tokens"),
            func.sum(LLMTokenUsage.estimated_cost_usd).label("total_cost"),
            func.count().label("call_count"),
        )
        .where(LLMTokenUsage.created_at >= since)
        .group_by(LLMTokenUsage.agent_name, LLMTokenUsage.model_name)
    )
    result = await db.execute(stmt)
    return [dict(row._mapping) for row in result.all()]


# ---------------------------------------------------------------------------
# Agent Runs
# ---------------------------------------------------------------------------

async def create_agent_run(
    db: AsyncSession,
    request_id: uuid.UUID,
    agent_name: str,
    input_summary: str | None = None,
) -> AgentRun:
    run = AgentRun(
        request_id=request_id,
        agent_name=agent_name,
        input_summary=input_summary,
    )
    db.add(run)
    await db.flush()
    return run


async def start_agent_run(db: AsyncSession, run_id: uuid.UUID) -> None:
    await db.execute(
        update(AgentRun)
        .where(AgentRun.id == run_id)
        .values(status="running", started_at=datetime.utcnow())
    )


async def complete_agent_run(
    db: AsyncSession, run_id: uuid.UUID, output_summary: str | None = None
) -> None:
    now = datetime.utcnow()
    run = await db.get(AgentRun, run_id)
    if run:
        duration = int((now - run.started_at).total_seconds() * 1000) if run.started_at else None
        await db.execute(
            update(AgentRun)
            .where(AgentRun.id == run_id)
            .values(
                status="completed",
                completed_at=now,
                duration_ms=duration,
                output_summary=output_summary,
            )
        )


async def fail_agent_run(
    db: AsyncSession,
    run_id: uuid.UUID,
    error_type: str,
    error_message: str,
    error_traceback: str | None = None,
) -> None:
    now = datetime.utcnow()
    run = await db.get(AgentRun, run_id)
    if run:
        duration = int((now - run.started_at).total_seconds() * 1000) if run.started_at else None
        await db.execute(
            update(AgentRun)
            .where(AgentRun.id == run_id)
            .values(
                status="failed",
                completed_at=now,
                duration_ms=duration,
                error_type=error_type,
                error_message=error_message,
                error_traceback=error_traceback,
            )
        )


async def list_agent_runs(
    db: AsyncSession,
    *,
    limit: int = 50,
    offset: int = 0,
    status: str | None = None,
    agent_name: str | None = None,
) -> Sequence[AgentRun]:
    stmt = select(AgentRun).order_by(AgentRun.created_at.desc())
    if status:
        stmt = stmt.where(AgentRun.status == status)
    if agent_name:
        stmt = stmt.where(AgentRun.agent_name == agent_name)
    stmt = stmt.limit(limit).offset(offset)
    result = await db.execute(stmt)
    return result.scalars().all()


async def get_agent_run(db: AsyncSession, run_id: uuid.UUID) -> AgentRun | None:
    return await db.get(AgentRun, run_id)


# ---------------------------------------------------------------------------
# Admin Users
# ---------------------------------------------------------------------------

async def get_user_by_email(db: AsyncSession, email: str) -> AdminUser | None:
    stmt = select(AdminUser).where(AdminUser.email == email)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def get_user_by_username(db: AsyncSession, username: str) -> AdminUser | None:
    stmt = select(AdminUser).where(AdminUser.username == username)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def create_admin_user(db: AsyncSession, **kwargs: Any) -> AdminUser:
    user = AdminUser(**kwargs)
    db.add(user)
    await db.flush()
    return user


async def update_user_login(db: AsyncSession, user_id: uuid.UUID) -> None:
    await db.execute(
        update(AdminUser)
        .where(AdminUser.id == user_id)
        .values(last_login_at=datetime.utcnow())
    )
