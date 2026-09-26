"""OpportunityClassifier — multi-signal ROUTER, not an absolute gate.

Answers "what should Polaris do with this candidate?" — not "is this
definitely a scholarship?". Combines weighted term families, URL signals,
structured data, and organization context. Confidence drives routing:
high → normal pipeline, medium → lower priority, unknown/ambiguous → retained
for review, high-confidence JOB/VISA_JOB → rejected with evidence retained.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

from services.exploration.candidate_analyzer import AnalyzedCandidate

# --- Term families (English base; localized packs come from country config) ---

SCHOLARSHIP_TERMS = [
    "scholarship", "scholarships", "奨学金", "장학금", "beasiswa", "bourse",
    "stipendium", "奖学金", "장학", "studienstipendium",
]
FELLOWSHIP_TERMS = ["fellowship", "fellowships", "research fellowship", "postdoctoral fellowship"]
GRANT_TERMS = ["grant", "grants", "bursary", "bursaries", "studentship", "award", "financial aid"]
STUDENT_FUNDING_TERMS = [
    "fully funded", "tuition waiver", "tuition-free", "funding for students",
    "student funding", "study grant", "financial support for students",
]

JOB_TERMS = [
    "job", "jobs", "vacancy", "vacancies", "hiring", "recruitment", "position",
    "positions", "career", "careers", "employment", "salary", "full-time",
    "part-time", "we are hiring", "apply for this job", "job description",
]
VISA_JOB_TERMS = [
    "visa sponsorship", "visa sponsored", "sponsorship jobs", "work visa",
    "skilled worker visa", "farm jobs", "seasonal work", "seasonal worker",
]
INTERNSHIP_TERMS = ["internship", "internships", "intern position", "placement year"]
COURSE_TERMS = [
    "online course", "training program", "certificate program", "mooc",
    "short course", "workshop series",
]

IRRELEVANT_TERMS = [
    "casino", "betting", "porn", "crypto airdrop", "forex signal",
    "download driver", "cracked software",
]

# Terms that strengthen the student-funding reading of "sponsorship"/"funding"
STUDENT_CONTEXT_TERMS = [
    "university", "student", "students", "undergraduate", "postgraduate",
    "master", "phd", "doctoral", "academic", "tuition", "enrollment",
    "admission", "semester", "academic year",
]


@dataclass
class ClassificationResult:
    label: str
    confidence: float
    signals: dict = field(default_factory=dict)
    routing: str = "unknown"           # opportunity | low_priority | review | reject | irrelevant
    priority: int = 5
    reasoning: str = ""


def _count_terms(text: str, terms: list[str]) -> list[str]:
    found = []
    for term in terms:
        if re.search(re.escape(term.lower()), text):
            found.append(term)
    return found


class OpportunityClassifier:
    """Multi-signal classifier with confidence-aware routing."""

    def __init__(self, terminology: dict[str, list[str]] | None = None) -> None:
        # Localized scholarship terms from country config join the base list.
        extra = [t.lower() for t in (terminology or {}).get("scholarship", [])]
        self.scholarship_terms = list(dict.fromkeys(SCHOLARSHIP_TERMS + extra))

    def classify(self, candidate: AnalyzedCandidate, snippet: str = "") -> ClassificationResult:
        title = (candidate.title or "").lower()
        headings = " ".join(candidate.headings).lower()
        url_path = urlparse(candidate.url).path.lower()
        body = (candidate.main_text or "")[:6000].lower()
        meta = (candidate.meta_description or "").lower()
        combined = " ".join([title, headings, meta, snippet.lower()])

        signals: dict = {}

        # 1. Structured data: JobPosting is a strong JOB signal
        jsonld_types = set()
        for item in candidate.structured_data:
            t = item.get("@type")
            if isinstance(t, str):
                jsonld_types.add(t)
            elif isinstance(t, list):
                jsonld_types.update(t)
        has_jobposting = "JobPosting" in jsonld_types
        signals["jobposting_structured_data"] = has_jobposting

        # 2. Irrelevance check (only clear-out evidence rejects outright)
        irrelevant_hits = _count_terms(combined + " " + body[:2000], IRRELEVANT_TERMS)
        if irrelevant_hits:
            return ClassificationResult(
                label="OTHER",
                confidence=0.9,
                signals={"irrelevant_hits": irrelevant_hits},
                routing="irrelevant",
                priority=9,
                reasoning=f"clearly irrelevant content: {irrelevant_hits[:3]}",
            )

        # 3. Term family counts (weighted: title/headings > meta > body > url)
        def hits(terms: list[str]) -> dict:
            return {
                "title": len(_count_terms(title, terms)),
                "headings": len(_count_terms(headings, terms)),
                "meta": len(_count_terms(meta, terms)),
                "snippet": len(_count_terms(snippet.lower(), terms)),
                "body": min(len(_count_terms(body, terms)), 8),
                "url": len(_count_terms(url_path.replace("-", " "), terms)),
            }

        sch = hits(self.scholarship_terms)
        fel = hits(FELLOWSHIP_TERMS)
        grt = hits(GRANT_TERMS)
        fun = hits(STUDENT_FUNDING_TERMS)
        job = hits(JOB_TERMS)
        vjob = hits(VISA_JOB_TERMS)
        itr = hits(INTERNSHIP_TERMS)
        crs = hits(COURSE_TERMS)

        def score(h: dict) -> float:
            return (
                h["title"] * 3.0 + h["headings"] * 2.0 + h["meta"] * 1.5
                + h["snippet"] * 1.0 + h["body"] * 0.5 + h["url"] * 1.0
            )

        scholarship_score = score(sch) + score(fun) * 0.8 + score(fel) * 0.9 + score(grt) * 0.9
        job_score = score(job) + (4.0 if has_jobposting else 0.0)
        visa_job_score = score(vjob) + score(job) * 0.6
        internship_score = score(itr)
        course_score = score(crs)

        signals.update(
            {
                "scholarship_hits": sch,
                "funding_hits": fun,
                "fellowship_hits": fel,
                "grant_hits": grt,
                "job_hits": job,
                "visa_job_hits": vjob,
                "internship_hits": itr,
                "course_hits": crs,
                "scores": {
                    "scholarship": scholarship_score,
                    "job": job_score,
                    "visa_job": visa_job_score,
                    "internship": internship_score,
                    "course": course_score,
                },
            }
        )

        # 4. Negative-context handling: employment families dominate when
        # mixed with funding words ("visa sponsorship farm jobs" case).
        # But student-context terms rescue genuinely academic pages.
        student_context = len(_count_terms(combined + " " + body[:3000], STUDENT_CONTEXT_TERMS))
        signals["student_context_hits"] = student_context

        best_label, best_score = "UNKNOWN", 0.0
        for label, s in (
            ("SCHOLARSHIP", scholarship_score),
            ("JOB", job_score),
            ("VISA_JOB", visa_job_score),
            ("INTERNSHIP", internship_score),
            ("COURSE", course_score),
        ):
            if s > best_score:
                best_label, best_score = label, s

        total = scholarship_score + job_score + visa_job_score + internship_score + course_score
        if best_score <= 0.5:
            return ClassificationResult(
                label="UNKNOWN",
                confidence=0.2,
                signals=signals,
                routing="review",
                priority=6,
                reasoning="no meaningful term-family signal",
            )

        confidence = min(0.99, best_score / (best_score + max(total - best_score, 1.0) + 2.0))

        # Employment dominance rule: job/visa signals swamp academic context
        employment = job_score + visa_job_score
        if employment > scholarship_score * 2.0 and student_context < 2:
            label = "JOB" if job_score >= visa_job_score else "VISA_JOB"
            return ClassificationResult(
                label=label,
                confidence=max(confidence, 0.8),
                signals=signals,
                routing="reject",
                priority=8,
                reasoning="employment terms dominate with no student context",
            )

        if best_label == "SCHOLARSHIP":
            if confidence >= 0.75:
                routing, priority = "opportunity", 2
            elif confidence >= 0.45:
                routing, priority = "low_priority", 4
            else:
                routing, priority = "review", 5
            return ClassificationResult(
                label="SCHOLARSHIP",
                confidence=round(confidence, 2),
                signals=signals,
                routing=routing,
                priority=priority,
                reasoning="scholarship term-family signal",
            )

        if best_label in ("JOB", "VISA_JOB") and confidence >= 0.7:
            return ClassificationResult(
                label=best_label,
                confidence=round(confidence, 2),
                signals=signals,
                routing="reject",
                priority=8,
                reasoning="high-confidence employment page",
            )
        if best_label == "INTERNSHIP" and confidence >= 0.7:
            return ClassificationResult(
                label="INTERNSHIP",
                confidence=round(confidence, 2),
                signals=signals,
                routing="reject",
                priority=8,
                reasoning="internship page, not student funding",
            )
        if best_label == "COURSE" and confidence >= 0.7:
            return ClassificationResult(
                label="COURSE",
                confidence=round(confidence, 2),
                signals=signals,
                routing="reject",
                priority=8,
                reasoning="course page, not funding",
            )

        # Ambiguous: retain for review, never silently discard
        return ClassificationResult(
            label=best_label if best_label != "UNKNOWN" else "UNKNOWN",
            confidence=round(confidence, 2),
            signals=signals,
            routing="review",
            priority=5,
            reasoning="ambiguous multi-family signal",
        )
