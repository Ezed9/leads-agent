import requests
from bs4 import BeautifulSoup
import urllib.parse


def search_producthunt(query: str, max_results: int = 10) -> list[dict]:
    """Scrape Product Hunt search results for products matching a query."""
    encoded = urllib.parse.quote_plus(query)
    url = f"https://www.producthunt.com/search?q={encoded}"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }

    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        return [{"error": f"Request failed: {e}"}]

    soup = BeautifulSoup(resp.text, "html.parser")
    results = []

    # Product Hunt search results are rendered server-side in <li> cards
    # Each product link has data-test="product-item" or appears in search result cards
    items = soup.select("li[class*='item']") or soup.select("[data-test*='post']")

    if not items:
        # Fallback: find all product links
        items = soup.find_all("a", href=lambda h: h and "/posts/" in h)

    seen = set()
    for item in items:
        if len(results) >= max_results:
            break

        # Try to extract from anchor tags with /posts/ paths
        if item.name == "a":
            link = item
        else:
            link = item.find("a", href=lambda h: h and "/posts/" in h)

        if not link:
            continue

        href = link.get("href", "")
        if not href or href in seen:
            continue
        seen.add(href)

        full_url = f"https://www.producthunt.com{href}" if href.startswith("/") else href

        # Extract name and tagline
        name = ""
        tagline = ""

        # Look for heading / strong text
        heading = item.find(["h2", "h3", "strong", "span"], class_=lambda c: c and "name" in c.lower()) if item.name != "a" else None
        if heading:
            name = heading.get_text(strip=True)

        # Fallback: use link text
        if not name:
            name = link.get_text(strip=True).split("\n")[0][:80]

        # Tagline
        tagline_el = item.find("p") if item.name != "a" else None
        if tagline_el:
            tagline = tagline_el.get_text(strip=True)[:200]

        if not name:
            continue

        results.append(
            {
                "name": name,
                "tagline": tagline,
                "url": full_url,
            }
        )

    if not results:
        # Return minimal info so Claude knows the search ran
        return [{"info": f"No Product Hunt results parsed for '{query}'. The page may require JS rendering.", "url": url}]

    return results
