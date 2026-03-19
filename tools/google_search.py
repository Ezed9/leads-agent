import time
try:
    from ddgs import DDGS
    from ddgs.exceptions import RatelimitException
except ImportError:
    from duckduckgo_search import DDGS
    from duckduckgo_search.exceptions import RatelimitException


def search_google(query: str, max_results: int = 10) -> list[dict]:
    """Search the web using DuckDuckGo. Retries once on rate limit."""
    for attempt in range(2):
        try:
            with DDGS() as ddgs:
                results = []
                for r in ddgs.text(query, max_results=max_results):
                    results.append({
                        "title": r.get("title", ""),
                        "url": r.get("href", ""),
                        "snippet": r.get("body", ""),
                    })
                return results
        except RatelimitException:
            if attempt == 0:
                time.sleep(3)
                continue
            return [{"error": "DuckDuckGo rate limit hit. Try again in a few seconds."}]
        except Exception as e:
            return [{"error": str(e)}]
    return []
