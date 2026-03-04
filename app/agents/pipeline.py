"""Background enrichment pipeline – runs agents with tool-specific access control."""

from __future__ import annotations

import asyncio
import logging
import traceback
import uuid
from collections import defaultdict
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config.logging_config import setup_logging
from app.config.settings import settings
from app.db import repository as repo
from app.db.models import ToolConfig

# Ensure file logging is active even when pipeline runs in a background thread
setup_logging()
logger = logging.getLogger(__name__)

# Rough cost per 1M tokens (input/output) – update as pricing changes
_MODEL_COST_PER_1M: dict[str, tuple[float, float]] = {
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4-turbo": (10.00, 30.00),
    "gpt-4": (30.00, 60.00),
    "gpt-3.5-turbo": (0.50, 1.50),
}


def _estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> Decimal:
    """Estimate USD cost from token counts."""
    # Strip provider prefix (e.g. 'openai/gpt-4o-mini' -> 'gpt-4o-mini')
    model_key = model.split("/")[-1] if "/" in model else model
    rates = _MODEL_COST_PER_1M.get(model_key, (0.15, 0.60))  # default to mini
    cost = (prompt_tokens * rates[0] + completion_tokens * rates[1]) / 1_000_000
    return Decimal(str(round(cost, 6)))


def _make_session_factory():
    """Create a fresh engine + session factory for the background thread's own event loop."""
    engine = create_async_engine(
        settings.database_url,
        echo=False,
        pool_size=5,
        max_overflow=2,
        pool_pre_ping=True,
    )
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return engine, factory


async def _get_tool_assignments(db: AsyncSession) -> dict[str, list[str]]:
    """
    Query tool_configs to build: { agent_name: [tool_name, ...] }

    Only includes enabled tools that have an agent assigned.
    """
    stmt = (
        select(ToolConfig.agent_name, ToolConfig.tool_name)
        .where(ToolConfig.agent_name.isnot(None))
        .where(ToolConfig.is_enabled.is_(True))
    )
    result = await db.execute(stmt)

    assignments: dict[str, list[str]] = defaultdict(list)
    for agent_name, tool_name in result.all():
        assignments[agent_name].append(tool_name)

    return dict(assignments)


# All stages that always run (all data agents + aggregation)
PIPELINE_STAGES = [
    {"name": "contact_agent", "label": "Contact Agent", "task_index": 0},
    {"name": "news_agent", "label": "News Agent", "task_index": 1},
    {"name": "financial_agent", "label": "Financial Agent", "task_index": 2},
    {"name": "aggregation_agent", "label": "Aggregation Agent", "task_index": 3},
]


def _extract_token_counts(tu: object) -> tuple[int, int, int]:
    """Extract (prompt_tokens, completion_tokens, total_tokens) from a
    CrewAI UsageMetrics object *or* a plain dict.  Returns (0, 0, 0)
    if nothing useful is found."""
    if tu is None:
        return 0, 0, 0

    # Pydantic UsageMetrics — access as attributes
    if hasattr(tu, "prompt_tokens"):
        prompt = getattr(tu, "prompt_tokens", 0) or 0
        completion = getattr(tu, "completion_tokens", 0) or 0
        total = getattr(tu, "total_tokens", 0) or (prompt + completion)
        return prompt, completion, total

    # Plain dict fallback
    if isinstance(tu, dict):
        prompt = tu.get("prompt_tokens", 0) or 0
        completion = tu.get("completion_tokens", 0) or 0
        total = tu.get("total_tokens", 0) or (prompt + completion)
        return prompt, completion, total

    return 0, 0, 0


