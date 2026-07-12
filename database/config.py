"""Lazy configuration — values are resolved on first access, not at import time."""

from __future__ import annotations

import os

from dotenv import load_dotenv

# Load .env file once at import time (safe — no side effects beyond setting env vars)
load_dotenv()


def get_database_url() -> str:
    """Return DATABASE_URL from environment. Raises if not set."""
    url = os.getenv("DATABASE_URL")
    if url is None:
        raise RuntimeError("DATABASE_URL is not configured")
    return url
