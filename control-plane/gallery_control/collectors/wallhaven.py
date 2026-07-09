from __future__ import annotations

from typing import Any

import httpx

from .base import CollectedItem, CollectedMedia


class WallhavenCollector:
    platform = "wallhaven"

    def __init__(self, api_key: str = ""):
        self.api_key = api_key
        self.client = httpx.Client(timeout=30, headers={"User-Agent": "prompt-gallery-collector/1.0"})

    def collect(self, source: dict[str, Any]) -> tuple[list[CollectedItem], str | None]:
        config = source.get("config", {})
        params: dict[str, Any] = {
            "q": source["locator"],
            "sorting": config.get("sorting", "date_added"),
            "order": config.get("order", "desc"),
            "purity": config.get("purity", "100"),
            "categories": config.get("categories", "111"),
            "atleast": config.get("atleast", "1920x1080"),
            "page": 1,
        }
        if config.get("topRange"):
            params["topRange"] = config["topRange"]
        if self.api_key:
            params["apikey"] = self.api_key
        response = self.client.get("https://wallhaven.cc/api/v1/search", params=params)
        response.raise_for_status()
        payload = response.json()
        limit = min(24, max(1, int(config.get("max_results", 12))))
        items: list[CollectedItem] = []
        for wallpaper in payload.get("data", [])[:limit]:
            uploader = (wallpaper.get("uploader") or {}).get("username") or "Wallhaven"
            tags = [tag.get("name", "") for tag in wallpaper.get("tags", []) if tag.get("name")]
            title = " / ".join(tags[:4]) or f"Wallhaven {wallpaper.get('id', '')}"
            items.append(
                CollectedItem(
                    platform="wallhaven",
                    canonical_url=wallpaper["url"],
                    external_id=wallpaper["id"],
                    author=uploader,
                    title=title,
                    source_text="、".join(tags),
                    published_at=wallpaper.get("created_at"),
                    media=[
                        CollectedMedia(
                            source_url=wallpaper["path"],
                            width=wallpaper.get("dimension_x"),
                            height=wallpaper.get("dimension_y"),
                            attribution={
                                "platform": "Wallhaven",
                                "author": uploader,
                                "source_url": wallpaper["url"],
                            },
                        )
                    ],
                    metadata={
                        "tags": tags,
                        "purity": wallpaper.get("purity"),
                        "category": wallpaper.get("category"),
                        "colors": wallpaper.get("colors", []),
                    },
                )
            )
        cursor = items[0].external_id if items else source.get("last_cursor")
        return items, cursor
