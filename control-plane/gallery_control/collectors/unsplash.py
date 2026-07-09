from __future__ import annotations

from typing import Any

import httpx

from .base import CollectedItem, CollectedMedia


class UnsplashCollector:
    platform = "unsplash"

    def __init__(self, access_key: str):
        if not access_key:
            raise RuntimeError("UNSPLASH_ACCESS_KEY is required for Unsplash collection")
        self.client = httpx.Client(
            timeout=30,
            headers={
                "Authorization": f"Client-ID {access_key}",
                "Accept-Version": "v1",
                "User-Agent": "prompt-gallery-collector/1.0",
            },
        )

    def collect(self, source: dict[str, Any]) -> tuple[list[CollectedItem], str | None]:
        config = source.get("config", {})
        params: dict[str, Any] = {
            "query": source["locator"],
            "page": 1,
            "per_page": min(30, max(1, int(config.get("max_results", 12)))),
            "order_by": config.get("order_by", "latest"),
            "content_filter": "high",
        }
        response = self.client.get("https://api.unsplash.com/search/photos", params=params)
        response.raise_for_status()
        payload = response.json()
        items: list[CollectedItem] = []
        for photo in payload.get("results", []):
            user = photo.get("user") or {}
            author = user.get("name") or user.get("username") or "Unsplash"
            source_url = (photo.get("links") or {}).get("html")
            image_url = (photo.get("urls") or {}).get("regular") or (photo.get("urls") or {}).get("full")
            if not source_url or not image_url:
                continue
            profile_url = (user.get("links") or {}).get("html", "")
            description = photo.get("description") or photo.get("alt_description") or ""
            items.append(
                CollectedItem(
                    platform="unsplash",
                    canonical_url=source_url,
                    external_id=photo["id"],
                    author=author,
                    title=description[:90] or f"Unsplash photo by {author}",
                    source_text=description,
                    published_at=photo.get("created_at"),
                    media=[
                        CollectedMedia(
                            source_url=image_url,
                            alt_text=photo.get("alt_description") or "",
                            width=photo.get("width"),
                            height=photo.get("height"),
                            media_policy="hotlink",
                            attribution={
                                "platform": "Unsplash",
                                "author": author,
                                "author_url": profile_url,
                                "source_url": source_url,
                                "download_location": (photo.get("links") or {}).get("download_location", ""),
                            },
                        )
                    ],
                    metadata={"color": photo.get("color"), "likes": photo.get("likes")},
                )
            )
        cursor = items[0].external_id if items else source.get("last_cursor")
        return items, cursor
