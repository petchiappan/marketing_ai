"""Tool registry – maps tool_name (from ToolConfig DB) → Python tool function."""

from __future__ import annotations

from app.tools.lusha import search_lusha
from app.tools.apollo import search_apollo
from app.tools.signal_hire import search_signal_hire
from app.tools.news_search import search_company_news
from app.tools.financial_data import fetch_financial_data

# Maps the tool_name stored in DB (tool_configs.tool_name) → CrewAI tool function.
# When adding a new tool, register it here so it can be assigned via the admin panel.
TOOL_REGISTRY: dict[str, object] = {
    "lusha": search_lusha,
    "apollo": search_apollo,
    "signal_hire": search_signal_hire,
    "news_search": search_company_news,
    "financial_data": fetch_financial_data,
}


def resolve_tools(tool_names: list[str]) -> list:
    """Given a list of tool_name strings, return the corresponding Python tool functions."""
    tools = []
    for name in tool_names:
        fn = TOOL_REGISTRY.get(name)
        if fn:
            tools.append(fn)
    return tools
