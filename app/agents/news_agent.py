"""News enrichment agent – researches company news and press."""

from __future__ import annotations

from crewai import Agent

from app.config.settings import settings


def create_news_agent(tools: list | None = None, llm: str | None = None) -> Agent:
    """Build the Company News Analyst agent.

    Args:
        tools: List of CrewAI tool functions this agent can use.
        llm: LLM identifier string (e.g. 'gemini/gemini-2.5-flash').
             Defaults to settings.llm_identifier.
    """
    return Agent(
        role="Company News Analyst",
        goal=(
            "Research and compile recent news, press releases, "
            "and public information about the target company, "
            "including sentiment analysis and categorization."
        ),
        backstory=(
            "You are an expert business analyst who tracks company news "
            "across multiple sources. You categorize articles by type "
            "(funding, product launch, leadership change, etc.) and "
            "provide sentiment analysis for each piece of news."
        ),
        tools=tools or [],
        verbose=True,
        allow_delegation=False,
        max_iter=5,
        llm=llm or settings.llm_identifier,
    )
