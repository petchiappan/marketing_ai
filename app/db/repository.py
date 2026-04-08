"""Repository pattern – CRUD operations for all database entities."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Sequence

from sqlalchemy import Integer, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AdminUser,
    AgentRun,
    ContactResult,
    EnhancementHistory,
    EnrichedLead,
    EnrichmentAuditLog,
    EnrichmentRequest,
    FewShotExample,
    FinancialResult,
    LLMResponseCache,
    LLMTokenUsage,
    NewsResult,
    ProviderRateLimit,
    ResponseEvaluation,
    SystemSetting,
    ToolConfig,
    UserFeedback,
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
        .values(status=status, updated_at=datetime.now(timezone.utc))
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
        existing.updated_at = datetime.now(timezone.utc)
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
    rl.updated_at = datetime.now(timezone.utc)
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
    since = datetime.now(timezone.utc) - timedelta(days=days)
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
        .values(status="running", started_at=datetime.now(timezone.utc))
    )


async def complete_agent_run(
    db: AsyncSession, run_id: uuid.UUID, output_summary: str | None = None
) -> None:
    now = datetime.now(timezone.utc)
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
    now = datetime.now(timezone.utc)
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
    request_id: uuid.UUID | None = None,
) -> Sequence[AgentRun]:
    stmt = select(AgentRun).order_by(AgentRun.created_at.desc())
    if status:
        stmt = stmt.where(AgentRun.status == status)
    if agent_name:
        stmt = stmt.where(AgentRun.agent_name == agent_name)
    if request_id:
        stmt = stmt.where(AgentRun.request_id == request_id)
    stmt = stmt.limit(limit).offset(offset)
    result = await db.execute(stmt)
    return result.scalars().all()


async def list_agent_runs_grouped(
    db: AsyncSession,
    *,
    limit: int = 50,
    offset: int = 0,
    status: str | None = None,
    agent_name: str | None = None,
    exclude_agent_name: str | None = None,
    request_id: uuid.UUID | None = None,
) -> list[dict]:
    """Return agent runs grouped by their parent enrichment request.

    Each group includes the company_name, overall request status,
    request created_at, and a list of individual agent run dicts.
    """
    stmt = (
        select(AgentRun, EnrichmentRequest.company_name, EnrichmentRequest.status.label("request_status"), EnrichmentRequest.created_at.label("request_created_at"))
        .join(EnrichmentRequest, AgentRun.request_id == EnrichmentRequest.id)
        .order_by(AgentRun.created_at.desc())
    )
    if status:
        stmt = stmt.where(AgentRun.status == status)
    if agent_name:
        stmt = stmt.where(AgentRun.agent_name == agent_name)
    if exclude_agent_name:
        stmt = stmt.where(AgentRun.agent_name != exclude_agent_name)
    if request_id:
        stmt = stmt.where(AgentRun.request_id == request_id)

    result = await db.execute(stmt)
    rows = result.all()

    # Group by request_id preserving order
    from collections import OrderedDict
    groups: OrderedDict[uuid.UUID, dict] = OrderedDict()
    for run, company_name, request_status, request_created_at in rows:
        rid = run.request_id
        if rid not in groups:
            groups[rid] = {
                "request_id": str(rid),
                "company_name": company_name,
                "status": request_status,
                "created_at": request_created_at.isoformat() if request_created_at else None,
                "agents": [],
            }
        groups[rid]["agents"].append({
            "id": str(run.id),
            "agent_name": run.agent_name,
            "status": run.status,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
            "duration_ms": run.duration_ms,
            "error_type": run.error_type,
            "error_message": run.error_message,
        })

    grouped = list(groups.values())
    # Apply pagination to the groups
    return grouped[offset:offset + limit]


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
        .values(last_login_at=datetime.now(timezone.utc))
    )


# ---------------------------------------------------------------------------
# LLM Response Cache
# ---------------------------------------------------------------------------

async def get_cached_response(
    db: AsyncSession, cache_key: str
) -> LLMResponseCache | None:
    """Retrieve a non-expired cache entry by key."""
    stmt = (
        select(LLMResponseCache)
        .where(LLMResponseCache.cache_key == cache_key)
        .where(LLMResponseCache.expires_at > datetime.now(timezone.utc))
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def store_cached_response(db: AsyncSession, **kwargs: Any) -> LLMResponseCache:
    """Create a new cache entry."""
    obj = LLMResponseCache(**kwargs)
    db.add(obj)
    await db.flush()
    return obj


async def update_cached_response(
    db: AsyncSession, cache_key: str, **kwargs: Any
) -> LLMResponseCache | None:
    """Update an existing cache entry (for tool-response replacement)."""
    stmt = select(LLMResponseCache).where(LLMResponseCache.cache_key == cache_key)
    result = await db.execute(stmt)
    entry = result.scalar_one_or_none()
    if entry:
        for k, v in kwargs.items():
            setattr(entry, k, v)
        await db.flush()
    return entry


async def increment_cache_hit(db: AsyncSession, cache_key: str) -> None:
    """Increment hit count and update last_hit_at."""
    await db.execute(
        update(LLMResponseCache)
        .where(LLMResponseCache.cache_key == cache_key)
        .values(
            hit_count=LLMResponseCache.hit_count + 1,
            last_hit_at=datetime.now(timezone.utc),
        )
    )


async def get_cache_stats(db: AsyncSession) -> dict[str, Any]:
    """Aggregate cache statistics for admin dashboard."""
    total = (await db.execute(select(func.count(LLMResponseCache.id)))).scalar() or 0
    active = (await db.execute(
        select(func.count(LLMResponseCache.id))
        .where(LLMResponseCache.expires_at > datetime.now(timezone.utc))
    )).scalar() or 0
    total_hits = (await db.execute(
        select(func.coalesce(func.sum(LLMResponseCache.hit_count), 0))
    )).scalar() or 0
    return {
        "total_entries": total,
        "active_entries": active,
        "expired_entries": total - active,
        "total_hits": total_hits,
    }


# ---------------------------------------------------------------------------
# Response Evaluations
# ---------------------------------------------------------------------------

async def save_evaluation(db: AsyncSession, **kwargs: Any) -> ResponseEvaluation:
    obj = ResponseEvaluation(**kwargs)
    db.add(obj)
    await db.flush()
    return obj


async def list_evaluations(
    db: AsyncSession,
    *,
    limit: int = 50,
    offset: int = 0,
    agent_name: str | None = None,
    request_id: uuid.UUID | None = None,
) -> Sequence[ResponseEvaluation]:
    stmt = select(ResponseEvaluation).order_by(ResponseEvaluation.created_at.desc())
    if agent_name:
        stmt = stmt.where(ResponseEvaluation.agent_name == agent_name)
    if request_id:
        stmt = stmt.where(ResponseEvaluation.request_id == request_id)
    stmt = stmt.limit(limit).offset(offset)
    result = await db.execute(stmt)
    return result.scalars().all()


async def get_evaluation_summary(
    db: AsyncSession, *, days: int = 30
) -> dict[str, Any]:
    """Aggregate evaluation metrics for admin dashboard KPIs."""
    since = datetime.now(timezone.utc) - timedelta(days=days)

    total = (await db.execute(
        select(func.count(ResponseEvaluation.id)).where(ResponseEvaluation.created_at >= since)
    )).scalar() or 0

    if total == 0:
        return {
            "total_evaluations": 0,
            "avg_determinism_score": None,
            "avg_field_completeness": None,
            "schema_compliance_rate": None,
            "cache_hit_rate": None,
            "json_valid_rate": None,
            "by_agent": [],
        }

    avg_det = (await db.execute(
        select(func.avg(ResponseEvaluation.determinism_score))
        .where(ResponseEvaluation.created_at >= since)
        .where(ResponseEvaluation.determinism_score.isnot(None))
    )).scalar()

    avg_completeness = (await db.execute(
        select(func.avg(ResponseEvaluation.field_completeness_pct))
        .where(ResponseEvaluation.created_at >= since)
    )).scalar()

    schema_ok = (await db.execute(
        select(func.count(ResponseEvaluation.id))
        .where(ResponseEvaluation.created_at >= since)
        .where(ResponseEvaluation.schema_compliant.is_(True))
    )).scalar() or 0

    cache_hits = (await db.execute(
        select(func.count(ResponseEvaluation.id))
        .where(ResponseEvaluation.created_at >= since)
        .where(ResponseEvaluation.cache_status == "hit")
    )).scalar() or 0

    json_ok = (await db.execute(
        select(func.count(ResponseEvaluation.id))
        .where(ResponseEvaluation.created_at >= since)
        .where(ResponseEvaluation.json_valid.is_(True))
    )).scalar() or 0

    # Per-agent breakdown
    agent_stmt = (
        select(
            ResponseEvaluation.agent_name,
            func.count().label("count"),
            func.avg(ResponseEvaluation.determinism_score).label("avg_determinism"),
            func.avg(ResponseEvaluation.field_completeness_pct).label("avg_completeness"),
            func.sum(func.cast(ResponseEvaluation.schema_compliant, Integer)).label("schema_ok"),
            func.sum(func.cast(ResponseEvaluation.json_valid, Integer)).label("json_ok"),
        )
        .where(ResponseEvaluation.created_at >= since)
        .group_by(ResponseEvaluation.agent_name)
    )
    agent_rows = await db.execute(agent_stmt)
    by_agent = []
    for row in agent_rows.all():
        m = row._mapping
        cnt = m["count"]
        by_agent.append({
            "agent_name": m["agent_name"],
            "count": cnt,
            "avg_determinism": round(float(m["avg_determinism"]), 2) if m["avg_determinism"] else None,
            "avg_completeness": round(float(m["avg_completeness"]), 2) if m["avg_completeness"] else None,
            "schema_compliance_rate": round((m["schema_ok"] / cnt) * 100, 1) if cnt else None,
            "json_valid_rate": round((m["json_ok"] / cnt) * 100, 1) if cnt else None,
        })

    return {
        "total_evaluations": total,
        "avg_determinism_score": round(float(avg_det), 2) if avg_det else None,
        "avg_field_completeness": round(float(avg_completeness), 2) if avg_completeness else None,
        "schema_compliance_rate": round((schema_ok / total) * 100, 1),
        "cache_hit_rate": round((cache_hits / total) * 100, 1),
        "json_valid_rate": round((json_ok / total) * 100, 1),
        "by_agent": by_agent,
    }


async def get_evaluation_detail(
    db: AsyncSession, eval_id: uuid.UUID
) -> ResponseEvaluation | None:
    return await db.get(ResponseEvaluation, eval_id)


# ---------------------------------------------------------------------------
# System Settings
# ---------------------------------------------------------------------------

async def get_system_setting(db: AsyncSession, key: str) -> str | None:
    """Get a system setting value by key."""
    obj = await db.get(SystemSetting, key)
    return obj.value if obj else None


async def get_all_system_settings(db: AsyncSession) -> Sequence[SystemSetting]:
    result = await db.execute(select(SystemSetting).order_by(SystemSetting.key))
    return result.scalars().all()


async def upsert_system_setting(
    db: AsyncSession,
    key: str,
    value: str,
    description: str | None = None,
    updated_by: str | None = None,
) -> SystemSetting:
    existing = await db.get(SystemSetting, key)
    if existing:
        existing.value = value
        if description is not None:
            existing.description = description
        existing.updated_by = updated_by
        existing.updated_at = datetime.now(timezone.utc)
        await db.flush()
        return existing
    obj = SystemSetting(key=key, value=value, description=description, updated_by=updated_by)
    db.add(obj)
    await db.flush()
    return obj


# ---------------------------------------------------------------------------
# User Feedback
# ---------------------------------------------------------------------------

async def save_feedback(
    db: AsyncSession,
    request_id: uuid.UUID,
    rating: int,
    feedback_text: str | None = None,
    rated_by: str | None = None,
) -> UserFeedback:
    obj = UserFeedback(
        request_id=request_id,
        rating=rating,
        feedback_text=feedback_text,
        rated_by=rated_by,
    )
    db.add(obj)
    await db.flush()
    return obj


async def get_feedback_for_request(
    db: AsyncSession, request_id: uuid.UUID
) -> Sequence[UserFeedback]:
    stmt = (
        select(UserFeedback)
        .where(UserFeedback.request_id == request_id)
        .order_by(UserFeedback.created_at.desc())
    )
    result = await db.execute(stmt)
    return result.scalars().all()


# ---------------------------------------------------------------------------
# Few-Shot Prompt Bank
# ---------------------------------------------------------------------------

async def promote_to_few_shot(
    db: AsyncSession,
    request_id: uuid.UUID,
    company_name: str,
    output_response: str,
    rating: int,
    embedding: list[float] | None = None,
) -> FewShotExample:
    """Promote a high-rated output to the few-shot prompt bank."""
    obj = FewShotExample(
        company_name=company_name,
        output_response=output_response,
        rating=rating,
        source_request_id=request_id,
        embedding=embedding,
    )
    db.add(obj)
    await db.flush()
    return obj


async def get_few_shot_examples(
    db: AsyncSession,
    *,
    limit: int = 3,
    min_rating: int = 4,
    query_embedding: list[float] | None = None,
) -> list[dict[str, Any]]:
    """Get active few-shot examples ordered by rating desc, most recent first, or by vector similarity."""
    stmt = (
        select(FewShotExample)
        .where(FewShotExample.is_active.is_(True))
        .where(FewShotExample.rating >= min_rating)
    )
    
    if query_embedding is not None:
        stmt = stmt.order_by(FewShotExample.embedding.cosine_distance(query_embedding))
    else:
        stmt = stmt.order_by(FewShotExample.rating.desc(), FewShotExample.created_at.desc())
        
    stmt = stmt.limit(limit)
    result = await db.execute(stmt)
    examples = result.scalars().all()
    return [
        {
            "id": str(ex.id),
            "company_name": ex.company_name,
            "output_response": ex.output_response,
            "rating": ex.rating,
            "created_at": ex.created_at.isoformat() if ex.created_at else None,
        }
        for ex in examples
    ]


# ---------------------------------------------------------------------------
# Enhancement History
# ---------------------------------------------------------------------------

async def save_enhancement(
    db: AsyncSession,
    request_id: uuid.UUID,
    original_output: str,
    enhanced_output: str,
    user_instructions: str | None = None,
    enhancement_model: str | None = None,
    token_usage: dict | None = None,
) -> EnhancementHistory:
    obj = EnhancementHistory(
        request_id=request_id,
        original_output=original_output,
        enhanced_output=enhanced_output,
        user_instructions=user_instructions,
        enhancement_model=enhancement_model,
        token_usage=token_usage or {},
    )
    db.add(obj)
    await db.flush()
    return obj


async def update_enrichment_summary(
    db: AsyncSession,
    request_id: uuid.UUID,
    new_summary: str,
) -> None:
    """Update the enriched lead summary (used by enhance button)."""
    await db.execute(
        update(EnrichedLead)
        .where(EnrichedLead.request_id == request_id)
        .values(enrichment_summary=new_summary, updated_at=datetime.now(timezone.utc))
    )
