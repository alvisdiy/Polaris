"""Page intent — what *kind of page* is this, before asking what it says.

POST-M10 measured the cost of not having this. 36 curated official targets
produced 9 extraction successes and 0 new records; the M10 review pilot found
6 of its 8 pages were index or overview pages. Both failures share one cause:
nothing in the pipeline could tell "this page mentions scholarships" from
"this page *is* one scholarship". The URL-level classifier in
`acquisition_policy` can only read a path and an anchor, which is why six of
eight pilot pages looked like scholarship pages and yielded nothing.

This module reads the fetched document. It is deterministic and evidence-based:
every verdict carries the observations that produced it, and insufficient
evidence produces ``UNKNOWN`` rather than a guess. An LLM is not consulted and
could not be made authoritative here without breaking that property.

    SCHOLARSHIP_DETAIL   one specific opportunity — extract this
    SCHOLARSHIP_INDEX    a list of opportunities — expand it, never extract it
    SCHOLARSHIP_OVERVIEW describes a family of opportunities — expand it
    PROVIDER_INFORMATION an organisation profile — expand it
    UNIVERSITY_INFORMATION a university's own pages — expand it
    APPLICATION_PORTAL   a login or form, not a description
    NEWS_ANNOUNCEMENT    dated commentary — not an opportunity page
    FAQ                  questions about a programme — not an opportunity
    GENERAL_PROGRAMME_PAGE a programme/course page without funding detail
    IRRELEVANT           not scholarship content at all
    UNKNOWN              the evidence does not settle it

The distinction that matters downstream is `is_detail` versus
`is_discovery_surface`. An index page is not a failed page: it is the cheapest
place to find fifty detail pages, and the previous funnel threw it away.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

from services.domain.page_labels import section_label
from services.exploration.url_utils import normalize_url


class PageIntent:
    SCHOLARSHIP_DETAIL = "SCHOLARSHIP_DETAIL"
    SCHOLARSHIP_INDEX = "SCHOLARSHIP_INDEX"
    SCHOLARSHIP_OVERVIEW = "SCHOLARSHIP_OVERVIEW"
    PROVIDER_INFORMATION = "PROVIDER_INFORMATION"
    UNIVERSITY_INFORMATION = "UNIVERSITY_INFORMATION"
    APPLICATION_PORTAL = "APPLICATION_PORTAL"
    NEWS_ANNOUNCEMENT = "NEWS_ANNOUNCEMENT"
    FAQ = "FAQ"
    GENERAL_PROGRAMME_PAGE = "GENERAL_PROGRAMME_PAGE"
    IRRELEVANT = "IRRELEVANT"
    UNKNOWN = "UNKNOWN"


# Intents that exist to be followed, not to be extracted from.
_DISCOVERY_SURFACES = frozenset(
    {
        PageIntent.SCHOLARSHIP_INDEX,
        PageIntent.SCHOLARSHIP_OVERVIEW,
        PageIntent.PROVIDER_INFORMATION,
        PageIntent.UNIVERSITY_INFORMATION,
        PageIntent.GENERAL_PROGRAMME_PAGE,
    }
)

# Vocabulary. Kept as plain tuples so a country's terminology pack can extend
# them without this module knowing where it came from.
_FUNDING_NOUNS = (
    "scholarship", "fellowship", "bursary", "stipend", "grant", "award",
    "studentship", "financial aid", "financial support", "tuition waiver",
    "tuition bursary", "postgraduate award", "studentship",
)
_FUNDING_NOUNS_JP = ("奨学金", "奨学生", "支給")
_FUNDING_NOUNS_KO = ("장학금", "학자금")
_FUNDING_NOUNS_ZH = ("奖学金", "助学金", "资助")
_FUNDING_NOUNS_ID = ("beasiswa",)
_FUNDING_NOUNS_DE = ("stipendium", "stipendien", "förderung")
_FUNDING_NOUNS_FR = ("bourse", "bourses", "aide financière", "allocation")
_FUNDING_NOUNS_ALL = (
    _FUNDING_NOUNS + _FUNDING_NOUNS_JP + _FUNDING_NOUNS_KO
    + _FUNDING_NOUNS_ZH + _FUNDING_NOUNS_ID + _FUNDING_NOUNS_DE + _FUNDING_NOUNS_FR
)

#: Public alias. Discovery link-filtering needs the same vocabulary this
#: classifier uses, and a second copy of it would drift.
FUNDING_TERMS = _FUNDING_NOUNS_ALL

# Language that only appears on a page describing *one* award.
_DEADLINE_LANGUAGE = (
    "application deadline", "deadline", "closing date", "applications close",
    "apply by", "applications must be", "deadline for applications",
    # Added in V0.1 after measuring 319 stored pages: "application period" or
    # "application window" appears in 47 of them and the phrases above missed 31
    # of those documents entirely. "close on" / "closes on" cover 7 more. These
    # are the same claim in different words, not a looser one. Bare "open on" is
    # deliberately absent: an exhibition is open on a date too.
    "application period", "application window", "application date",
    "close on", "closes on", "応募期限", "応募期間", "締切", "마감",
    "접수 마감", "신청 기간", "신청 마감", "batas pendaftaran",
    "tenggat pendaftaran", "截止日期", "申请截止", "申请时间", "报名截止",
    "bewerbungsfrist", "bewerbungsschluss", "antragsfrist", "date limite",
    "clôture des candidatures", "date limite de candidature",
    "申请的截止", "申請期限", "마감", "batas akhir",
)
_ELIGIBILITY_LANGUAGE = (
    "eligibility", "eligible", "who can apply", "to be eligible", "criteria",
    "requirements", "open to", "applicants must", "入选", "Eligibility criteria",
    "応募資格", "出願資格", "対象者", "지원 자격", "신청 자격", "자격 요건",
    "申请资格", "申请条件", "申請條件", "适用对象", "资格要求",
    "persyaratan", "syarat pendaftaran", "kriteria",
    "voraussetzungen", "teilnahmebedingungen", "bewerbungsvoraussetzungen",
    "conditions d'éligibilité", "critères d'éligibilité", "conditions de candidature",
)
_BENEFIT_LANGUAGE = (
    "tuition fees", "tuition fee", "living allowance", "monthly stipend",
    "accommodation", "health insurance", "travel costs", "airfare", "benefits",
    "what you get", "covers the cost", "授業料", "奨学金額", "支給額", "生活費",
    "등록금", "생활비", "장학금액", "지원 내용", "奖学金金额", "资助金额",
    "学费", "生活费", "资助内容", "biaya kuliah", "tunjangan hidup",
    "cakupan beasiswa", "manfaat beasiswa",
    "studiengebühren", "lebenshaltungskosten", "stipendienhöhe", "förderumfang",
    "frais de scolarité", "allocation mensuelle", "montant de la bourse", "frais de vie",
)
_APPLICATION_LANGUAGE = (
    "how to apply", "application procedure", "application process", "apply now",
    "application form", "documents required", "submit your application",
    "応募方法", "申請方法", "出願方法", "신청 방법", "지원 방법", "申请方式",
    "申请办法", "申请手续", "cara mendaftar", "prosedur pendaftaran",
    "bewerbungsverfahren", "bewerbungsunterlagen", "comment postuler",
    "modalités de candidature", "dossier de candidature",
)
_RECIPIENT_LANGUAGE = (
    "awardee", "recipients", "selected students", "successful applicants",
    "each year", "per year", "students will receive", "worth", "value of",
    "採用人数", "受給者", "선발 인원", "수혜자", "资助对象", "录取人数",
    "penerima beasiswa", "kuota penerima",
    "stipendiaten", "bénéficiaires", "lauréats", "nombre de bourses",
)
_CATEGORY_LANGUAGE = (
    "undergraduate scholarships", "postgraduate scholarships", "graduate scholarships",
    "phd scholarships", "doctoral scholarships", "types of scholarships",
    "scholarship opportunities", "scholarship programmes", "scholarship programs",
    "list of scholarships", "available scholarships", "all scholarships",
    "奨学金一覧", "奨学金制度", "奨学金情報", "장학금 목록", "장학금 프로그램",
    "장학금 안내", "奖学金列表", "奖学金项目", "奖学金信息",
    "daftar beasiswa", "program beasiswa", "jenis beasiswa",
    "stipendienübersicht", "stipendienprogramme", "liste des bourses",
    "types de bourses", "bourses disponibles",
)
_PORTAL_LANGUAGE = (
    "sign in", "log in", "login", "create an account", "my application",
    "application portal", "portal login", "register your account", " applicant login",
)
_NEWS_LANGUAGE = (
    "press release", "news release", "announcement", "read more", "posted on",
    "share this page", "related news", "news article", "blog",
)
_PROVIDER_LANGUAGE = (
    "about us", "about the", "our mission", "who we are", "contact us",
    "organisational structure", "organizational structure", "annual report",
    "governance", "our history",
)
_UNIVERSITY_LANGUAGE = (
    "admissions", "campus", "faculty", "our programmes", "study at",
    "why study", "research strengths", "facilities", "student life",
)

_QUESTION_SHAPE = re.compile(r"^(how|what|when|where|who|which|why|can|do|does|is|are)\b", re.I)
_YEAR = re.compile(r"(19|20)\d{2}")
# A date at the front of a title is the strongest news signal there is.
_TITLE_DATE = re.compile(r"^\s*(\d{1,2}[./-]\d{1,2}[./-]\d{2,4}|\d{4}-\d{2}-\d{2})\b")

# A page that says it is a FAQ, in its own title, is a FAQ. Question-shaped
# headings alone are too weak: several detail pages have an eligibility
# section that starts with "Do applicants need...".
_FAQ_TITLE = re.compile(r"\bfaqs?\b|\bfrequently asked\b|\b常见问题\b|\bQ\s*&\s*A\b", re.I)

# Titles that declare a collection rather than an award. These pages are worth
# following precisely because they say out loud that they are a list.
_OVERVIEW_TITLE = re.compile(
    r"\ban overview\b|\boverview of\b|\btypes of\b|\blist of\b|\ball scholarships\b"
    r"|\bscholarship types\b|\ba guide to\b|\bintroduction to\b|\bfaq\b"
    r"|\bscholarships? offered\b|\bscholarships? for\b|\bscholarships? by\b"
    r"|\bscholarship opportunities\b|\bfunding opportunities\b"
    r"|奨学金一覧|奨学金制度|奨学金情報|장학금 목록|장학금 프로그램|장학금 안내"
    r"|奖学金列表|奖学金项目|奖学金信息|daftar beasiswa|program beasiswa|jenis beasiswa"
    r"|Stipendienübersicht|Stipendienprogramme|Liste der Stipendien"
    r"|liste des bourses|types de bourses|bourses disponibles",
    # These terms are common collection labels in configured European locales.
    re.I,
)

#: A title that names *one* programme rather than a family of them. Singular on
#: purpose: "Hilde Domin Programme" is one award, "Graduate Scholarships" is a
#: collection, and the plural forms are how publishers spell the collection.
_ONE_PROGRAMME_TITLE = re.compile(
    r"\b(programme|program|scholarship|fellowship|studentship|award|grant)\b",
    re.I,
)

# Headline verbs. "X receives scholarship" is a story about someone who
# already won; the page describes a person, not an open opportunity.
_NEWS_VERB = re.compile(
    r"\b(receives|received|awarded|wins|won|announces|announced|honou?rs?|"
    r"celebrates|congratulates|visits|speaks|anniversary)\b",
    re.I,
)
_NEWS_PATH = re.compile(r"/(news|blog|press|press-release|media|events|articles?)/", re.I)

# A path segment that is a bare noun ("scholarships", "funding") describes a
# collection. One that carries a specific token or a year describes one award.
_COLLECTION_SEGMENTS = frozenset(
    {"scholarships", "scholarship", "fellowships", "fellowship", "grants", "grant",
     "bursaries", "awards", "funding", "financial-aid", "financial-support",
     "opportunities", "scholarship-types", "scholarship-types-and-eligibility"}
)

# Pages that describe how to apply rather than what is being applied for.
# They sit on official scholarship sites, they use the funding vocabulary, and
# they are not opportunities. Without this they read as detail pages.
_GUIDANCE_TITLE = re.compile(
    r"\bimportant information\b|\binformation for\b|\bhow to apply\b|\bapplying\b"
    r"|\bfor applicants\b|\bbefore you apply\b|\btips\b|\bguidance\b|\bfaq\b",
    re.I,
)

# A path that names a collection or a process rather than one award. The last
# segment of ``/grants/fellowship-program/`` is a programme; ``/topics/2026/``
# and ``/fees-and-funding/`` are places that list or explain them.
_COLLECTION_PATH = re.compile(
    r"/(?:topics?|categories?|category|tag|archive|archives|fees|fees-and-funding"
    r"|tuition-fees|how-to-apply|application-process|application-procedure"
    r"|guidelines|scholarship-list|list-of-scholarships)/",
    re.I,
)


def _any(text: str, terms) -> list[str]:
    return [t for t in terms if t and t in text]


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


@dataclass(frozen=True)
class PageIntentResult:
    """One verdict, and the observations that produced it."""

    intent: str
    confidence: float
    evidence: tuple[str, ...] = ()
    funding_mentions: int = 0
    programme_links: int = 0
    detail_signals: tuple[str, ...] = ()
    signals: dict = field(default_factory=dict)

    @property
    def is_detail(self) -> bool:
        """Extract this page as one scholarship."""
        return self.intent == PageIntent.SCHOLARSHIP_DETAIL

    @property
    def is_discovery_surface(self) -> bool:
        """Follow this page's links instead of extracting from it."""
        return self.intent in _DISCOVERY_SURFACES

    @property
    def is_terminally_unusable(self) -> bool:
        """Nothing here and nothing to follow. Do not spend a fetch again."""
        return self.intent in (PageIntent.IRRELEVANT, PageIntent.APPLICATION_PORTAL)


