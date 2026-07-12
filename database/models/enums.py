from enum import Enum


class ProviderType(str, Enum):
    GOVERNMENT = "Government"
    UNIVERSITY = "University"
    FOUNDATION = "Foundation"
    NGO = "NGO"
    COMPANY = "Company"
