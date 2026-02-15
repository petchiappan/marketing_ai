"""Financial enrichment agent – retrieves company financials."""

from crewai import Agent

from app.config.settings import settings
from app.tools.financial_data import fetch_financial_data


def create_financial_agent() -> Agent:
    """Build the Financial Data Analyst agent."""
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
        tools=[fetch_financial_data],
        verbose=True,
        allow_delegation=False,
        max_iter=5,
        llm=settings.openai_model_name,
    )
