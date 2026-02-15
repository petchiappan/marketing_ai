"""Aggregation agent – synthesizes outputs from all enrichment agents."""

from crewai import Agent

from app.config.settings import settings


def create_aggregation_agent() -> Agent:
    """Build the Lead Intelligence Synthesizer agent."""
    return Agent(
        role="Lead Intelligence Synthesizer",
        goal=(
            "Merge, deduplicate, and synthesize all enrichment data "
            "into a unified, high-quality lead profile with an "
            "executive summary and overall confidence score."
        ),
        backstory=(
            "You are a data integration specialist who excels at "
            "merging data from multiple sources. You deduplicate "
            "contacts, reconcile conflicting financial data, rank "
            "news by relevance, and produce concise executive summaries."
        ),
        tools=[],  # No external tools – works on data from other agents
        verbose=True,
        allow_delegation=False,
        max_iter=3,
        llm=settings.openai_model_name,
    )
