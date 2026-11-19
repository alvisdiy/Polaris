from services.ingestion.cleaner import _extract_structure


def test_cleaner_preserves_resolved_http_anchor_hrefs():
    html = """
    <html><head><title>Scholarship article</title></head><body>
      <h1>Example Scholarship</h1>
      <a href="/official-program">Official Site</a>
      <a href="https://apply.example.edu/form#start">Apply Now</a>
      <a href="javascript:void(0)">Apply here</a>
      <a href="#details">Details</a>
    </body></html>
    """

    title, headings, anchors, anchor_links = _extract_structure(html, "https://aggregator.example/scholarship-article")

    assert title == "Scholarship article"
    assert headings == ["Example Scholarship"]
    assert "Official Site" in anchors
    assert [(link.text, link.href) for link in anchor_links] == [
        ("Official Site", "https://aggregator.example/official-program"),
        ("Apply Now", "https://apply.example.edu/form"),
        ("Details", "https://aggregator.example/scholarship-article"),
    ]
