import os
from googleapiclient.discovery import build


def search_youtube(query: str, search_type: str = "channel", max_results: int = 10) -> list[dict]:
    """Search YouTube for channels or videos matching a query."""
    api_key = os.getenv("YOUTUBE_API_KEY")
    if not api_key:
        return [{"error": "YOUTUBE_API_KEY not set"}]

    youtube = build("youtube", "v3", developerKey=api_key)

    if search_type == "channel":
        req = youtube.search().list(
            q=query,
            type="channel",
            part="snippet",
            maxResults=min(max_results, 50),
            order="relevance",
        )
        resp = req.execute()
        items = resp.get("items", [])
        results = []
        for item in items:
            snippet = item.get("snippet", {})
            channel_id = item["id"].get("channelId", "")
            results.append(
                {
                    "channel_name": snippet.get("channelTitle", ""),
                    "description": snippet.get("description", ""),
                    "url": f"https://www.youtube.com/channel/{channel_id}",
                    "channel_id": channel_id,
                    "published_at": snippet.get("publishedAt", ""),
                }
            )
        return results

    elif search_type == "video":
        req = youtube.search().list(
            q=query,
            type="video",
            part="snippet",
            maxResults=min(max_results, 50),
            order="relevance",
        )
        resp = req.execute()
        items = resp.get("items", [])
        results = []
        for item in items:
            snippet = item.get("snippet", {})
            video_id = item["id"].get("videoId", "")
            results.append(
                {
                    "title": snippet.get("title", ""),
                    "channel_name": snippet.get("channelTitle", ""),
                    "description": snippet.get("description", ""),
                    "url": f"https://www.youtube.com/watch?v={video_id}",
                    "published_at": snippet.get("publishedAt", ""),
                }
            )
        return results

    return []
