# Polaris Web Design Specification

> **Document status:** design specification only. This document defines the Polaris web
> product experience. It does not ship frontend code; implementation follows only after this
> specification is approved.
>
> **Sources of truth used:** `docs/design.md` (as-built backend design), the actual API
> implementation (`api/app.py`, `api/routers/scholarships.py`, `api/routers/recommendations.py`,
> `api/schemas.py`), the matching models (`services/matching/models/*`), and the existing
> `frontend/` scaffold. Every endpoint and field referenced here was verified against code.
> Capabilities the backend does not yet provide are explicitly marked **Future API Requirement**.

---

## 1. Design Goals

Polaris is a scholarship intelligence platform. The web product turns the verified scholarship
knowledge base and the deterministic matching engine into a coherent experience for students.

The interface optimizes for:

1. **Trust through evidence.** Every scholarship points to its official source. Provenance is
   never hidden or summarized away.
2. **Honest freshness.** Users always know whether an opportunity is current, rolling, unknown,
   or past its deadline. Expired opportunities are never presented as current.
3. **Clarity over decoration.** The product reads like a well-edited research publication, not
   a marketing site and not a generic SaaS dashboard.
4. **Two connected modes.** Discovery (browse and search the knowledge base) and Matching
   (profile-driven ranking) are one product: the same scholarship card, the same detail page,
   the same trust language in both.
5. **Low cognitive load.** Progressive disclosure: summary first, evidence on demand.
6. **Deterministic intelligence, honestly presented.** Matching scores are explained, never
   mystified, never sold as predictions.

The frontend is a consumer of the knowledge base and matching API. It is not the discovery
engine.

## 2. Product UX Principles

| Principle | Meaning in practice |
|---|---|
| Source-first trust | The official source URL is visible at every level where a scholarship appears (card, detail, match result). A scholarship without a visible source link is a defect. |
| Current and fresh information | Deadline state is communicated with badge, color, and text together (never color alone). Expired items are excluded from discovery by the backend and, if reached directly, are shown as archive. |
| Evidence before interpretation | Requirements, benefits, and timeline (official-source-derived fields) are shown before any Polaris commentary. Match explanations quote concrete criteria. |
| Clarity over decoration | No decorative animation on data. Motion is reserved for state feedback and orientation. |
| Progressive disclosure | Cards and section headers summarize; detail pages disclose; a "how this was collected" affordance explains provenance for those who want it. |
| Consistent interaction | The same scholarship card, badge system, and empty/error states are reused across Home, Discover, Match, and Compare. |
| Accessibility | WCAG AA contrast, full keyboard navigation, visible focus, semantic HTML, reduced-motion support. |
| Responsive behavior | Mobile is a first-class layout: filters become sheets, compare becomes stacked cards, navigation collapses. |
| No fabrication | The UI never invents scholarship facts, deadlines, statistics, or testimonials. Unknown is labeled unknown. |

## 3. Target Users

**Primary persona: Indonesian university student (S1/S2) exploring international scholarships.**

- Reads Bahasa Indonesia as first language, English comfortably (scholarship data itself is
  English).
- Workflow: arrive, explore, search/filter, open detail, check eligibility/funding/deadline and
  the official source, build a profile, get matched, understand why, compare shortlist, decide
  what to apply for.
- Device reality: mobile-first for browsing, desktop for comparing and form filling.

**Secondary users and use cases:**

- University career-center or scholarship-corner staff demonstrating options to students
  (desktop, comparison heavy).
- Parents or sponsors reviewing funding coverage and deadlines (read-only, detail pages).
- Future: providers and researchers auditing coverage. Not designed for in this phase.

## 4. Information Architecture

```
Home                         /            What Polaris is, two entries (Discover, Match)
Discover                     /discover    Search, filter, browse the approved knowledge base
Scholarship Detail           /scholarships/:id   Full record, provenance, official link
Match                        /match       Profile form and ranked results
Compare                      /compare     Side-by-side of 2 to 4 shortlisted scholarships
Shortlist (Saved)            /saved       Locally saved list (browser storage)
About and Method             /about       How data is collected, verified, and scored
```

Notes:

- Only areas that the current backend supports are included. There is no admin UI, no provider
  directory pages, no coverage dashboard (all would need **Future API Requirements**; see
  section 29).
