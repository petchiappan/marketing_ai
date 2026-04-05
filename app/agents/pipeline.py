"""Background enrichment pipeline – runs agents with tool-specific access control."""

from __future__ import annotations

import asyncio
import json
import logging
import traceback
import uuid
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config.logging_config import setup_logging
from app.config.settings import settings
from app.db import repository as repo
from app.tools.registry import get_agent_tool_assignments

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
    Build agent → tool-name mapping using the file-based registry,
    but only include a tool if it is configured in the DB admin panel
    with is_enabled=True AND a non-empty API key.

    If a tool is not configured, disabled, or has no API key,
    it is skipped — the agent will run with LLM only for that tool.
    """
    base_assignments = get_agent_tool_assignments()
    validated: dict[str, list[str]] = {}

    for agent_name, tool_names in base_assignments.items():
        active_tools: list[str] = []
        for tool_name in tool_names:
            config = await repo.get_tool_config(db, tool_name)
            if config is None:
                logger.info(
                    "[%s] Tool '%s' skipped — not configured in admin",
                    agent_name, tool_name,
                )
                continue
            if not config.is_enabled:
                logger.info(
                    "[%s] Tool '%s' skipped — disabled in admin",
                    agent_name, tool_name,
                )
                continue
            if not config.api_key_encrypted:
                logger.info(
                    "[%s] Tool '%s' skipped — no API key configured",
                    agent_name, tool_name,
                )
                continue
            logger.info(
                "[%s] Tool '%s' ✔ validated (enabled + API key present)",
                agent_name, tool_name,
            )
            active_tools.append(tool_name)
        validated[agent_name] = active_tools

    return validated


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
    """Route to the correct pipeline based on DB system_settings."""
    engine, session_factory = _make_session_factory()

    try:
        async with session_factory() as db:
            # Check which pipeline the admin configured
            pipeline_mode = await repo.get_system_setting(db, "enrichment_pipeline")
            pipeline_mode = (pipeline_mode or "crew").lower().strip()

        logger.info("Pipeline selector: mode='%s' for request=%s", pipeline_mode, request_id)

        if pipeline_mode == "workflow":
            await _run_workflow_pipeline(request_id)
        else:
            await _run_crew_pipeline(request_id)
    except Exception as exc:
        logger.exception("Pipeline selector failed for request=%s: %s", request_id, exc)
        # Mark request as failed
        try:
            async with session_factory() as db:
                await repo.update_request_status(db, request_id, "failed")
                await db.commit()
        except Exception:
            pass
    finally:
        await engine.dispose(close=False)


async def _run_workflow_pipeline(request_id: uuid.UUID) -> None:
    """NEW: Deterministic workflow pipeline using CrewAI Flow.

    Code handles all API selection, fetching, validation, retries, normalization.
    LLM handles only data merging, dedup, scoring, and insight generation (1 call).
    """
    engine, session_factory = _make_session_factory()

    try:
        async with session_factory() as db:
            req = await repo.get_request(db, request_id)
            if not req:
                logger.error("[Workflow] Request %s not found", request_id)
                return

            company = req.company_name
            context = req.additional_fields or {}

            # Load few-shot examples from the feedback loop
            few_shots = await repo.get_few_shot_examples(db, limit=3, min_rating=4)

            # Update request status
            await repo.update_request_status(db, request_id, "processing")

            # Create a single agent run entry for tracking
            agent_run = await repo.create_agent_run(
                db,
                request_id=request_id,
                agent_name="workflow_pipeline",
                input_summary=f"Workflow enrichment for '{company}'",
            )
            await repo.start_agent_run(db, agent_run.id)
            await db.commit()

        # Run the deterministic flow (outside the DB session)
        from app.flows.enrichment_flow import LeadEnrichmentFlow

        loop = asyncio.get_event_loop()
        flow = LeadEnrichmentFlow()
        flow.state.request_id = str(request_id)
        flow.state.company_name = company
        flow.state.additional_context = context
        flow.state.salesforce_lead_id = req.salesforce_lead_id
        flow.state.few_shot_examples = few_shots

        # kickoff() is synchronous in CrewAI Flows
        await loop.run_in_executor(None, flow.kickoff)

        logger.info("[Workflow] Completed for '%s'", company)

        # Mark agent run as completed
        async with session_factory() as db:
            output_summary = "Workflow completed successfully"
            if flow.state.final_output:
                output_summary = json.dumps(flow.state.final_output, default=str)[:10000]
            await repo.complete_agent_run(db, agent_run.id, output_summary)
            await db.commit()

    except Exception as exc:
        logger.exception("[Workflow] Failed for request=%s: %s", request_id, exc)
        async with session_factory() as db:
            await repo.fail_agent_run(
                db, agent_run.id,
                error_type=type(exc).__name__,
                error_message=str(exc),
                error_traceback=traceback.format_exc(),
            )
            await repo.update_request_status(db, request_id, "failed")
            await db.commit()
    finally:
        await engine.dispose(close=False)


async def _run_crew_pipeline(request_id: uuid.UUID) -> None:
    """EXISTING: CrewAI Crew pipeline — completely unchanged."""
    engine, session_factory = _make_session_factory()

    try:
        async with session_factory() as db:
            req = await repo.get_request(db, request_id)
            if not req:
                return

            company = req.company_name
            context = req.additional_fields or {}

            # ── Determine which tools pass DB validation ──
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

                # ── Record per-task results + cache & evaluation ──
                from app.agents.normalizer import normalize_output
                from app.infrastructure.llm_cache import (
                    compute_cache_key, compute_prompt_hash, compute_response_hash,
                    compare_and_update_cache,
                )
                from app.infrastructure.evaluation import evaluate_response
                from app.infrastructure.prompt_generator import prompt_generator

                model_id = settings.llm_identifier

                for stage in PIPELINE_STAGES:
                    run = agent_runs[stage["name"]]
                    idx = stage["task_index"]
                    agent_name = stage["name"]

                    try:
                        if hasattr(result, 'tasks_output') and idx < len(result.tasks_output):
                            task_output = str(result.tasks_output[idx])
                            # Apply deterministic post-processing normalization
                            task_output = normalize_output(agent_name, task_output)
                        else:
                            task_output = "Completed as part of crew execution"

                        await repo.complete_agent_run(
                            db, run.id,
                            output_summary=task_output[:5000],
                        )

                        # ── Cache & Evaluation (non-fatal) ──
                        try:
                            # Build prompt for cache key (same prompt used by orchestrator)
                            from app.agents.orchestrator import AGENT_REGISTRY
                            agent_tools = tool_assignments.get(agent_name, [])
                            has_tools = len(agent_tools) > 0

                            if agent_name in AGENT_REGISTRY:
                                prompt_text = AGENT_REGISTRY[agent_name]["build_prompt"](
                                    prompt_generator, company, context
                                )
                            else:
                                prompt_text = f"aggregation:{company}"

                            cache_key = compute_cache_key(agent_name, prompt_text, model_id, agent_tools)
                            prompt_hash = compute_prompt_hash(prompt_text)
                            response_hash = compute_response_hash(task_output)

                            # Two-tier cache strategy
                            cached_entry = await repo.get_cached_response(db, cache_key)
                            cached_text = cached_entry.response_text if cached_entry else None
                            cached_hash = cached_entry.response_hash if cached_entry else None

                            cache_status = await compare_and_update_cache(
                                db,
                                cache_key=cache_key,
                                agent_name=agent_name,
                                model_name=model_id,
                                prompt_hash=prompt_hash,
                                new_response_text=task_output,
                                new_response_hash=response_hash,
                                tools_used=agent_tools,
                            )

                            # Run evaluation
                            eval_result = evaluate_response(
                                agent_name=agent_name,
                                response_text=task_output,
                                cache_status=cache_status,
                                cached_response_text=cached_text,
                                cached_response_hash=cached_hash,
                                latency_ms=run.duration_ms,
                            )

                            # Store evaluation record
                            await repo.save_evaluation(
                                db,
                                request_id=request_id,
                                agent_run_id=run.id,
                                agent_name=agent_name,
                                cache_hit=(cache_status == "hit"),
                                cache_status=cache_status,
                                response_hash=eval_result.response_hash,
                                json_valid=eval_result.json_valid,
                                schema_compliant=eval_result.schema_compliant,
                                field_completeness_pct=Decimal(str(eval_result.field_completeness_pct)),
                                confidence_score_valid=eval_result.confidence_score_valid,
                                determinism_score=Decimal(str(eval_result.determinism_score)) if eval_result.determinism_score is not None else None,
                                latency_ms=eval_result.latency_ms,
                                evaluation_details=eval_result.details,
                            )
                            logger.info(
                                "Evaluation saved for %s: cache=%s, json=%s, schema=%s, completeness=%.1f%%, determinism=%s",
                                agent_name, cache_status, eval_result.json_valid,
                                eval_result.schema_compliant, eval_result.field_completeness_pct,
                                f"{eval_result.determinism_score:.1f}%" if eval_result.determinism_score is not None else "N/A",
                            )
                        except Exception as eval_err:
                            logger.warning("Evaluation/cache failed for %s: %s", agent_name, eval_err, exc_info=True)
                            # Non-fatal – don't fail the pipeline over evaluation

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
