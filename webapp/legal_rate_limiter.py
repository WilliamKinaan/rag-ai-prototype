"""In-memory rate limiting for the Legal Assistant endpoint
(POST /api/legal-review) - separate from rate_limiter.py, which guards this
app's *share of the shared Mistral key* specifically (see that module's
docstring). This one guards the Legal Assistant feature itself, independent
of which provider's key is used, on two axes:

- **Per model**: at most PER_MODEL_MAX_REQUESTS requests per
  PER_MODEL_WINDOW_SECONDS, tracked separately for each provider - so no
  single model's hosted API (including ones with no key-sharing concern of
  their own, like OpenAI/Anthropic) gets hammered.
- **Per IP**: at most PER_IP_MAX_REQUESTS requests per PER_IP_WINDOW_SECONDS
  from the same client address, across all models combined - so no single
  visitor can hammer the endpoint by spreading requests across providers.

Deliberately simple - fixed-window counters (reusing rate_limiter.py's
_FixedWindowLimiter), no Redis, resets on process restart. Known
limitation: the per-IP dict below is never evicted, so a very large number
of distinct IPs over a long-running process would grow it unbounded - fine
for a prototype, revisit if this ever sees real traffic.
"""

import threading

# _FixedWindowLimiter is underscore-prefixed in rate_limiter.py (an
# internal detail there, wrapped by that module's own reserve()/status()
# for its one singleton use), but it's exactly the fixed-window counter
# this module needs many independent copies of - reused directly rather
# than duplicating the same ~15 lines of locking/window logic here.
from rate_limiter import RateLimitExceeded, _FixedWindowLimiter

PER_MODEL_MAX_REQUESTS = 2
PER_MODEL_WINDOW_SECONDS = 60.0

PER_IP_MAX_REQUESTS = 10
PER_IP_WINDOW_SECONDS = 30 * 60.0


class ModelRateLimitExceeded(RateLimitExceeded):
    """A specific model got too many legal-review requests too fast.
    Subclasses rate_limiter.RateLimitExceeded so app.py's existing
    exception handler for that type also catches this one (same 429
    treatment) with no extra wiring needed.
    """

    def __init__(self, model: str, retry_after: float):
        self.retry_after = retry_after
        Exception.__init__(
            self,
            f"'{model}' has already handled {PER_MODEL_MAX_REQUESTS} "
            f"legal-review requests in the last minute. Please wait a "
            f"minute and try again.",
        )


class IPRateLimitExceeded(RateLimitExceeded):
    """One client address made too many legal-review requests too fast."""

    def __init__(self, retry_after: float):
        self.retry_after = retry_after
        minutes = max(1, round(retry_after / 60))
        Exception.__init__(
            self,
            f"You've reached the limit of {PER_IP_MAX_REQUESTS} "
            f"legal-review requests per 30 minutes. Please wait about "
            f"{minutes} minute(s) and try again.",
        )


# --- Per-provider daily cap (Layer 3) ---------------------------------
#
# Unlike the two limiters above, this bounds *daily total spend*, not burst
# rate: PER_MODEL_MAX_REQUESTS resets every minute, so a steady stream of
# requests all day still passes through it every single window. Added on
# direct request once a paid-per-token provider (Qwen, then Anthropic) went
# live on a real site (see CONTEXT-legal-assistant.md) - a cost circuit
# breaker shared across every visitor combined, not a per-user throttle.
#
# One dict of per-provider limits rather than a Qwen-specific function
# duplicated for each new paid provider - DAILY_CAPS is the only thing that
# needs a new line when the next provider needs this (e.g. OpenAI later).
# A provider with no entry here just isn't covered by this layer at all
# (currently: Mistral has rate_limiter.py's own shared-key budget instead;
# OpenAI has neither yet). Values are per-provider because cost per request
# varies a lot: Anthropic's Sonnet 5 runs roughly 7-10x Qwen-plus's
# per-token price, so its cap is set tighter for a comparable dollar-risk,
# not matched request-for-request. Same in-memory/resets-on-restart caveat
# as everything else in this module - not a substitute for a real spend cap
# set on the provider's own console.
DAILY_CAPS = {
    "qwen": 100,
    "anthropic": 20,
}
DAILY_WINDOW_SECONDS = 24 * 60 * 60.0

