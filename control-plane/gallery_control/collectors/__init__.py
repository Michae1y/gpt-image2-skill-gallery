from __future__ import annotations

from .rss import RssCollector
from .unsplash import UnsplashCollector
from .wallhaven import WallhavenCollector
from .x_api import XApiCollector


def collector_for(platform: str, settings):
    platform = platform.lower()
    if platform == "x":
        return XApiCollector(settings.x_bearer_token)
    if platform == "wallhaven":
        return WallhavenCollector(settings.wallhaven_api_key)
    if platform == "unsplash":
        return UnsplashCollector(settings.unsplash_access_key)
    if platform in {"rss", "design-milk", "abduzeedo"}:
        return RssCollector()
    raise ValueError(f"Unsupported automatic collector: {platform}")
