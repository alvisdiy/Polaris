"""Deterministic extraction client using heuristic parsing."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any, Dict, Optional

from services.ingestion.extractor import LLMClient


def _relative_date(days: int) -> str:
    return (date.today() + timedelta(days=days)).isoformat()


class DeterministicLLMClient(LLMClient):
    """Parse clean text to extract scholarship data using heuristics.

    This client uses pattern matching to extract dates, requirements, and benefits
    from trafilatura-cleaned text. It does not call external LLM APIs.
    Fields that cannot be determined are left as None.
    """

    def _extract_title(self, text: str) -> str | None:
        # Try to find heading or title
        patterns = [
            r"^#\s+(.+)$",  # Markdown heading
            r"([A-Z][A-Za-z\s]+(?:Scholarship|Program|Grant|Fellowship))",
            r"(Japanese Government.*?Scholarship)",
        ]
        for p in patterns:
            m = re.search(p, text, re.MULTILINE)
            if m:
                return m.group(1).strip()
        return None

    def _extract_cycle(self, text: str) -> Optional[str]:
        """Extract the scholarship cycle/cohort label (e.g. "2027", "AY2027/28").

        Only explicit cohort phrasing counts. A bare year on the page is not
        a cycle — inventing one would conflate cycle with deadline.
        """
        patterns = [
            r"(?:academic year|a\.?y\.?)\s*:?\s*(20\d{2}\s*[-/]\s*(?:\d{2}|20\d{2}))",
            r"(20\d{2})\s*(?:intake|cohort|cycle)",
            r"(?:intake|cohort|cycle)\s*(?:of|for|:)?\s*(20\d{2})",
        ]
        for p in patterns:
            m = re.search(p, text, re.IGNORECASE)
            if m:
                return re.sub(r"\s*([-/])\s*", r"\1", m.group(1).strip())
        return None

    def _extract_deadline(self, text: str) -> Optional[str]:
        """Extract and normalize deadline to ISO YYYY-MM-DD format.

        Supports formats: Month DD, YYYY | DD Month YYYY | YYYY-MM-DD | YYYY/MM/DD | DD.MM.YYYY
        """
        # Extended patterns for deadline extraction
        patterns = [
            # "deadline: May 15, 2024" | "apply by: June 1st, 2024"
            r"(?:deadline|application deadline|apply by|due date)[:\s]+([A-Za-z]+\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4})",
            # "deadline: 2024-05-15" | "apply by 2024/05/15"
            r"(?:deadline|application deadline|apply by)[:\s]+(\d{4}[-/]\d{2}[-/]\d{2})",
            # "May 15, 2024 deadline" | "June 1, 2024 application"
            r"([A-Za-z]+\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4}).*?(?:deadline|due|application)",
            # "15 May 2024" | "1st June 2024"
            r"(?:deadline|application deadline|apply by)[:\s]+(\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]+\s+\d{4})",
            # "by 15.05.2024" | "until 01.06.2024"
            r"(?:by|until|deadline)[:\s]+(\d{1,2}\.\d{2}\.\d{4})",
            # Standalone dates near context words
            r"(?:accept.*?until|period.*?to)[:\s]+([A-Za-z]+\s+\d{1,2},?\s+\d{4})",
        ]

        for p in patterns:
            m = re.search(p, text, re.IGNORECASE)
            if m:
                date_str = m.group(1).strip()
                normalized = self._normalize_date(date_str)
                if normalized:
                    return normalized
        return None

    def _normalize_date(self, date_str: str) -> Optional[str]:
        """Normalize various date formats to ISO YYYY-MM-DD."""
        try:
            from dateutil import parser
            # Remove ordinal suffixes (1st -> 1, 2nd -> 2)
            cleaned = re.sub(r'(\d+)(?:st|nd|rd|th)', r'\1', date_str)
            # DD.MM.YYYY pattern - use dayfirst=True to avoid month/day swap
            if re.match(r'\d{1,2}\.\d{2}\.\d{4}', cleaned):
                parsed = parser.parse(cleaned, dayfirst=True, fuzzy=False)
            else:
                parsed = parser.parse(cleaned, fuzzy=False)
            return parsed.strftime('%Y-%m-%d')
        except Exception:
            return None

    def _extract_gpa(self, text: str) -> float | None:
        m = re.search(r"(?:GPA|gpa)[:\s]+(\d+\.?\d*)", text)
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                pass
        return None

    def _extract_age_limit(self, text: str) -> int | None:
        m = re.search(r"(?:under|age limit|below)[:\s]*(\d{2})", text, re.IGNORECASE)
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                pass
        return None

    def _extract_toefl(self, text: str) -> tuple[bool, int | None]:
        m = re.search(r"TOEFL[:\s]+(\d{2,3})", text, re.IGNORECASE)
        if m:
            return (True, int(m.group(1)))
        return (False, None)

    def _extract_benefits(self, text: str) -> Dict[str, bool]:
        text_lower = text.lower()
        return {
            "tuition_fee": bool(re.search(r"tuition", text_lower)),
            "monthly_allowance": bool(re.search(r"monthly\s+(allowance|stipend)", text_lower)),
            "accommodation": bool(re.search(r"accommodation|housing", text_lower)),
            "health_insurance": bool(re.search(r"health\s+insurance|medical", text_lower)),
            "travel_ticket": bool(re.search(r"(?:round-?trip|airfare|flight|travel)", text_lower)),
            "research_grant": bool(re.search(r"research\s+grant", text_lower)),
        }

    # ----------------------------------------------------------------------
    # Heuristic extraction for fields required by validation but not covered
    # ----------------------------------------------------------------------
    def _extract_provider_name(self, text: str) -> str | None:
        """Attempt to find a provider name in the text.
        Looks for known provider keywords; falls back to a generic pattern.
        """
        providers = [
            "Ministry of Education",
            "JASSO",
            "DAAD",
            "Chevening",
            "LPDP",
            "Campus France",
            "State Department",
            "Australian Government",
            "CSC",
            "GKS",
        ]
        lowered = text.lower()
        for p in providers:
            if p.lower() in lowered:
                return p
        # Fallback: look for "by <provider>"
        m = re.search(r"by\s+([A-Za-z\s]+)", text, re.IGNORECASE)
        if m:
            return m.group(1).strip()
        return None

    def _extract_scholarship_type(self, text: str) -> str | None:
        """Detect scholarship type (Government, University, etc.)"""
        types = ["government", "university", "foundation", "ngo", "company"]
        lowered = text.lower()
        for t in types:
            if t in lowered:
                return t.title()
        return None

    def _extract_degree(self, text: str) -> str | None:
        """Detect degree level from text."""
        degrees = ["Bachelor", "Master", "PhD", "Doctorate", "Exchange", "Short Course"]
        lowered = text.lower()
        for d in degrees:
            if d.lower() in lowered:
                return d
        return None

    def _extract_funding_type(self, text: str) -> str | None:
        """Detect funding type, mapping to validator enum values."""
        lowered = text.lower()
        if "fully funded" in lowered or "full scholarship" in lowered:
            return "Fully Funded"
        if "partial" in lowered or "partial funded" in lowered:
            return "Partial Funded"
        if "tuition only" in lowered:
            return "Tuition Only"
        return None

    def _extract_country_heuristic(self, text: str) -> str | None:
        """Heuristic extraction of country from text using known ISO2 mappings.

        Returns an ISO2 code or None if nothing matches.
        """
        # Order matters: more specific patterns first
        patterns = [
            (r"Japan|日本", "JP"),
            (r"China|中国|中华人民共和国", "CN"),
            (r"Republic of Korea|South Korea|대한민국|韓国|韓国", "KR"),
            (r"Germany|Deutschland", "DE"),
            (r"France|République française", "FR"),
            (r"United Kingdom|Britain", "GB"),
            (r"United States|USA|America", "US"),
            (r"Australia", "AU"),
            (r"Indonesia", "ID"),
        ]
        for pattern, code in patterns:
            if re.search(pattern, text):
                return code
        return None

    def _extract_fields_of_study(self, text: str) -> list[str]:
        """Heuristic extraction of fields of study from text.

        Returns an empty list if no specific fields are mentioned. The list
        is intentionally permissive so validation passes; specific filtering
        happens downstream.
        """
        fields = [
            "Engineering", "Computer Science", "Natural Sciences", "Mathematics",
            "Medicine", "Law", "Business", "Economics", "Humanities",
            "Social Sciences", "Arts", "Education", "Agriculture", "Architecture",
        ]
        lowered = text.lower()
        matched: list[str] = []
        for f in fields:
            if f.lower() in lowered:
                matched.append(f)
        # If nothing matched but text mentions general study, return a generic marker
        if not matched and "all" in lowered and "field" in lowered:
            matched.append("All Fields")
        return matched

    def extract_scholarship(self, clean_text: str, source_url: str, default_country: str = "JP") -> Dict[str, Any]:
        name = self._extract_title(clean_text) or "Unknown Scholarship"
        # A page with open-ended application semantics has no fixed deadline;
        # any date the patterns latch onto there is decoration, not a deadline.
        from services.scholarship.freshness import detect_rolling

        deadline = None if detect_rolling(clean_text) else self._extract_deadline(clean_text)
        cycle = self._extract_cycle(clean_text)
        gpa = self._extract_gpa(clean_text)
        age = self._extract_age_limit(clean_text)
        toefl_required, toefl_score = self._extract_toefl(clean_text)
        benefits = self._extract_benefits(clean_text)

        # Heuristic extraction for missing fields
        provider_name = self._extract_provider_name(clean_text) or "Unknown"
        scholarship_type = self._extract_scholarship_type(clean_text)  # None if unknown
        degree = self._extract_degree(clean_text)  # None if unknown
        funding_type = self._extract_funding_type(clean_text)  # None if unknown
        country = self._extract_country_heuristic(clean_text) or default_country
        field_of_study = self._extract_fields_of_study(clean_text)

        return {
            "scholarship_name": name,
            "provider_name": provider_name,
            "scholarship_type": scholarship_type,
            "country": country,
            "university": None,
            "degree": degree,
            "funding_type": funding_type,
            "field_of_study": field_of_study,
            "application_url": source_url,
            "official_source": source_url,
            "timeline": {
                "application_open": None,
                "application_deadline": deadline,
                "application_cycle": cycle,
                "interview_date": None,
                "result_date": None,
                "study_start": None,
            },
            "eligibility": {
                "minimum_gpa": gpa,
                "ielts_required": None,
                "minimum_ielts": None,
                "toefl_required": toefl_required if toefl_score else None,
                "minimum_toefl": toefl_score,
                "gre_required": None,
                "age_limit": age,
                "work_experience": None,
                "research_experience": "Preferred" if "research" in clean_text.lower() else None,
                "publication": None,
                "recommendation_letter": bool(re.search(r"recommendation", clean_text, re.IGNORECASE)),
                "motivation_letter": None,
                "cv_required": None,
                "passport_required": None,
            },
            "benefits": benefits,
        }

