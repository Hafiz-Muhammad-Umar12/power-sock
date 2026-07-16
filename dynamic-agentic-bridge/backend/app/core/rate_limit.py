"""
Simple in-memory rate limiter for API endpoints.
Uses a sliding window counter per IP address.

For production, replace with Redis-backed rate limiting (e.g. slowapi).
"""

from __future__ import annotations

import time
from collections import defaultdict
from fastapi import HTTPException, Request


class RateLimiter:
    """Sliding window rate limiter."""

    def __init__(self, max_requests: int, window_seconds: int) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: dict[str, list[float]] = defaultdict(list)

    def _get_client_id(self, request: Request) -> str:
        """Extract client identifier from request."""
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
        if request.client:
            return request.client.host
        return "unknown"

    def check(self, request: Request) -> None:
        """
        Check if the request is within rate limits.
        Raises HTTPException 429 if rate limit exceeded.
        """
        client_id = self._get_client_id(request)
        now = time.time()
        cutoff = now - self.window_seconds

        # Clean old entries
        self._requests[client_id] = [
            t for t in self._requests[client_id] if t > cutoff
        ]

        if len(self._requests[client_id]) >= self.max_requests:
            retry_after = int(self._requests[client_id][0] + self.window_seconds - now) + 1
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded. Try again in {retry_after}s",
                headers={"Retry-After": str(retry_after)},
            )

        self._requests[client_id].append(now)


# Pre-configured rate limiters
observe_limiter = RateLimiter(max_requests=5, window_seconds=60)  # 5 per minute
execute_limiter = RateLimiter(max_requests=10, window_seconds=60)  # 10 per minute
