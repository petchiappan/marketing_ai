"""LLM Response Cache – two-tier caching for deterministic results.

Tier 1 (LLM-only agents): Full cache-hit-and-skip.
Tier 2 (Tool-using agents): Always execute, then compare & update cache.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import settings
from app.db import repository as repo

logger = logging.getLogger(__name__)


def compute_cache_key(
    agent_name: str,
    prompt: str,
    model_name: str,
    tool_names: list[str] | None = None,
) -> str:
    """Generate a SHA-256 cache key from the input combination."""
    tools_sig = ",".join(sorted(tool_names or []))
    raw = f"{agent_name}|{prompt}|{model_name}|{tools_sig}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def compute_response_hash(response_text: str) -> str:
    """SHA-256 hash of the response text for comparison."""
    return hashlib.sha256(response_text.encode("utf-8")).hexdigest()


def compute_prompt_hash(prompt: str) -> str:
    """SHA-256 hash of the prompt for storage / debugging."""
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


async def lookup_cache(
    db: AsyncSession,
    cache_key: str,
) -> dict[str, Any] | None:
    """Look up cache for a given key. Returns dict with response_text and response_hash if found."""
    if not settings.llm_cache_enabled:
        return None

    entry = await repo.get_cached_response(db, cache_key)
    if entry is None:
        return None

    return {
        "response_text": entry.response_text,
        "response_hash": entry.response_hash,
        "hit_count": entry.hit_count,
    }


async def store_in_cache(
    db: AsyncSession,
    *,
    cache_key: str,
    agent_name: str,
    model_name: str,
    prompt_hash: str,
    response_text: str,
    response_hash: str,
    tools_used: list[str] | None = None,
) -> None:
    """Store a new cache entry."""
    if not settings.llm_cache_enabled:
        return

    expires_at = datetime.utcnow() + timedelta(hours=settings.llm_cache_ttl_hours)
    await repo.store_cached_response(
        db,
        cache_key=cache_key,
        agent_name=agent_name,
        model_name=model_name,
        prompt_hash=prompt_hash,
        response_text=response_text,
        response_hash=response_hash,
        tools_used=tools_used or [],
        expires_at=expires_at,
    )
    logger.info("Cache STORE for %s (key=%s…)", agent_name, cache_key[:12])


async def compare_and_update_cache(
    db: AsyncSession,
    *,
    cache_key: str,
    agent_name: str,
    model_name: str,
    prompt_hash: str,
    new_response_text: str,
    new_response_hash: str,
    tools_used: list[str] | None = None,
) -> str:
    """Compare new response with cached entry and decide action.

    Returns cache_status: 'hit', 'miss', or 'updated'.
    """
    if not settings.llm_cache_enabled:
        return "miss"

    existing = await repo.get_cached_response(db, cache_key)

    if existing is None:
        # No cache entry – store and return miss
        await store_in_cache(
            db,
            cache_key=cache_key,
            agent_name=agent_name,
            model_name=model_name,
            prompt_hash=prompt_hash,
            response_text=new_response_text,
            response_hash=new_response_hash,
            tools_used=tools_used,
        )
        return "miss"

    if existing.response_hash == new_response_hash:
        # Same response – deterministic! Mark as hit.
        await repo.increment_cache_hit(db, cache_key)
        logger.info("Cache HIT for %s (key=%s…, hits=%d)", agent_name, cache_key[:12], existing.hit_count + 1)
        return "hit"

    # Different response – tool returned fresh data. Replace cache.
    expires_at = datetime.utcnow() + timedelta(hours=settings.llm_cache_ttl_hours)
    await repo.update_cached_response(
        db,
        cache_key,
        response_text=new_response_text,
        response_hash=new_response_hash,
        tools_used=tools_used or [],
        expires_at=expires_at,
        hit_count=0,  # Reset hit count with new data
    )
    logger.info("Cache UPDATED for %s (key=%s…, tool response changed)", agent_name, cache_key[:12])
    return "updated"
