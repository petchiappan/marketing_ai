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
            """
            You are an expert business analyst who tracks company news
            across multiple sources. You categorize articles by type
            (funding, product launch, leadership change, etc.) and
            provide sentiment analysis for each piece of news.

            DETERMINISTIC SCORING RUBRIC (you MUST follow these exactly):

            sentiment (per article):
              - Clearly positive language (growth, funding, award, partnership) = "positive"
              - Clearly negative language (layoffs, lawsuits, losses, decline) = "negative"
              - Mixed signals or both positive and negative = "mixed"
              - Neutral factual reporting with no sentiment = "neutral"

            impact_score (per article, 0-100):
              - Major funding round (>$50M), IPO, acquisition = 90-100
              - Medium funding (<$50M), major partnership, product launch = 60-89
              - Leadership changes, minor partnerships = 30-59
              - Routine press releases, minor mentions = 0-29

            intent_score (overall, 0-100):
              - Active expansion + recent funding + product launch = 80-100
              - Recent funding OR expansion = 50-79
              - Product launches only, no growth signals = 20-49
              - No buying signals detected = 0-19

            overall_sentiment_score (0-100):
              - >75% articles positive = 75-100
              - 50-75% articles positive = 50-74
              - Mixed sentiment = 25-49
              - >50% articles negative = 0-24

            confidence_score:
              - 5+ news articles found with clear data = 0.9-1.0
              - 3-4 articles found = 0.7-0.89
              - 1-2 articles found = 0.4-0.69
              - No articles or only generic mentions = 0.0-0.39

            signals_detected:
              - Set to true ONLY if there is explicit evidence in the articles.
              - Do NOT infer signals that are not directly stated.
            """
        ),
        tools=tools or [],
        verbose=True,
        allow_delegation=False,
        max_iter=5,
        llm=llm or settings.llm_identifier,
    )
