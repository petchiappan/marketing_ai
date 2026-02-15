"""News and web search tool for CrewAI – retrieves company news."""

from __future__ import annotations

from crewai.tools import tool


@tool("Search company news")
def search_company_news(company_name: str) -> str:
    """
    Search for recent news articles about the given company using
    web search APIs (Bing News Search, Google News, etc.).

    Returns a JSON string of news articles with headline, summary,
    URL, published_date, sentiment, relevance_score, and category.
    """
    return (
        f'{{"source_tool": "news_search", "company": "{company_name}", '
        f'"articles": [], "note": "Placeholder – configure News Search API key in admin panel"}}'
    )
