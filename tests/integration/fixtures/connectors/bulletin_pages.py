from __future__ import annotations

MOFA_KR_BULLETIN_PAGE_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
  <title>News &amp; Events - Embassy of the Republic of Korea in the State of Israel</title>
</head>
<body>
  <div class="brd_list">
    <a href="view.do?seq=759977">2025-2026 Scholarship for Graduate Studies and Fellowship for Postdoctoral Research</a>
    <a href="view.do?seq=759978">[KF] 2025-2026 Scholarship for Graduate Studies</a>
    <a href="view.do?seq=759979">2025 Dispatch Notice</a>
    <a href="/il-en/brd/m_11417/view.do?seq=759980">Another bulletin entry</a>
    <a href="https://www.mofa.go.kr/il-en/brd/m_11417/view.do?seq=759981">Full absolute link</a>
    <a href="/il-en/board/notice/list.do">Notice list</a>
    <a href="javascript:void(0)">script link</a>
    <a href="#top">anchor</a>
    <a href="mailto:test@mofa.go.kr">email</a>
    <a href="attachment.pdf">PDF attachment</a>
  </div>
</body>
</html>
"""

MOFA_KR_BULLETIN_BASE_URL = "https://www.mofa.go.kr/il-en/brd/m_11417/view.do?seq=759978"

#: With the default keyword set, two entries are discovered because their
#: *anchor text* names a scholarship. Their URLs are opaque board queries
#: (``view.do?seq=N``) that say nothing about funding, which is the whole reason
#: the entry page yielded nothing before anchor text was read. This constant was
#: previously ``[]``, which was an accurate measurement of the defect and is not
#: an accurate statement of the corrected behaviour.
#:
#: The remaining three records are admitted by URL *shape* rather than by
#: keyword: a viewer route carrying a numeric record id is one page of the
#: publisher's CMS, and its label ("2025 Dispatch Notice") is the only thing
#: that says what it is. Discovery admits them; the acquisition policy keeps
#: only the two whose label names a scholarship. Both halves of that contract
#: are pinned — here and in ``test_discovery_reliability.py``.
MOFA_KR_BULLETIN_LINKS_DEFAULT_KEYWORDS = [
    "https://www.mofa.go.kr/il-en/brd/m_11417/view.do?seq=759977",
    "https://www.mofa.go.kr/il-en/brd/m_11417/view.do?seq=759978",
    "https://www.mofa.go.kr/il-en/brd/m_11417/view.do?seq=759979",
    "https://www.mofa.go.kr/il-en/brd/m_11417/view.do?seq=759980",
    "https://www.mofa.go.kr/il-en/brd/m_11417/view.do?seq=759981",
]

#: With a bulletin-shaped keyword set, the board identifier embedded in the path
#: makes every entry on the board — including its PDF attachment — match. Only
#: the non-http schemes and the fragment-only link drop out.
MOFA_KR_BULLETIN_LINKS_WITH_BULLETIN_KEYWORDS = [
    "https://www.mofa.go.kr/il-en/brd/m_11417/view.do?seq=759977",
    "https://www.mofa.go.kr/il-en/brd/m_11417/view.do?seq=759978",
    "https://www.mofa.go.kr/il-en/brd/m_11417/view.do?seq=759979",
    "https://www.mofa.go.kr/il-en/brd/m_11417/view.do?seq=759980",
    "https://www.mofa.go.kr/il-en/brd/m_11417/view.do?seq=759981",
    "https://www.mofa.go.kr/il-en/board/notice/list.do",
    "https://www.mofa.go.kr/il-en/brd/m_11417/attachment.pdf",
]

EMPTY_PAGE_HTML = """
<!DOCTYPE html>
<html>
<head>
  <title>Empty</title>
</head>
<body></body>
</html>
"""

#: Markup that reaches the DOM only after JavaScript runs. The link is present as
#: text inside a script, not as an anchor, so DOM parsing correctly finds nothing:
#: the live path evaluates the script through the browser and reads the rendered
#: DOM afterwards, and this fixture models the pre-render snapshot.
JS_RENDERED_BULLETIN_HTML = """
<!DOCTYPE html>
<html>
<head>
  <title>Bulletin</title>
</head>
<body>
  <div id="content"><span>Loading...</span></div>
  <script>
    document.getElementById("content").innerHTML =
      '<a href="view.do?seq=759978">[KF] 2025-2026 Scholarship</a>' +
      '<a href="/il-en/brd/m_11417/view.do?seq=759980">Another bulletin entry</a>';
  </script>
</body>
</html>
"""

MEXT_STYLE_LIST_HTML = """
<!DOCTYPE html>
<html>
<head>
  <title>MEXT Scholarship Program</title>
</head>
<body>
  <ul>
    <li><a href="detail/2026/">2026 MEXT Scholarship</a></li>
    <li><a href="/en/program/2025/detail.html">2025 MEXT Program Detail</a></li>
    <li><a href="/en/contact/">Contact</a></li>
    <li><a href="https://external.example.org/scholarship">External link</a></li>
  </ul>
</body>
</html>
"""
