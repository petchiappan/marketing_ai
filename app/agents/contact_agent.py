"""Contact enrichment agent – finds key decision-maker contacts."""

from crewai import Agent

from app.config.settings import settings
from app.tools.lusha import search_lusha
from app.tools.apollo import search_apollo
from app.tools.signal_hire import search_signal_hire


def create_contact_agent() -> Agent:
    """Build the Contact Research Specialist agent."""
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
        tools=[search_lusha, search_apollo, search_signal_hire],
        verbose=True,
        allow_delegation=False,
        max_iter=5,
        llm=settings.openai_model_name,
    )
