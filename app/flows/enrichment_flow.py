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

    def _log(self, message: str):
        """Append a timestamped log entry to activity_log and also emit to Python logger."""
        from datetime import datetime
        ts = datetime.now().strftime("%H:%M:%S")
        entry = f"[{ts}] {message}"
        self.state.activity_log.append(entry)
        logger.info(message)

    # ── Step 1: Validate ─────────────────────────────────────────────────

    @start()
    def validate_input(self):
        """Step 1: Validate input — pure Python."""
        if not self.state.company_name:
            raise ValueError("company_name is required")
        self._log("[Workflow] Step 1 — Validated input for: %s" % self.state.company_name)

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
            if enabled:
                self._log("[Workflow] Step 2 — Selected APIs: %s" % enabled)
            else:
                self._log("[Workflow] Step 2 — ⚠ No APIs enabled/configured. Will rely on LLM + Fallback.")
        finally:
            loop.close()

    # ── Step 3: Fetch Data ───────────────────────────────────────────────

    @listen(select_apis)
    def fetch_data(self):
        """Step 3: Fetch data in parallel — httpx + tenacity, no LLM."""
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(self._fetch_all())
            self._log(
                "[Workflow] Step 3 — Fetched: %d contact sources, %d news sources, %d financial sources"
                % (len(self.state.raw_contact_results), len(self.state.raw_news_results), len(self.state.raw_financial_results))
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
                self._log(
                    "[Workflow] Step 4 — ⚠ Still failed after retries: %s"
                    % [e["tool"] for e in self.state.fetch_errors]
                )
            else:
                self._log("[Workflow] Step 4 — All fetches OK")
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
        self._log(
            "[Workflow] Step 5 — Normalized: %d contacts, %d news articles"
            % (len(self.state.normalized_contacts), len(self.state.normalized_news))
        )

    # ── Step 6: Store Raw Results ────────────────────────────────────────

    @listen(normalize_and_format)
    def store_raw_results(self):
        """Step 6: Persist raw results to DB — pure Python."""
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(self._store_raw())
            self._log("[Workflow] Step 6 — Stored raw results")
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

        self._log("[Workflow] Step 7 — Starting single LLM call for '%s'" % self.state.company_name)
        self.state.llm_output = run_intelligence(
            company_name=self.state.company_name,
            contacts=self.state.normalized_contacts,
            news=self.state.normalized_news,
            financials=self.state.normalized_financials,
            few_shot_examples=self.state.few_shot_examples,
        )
        self._log("[Workflow] Step 7 — LLM call completed. Parse error: %s" % self.state.llm_output.get("parse_error", False) if self.state.llm_output else "No output")

    # ── Step 7b: Hybrid Escalation Trigger ───────────────────────────────

    @listen(llm_intelligence)
    def hybrid_trigger(self):
        """Step 7b: Evaluate data and trigger Fallback Agent if needed.

        Checks confidence score and completeness of the contacts.
        If threshold fails, builds Target_Gap and calls the Fallback Agent.
        ALSO force-triggers when no APIs were used (LLM data is hallucinated).
        """
        if not self.state.llm_output:
            self._log("[Workflow] Step 7b — No LLM output. Skipping fallback.")
            return

        # ── Force-trigger when NO APIs were used ──
        # If enabled_tools is empty, the LLM received empty data and
        # hallucinated everything. We MUST go to fallback for real data.
        no_real_data = not self.state.enabled_tools
        if no_real_data:
            self._log("[Workflow] Step 7b — ⚠ No APIs were enabled. LLM output is based on empty data (likely hallucinated). Forcing fallback.")

        scores = self.state.llm_output.get("lead_scores", {})
        confidence = float(scores.get("confidence_score", 1.0))
        contacts = self.state.llm_output.get("merged_contacts", [])

        self._log("[Workflow] Step 7b — Evaluating: confidence=%.2f, contacts=%d" % (confidence, len(contacts)))

        # Logic for determining gap
        gap = []

        if no_real_data:
            # Force all gaps when no APIs were used
            gap.extend(["ceo_email", "company_phone_number", "recent_company_news", "revenue", "overall_confidence_improvement"])
            self._log("[Workflow] Step 7b — Forced full gap list (no APIs): %s" % gap)
        else:
            if confidence <= 0.70:
                gap.append("overall_confidence_improvement")
            
            has_ceo_email = False
            has_phone = False
            for c in contacts:
                if "ceo" in str(c.get("title", "")).lower() and c.get("email"):
                    has_ceo_email = True
                if c.get("phone"):
                    has_phone = True

            if not has_ceo_email:
                gap.append("ceo_email")
            if not has_phone:
                gap.append("company_phone_number")
                
            news_summary = self.state.llm_output.get("news_summary", [])
            if not news_summary:
                gap.append("recent_company_news")
                
            financials = self.state.llm_output.get("financials_summary", {})
            if not financials or not financials.get("revenue"):
                gap.append("revenue")
        
        # If no gaps, we skip fallback
        if not gap:
            self._log("[Workflow] Step 7b — No gaps detected. Fallback skipped.")
            return

        self.state.target_gap = gap
        self.state.fallback_triggered = True

        self._log("[Workflow] Step 7b — Hybrid trigger activated. Target_Gap: %s" % gap)

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(self._run_hybrid_fallback(gap))
        except Exception as e:
            self._log("[Workflow] Step 7b — ⚠ Fallback execution failed completely: %s" % e)
        finally:
            loop.close()

    async def _run_hybrid_fallback(self, gap: list[str]):
        """Feature 2, 3, 5: Run fallback with Circuit Breaker, Redis Cache, and asyncio 30s timeouts."""
        import redis.asyncio as aioredis
        from app.config.settings import settings
        
        try:
            r = aioredis.from_url(settings.redis_url)
            self._log("[Workflow] Step 7b — Connected to Redis for caching")
        except Exception as e:
            self._log("[Workflow] Step 7b — Redis unavailable: %s" % e)
            r = None
            
        # 1. CIRCUIT BREAKER (Feature 5)
        if r:
            try:
                failures = int(await r.get("web_search_failures") or 0)
                if failures >= 5:
                    self._log("[Workflow] Step 7b — ⚠ Circuit Breaker OPEN (>= 5 web failures). Skipping fallback.")
                    return
            except Exception as e:
                logger.debug("Redis circuit breaker check failed: %s", e)
                
        # 2. AGENT CACHING (Feature 3)
        cache_hits = {}
        actual_gap = []
        if r:
            for g in gap:
                try:
                    cached = await r.get(f"agent_cache:{self.state.company_name}:{g}")
                    if cached:
                        cache_hits[g] = cached.decode("utf-8")
                    else:
                        actual_gap.append(g)
                except Exception:
                    actual_gap.append(g)
        else:
            actual_gap = gap
            
        if not actual_gap:
            self._log("[Workflow] Step 7b — All gap elements recovered from Redis cache!")
            self.state.fallback_recovered_data = cache_hits
            for k in cache_hits:
                self.state.enrichment_source[k] = "Redis_Cache"
            return
            
        from app.agents.fallback_agent import run_fallback, run_llm_only_fallback
        from app.tools.registry import get_agent_tool_assignments, resolve_tools
        import concurrent.futures

        tool_assignments = get_agent_tool_assignments()
        fallback_tool_names = tool_assignments.get("fallback_agent", ["web_search", "news_search"])
        fallback_tools = resolve_tools(fallback_tool_names)

        fallback_result = {}
        loop = asyncio.get_running_loop()

        if not fallback_tools:
            # ── NO TOOLS ATTACHED → Pure LLM Fallback ──
            self._log("[Workflow] Step 7b — No fallback tools resolved. Routing to LLM-only fallback agent.")
            try:
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    fallback_result = await asyncio.wait_for(
                        loop.run_in_executor(
                            pool,
                            lambda: run_llm_only_fallback(
                                company_name=self.state.company_name,
                                partial_data=self.state.llm_output or {},
                                target_gap=actual_gap,
                            )
                        ),
                        timeout=30.0
                    )
            except asyncio.TimeoutError:
                self._log("[Workflow] Step 7b — ⚠ LLM-only fallback exceeded 30s timeout.")
            except Exception as e:
                self._log("[Workflow] Step 7b — ⚠ LLM-Only Fallback Error: %s" % e)
        else:
            # ── TOOLS AVAILABLE → Agent-based Fallback ──
            self._log("[Workflow] Step 7b — Running agent-based fallback with tools: %s" % fallback_tool_names)
            try:
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    fallback_result = await asyncio.wait_for(
                        loop.run_in_executor(
                            pool,
                            lambda: run_fallback(
                                company_name=self.state.company_name,
                                partial_data=self.state.llm_output or {},
                                target_gap=actual_gap,
                                tools=fallback_tools,
                            )
                        ),
                        timeout=30.0  # 30 second strict timeout
                    )
            except asyncio.TimeoutError:
                self._log("[Workflow] Step 7b — ⚠ Agent fallback exceeded 30s timeout.")
            except Exception as e:
                self._log("[Workflow] Step 7b — ⚠ Agent Fallback Error: %s" % e)
            
        recovered = fallback_result.get("recovered_data", {})
        
        # Merge hits
        recovered.update(cache_hits)
        
        # Add to source lineage
        fallback_source_label = "LLM_Only_Fallback" if not fallback_tools else "Agent_Fallback_Search"
        for k in recovered.keys():
            self.state.enrichment_source[k] = fallback_source_label if k not in cache_hits else "Redis_Cache"
        
        # Update cache for newly discovered items
        if r:
            for k, v in recovered.items():
                if k not in cache_hits and v is not None:
                    try:
                        await r.setex(f"agent_cache:{self.state.company_name}:{k}", 2592000, str(v))
                    except Exception:
                        pass
                        
        self.state.fallback_recovered_data = recovered
        # Store fallback LLM I/O for debug
        self.state.additional_context["_fallback_prompt"] = fallback_result.get("_fallback_prompt", "")
        self.state.additional_context["_fallback_raw_output"] = fallback_result.get("_fallback_raw_output", fallback_result.get("raw_markdown", ""))
        self._log("[Workflow] Step 7b — Fallback complete. Recovered %d fields: %s" % (len(recovered), list(recovered.keys())))

    # ── Step 8: Finalize & Store ─────────────────────────────────────────

    @listen(hybrid_trigger)
    def finalize_and_store(self):
        """Step 8: Build final output and store — pure Python."""
        # Gather LLM debug I/O
        llm_debug = {}
        if self.state.llm_output:
            llm_debug["step7_prompt"] = self.state.llm_output.get("_llm_prompt", "")
            llm_debug["step7_raw_output"] = self.state.llm_output.get("_llm_raw_output", "")
        if self.state.fallback_triggered:
            llm_debug["fallback_prompt"] = self.state.additional_context.get("_fallback_prompt", "")
            llm_debug["fallback_raw_output"] = self.state.additional_context.get("_fallback_raw_output", "")

        self.state.final_output = {
            "company_name": self.state.company_name,
            "pipeline": "hybrid",
            "merged_contacts": self.state.llm_output.get("merged_contacts", []) if self.state.llm_output else [],
            "lead_scores": self.state.llm_output.get("lead_scores", {}) if self.state.llm_output else {},
            "executive_summary": self.state.llm_output.get("executive_summary", "") if self.state.llm_output else "",
            "recommendations": self.state.llm_output.get("recommendations", []) if self.state.llm_output else [],
            "news_summary": self.state.llm_output.get("news_summary", []) if self.state.llm_output else [],
            "financials_summary": self.state.llm_output.get("financials_summary", {}) if self.state.llm_output else {},
            "dedup_summary": self.state.llm_output.get("dedup_summary", "") if self.state.llm_output else "",
            "raw_contact_count": sum(r.get("total", 0) for r in self.state.raw_contact_results),
            "raw_news_count": len(self.state.normalized_news),
            "fetch_errors": self.state.fetch_errors,
            "sources_used": self.state.enabled_tools,
            "fallback_triggered": self.state.fallback_triggered,
            "fallback_recovered_data": self.state.fallback_recovered_data,
            "enrichment_source": self.state.enrichment_source,
            "activity_log": self.state.activity_log,
            "llm_debug": llm_debug,
        }

        # Setup standard deterministic sources (Feature 4)
        if self.state.llm_output:
            for c in self.state.llm_output.get("merged_contacts", []):
                sources = c.get("sources", ["API"])
                if c.get("email"):
                    self.state.enrichment_source["ceo_email" if "ceo" in str(c.get("title", "")).lower() else "contact_email"] = sources[0]
                if c.get("phone"):
                    self.state.enrichment_source["company_phone_number"] = sources[0]

        # Merge any specific items recovered directly into the root level of final_output
        if self.state.fallback_recovered_data:
            self.state.final_output.update(self.state.fallback_recovered_data)

        # Import sync module
        from app.services.salesforce_sync import sync_lead_to_salesforce

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(self._store_final())
            self._log("[Workflow] Step 8 — Final output stored for '%s'" % self.state.company_name)
            
            # Fire the webhook
            self._log("[Workflow] Step 8b — Syncing to Salesforce Webhook")
            loop.run_until_complete(sync_lead_to_salesforce(self.state.final_output, self.state.salesforce_lead_id))
            self._log("[Workflow] ✅ Pipeline complete for '%s'" % self.state.company_name)
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
        enabled_grouped: dict[str, list[str]] = {}
        configs: dict[str, dict[str, str]] = {}

        try:
            async with factory() as db:
                for tool_name in sorted(all_tools):
                    # Check DB for status
                    config = await repo.get_tool_config(db, tool_name)
                    is_enabled_in_db = config.is_enabled if config else True

                    # Fetch secrets from DB
                    api_key = config.api_key if config and config.api_key else None
                    category = config.category if config and config.category else "contact"
                    sequence = config.sequence_number if config and config.sequence_number else 1

                    # Decide if tool can be used
                    if is_enabled_in_db and api_key:
                        enabled.append(tool_name)
                        configs[tool_name] = {
                            "api_key": api_key,
                            "sequence": sequence,
                        }
                        if category not in enabled_grouped:
                            enabled_grouped[category] = []
                        enabled_grouped[category].append((sequence, tool_name))
                    else:
                        reason = "no API key in DB config" if not api_key else "disabled in admin"
                        logger.info("[Workflow] Skipping tool '%s': %s", tool_name, reason)
                
                for cat in enabled_grouped:
                    enabled_grouped[cat] = [t[1] for t in sorted(enabled_grouped[cat], key=lambda x: x[0])]

                self.state.enabled_tools_grouped = enabled_grouped
        finally:
            await engine.dispose(close=False)

        return enabled, configs

    async def _fetch_all(self) -> None:
        """Call allowed APIs sequentially grouped by category using a waterfall approach to save API credits."""
        from app.flows.data_fetchers import FETCHER_MAP

        if not self.state.enabled_tools_grouped:
            logger.warning("[Workflow] No APIs enabled — nothing to fetch")
            return

        async def process_category(category: str, tools: list[str]):
            for name in tools:
                if name not in FETCHER_MAP:
                    continue
                try:
                    logger.info("[Workflow] Fetching Data (Category: %s | Tool: %s)", category, name)
                    result = await FETCHER_MAP[name](
                        self.state.company_name,
                        self.state.tool_configs.get(name, {}),
                    )
                    
                    if category == "contact":
                        self.state.raw_contact_results.append(result)
                        if isinstance(result, dict) and (result.get("emails") or result.get("phone_numbers")):
                             logger.info("[Workflow] ✅ Stop condition met for %s via %s. Short-circuiting remaining sequence.", category, name)
                             break
                    elif category == "news":
                        self.state.raw_news_results.append(result)
                        if isinstance(result, list) and len(result) > 0:
                             logger.info("[Workflow] ✅ Stop condition met for %s via %s", category, name)
                             break
                    elif category == "financial":
                        self.state.raw_financial_results.append(result)
                        if isinstance(result, dict) and result.get("revenue_range"):
                             logger.info("[Workflow] ✅ Stop condition met for %s via %s", category, name)
                             break
                except Exception as e:
                    self.state.fetch_errors.append({
                        "tool": name,
                        "error": str(e),
                        "retries": 0,
                    })
                    logger.warning("[Workflow] Fetch failed for '%s': %s", name, e)

        tasks = []
        for cat, tools in self.state.enabled_tools_grouped.items():
            tasks.append(process_category(cat, tools))

        await asyncio.gather(*tasks)

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
                )

                # Update request status to completed
                await repo.update_request_status(db, req_id, "completed")

                await db.commit()
        finally:
            await engine.dispose(close=False)
