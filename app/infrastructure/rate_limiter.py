"""Token-bucket rate limiter backed by Redis with DB-configurable limits."""

from __future__ import annotations

import asyncio
import time
from typing import Any

import redis.asyncio as aioredis

# Default limits used when DB is unreachable
_DEFAULTS: dict[str, dict[str, int]] = {
    "lusha":         {"requests_per_min": 60,  "burst_limit": 10, "daily_quota": 1000},
    "apollo":        {"requests_per_min": 100, "burst_limit": 20, "daily_quota": 5000},
    "signal_hire":   {"requests_per_min": 30,  "burst_limit": 5,  "daily_quota": 500},
    "news_search":   {"requests_per_min": 100, "burst_limit": 20, "daily_quota": 0},
    "yahoo_finance": {"requests_per_min": 200, "burst_limit": 50, "daily_quota": 0},
}


class RateLimitExceeded(Exception):
    """Raised when a rate limit is exceeded."""

    def __init__(self, provider: str, retry_after: float = 0):
        self.provider = provider
        self.retry_after = retry_after
        super().__init__(f"Rate limit exceeded for {provider}. Retry after {retry_after:.1f}s")


class RateLimiter:
    """
    Token-bucket rate limiter with DB-backed, admin-configurable limits.

    Uses Redis for distributed state so that multiple workers share
    the same token bucket.
    """

    def __init__(
        self,
        provider: str,
        redis: aioredis.Redis,
        requests_per_min: int | None = None,
        burst_limit: int | None = None,
        daily_quota: int | None = None,
    ):
        self.provider = provider
        self.redis = redis

        defaults = _DEFAULTS.get(provider, {"requests_per_min": 60, "burst_limit": 10, "daily_quota": 0})
        self.requests_per_min = requests_per_min or defaults["requests_per_min"]
        self.burst_limit = burst_limit or defaults["burst_limit"]
        self.daily_quota = daily_quota or defaults.get("daily_quota", 0)

        # Derived
        self.refill_rate = self.requests_per_min / 60.0  # tokens per second
        self._bucket_key = f"ratelimit:{provider}:bucket"
        self._last_ts_key = f"ratelimit:{provider}:ts"
        self._daily_key = f"ratelimit:{provider}:daily"

    async def reload_config(
        self,
        requests_per_min: int,
        burst_limit: int,
        daily_quota: int | None = None,
    ) -> None:
        """Hot-reload limits (called after admin updates config)."""
        self.requests_per_min = requests_per_min
        self.burst_limit = burst_limit
        self.daily_quota = daily_quota or 0
        self.refill_rate = requests_per_min / 60.0

    async def acquire(self, tokens: int = 1) -> bool:
        """
        Attempt to acquire *tokens* from the bucket.

        Returns True if successful, raises RateLimitExceeded otherwise.
        """
        now = time.time()

        # --- Daily quota check ---
        if self.daily_quota > 0:
            daily_count = await self.redis.get(self._daily_key)
            if daily_count and int(daily_count) >= self.daily_quota:
                raise RateLimitExceeded(self.provider, retry_after=0)

        # --- Token bucket (Lua script for atomicity) ---
        lua_script = """
        local bucket_key  = KEYS[1]
        local ts_key      = KEYS[2]
        local max_tokens  = tonumber(ARGV[1])
        local refill_rate = tonumber(ARGV[2])
        local now         = tonumber(ARGV[3])
        local requested   = tonumber(ARGV[4])

        local tokens   = tonumber(redis.call('GET', bucket_key) or max_tokens)
        local last_ts  = tonumber(redis.call('GET', ts_key) or now)

        -- Refill
        local elapsed  = math.max(0, now - last_ts)
        tokens = math.min(max_tokens, tokens + elapsed * refill_rate)

        if tokens >= requested then
            tokens = tokens - requested
            redis.call('SET', bucket_key, tokens)
            redis.call('SET', ts_key, now)
            return 1
        else
            return 0
        end
        """
        result = await self.redis.eval(
            lua_script,
            2,
            self._bucket_key,
            self._last_ts_key,
            self.burst_limit,
            self.refill_rate,
            now,
            tokens,
        )

        if result == 1:
            # Increment daily counter
            if self.daily_quota > 0:
                pipe = self.redis.pipeline()
                pipe.incr(self._daily_key, tokens)
                pipe.expire(self._daily_key, 86_400)
                await pipe.execute()
            return True

        # Calculate retry_after
        retry_after = tokens / self.refill_rate if self.refill_rate > 0 else 1.0
        raise RateLimitExceeded(self.provider, retry_after=retry_after)

    async def wait_and_acquire(self, tokens: int = 1, timeout: float = 30.0) -> None:
        """Block until tokens are available or timeout is reached."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                await self.acquire(tokens)
                return
            except RateLimitExceeded as exc:
                wait = min(exc.retry_after, deadline - time.time())
                if wait <= 0:
                    raise
                await asyncio.sleep(wait)
        raise RateLimitExceeded(self.provider, retry_after=0)
