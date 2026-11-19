"""Scholarship discovery services - country-centric discovery architecture."""

from .scholarship_discovery import (
    discover_scholarships_for_country,
    discover_scholarships_for_country_async,
)
from .source_registration import register_source

__all__ = [
    "register_source",
    "discover_scholarships_for_country",
    "discover_scholarships_for_country_async",
]
