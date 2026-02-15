"""News enrichment agent – researches company news and press."""

from crewai import Agent

from app.config.settings import settings
from app.tools.news_search import search_company_news


def create_news_agent() -> Agent:
    """Build the Company News Analyst agent."""
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
        tools=[search_company_news],
        verbose=True,
        allow_delegation=False,
        max_iter=5,
        llm=settings.openai_model_name,
    )
