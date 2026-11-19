"""Post-M10 Priority C — quantify the two vocabulary gaps on real pages.

M10 reported two gaps by inspection. A decision to widen a controlled
vocabulary needs more than inspection, so this counts the occurrences across
every page Polaris has actually stored, and prints the surrounding sentence for
each so the semantics can be read rather than guessed.
"""

from __future__ import annotations

import re

from sqlalchemy import text

from database.session import SessionLocal

# The two phrases the brief names, plus the neighbouring wordings a reviewer
# would ask about, so the count is not an artefact of one exact string.
UNDERGRADUATE = re.compile(r"\bundergraduate\b", re.IGNORECASE)
COMPREHENSIVE = re.compile(
    r"all\s+tuition\s+fees|full\s+tuition\s+fees|"
    r"tuition\s+fees?,?\s+(?:travel|and\s+living|living)|"
    r"travel\s+and\s+living\s+costs?",
    re.IGNORECASE,
)


def contexts(pattern, label, limit=6):
    session = SessionLocal()
    try:
        rows = session.execute(
            text("SELECT source_url, raw_content FROM raw_document")
        ).fetchall()
    finally:
        session.close()

    documents = hits = 0
    examples = []
    for url, raw in rows:
        if not raw:
            continue
        documents += 1
        # Strip tags so a match inside a navigation attribute is not counted.
        text_only = re.sub(r"<[^>]+>", " ", raw)
        found = list(pattern.finditer(text_only))
        if not found:
            continue
        hits += 1
        for match in found:
            if len(examples) < limit:
                start = max(0, match.start() - 130)
                end = min(len(text_only), match.end() + 130)
                snippet = " ".join(text_only[start:end].split())
                examples.append((url, snippet))

    print(f"=== {label} ===")
    print(f"documents scanned : {documents}")
    print(f"documents matching: {hits}")
    for url, snippet in examples:
        print(f"\n  {url}\n    …{snippet}…")
    print()


if __name__ == "__main__":
    contexts(UNDERGRADUATE, "C1 degree: 'undergraduate'")
    contexts(COMPREHENSIVE, "C2 funding: comprehensive cost statements")
