import os
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed


def search_google_maps(query: str, location: str = "", max_results: int = 10) -> list[dict]:
    """Search Google Places API for businesses matching a query."""
    api_key = os.getenv("GOOGLE_MAPS_API_KEY")
    if not api_key:
        return [{"error": "GOOGLE_MAPS_API_KEY not set. Skipping Google Maps search."}]

    search_query = f"{query} {location}".strip()
    url = "https://maps.googleapis.com/maps/api/place/textsearch/json"
    params = {"query": search_query, "key": api_key}

    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        return [{"error": f"Google Maps API request failed: {e}"}]

    if data.get("status") not in ("OK", "ZERO_RESULTS"):
        return [{"error": f"Google Maps API error: {data.get('status')} - {data.get('error_message', '')}"}]

    places = data.get("results", [])[:max_results]
    if not places:
        return []

    # Fetch Place Details (website) in parallel
    def fetch_website(place_id: str) -> str:
        return _get_place_website(place_id, api_key)

    place_ids = [p.get("place_id", "") for p in places]
    websites = {}
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(fetch_website, pid): pid for pid in place_ids if pid}
        for future in as_completed(futures):
            pid = futures[future]
            try:
                websites[pid] = future.result()
            except Exception:
                websites[pid] = ""

    results = []
    for place in places:
        place_id = place.get("place_id", "")
        results.append({
            "name": place.get("name", ""),
            "address": place.get("formatted_address", ""),
            "rating": place.get("rating"),
            "url": f"https://www.google.com/maps/place/?q=place_id:{place_id}",
            "website": websites.get(place_id, ""),
            "types": place.get("types", []),
        })

    return results


def _get_place_website(place_id: str, api_key: str) -> str:
    """Fetch the website for a place from the Place Details API."""
    if not place_id:
        return ""
    url = "https://maps.googleapis.com/maps/api/place/details/json"
    params = {"place_id": place_id, "fields": "website", "key": api_key}
    try:
        resp = requests.get(url, params=params, timeout=10)
        if resp.ok:
            return resp.json().get("result", {}).get("website", "")
    except Exception:
        pass
    return ""
