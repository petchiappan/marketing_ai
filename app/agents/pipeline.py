"""Background enrichment pipeline – runs the CrewAI orchestrator and tracks each agent step."""

from __future__ import annotations

import asyncio
import json
import traceback
import uuid
from datetime import datetime

from app.db.session import async_session_factory
from app.db import repository as repo


AGENT_STAGES = [
    {"name": "contact_agent", "label": "Contact Agent", "task_index": 0},
    {"name": "news_agent", "label": "News Agent", "task_index": 1},
    {"name": "financial_agent", "label": "Financial Agent", "task_index": 2},
    {"name": "aggregation_agent", "label": "Aggregation Agent", "task_index": 3},
]


async def _run_pipeline(request_id: uuid.UUID) -> None:
    """Execute the enrichment crew and persist per-agent results."""
    async with async_session_factory() as db:
        req = await repo.get_request(db, request_id)
        if not req:
            return

        company = req.company_name
        context = req.additional_fields or {}

        # ── Create AgentRun entries for all 4 stages upfront ──
        agent_runs = {}
        for stage in AGENT_STAGES:
            run = await repo.create_agent_run(
                db,
                request_id=request_id,
                agent_name=stage["name"],
                input_summary=f"Enrichment for '{company}' — {stage['label']}",
            )
            agent_runs[stage["name"]] = run
        await db.commit()

        # ── Build the crew ──
        try:
            from app.agents.orchestrator import build_enrichment_crew

            crew = build_enrichment_crew(company, context)
        except Exception as exc:
            # Failed during crew build — mark all runs as failed
            for stage in AGENT_STAGES:
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
            # Mark all agents as running
            for stage in AGENT_STAGES:
                await repo.start_agent_run(db, agent_runs[stage["name"]].id)
            await db.commit()

            # CrewAI kickoff is synchronous – run in a thread
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, crew.kickoff)

            result_str = str(result)

            # ── Record per-task results ──
            for stage in AGENT_STAGES:
                run = agent_runs[stage["name"]]
                idx = stage["task_index"]

                try:
                    # Try to extract individual task output
                    if hasattr(result, 'tasks_output') and idx < len(result.tasks_output):
                        task_output = str(result.tasks_output[idx])
                    else:
                        task_output = f"Completed as part of crew execution"

                    await repo.complete_agent_run(
                        db, run.id,
                        output_summary=task_output[:5000],  # Truncate large outputs
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
            # Crew execution failed — mark remaining running agents as failed
            for stage in AGENT_STAGES:
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


def run_enrichment_pipeline(request_id: uuid.UUID) -> None:
    """Entry point for BackgroundTasks – creates an event loop and runs the async pipeline."""
    asyncio.run(_run_pipeline(request_id))
