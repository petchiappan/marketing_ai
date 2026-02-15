"""Redis-backed caching with namespace-aware keys and TTL management."""

from __future__ import annotations

import json
from typing import Any, Callable, Awaitable

import redis.asyncio as aioredis


class EnrichmentCache:
    """
    Redis cache with namespace-aware keys and TTL management.

    Keys follow the pattern:  cache:{namespace}:{key}
    """

    def __init__(self, redis: aioredis.Redis):
        self.redis = redis

    def _make_key(self, namespace: str, key: str) -> str:
        """Build a namespaced cache key."""
        return f"cache:{namespace}:{key}"

    async def get(self, namespace: str, key: str) -> Any | None:
        """Retrieve a cached value, or None on miss."""
        raw = await self.redis.get(self._make_key(namespace, key))
        if raw is None:
            return None
        return json.loads(raw)

    async def set(self, namespace: str, key: str, value: Any, ttl: int) -> None:
        """Store a value with the given TTL in seconds."""
        await self.redis.setex(
            self._make_key(namespace, key),
            ttl,
            json.dumps(value, default=str),
        )

    async def get_or_fetch(
        self,
        namespace: str,
        key: str,
        fetch_fn: Callable[[], Awaitable[Any]],
        ttl: int,
    ) -> Any:
        """
        Return cached value if available, otherwise call fetch_fn,
        cache the result with the given TTL, and return it.
        """
        cached = await self.get(namespace, key)
        if cached is not None:
            return cached

        value = await fetch_fn()
        if value is not None:
            await self.set(namespace, key, value, ttl)
        return value

    async def invalidate(self, namespace: str, key: str) -> None:
        """Remove a specific cache entry."""
        await self.redis.delete(self._make_key(namespace, key))

    async def invalidate_namespace(self, namespace: str) -> int:
        """Remove all cache entries in a namespace. Returns count deleted."""
        pattern = f"cache:{namespace}:*"
        keys = []
        async for key in self.redis.scan_iter(match=pattern, count=100):
            keys.append(key)
        if keys:
            return await self.redis.delete(*keys)
        return 0