_daily_limiters: dict[str, _FixedWindowLimiter] = {}
_daily_limiters_lock = threading.Lock()


class DailyLimitExceeded(RateLimitExceeded):
    """The daily cap on total legal-review calls to one provider (all
    visitors combined) has been reached."""

    def __init__(self, provider: str, retry_after: float):
        self.retry_after = retry_after
        hours = max(1, round(retry_after / 3600))
        Exception.__init__(
            self,
            f"The daily limit of {DAILY_CAPS[provider]} '{provider}' "
            f"legal-review requests (shared across all visitors) has been "
            f"reached. Please try again in about {hours} hour(s), or pick "
            f"a different model.",
        )


def _get_daily_limiter(provider: str) -> _FixedWindowLimiter:
    with _daily_limiters_lock:
        limiter = _daily_limiters.get(provider)
        if limiter is None:
            limiter = _FixedWindowLimiter(DAILY_CAPS[provider], DAILY_WINDOW_SECONDS)
            _daily_limiters[provider] = limiter
        return limiter


def reserve_daily(provider: str) -> None:
    """Reserve one request against `provider`'s daily cap, or raise. A
    no-op for any provider not listed in DAILY_CAPS - call this
    unconditionally after reserve() above (see app.py) rather than gating
    on a provider list there too."""
    if provider not in DAILY_CAPS:
        return
    try:
        _get_daily_limiter(provider).reserve(1)
    except RateLimitExceeded as e:
        raise DailyLimitExceeded(provider, e.retry_after) from e


# One limiter per provider name, created lazily on first use so this module
# doesn't need its own copy of legal_review.PROVIDERS' key list - an unknown
# provider getting its own limiter here is harmless, since app.py already
# rejects unknown providers before this is ever reached.
_model_limiters: dict[str, _FixedWindowLimiter] = {}
_model_limiters_lock = threading.Lock()

# One limiter per client IP - see the "never evicted" note above.
_ip_limiters: dict[str, _FixedWindowLimiter] = {}
_ip_limiters_lock = threading.Lock()


def _get_model_limiter(model: str) -> _FixedWindowLimiter:
    with _model_limiters_lock:
        limiter = _model_limiters.get(model)
        if limiter is None:
            limiter = _FixedWindowLimiter(PER_MODEL_MAX_REQUESTS, PER_MODEL_WINDOW_SECONDS)
            _model_limiters[model] = limiter
        return limiter


def _get_ip_limiter(ip: str) -> _FixedWindowLimiter:
    with _ip_limiters_lock:
        limiter = _ip_limiters.get(ip)
        if limiter is None:
            limiter = _FixedWindowLimiter(PER_IP_MAX_REQUESTS, PER_IP_WINDOW_SECONDS)
            _ip_limiters[ip] = limiter
        return limiter


def reserve(model: str, ip: str) -> None:
    """Reserve one request against both budgets, or raise. Checks the IP
    budget first: on a request that fails there, no per-model budget is
    spent. A request that passes the IP check but fails the per-model
    check does spend one IP-budget slot even though it's ultimately
    rejected - a minor over-count, acceptable for this prototype's "simple,
    good enough to start with" bar.
    """
    try:
        _get_ip_limiter(ip).reserve(1)
    except RateLimitExceeded as e:
        raise IPRateLimitExceeded(e.retry_after) from e

    try:
        _get_model_limiter(model).reserve(1)
    except RateLimitExceeded as e:
        raise ModelRateLimitExceeded(model, e.retry_after) from e
