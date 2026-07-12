# How to Implement a Connector

**Scope:** Step-by-step procedure for creating a new connector for a scholarship source.
**Spec reference:** `docs/v0.1/connector-specification.md`

---

## Prerequisites

- [ ] The source is registered in Source Registry (or will be)
- [ ] You know the source URL and its content type (HTML, PDF, API)
- [ ] You have read `docs/v0.1/connector-specification.md`

---

## Procedure

### Step 1 — Determine Connector Type

| Source Characteristic | Connector Type |
|---|---|
| JavaScript-rendered content | Playwright Connector |
| Static HTML | Crawl4AI Connector |
| REST/GraphQL API available | API Connector |
| PDF documents | PDF Connector |
| Complex structure needing custom logic | Custom Connector |

### Step 2 — Create Connector File

Location based on source type:

```
connectors/
├── base_connector.py        # Abstract interface (must exist first)
├── government/
│   └── {provider}_connector.py
├── university/
│   └── {university}_connector.py
└── utils/
```

### Step 3 — Implement the Interface

Every connector implements these methods from `base_connector.py`:

```python
from abc import ABC, abstractmethod


class BaseConnector(ABC):
    """Base interface for all Polaris connectors."""

    @abstractmethod
    async def connect(self) -> None:
        """Initialize connection (browser, HTTP client, etc.)."""

    @abstractmethod
    async def fetch(self, url: str) -> str:
        """Fetch content from the source URL.

        Returns raw HTML, Markdown, or text content.
        Raises ConnectorError on failure.
        """

    @abstractmethod
    async def extract(self, raw_content: str) -> str:
        """Extract main content from raw fetched data.

        Removes navigation, footers, ads, cookie banners.
        """

    @abstractmethod
    async def close(self) -> None:
        """Clean up resources (close browser, HTTP session, etc.)."""
```

### Step 4 — Implement the Connector

Example — Playwright connector for a government source:

```python
from loguru import logger

from connectors.base_connector import BaseConnector


class MextConnector(BaseConnector):
    def __init__(self, source_record: dict):
        self.source_id = source_record["source_id"]
        self.entry_url = source_record["crawl_entry_url"]
        self.browser = None

    async def connect(self):
        from playwright.async_api import async_playwright
        self._pw = await async_playwright().start()
        self.browser = await self._pw.chromium.launch()
        logger.info("Connected: {}", self.source_id)

    async def fetch(self, url: str) -> str:
        page = await self.browser.new_page()
        try:
            await page.goto(url, wait_until="networkidle")
            return await page.content()
        except Exception as e:
            raise ConnectorError(self.source_id, str(e))
        finally:
            await page.close()

    async def extract(self, raw_content: str) -> str:
        import trafilatura
        return trafilatura.extract(raw_content) or ""

    async def close(self):
        if self.browser:
            await self.browser.close()
        await self._pw.stop()
        logger.info("Closed: {}", self.source_id)
```

### Step 5 — Add Error Handling

Handle these errors per the connector spec:

| Error | Action |
|---|---|
| Timeout | Retry with exponential backoff (max 3) |
| 403 Forbidden | Log error, skip source, do NOT retry |
| 404 Not Found | Log error, flag source for review |
| 429 Too Many Requests | Retry after backoff |
| SSL Error | Log error, flag source |
| JS Rendering Failure | Retry once, then log and skip |

### Step 6 — Add Logging

Every connector logs:

```python
logger.info("Crawling source={} url={}", self.source_id, url)
logger.info("Crawl complete source={} status={} duration={}ms", ...)
logger.warning("Retry {}/{} source={}", attempt, max_retries, self.source_id)
logger.error("Connector failed source={} error={}", self.source_id, error)
```

### Step 7 — Register the Connector

Ensure the connector is resolvable by the Knowledge Pipeline via the Source Registry's `connector_name` field.

---

## Rules

- One connector per source provider.
- Connector failures MUST NOT stop the pipeline.
- Maximum 3 retries with exponential backoff.
- All connectors follow the same interface.
- Connectors do NOT do AI extraction, validation, or database operations.
- Every connector logs source_id, crawl time, status, and errors.

---

## Anti-Patterns

- One connector handling multiple unrelated sources
- Connector doing AI extraction or schema validation
- Connector writing to database directly
- Swallowing errors without logging
- No retry logic for transient failures
- Hardcoded URLs inside connectors (use source_record)

---

## References

- Connector spec: `docs/v0.1/connector-specification.md`
- Source Registry: `docs/v0.1/source-registry-specification.md`
- Knowledge Pipeline: `docs/v0.1/knowledge-pipeline.md`
- Tech stack (Playwright, Crawl4AI, Trafilatura): `docs/v0.1/tech-stack.md`
