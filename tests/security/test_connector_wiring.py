"""The connectors must actually go through the safety boundary.

`url_safety`, `robots` and `fetch_safety` are only useful if the code that
fetches pages calls them. These tests wire each connector to a client that
records requests, and assert that a request to a private address never happens
and that robots.txt is consulted with the connector's declared user agent.
"""

from __future__ import annotations

import uuid

import pytest

from services.ingestion.connectors.base_connector import ConnectorConfig
from services.ingestion.connectors.generic_connector import GenericHTTPConnector
from services.ingestion.connectors.government.mext_connector import MEXTConnector
from services.ingestion.url_safety import UrlSafetyError

ROBOTS_ALLOW = "User-agent: *\nAllow: /\n"


class _RecordingClient:
    def __init__(self):
        self.calls: list[str] = []
        self.closed = False

    async def get(self, url, **kwargs):
        self.calls.append(url)
        raise AssertionError(f"a request was made to {url}")

    async def aclose(self):
        self.closed = True


def _config(url: str) -> ConnectorConfig:
    return ConnectorConfig(
        source_id=uuid.uuid4(),
        url=url,
        timeout=5,
        user_agent="PolarisBot/test",
    )


CONNECTORS = [
    pytest.param(GenericHTTPConnector, id="generic-http"),
    pytest.param(MEXTConnector, id="mext"),
]


@pytest.mark.parametrize("connector_cls", CONNECTORS)
@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:5432/",
        "http://169.254.169.254/latest/meta-data/",
        "http://10.1.2.3/internal",
        "http://localhost/",
    ],
)
def test_connector_refuses_to_fetch_a_private_target(connector_cls, url):
    connector = connector_cls(_config("https://www.example.org/scholarship.html"))
    client = _RecordingClient()
    connector.client = client

    with pytest.raises(UrlSafetyError):
        import asyncio

        asyncio.run(connector.fetch(url))

    assert client.calls == [], "the request was made before validation"


def test_connector_consults_robots_with_its_declared_user_agent():
    """robots.txt is fetched once, with the agent the connector advertises."""
    import asyncio

    connector = MEXTConnector(
        _config("https://www.example.org/scholarship.html")
    )
    seen: list[tuple[str, str]] = []

    async def fetch_robots(url: str) -> str:
        seen.append((url, connector.robots.user_agent))
        return "User-agent: *\nDisallow: /private/\n"

    connector.robots.fetch_robots = fetch_robots
    connector.client = _RecordingClient()

    with pytest.raises(Exception) as exc:
        asyncio.run(connector.fetch("https://www.example.org/private/scholarship"))

    assert "disallowed" in str(exc.value).lower()
    assert seen == [("https://www.example.org/robots.txt", "PolarisBot/test")]


def test_every_connector_module_wires_the_safety_boundary():
    """Static guard: a connector that forgets SafeFetch is a silent hole."""
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "services/ingestion/connectors"
    unchecked = []
    for path in root.rglob("*.py"):
        if path.name in {"base_connector.py", "__init__.py"}:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        called = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        used = {
            alias.name.split(".")[-1]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            for alias in node.names
        }
        if not ({"SafeFetch", "validate_external_url"} & (called | used)):
            unchecked.append(path.name)

    assert unchecked == [], f"connectors without a safety boundary: {unchecked}"
