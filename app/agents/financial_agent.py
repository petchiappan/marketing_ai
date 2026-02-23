"""Financial enrichment agent – retrieves company financials."""

from __future__ import annotations

from crewai import Agent

from app.config.settings import settings


def create_financial_agent(tools: list | None = None, llm: str | None = None) -> Agent:
    """Build the Financial Data Analyst agent.

    Args:
        tools: List of CrewAI tool functions this agent can use.
        llm: LLM identifier string (e.g. 'anthropic/claude-3-5-sonnet-20241022').
             Defaults to settings.llm_identifier.
    """
    return Agent(
        role="Financial Data Analyst",
        goal=(
            "Gather comprehensive financial statistics about the target "
            "company including revenue, funding, market cap, employee "
            "count, and industry classification."
        ),
        backstory=(
            "You are a financial research specialist who extracts key "
            "financial metrics from public filings, databases, and "
            "financial platforms. You distinguish between verified data "
            "and estimates, and assign confidence scores accordingly."
        ),
        tools=tools or [],
        verbose=True,
        allow_delegation=False,
        max_iter=5,
        llm=llm or settings.llm_identifier,
    )
