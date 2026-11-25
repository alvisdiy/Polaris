"""PDF candidates in the discovery analyzer.

Official programmes often publish only a PDF pamphlet. The analyzer
used to reject every PDF twice over: ".pdf" sat in the binary
extension list (so PDF links on a page never became candidates), and
the fetch's content-type gate refused application/pdf outright. The
bounded fix reads a PDF through the ingestion connector's existing
text path; these tests pin that behaviour with the network replaced
at the module's seams.
"""

from __future__ import annotations

import pytest

from services.exploration import candidate_analyzer
from services.exploration.candidate_analyzer import CandidateAnalyzer


def _make_pdf(lines: list[str]) -> bytes:
    """A minimal one-page PDF carrying the given text lines."""
    content_ops = ["BT /F1 14 Tf 72 720 Td"]
    for i, line in enumerate(lines):
        if i:
            content_ops.append("0 -20 Td")
        content_ops.append(f"({line}) Tj")
    content_ops.append("ET")
    stream = "\n".join(content_ops).encode()

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_at = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_at}\n%%EOF\n"
    ).encode()
    return bytes(out)


class _Response:
    def __init__(self, url, *, content_type, content: bytes, text: str = ""):
        self.status_code = 200
        self.url = url
        self.history = []
        self.headers = {"content-type": content_type}
        self.content = content
        self.text = text


class _FakeClient:
    response: _Response | None = None

    def __init__(self, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url):
        return _FakeClient.response


@pytest.fixture(autouse=True)
def _seams(monkeypatch):
    candidate_analyzer._robots_cache.clear()
    candidate_analyzer._robots_cache["https://example.org"] = None
    monkeypatch.setattr(candidate_analyzer, "validate_external_url", lambda *a, **k: None)
    monkeypatch.setattr(candidate_analyzer, "validate_redirect_chain", lambda *a, **k: None)
    monkeypatch.setattr(candidate_analyzer.httpx, "AsyncClient", _FakeClient)
    yield
    candidate_analyzer._robots_cache.clear()


@pytest.fixture
def analyzer():
    return CandidateAnalyzer(per_domain_delay_ms=0)


@pytest.mark.asyncio
async def test_a_pdf_candidate_is_read_as_text(analyzer):
    _FakeClient.response = _Response(
        "https://example.org/guide.pdf",
        content_type="application/pdf",
        content=_make_pdf(
            ["Brightpath Scholars Award 2027", "Full tuition for master students worldwide"]
        ),
    )
    result = await analyzer.analyze("https://example.org/guide.pdf")
    assert result.error is None
    assert result.fetched is True
    assert "Brightpath Scholars Award 2027" in result.main_text
    assert result.title == "Brightpath Scholars Award 2027"


@pytest.mark.asyncio
async def test_an_unreadable_pdf_reports_why(analyzer):
    _FakeClient.response = _Response(
        "https://example.org/guide.pdf",
        content_type="application/pdf",
        content=b"this is not a pdf at all",
    )
    result = await analyzer.analyze("https://example.org/guide.pdf")
    assert result.fetched is False
    assert result.error is not None and result.error.startswith("pdf_unreadable")


@pytest.mark.asyncio
async def test_pdf_links_on_a_page_become_candidates(analyzer):
    html = (
        "<html><head><title>Programmes</title></head><body>"
        "<p>Our awards for the coming academic year are listed below.</p>"
        '<a href="/files/guide.pdf">Scholarship guide (PDF)</a>'
        '<a href="/logo.png">Logo</a>'
        "</body></html>"
    )
    _FakeClient.response = _Response(
        "https://example.org/programmes",
        content_type="text/html",
        content=html.encode(),
        text=html,
    )
    result = await analyzer.analyze("https://example.org/programmes")
    urls = [link.url for link in result.links]
    assert "https://example.org/files/guide.pdf" in urls
    assert not any(u.endswith(".png") for u in urls)


@pytest.mark.asyncio
async def test_other_binaries_are_still_refused(analyzer):
    _FakeClient.response = _Response(
        "https://example.org/photo",
        content_type="image/png",
        content=b"\x89PNG",
    )
    result = await analyzer.analyze("https://example.org/photo")
    assert result.fetched is False
    assert result.error is not None
    assert result.error.startswith("unsupported_content_type")
