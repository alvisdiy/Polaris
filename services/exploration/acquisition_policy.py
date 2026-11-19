"""Source acquisition policy and URL identity.

Two problems this module exists to solve, both of which were silently costing
Polaris real scholarships.

**A verified source is not necessarily a scholarship.** Exploration verifies
authority (is this the ministry's own site?) and opportunity presence (does it
mention scholarships?). Neither answers "is *this* page one scholarship?".
Feeding every verified URL straight into extraction is why the M8 run produced
rows named `Number of Scholarship` and `Das Program`: the pipeline was being
handed a ministry homepage and asked for a scholarship.

    SourceRegistry (VERIFIED)
        ↓ classify page
    SOURCE_PAGE      → discover scholarship-bearing links, then fetch those
    SCHOLARSHIP_PAGE → fetch and extract directly
    PROVIDER_PAGE     → discover links, fetch only those naming a programme
    OTHER_OFFICIAL    → discover, but do not extract this page as a scholarship

**A URL is not a stable identity.** `_register_source` stored the redirected
final URL while lookups used the raw frontier URL, so a redirect could register
one row and then fail to find it. Everything here keys on `url_hash(normalize_url(...))`
instead, which is what the `ix_source_registry_url_hash` index exists for.

Both decisions are recorded on the SourceRegistry row (`page_type`,
`canonical_url`, `url_hash`, `acquisition_state`, `acquisition_error`,
`scholarship_page_urls`) so a reviewer can see why a page was fetched or skipped
rather than inferring it from silence.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

from database.models.source_registry import SourceAcquisitionState
from services.domain.source_trust import aggregator_host
from services.exploration.url_utils import is_detail_record_url, normalize_url, url_hash

logger = logging.getLogger("polaris.exploration.acquisition_policy")


class PageType:
    """What kind of page a verified source points at."""

    # A ministry/scholarship-body landing page: a portal, not a programme.
    SOURCE_PAGE = "SOURCE_PAGE"
    # A single programme's detail page: extract directly.
    SCHOLARSHIP_PAGE = "SCHOLARSHIP_PAGE"
    # An organisation profile page (embassy, agency, foundation).
    PROVIDER_PAGE = "PROVIDER_PAGE"
    # Official, reachable, but not scholarship-bearing as far as we can tell.
    OTHER_OFFICIAL_PAGE = "OTHER_OFFICIAL_PAGE"
    # A third-party listing site. Useful as a discovery lead, never as the
    # page a reader is sent to verify.
    AGGREGATOR = "AGGREGATOR"


class AcquisitionState:
    """What acquisition actually did with a source.

    Persisted per source so a failure is visible in the database rather than
    only in a log line that nobody reads a week later.

    An alias, not a declaration: the vocabulary lives on the model so there is
    exactly one list of values for `source_registry.acquisition_state`. The
    previous copy here and the one on `SourceAcquisitionState` had drifted —
    the model listed COMPLETED/IN_PROGRESS, which nothing ever writes.
    """

    PENDING = SourceAcquisitionState.PENDING
    ACQUIRED = SourceAcquisitionState.ACQUIRED
    NO_SCHOLARSHIP_PAGES = SourceAcquisitionState.NO_SCHOLARSHIP_PAGES
    FAILED = SourceAcquisitionState.FAILED
    SKIPPED = SourceAcquisitionState.SKIPPED


# Path and anchor vocabulary that identifies one programme's page. Structural
# rather than an allow-list of known sites: every government site words this
# differently, and a list of them would go stale immediately.
_SCHOLARSHIP_PATH_HINTS = (
    "scholarship", "fellowship", "grant", "bursary", "award", "fund",
    "stipend", "programme", "program", "scholarships",
)
_PROVIDER_PATH_HINTS = (
    "about", "organisation", "organization", "who-we-are", "contact",
    "mission", "profile",
)
# Depth and breadth signals of a portal rather than a programme page.
_PORTAL_PATH_HINTS = (
    "index", "home", "sitemap", "search", "category", "archive", "news",
    "events", "faq", "media", "press", "blog",
)

# A year is the strongest single signal that a page describes one intake.
_YEAR_PATTERN = re.compile(r"(19|20)\d{2}")
_WORD_SPLIT = re.compile(r"[^a-z0-9]+")

# Small set of short neutral tokens that often act as identifiers in scholarship
# paths rather than category names: ``pg``, ``view``, ``detail``, ``item``,
# ``article``, ``entry``, ``form``, ``apply``, ``no``, ``id``, ``seq``.
_TOKEN_IS_ID = frozenset({
    "pg", "view", "detail", "item", "article", "entry", "form", "apply",
    "no", "id", "seq", "news", "list", "record", "file", "document",
})

#: Noun that names the thing being awarded, as opposed to the process around it
#: or the section that collects several of them. A final segment that carries
#: one of these *and* a name is how official sites spell "this is one
#: programme": ``/scholarships/daad-funding-programme``. Plurals are absent on
#: purpose — ``/our-programmes`` and ``/scholarships`` are collections.
_PROGRAMME_HEAD_TOKENS = frozenset({
    "programme", "program", "scholarship", "fellowship", "studentship",
})

#: Action words that make a segment describe the act of applying rather than the
#: award: ``/apply-for-a-scholarship`` is a process page even though it names a
#: scholarship. Kept out of the named-programme tier for that reason.
_PROCESS_SEGMENT_TOKENS = frozenset({
    "apply", "applying", "application", "applications", "applicant", "applicants",
    "form", "forms", "register", "registration", "how",
    "information", "info", "overview", "details", "summary", "advice", "tips",
})

def _tokens(text: str) -> list[str]:
    return [t for t in _WORD_SPLIT.split((text or "").casefold()) if t]


def _token_is_identifier(token: str) -> bool:
    return token in _TOKEN_IS_ID


def _has_token(text: str, hints) -> bool:
    """Whether any hint appears as a whole token of ``text``.

    Substring matching read the ``mission`` path hint out of ``admissions``, so
    a university admissions page was taxed as an organisation profile. One
    page is not worth a rule, but the same substring collision applies to
    ``commission``, ``permission`` and ``submission`` — all common in the paths
    of the pages that publish scholarship announcements.
    """
    joined = " ".join(_tokens(text))
    for hint in hints:
        phrase = " ".join(_tokens(hint))
        if phrase and re.search(rf"(?:^| ){re.escape(phrase)}(?: |$)", joined):
            return True
    return False




@dataclass
class PageAssessment:
    """What we concluded about one page, and on what evidence."""

    page_type: str
    confidence: float
    reasons: list[str] = field(default_factory=list)

    @property
    def is_scholarship_page(self) -> bool:
        return self.page_type == PageType.SCHOLARSHIP_PAGE

    @property
    def should_discover_links(self) -> bool:
        """Whether this page is a place to look for other pages."""
        return self.page_type in (
            PageType.SOURCE_PAGE, PageType.PROVIDER_PAGE, PageType.OTHER_OFFICIAL_PAGE,
        )


@dataclass
class CandidatePage:
    """One link found on a source page, with its score."""

    url: str
    canonical_url: str
    url_hash: str
    score: float
    reasons: list[str] = field(default_factory=list)


def classify_page(url: str, *, title: str = "", anchor_text: str = "") -> PageAssessment:
    """Decide what kind of page a URL points at.

    Signals, strongest first:

    1. A third-party aggregator host is never an official source, whatever its
       path or anchor says.
    2. A year in the path or anchor. Almost every scholarship detail page is
       about one intake, and portals almost never carry a year in their path.
    3. A scholarship noun in the *last* path segment. `/grants/scholarship`
       is a programme; `/scholarship/how-to-apply` is guidance.
    4. Explicit portal vocabulary, which rules the page out.

    The classifier never invents: an ambiguous page is reported as
    OTHER_OFFICIAL_PAGE and the caller decides, rather than being guessed into
    a scholarship.
    """
    aggregator = aggregator_host(url)
    if aggregator:
        return PageAssessment(
            PageType.AGGREGATOR,
            0.95,
            [f"third-party aggregator ({aggregator}); not an official source"],
        )

    reasons: list[str] = []
    confidence = 0.0

    parsed = urlparse(normalize_url(url))
    segments = [s for s in (parsed.path or "").split("/") if s]
    last = _tokens(segments[-1]) if segments else []
    anchor = anchor_text or title or ""
    anchor_lower = anchor.casefold()

    has_scholarship_noun = any(
        hint in (parsed.path or "").casefold() or hint in anchor_lower
        for hint in _SCHOLARSHIP_PATH_HINTS
    )
    has_year = bool(_YEAR_PATTERN.search(parsed.path or "")) or bool(
        _YEAR_PATTERN.search(anchor)
    )
    has_portal_noun = any(
        hint in (parsed.path or "").casefold() for hint in _PORTAL_PATH_HINTS
    )
    # "How to apply", "eligibility", "contact" describe a process, not a programme.
    # Read from the path only: the URL is the page's identity, the anchor is
    # only a label for it. Matching the label too cost real records — an anchor
    # reading "2026 Global Korea Scholarship Application Guidelines" was
    # deducted as a guidedance page because "guidelines" contains "guide".
    guidance_noun = _has_token(
        parsed.path or "",
        ("how-to-apply", "eligibility", "requirements", "faq", "guide", "contact"),
    )

    if has_portal_noun and not has_year:
        reasons.append(f"portal vocabulary in path: {parsed.path}")
        return PageAssessment(PageType.SOURCE_PAGE, 0.5, reasons)

    # A shallow path is a site's front door. /en/ or /index.php is where a
    # portal lists its programmes, so treat it as a source page to expand
    # rather than a page to extract from.
    if len(segments) <= 1 and not has_scholarship_noun:
        reasons.append(f"front-door path with no programme signal: {parsed.path or '/'}")
        return PageAssessment(PageType.SOURCE_PAGE, 0.4, reasons)

    # A neutral identifier that names one thing rather than a category is a
    # mild specificity signal. It is not enough on its own: a slug like
    # ``/pg/123`` could still be a listing, a form, or a landing. Paired with
    # a scholarship noun in the wider path, though, it breaks the
    # "scholarship == index if no year" assumption that M13.1 found too strict.
    has_neutral_identifier = bool(
        len(last) == 1
        and last[0] in _TOKEN_IS_ID
    )

    if has_year:
        confidence += 0.45
        reasons.append("path or anchor names an intake year")

    # One record on the publisher's CMS: an id-shaped tail, or a viewer route
    # whose query carries the id. It is a specificity signal like `pg`, and it
    # is deliberately not sufficient on its own.
    detail_record = is_detail_record_url(parsed.geturl())
    if detail_record:
        has_neutral_identifier = True

    # A final segment that names a programme *inside a scholarship collection*
    # (``/scholarships/daad-funding-programme``) is the one shape the older
    # rules could not express: without a year it scored 0.40 and stayed a
    # SOURCE_PAGE, so every year-less official programme page was discovered
    # and then thrown away unread (DAAD: 6 found, 0 ranked).
    #
    # The collection is part of the rule, not decoration. Measured against real
    # paths, a segment that merely contains a programme head is not enough:
    # ``/campuslife/support-scholarship/`` is the section that *collects*
    # programmes, and promoting it would send a hub to the extractor. What
    # distinguishes the two is the parent: DAAD's programmes sit under
    # ``/scholarships/``; the hub is the collection itself.
    parent_segments = "/".join(segments[:-1]).casefold() if len(segments) > 1 else ""
    parent_names_collection = bool(parent_segments) and any(
        hint in parent_segments for hint in _SCHOLARSHIP_PATH_HINTS
    )
    named_programme = bool(
        len(last) >= 2
        and parent_names_collection
        and not guidance_noun
        and not any(token in _PORTAL_PATH_HINTS for token in last)
        and not any(token in _PROCESS_SEGMENT_TOKENS for token in last)
        and any(token in _PROGRAMME_HEAD_TOKENS for token in last)
    )

    if has_scholarship_noun:
        # A scholarship noun as the final segment is much stronger than one
        # anywhere in the path: `/grants/scholarship` vs `/scholarship/faq`.
        if named_programme:
            confidence += 0.60
            reasons.append("final segment names one programme")
        elif any(hint in last for hint in _SCHOLARSHIP_PATH_HINTS):
            confidence += 0.40
            reasons.append("scholarship noun in the final path segment")
        else:
            # Right-hand scholarship slugs are usually indices, but a
            # scholarship noun earlier in the path plus a programme-shaped tail
            # is enough to prefer one programme over a generic listing.
            if has_neutral_identifier:
                confidence += 0.40
                reasons.append("specific identifier with a scholarship page")
            else:
                confidence += 0.15
                reasons.append("scholarship noun in path")

    if guidance_noun:
        confidence -= 0.35
        reasons.append("path describes a process, not a programme")

    if _has_token(parsed.path or "", _PROVIDER_PATH_HINTS):
        confidence -= 0.20
        reasons.append("path describes the organisation, not a programme")

    if confidence >= 0.6:
        return PageAssessment(PageType.SCHOLARSHIP_PAGE, round(confidence, 3), reasons)
    if has_scholarship_noun:
        return PageAssessment(PageType.SOURCE_PAGE, round(confidence, 3), reasons)
    return PageAssessment(PageType.OTHER_OFFICIAL_PAGE, round(confidence, 3), reasons)


def classify_provider_page(url: str, *, title: str = "") -> PageAssessment:
    """Classify a page that arrived via an opportunity/provider candidate."""
    parsed = urlparse(normalize_url(url))
    path = (parsed.path or "").casefold()
    if any(hint in path for hint in _PROVIDER_PATH_HINTS):
        return PageAssessment(
            PageType.PROVIDER_PAGE, 0.6, [f"organisation vocabulary in path: {parsed.path}"]
        )
    # An opportunity page usually *is* the scholarship page. Fall through to
    # the shared classifier rather than guessing.
    return classify_page(url, title=title)


@dataclass
class LinkAssessment:
    """One discovered link, what the policy made of it, and why.

    Recorded for every link, kept or not. Acquisition used to report a single
    number ("6 links found") that could not distinguish "nothing on the page
    described a scholarship" from "three pages were portals and one was
    guidance", which is the difference between a broken source and a broken
    rule.
    """

    url: str
    canonical_url: str
    url_hash: str
    page_type: str
    score: float
    reasons: list[str] = field(default_factory=list)

    @property
    def is_scholarship_page(self) -> bool:
        return self.page_type == PageType.SCHOLARSHIP_PAGE


def assess_candidate_links(
    links: list[tuple[str, str]],
    *,
    country_domain: str | None = None,
) -> list[LinkAssessment]:
    """Classify every discovered link once, in discovery order.

    Deduplicated on canonical identity and filtered by domain, but not by
    verdict: the caller decides what to do with a portal, and needs to be able
    to report how many there were.
    """
    assessments: list[LinkAssessment] = []
    seen: set[str] = set()

    for url, anchor in links:
        if not url:
            continue
        canonical = normalize_url(url)
        if not canonical:
            continue
        digest = url_hash(url)
        if digest in seen:
            # Same logical URL through a different spelling or a redirect.
            continue
        seen.add(digest)

        if country_domain:
            host = urlparse(canonical).netloc
            if not (host == country_domain or host.endswith("." + country_domain)):
                continue

        assessment = classify_page(canonical, anchor_text=anchor)
        assessments.append(
            LinkAssessment(
                url=url,
                canonical_url=canonical,
                url_hash=digest,
                page_type=assessment.page_type,
                score=assessment.confidence,
                reasons=list(assessment.reasons),
            )
        )

    return assessments


def rank_candidate_urls(
    links: list[tuple[str, str]],
    *,
    limit: int,
    country_domain: str | None = None,
    assessments: list[LinkAssessment] | None = None,
) -> list[CandidatePage]:
    """Rank links found on a source page, best scholarship page first.

    Args:
        links: ``(url, anchor_text)`` pairs. The anchor text is the label that
            pointed at the URL. It is real evidence about what the target is,
            and the classifier reads it, so a discovery path that drops it is
            ranking on less information than it actually has.
        limit: maximum pages to return. Bounded on purpose: acquisition must
            not become an uncontrolled crawl.
        country_domain: when given, off-domain links are dropped. A verified
            government source pointing at an unrelated commercial site is not
            an official source for this country.
        assessments: the result of :func:`assess_candidate_links` for these
            links, when the caller already has it. Passing it back in avoids
            classifying the same page twice per run.

    Returns only pages the policy classifies as one scholarship, highest score
    first. A page that is not one scholarship is not returned: it is a place to
    look, and its own links are expanded on a later pass instead. That boundary
    is deliberately strict — widening it is how a portal or a listing reaches
    the extractor and is persisted as a scholarship that does not exist.
    """
    if assessments is None:
        assessments = assess_candidate_links(links, country_domain=country_domain)

    scored = [
        CandidatePage(
            url=a.url,
            canonical_url=a.canonical_url,
            url_hash=a.url_hash,
            score=a.score,
            reasons=a.reasons,
        )
        for a in assessments
        if a.is_scholarship_page
    ]

    scored.sort(key=lambda p: (-p.score, p.canonical_url))
    return scored[:limit]


def resolve_url_identity(url: str) -> tuple[str, str]:
    """``(canonical_url, url_hash)`` for a URL, including a bare host.

    A redirect target and the URL that redirected to it usually canonicalize
    to different values, which is correct: they are different pages. What must
    not happen is the same logical URL registering twice, and that is what the
    hash prevents.
    """
    canonical = normalize_url(url)
    return canonical, (url_hash(url) if canonical else "")


def find_source(session, url: str, url_hash_value: str | None = None):
    """Find a SourceRegistry row by URL identity.

    Tries the hash first (correct across redirects and query noise), then the
    legacy raw columns so rows written before `url_hash` existed stay
    reachable.
    """
    from database.models.source_registry import SourceRegistry

    canonical, digest = resolve_url_identity(url)
    if url_hash_value is None:
        url_hash_value = digest

    if url_hash_value:
        row = (
            session.query(SourceRegistry)
            .filter(SourceRegistry.url_hash == url_hash_value)
            .first()
        )
        if row is not None:
            return row

    if canonical:
        row = (
            session.query(SourceRegistry)
            .filter(
                (SourceRegistry.canonical_url == canonical)
                | (SourceRegistry.official_url == canonical)
                | (SourceRegistry.crawl_entry_url == canonical)
            )
            .first()
        )
        if row is not None:
            return row

    # Last resort: the raw frontier URL, which is what pre-M9 rows were
    # registered under when a redirect moved the stored value elsewhere.
    return (
        session.query(SourceRegistry)
        .filter(
            (SourceRegistry.official_url == url) | (SourceRegistry.crawl_entry_url == url)
        )
        .first()
    )
