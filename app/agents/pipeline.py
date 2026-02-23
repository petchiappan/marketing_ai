"""Background enrichment pipeline – runs agents with tool-specific access control."""

from __future__ import annotations

import asyncio
import traceback
import uuid
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config.settings import settings
from app.db import repository as repo
from app.db.models import ToolConfig


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
        await engine.dispose()


def run_enrichment_pipeline(request_id: uuid.UUID) -> None:
    """Entry point for BackgroundTasks – creates its own event loop to avoid conflicts."""
    asyncio.run(_run_pipeline(request_id))
