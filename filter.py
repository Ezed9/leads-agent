"""Lead filtering, classification, and priority scoring."""

import csv
import os
import re
from models import Lead, FilteredLead


# TLD → country mapping for location extraction
TLD_COUNTRY = {
    ".au": "Australia", ".uk": "UK", ".de": "Germany", ".fr": "France",
    ".ca": "Canada", ".in": "India", ".jp": "Japan", ".br": "Brazil",
    ".nl": "Netherlands", ".se": "Sweden", ".no": "Norway", ".dk": "Denmark",
    ".fi": "Finland", ".nz": "New Zealand", ".sg": "Singapore", ".hk": "Hong Kong",
    ".kr": "South Korea", ".mx": "Mexico", ".za": "South Africa", ".ie": "Ireland",
    ".it": "Italy", ".es": "Spain", ".pt": "Portugal", ".ch": "Switzerland",
    ".at": "Austria", ".be": "Belgium", ".pl": "Poland", ".cz": "Czech Republic",
    ".il": "Israel", ".ae": "UAE", ".ph": "Philippines", ".th": "Thailand",
    ".co.uk": "UK", ".com.au": "Australia", ".co.nz": "New Zealand",
    ".co.in": "India", ".co.za": "South Africa",
}

# Cities/regions to scan for in descriptions
KNOWN_LOCATIONS = [
    "New York", "San Francisco", "Los Angeles", "Chicago", "Seattle", "Austin",
    "Boston", "Denver", "Miami", "Dallas", "Houston", "Atlanta", "Portland",
    "Toronto", "Vancouver", "Montreal", "London", "Manchester", "Berlin",
    "Munich", "Paris", "Amsterdam", "Stockholm", "Copenhagen", "Oslo",
    "Helsinki", "Dublin", "Sydney", "Melbourne", "Brisbane", "Perth",
    "Auckland", "Singapore", "Hong Kong", "Tokyo", "Seoul", "Mumbai",
    "Bangalore", "Tel Aviv", "Dubai", "Cape Town", "Sao Paulo",
    "USA", "United States", "Canada", "UK", "United Kingdom", "Germany",
    "France", "Australia", "India", "Japan", "Brazil", "Netherlands",
    "Sweden", "Norway", "Denmark", "Finland", "New Zealand", "Singapore",
    "Israel", "UAE",
]

# Business type keyword patterns
TYPE_KEYWORDS = {
    "saas": ["saas", "platform", "software", "app", "cloud", "api", "tool", "suite", "dashboard"],
    "agency": ["agency", "consulting", "consultancy", "services", "studio", "firm", "advisors", "partners"],
    "ecommerce": ["shop", "store", "e-commerce", "ecommerce", "retail", "marketplace", "commerce"],
    "local_service": [
        "gym", "salon", "clinic", "restaurant", "plumber", "dentist", "spa",
        "fitness", "yoga", "barber", "cleaning", "landscaping", "roofing",
        "hvac", "electrician", "mechanic", "veterinary", "vet", "cafe",
        "bakery", "florist", "photography", "tattoo", "massage", "chiropractic",
    ],
}


