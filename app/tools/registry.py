"""Tool registry – maps tool_name (from ToolConfig DB) → Python tool function."""

from __future__ import annotations

import logging

from app.tools.lusha import search_lusha
from app.tools.apollo import search_apollo
from app.tools.signal_hire import search_signal_hire
from app.tools.news_search import search_company_news
from app.tools.financial_data import fetch_financial_data
from app.tools.web_search import perform_web_search

logger = logging.getLogger(__name__)

# Maps the tool_name stored in DB (tool_configs.tool_name) → CrewAI tool function.
# When adding a new tool, register it here so it can be assigned via the admin panel.
TOOL_REGISTRY: dict[str, object] = {
    "lusha": search_lusha,
    "apollo": search_apollo,
    "signal_hire": search_signal_hire,
    "news_search": search_company_news,
    "financial_data": fetch_financial_data,
    "web_search": perform_web_search,
}


def resolve_tools(tool_names: list[str]) -> list:
    """Given a list of tool_name strings, return the corresponding Python tool functions."""
    logger.info("resolve_tools called with: %s", tool_names)
    tools = []
    for name in tool_names:
        fn = TOOL_REGISTRY.get(name)
        if fn:
            logger.info("  ✔ Tool '%s' found in registry", name)
            tools.append(fn)
        else:
            logger.warning("  ✘ Tool '%s' NOT found in registry (available: %s)", name, list(TOOL_REGISTRY.keys()))
    logger.info("resolve_tools returning %d tools", len(tools))
    return tools


# Hardcoded agent → tool assignments (replaces DB-driven assignment).
# To add/remove tools from an agent, edit this mapping.
AGENT_TOOL_ASSIGNMENTS: dict[str, list[str]] = {
    "contact_agent": ["lusha", "apollo", "signal_hire"],
    "news_agent": ["news_search"],
    "financial_agent": ["financial_data"],
    "fallback_agent": ["web_search", "news_search"],
}


def get_agent_tool_assignments() -> dict[str, list[str]]:
    """Return the hardcoded agent→tool-name mapping.

    This is the single source of truth for which tools each agent receives.
    """
    return dict(AGENT_TOOL_ASSIGNMENTS)

