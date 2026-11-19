"""Bearer-token guard for the internal review/admin surface.

The review API can approve or reject a scholarship. That decision *is* the
publication boundary, so an anonymous caller must not be able to make it.

There are no user accounts and no sessions in Polaris. One operator token is
the smallest thing that closes the hole without pretending to be an identity
system:

* ``POLARIS_ADMIN_TOKEN`` is required. When it is unset the admin surface is
  **disabled** (503), not open. A missing secret must fail closed.
* The token is compared in constant time, so a wrong value does not leak its
  prefix through response timing.
* The token identifies an operator, not a person. The ``actor`` field on a
  review action remains "who claimed to do this"; namespacing it with the
  authenticated operator is a later, separate concern.
"""

from __future__ import annotations

import hmac
import os

from fastapi import Header, HTTPException, status

ADMIN_TOKEN_ENV = "POLARIS_ADMIN_TOKEN"


def configured_token() -> str:
    """The configured admin token, or an empty string when unset."""
    return os.getenv(ADMIN_TOKEN_ENV, "").strip()


def require_admin(authorization: str | None = Header(default=None)) -> None:
    """Reject the request unless it carries the configured bearer token."""
    token = configured_token()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Admin review API is disabled: POLARIS_ADMIN_TOKEN is not set. "
                "Set it to enable the internal curation surface."
            ),
        )

    scheme, _, presented = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not presented:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not hmac.compare_digest(presented, token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid admin token",
            headers={"WWW-Authenticate": "Bearer"},
        )
