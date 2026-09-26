# Provider Discovery Specification

## Polaris — Scholarship Intelligence Platform

**Version:** 1.0  
**Owner:** AlVis  
**Status:** Production  
**Last Updated:** September 2026

---

# Purpose

Provider Discovery is the systematic process of identifying, verifying, and registering official scholarship providers for a given country. This specification defines the production-grade architecture for discovering candidate providers from authoritative sources and managing their lifecycle from discovery to active acquisition.

---

# Core Principles

1. **Country is the primary dimension** - Discovery begins with a country, not a known provider
2. **Official sources only** - Only government, academic, and recognized organizational domains are authoritative
3. **Evidence-based verification** - Every provider has traceable provenance explaining why Polaris believes it exists
4. **Human review boundary** - Automatic verification has limits; uncertain candidates require human review
5. **Idempotent operations** - Repeated discovery runs must not create duplicates or lose provenance
6. **Extensible strategies** - Different countries may require different discovery approaches without architectural changes

---

# Provider Lifecycle

```
DISCOVERED → CANDIDATE → VERIFIED → REGISTERED → ACTIVE
                ↓            ↓           ↓
            REJECTED      REJECTED    DEPRECATED
```

| State | Description | Entry Criteria |
|-------|-------------|----------------|
| **DISCOVERED** | Found via automated discovery | URL found on authoritative discovery surface |
| **CANDIDATE** | Passed initial heuristic checks | Domain matches official TLD pattern, contains scholarship keywords |
| **VERIFIED** | Deterministic checks passed | URL reachable, domain verified, type inferred correctly |
| **REGISTERED** | Added to active SourceRegistry | Human-approved or high-confidence auto-approved |
| **ACTIVE** | Participating in acquisition pipeline | Source registered with status='Active' |
| **REJECTED** | Failed verification or human review | Does not meet official source criteria |
| **DEPRECATED** | Previously active but no longer valid | URL dead, organization dissolved, or superseded |

---

# Data Model

## Provider Extensions

The existing `Provider` model is extended with verification lifecycle fields:

```python
class Provider(Base, TimestampMixin):
    # Existing fields
    provider_id: UUID
    provider_code: str  # Unique, derived from normalized domain
    provider_name: str
    provider_type: ProviderType
    country_id: UUID
    official_url: str
    
    # New verification lifecycle fields
    verification_status: str  # pending, candidate, verified, rejected, deprecated
    discovery_source: str     # URL where this provider was discovered
    discovery_method: str     # 'government_portal', 'education_directory', etc.
    discovery_evidence: JSON  # Structured evidence for verification
    discovered_at: datetime
    verified_at: datetime | None
    verified_by: str | None   # 'auto' or user identifier
    rejection_reason: str | None
```

## ProviderDiscoveryAttempt (New Table)

Tracks every discovery attempt for observability and debugging:

```python
class ProviderDiscoveryAttempt(Base, TimestampMixin):
    attempt_id: UUID
    country_id: UUID
    discovery_surface_url: str      # The page we crawled
    discovered_url: str             # The candidate provider URL found
    discovery_method: str
    domain_pattern_matched: str     # Which TLD pattern matched
    keywords_matched: list[str]
    http_status: int | None
    verification_checks: JSON       # Results of each verification check
    outcome: str                    # 'created', 'duplicate', 'rejected', 'error'
    provider_id: UUID | None        # FK if created
```

---

# Discovery Surfaces

A **discovery surface** is an authoritative web page that lists official scholarship providers for a country.

## Surface Types

| Type | Description | Example |
|------|-------------|---------|
| `government_portal` | Ministry of Education portal | `https://www.mext.go.jp/` |
| `education_directory` | National education directory | `https://www.studyinjapan.go.jp/` |
| `scholarship_agency` | National scholarship agency portal | `https://www.daad.de/` |
| `university_directory` | Official university listing | `https://www.univ-japan.jp/` |

## Surface Registry

Discovery surfaces are stored in `SourceRegistry` with a special marker:

```python
source_type: str  # 'provider_discovery_surface' vs 'scholarship_source'
```

This allows the same infrastructure (connectors, crawling) to be reused for provider discovery.