def load_leads_csv(filepath: str) -> list[Lead]:
    """Load leads from a CSV file into Lead objects."""
    leads = []
    with open(filepath, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            leads.append(Lead(
                company_name=row.get("company_name", "Unknown"),
                source=row.get("source", "unknown"),
                description=row.get("description", ""),
                url=row.get("url", ""),
                website=row.get("website", ""),
                email=row.get("email", ""),
                linkedin=row.get("linkedin", ""),
                why_good_lead=row.get("why_good_lead", ""),
                score=int(row.get("score", 5)),
            ))
    return leads


def extract_location(lead: Lead) -> str:
    """Extract location from URL TLD or description text."""
    url = lead.website or lead.url
    if url:
        # Check compound TLDs first (e.g. .co.uk before .uk)
        for tld, country in sorted(TLD_COUNTRY.items(), key=lambda x: -len(x[0])):
            # Match TLD at end of domain (before path)
            domain = url.split("/")[2] if "://" in url else url.split("/")[0]
            if domain.endswith(tld):
                return country

    # Scan description for known locations
    text = f"{lead.description} {lead.why_good_lead}".lower()
    for loc in KNOWN_LOCATIONS:
        if loc.lower() in text:
            return loc
    return ""


def classify_business_type(lead: Lead) -> str:
    """Classify business type using keyword heuristics."""
    text = f"{lead.description} {lead.company_name} {lead.why_good_lead}".lower()
    scores = {}
    for btype, keywords in TYPE_KEYWORDS.items():
        scores[btype] = sum(1 for kw in keywords if kw in text)
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "other"


def compute_priority_score(lead: Lead, business_type: str, location: str,
                           filter_type: str | None = None,
                           filter_location: str | None = None) -> float:
    """Compute 0-100 outreach priority score."""
    score = 0.0

    # Has email: +30
    if lead.email and lead.email.strip():
        score += 30

    # Has website: +20
    website = lead.website or lead.url
    if website and website.strip():
        score += 20

    # Agent score contribution: up to 25
    score += (min(lead.score, 10) / 10) * 25

    # Business type match: +15
    if filter_type and business_type == filter_type:
        score += 15

    # Location match: +10
    if filter_location and location and filter_location.lower() in location.lower():
        score += 10

    return round(score, 1)


def filter_leads(
    leads: list[Lead],
    min_score: int | None = None,
    has_email: bool = False,
    has_website: bool = False,
    business_type: str | None = None,
    location: str | None = None,
) -> list[FilteredLead]:
    """Filter, classify, score, and sort leads."""
    filtered = []
    for lead in leads:
        # Apply filters
        if min_score is not None and lead.score < min_score:
            continue
        if has_email and not (lead.email and lead.email.strip()):
            continue
        website = lead.website or lead.url
        if has_website and not (website and website.strip()):
            continue

        loc = extract_location(lead)
        btype = classify_business_type(lead)

        if business_type and btype != business_type:
            continue
        if location and (not loc or location.lower() not in loc.lower()):
            continue

        priority = compute_priority_score(lead, btype, loc, business_type, location)

        filtered.append(FilteredLead(
            company_name=lead.company_name,
            source=lead.source,
            description=lead.description,
            url=lead.url,
            website=lead.website,
            email=lead.email,
            linkedin=lead.linkedin,
            why_good_lead=lead.why_good_lead,
            score=lead.score,
            priority_score=priority,
            business_type=btype,
            location=loc,
            has_email=bool(lead.email and lead.email.strip()),
            has_website=bool(website and website.strip()),
        ))

    filtered.sort(key=lambda x: x.priority_score, reverse=True)
    return filtered


def save_filtered_csv(filtered_leads: list[FilteredLead], original_filepath: str) -> str:
    """Save filtered leads to CSV, compatible with outreach-agent."""
    output_dir = os.path.join(os.path.dirname(__file__), "output")
    os.makedirs(output_dir, exist_ok=True)

    original_name = os.path.basename(original_filepath)
    if original_name.startswith("filtered_"):
        filename = original_name  # don't double-prefix
    else:
        filename = f"filtered_{original_name}"
    filepath = os.path.join(output_dir, filename)

    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "priority_score", "business_type",
            "company_name", "score", "source", "description",
            "website", "email", "linkedin", "why_good_lead", "url",
        ])
        writer.writeheader()
        for lead in filtered_leads:
            writer.writerow({
                "priority_score": lead.priority_score,
                "business_type": lead.business_type,
                "company_name": lead.company_name,
                "score": lead.score,
                "source": lead.source,
                "description": lead.description,
                "website": lead.website or lead.url,
                "email": lead.email,
                "linkedin": lead.linkedin,
                "why_good_lead": lead.why_good_lead,
                "url": lead.url,
            })
    return filepath