async def _run_pipeline(request_id: uuid.UUID) -> None:
    """Execute the enrichment crew with per-agent tool access control."""
    engine, session_factory = _make_session_factory()

    try:
        async with session_factory() as db:
            req = await repo.get_request(db, request_id)
            if not req:
                return

            company = req.company_name
            context = req.additional_fields or {}

            # ── Query which tools are assigned to which agents ──
            tool_assignments = await _get_tool_assignments(db)

            # ── Create AgentRun entries for ALL stages ──
            agent_runs = {}
            for stage in PIPELINE_STAGES:
                assigned = tool_assignments.get(stage["name"], [])
                tools_info = f" (tools: {', '.join(assigned)})" if assigned else " (no tools)"
                run = await repo.create_agent_run(
                    db,
                    request_id=request_id,
                    agent_name=stage["name"],
                    input_summary=f"Enrichment for '{company}' — {stage['label']}{tools_info}",
                )
                agent_runs[stage["name"]] = run
            await db.commit()

            # ── Build the crew with tool assignments ──
            try:
                from app.agents.orchestrator import build_enrichment_crew

                crew = build_enrichment_crew(company, context, tool_assignments=tool_assignments)
            except Exception as exc:
                for stage in PIPELINE_STAGES:
                    run = agent_runs[stage["name"]]
                    await repo.start_agent_run(db, run.id)
                    await repo.fail_agent_run(
                        db, run.id,
                        error_type=type(exc).__name__,
                        error_message=f"Crew build failed: {exc}",
                        error_traceback=traceback.format_exc(),
                    )
                await repo.update_request_status(db, request_id, "failed")
                await db.commit()
                return

            # ── Execute the crew ──
            overall_success = True
            try:
                for stage in PIPELINE_STAGES:
                    await repo.start_agent_run(db, agent_runs[stage["name"]].id)
                await db.commit()

                # CrewAI kickoff is synchronous – run in a thread
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(None, crew.kickoff)

                result_str = str(result)
                logger.info("Crew execution completed for request %s", request_id)
                logger.debug("Result type: %s", type(result).__name__)
                logger.debug("Result token_usage raw: %s", getattr(result, 'token_usage', None))
                logger.debug("Result tasks_output count: %s",
                             len(result.tasks_output) if hasattr(result, 'tasks_output') and result.tasks_output else 0)

                # ── Record per-task results ──
                for stage in PIPELINE_STAGES:
                    run = agent_runs[stage["name"]]
                    idx = stage["task_index"]

                    try:
                        if hasattr(result, 'tasks_output') and idx < len(result.tasks_output):
                            task_output = str(result.tasks_output[idx])
                        else:
                            task_output = "Completed as part of crew execution"

                        await repo.complete_agent_run(
                            db, run.id,
                            output_summary=task_output[:5000],
                        )
                    except Exception as inner_exc:
                        await repo.fail_agent_run(
                            db, run.id,
                            error_type=type(inner_exc).__name__,
                            error_message=str(inner_exc),
                            error_traceback=traceback.format_exc(),
                        )
                        overall_success = False
                await db.commit()

                # ── Record LLM token usage ──
                try:
                    model_name = settings.llm_identifier
                    logger.info("Recording token usage for model: %s", model_name)

                    # Try per-task token usage first
                    has_per_task = (
                        hasattr(result, 'tasks_output')
                        and result.tasks_output
                        and any(
                            getattr(t, 'token_usage', None)
                            for t in result.tasks_output
                        )
                    )

                    if has_per_task:
                        logger.info("Using per-task token usage")
                        for stage in PIPELINE_STAGES:
                            idx = stage["task_index"]
                            if idx < len(result.tasks_output):
                                tu = getattr(result.tasks_output[idx], 'token_usage', None)
                                logger.debug("Task %s token_usage: %s (type: %s)",
                                             stage["name"], tu, type(tu).__name__)
                                prompt, completion, total = _extract_token_counts(tu)
                                if total > 0:
                                    await repo.log_token_usage(
                                        db,
                                        request_id=request_id,
                                        agent_name=stage["name"],
                                        model_name=model_name,
                                        prompt_tokens=prompt,
                                        completion_tokens=completion,
                                        total_tokens=total,
                                        estimated_cost_usd=_estimate_cost(model_name, prompt, completion),
                                    )
                                    logger.info("Recorded %s: prompt=%d, completion=%d, total=%d",
                                                stage["name"], prompt, completion, total)
                    else:
                        # Fall back to overall crew token_usage
                        tu = getattr(result, 'token_usage', None)
                        logger.debug("Overall crew token_usage: %s (type: %s)",
                                     tu, type(tu).__name__ if tu else "None")
                        prompt_all, completion_all, total_all = _extract_token_counts(tu)
                        num_agents = len(PIPELINE_STAGES)

                        if total_all > 0:
                            logger.info("Using overall crew token usage (split across %d agents): "
                                        "prompt=%d, completion=%d, total=%d",
                                        num_agents, prompt_all, completion_all, total_all)
                            # Split evenly across agents as approximation
                            for stage in PIPELINE_STAGES:
                                agent_prompt = prompt_all // num_agents
                                agent_completion = completion_all // num_agents
                                agent_total = total_all // num_agents
                                await repo.log_token_usage(
                                    db,
                                    request_id=request_id,
                                    agent_name=stage["name"],
                                    model_name=model_name,
                                    prompt_tokens=agent_prompt,
                                    completion_tokens=agent_completion,
                                    total_tokens=agent_total,
                                    estimated_cost_usd=_estimate_cost(model_name, agent_prompt, agent_completion),
                                )
                        else:
                            logger.warning("No token usage data available from CrewAI result")

                    await db.commit()
                    logger.info("Token usage committed for request %s", request_id)
                except Exception as token_err:
                    logger.warning("Failed to record token usage: %s", token_err, exc_info=True)
                    # Non-fatal – don't fail the pipeline over tracking

                # ── Save enriched lead ──
                await repo.save_enriched_lead(
                    db,
                    request_id=request_id,
                    company_name=company,
                    enrichment_summary=result_str[:10000],
                )
                final_status = "completed" if overall_success else "partial"
                await repo.update_request_status(db, request_id, final_status)
                await db.commit()

            except Exception as exc:
                for stage in PIPELINE_STAGES:
                    run = agent_runs[stage["name"]]
                    try:
                        current = await repo.get_agent_run(db, run.id)
                        if current and current.status == "running":
                            await repo.fail_agent_run(
                                db, run.id,
                                error_type=type(exc).__name__,
                                error_message=str(exc),
                                error_traceback=traceback.format_exc(),
                            )
                    except Exception:
                        pass

                await repo.update_request_status(db, request_id, "failed")
                await db.commit()
    finally:
        # close=False avoids asyncpg cross-loop termination errors
        # when crew.kickoff() spawned sub-loops in its thread executor
        await engine.dispose(close=False)


def run_enrichment_pipeline(request_id: uuid.UUID) -> None:
    """Entry point for BackgroundTasks - creates its own event loop to avoid conflicts."""
    asyncio.run(_run_pipeline(request_id))
