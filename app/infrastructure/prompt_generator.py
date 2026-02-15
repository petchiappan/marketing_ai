"""Dynamic prompt generator for enrichment agents."""

from __future__ import annotations

from typing import Any


class PromptGenerator:
    """
    Generates agent prompts dynamically based on input context.

    Adapts instructions to:
    - Public vs private company (financial data approach)
    - Industry vertical (news search keywords)
    - Available Salesforce context (avoids re-fetching)
    - Agent success/failure states (aggregation instructions)
    """

    # ------------------------------------------------------------------
    # Contact Agent
    # ------------------------------------------------------------------

    def build_contact_prompt(self, company: str, context: dict[str, Any]) -> str:
        industry = context.get("industry", "")
        known_contacts = context.get("known_contacts", [])

        exclusion = ""
        if known_contacts:
            names = ", ".join(known_contacts)
            exclusion = f"\n\nWe already have the following contacts — do NOT re-fetch them: {names}."

        industry_hint = ""
        if industry:
            industry_hint = f"\nThis company operates in the **{industry}** industry."

        return f"""You are a Contact Research Specialist.

Your task is to find key decision-maker contacts at **{company}**.
{industry_hint}
Focus on:
- C-suite executives (CEO, CTO, CFO, CMO)
- VP-level and Director-level leaders
- Relevant department heads

For each contact, gather:
- Full name
- Job title
- Business email
- Phone number (if available)
- LinkedIn profile URL

Use all available tools (Lusha, Apollo, Signal Hire) to cross-reference
and maximize data coverage. Assign a confidence score (0.0–1.0) to each
contact based on source reliability and data freshness.
{exclusion}

Return your results as a JSON array of contact objects."""

    # ------------------------------------------------------------------
    # News Agent
    # ------------------------------------------------------------------

    def build_news_prompt(self, company: str, context: dict[str, Any]) -> str:
        industry = context.get("industry", "")
        time_range = context.get("news_time_range", "last 6 months")

        topic_filters = ""
        if industry:
            topic_filters = f"\nPay special attention to {industry}-specific news."

        return f"""You are a Company News Analyst.

Your task is to research recent news and publicly available information
about **{company}** from the {time_range}.
{topic_filters}
Focus on:
- Product launches and major announcements
- Funding rounds and financial events
- Leadership changes and key hires
- Partnerships and acquisitions
- Market positioning and competitive moves

For each news item, provide:
- Headline
- Summary (2–3 sentences)
- Source URL
- Publication date
- Sentiment (positive / negative / neutral / mixed)
- Relevance score (0.0–1.0)
- Category (product_launch, funding, leadership, partnership, etc.)

Return your results as a JSON array of news objects."""

    # ------------------------------------------------------------------
    # Financial Agent
    # ------------------------------------------------------------------

    def build_financial_prompt(self, company: str, context: dict[str, Any]) -> str:
        is_public = context.get("is_public", None)

        strategy = ""
        if is_public is True:
            strategy = """
This is a **publicly traded company**. Use Yahoo Finance and SEC EDGAR
to retrieve official financial filings, stock data, and market cap."""
        elif is_public is False:
            strategy = """
This is a **private company**. Use Crunchbase and other sources for
funding information. Revenue and market cap may be estimated."""
        else:
            strategy = """
Determine whether this company is publicly traded or private, then
adapt your data sources accordingly."""

        return f"""You are a Financial Data Analyst.

Your task is to gather financial statistics about **{company}**.
{strategy}

Retrieve the following data points:
- Annual revenue (and currency)
- Total funding raised
- Latest funding round
- Market capitalization (if public)
- Employee count
- Industry classification
- Fiscal year
- Headquarters location

Assign a confidence score (0.0–1.0) to the overall financial profile
based on data recency and source reliability.

Return your results as a JSON object."""

    # ------------------------------------------------------------------
    # Aggregation Agent
    # ------------------------------------------------------------------

    def build_aggregation_prompt(
        self, company: str, partial_results: dict[str, Any]
    ) -> str:
        available = []
        missing = []

        for agent in ("contact", "news", "financial"):
            if partial_results.get(agent):
                available.append(agent)
            else:
                missing.append(agent)

        available_str = ", ".join(available) if available else "none"
        missing_str = ", ".join(missing) if missing else "none"

        return f"""You are a Lead Intelligence Synthesizer.

Your task is to merge and deduplicate the enrichment data collected
about **{company}** into a unified lead profile.

**Available data sources:** {available_str}
**Missing/failed sources:** {missing_str}

Instructions:
1. **Contacts**: Deduplicate by name/email. Keep the highest-confidence
   version of each contact. Merge supplementary fields from other sources.
2. **News**: Remove duplicate articles. Rank by relevance.
   Compute an overall sentiment score.
3. **Financial**: Use the most recent and highest-confidence data.
   Flag any contradictions between sources.
4. **Executive Summary**: Write a 3–5 sentence overview of the company
   covering its market position, recent activity, and key contacts.
5. **Confidence Score**: Compute an overall confidence (0.0–1.0).
   Degrade proportionally for missing sources.

Return a single JSON object matching the EnrichedLead schema."""


# Module-level singleton
prompt_generator = PromptGenerator()
