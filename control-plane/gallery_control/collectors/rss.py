from __future__ import annotations

from html import unescape
import re
from urllib.parse import urljoin

import feedparser

from .base import CollectedItem, CollectedMedia


IMAGE_RE = re.compile(r'<img[^>]+src=["\']([^"\']+)["\']', re.I)


class RssCollector:
    platform = "rss"

    def collect(self, source: dict) -> tuple[list[CollectedItem], str | None]:
        feed = feedparser.parse(source["locator"])
        if getattr(feed, "bozo", False) and not getattr(feed, "entries", []):
            raise RuntimeError(str(getattr(feed, "bozo_exception", "RSS parse failed")))
        config = source.get("config", {})
        limit = min(50, max(1, int(config.get("max_results", 12))))
        items: list[CollectedItem] = []
        for entry in feed.entries[:limit]:
            link = entry.get("link")
            if not link:
                continue
            html = entry.get("content", [{}])[0].get("value", "") or entry.get("summary", "")
            media_url = ""
            if entry.get("media_content"):
                media_url = entry.media_content[0].get("url", "")
            if not media_url:
                match = IMAGE_RE.search(html)
                if match:
                    media_url = urljoin(link, unescape(match.group(1)))
            if not media_url:
                continue
            external_id = entry.get("id") or link
            title = unescape(re.sub(r"<[^>]+>", "", entry.get("title", ""))).strip()
            summary = unescape(re.sub(r"<[^>]+>", " ", entry.get("summary", ""))).strip()
            items.append(
                CollectedItem(
                    platform=source.get("platform", "rss"),
                    canonical_url=link,
                    external_id=external_id,
                    author=entry.get("author") or source.get("label") or "",
                    title=title,
                    source_text=summary,
                    published_at=entry.get("published"),
                    media=[
                        CollectedMedia(
                            source_url=media_url,
                            attribution={
                                "platform": source.get("label") or source.get("platform", "RSS"),
                                "author": entry.get("author", ""),
                                "source_url": link,
                            },
                        )
                    ],
                    metadata={"feed_url": source["locator"]},
                )
            )
        cursor = items[0].external_id if items else source.get("last_cursor")
        return items, cursor