---

# Discovery Strategies

Different countries have different web structures. The system supports multiple strategies:

## Strategy 1: Link Discovery from Portal

Most common strategy. Crawl a government portal, extract links matching official domain patterns.

**Configuration:**
```yaml
strategy: link_discovery
discovery_surface: https://www.studyinjapan.go.jp/en/
allowed_tlds: [.go.jp, .ac.jp, .or.jp]
keyword_filter: [scholarship, grant, student, education]
```

**Process:**
1. Fetch discovery surface using existing Playwright connector
2. Extract all `<a href>` links
3. Filter by domain TLD (`.go.jp`, `.ac.jp`, `.or.jp` for Japan)
4. Filter by keywords in URL or anchor text
5. Create DISCOVERED providers

## Strategy 2: Sitemap Discovery

Parse XML sitemaps for scholarship-related URLs.

**Configuration:**
```yaml
strategy: sitemap_discovery
sitemap_url: https://www.example.gov/sitemap.xml
url_patterns: [/scholarship, /grant, /funding]
```

## Strategy 3: Structured Directory

Parse a known directory structure (e.g., university listings).

**Configuration:**
```yaml
strategy: structured_directory
directory_url: https://www.univ-japan.jp/en/universities/
item_selector: .university-item
name_selector: .name
url_selector: a[href]
```

## Strategy 4: Hybrid

Combine multiple strategies for comprehensive coverage.

---

# Verification Checks

Each candidate provider undergoes deterministic verification:

## Check 1: Domain TLD Validation

Verify the domain matches an official TLD pattern for the country.

| Country | Official TLDs |
|---------|---------------|
| Japan | `.go.jp`, `.ac.jp`, `.or.jp` |
| Germany | `.de` (government), `.edu` variants |
| USA | `.gov`, `.edu` |
| UK | `.gov.uk`, `.ac.uk`, `.org.uk` |
| France | `.gouv.fr`, `.fr` |
| Indonesia | `.go.id`, `.ac.id`, `.or.id` |
| Australia | `.gov.au`, `.edu.au` |
| China | `.gov.cn`, `.edu.cn` |
| Korea | `.go.kr`, `.ac.kr`, `.or.kr` |

**Implementation:** Maintain a configurable mapping of country → allowed TLD patterns.

## Check 2: HTTP Reachability

Attempt to fetch the URL. Record HTTP status.

- 200-299: Pass
- 300-399: Pass if final URL is valid
- 400-499: Warning (may require authentication)
- 500-599: Fail
- Timeout/Connection error: Fail

## Check 3: Content Verification

Lightweight content check:
- Does page contain keywords suggesting scholarship activity?
- Does page have a title that looks like an organization name?
- Are there navigation elements suggesting official website?

This is NOT full extraction - just enough to verify it's a real organization.

## Check 4: Type Inference

Infer `ProviderType` from domain and content:

- `.go.*`, `.gov.*` → GOVERNMENT
- `.ac.*`, `.edu.*`, `.university` → UNIVERSITY
- `foundation` in domain → FOUNDATION
- `.org`, `.or.*` → NGO (requires manual review)
- Corporate domain patterns → COMPANY

## Check 5: Deduplication

Check if provider already exists by:
1. Exact URL match
2. Normalized domain match (ignore www., http vs https)
3. Similarity match on provider_name (fuzzy matching)

---

# Provenance Model

Every provider has complete provenance:

```json
{
  "provider_id": "uuid",
  "provider_name": "Japan Student Services Organization",
  "official_url": "https://www.jasso.go.jp/",
  "verification_status": "verified",
  "discovery_source": "https://www.studyinjapan.go.jp/en/",
  "discovery_method": "government_portal",
  "discovered_at": "2026-09-19T09:00:00Z",
  "discovery_evidence": {
    "anchor_text": "JASSO - Japan Student Services Organization",
    "surrounding_context": "Official scholarship information...",
    "keywords_matched": ["scholarship", "student", "services"],
    "tld_matched": ".go.jp",
    "crawl_depth": 1
  },
  "verification_checks": {
    "domain_tld": {"status": "pass", "matched": ".go.jp"},
    "http_reachability": {"status": "pass", "http_status": 200, "final_url": "https://www.jasso.go.jp/en/"},
    "content_verification": {"status": "pass", "keywords_found": ["scholarship", "student"]},
    "type_inference": {"status": "pass", "inferred_type": "Government", "confidence": 0.95},
    "deduplication": {"status": "pass", "duplicates_found": 0}
  },
  "verified_at": "2026-09-19T09:05:00Z",
  "verified_by": "auto"
}
```

