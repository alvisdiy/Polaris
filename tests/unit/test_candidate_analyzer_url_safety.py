"""SSRF guard for CandidateAnalyzer.

The analyzer fetches URLs that come from search results and extracted
links — fully untrusted input. Before this guard it would fetch any
target, including loopback and cloud metadata endpoints, and hand the
content to the classifier. These cases are all rejected before any DNS
lookup, so they are environment-independent.
"""

from __future__ import annotations

import pytest

from services.exploration.candidate_analyzer import CandidateAnalyzer


@pytest.fixture
def analyzer():
    return CandidateAnalyzer(per_domain_delay_ms=0)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/admin",
        "http://127.1/admin",
        "http://0177.0.0.1/admin",
        "http://[::1]/admin",
        "http://169.254.169.254/latest/meta-data",
        "https://localhost/internal",
        "https://metadata.google.internal/computeMetadata/v1/",
        "file:///etc/passwd",
        "ftp://example.org/file",
        "https://user:secret@example.org/scholarship",
        "not-a-url",
    ],
)
async def test_unsafe_urls_are_refused_before_fetch(analyzer, url):
    result = await analyzer.analyze(url)
    assert result.fetched is False
    assert result.error is not None
    assert result.error.startswith("unsafe_url"), result.error
