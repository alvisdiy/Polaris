"""Guards for running a live exploration against a database.

A live exploration run *writes*: it creates an ExplorationRun row, inserts
frontier candidates, may persist raw documents and scholarship records, and
commits as it goes. Running that against the development knowledge base is how
a "quick test" becomes 300 new rows and a frontier queue nobody asked for.

The rule this module enforces:

    a live run is allowed only against a local database whose name ends in
    ``_test`` or ``_scratch`` (or when the operator explicitly opts out).

The check is on the parsed database name, not on a substring of the URL: a
remote host called ``polaris_test.example.com`` is still remote, and a
database called ``polaris`` with the word "scratch" in its query string is
still the development database.

This is a guard against ordinary mistakes, not a security boundary. An
operator who sets ``POLARIS_ALLOW_NON_SCRATCH=1`` has said, in the
environment, that they mean it.
"""

from __future__ import annotations

import os
from urllib.parse import urlsplit

#: Database names ending with one of these are disposable by convention.
SCRATCH_SUFFIXES: tuple[str, ...] = ("_test", "_testing", "_scratch")

#: Hosts that mean "this machine". An empty host is a Unix socket, which is
#: also local by definition.
LOCAL_HOSTS = frozenset({"", "localhost", "127.0.0.1", "::1", "[::1]"})

#: Opt-out for the deliberate case (a dedicated local database that is not
#: named with a scratch suffix). Named rather than implied.
ALLOW_ENV = "POLARIS_ALLOW_NON_SCRATCH"


class NonScratchDatabase(RuntimeError):
    """A live run was pointed at a database that is not disposable."""


def database_name(url: str) -> str:
    """The database name component of a SQLAlchemy/Postgres URL."""
    path = urlsplit(url).path or ""
    return path.lstrip("/").split("?")[0].strip()


def is_local_host(url: str) -> bool:
    """Whether the URL's host is this machine (including a Unix socket)."""
    host = (urlsplit(url).hostname or "").lower()
    if host in LOCAL_HOSTS:
        return True
    # IPv4 loopback range is 127.0.0.0/8; a hostname is not.
    return host.startswith("127.")


def is_scratch_database(url: str) -> bool:
    """A local database whose name marks it as disposable."""
    name = database_name(url).lower()
    return is_local_host(url) and name.endswith(SCRATCH_SUFFIXES)


def allow_non_scratch_from_env() -> bool:
    return os.getenv(ALLOW_ENV, "").strip() == "1"


def assert_scratch_database(url: str, *, allow_non_scratch: bool = False) -> None:
    """Refuse a live run against a non-disposable database.

    Raises:
        NonScratchDatabase: with the actual database name in the message, so
            the operator can see what they pointed at rather than guessing.
    """
    if allow_non_scratch or allow_non_scratch_from_env():
        return
    if is_scratch_database(url):
        return
    name = database_name(url) or "<unknown>"
    raise NonScratchDatabase(
        f"Refusing to run a live exploration against database {name!r}. "
        "Point DATABASE_URL at a local database whose name ends in "
        "'_test', '_testing' or '_scratch' (for example "
        "postgresql+psycopg://postgres:postgres@localhost:5432/polaris_scratch), "
        f"or set {ALLOW_ENV}=1 if this database is genuinely disposable. "
        "Use --plan-only to inspect the query plan without touching any database."
    )
