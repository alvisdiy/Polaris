"""Scholarship discovery services - country-centric discovery architecture."""

from .source_registration import register_source
from .scholarship_discovery import discover_scholarships_for_country

__all__ = ["register_source", "discover_scholarships_for_country"]
