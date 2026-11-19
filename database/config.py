"""Lazy configuration — values are resolved on first access, not at import time."""

from __future__ import annotations

import os
import re
import sys

from dotenv import load_dotenv
from sqlalchemy.engine import make_url

_TEST_MODE = "pytest" in sys.modules

if not _TEST_MODE:
    # Preserve developer convenience outside tests; pytest must never inherit .env.
    load_dotenv()


def get_database_url() -> str:
    """Return the configured database URL, requiring a disposable target in tests."""
    if _TEST_MODE:
        value = os.getenv("POLARIS_TEST_DATABASE_URL", "").strip()
        if not value:
            raise RuntimeError(
                "Set POLARIS_TEST_DATABASE_URL to a disposable local PostgreSQL database."
            )
        url = make_url(value)
        if url.get_backend_name() != "postgresql":
            raise RuntimeError("Test database requires PostgreSQL.")
        if url.host not in (None, "localhost", "127.0.0.1", "::1"):
            raise RuntimeError("Refusing a non-local test database host.")
        if not re.search(r"(?:_test|_scratch)$", url.database or "", re.IGNORECASE):
            raise RuntimeError("Test database name must end with _test or _scratch.")
        return value

    url = os.getenv("DATABASE_URL")
    if url is None:
        raise RuntimeError("DATABASE_URL is not configured")
    return url
