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
