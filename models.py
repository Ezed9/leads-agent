from dataclasses import dataclass


@dataclass
class Lead:
    company_name: str
    source: str           # "google" | "producthunt" | "github" | "reddit" | "maps"
    description: str
    url: str
    website: str          # company homepage if different from url
    email: str            # extracted contact email, if found
    linkedin: str         # LinkedIn company/person URL, if found
    why_good_lead: str    # Claude explains fit
    score: int            # 1–10


@dataclass
class FilteredLead:
    # Original Lead fields (passed through)
    company_name: str
    source: str
    description: str
    url: str
    website: str
    email: str
    linkedin: str
    why_good_lead: str
    score: int
    # Computed fields
    priority_score: float     # 0-100 composite outreach priority
    business_type: str        # "saas"|"agency"|"local_service"|"ecommerce"|"other"
    location: str             # extracted location or ""
    has_email: bool
    has_website: bool
