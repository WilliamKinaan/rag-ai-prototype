"""In-memory, per-process rate limiter guarding the shared Mistral key.

This key is also used by two other live demo apps (llm-playground,
chatagent) on the same account — Mistral enforces limits per *workspace*,
shared across every key in it, not per key — so this is a local guard
against bursts from this app specifically, not a substitute for Mistral's
own limit. See RATE_LIMIT_MAX_REQUESTS/RATE_LIMIT_WINDOW_SECONDS below.

Deliberately simple, matching this project's "no framework wrappers" style
(see webapp/llm.py's docstring): a single fixed-window request counter, no
Redis, resets on process restart. This app only ever makes one real Mistral
call per /api/chat turn (no fan-out, no streaming, no agent loop), so
reserve(1) right before that call is the only reservation point needed.
"""

import os
import threading
import time

from dotenv import load_dotenv

load_dotenv()

# Placeholder defaults - Mistral doesn't publish exact free-tier numbers;
# check console.mistral.ai -> Admin Panel -> API -> Limits for this
# workspace's real limit, and size these as roughly this app's *share* of
# it (three live apps currently share this same key).
MAX_REQUESTS = int(os.environ.get("RATE_LIMIT_MAX_REQUESTS", "5"))
WINDOW_SECONDS = float(os.environ.get("RATE_LIMIT_WINDOW_SECONDS", "10"))


class RateLimitExceeded(Exception):
    """Raised by reserve() when the current window's budget is used up."""

    def __init__(self, retry_after: float):
        self.retry_after = retry_after
        super().__init__(f"Rate limit reached — try again in {max(1, round(retry_after))}s")


class _FixedWindowLimiter:
    def __init__(self, max_requests: int, window_seconds: float):
        self._max = max_requests
        self._window = window_seconds
        self._lock = threading.Lock()
        self._window_start = time.monotonic()
        self._count = 0

    def _reset_if_elapsed(self, now: float) -> None:
        if now - self._window_start >= self._window:
            self._window_start = now
            self._count = 0

    def reserve(self, n: int = 1) -> None:
        with self._lock:
            now = time.monotonic()
            self._reset_if_elapsed(now)
            if self._count + n > self._max:
                raise RateLimitExceeded(self._window - (now - self._window_start))
            self._count += n

    def status(self) -> tuple[int, float]:
        """Read-only (remaining, seconds_until_reset), for the status route -
        reports (max, 0) rather than a countdown when nothing's been spent
        yet, so the page's badge doesn't show a bogus countdown ticking
        toward "resetting" a budget that's already full.
        """
        with self._lock:
            now = time.monotonic()
            self._reset_if_elapsed(now)
            if self._count == 0:
                return self._max, 0.0
            return max(0, self._max - self._count), self._window - (now - self._window_start)


_limiter = _FixedWindowLimiter(MAX_REQUESTS, WINDOW_SECONDS)


def reserve(n: int = 1) -> None:
    """Reserve n calls' worth of budget, or raise RateLimitExceeded."""
    _limiter.reserve(n)


def status() -> tuple[int, float]:
    """Read-only (remaining, seconds_until_reset)."""
    return _limiter.status()
