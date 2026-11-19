"""Name providers from their own pages instead of from their hostname.

Discovery sometimes registers a provider under its domain ("upm.edu.my",
"moe.gov.bn") or a batch label ("Chinese universities (scholarship pages)").
Publishing under that puts a hostname where a student expects an institution.

The page already says who it is: JSON-LD ``Organization``/``CollegeOrUniversity``,
``og:site_name``, or a title segment before a separator. This script reads that
evidence from the stored document and renames the provider — deterministically,
with no model, and only when the evidence names an actual organisation.

    python scripts/fix_provider_identity.py --dry-run
    python scripts/fix_provider_identity.py
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bs4 import BeautifulSoup  # noqa: E402

from database.models.provider import Provider  # noqa: E402
from database.models.raw_document import RawDocument  # noqa: E402
from database.models.scholarship import Scholarship  # noqa: E402

_DOMAINISH = re.compile(r"^[a-z0-9][a-z0-9.-]*\.[a-z]{2,}$", re.IGNORECASE)
_GENERIC = re.compile(
    r"^(?:.*universities? \(.*\)|.*scholarship pages|.*funding pages)$", re.IGNORECASE
)
_INSTITUTION = re.compile(
    r"\b(?:Universit(?:y|i|ät|é)|College|Institut(?:e|ion)?|School|Academy|"
    r"Ministry|Kementerian|Majlis|Council|Foundation|Stiftung|Board|Commission|"
    r"Polytechnic|Politeknik|Hochschule|Centre|Center)\b",
    re.IGNORECASE,
)
_NOISE = re.compile(
    r"^(?:home|welcome|untitled|just a moment|access denied|404|search|"
    r"universiti|university|college|scholarships?|funding)$",
    re.IGNORECASE,
)


def _document_text(session, provider: Provider) -> str:
    row = (
        session.query(Scholarship)
        .filter(Scholarship.provider_id == provider.provider_id)
        .first()
    )
    if row is not None:
        for entry in (row.field_provenance or {}).values():
            if isinstance(entry, dict) and entry.get("document_id"):
                document = session.get(RawDocument, entry["document_id"])
                if document is not None and document.raw_content:
                    return document.raw_content
    return ""


def _name_from_html(html: str) -> tuple[str, str] | None:
    """(organisation, evidence) from JSON-LD, og:site_name, or the title."""
    soup = BeautifulSoup(html, "html.parser")

    for script in soup.find_all("script", type="application/ld+json"):
        try:
            import json

            payload = json.loads(script.string or "{}")
        except Exception:
            continue
        items = payload if isinstance(payload, list) else [payload]
        for item in items:
            if not isinstance(item, dict):
                continue
            if item.get("@type") in (
                "Organization",
                "CollegeOrUniversity",
                "EducationalOrganization",
                "GovernmentOrganization",
                "University",
            ):
                name = " ".join(str(item.get("name") or "").split())
                if name and not _NOISE.match(name) and not _DOMAINISH.match(name):
                    return name[:120], "JSON-LD"

    site = soup.find("meta", attrs={"property": "og:site_name"})
    if site and site.get("content"):
        name = " ".join(site["content"].split())
        if name and not _NOISE.match(name) and not _DOMAINISH.match(name):
            return name[:120], "og:site_name"

    if soup.title and soup.title.string:
        title = " ".join(soup.title.string.split())
        # "Welcome to Universiti Malaya" is the institution with a greeting in
        # front of it, not a different name.
        title = re.sub(r"^(?:welcome to|selamat datang ke|home\s*[-|:])\s*", "", title, flags=re.IGNORECASE)
        for separator in (" | ", " – ", " — ", " :: ", " - "):
            if separator not in title:
                continue
            parts = [part.strip() for part in title.split(separator)]
            for part in (parts[0], parts[-1]):
                if (
                    len(part) >= 6
                    and not _NOISE.match(part)
                    and not _DOMAINISH.match(part)
                    and _INSTITUTION.search(part)
                ):
                    return part[:120], "page title"
        # A title with no separator can still be the organisation name, but only
        # when it reads like one: short, and naming an institution type.
        if (
            2 <= len(title.split()) <= 8
            and len(title) <= 100
            and _INSTITUTION.search(title)
            and not _NOISE.match(title)
        ):
            return title[:120], "page title"
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=200)
    args = parser.parse_args(argv)

    from database.session import SessionLocal

    session = SessionLocal()
    try:
        # No SQL LIMIT: the providers that need this are the ones sorted last
        # ("upm.edu.my" is far past the first few hundred), and a limit here
        # quietly skipped exactly the rows the script exists for.
        providers = session.query(Provider).order_by(Provider.provider_name).all()
        renamed = 0
        for provider in providers:
            name = (provider.provider_name or "").strip()
            if not (_DOMAINISH.match(name) or _GENERIC.match(name)):
                continue
            html = _document_text(session, provider)
            if not html:
                continue
            found = _name_from_html(html)
            if found is None:
                continue
            candidate, evidence = found
            if candidate.casefold() == name.casefold():
                continue
            print(f"{name[:44]:<44} -> {candidate[:60]:<60} [{evidence}]")
            if not args.dry_run:
                provider.provider_name = candidate
            renamed += 1
        if args.dry_run:
            session.rollback()
        else:
            session.commit()
        print(f"\nrenamed {renamed} provider(s); dry_run={args.dry_run}")
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