---

# Human Review Boundary

Not all providers can be auto-verified. Rules for requiring human review:

1. **Novel domain pattern** - TLD not in known official patterns
2. **Ambiguous type** - Cannot confidently infer provider type
3. **Low confidence** - Multiple verification checks failed or warned
4. **Similar to existing** - Fuzzy match to existing provider name
5. **First discovery for country** - Conservative approach for new countries

Human reviewers see:
- All discovery evidence
- Verification check results
- Similar existing providers (if any)
- Option to: Approve, Reject, or Merge with existing

---

# Metrics and Observability

Provider Discovery produces metrics similar to scholarship acquisition:

```python
@dataclass
class ProviderDiscoveryMetrics:
    country_iso2: str
    started_at: datetime
    finished_at: datetime | None
    discovery_surfaces_processed: int
    candidate_urls_found: int
    candidates_after_tld_filter: int
    candidates_after_keyword_filter: int
    verification_passed: int
    verification_failed: int
    verification_pending_review: int
    duplicates_skipped: int
    providers_created: int
    providers_updated: int
    sources_registered: int
    errors: list[str]
```

---

# Integration with Acquisition Pipeline

Once a provider is **VERIFIED** and **REGISTERED**:

1. Create `SourceRegistry` entry with status='Active'
2. Assign appropriate connector (usually `generic_playwright`)
3. Provider's sources appear in `CountryDiscoveryOrchestrator` queries
4. Existing scholarship discovery pipeline takes over

No changes to scholarship acquisition code needed.

---

# Configuration Registry

Discovery configuration is stored in the database, not hardcoded:

```python
class ProviderDiscoveryConfig(Base, TimestampMixin):
    country_id: UUID
    discovery_surface_url: str
    discovery_strategy: str
    allowed_tlds: list[str]
    keyword_filters: list[str]
    exclude_patterns: list[str]
    auto_verify_enabled: bool
    confidence_threshold: float
    priority: int
    is_active: bool
```

This allows adding new countries via database operations without code changes.

---

# Operational Workflow

## Initial Discovery (New Country)

```bash
# 1. Add country to database
python -c "from database.session import SessionLocal; from database.models.country import Country; s=SessionLocal(); s.add(Country(iso2='JP', iso3='JPN', name='Japan')); s.commit()"

# 2. Seed discovery configuration
python scripts/seed_provider_discovery_config.py JP

# 3. Run provider discovery
python scripts/run_provider_discovery.py JP

# 4. Review pending candidates (if any)
python scripts/review_provider_candidates.py JP

# 5. Verify and register approved providers
python scripts/register_verified_providers.py JP

# 6. Scholarship acquisition picks up new sources automatically
python scripts/run_global_acquisition.py
```

## Incremental Discovery (Existing Country)

```bash
# Re-run discovery to find new providers
python scripts/run_provider_discovery.py JP

# System automatically skips duplicates
# New candidates go to pending review
```

---

# Success Criteria

Provider Discovery is successful when:

1. Adding a new country requires only configuration, not code changes
2. Discovery runs are idempotent (no duplicates)
3. Every provider has complete, inspectable provenance
4. Human review boundary is respected
5. Verified providers feed directly into scholarship acquisition
6. Metrics provide visibility into coverage gaps
7. Multiple discovery strategies work without architectural changes
8. Evidence is deterministic and auditable

---

# Non-Goals

Provider Discovery does NOT:

- Discover individual scholarships (that's scholarship discovery)
- Use ML or predictive models
- Scrape non-official sources (blogs, aggregators, social media)
- Auto-verify low-confidence candidates
- Replace human judgment for ambiguous cases