def programme_link_count(anchors: list[str]) -> int:
    """How many link labels on this page name a funding opportunity.

    An index page's defining feature is not that it mentions scholarships, it
    is that it *links to* many of them.
    """
    seen: set[str] = set()
    for anchor in anchors or []:
        label = _norm(anchor).casefold()
        if not label or label in seen:
            continue
        if _any(label, _FUNDING_NOUNS_ALL):
            seen.add(label)
    return len(seen)


def classify_page_intent(
    *,
    url: str = "",
    page_title: str = "",
    headings: list[str] | None = None,
    anchors: list[str] | None = None,
    text: str = "",
    content_type: str = "html",
) -> PageIntentResult:
    """Decide what kind of page this is, from what is actually on it.

    Conservative by construction: a page with no funding claim and no
    programme links is ``UNKNOWN``, not a scholarship. Over-claiming here is
    the failure mode this module exists to stop.
    """
    headings = headings or []
    anchors = anchors or []
    title = _norm(page_title)
    title_lower = title.casefold()
    h1 = _norm(headings[0]) if headings else ""
    h1_lower = h1.casefold()
    path = urlparse(normalize_url(url)).path if url else ""
    segments = [s for s in path.split("/") if s]
    last_segment = segments[-1] if segments else ""

    body = (text or "")[:20000].casefold()
    # Headings are the page's own claims about its own structure; counting
    # them separately from body prose avoids mistaking a passing mention for
    # a section.
    headings_text = " | ".join(_norm(h).casefold() for h in headings[:20])
    own_claim = f"{title_lower} {h1_lower} {headings_text}"

    programme_links = programme_link_count(anchors)
    deadline_hits = _any(body, _DEADLINE_LANGUAGE)
    eligibility_hits = _any(body, _ELIGIBILITY_LANGUAGE)
    benefit_hits = _any(body, _BENEFIT_LANGUAGE)
    application_hits = _any(body, _APPLICATION_LANGUAGE)
    recipient_hits = _any(body, _RECIPIENT_LANGUAGE)
    category_hits = _any(own_claim, _CATEGORY_LANGUAGE)
    portal_hits = _any(body, _PORTAL_LANGUAGE)
    news_hits = _any(own_claim + " " + body[:3000], _NEWS_LANGUAGE)
    provider_hits = _any(own_claim, _PROVIDER_LANGUAGE)
    university_hits = _any(own_claim, _UNIVERSITY_LANGUAGE)

    title_funding = _any(title_lower + " " + h1_lower, _FUNDING_NOUNS_ALL)
    body_funding = len(_any(body, _FUNDING_NOUNS_ALL))

    question_headings = sum(1 for h in headings[:20] if _QUESTION_SHAPE.match(_norm(h)))
    has_year_in_path = bool(_YEAR.search(path))
    collection_last = last_segment.casefold().replace("_", "-").replace("%20", "-") in _COLLECTION_SEGMENTS

    detail_signals = []
    if deadline_hits:
        detail_signals.append(f"deadline language: {deadline_hits[:3]}")
    if eligibility_hits:
        detail_signals.append(f"eligibility language: {eligibility_hits[:3]}")
    if benefit_hits:
        detail_signals.append(f"benefit language: {benefit_hits[:3]}")
    if recipient_hits:
        detail_signals.append(f"recipient/value language: {recipient_hits[:3]}")

    #: How many independent detail signal families the page shows. A page that
    #: states its own deadline, eligibility rules and value is describing one
    #: programme, whatever else it links to; an index states none of them.
    detail_points = len({s.split(":")[0] for s in detail_signals})

    signals = {
        "path": path,
        "title_funding_claim": bool(title_funding),
        "body_funding_mentions": body_funding,
        "programme_links": programme_links,
        "question_headings": question_headings,
        "year_in_path": has_year_in_path,
        "last_segment_is_collection": collection_last,
        "anchor_count": len(anchors),
        "heading_count": len(headings),
        "text_length": len(text or ""),
    }

    def done(intent: str, confidence: float, evidence: list[str]) -> PageIntentResult:
        return PageIntentResult(
            intent=intent,
            confidence=round(confidence, 3),
            evidence=tuple(evidence),
            funding_mentions=body_funding,
            programme_links=programme_links,
            detail_signals=tuple(detail_signals),
            signals=signals,
        )

    # 1. Nothing here at all.
    if not body and not title:
        return done(PageIntent.IRRELEVANT, 0.6, ["no title and no readable text"])

    # 2. Login walls are not descriptions of anything.
    if len(portal_hits) >= 2 and not title_funding:
        return done(
            PageIntent.APPLICATION_PORTAL,
            0.75,
            [f"portal/login language without a funding claim: {portal_hits[:3]}"],
        )

    # 3. Dated commentary, or a headline about someone who already won.
    news_reason = None
    if _TITLE_DATE.match(title):
        news_reason = "date-prefixed title"
    elif _NEWS_PATH.search(path):
        news_reason = f"news path: {path}"
    elif _NEWS_VERB.search(title):
        news_reason = f"headline describes an event, not an open call: {title[:80]!r}"
    elif news_hits and not title_funding:
        news_reason = f"news/announcement wording: {news_hits[:3]}"
    if news_reason:
        return done(PageIntent.NEWS_ANNOUNCEMENT, 0.75, [news_reason])

    # 4. FAQ: a self-declared one, or question-shaped headings in the majority.
    if _FAQ_TITLE.search(title):
        return done(PageIntent.FAQ, 0.8, [f"title declares a FAQ: {title[:80]!r}"])
    if len(headings) >= 3 and question_headings >= max(2, len(headings[:20]) // 2):
        return done(
            PageIntent.FAQ,
            0.75,
            [f"{question_headings} question-shaped headings of {min(len(headings), 20)}"],
        )

    # 4b. Guidance about applying is not an opportunity to apply to.
    if _GUIDANCE_TITLE.search(title):
        return done(
            PageIntent.GENERAL_PROGRAMME_PAGE,
            0.7,
            [f"title describes guidance, not an award: {title[:80]!r}"],
        )

    # 4c. A section label is the page's own table of contents, not a programme.
    #     "Fellowship Categories", "JSPS Topics" and "Fees and funding" all
    #     mention funding somewhere; none of them is something a student can
    #     apply to.
    label = section_label(title) or section_label(h1)
    if label:
        # An organisation's own "About us" page is a provider page, not a
        # programme index. The label still decides that it is not a DETAIL.
        if provider_hits and not title_funding:
            return done(
                PageIntent.PROVIDER_INFORMATION,
                0.7,
                [f"organisation page with a section label: {label[:80]!r}"],
            )
        return done(
            PageIntent.SCHOLARSHIP_INDEX if programme_links >= 3 else PageIntent.GENERAL_PROGRAMME_PAGE,
            0.8,
            [f"title is a section label, not a programme: {label[:80]!r}"],
        )

    # 4d. A collection path with no detail language is an index. The path is
    #     the page's identity, and ``/topics/`` is not where one award lives.
    if _COLLECTION_PATH.search(path) and detail_points == 0:
        return done(
            PageIntent.SCHOLARSHIP_INDEX,
            0.75,
            [f"collection path: {path}"],
        )

    # 5. A collection by its own path: /scholarships is a list even if the
    #    body reads like a description.
    if collection_last and programme_links >= 3:
        return done(
            PageIntent.SCHOLARSHIP_INDEX,
            0.8,
            [f"last path segment is a collection word: {last_segment!r}",
             f"{programme_links} funding links on the page"],
        )

    # 6. The index shape: the page's own headings are category labels and it
    #    links to many named opportunities.
    #
    #    Link count is weak evidence on its own: every modern government site's
    #    footer links to its programme catalogue, so a single programme's page
    #    routinely carries five funding-named links. Measured on the 2026-10
    #    DAAD run: "Hilde Domin Programme" states a nomination deadline, target
    #    group, funding period and value, and was still read as an index because
    #    its navigation offered five programme links — so a real award was
    #    fetched and then thrown away unread.
    #
    #    What settles it is the page's own claim, not its link count: a title
    #    that names one programme (singular — "Hilde Domin Programme" versus
    #    "Funding Options") plus at least one stated detail. The DAAD "Funding
    #    Options" index also mentions a deadline and eligibility; what it does
    #    not do is name an award in its title.
    describes_one_programme = (
        detail_points >= 1
        and not collection_last
        and bool(_ONE_PROGRAMME_TITLE.search(title))
        and not _OVERVIEW_TITLE.search(title)
    )
    if (
        programme_links >= 5
        and (category_hits or not title_funding)
        and not describes_one_programme
    ):
        return done(
            PageIntent.SCHOLARSHIP_INDEX,
            0.8,
            [f"{programme_links} funding links on the page",
             f"category headings: {category_hits[:3] or 'none'}",
             f"own funding claim: {bool(title_funding)}"],
        )

    # 6b. A title that declares a collection settles it before anything else,
    #     because the publisher has already answered the question.
    if title_funding and _OVERVIEW_TITLE.search(title):
        return done(
            PageIntent.SCHOLARSHIP_OVERVIEW,
            0.8,
            [f"title declares a collection: {title[:80]!r}",
             f"{programme_links} funding links on the page"],
        )

    # 7. A detail page: the page names one opportunity and states how to get
    #    it. Two independent detail signals, or three counting the claim.
    #
    #    The single-signal case is narrow on purpose: a title that names one
    #    award, a year in the path and a slug that is not a collection word is
    #    a specific claim, and the M9 acquisition fixture is exactly that shape.
    #    Index pages do not reach here — rules 5, 6 and 6b claim them first —
    #    and a collection-shaped page contributes no claim point at all.
    claim_points = 1 if title_funding else 0
    claim_points += 1 if has_year_in_path else 0
    claim_points += 1 if not collection_last else 0
    specific_claim = claim_points >= 3
    if title_funding and detail_points >= 2 and claim_points >= 2:
        confidence = min(0.95, 0.55 + 0.1 * detail_points)
        return done(
            PageIntent.SCHOLARSHIP_DETAIL,
            confidence,
            [f"page claims a funding opportunity: {title or h1[:80]!r}"] + detail_signals,
        )
    if title_funding and detail_points >= 1 and specific_claim:
        return done(
            PageIntent.SCHOLARSHIP_DETAIL,
            min(0.8, 0.55 + 0.1 * detail_points),
            [f"page names one award specifically: {title or h1[:80]!r}"] + detail_signals,
        )

    # 8. An overview describes a family: funding vocabulary, a claim, but no
    #    single award's instructions.
    if title_funding and detail_points < 2:
        return done(
            PageIntent.SCHOLARSHIP_OVERVIEW,
            0.6,
            [f"page claims funding without stating one award: {title or h1[:80]!r}",
             f"{programme_links} funding links, {detail_points} detail sections"],
        )

    # 9. Organisation or institution pages.
    if provider_hits and not title_funding:
        return done(PageIntent.PROVIDER_INFORMATION, 0.6,
                    [f"organisation language: {provider_hits[:3]}"])
    if university_hits and not title_funding:
        return done(PageIntent.UNIVERSITY_INFORMATION, 0.6,
                    [f"institution language: {university_hits[:3]}"])

    # 10. A programme page that simply has no funding on it.
    if application_hits and not title_funding and not body_funding:
        return done(PageIntent.GENERAL_PROGRAMME_PAGE, 0.5,
                    [f"application process without funding: {application_hits[:3]}"])

    # 11. Mentions funding only in passing, from a page that is not about it.
    #
    #     The rule reads anchor structure: a page that links to nothing
    #     scholarship-shaped while mentioning funding is talking *about*
    #     funding, not offering it. A PDF has no anchors at all — its empty
    #     link list is structural absence, not evidence — so the same
    #     silence cannot condemn it. Without a title claim (PDFs arrive with
    #     no HTML title) the evidence does not settle the question, and
    #     UNKNOWN is what acquisition deliberately extracts.
    if not title_funding and body_funding and programme_links == 0:
        if content_type != "html":
            return done(PageIntent.UNKNOWN, 0.0,
                        [f"non-HTML document ({content_type}) with {body_funding} funding "
                         "mentions; no link structure to read, evidence does not settle it"])
        return done(PageIntent.IRRELEVANT, 0.5,
                    [f"{body_funding} passing funding mentions, no links, no claim"])

    # 12. The evidence does not settle it. Say so.
    return done(
        PageIntent.UNKNOWN,
        0.0,
        [f"no funding claim in title/h1 ({bool(title_funding)}), "
         f"{programme_links} programme links, {detail_points} detail sections"],
    )
