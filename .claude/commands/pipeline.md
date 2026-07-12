# How to Implement the Knowledge Pipeline

**Scope:** Step-by-step procedure for working on any component of the Knowledge Pipeline.
**Spec reference:** `docs/v0.1/knowledge-pipeline.md`

---

## Prerequisites

- [ ] You have read `docs/v0.1/knowledge-pipeline.md`
- [ ] You have read `docs/v0.1/connector-specification.md`
- [ ] You have read `docs/v0.1/source-registry-specification.md`
- [ ] You have read `docs/v0.1/data-dictionary.md`

---

## Pipeline Overview

```
Official Website
    → Crawler (Connector)
    → Cleaner
    → AI Extractor
    → Validator
    → Review Queue
    → Knowledge Base
```

Each stage is a separate module. Never combine responsibilities.

---

## Module Responsibilities

| Module | Input | Output | Can it fail without stopping pipeline? |
|--------|-------|--------|----------------------------------------|
| Crawler | Source Registry record | Raw HTML / Markdown | Yes — log and continue |
| Cleaner | Raw HTML | Cleaned text | Yes — log and continue |
| Extractor | Cleaned text | JSON per Data Dictionary | Yes — log, do NOT write bad data |
| Validator | Extracted JSON | Valid schema or error | Validation fail = no storage |
| Review Queue | Validated JSON | `pending_review` record | No — this is the publish gate |
| Knowledge Base | Approved record | Stored scholarship | No — data integrity required |

---

## Procedure

### Step 1 — Crawler

The crawler does NOT fetch URLs directly. It resolves a connector from the Source Registry:

```python
source = get_source_from_registry(source_id)

if source["status"] != "Active":
    logger.warning("Source not active: {}", source_id)
    return

connector = resolve_connector(source)  # returns BaseConnector subclass
await connector.connect()

try:
    raw = await connector.fetch(source["crawl_entry_url"])
finally:
    await connector.close()
```

Rules:
- Only crawl sources with status `Active`
- Respect `robots.txt` if `robots_allowed = True` in source record
- Apply rate limiting between requests
- Use retry with exponential backoff (max 3)

### Step 2 — Cleaner

Removes HTML noise, keeps main scholarship content:

```python
import trafilatura

def clean_html(raw_html: str) -> str:
    cleaned = trafilatura.extract(raw_html, include_tables=True)
    if not cleaned:
        raise CleanerError("Content extraction failed")
    return cleaned
```

Rules:
- Use Trafilatura as primary extraction tool
- Output should be readable plain text or Markdown
- If cleaning produces empty output, log and skip

### Step 3 — AI Extractor

Uses LLM to extract structured data. The LLM follows a strict schema — it does NOT invent data:

```python
from openai import OpenAI
import json

client = OpenAI()

def extract_scholarship(content: str, source_url: str) -> dict:
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
            {"role": "user", "content": f"Source: {source_url}\n\n{content}"}
        ],
        response_format={"type": "json_object"},
    )
    return json.loads(response.choices[0].message.content)
```

Rules:
- LLM only extracts what is present in the content
- LLM does NOT generate or infer data not in the source
- Prompt enforces the Data Dictionary schema
- Output is validated by the next stage before storage

### Step 4 — Validator

Validates extracted JSON against Pydantic schema:

```python
from pydantic import ValidationError
from .schemas import ScholarshipExtracted

def validate_extraction(data: dict) -> ScholarshipExtracted:
    try:
        return ScholarshipExtracted(**data)
    except ValidationError as e:
        raise ExtractorValidationError(str(e))
```

Rules:
- Use Pydantic schemas derived from `docs/v0.1/data-dictionary.md`
- Missing required fields → reject
- Invalid types or values → reject
- Failed validation = data does NOT proceed to review queue

### Step 5 — Review Queue

Stores validated data with `pending_review` status:

```python
record = ScholarshipDraft(
    **validated_data.model_dump(),
    verification_status="pending_review",
    extracted_from=source_url,
    extracted_at=datetime.now(tz=utc),
)
session.add(record)
session.commit()
```

Rules:
- All extracted data starts with `verification_status = "pending_review"`
- Never auto-publish without human review
- Human reviewers approve → status changes to `published`

---

## Adding a New Pipeline Stage

1. Create a module in `knowledge-pipeline/{stage_name}/`
2. Implement a clear input → output function
3. Handle errors without stopping the pipeline
4. Log all operations with source_id and timestamps
5. Write tests covering both success and failure paths

---

## Rules

- Each stage has exactly one responsibility
- No stage writes directly to the public Knowledge Base without the review gate
- Failure in any stage (except Review Queue and Knowledge Base) must be logged and skipped, not crash
- LLM is only used in the Extractor stage
- Source Registry is the only source of crawl targets

---

## Anti-Patterns

- Skipping the Validator stage
- LLM writing directly to Knowledge Base without validation
- Auto-publishing extraction results
- One function doing crawl + clean + extract
- Connector doing extraction or validation
- Crawling URLs not in Source Registry

---

## References

- Pipeline spec: `docs/v0.1/knowledge-pipeline.md`
- Connector guide: `.claude/commands/connector.md`
- Connector spec: `docs/v0.1/connector-specification.md`
- Source Registry: `docs/v0.1/source-registry-specification.md`
- Data Dictionary: `docs/v0.1/data-dictionary.md`
- Example extraction: `examples/scholarship-extraction.json`
