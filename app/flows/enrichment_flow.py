"""Deterministic enrichment workflow using CrewAI Flow.

Architecture rules:
  - Code handles: API selection, fetching, validation, retries, normalization, storage.
  - LLM handles:  Fill missing data, remove duplicates, lead scoring, insights (ONE call).
  - LLM NEVER:    Selects APIs, makes HTTP calls, handles retries, controls workflow.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any

from crewai.flow.flow import Flow, start, listen

from app.flows.flow_state import EnrichmentState

logger = logging.getLogger(__name__)


class LeadEnrichmentFlow(Flow[EnrichmentState]):
    """Deterministic lead enrichment flow.

    Steps 1-6 are pure Python / deterministic code.
    Step 7 is a single LLM call with no tools.
    Step 8 stores the final output.
    """

    # ── Step 1: Validate ─────────────────────────────────────────────────

    @start()
    def validate_input(self):
        """Step 1: Validate input — pure Python."""
        if not self.state.company_name:
            raise ValueError("company_name is required")
        logger.info("[Workflow] Step 1 — Validated input for: %s", self.state.company_name)

    # ── Step 2: Select APIs ──────────────────────────────────────────────

    @listen(validate_input)
    def select_apis(self):
        """Step 2: Determine which APIs to call — pure Python if/else.

        Reads tool_configs from DB. If enabled + has API key → include.
        The LLM NEVER decides which API to call.
        """
        loop = asyncio.new_event_loop()
        try:
            enabled, configs = loop.run_until_complete(self._load_tool_configs())
            self.state.enabled_tools = enabled
            self.state.tool_configs = configs
            logger.info("[Workflow] Step 2 — Selected APIs: %s", enabled)
        finally:
            loop.close()

    # ── Step 3: Fetch Data ───────────────────────────────────────────────

    @listen(select_apis)
    def fetch_data(self):
        """Step 3: Fetch data in parallel — httpx + tenacity, no LLM."""
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(self._fetch_all())
            logger.info(
                "[Workflow] Step 3 — Fetched: %d contact sources, %d news sources, %d financial sources",
                len(self.state.raw_contact_results),
                len(self.state.raw_news_results),
                len(self.state.raw_financial_results),
            )
        finally:
            loop.close()

    # ── Step 4: Validate & Retry ─────────────────────────────────────────

    @listen(fetch_data)
    def validate_and_retry(self):
        """Step 4: Retry failed fetches — pure Python."""
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(self._retry_failed())
            if self.state.fetch_errors:
                logger.warning(
                    "[Workflow] Step 4 — Still failed after retries: %s",
                    [e["tool"] for e in self.state.fetch_errors],
                )
            else:
                logger.info("[Workflow] Step 4 — All fetches OK")
        finally:
            loop.close()

    # ── Step 5: Normalize & Format ───────────────────────────────────────

    @listen(validate_and_retry)
    def normalize_and_format(self):
        """Step 5: Normalize, deduplicate, clamp scores — pure Python.

        Reuses the existing deterministic scoring logic from normalizer.py.
        """
        self._normalize_contacts()
        self._normalize_news()
        self._normalize_financials()
        logger.info(
            "[Workflow] Step 5 — Normalized: %d contacts, %d news articles",
            len(self.state.normalized_contacts),
            len(self.state.normalized_news),
        )

    # ── Step 6: Store Raw Results ────────────────────────────────────────

    @listen(normalize_and_format)
    def store_raw_results(self):
        """Step 6: Persist raw results to DB — pure Python."""
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(self._store_raw())
            logger.info("[Workflow] Step 6 — Stored raw results")
        finally:
            loop.close()

    # ── Step 7: LLM Intelligence (SINGLE CALL) ──────────────────────────

    @listen(store_raw_results)
    def llm_intelligence(self):
        """Step 7: SINGLE LLM call — fill gaps, dedup, score, insights.

        The LLM receives ALL pre-fetched data as context.
        It does NOT call any APIs or decide control flow.
        """
        from app.flows.llm_processor import run_intelligence

        logger.info("[Workflow] Step 7 — Starting single LLM call for '%s'", self.state.company_name)
        self.state.llm_output = run_intelligence(
            company_name=self.state.company_name,
            contacts=self.state.normalized_contacts,
            news=self.state.normalized_news,
            financials=self.state.normalized_financials,
            few_shot_examples=self.state.few_shot_examples,
        )
        logger.info("[Workflow] Step 7 — LLM call completed")

    # ── Step 8: Finalize & Store ─────────────────────────────────────────

    @listen(llm_intelligence)
    def finalize_and_store(self):
        """Step 8: Build final output and store — pure Python."""
        self.state.final_output = {
            "company_name": self.state.company_name,
            "pipeline": "workflow",
            "merged_contacts": self.state.llm_output.get("merged_contacts", []) if self.state.llm_output else [],
            "lead_scores": self.state.llm_output.get("lead_scores", {}) if self.state.llm_output else {},
            "executive_summary": self.state.llm_output.get("executive_summary", "") if self.state.llm_output else "",
            "recommendations": self.state.llm_output.get("recommendations", []) if self.state.llm_output else [],
            "dedup_summary": self.state.llm_output.get("dedup_summary", "") if self.state.llm_output else "",
            "raw_contact_count": sum(r.get("total", 0) for r in self.state.raw_contact_results),
            "raw_news_count": len(self.state.normalized_news),
            "fetch_errors": self.state.fetch_errors,
            "sources_used": self.state.enabled_tools,
        }

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(self._store_final())
            logger.info("[Workflow] Step 8 — Final output stored for '%s'", self.state.company_name)
        finally:
            loop.close()

    # =====================================================================
    # Private helpers (all deterministic Python)
    # =====================================================================

    async def _load_tool_configs(self) -> tuple[list[str], dict[str, dict[str, str]]]:
        """Query DB for enabled tools with valid API keys."""
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
        from app.config.settings import settings
        from app.db import repository as repo
        from app.tools.registry import AGENT_TOOL_ASSIGNMENTS

        engine = create_async_engine(settings.database_url, pool_size=1)
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        # Collect all tool names from agent assignments
        all_tools: set[str] = set()
        for tools in AGENT_TOOL_ASSIGNMENTS.values():
            all_tools.update(tools)

        enabled: list[str] = []
        configs: dict[str, dict[str, str]] = {}

        try:
            async with factory() as db:
                for tool_name in sorted(all_tools):
                    # Check DB for status
                    config = await repo.get_tool_config(db, tool_name)
                    is_enabled_in_db = config.is_enabled if config else True

                    # Fetch secrets from environment
                    env_config = settings.get_tool_config(tool_name)
                    api_key = env_config.get("api_key")
                    base_url = env_config.get("base_url")

                    # Decide if tool can be used
                    if is_enabled_in_db and api_key:
                        enabled.append(tool_name)
                        configs[tool_name] = {
                            "api_key": api_key,
                            "base_url": base_url or "",
                        }
                    else:
                        reason = "no API key in env" if not api_key else "disabled in admin"
                        logger.info("[Workflow] Skipping tool '%s': %s", tool_name, reason)
        finally:
            await engine.dispose(close=False)

        return enabled, configs

    async def _fetch_all(self) -> None:
        """Call all enabled APIs concurrently with asyncio.gather."""
        from app.flows.data_fetchers import FETCHER_MAP

        tasks = []
        task_names: list[str] = []
        for name in self.state.enabled_tools:
            if name in FETCHER_MAP:
                tasks.append(
                    FETCHER_MAP[name](
                        self.state.company_name,
                        self.state.tool_configs.get(name, {}),
                    )
                )
                task_names.append(name)

        if not tasks:
            logger.warning("[Workflow] No APIs enabled — nothing to fetch")
            return

        results = await asyncio.gather(*tasks, return_exceptions=True)

        for name, result in zip(task_names, results):
            if isinstance(result, Exception):
                self.state.fetch_errors.append({
                    "tool": name,
                    "error": str(result),
                    "retries": 0,
                })
                logger.warning("[Workflow] Fetch failed for '%s': %s", name, result)
            elif name in ("lusha", "apollo", "signal_hire"):
                self.state.raw_contact_results.append(result)
            elif name == "news_search":
                self.state.raw_news_results.append(result)
            elif name == "financial_data":
                self.state.raw_financial_results.append(result)

    async def _retry_failed(self) -> None:
        """Retry failed API fetches one more time."""
        from app.flows.data_fetchers import FETCHER_MAP

        still_failed: list[dict[str, Any]] = []
        for err in self.state.fetch_errors:
            name = err["tool"]
            if name not in FETCHER_MAP:
                still_failed.append(err)
                continue
            try:
                result = await FETCHER_MAP[name](
                    self.state.company_name,
                    self.state.tool_configs.get(name, {}),
                )
                if name in ("lusha", "apollo", "signal_hire"):
                    self.state.raw_contact_results.append(result)
                elif name == "news_search":
                    self.state.raw_news_results.append(result)
                elif name == "financial_data":
                    self.state.raw_financial_results.append(result)
                logger.info("[Workflow] Retry succeeded for '%s'", name)
            except Exception as e:
                still_failed.append({"tool": name, "error": str(e), "retries": 1})
                logger.warning("[Workflow] Retry also failed for '%s': %s", name, e)

        self.state.fetch_errors = still_failed

    def _normalize_contacts(self) -> None:
        """Flatten and normalize all contact results from different API sources."""
        from app.agents.normalizer import _score_title, _clamp

        all_contacts: list[dict[str, Any]] = []
        for result in self.state.raw_contact_results:
            source = result.get("source", "unknown")
            for contact in result.get("contacts", []):
                contact["source_tool"] = source
                # Apply deterministic title scoring
                title = contact.get("title", "")
                if title:
                    contact["decision_maker_score"] = _score_title(title)
                all_contacts.append(contact)

        self.state.normalized_contacts = all_contacts

    def _normalize_news(self) -> None:
        """Flatten news articles from all sources."""
        articles: list[dict[str, Any]] = []
        for result in self.state.raw_news_results:
            for article in result.get("articles", []):
                article["source_api"] = result.get("source", "unknown")
                articles.append(article)
        self.state.normalized_news = articles

    def _normalize_financials(self) -> None:
        """Take the first financial result (typically one source)."""
        if self.state.raw_financial_results:
            self.state.normalized_financials = self.state.raw_financial_results[0].get("financials", {})
        else:
            self.state.normalized_financials = {}

    async def _store_raw(self) -> None:
        """Store raw API results in existing result tables."""
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
        from app.config.settings import settings
        from app.db import repository as repo

        req_id = uuid.UUID(self.state.request_id) if self.state.request_id else None
        if not req_id:
            return

        engine = create_async_engine(settings.database_url, pool_size=1)
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        try:
            async with factory() as db:
                # Store contact results
                if self.state.raw_contact_results:
                    await repo.save_contact_result(
                        db,
                        request_id=req_id,
                        raw_response=json.dumps(self.state.raw_contact_results, default=str),
                        source_tool=",".join(r.get("source", "") for r in self.state.raw_contact_results),
                    )

                # Store news results
                if self.state.raw_news_results:
                    await repo.save_news_result(
                        db,
                        request_id=req_id,
                        raw_response=json.dumps(self.state.raw_news_results, default=str),
                        source_tool=",".join(r.get("source", "") for r in self.state.raw_news_results),
                    )

                # Store financial results
                if self.state.raw_financial_results:
                    await repo.save_financial_result(
                        db,
                        request_id=req_id,
                        raw_response=json.dumps(self.state.raw_financial_results, default=str),
                        source_tool=",".join(r.get("source", "") for r in self.state.raw_financial_results),
                    )

                await db.commit()
        finally:
            await engine.dispose(close=False)

    async def _store_final(self) -> None:
        """Store the final enriched lead output and update request status."""
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
        from app.config.settings import settings
        from app.db import repository as repo

        req_id = uuid.UUID(self.state.request_id) if self.state.request_id else None
        if not req_id:
            return

        engine = create_async_engine(settings.database_url, pool_size=1)
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        try:
            async with factory() as db:
                # Save enriched lead
                await repo.save_enriched_lead(
                    db,
                    request_id=req_id,
                    company_name=self.state.company_name,
                    enrichment_summary=json.dumps(self.state.final_output, default=str),
                    salesforce_lead_id=self.state.salesforce_lead_id,
                )

                # Update request status to completed
                await repo.update_request_status(db, req_id, "completed")

                await db.commit()
        finally:
            await engine.dispose(close=False)
