"""In-process rate limiting for the public API.

The public surface had no abuse control at all: ``POST
/api/v1/recommendations`` runs a scoring pass over the catalogue and
was anonymous and unlimited, and catalogue GETs could be scraped at
full speed. This module is the smallest thing that closes that hole
without new infrastructure: a sliding-window counter per client,
held in process memory.

Scope and limits are policy, so they live in one place (``POLICY``
below) and can be retuned without touching the middleware. The admin
review surface is deliberately out of scope — it is token-gated, and
an operator bulk-reviewing should never trip a public limit.

Deliberate limits of the design: counters are per-process (a
multi-worker deployment gets one budget per worker, which dampens
abuse without pretending to be a distributed quota), and the client
key trusts the first ``X-Forwarded-For`` hop when present, which is
the deployment's own proxy in the combined setup. ``POLARIS_RATE_LIMIT=off``
disables the middleware for local development.
"""

from __future__ import annotations

import os
import threading
import time
from collections import deque

WINDOW_SECONDS = 60.0

# (method class, path prefix) -> requests per window per client.
# Order matters: the first matching rule wins.
POLICY: list[tuple[str, str, int]] = [
    # Matching is the expensive, anonymous write: strictest budget.
    ("POST", "/api/v1/recommendations", 60),
    # Other public writes (none today besides matching, but the rule
    # future-proofs new endpoints).
    ("WRITE", "/api/v1/", 120),
    # Reads are cheap and cached, but not free: a generous ceiling
    # that no human browsing pattern approaches.
    ("GET", "/api/v1/", 1200),
]


def _rule_for(method: str, path: str) -> tuple[str, int] | None:
    """(bucket name, limit) for the first matching policy rule."""
    for kind, prefix, limit in POLICY:
        if not path.startswith(prefix):
            continue
        if kind == "WRITE" and method in ("POST", "PUT", "PATCH", "DELETE"):
            return f"write:{prefix}", limit
        if kind == method:
            return f"{method.lower()}:{prefix}", limit
    return None


class SlidingWindowLimiter:
    """Per-key sliding-window counter. Thread-safe; keys expire lazily."""

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str, limit: int, window: float = WINDOW_SECONDS) -> bool:
        now = time.monotonic()
        cutoff = now - window
        with self._lock:
            bucket = self._hits.setdefault(key, deque())
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= limit:
                return False
            bucket.append(now)
            return True

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


def rate_limit_enabled() -> bool:
    return os.getenv("POLARIS_RATE_LIMIT", "on").strip().lower() != "off"


def bucket_for(method: str, path: str) -> tuple[str, int] | None:
    """The (bucket, per-window budget) for this request, or None when
    unregulated. The admin surface returns None by design (see module
    docstring). The bucket groups paths so each detail URL does not get
    its own budget."""
    if path.startswith("/api/v1/admin"):
        return None
    return _rule_for(method, path)


def client_key(request) -> str:
    """Identify the client: first forwarded hop when a proxy set one."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