- Shortlist uses browser-local storage because the backend has no persistence
  (**Future API Requirement**, P1). This is stated honestly in the UI ("tersimpan di
  peramban ini").
- About and Method exists because trust claims need a real page that explains collection,
  verification, and scoring. Its content is derived from `docs/design.md` (real process, no
  invented claims).

## 5. Navigation Architecture

**Desktop (top navigation bar):**

- Left: Polaris wordmark (text wordmark; a logo mark is a placeholder until provided, per the
  asset rule in section 22).
- Center/right: "Jelajahi" (to /discover), "Cocokkan Profil" (to /match), "Bandingkan" (to
  /compare, with a live count badge of shortlisted items), "Tentang" (to /about).
- Right: global search field (see below).
- Active state: current section indicated by an underline marker plus weight change; the state
  is derived from the route, not from click memory.

**Mobile (top bar plus sheet):**

- Top bar: wordmark, search icon, menu button.
- Menu opens a full-width sheet with the same four destinations, current section marked, and
  the shortlist count. Minimum tap target 44px (see section 20).

**Global search:**

- One search input in the navigation on all pages.
- Behavior: typing and submitting navigates to `/discover?q={query}`. There is no autocomplete
  in this phase: the backend search is a name-substring query (`q` parameter) and has no
  suggestion endpoint. Fake autocomplete is forbidden (**Future API Requirement**, P2).

**Contextual navigation:**

- Scholarship Detail offers "Kembali ke hasil" (returns to the last Discover or Match result
  set, preserved via URL state) and "Bandingkan" (adds to compare selection).
- Cards on Discover and Match link to Detail. Match results link to Detail and to Compare.

**Breadcrumbs:**

- Detail pages show a compact trail: `Jelajahi / {Nama Beasiswa}` or `Cocokkan / {Nama
  Beasiswa}` (derived from navigation origin; default is Jelajahi on direct entry).
- Other pages do not need breadcrumbs; the hierarchy is two levels deep at most.

## 6. Route Map

| Route | Purpose | Entry points | Required API | Important states | Auth | Future dependency |
|---|---|---|---|---|---|---|
| `/` | Product entry, orientation | Direct, navigation wordmark | `GET /api/v1/scholarships` (3 example records) | Loading, API error, empty knowledge base | None | None for v1 |
| `/discover` | Search and browse | Nav, homepage CTA, global search | `GET /api/v1/scholarships` with `q, country, degree, limit, offset` | Loading, empty result, API error, filtered-empty | None | Funding/field/deadline-state filters (P0, see 18) |
| `/scholarships/:id` | Full scholarship record | Cards, match results, compare, direct link | `GET /api/v1/scholarships/{id}` | Loading, 404 not found, 500, expired record, missing sections | None | deadline_state and last-verified exposure (P0, see 12) |
| `/match` | Profile form and results | Nav, homepage CTA, card "Cocokkan" | `POST /api/v1/matching` | Form validation (422), loading, zero results, API error | None | Criteria breakdown exposure (P1, see 14) |
| `/compare?ids=a,b,c` | Side-by-side comparison | Shortlist, detail, match results | `GET /api/v1/scholarships/{id}` per selected item | Fewer than 2 selected, loading, one record fails | None | None |
| `/saved` | Shortlist of saved scholarships | Nav badge, card save action | `GET /api/v1/scholarships/{id}` per saved id (local list) | Empty, item no longer exists (404 handling) | None | Server-side persistence (P1) |
| `/about` | Method and trust explanation | Nav footer links | None (static content) | N/A | None | None |

Authentication: none exists in the backend; no route requires or implies login. Any future
accounts feature is a backend requirement (section 29, P2) and is not designed here.

## 7. Homepage

Purpose: a first-time visitor understands within seconds what Polaris is, that the data comes
from official sources, and that there are exactly two ways to proceed.

**Structure (top to bottom):**

1. **Navigation bar** (section 5).
2. **Hero.** One clear statement, two lines maximum at desktop width
   (`max-w-5xl` container, `clamp(2.25rem, 4.5vw, 3.75rem)` sizing):
   "Beasiswa internasional, diverifikasi dari sumber resminya." Secondary line explains the
   two modes in one sentence: "Jelajahi basis data beasiswa yang terkumpul dari situs resmi,
   atau biarkan Polaris mencocokkan profil Anda."
   - Primary CTA: "Jelajahi beasiswa" (to `/discover`). Secondary CTA: "Cocokkan profil saya"
     (to `/match`). Both are solid/outline pair with full contrast (dark text on light chip,
     light text on dark chip).
   - No statistics in the hero. Polaris has no real usage statistics and must not invent any
     (backend currently exposes no aggregate counts; see section 29). No pill-tags, no badges,
     no floating icons.
3. **How it works, in Polaris terms.** Three plain steps without the generic "3 numbered
   circles" template: a short prose-and-line layout describing (a) the engine collects from
   official web sources, (b) each record keeps its source link and freshness status, (c) the
   matching engine ranks by your profile with explicit reasons. Each step links to the matching
   section of `/about` for the curious.
4. **Live examples.** Three real scholarship cards fetched from
   `GET /api/v1/scholarships?limit=3` (real data, not fabricated). A text link "Lihat semua di
   Jelajahi" leads to `/discover`. If the API fails or is empty, this section renders the
   standard error/empty state with a retry, never placeholder scholarships.
5. **Trust block.** One paragraph and one visual motif line (the provenance citation style,
   section 11): what "verified from official source" means, what "deadline unknown" means, and
   what Polaris does not do (it does not predict acceptance). Links to `/about`.
6. **Footer.** Minimal: wordmark, nav links to real pages only, and the method note "Data
   beasiswa dikumpulkan otomatis dari situs resmi; selalu konfirmasi ke halaman resmi
   sebelum mendaftar." No fake contact addresses, no social links that do not exist.

## 8. Discover Experience

Route: `/discover`. This is the primary screen.

**Layout (desktop):** left filter rail (280px) with the result list to the right; on mobile the
filter rail becomes a bottom sheet opened by a "Filter" button showing the active count.

**Search:** the list has its own query input bound to the `q` parameter (server-side substring
match on scholarship name). Search-as-you-type is debounced (300ms) and updates the URL; there
is no client-side filtering of server data.

**Filters, mapped to actual backend capability:**

| UI filter | Backend support today | Verdict |
|---|---|---|
| Kata kunci (`q`) | Yes, `q` param on `GET /api/v1/scholarships` | Supported now |
| Negara (`country`) | Yes, `country` param (name or ISO3) | Supported now |
| Jenjang (`degree`) | Yes, `degree` param | Supported now |
| Sumber pendanaan (`funding_type`) | No param exists | Future API Requirement (P0) |
| Bidang studi (`field_of_study`) | No param exists | Future API Requirement (P0) |
| Status tenggat (aktif/rolling) | No param exists; expired items are already excluded server-side | Future API Requirement (P0) |
| Facet counts (jumlah per nilai filter) | No endpoint | Future API Requirement (P1) |

Unsupported filters are not rendered as disabled controls and are not faked client-side. The
client must not filter server data in the browser and present it as complete.

The country and degree inputs present known values (from the 10 supported countries and the
degree vocabulary used by the backend: Bachelor, Master, PhD, Exchange, Short Course) as
selectable options, since these vocabularies are fixed in the backend schemas.

**Sorting:** the backend `search_approved` currently defines no client-selectable order.
No sort control is shown in v1 (a visible but non-functional control is forbidden).
**Future API Requirement** (P0): server-side `sort` parameter (proposed: relevance, deadline
ascending, newest verified first).

**Result count and pagination:**

- A result line states the total: "Menampilkan X dari Y beasiswa" using the `total` field
  (real number from the API; shown only when the request succeeds).
- Pagination: previous/next plus page indicator, driven by `limit` (default 20) and `offset`.
- Infinite scroll is not used (pagination keeps URL state shareable and avoids loading
  ambiguity).

**Filter chips:** active filters render as removable chips above the result list
(e.g. `Negara: Japan x`, `q: "MEXT" x`). Removing a chip updates the URL and refetches.

**States:**

- Initial loading: list-region skeleton with static lines (no spinner circus), announce
  "Memuat daftar beasiswa" to screen readers.
- Search/refetch loading: keep previous results visible with a subtle top progress line; do
  not flash empty.
- Empty knowledge base (total 0, no filters): explanatory empty state ("Basis data sedang
  kosong atau belum mencakup hasil") with a link to `/about` on how collection works.
- No results for filters (total 0, filters active): state distinguishes this from an empty
  database and offers "Hapus semua filter".
- API error: explicit error card with retry; the rest of the page shell remains.
- Empty `results` array with nonzero `total` (edge case): treat as error state (defensive).

## 9. Scholarship Card

One card component everywhere (Home examples, Discover list, Match results, Compare picker,
Saved list), with two variants: **browse** and **match** (match adds score elements).

**Information hierarchy:**

1. **Primary:** Scholarship name (largest text in the card).
2. **Secondary:** Provider name, country. On the match variant: match score and category badge
   (from the matching API only).
3. **Metadata row:** degree, funding type, up to 2 field-of-study tags then "+n".
4. **Deadline line:** formatted date when present; when `deadline` is `null`, the literal text
   "Tenggat tidak diketahui" (never a fabricated date, never a blank). See section 12 for state
   semantics. Note: the list API does not yet expose `deadline_state`, so the browse card
   derives display from the `deadline` value alone; the precise state badge is a **Future API
   Requirement** (P0). On the match variant, `deadline` comes from the matching response with
   the same rule.
5. **Trust line (the identity motif):** source citation line, e.g. "Sumber: studyinjapan.go.jp"
   derived from `official_url` host. This line is never omitted.
6. **CTA row:** "Lihat detail" (whole-card link to detail; the named button is the accessible
   fallback), and on the match/browse variants a save (shortlist) toggle button and a compare
   checkbox. On the match variant an additional "Kenapa cocok" link expands the explanation
   inline.

**Hover/focus:** card lifts border emphasis and the title color shifts to the interactive
color; focus-visible shows the same outline as keyboard focus. No scale/parallax on data cards
(motion dial is 1; motion is reserved for state feedback).

**Mobile layout:** same order, single column, metadata row wraps; tap targets at least 44px;
the save and compare controls remain visible (no hover-only actions).

**Expired rule:** the Discover list cannot contain expired records (backend excludes them). If
a card is rendered from local shortlist data whose detail later returns an expired record, the
detail page handles it per section 12; cards themselves never render an active-looking expired
item because the state badge (future exposure) plus detail behavior cover the gap. The card
must never show a countdown or "closing soon" implication for unknown deadlines.

## 10. Scholarship Detail

Route: `/scholarships/:id`. Data: `GET /api/v1/scholarships/{id}`.

**Page order (top to bottom):**

1. **Header block:** scholarship name (H1), provider name and provider type, country, breadcrumb.
   Primary CTA: "Buka halaman resmi" (external link to `official_url`, `rel="noopener"`, with
   an external-link icon and the host shown). Secondary CTA when `application_url` exists and
   differs: "Halaman aplikasi". Save-to-shortlist toggle and Add-to-compare button.
2. **Key facts strip:** degree, funding type, deadline (formatted or "Tenggat tidak
   diketahui"), application cycle (from `timeline.application_cycle` when present). Rendered as
   a definition list, not decorative tiles.
3. **Timeline section** (when `timeline` exists): application open, deadline, cycle, interview
   date, result date, study start. Missing sub-fields are omitted, not faked. If the whole
   timeline object is absent, the section is omitted entirely.
4. **Eligibility and requirements** (when `requirement` exists): minimum GPA, IELTS required
   plus minimum score, TOEFL required plus minimum score, work experience, research experience,
   publication expectation. Fields the record does not have are shown as "tidak disebutkan di
   sumber" only when the section exists but the value is null; if the section is null the
   section header shows with that single explanatory line (the distinction between "not
   mentioned" and "not collected" is preserved).
5. **Benefits** (when `benefit` exists): the six boolean coverages (tuition fee, monthly
   allowance, accommodation, health insurance, travel ticket, research grant) rendered as a
   two-column checklist with yes/no/not-mentioned per item.
6. **Fields of study:** tag list.
7. **Source and provenance block:** the citation motif expanded: official page link with full
   host, provider name, and (Future API Requirement) last-verified timestamp and deadline
   state. Today the block explains honestly: "Data direkam Polaris dari halaman resmi
   penyedia. Selalu periksa halaman resmi untuk informasi terbaru." A "Bagaimana data ini
   dikumpulkan" disclosure links to `/about`.
8. **Comparison affordance:** "Tambahkan ke perbandingan".

**Polaris-derived vs official-source information:** the page visually separates them. Fields 2
through 6 carry a shared label group "Informasi dari sumber resmi" (collected from the
provider's page). The provenance block and any Polaris commentary (Future: freshness notes) are
labeled "Informasi Polaris". A scholarship fact never appears without its group context.

**Progressive disclosure:** header, key facts, timeline, and provenance are immediately
visible. Requirements and benefits are visible by default on desktop and collapsed to two
expandable sections on mobile (first paint stays short). The method disclosure is always
collapsed.

**Expired record behavior:** the detail endpoint does not exclude expired records, so a direct
visit can return one. When the record's deadline is in the past (and, after the P0 exposure,
when `deadline_state == "expired"`), the page shows an archive banner: "Tenggat beasiswa ini
sudah lewat. Informasi berikut disajikan sebagai arsip." The application CTA is visually
demoted (outline, not solid) but not removed, because the official page remains the authority.

## 11. Provenance and Trust UI

Trust is a differentiator; every trust element maps to real backend data. No invented badges.

| Trust element | Data source today | UI form |
|---|---|---|
| Official source | `official_url` (list, detail, match responses) | Citation line + "Buka halaman resmi" button with visible host |
| Provider identity | `provider_name` (+ `provider_type` on detail) | Text in header and citation line |
| Application page | `application_url` (detail) | Secondary link when present and different |
| Verification status | Not exposed yet | **Future API Requirement (P0)**: `verification_state`, `last_verified_at` |
| Deadline freshness | Only `deadline` date exposed; `deadline_state` internal | Section 12 display rules; precise badges are P0 |
| Collection method | Documented process (`docs/design.md`) | `/about` page and the "Bagaimana data ini dikumpulkan" disclosure |

Rules:

- A trust indicator that has no backing field does not exist in the UI. There is no "Verified"
  checkmark anywhere until the backend exposes verification state.
- The citation line (host of `official_url`) is the product's identity motif and appears on
  cards, detail, match results, and compare columns.
- Uncertainty is stated in words: "Tenggat tidak diketahui", "Tidak disebutkan di sumber".

## 12. Deadline and Freshness UX

Backend semantics (from `docs/design.md` and the repository): `deadline_state` is one of
`active`, `rolling`, `unknown`, `expired`, or NULL (unclassified legacy). The list and matching
endpoints currently expose only the `deadline` date (nullable); the list endpoint already
excludes expired records server-side. Precise badge rendering therefore requires the state to
be exposed (**Future API Requirement, P0**). Until then, the UI renders:

| State | Badge text | Color | Icon | Explanatory text | Behavior |
|---|---|---|---|---|---|
| `active` | "Aktif" | Green | Open circle (clock outline) | "Tenggat: {date}" | Normal |
| `rolling` | "Rolling" | Teal (brand) | Circular arrows | "Dibuka terus, umumnya per periode" | Normal; sorts as current |
| `unknown` | "Tenggat tidak diketahui" | Amber | Question-mark circle | "Sumber belum menyebutkan tenggat" | Normal; never shows a fake date or countdown |
| `expired` | "Lewat tenggat" | Neutral gray | Strikethrough clock | "Ditampilkan sebagai arsip" | Excluded from Discover; archive treatment on detail; not comparable as current |
| NULL (legacy) | "Belum terklasifikasi" | Gray outline | Dashed circle | "Status tenggat belum dievaluasi" | Treated as visible-but-unlabeled; never shown as definitely active |

Design rules:

- Badge, color, icon, and text always appear together (accessibility: state is never conveyed
  by color alone).
- Dates use an explicit format ("1 Maret 2027") and are never rendered as a bare ISO string to
  users.
- No countdown timers anywhere. Countdowns imply precision the data does not have.
- Sorting behavior once a server-side sort exists (P0): active and rolling before unknown;
  expired only in archive views, never interleaved as current.

## 13. Matching Experience

Route: `/match`. Uses `POST /api/v1/matching` (the router also serves the same handler at
`POST /recommendations`; the UI uses the versioned path). The frontend runs no matching logic.

**Page structure:**

1. **Profile form** (section 16 for fields, exactly the backend schema).
2. **Submit action:** "Lihat hasil pencocokan". Submitting puts the form into a loading state
   with the button disabled and a progress line; there is no fake staged progress.
3. **Results list:** ranked `RecommendationResponse` items rendered with the match card
   variant: rank number, name, provider, country, score with category badge, explanation
   summary, strengths (top 3), gaps (top 3), deadline line, citation line, actions (detail,
   compare, save).
4. **Per-result explanation:** "Kenapa cocok" expands to show the full `explanation` text,
   complete `strengths` and `gaps` lists, and `next_steps` as an ordered list. `next_steps`
   items containing the official URL render as links.
5. **Empty result state:** "Belum ada beasiswa yang cocok dengan profil ini" plus guidance to
   adjust the profile; never padded with irrelevant items.
6. **Zero-result vs error:** a 422 shows inline field-level errors mapped from the API's
   validation detail; a 500 or network failure shows the standard error card with retry. The
   form values are preserved in both cases.

**Mode cohesion:** every match result links to the same detail page as discovery; every detail
page offers "Cocokkan dengan profil saya" in a side panel (desktop) or a bottom action bar
(mobile) that navigates to `/match`, carrying nothing but the route (the profile is client
state, section 26). Discovery and matching share the card, badges, and trust language so they
read as one product.

## 14. Match Score UX

The backend score is a deterministic weighted sum (0 to 100) of criteria: country, degree,
field of study, GPA, language, funding, research, work, leadership. Categories: Excellent
Match (90+), Strong Match (80+), Good Match (70+), Moderate Match (60+), Low Match otherwise.

Presentation rules:

- The score is shown as "Skor kecocokan: 87 / 100" with the category as a badge
  ("Kecocokan sangat baik" for Excellent Match, and equivalent Indonesian labels for the other
  tiers).
- The score is explicitly labeled "Skor kecocokan berbasis kriteria" with a persistent
  one-line note: "Skor ini bukan prediksi peluang diterima." This note appears on the match
  results header once and again inside the expanded explanation.
- The criteria-level breakdown (per-criterion score/weight/reason) exists inside the backend
  engine but is not part of the API response today. The UI therefore shows only the response
  fields: total score, category, explanation, strengths, gaps, next steps. A per-criterion
  bar breakdown is designed but gated behind **Future API Requirement (P1)** (expose
  `criteria` in `RecommendationResponse`).
- No gauge dials, no percentage-of-fit rings, no AI language. The score is what the engine
  computed, no more.

## 15. Compare Experience

Route: `/compare?ids={id1},{id2,...}`.

- **Selection mechanism:** compare checkboxes on cards and detail (label "Bandingkan"), stored
  client-side (section 26), minimum 2 and maximum 4 items; the compare nav badge shows the
  current count. Navigating to `/compare` with fewer than 2 selected shows an explanatory
  empty state with a link to `/discover`.
- **Data:** each column fetches `GET /api/v1/scholarships/{id}`. A failing fetch renders a
  per-column error with retry instead of breaking the table.
- **Fields compared (rows):** provider (with provider type), country, degree, funding type,
  deadline (with state semantics from section 12), application cycle, minimum GPA, IELTS/TOEFL
  minimums, the six benefit booleans, official source link. Rows missing data show "Tidak
  disebutkan"; they are never blank.
- **Deadline comparison** respects section 12: unknown is a stated value, expired is shown as
  archive, never silently equalized.
- **Application CTA row:** one row of "Buka halaman resmi" links, one per column.
- **Mobile behavior:** the table becomes stacked per-scholarship panels with row labels as
  section headers (no horizontal-scrolling mega-table); a sticky field-label column is
  explicitly avoided on small screens.

## 16. Profile Experience

The form mirrors the backend `RecommendationRequest` exactly (verified against
`api/schemas.py`). No invented fields.

**Required fields (backend rejects their absence):**

| Field | Control | Constraint |
|---|---|---|
| `target_country` | Select from the 10 supported countries (backend matches on name) | Free string per API; UI constrains to real values |
| `degree` | Radio group: Bachelor, Master, PhD, Exchange, Short Course | Must be one of the vocabulary |
| `field_of_study` | Tag input, minimum 1 | Array, min length 1 |
| `current_gpa` | Number input 0.0 to 4.0, step 0.01, scale explained inline | 0 to 4 enforced |
| `research_experience` | Radio: Not Required, Optional, Preferred, Required | Vocabulary from schema description |
| `work_experience` | Radio: Not Required, Optional, Preferred, Required | Vocabulary |
| `publication` | Radio: Not Required, Optional, Preferred, Required | Vocabulary |
| `leadership` | Checkbox (yes/no) | Boolean |
| `funding_preference` | Radio: Fully Funded, Partial Funded, Tuition Only | Vocabulary |

**Optional fields:** `ielts_score` (0.0 to 9.0) and `toefl_score` (0 to 120, integer); both
default to "belum diambil" (null). Filling both is allowed; the engine handles them.

**Field-of-study input:** free text tags (the backend compares as strings). A short helper
line shows an example ("misal: Computer Science, Public Health"). No fake autocomplete list
(backend has no field vocabulary endpoint; **Future API Requirement**, P2).

**Validation:** client-side mirrors the API constraints (required, ranges, min length); on
submit, server 422 details ("field -> message" strings from the API validation handler) are
parsed and mapped onto the corresponding fields; unmapped errors surface in a form-level alert.

**Profile completeness:** since every field except the two language scores is required, a
completeness meter is unnecessary and would be decorative; it is omitted.

**Saved state:** the profile persists to browser localStorage under a versioned key after each
successful match, with an explicit "Profil tersimpan di peramban ini" note and a clear-control.
Server-side profile persistence is a **Future Backend/API Requirement** (P1). There is no
login, no account, no sync.

## 17. Search UX

- **Global search** (navigation, all pages): submits to `/discover?q={term}`. On mobile it is
  an icon that opens a full-width search bar. No autocomplete (no backend support; P2 future).
- **Discover search:** bound to the `q` parameter, debounced, URL-synced, server-executed.
- **No-result behavior:** section 8's two distinct empty states.
- **Query persistence:** the full search state lives in the URL (section 27), so refresh and
  share reproduce the result set.
- **Search state on navigation away and back:** navigating to a detail and using "Kembali ke
  hasil" returns to the Discover URL exactly as left (browser history preserves the URL).

## 18. Filtering and Sorting UX

| Dimension | UI control | Backend status |
|---|---|---|
| Keyword `q` | Text input | **Supported now** |
| Country | Select (10 values) | **Supported now** (`country` param) |
| Degree | Select (5 values) | **Supported now** (`degree` param) |
| Funding type | Radio list | **Future API Requirement** (P0): `funding_type` param |
| Field of study | Tag input | **Future API Requirement** (P0): `field_of_study` param |
| Deadline state | Checkbox group (aktif, rolling, unknown) | **Future API Requirement** (P0): `deadline_state` param; expired is server-excluded already |
| Pagination | limit/offset | **Supported now** |
| Sorting | Sort select | **Future API Requirement** (P0): `sort` param |
| Facet counts | counts per filter value | **Future API Requirement** (P1) |

Rules: unsupported filters are not rendered (not even disabled). Client-side filtering over
server data is forbidden because it produces misleading completeness. When the P0 filter
parameters land, each control activates with the same chip/URL behavior as the existing ones.

## 19. Responsive Design

| Breakpoint | Layout decisions |
|---|---|
| Desktop (>= 1024px) | Discover uses left filter rail; match page uses form-left, tips-right; compare is a full table; nav is a horizontal bar with inline search |
| Tablet (640 to 1023px) | Filter rail collapses to a toggleable side drawer; compare table allows horizontal scroll within its container with sticky first column; nav keeps primary links, search collapses to icon |
| Mobile (< 640px) | Single column everywhere; filters open as a bottom sheet with an active-count button; compare becomes stacked panels (section 15); nav becomes menu sheet; forms are single column with full-width controls; tap targets >= 44px |

Cross-cutting rules:

- No horizontal page overflow at any breakpoint; wide tables scroll within their own
  containers only.
- The scholarship card reflows (metadata wraps) rather than truncating provider or deadline.
- Filter and menu sheets trap focus while open and close on Escape (section 20).
- Text never relies on hover for disclosure on touch devices (explanations expand by tap).

## 20. Accessibility

- **Keyboard:** all interactive elements reachable in visual order; Enter/Space activate
  buttons and toggles; Escape closes sheets, menus, and disclosure panels; focus moves into
  opened sheets and returns to the trigger on close; skip-to-content link as the first
  focusable element.
- **Focus states:** a visible 2px focus outline with offset on all interactive elements, never
  removed; on dark surfaces the outline uses the light token.
- **Semantic HTML:** one H1 per page; navigation landmarks (`nav`, `main`, `footer`);
  definition lists for key facts; real `button` for actions and `a` for navigation; form
  fields with `label`, described-by hints, and `aria-invalid` on error.
- **Screen readers:** loading regions use `aria-busy` and live-region announcements ("Memuat
  hasil", "X beasiswa ditemukan"); result lists announce the total; state badges are text,
  so they are read as-is; icon-only buttons have `aria-label`.
- **Contrast:** all text meets WCAG AA (4.5:1 normal, 3:1 large); state colors are chosen to
  pass on both card surfaces (section 22 tokens); disabled controls keep legible text.
- **Forms:** errors are announced via live region, reference the field by its visible label,
  and never rely on color alone.
- **Reduced motion:** with `prefers-reduced-motion`, transitions and skeleton animations are
  reduced to opacity changes; no parallax or auto-advancing motion exists by design.
- **Touch targets:** minimum 44 by 44 px including padding for chips, toggles, pagination.

## 21. Loading / Empty / Error States

Every data region defines all of the following:

| Situation | Design |
|---|---|
| Initial loading (first paint of a data region) | Static skeleton lines in the exact layout of the loaded content; announced to screen readers |
| Refetch loading (search, filter change) | Previous content stays; a thin progress line indicates refresh; submit buttons disable |
| Submitting match | Button disabled with label "Menghitung kecocokan..."; form stays interactive-read; no fake progress stages |
| Empty knowledge base | Explanation + link to method page; no fake examples |
| Empty filter results | Distinct from empty database; offers clear-filters action |
| Empty match results | "Belum ada kecocokan" + profile adjustment guidance |
| Empty shortlist / compare | Explanatory state with the action that populates it |
| 404 scholarship not found | Full-page state: "Beasiswa tidak ditemukan", likely-reason line (removed or wrong link), links to Discover |
| Expired scholarship (detail, direct visit) | Archive banner + demoted CTA (section 12); content remains readable |
| Unknown deadline | Amber badge + literal text; never blank, never invented |
| API validation error (422) | Field-level messages parsed from the API `detail` list; form-level alert for unmapped items |
| Server error (500) / network failure | Error card with the affected region scoped (list, column, or page), retry button, and a "coba lagi" that re-issues the exact request; the navigation shell survives |
| Rate/size edge (empty `results` with `total > 0`) | Defensive: treated as an error state |

## 22. Visual Design Direction

**Visual personality:** a research institute's reading room, not a startup landing page.
Calm, typographic, document-like. The design should feel like the scholarship records were
filed by a careful librarian who cites every source.

**Design Read (dials):** reading this as: a scholarship intelligence platform for Indonesian
students, in an editorial research-document visual language, dial **ENERGY 1 / RHYTHM 2 /
MOTION 1**.

- ENERGY 1: calm, high-trust, no marketing theatrics. Fits students making serious decisions.
- RHYTHM 2: consistent editorial baseline with deliberate breaks (the full-bleed trust block
  on Home, the definition-list key facts on Detail) so pages do not feel machine-uniform.
- MOTION 1: motion only for state feedback (progress, sheet transitions, disclosure) and
  orientation; no scroll choreography on data.

**Identity motif:** the provenance citation line. Rendered in a smaller size with a subtle
rule above, repeating across cards, detail, match, and compare. When the logo is swapped, this
citation voice plus the warm-paper palette still reads unmistakably as Polaris.

**Typography:**

- UI and body: **Public Sans** (reason: engineered for government-grade legibility of dense
  data on screens, open license, full Indonesian/Latin support; avoids the default-AI font
  look without becoming decorative).
- Numerals: `font-variant-numeric: tabular-nums` for deadlines, scores, and counts so columns
  align.
- Scale: 12/14/16/18/22/28/36/48 with H1 at `clamp(2.25rem, 4.5vw, 3.75rem)` and hero copy
  constrained to wide containers (`max-w-5xl`) so headings never wrap beyond two lines.
- No monospace for aesthetics; monospace only inside the citation motif is unnecessary, so it
  is not used there either (the motif is typographic through size, rule, and repetition).

**Color system (2 core + 1 accent + semantics):**

| Token | Value | Purpose and reason |
|---|---|---|
| `paper` | #FAF7F2 | Page background; warm off-white reads as document/archive rather than SaaS dashboard |
| `ink` | #14212B | Text and primary surfaces on light; near-black navy keeps the research tone |
| `brand` | #0E6B63 (deep teal) | Interactive color (links, primary buttons, focus); distinct from default-AI blue/purple; passes AA on paper |
| `sem-active` | #1F7A3D | Deadline active |
| `sem-rolling` | #0E6B63 | Rolling (shares brand to signal "current") |
| `sem-unknown` | #9A6700 | Unknown deadline |
| `sem-expired` | #5C6670 | Expired/archive |
| `sem-legacy` | #8A9199 (outline) | Unclassified |

Semantic colors are functional communication, not decoration; each is used with text and icon
so color is never the only carrier. All text/background pairs verified against AA in both
themes.

**Spacing:** a 4px base scale (4/8/12/16/24/32/48/64/96); sections breathe with 64 to 96px
vertical padding on marketing pages (Home, About) and 24 to 48px on data pages so density
serves scanning, not uniformity.

**Radius:** 6px controls, 10px cards, full-round only for the search input; nothing else is
pill-shaped (radius variation is hierarchy, not style cycling).

**Elevation:** one shadow token (subtle, for elevated overlays only: sheets, dropdowns, sticky
headers). Cards are defined by 1px borders, not shadows; borders signal records, shadows signal
layers.

**Borders:** 1px `line` token (#E4DED4 warm gray) throughout; the citation motif uses a
top rule of the same token.

**Iconography:** one line-icon set at 1.5px stroke used sparingly and only where meaning is
real: external-link, clock, circular-arrows (rolling), question-circle (unknown), check/minus
(benefits), bookmark (save), layers (compare). No sparkle, star, magic, or robot icons
anywhere.

**Imagery:** no stock photography of students, no campus hero images (they would be
fabricated atmosphere for a data product). The Home hero is typographic on paper with an
optional abstract fine-line compass/grid motif only if it passes the purpose test during
implementation; default is none. The placeholder wordmark is text until a real logo is
provided (asset rule, R-23).

**Data visualization rules:** v1 has no charts. When the criteria breakdown arrives (P1), it
renders as a labeled horizontal bar list with values and weights printed, ordered by weight;
no gauges, no radial progress.

## 23. Design Tokens

Conceptual tokens (specification, not code):

```
color.paper            #FAF7F2      color.ink             #14212B
color.ink-secondary    #44525C      color.line            #E4DED4
color.brand            #0E6B63      color.brand-ink       #0A4B46 (hover)
color.surface          #FFFFFF      color.surface-inverse #14212B
color.sem-active       #1F7A3D      color.sem-rolling     #0E6B63
color.sem-unknown      #9A6700      color.sem-expired     #5C6670
color.sem-legacy       #8A9199
color.feedback-error   #B3261E      color.feedback-success #1F7A3D

font.family            "Public Sans", system fallbacks
font.size              12 / 14 / 16 / 18 / 22 / 28 / 36 / 48
font.weight            400 / 500 / 600 / 700
font.numeric           tabular-nums (deadlines, scores, counts)

space                  4 / 8 / 12 / 16 / 24 / 32 / 48 / 64 / 96
radius.control         6px          radius.card           10px
radius.pill            999px (search input only)

shadow.overlay         0 8px 24px rgba(20,33,43,0.12)  (overlays only)
border.width           1px

breakpoint.tablet      640px        breakpoint.desktop    1024px

z.nav                  100          z.sheet               200
z.dropdown             300          z.toast               400

motion.fast            150ms ease-out   (state feedback)
motion.sheet           240ms ease-out   (sheet/menu)
motion.reduced         opacity-only fallback (prefers-reduced-motion)
```

Theme rule: light is the default theme; dark mode is a working toggle (both themes fully
tokenized, contrast verified per theme) included in Phase 1 implementation. No theme is
shipped half-working.

## 24. Component Architecture

Categories and key components (responsibility, data, states, reuse; no files created here):

**Layout:** `AppShell` (nav, footer, skip link, overflow guard), `PageContainer` (width and
padding rhythm), `TwoColumnLayout` (Discover, Match). State: nav active route from router.

**Navigation:** `NavBar` (desktop), `MobileMenuSheet`, `GlobalSearch`, `Breadcrumb`,
`FooterBar`. Data: routes, compare count (store). States: active, open/closed, focus-trapped.

**Search and Filters:** `SearchInput` (debounced, URL-bound), `FilterRail` / `FilterSheet`,
`FilterChip`, `PaginationControls`. Data: URL query; emits param updates. States: idle,
loading, disabled (never rendered if unsupported).

**Scholarship:** `ScholarshipCard` (browse/match variants), `DeadlineBadge` (section 12),
`SourceCitation` (motif), `KeyFactsList`, `TimelineList`, `RequirementList`, `BenefitList`,
`FieldTags`, `SaveButton` (shortlist store), `CompareToggle` (compare store).
States: loading skeleton, data, partial data (per-field "tidak disebutkan"), expired variant.

**Matching:** `ProfileForm` (all schema fields, client + server validation),
`MatchResultCard` (score, category, explanation), `ScoreBadge`, `ExplanationPanel`
(strengths/gaps/next steps). States: idle, submitting, results, empty, error.

**Compare:** `CompareTable` (desktop), `CompareStack` (mobile), `CompareColumn` with its own
fetch/retry state.

**Feedback:** `EmptyState`, `ErrorState` (region-scoped, retry), `ProgressLine`, `SkeletonBlock`,
`Toast` (shortlist/compare confirmations; auto-dismiss, polite live region).

**Trust/Provenance:** `SourceCitation`, `ProvenanceBlock` (detail), `MethodDisclosure`
(links to `/about`).

**Forms:** `TextField`, `NumberField`, `SelectField`, `RadioGroup`, `TagInput`, `Checkbox`,
with consistent label, hint, error anatomy.

Reuse map: `ScholarshipCard`, `DeadlineBadge`, `SourceCitation`, `EmptyState`, `ErrorState`
appear on Home, Discover, Match, Saved, Compare; `ProfileForm` is Match-only;
`CompareTable/Stack` are Compare-only.

## 25. API to UI Mapping

Actual API surface (verified in `api/`):

| Endpoint | Method | UI consumer | Request parameters | Response fields used | Loading state | Error state |
|---|---|---|---|---|---|---|
| `/api/v1/scholarships` | GET | Home examples, Discover list, Saved hydration | `q`, `country`, `degree`, `limit` (1..100), `offset` | `results[]`: scholarship_id, scholarship_name, provider_name, country, degree, funding_type, field_of_study[], deadline, official_url; `total` | Skeleton / progress line | Region error card + retry |
| `/api/v1/scholarships/{id}` | GET | Detail page, Compare columns, Saved detail checks | path `scholarship_id` | summary fields plus provider_type, application_url, requirement{...}, benefit{...}, timeline{application_open, application_deadline, application_cycle, interview_date, result_date, study_start} | Skeleton | 404 not-found page; per-column error in Compare; 500 region error |
| `/api/v1/matching` | POST | Match page | `RecommendationRequest` body (section 16) | `results[]`: scholarship_id, scholarship_name, deadline, provider_name, country, match_score, recommendation_category, explanation, strengths[], gaps[], next_steps[], official_url; `total` | Submitting state | 422 field errors; 500/ network error card; form values preserved |
| `/health` | GET | (Implementation diagnostics only; not a UI element) | none | status | n/a | n/a |

Notes verified against code:

- The router also exposes the identical matching handler at `POST /recommendations` (legacy
  alias). The UI uses `/api/v1/matching` only.
- 422 responses return `detail` as a list of strings shaped `field -> message` (built by the
  API's validation handler); 500 returns `{"detail": "Internal server error"}`.
- The Vite dev server proxies `/api` to `http://localhost:8000` (existing `vite.config.ts`);
  the UI calls relative `/api/...` paths, no hardcoded host.

Fields the UX needs but the API does not expose today are listed in section 29 and are never
faked.

## 26. Frontend State Architecture

Simplest architecture compatible with the existing Vue 3 + Vite + TypeScript repository:

- **Server state:** a thin typed API client module (fetch wrapper with error normalization:
  network, 404, 422 with parsed detail, 500) plus per-page composables
  (`useScholarshipList(params)`, `useScholarshipDetail(id)`, `useMatching(profile)`). No global
  cache layer is specified for v1; each consumer owns its loading/error state. If duplication
  hurts later, a cache can be introduced without redesign.
- **Local UI state:** component-local `ref`/`reactive` for form drafts, open/closed sheets,
  disclosure panels.
- **URL state:** the single source of truth for Discover (`q`, `country`, `degree`, `limit`,
  `offset`) and Compare (`ids`). Details of section 27.
- **Profile state:** a typed reactive profile store (composable with module scope) mirrored to
  localStorage after a successful match; cleared by an explicit control.
- **Shortlist (saved) state:** localStorage-backed list of scholarship ids with add/remove and
  derived count for the nav badge; hydration checks each id against the detail endpoint and
  gracefully drops 404s with a one-time notice.
- **Compare selection state:** in-memory store of ids (max 4) synced to the `/compare` URL;
  not persisted across sessions (an explicit choice: compare sessions are ephemeral; shortlist
  is the persistent list).
- No state-management library is introduced for v1 (Vue reactivity plus composables covers the
  scope; the existing scaffold has no store and adding one would be ceremony).

## 27. URL and State Persistence

| State | Belongs in | Reason |
|---|---|---|
| Discover `q`, `country`, `degree` | URL query | Shareable, survives refresh and back-navigation |
| Discover `limit`, `offset` | URL query | Same; page numbers must be linkable |
| Compare selection | URL query (`ids`) | A comparison is a shareable artifact |
| Match form draft | Component store + localStorage (post-submit) | Privacy-sensitive data should not live in the URL |
| Match results | Not in URL (computed from profile via POST); back button returns to the form preserved | No result-id exists server-side |
| Shortlist (saved ids) | localStorage | No persistence API exists (P1 future) |
| Theme preference | localStorage | User choice must survive reload |
| Disclosure/panel open state | Component state | Ephemeral UI, no share value |

Guardrails: unknown URL query keys are ignored (not silently mapped to filters); invalid
values (e.g. `degree=xy`) fall back to defaults and the control reflects that honestly; URL
updates use `replaceState` for typing-debounce and `pushState` for discrete actions so Back
feels natural.

## 28. Trust and Content Rules

Binding rules for every screen and every string of UI copy:

1. Never invent scholarship facts, deadlines, provider names, or counts. If the API does not
   return it, the UI does not show it.
2. Never fabricate deadlines: a missing deadline renders as "Tenggat tidak diketahui", always
   with the state badge, never as blank, never as a guessed date, never with a countdown.
3. Never hide source attribution: every scholarship representation carries the citation line
   and, on detail, the full provenance block with the official link.
4. Never call the deterministic engine "AI": the matching engine is described as
   "perhitungan berbasis kriteria" (criteria-based computation). No AI wording anywhere.
5. Never imply the match score is an acceptance probability: the disclaimer line is part of
   the results header and the expanded explanation.
6. Distinguish unknown from unavailable: "Tenggat tidak diketahui" (source does not say) is
   different from "Data belum tersedia" (Polaris has not collected it); both wordings are used
   precisely.
7. Distinguish expired from active: expired is archive (section 12), excluded from discovery,
   and never styled like a live opportunity.
8. Testimonials, statistics, and trust claims require real data; absent data means absent UI
   elements (no fake logos, no user counts, no invented partner bars).
9. Indonesian UI copy stays specific and calm: buttons name their real action ("Jelajahi
   beasiswa", "Lihat hasil pencocokan", "Buka halaman resmi"); no "Get Started", no
   "Learn More".

## 29. Future Backend Requirements

Concrete API work the ideal UX needs but the backend does not provide today. None of it is
implemented in this phase.

**P0 (required for the initial web release to be honest at scale):**

1. Expose `deadline_state` (active/rolling/unknown/expired/unclassified) on scholarship
   summary and detail responses, and optionally as a Discover filter parameter. Without it the
   card badge approximates from the deadline date only (the unknown vs unclassified
   distinction is impossible to render faithfully).
2. Expose `last_verified_at` (and verification status if retained) on summary/detail for the
   provenance block's freshness line.
3. Server-side filtering for `funding_type` and `field_of_study`, and a `sort` parameter
   (deadline ascending, relevance) on `GET /api/v1/scholarships`. The UI ships these controls
   only when the parameters exist.
4. Expose `application_url` (already on detail) also on the summary so cards can link
   correctly when the application page differs.

**P1 (useful shortly after launch):**

5. Criteria breakdown in `RecommendationResponse` (the engine already computes
   per-criterion scores, weights, and reasons; serializing them enables the score-breakdown
   UI designed in section 14).
6. Aggregate stats endpoint (real counts: total approved, per-country counts, freshness
   distribution) so Home and About can show true numbers instead of none.
7. Server-side shortlist/profile persistence with an anonymous or lightweight identity
   concept (this is the only P1 that implies future auth decisions; nothing in the current UI
   pretends it exists).
8. Facet counts (per-filter value counts) for the Discover rail.
9. A degree/country/field vocabulary endpoint so form and filter options come from data
   instead of frontend constants.

**P2 (later enhancement):**

10. Search suggestions/autocomplete endpoint (name prefix service).
11. Provider directory pages and per-provider scholarship lists.
12. Freshness/collection activity feed (recently verified sources) for the About page.
13. Localization framework if additional UI languages are ever needed beyond the Indonesian
    default.

## 30. Frontend Implementation Plan

Recommended sequence after this specification is approved, based on the actual repository
state (Vue 3 + Vite + TS scaffold exists; its single `App.vue` and three stub components are
broken and will be replaced, while `vite.config.ts` proxy, `tsconfig`, and index HTML shell
are kept):

- **Phase 0, Scaffold repair:** add `vue` (and `@vitejs/plugin-vue`) to `package.json`;
  remove the broken `App.vue` content and JSX-containing stub components; establish the typed
  API client, design tokens (section 23), `AppShell`, theme toggle, and routing (vue-router).
- **Phase 1, Foundation:** token implementation, layout components, navigation (desktop and
  mobile sheet), Empty/Error/Loading primitives, accessibility baseline (skip link, focus
  system).
- **Phase 2, Discover:** list page with URL-state sync, `q`/country/degree filters (supported
  ones only), pagination, chips, all list states.
- **Phase 3, Scholarship Detail:** full record, provenance block, deadline semantics,
  expired/archive handling, save and compare actions.
- **Phase 4, Search and Filter hardening:** global search, debounce/URL behavior, mobile
  filter sheet polish.
- **Phase 5, Matching:** profile form (schema-exact), submission, results, explanation panel,
  score presentation, all match states.
- **Phase 6, Compare:** selection store, table and stacked layouts, per-column error states.
- **Phase 7, Responsive, accessibility, and polish:** breakpoint audit, reduced motion, theme
  both-modes verification, keyboard pass, content review against section 28.

Each phase ends with the app built and clicked through (every control exercised) before the
next begins.

## 31. Acceptance Criteria

Measurable criteria for the future implementation:

1. Every scholarship representation (card, detail, match result, compare column) shows its
   official source link; zero exceptions.
2. Expired opportunities are visually distinguishable from current ones and never appear in
   the Discover list; direct visits to an expired detail show the archive banner and demoted
   CTA.
3. A missing deadline renders the unknown badge and text; no screen ever shows an invented or
   blank deadline.
4. Discover search/filter/pagination state fully survives navigation, refresh, and sharing
   (URL is the source of truth).
5. Match results display exactly the backend-returned score, category, explanation,
   strengths, gaps, and next steps; the frontend contains no scoring, filtering, or ranking
   logic of its own.
6. The score disclaimer ("bukan prediksi peluang diterima") appears on match results and in
   the expanded explanation.
7. 422 responses map to field-level errors; 404, 500, and network failures each have distinct,
   region-scoped UI states with retry.
8. Loading, empty (database, filtered, match, compare, saved), and error states exist for
   every data region (verified by forcing each condition).
9. Keyboard-only operation completes the primary journey: discover, open detail, fill profile,
   match, compare two items; focus is visible throughout.
10. No horizontal overflow at 320px width; all tap targets are at least 44px; mobile filter
    and menu sheets trap and restore focus.
11. Both light and dark themes pass AA contrast with no broken component.
12. The UI contains no fabricated statistics, testimonials, badges, or AI wording; a content
    review against section 28 passes with zero findings.
13. Reduced-motion preference removes nonessential motion.
14. `npm run build` succeeds with no TypeScript errors, and the app runs against the real API
    with the documented behaviors.

## 32. Design Decisions and Rationale

| Decision | Rationale |
|---|---|
| Keep Vue 3 + Vite + TS; replace the broken scaffold content only | The infrastructure (proxy, tooling) works; the scaffold's runtime defects (missing dependency, wrong endpoint, JSX in .vue) are concrete, not stylistic |
| Editorial research-document visual language, ENERGY 1 / RHYTHM 2 / MOTION 1 | The product's value is verified data; calm typography signals trust better than marketing motion, and motion is reserved for state feedback |
| Warm paper background instead of white/SaaS gray | Distinguishes Polaris from generic dashboards and reinforces the archive/document character of verified records |
| Provenance citation line as the identity motif | It is the one element no competitor copy can fake: it is bound to real `official_url` data and appears everywhere |
| Deep teal instead of default blue/purple | Avoids the generic-AI palette; teal passes AA on both themes and reads institutional rather than playful |
| Two modes (Discover and Match) sharing one card component | The brief requires them to feel like one product; shared components enforce it structurally |
| No client-side filtering or sorting of server data | Rendering an incomplete result set as complete would be a trust violation; unsupported filters are future-gated explicitly |
| URL as state for search/filter/pagination/compare | Shareable and honest; a scholarship comparison or search result should survive a refresh and be sendable |
| LocalStorage for shortlist and profile, stated in UI | The backend has no persistence; honesty about local-only storage is better than a fake account system; real persistence is P1 |
| Score shown as criteria-based, with disclaimer | The backend is deterministic weighted scoring; presenting it as probability or AI would be false; the disclaimer prevents the strongest misreading |
| No homepage statistics | No aggregate-count endpoint exists; showing invented numbers is forbidden; a real stats endpoint is P1 |
| Public Sans + tabular numerals | Legibility of dense dates/scores, government-grade neutrality, Indonesian Latin coverage, and a non-default-AI identity |
| Indonesian UI copy over English copy | The primary persona is an Indonesian student; scholarship data itself remains in its source language |
| Both themes built in Phase 1 | A theme shipped half-working is a defect; tokens make the cost low and the rule non-negotiable |
| Compare capped at 4 items | Beyond four, comparison degrades into scanning noise on every breakpoint; four columns remain legible on desktop |

---

*End of design specification. Implementation has not been started; the next step is approval
of this document, then Phase 0 per section 30.*
