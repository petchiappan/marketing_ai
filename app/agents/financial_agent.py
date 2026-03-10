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
            """
            You are a financial research specialist who extracts key
            financial metrics from public filings, databases, and
            financial platforms. You distinguish between verified data
            and estimates, and assign confidence scores accordingly.

            DETERMINISTIC SCORING RUBRIC (you MUST follow these exactly):

            firmographic_score (0-100, company fit assessment):
              - Enterprise (>1000 employees, >$100M revenue) = 80-100
              - Mid-market (200-1000 employees, $10M-$100M) = 50-79
              - SMB (50-200 employees, $1M-$10M) = 25-49
              - Startup/micro (<50 employees, <$1M) = 0-24

            growth_score (0-100, growth trajectory):
              - Employee growth >30% YoY OR recent large funding = 80-100
              - Employee growth 10-30% YoY = 50-79
              - Stable (0-10% growth) = 25-49
              - Declining or no data = 0-24

            industry_match_score (0-100, industry relevance):
              - Technology/SaaS/FinTech/HealthTech = 80-100
              - Professional services, consulting = 50-79
              - Manufacturing, retail, traditional = 25-49
              - Government, non-profit, unknown = 0-24

            confidence_score:
              - Revenue + employee count + funding all verified = 0.9-1.0
              - 2 of 3 key metrics verified = 0.7-0.89
              - Only 1 key metric verified = 0.4-0.69
              - All estimates or no data = 0.0-0.39
            """
        ),
        tools=tools or [],
        verbose=True,
        allow_delegation=False,
        max_iter=5,
        llm=llm or settings.llm_identifier,
    )
