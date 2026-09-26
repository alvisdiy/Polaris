"""Provider Discovery Orchestrator.

Orchestrates the discovery of new scholarship providers based on the Provider Discovery Spec.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any
from urllib.parse import urljoin, urlparse

from loguru import logger
from sqlalchemy import or_, select

from database.models.country import Country
from database.models.enums import ProviderType
from database.models.provider import Provider
from database.models.provider_discovery_attempt import ProviderDiscoveryAttempt
from database.models.provider_discovery_config import ProviderDiscoveryConfig
from database.models.source_registry import SourceRegistry
from services.ingestion.connectors.base_connector import ConnectorConfig
from services.ingestion.connectors.generic_playwright import GenericPlaywrightConnector

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


@dataclass
class ProviderDiscoveryMetrics:
    """Metrics for a provider discovery run."""

    country_iso2: str
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: datetime | None = None
    discovery_surfaces_processed: int = 0
    candidate_urls_found: int = 0
    candidates_after_tld_filter: int = 0
    candidates_after_keyword_filter: int = 0
    verification_passed: int = 0
    verification_failed: int = 0
    verification_pending_review: int = 0
    duplicates_skipped: int = 0
    providers_created: int = 0
    providers_updated: int = 0
    sources_registered: int = 0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "country_iso2": self.country_iso2,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "discovery_surfaces_processed": self.discovery_surfaces_processed,
            "candidate_urls_found": self.candidate_urls_found,
            "candidates_after_tld_filter": self.candidates_after_tld_filter,
            "candidates_after_keyword_filter": self.candidates_after_keyword_filter,
            "verification_passed": self.verification_passed,
            "verification_failed": self.verification_failed,
            "verification_pending_review": self.verification_pending_review,
            "duplicates_skipped": self.duplicates_skipped,
            "providers_created": self.providers_created,
            "providers_updated": self.providers_updated,
            "sources_registered": self.sources_registered,
            "errors": self.errors,
        }


class ProviderDiscoveryOrchestrator:
    """Orchestrates provider discovery based on configured strategies."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.metrics: ProviderDiscoveryMetrics | None = None

    def _infer_provider_type(self, host: str, tld: str) -> tuple[ProviderType, float]:
        """Infer provider type from hostname and TLD.
        Returns a tuple of (ProviderType, confidence_score).
        """
        host = host.lower()
        if any(gov in host for gov in [".gov", ".go.", "ministry", "embassy"]):
            return ProviderType.GOVERNMENT, 0.9
        if any(edu in host for edu in [".edu", ".ac.", "university", "college", "school"]):
            return ProviderType.UNIVERSITY, 0.9
        if "foundation" in host:
            return ProviderType.FOUNDATION, 0.8
        if any(org in host for org in [".org", ".or."]):
            return ProviderType.NGO, 0.6
        # Treat generic .com domains as generic NGOs unless they explicitly look like a company.
        if any(com in host for com in [".com", ".co."]) and ("company" in host or "corp" in host):
            return ProviderType.COMPANY, 0.6

        # Fallback: unknown or generic domains are considered NGOs with low confidence.
        return ProviderType.NGO, 0.3  # Fallback with low confidence

    async def discover_providers_for_country(self, iso2: str) -> ProviderDiscoveryMetrics:
        """Run provider discovery for a specific country."""
        logger.info("Starting provider discovery for {}", iso2)
        self.metrics = ProviderDiscoveryMetrics(country_iso2=iso2)

        try:
            # 1. Get Country
            country = self.session.query(Country).filter_by(iso2=iso2).first()
            if not country:
                logger.error("Country {} not found", iso2)
                self.metrics.errors.append(f"Country {iso2} not found")
                return self._finalize()

            # 2. Get active discovery configurations
            configs = (
                self.session.query(ProviderDiscoveryConfig)
                .filter_by(country_id=country.country_id, is_active=True)
                .order_by(ProviderDiscoveryConfig.priority)
                .all()
            )

            if not configs:
                logger.info("No active provider discovery configs found for {}", iso2)
                return self._finalize()

            logger.info("Found {} active discovery configs for {}", len(configs), iso2)

            # 3. Process each configuration
            for config in configs:
                try:
                    await self._process_config(country, config)
                except Exception as e:
                    logger.exception("Error processing config {}: {}", config.config_id, e)
                    self.metrics.errors.append(f"Config {config.discovery_surface_url}: {e}")

            return self._finalize()

        except Exception as e:
            logger.exception("Provider discovery failed for {}: {}", iso2, e)
            self.metrics.errors.append(str(e))
            return self._finalize()

    async def _process_config(self, country: Country, config: ProviderDiscoveryConfig) -> None:
        """Process a single discovery configuration."""
        self.metrics.discovery_surfaces_processed += 1

        logger.info(
            "Processing strategy {} on {}",
            config.discovery_strategy,
            config.discovery_surface_url
        )

        if config.discovery_strategy == "link_discovery":
            await self._run_link_discovery(country, config)
        else:
            logger.warning("Strategy {} not implemented yet", config.discovery_strategy)
            self.metrics.errors.append(f"Strategy not implemented: {config.discovery_strategy}")

    async def _run_link_discovery(self, country: Country, config: ProviderDiscoveryConfig) -> None:
        """Execute link_discovery strategy using GenericPlaywrightConnector."""
        connector_cfg = ConnectorConfig(
            source_id=uuid.uuid4(),
            url=config.discovery_surface_url,
            timeout=30,
            user_agent="PolarisBot/0.1 (provider discovery)",
        )

        connector = GenericPlaywrightConnector(connector_cfg)

        try:
            await connector.connect()

            # Use discover() to get candidate URLs
            discovered_urls = await connector.discover()

            # Convert to links_data format expected by downstream code
            links_data = [{"href": url, "text": "", "title": ""} for url in discovered_urls]

        finally:
            await connector.close()

        logger.info("Extracted {} raw links from {}", len(links_data), config.discovery_surface_url)
        self.metrics.candidate_urls_found += len(links_data)

        # Deduplicate links before processing
        seen_urls = set()
        unique_links = []
        for link in links_data:
            url = link.get('href', '').strip()
            # Ignore anchors, mailto, javascript, etc.
            if not url or url.startswith(("#", "javascript:", "mailto:", "tel:")):
                continue

            try:
                # Ensure absolute URL
                full_url = urljoin(config.discovery_surface_url, url)
                parsed = urlparse(full_url)
                if not parsed.netloc:
                    continue

                # Basic normalization for deduplication
                norm_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
                if norm_url not in seen_urls:
                    seen_urls.add(norm_url)
                    link['full_url'] = full_url
                    link['parsed'] = parsed
                    unique_links.append(link)
            except Exception:
                pass

        # Filter 1: Domain TLDs (PERMISSIVE - soft filter, not hard gate)
        allowed_tlds = config.allowed_tlds or []

        for link in unique_links:
            parsed = link['parsed']
            domain = parsed.netloc.lower()

            matched_tld = None
            if not allowed_tlds:
                matched_tld = "any"
            else:
                for tld in allowed_tlds:
                    if domain.endswith(tld) or tld in domain:
                        matched_tld = tld
                        break

            # Store TLD match as relevance signal, don't filter out
            link['matched_tld'] = matched_tld

        self.metrics.candidates_after_tld_filter += len(unique_links)
        logger.info("TLD relevance scored: {}", len(unique_links))

        # Filter 2: Keywords (PERMISSIVE - soft signal, not requirement)
        keyword_filters = config.keyword_filters or []

        for link in unique_links:
            parsed = link['parsed']
            anchor_text = link.get('text', '').lower()
            title = link.get('title', '').lower()
            path_query = (parsed.path + "?" + parsed.query).lower()

            matched_keywords = []
            if not keyword_filters:
                matched_keywords = ["none_required"]
            else:
                for kw in keyword_filters:
                    kw_lower = kw.lower()
                    if kw_lower in path_query or kw_lower in anchor_text or kw_lower in title:
                        matched_keywords.append(kw)

            # Store keyword matches as relevance signal, don't filter out
            # Empty list means no keyword match but still processable
            link['matched_keywords'] = matched_keywords if matched_keywords else []

        self.metrics.candidates_after_keyword_filter += len(unique_links)
        logger.info("Keyword relevance scored: {}", len(unique_links))

        # Process ALL candidates (keywords/TLD are relevance signals, not gates)
        for link in unique_links:
            await self._evaluate_candidate(country, config, link)

    async def _evaluate_candidate(self, country: Country, config: ProviderDiscoveryConfig, link_data: dict) -> None:
        """Evaluate a single candidate URL, perform verification checks, and upsert Provider."""
        full_url = link_data['full_url']
        parsed = link_data['parsed']
        host = parsed.netloc

        # Normalize domain to create provider_code
        # E.g., www.jasso.go.jp -> JASSO_GO_JP
        norm_host = host.replace("www.", "")
        provider_code = norm_host.replace(".", "_").upper()

        # Create ProviderName from host and anchor text
        provider_name = link_data.get('text', '').strip()
        if not provider_name or len(provider_name) > 100:
            provider_name = norm_host.title()

        # Run Verification Checks
        checks = {}

        # Check 1: Domain TLD (relevance signal)
        matched_tld = link_data.get('matched_tld')
        checks['domain_tld'] = {
            'status': 'pass' if matched_tld else 'info',
            'matched': matched_tld
        }

        # Check 2: Keywords (relevance signal)
        matched_kws = link_data.get('matched_keywords', [])
        checks['content_verification'] = {
            'status': 'pass' if matched_kws else 'info',
            'keywords_found': matched_kws,
            'anchor_text': link_data.get('text', '')[:100]  # Truncate for DB
        }

        # Check 3: Type Inference
        p_type, type_confidence = self._infer_provider_type(host, matched_tld or "")
        checks['type_inference'] = {
            'status': 'pass' if type_confidence >= 0.6 else 'info',
            'inferred_type': p_type.value,
            'confidence': type_confidence
        }

        # Check 4: Deduplication Check
        existing_provider = (
            self.session.query(Provider)
            .filter(
                or_(
                    Provider.provider_code == provider_code,
                    Provider.official_url == full_url
                )
            )
            .first()
        )

        checks['deduplication'] = {
            'status': 'pass' if not existing_provider else 'duplicate',
            'provider_id': str(existing_provider.provider_id) if existing_provider else None
        }

        # Determine Outcome & Status
        outcome = "created"
        verification_status = "candidate"
        verified_by = None
        verified_at = None

        if existing_provider:
            outcome = "duplicate"
            self.metrics.duplicates_skipped += 1
            # We don't downgrade existing verified providers, but we might update them
            if existing_provider.is_verified():
                verification_status = existing_provider.verification_status
                verified_by = existing_provider.verified_by
                verified_at = existing_provider.verified_at
        else:
            # Automatic verification logic - PERMISSIVE
            # A provider becomes candidate by default; verified only when strongly confident.
            has_keyword_signal = bool(matched_kws) and matched_kws != ["none_required"]
            has_tld_signal = matched_tld is not None and matched_tld != "any"
            has_type_signal = type_confidence >= config.confidence_threshold

            if config.auto_verify_enabled:
                # Verify if we have STRONG evidence: type confidence + at least one relevance signal
                if has_type_signal and (has_keyword_signal or has_tld_signal):
                    verification_status = "verified"
                    verified_by = "auto"
                    verified_at = datetime.now(timezone.utc)
                    self.metrics.verification_passed += 1
                else:
                    verification_status = "candidate"  # Requires human review
                    self.metrics.verification_pending_review += 1
            else:
                verification_status = "candidate"
                self.metrics.verification_pending_review += 1

        # Build evidence JSON
        evidence = {
            "anchor_text": link_data.get('text', ''),
            "title_attr": link_data.get('title', ''),
            "keywords_matched": matched_kws,
            "tld_matched": matched_tld,
            "crawl_depth": 1
        }

        provider_id = existing_provider.provider_id if existing_provider else uuid.uuid4()

        # Persist Provider
        if existing_provider:
            # Update discovery info if it was manually created previously
            if not existing_provider.discovery_source:
                existing_provider.discovery_source = config.discovery_surface_url
                existing_provider.discovery_method = config.discovery_strategy
                existing_provider.discovery_evidence = evidence
                existing_provider.discovered_at = datetime.now(timezone.utc)
            self.metrics.providers_updated += 1
        else:
            new_provider = Provider(
                provider_id=provider_id,
                provider_code=provider_code,
                provider_name=provider_name,
                provider_type=p_type,
                country_id=country.country_id,
                official_url=full_url,
                verification_status=verification_status,
                discovery_source=config.discovery_surface_url,
                discovery_method=config.discovery_strategy,
                discovery_evidence=evidence,
                discovered_at=datetime.now(timezone.utc),
                verified_at=verified_at,
                verified_by=verified_by
            )
            self.session.add(new_provider)
            self.metrics.providers_created += 1

            # If auto-verified and config permits, we could also create SourceRegistry entry here
            # But according to spec, let's keep registration as a separate step or script for safety

        # Record Discovery Attempt
        attempt = ProviderDiscoveryAttempt(
            country_id=country.country_id,
            discovery_surface_url=config.discovery_surface_url,
            discovered_url=full_url,
            discovery_method=config.discovery_strategy,
            domain_pattern_matched=matched_tld,
            keywords_matched={'keywords': matched_kws},
            verification_checks=checks,
            outcome=outcome,
            provider_id=provider_id,
            attempted_at=datetime.now(timezone.utc)
        )
        self.session.add(attempt)

        # Flush to DB to avoid huge memory footprint if many links
        self.session.flush()

    def _finalize(self) -> ProviderDiscoveryMetrics:
        """Complete the run and commit changes."""
        try:
            self.session.commit()
        except Exception as e:
            logger.error("Failed to commit provider discovery: {}", e)
            self.session.rollback()
            self.metrics.errors.append(f"Commit failed: {e}")

        self.metrics.finished_at = datetime.now(timezone.utc)
        duration = (self.metrics.finished_at - self.metrics.started_at).total_seconds()

        logger.info(
            "Provider Discovery finished for {} in {:.1f}s. Created: {}, Updated: {}, Candidates pending review: {}, Auto-verified: {}",
            self.metrics.country_iso2,
            duration,
            self.metrics.providers_created,
            self.metrics.providers_updated,
            self.metrics.verification_pending_review,
            self.metrics.verification_passed
        )

        return self.metrics
