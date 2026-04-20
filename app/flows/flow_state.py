"""Pydantic structured state shared across all workflow steps."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel


class EnrichmentState(BaseModel):
    """Typed state for the deterministic enrichment flow.

    Passed between ``@start`` / ``@listen`` steps via ``self.state``.
    """

    # ── Input ──
    request_id: str = ""
    company_name: str = ""
    salesforce_lead_id: Optional[str] = None
    source: str = "api"
    additional_context: dict[str, Any] = {}

    # ── Step 2: API selection (code decides, not LLM) ──
    enabled_tools: list[str] = []
    enabled_tools_grouped: dict[str, list[str]] = {}
    tool_configs: dict[str, dict[str, str]] = {}

    # ── Step 3: Raw API responses ──
    raw_contact_results: list[dict[str, Any]] = []
    raw_news_results: list[dict[str, Any]] = []
    raw_financial_results: list[dict[str, Any]] = []
    fetch_errors: list[dict[str, Any]] = []

    # ── Step 5: Normalized data ──
    normalized_contacts: list[dict[str, Any]] = []
    normalized_news: list[dict[str, Any]] = []
    normalized_financials: dict[str, Any] = {}

    # ── LLM output ──
    llm_output: Optional[dict[str, Any]] = None

    target_gap: list[str] = []
    fallback_triggered: bool = False
    fallback_recovered_data: dict[str, Any] = {}
    enrichment_source: dict[str, str] = {}

    # ── Final ──
    final_output: Optional[dict[str, Any]] = None

    # ── Few-shot examples from feedback loop ──
    few_shot_examples: list[dict[str, Any]] = []

    # ── Activity Log (for admin debugging) ──
    activity_log: list[str] = []
