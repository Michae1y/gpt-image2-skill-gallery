from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import httpx

from .base import CollectedItem, CollectedMedia
from .x_api import XApiCollector


META_RE = re.compile(
    r'<meta\s+[^>]*(?:property|name)=["\']([^"\']+)["\'][^>]*content=["\']([^"\']*)["\'][^>]*>',
    re.I,
)
META_RE_REVERSED = re.compile(
    r'<meta\s+[^>]*content=["\']([^"\']*)["\'][^>]*(?:property|name)=["\']([^"\']+)["\'][^>]*>',
    re.I,
)


class LinkCollector:
    def __init__(self, *, x_bearer_token: str = "", wallhaven_api_key: str = "", unsplash_access_key: str = ""):
        self.x_bearer_token = x_bearer_token
        self.wallhaven_api_key = wallhaven_api_key
        self.unsplash_access_key = unsplash_access_key
        self.client = httpx.Client(
            timeout=35,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 PromptGalleryCollector/1.0"},
        )

    def collect(self, url: str) -> CollectedItem:
        parsed = urlparse(url)
        host = parsed.netloc.lower().removeprefix("www.")
        if host in {"x.com", "twitter.com"}:
            return self._x(url)
        if host.endswith("wallhaven.cc"):
            return self._wallhaven(url)
        return self._open_graph(url, host)

    def _x(self, url: str) -> CollectedItem:
        match = re.search(r"(?:x|twitter)\.com/([^/]+)/status/(\d+)", url, re.I)
        if not match:
            raise ValueError("Invalid X status URL")
        username, post_id = match.groups()
        canonical = f"https://x.com/{username}/status/{post_id}"
        if self.x_bearer_token:
            return XApiCollector(self.x_bearer_token).collect_url(canonical)

        response = self.client.get(f"https://api.fxtwitter.com/{username}/status/{post_id}")
        response.raise_for_status()
        tweet = response.json().get("tweet") or {}
        author = tweet.get("author") or {}
        media_data = (tweet.get("media") or {}).get("all") or []
        media = []
        for item in media_data:
            if item.get("type") not in {"photo", "image"} or not item.get("url"):
                continue
            media.append(
                CollectedMedia(
                    source_url=item["url"],
                    alt_text=item.get("altText") or item.get("alt_text") or "",
                    width=item.get("width"),
                    height=item.get("height"),
                    attribution={
                        "platform": "X",
                        "author": f"@{author.get('screen_name') or username}",
                        "author_url": f"https://x.com/{author.get('screen_name') or username}",
                    },
                )
            )
        if not media:
            raise RuntimeError("X public preview did not expose any photo media")
        text = tweet.get("text") or ""
        return CollectedItem(
            platform="x",
            canonical_url=canonical,
            external_id=post_id,
            author=f"@{author.get('screen_name') or username}",
            title=text.splitlines()[0][:90],
            source_text=text,
            published_at=tweet.get("date"),
            media=media,
            metadata={"public_preview": "fxtwitter", "likes": tweet.get("likes")},
        )

    def _wallhaven(self, url: str) -> CollectedItem:
        match = re.search(r"wallhaven\.cc/w/([a-z0-9]+)", url, re.I)
        if not match:
            raise ValueError("Invalid Wallhaven URL")
        wallpaper_id = match.group(1)
        headers = {"X-API-Key": self.wallhaven_api_key} if self.wallhaven_api_key else {}
        response = self.client.get(f"https://wallhaven.cc/api/v1/w/{wallpaper_id}", headers=headers)
        response.raise_for_status()
        wallpaper = response.json()["data"]
        tags = [tag.get("name", "") for tag in wallpaper.get("tags", []) if tag.get("name")]
        uploader = (wallpaper.get("uploader") or {}).get("username") or "Wallhaven"
        return CollectedItem(
            platform="wallhaven",
            canonical_url=wallpaper["url"],
            external_id=wallpaper["id"],
            author=uploader,
            title=" / ".join(tags[:4]) or f"Wallhaven {wallpaper_id}",
            source_text="、".join(tags),
            published_at=wallpaper.get("created_at"),
            media=[CollectedMedia(
                source_url=wallpaper["path"],
                width=wallpaper.get("dimension_x"),
                height=wallpaper.get("dimension_y"),
                attribution={"platform": "Wallhaven", "author": uploader, "source_url": wallpaper["url"]},
            )],
            metadata={"tags": tags, "purity": wallpaper.get("purity")},
        )

    def _open_graph(self, url: str, host: str) -> CollectedItem:
        response = self.client.get(url)
        response.raise_for_status()
        source = response.text[:2_000_000]
        metadata: dict[str, str] = {}
        for key, value in META_RE.findall(source):
            metadata[key.lower()] = html.unescape(value)
        for value, key in META_RE_REVERSED.findall(source):
            metadata[key.lower()] = html.unescape(value)
        image_url = metadata.get("og:image") or metadata.get("twitter:image")
        if not image_url:
            raise RuntimeError("The page does not expose an Open Graph image; upload or paste the image URL manually")
        title = metadata.get("og:title") or metadata.get("twitter:title") or host
        description = metadata.get("og:description") or metadata.get("description") or ""
        author = metadata.get("author") or host
        return CollectedItem(
            platform=host.split(".")[0] if host else "web",
            canonical_url=str(response.url),
            external_id=str(abs(hash(str(response.url)))),
            author=author,
            title=title[:120],
            source_text=description,
            published_at=datetime.now(timezone.utc).isoformat(),
            media=[CollectedMedia(
                source_url=image_url,
                attribution={"platform": host, "author": author, "source_url": str(response.url)},
            )],
            metadata={"open_graph": metadata},
        )
