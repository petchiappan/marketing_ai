"""Public endpoints for the Company Intelligence dashboard (Next.js SPA)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import settings
from app.db import repository as repo
from app.db.session import get_db

router = APIRouter(prefix="/api", tags=["intelligence-dashboard"])

CONTACT_TOOL_NAMES = frozenset({"lusha", "apollo", "signal_hire"})
NEWS_TOOL_NAME = "news_search"
FINANCE_TOOL_NAME = "financial_data"


class ConnectorStatusOut(BaseModel):
    """Maps to the prompt’s three-pill status bar + LLM."""

    lusha: bool  # “contacts” — any contact-data tool ready
    news: bool
    finance: bool
    llm: bool


@router.get("/connectors/status", response_model=ConnectorStatusOut)
async def connectors_status(db: AsyncSession = Depends(get_db)):
    """
    Whether contact / news / financial tools are enabled and configured,
    and whether an LLM key is set (required for CrewAI).
    """
    tools = await repo.list_tool_configs(db)
    by_name = {t.tool_name: t for t in tools}

    def tool_ready(name: str) -> bool:
        t = by_name.get(name)
        if not t or not t.is_enabled:
            return False
        return bool(t.api_key_encrypted)

    contacts = any(tool_ready(n) for n in CONTACT_TOOL_NAMES)
    # News/finance tools may run as placeholders without keys; treat “enabled” as ready for UI
    news_t = by_name.get(NEWS_TOOL_NAME)
    finance_t = by_name.get(FINANCE_TOOL_NAME)
    news_ok = bool(news_t and news_t.is_enabled)
    finance_ok = bool(finance_t and finance_t.is_enabled)

    return ConnectorStatusOut(
        lusha=contacts,
        news=news_ok,
        finance=finance_ok,
        llm=bool(settings.openai_api_key or settings.google_api_key or settings.anthropic_api_key),
    )
