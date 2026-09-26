from enum import Enum


class ProviderType(str, Enum):
    GOVERNMENT = "Government"
    UNIVERSITY = "University"
    FOUNDATION = "Foundation"
    RESEARCH_INSTITUTION = "Research Institution"
    SCHOLARSHIP_AGENCY = "Scholarship Agency"
    NGO = "NGO"
    COMPANY = "Company"
    OTHER = "Other"
