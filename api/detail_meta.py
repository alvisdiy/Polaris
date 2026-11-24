"""Per-record meta for scholarship detail pages.

Detail pages are client-rendered, so before this module every shared
or crawled ``/scholarships/<id>`` link carried the same static title
and description as the home page — a crawler (and anyone pasting a
link into a chat) saw "Polaris | Scholarship Intelligence" for every
programme in the catalogue. The app route for a detail URL now asks
this module for the record's real title, description and JSON-LD and
injects them into the SPA shell before serving it. The client app
then hydrates exactly as before; nothing about rendering changes.

Everything interpolated here comes from extracted data, so all of it
is escaped for its context: attribute values and the title element
through ``html.escape``, the JSON-LD block through ``json.dumps``
plus a ``</`` guard so a stray closing tag in a name cannot break
out of the script element.
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass
from datetime import date


@dataclass
class DetailMeta:
    title: str
    description: str
    canonical_url: str
    json_ld: dict


def _truncate(text: str, limit: int = 200) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rsplit(" ", 1)[0] + "…"


def build_detail_meta(
    *,
    name: str,
    provider_name: str | None,
    country_name: str | None,
    degree: str | None,
    funding_type: str | None,
    deadline: date | None,
    field_of_study: list[str] | None,
    canonical_url: str,
) -> DetailMeta:
    """Compose the meta for one published record from its real fields.

    Only facts the record actually carries are used; a missing field
    shortens the description rather than inventing a value.
    """
    title = f"{name} | Polaris"

    lead = name
    if provider_name:
        lead += f" by {provider_name}"
    if country_name:
        lead += f" in {country_name}"
    facts = [part for part in (degree, funding_type) if part]
    if field_of_study:
        facts.append(", ".join(field_of_study[:3]))
    description = lead + "."
    if facts:
        description += " " + " · ".join(facts) + "."
    if deadline:
        description += f" Application deadline: {deadline.isoformat()}."
    description += " Details verified against the official provider page."
    description = _truncate(description)

    json_ld: dict = {
        "@context": "https://schema.org",
        "@type": "EducationalOccupationalProgram",
        "name": name,
        "description": description,
        "url": canonical_url,
    }
    if provider_name:
        json_ld["provider"] = {"@type": "Organization", "name": provider_name}

    return DetailMeta(
        title=title,
        description=description,
        canonical_url=canonical_url,
        json_ld=json_ld,
    )


def _set_meta_content(document: str, attribute: str, key: str, value: str) -> str:
    """Replace the content of ``<meta {attribute}="{key}" content="...">``.

    The built shell writes these tags in a stable attribute order
    (name/property first, content second, possibly across lines), so a
    targeted regex is sufficient — and if a tag is ever absent the
    document is returned unchanged rather than corrupted.
    """
    pattern = re.compile(
        rf'(<meta\s+{attribute}="{re.escape(key)}"\s+content=")[^"]*(")',
        re.DOTALL,
    )
    return pattern.sub(lambda m: m.group(1) + html.escape(value, quote=True) + m.group(2), document, count=1)


def render_detail_html(shell: str, meta: DetailMeta) -> str:
    """Inject one record's meta into the SPA shell HTML."""
    document = re.sub(
        r"<title>.*?</title>",
        lambda _: f"<title>{html.escape(meta.title)}</title>",
        shell,
        count=1,
        flags=re.DOTALL,
    )
    document = _set_meta_content(document, "name", "description", meta.description)
    document = _set_meta_content(document, "property", "og:title", meta.title)
    document = _set_meta_content(document, "property", "og:description", meta.description)
    document = _set_meta_content(document, "property", "og:type", "article")

    json_ld = json.dumps(meta.json_ld, ensure_ascii=False).replace("</", "<\\/")
    extra = (
        f'<link rel="canonical" href="{html.escape(meta.canonical_url, quote=True)}" />\n'
        f'<meta property="og:url" content="{html.escape(meta.canonical_url, quote=True)}" />\n'
        f'<script type="application/ld+json">{json_ld}</script>\n'
    )
    return document.replace("</head>", extra + "</head>", 1)
