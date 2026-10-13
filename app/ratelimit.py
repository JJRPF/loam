"""In-process rate limits (token buckets) and a cap on concurrent route generations.

No new service: the limiter lives in this process, which is right for one API process on one Pi.
The key is the Firebase uid when the caller is signed in, otherwise the client IP. Behind Tailscale
Funnel the client IP comes from the last X-Forwarded-For entry (the one the local Funnel proxy
appended), and only when the direct peer is loopback; any other peer is used as is, so a client
cannot pick its own key by sending the header.
"""
import asyncio
import math
import time
from contextlib import asynccontextmanager
from typing import Dict, Optional, Tuple

from fastapi import Depends, HTTPException, Request

from app.auth import AuthUser, get_optional_user
from app.config import settings

LOOPBACK = ("127.0.0.1", "::1")
MAX_KEYS = 20000  # stale buckets are dropped past this; a bucket at full capacity carries no information


def parse_limit(spec: str) -> Tuple[int, float]:
    """'20/600' -> (20 requests, per 600 seconds)."""
    count, window = spec.split("/")
    return max(1, int(count)), max(1.0, float(window))


class RateLimiter:
    def __init__(self) -> None:
        self._buckets: Dict[str, Tuple[float, float]] = {}  # key -> (tokens, last monotonic time)

    def reset(self) -> None:
        self._buckets.clear()

    def check(self, key: str, count: int, window_s: float) -> Optional[int]:
        """Takes a token. Returns None when allowed, else the seconds until one is available."""
        now = time.monotonic()
        rate = count / window_s
        tokens, last = self._buckets.get(key, (float(count), now))
        tokens = min(float(count), tokens + (now - last) * rate)
        if tokens >= 1.0:
            self._buckets[key] = (tokens - 1.0, now)
            if len(self._buckets) > MAX_KEYS:
                self._prune(now)
            return None
        self._buckets[key] = (tokens, now)
        return max(1, math.ceil((1.0 - tokens) / rate))

    def _prune(self, now: float) -> None:
        for k in [k for k, (_, last) in self._buckets.items() if now - last > 3600]:
            del self._buckets[k]


limiter = RateLimiter()


def client_ip(request: Request) -> str:
    peer = request.client.host if request.client else "unknown"
    if peer in LOOPBACK:
        forwarded = request.headers.get("x-forwarded-for", "")
        parts = [p.strip() for p in forwarded.split(",") if p.strip()]
        if parts:
            return parts[-1]
    return peer


def rate_key(request: Request, user: Optional[AuthUser]) -> str:
    return f"u:{user.uid}" if user is not None else f"ip:{client_ip(request)}"


def wait_text(seconds: int) -> str:
    if seconds < 90:
        return f"{seconds} seconds"
    if seconds < 5400:
        return f"{math.ceil(seconds / 60)} minutes"
    return f"{math.ceil(seconds / 3600)} hours"


def too_many(what: str, seconds: int) -> HTTPException:
    return HTTPException(
        status_code=429,
        detail=f"You're {what} faster than Loam allows. Please wait about {wait_text(seconds)} and try again.",
        headers={"Retry-After": str(seconds)},
    )


def rate_limited(name: str, what: str):
    """FastAPI dependency: `name` selects the limit in settings.rate_limits; `what` finishes the sentence
    "You're ___ faster than Loam allows"."""
    async def dependency(request: Request, user: Optional[AuthUser] = Depends(get_optional_user)) -> None:
        count, window = parse_limit(settings.rate_limits[name])
        wait = limiter.check(f"{name}:{rate_key(request, user)}", count, window)
        if wait is not None:
            raise too_many(what, wait)
    return dependency


# --- concurrent route generations -------------------------------------------------------------

_slots: Optional[asyncio.Semaphore] = None
_slots_loop = None


def _semaphore() -> asyncio.Semaphore:
    global _slots, _slots_loop
    loop = asyncio.get_running_loop()
    if _slots is None or _slots_loop is not loop:  # one per event loop (the test client makes its own)
        _slots, _slots_loop = asyncio.Semaphore(settings.route_concurrency), loop
    return _slots


@asynccontextmanager
async def route_slot():
    """At most settings.route_concurrency route generations run at once; others wait up to
    settings.route_wait_s, then get a 429."""
    sem = _semaphore()
    try:
        await asyncio.wait_for(sem.acquire(), timeout=settings.route_wait_s)
    except asyncio.TimeoutError:
        raise too_many("asking for routes", 20)
    try:
        yield
    finally:
        sem.release()
