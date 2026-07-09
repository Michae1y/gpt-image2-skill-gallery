from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class CollectedMedia:
    source_url: str
    alt_text: str = ""
    width: int | None = None
    height: int | None = None
    media_policy: str = "cache"
    attribution: dict[str, Any] = field(default_factory=dict)


@dataclass
class CollectedItem:
    platform: str
    canonical_url: str
    external_id: str
    author: str
    title: str
    source_text: str
    published_at: str | None
    media: list[CollectedMedia]
    thread_texts: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class Collector(Protocol):
    def collect(self, source: dict[str, Any]) -> tuple[list[CollectedItem], str | None]: ...
