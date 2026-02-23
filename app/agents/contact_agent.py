"""Contact enrichment agent – finds key decision-maker contacts."""

from __future__ import annotations

from crewai import Agent

from app.config.settings import settings


def create_contact_agent(tools: list | None = None, llm: str | None = None) -> Agent:
    """Build the Contact Research Specialist agent.

    Args:
        tools: List of CrewAI tool functions this agent can use.
        llm: LLM identifier string (e.g. 'openai/gpt-4o-mini').
             Defaults to settings.llm_identifier.
    """
    return Agent(
        role="Contact Research Specialist",
        goal=(
            "Find key decision-maker contacts (C-suite, VP, Director) "
            "at the target company with verified emails, phone numbers, "
            "and LinkedIn URLs."
        ),
        backstory=(
            "You are an expert at finding business contacts using multiple "
            "data providers. You cross-reference sources to ensure accuracy "
            "and assign confidence scores to each contact based on data "
            "freshness and source reliability."
        ),
        tools=tools or [],
        verbose=True,
        allow_delegation=False,
        max_iter=5,
        llm=llm or settings.llm_identifier,
    )
