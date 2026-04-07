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
    """Entry point for the default hybrid enrichment pipeline."""
    engine, session_factory = _make_session_factory()

    try:
        logger.info("Pipeline Execution: native hybrid for request=%s", request_id)
        await _run_workflow_pipeline(request_id)
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
    """Universal Hybrid pipeline (Deterministic Fetch -> Micro Agent Extract).

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





def run_enrichment_pipeline(request_id: uuid.UUID) -> None:
    """Entry point for BackgroundTasks - creates its own event loop to avoid conflicts."""
    asyncio.run(_run_pipeline(request_id))
