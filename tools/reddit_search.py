import requests


def search_reddit(query: str, subreddits: list[str] | None = None, max_results: int = 10) -> list[dict]:
    """Search Reddit for posts matching a query, optionally within specific subreddits."""
    headers = {"User-Agent": "leads-agent/1.0 (B2B lead finder)"}
    results = []

    search_targets = subreddits if subreddits else ["all"]

    for sub in search_targets:
        if len(results) >= max_results:
            break
        url = f"https://www.reddit.com/r/{sub}/search.json"
        params = {
            "q": query,
            "limit": min(max_results - len(results), 25),
            "sort": "relevance",
            "restrict_sr": "true" if sub != "all" else "false",
            "t": "year",
        }
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=10)
            resp.raise_for_status()
            posts = resp.json().get("data", {}).get("children", [])
            for post in posts:
                d = post.get("data", {})
                results.append(
                    {
                        "title": d.get("title", ""),
                        "subreddit": d.get("subreddit", ""),
                        "author": d.get("author", ""),
                        "url": f"https://reddit.com{d.get('permalink', '')}",
                        "external_url": d.get("url", ""),
                        "selftext": (d.get("selftext") or "")[:500],
                        "score": d.get("score", 0),
                        "num_comments": d.get("num_comments", 0),
                        "flair": d.get("link_flair_text") or "",
                    }
                )
        except Exception as e:
            # Track errors separately — don't consume result quota slots
            results.append({"_error": str(e), "_subreddit": sub})

    # Return real results first, errors last, capped at max_results
    good = [r for r in results if "_error" not in r]
    errors = [r for r in results if "_error" in r]
    return (good + errors)[:max_results]
