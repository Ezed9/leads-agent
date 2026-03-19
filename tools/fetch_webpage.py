"""
Fetch a webpage and extract contact information.
Upgraded from the gmaps-leads skill: uses httpx + html2text,
auto-discovers /contact /about /team sub-pages, parallel fetching.
"""
import ipaddress
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin, urlparse, unquote

import httpx
import html2text as html2text_lib

# Contact page patterns ordered by priority (from gmaps-leads skill)
CONTACT_PAGE_PATTERNS = [
    r"/contact",
    r"/about",
    r"/team",
    r"/contact-us",
    r"/about-us",
    r"/our-team",
    r"/staff",
    r"/people",
    r"/meet-the-team",
    r"/leadership",
    r"/management",
    r"/founders",
    r"/who-we-are",
    r"/company",
    r"/meet-us",
    r"/our-story",
]

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def _fetch_html(url: str, timeout: float = 12.0) -> tuple[str | None, str]:
    """Fetch HTML from a URL. Returns (html, final_url) or (None, url) on error."""
    try:
        with httpx.Client(follow_redirects=True, timeout=timeout, headers=_HEADERS) as client:
            resp = client.get(url)
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "")
            if "text/html" not in content_type and "text/plain" not in content_type:
                return None, str(resp.url)
            return resp.text, str(resp.url)
    except Exception:
        return None, url


def _html_to_text(html: str) -> str:
    """Convert HTML to clean readable text using html2text."""
    h = html2text_lib.HTML2Text()
    h.ignore_links = False
    h.ignore_images = True
    h.ignore_tables = False
    h.body_width = 0
    text = h.handle(html)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _discover_contact_pages(html: str, base_url: str, max_pages: int = 3) -> list[str]:
    """Find internal URLs matching contact/about/team patterns, sorted by priority."""
    href_pattern = r'href=["\']([^"\']+)["\']'
    hrefs = re.findall(href_pattern, html, re.IGNORECASE)
    base_domain = urlparse(base_url).netloc

    seen: dict[str, int] = {}  # url -> priority
    for href in hrefs:
        if href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        full_url = urljoin(base_url, href)
        parsed = urlparse(full_url)
        if parsed.netloc and parsed.netloc != base_domain:
            continue
        path = parsed.path.lower()
        for priority, pattern in enumerate(CONTACT_PAGE_PATTERNS):
            if re.search(pattern, path):
                if full_url not in seen or priority < seen[full_url]:
                    seen[full_url] = priority
                break

    return [u for u, _ in sorted(seen.items(), key=lambda x: x[1])][:max_pages]


def _extract_emails(text: str) -> list[str]:
    pattern = r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"
    emails = list(set(re.findall(pattern, text)))
    # Filter obvious false positives
    return [
        e for e in emails
        if not any(x in e.lower() for x in [
            "example.com", "sentry.io", "w3.org", "schema.org",
            ".png", ".jpg", ".svg", ".gif", "noreply", "no-reply",
        ])
    ]


def _extract_linkedin(text: str) -> list[str]:
    pattern = r"https?://(?:www\.)?linkedin\.com/(?:company|in|profile)/[\w\-_%]+"
    return list(set(re.findall(pattern, text)))


def _extract_phones(text: str) -> list[str]:
    # Matches common phone formats
    pattern = r"(?:\+?1[\s\-.]?)?\(?\d{3}\)?[\s\-.]?\d{3}[\s\-.]?\d{4}"
    return list(set(re.findall(pattern, text)))[:5]


def _extract_social(text: str) -> dict[str, str]:
    social = {}
    patterns = {
        "twitter": r"https?://(?:www\.)?(?:twitter|x)\.com/[\w]+",
        "instagram": r"https?://(?:www\.)?instagram\.com/[\w.]+",
        "facebook": r"https?://(?:www\.)?facebook\.com/[\w.]+",
        "youtube": r"https?://(?:www\.)?youtube\.com/(?:@?[\w]+|channel/[\w-]+)",
    }
    for platform, pattern in patterns.items():
        match = re.search(pattern, text)
        if match:
            social[platform] = match.group(0)
    return social


def _is_safe_url(url: str) -> tuple[bool, str]:
    """Validate URL is http/https and not a private/loopback address (SSRF guard)."""
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False, f"Blocked scheme: {parsed.scheme}"
        host = parsed.hostname or ""
        try:
            addr = ipaddress.ip_address(host)
            if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved:
                return False, f"Blocked private/internal IP: {host}"
        except ValueError:
            pass  # hostname (not raw IP) — allow
        blocked_hosts = {"localhost", "metadata.google.internal", "169.254.169.254"}
        if host.lower() in blocked_hosts:
            return False, f"Blocked host: {host}"
        return True, ""
    except Exception as e:
        return False, str(e)


def fetch_webpage(url: str, company_name: str = "") -> dict:
    """
    Fetch a webpage and extract contact info.
    Auto-discovers /contact, /about, /team sub-pages and fetches them in parallel.

    Returns:
        url, text (truncated), emails, linkedin_urls, phones, social_media
    """
    if not url:
        return {"error": "No URL provided"}
    # Validate scheme BEFORE normalizing — catches file://, ftp://, etc.
    if "://" in url and not url.startswith(("http://", "https://")):
        return {"error": f"Blocked scheme in URL: {url}", "url": url}
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    safe, reason = _is_safe_url(url)
    if not safe:
        return {"error": reason, "url": url}

    # Fetch main page
    main_html, final_url = _fetch_html(url)
    if not main_html:
        return {"error": f"Could not fetch {url}", "url": url}

    # Discover contact sub-pages
    sub_pages = _discover_contact_pages(main_html, final_url, max_pages=3)

    # Fetch sub-pages in parallel
    all_html_parts = [main_html]
    if sub_pages:
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = {executor.submit(_fetch_html, link): link for link in sub_pages}
            for future in as_completed(futures):
                html, _ = future.result()
                if html:
                    all_html_parts.append(html)

    # Convert all HTML to text and combine
    combined_text = "\n\n".join(_html_to_text(h) for h in all_html_parts)

    emails = _extract_emails(combined_text)
    linkedins = _extract_linkedin(combined_text)
    phones = _extract_phones(combined_text)
    social = _extract_social(combined_text)

    return {
        "url": final_url,
        "company_name": company_name,
        "pages_fetched": 1 + len(sub_pages),
        "sub_pages": sub_pages,
        "text": combined_text[:3000],
        "emails": emails[:10],
        "linkedin_urls": linkedins[:5],
        "phones": phones,
        "social_media": social,
    }
