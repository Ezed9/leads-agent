import os
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed


def search_github(query: str, search_type: str = "repositories", max_results: int = 10) -> list[dict]:
    """Search GitHub for repositories or users matching a query."""
    token = os.getenv("GITHUB_TOKEN")
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    if search_type == "repositories":
        url = "https://api.github.com/search/repositories"
        params = {"q": query, "per_page": min(max_results, 30), "sort": "stars", "order": "desc"}
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=10)
            resp.raise_for_status()
        except Exception as e:
            return [{"error": f"GitHub search failed: {e}"}]
        items = resp.json().get("items", [])
        return [
            {
                "name": item["full_name"],
                "description": item.get("description") or "",
                "url": item["html_url"],
                "homepage": item.get("homepage") or "",
                "stars": item.get("stargazers_count", 0),
                "language": item.get("language") or "",
                "topics": item.get("topics", []),
            }
            for item in items
        ]

    elif search_type == "users":
        url = "https://api.github.com/search/users"
        params = {"q": query, "per_page": min(max_results, 30), "sort": "joined", "order": "desc"}
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=10)
            resp.raise_for_status()
        except Exception as e:
            return [{"error": f"GitHub user search failed: {e}"}]

        items = resp.json().get("items", [])[:max_results]

        def fetch_detail(item: dict) -> dict:
            try:
                detail_resp = requests.get(item["url"], headers=headers, timeout=10)
                detail = detail_resp.json() if detail_resp.ok else {}
            except Exception:
                detail = {}
            return {
                "name": item["login"],
                "display_name": detail.get("name") or item["login"],
                "company": detail.get("company") or "",
                "blog": detail.get("blog") or "",
                "bio": detail.get("bio") or "",
                "url": item["html_url"],
                "type": item.get("type", "User"),
            }

        # Fetch user details in parallel
        results = []
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {executor.submit(fetch_detail, item): item for item in items}
            for future in as_completed(futures):
                try:
                    results.append(future.result())
                except Exception as e:
                    results.append({"error": str(e)})
        return results

    return []
