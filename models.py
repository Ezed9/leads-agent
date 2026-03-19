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
