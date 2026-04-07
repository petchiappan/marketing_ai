"""Web search tool for CrewAI – generic web queries to fill data gaps."""

from __future__ import annotations

from crewai.tools import tool


@tool("Perform web search")
def perform_web_search(query: str) -> str:
    """
    Search the web for specific information about a company or individual.
    Use this to find missing data points not covered by specialized APIs.

    Returns a JSON string of web search results.
    """
    import asyncio
    from redis import Redis
    from app.config.settings import settings
    
    # We use a synchronous redis client here since CrewAI tool execution is synchronous
    try:
        # Simulated API call failure point
        return (
            f'{{"source_tool": "web_search", "query": "{query}", '
            f'"results": [], "note": "Placeholder – configure Web Search API key in admin panel"}}'
        )
    except Exception as e:
        # Feature 5: Redis Circuit Breaker Increment
        try:
            r = Redis.from_url(settings.redis_url)
            r.incr("web_search_failures")
            r.expire("web_search_failures", 300) # 5m rolling window
        except Exception as redis_err:
            pass # Failsafe
        
        return f'{{"error": "Search API Failed", "details": "{str(e)}"}}'
