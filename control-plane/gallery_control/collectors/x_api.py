from __future__ import annotations

from typing import Any
from urllib.parse import quote
import re

import httpx

from .base import CollectedItem, CollectedMedia


class XApiCollector:
    platform = "x"
    base_url = "https://api.x.com/2"

    def __init__(self, bearer_token: str):
        if not bearer_token:
            raise RuntimeError("X_BEARER_TOKEN is required for X collection")
        self.client = httpx.Client(
            timeout=30,
            headers={"Authorization": f"Bearer {bearer_token}", "User-Agent": "prompt-gallery-collector/1.0"},
        )

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        response = self.client.get(f"{self.base_url}{path}", params=params)
        response.raise_for_status()
        return response.json()

    def _resolve_user(self, username: str) -> dict[str, Any]:
        payload = self._get(
            f"/users/by/username/{quote(username.lstrip('@'))}",
            {"user.fields": "id,name,username,url,profile_image_url"},
        )
        if not payload.get("data"):
            raise RuntimeError(f"X user not found: {username}")
        return payload["data"]

    @staticmethod
    def _media_map(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
        return {
            item["media_key"]: item
            for item in payload.get("includes", {}).get("media", [])
            if item.get("media_key")
        }

    def _thread_texts(self, conversation_id: str, username: str) -> list[str]:
        query = f"conversation_id:{conversation_id} from:{username.lstrip('@')}"
        try:
            payload = self._get(
                "/tweets/search/recent",
                {
                    "query": query,
                    "max_results": 100,
                    "tweet.fields": "created_at,conversation_id,in_reply_to_user_id",
                },
            )
        except httpx.HTTPStatusError:
            return []
        posts = sorted(payload.get("data", []), key=lambda item: item.get("created_at", ""))
        return [item.get("text", "") for item in posts if item.get("text")]

    def collect(self, source: dict[str, Any]) -> tuple[list[CollectedItem], str | None]:
        username = source["locator"].lstrip("@")
        user = self._resolve_user(username)
        config = source.get("config", {})
        params: dict[str, Any] = {
            "max_results": min(100, max(5, int(config.get("max_results", 25)))),
            "exclude": "retweets",
            "tweet.fields": "id,text,created_at,conversation_id,attachments,author_id,referenced_tweets",
            "expansions": "attachments.media_keys",
            "media.fields": "media_key,type,url,preview_image_url,alt_text,width,height",
        }
        if source.get("last_cursor"):
            params["since_id"] = source["last_cursor"]
        payload = self._get(f"/users/{user['id']}/tweets", params)
        media_map = self._media_map(payload)
        items: list[CollectedItem] = []

        for post in payload.get("data", []):
            media_keys = post.get("attachments", {}).get("media_keys", [])
            media_items: list[CollectedMedia] = []
            for key in media_keys:
                media = media_map.get(key, {})
                if media.get("type") != "photo" or not media.get("url"):
                    continue
                media_items.append(
                    CollectedMedia(
                        source_url=media["url"],
                        alt_text=media.get("alt_text", ""),
                        width=media.get("width"),
                        height=media.get("height"),
                        attribution={
                            "platform": "X",
                            "author": f"@{username}",
                            "author_url": f"https://x.com/{username}",
                        },
                    )
                )
            if not media_items:
                continue
            post_id = post["id"]
            thread_texts = []
            if config.get("fetch_thread", True):
                thread_texts = self._thread_texts(post.get("conversation_id", post_id), username)
            text = post.get("text", "")
            items.append(
                CollectedItem(
                    platform="x",
                    canonical_url=f"https://x.com/{username}/status/{post_id}",
                    external_id=post_id,
                    author=f"@{username}",
                    title=text.splitlines()[0][:90],
                    source_text=text,
                    published_at=post.get("created_at"),
                    media=media_items,
                    thread_texts=thread_texts,
                    metadata={"conversation_id": post.get("conversation_id", post_id), "user": user},
                )
            )

        newest_id = payload.get("meta", {}).get("newest_id")
        return items, newest_id

    def collect_url(self, url: str) -> CollectedItem:
        match = re.search(r"x\.com/([^/]+)/status/(\d+)", url, re.I)
        if not match:
            raise ValueError("Invalid X status URL")
        username_hint, post_id = match.groups()
        payload = self._get(
            f"/tweets/{post_id}",
            {
                "tweet.fields": "id,text,created_at,conversation_id,attachments,author_id",
                "expansions": "author_id,attachments.media_keys",
                "media.fields": "media_key,type,url,preview_image_url,alt_text,width,height",
                "user.fields": "id,name,username,url",
            },
        )
        post = payload.get("data")
        if not post:
            raise RuntimeError("X post not found")
        users = payload.get("includes", {}).get("users", [])
        user = users[0] if users else {"username": username_hint, "name": username_hint}
        username = user.get("username") or username_hint
        media_map = self._media_map(payload)
        media_items = []
        for key in post.get("attachments", {}).get("media_keys", []):
            media = media_map.get(key, {})
            if media.get("type") != "photo" or not media.get("url"):
                continue
            media_items.append(
                CollectedMedia(
                    source_url=media["url"],
                    alt_text=media.get("alt_text", ""),
                    width=media.get("width"),
                    height=media.get("height"),
                    attribution={
                        "platform": "X",
                        "author": f"@{username}",
                        "author_url": f"https://x.com/{username}",
                    },
                )
            )
        if not media_items:
            raise RuntimeError("This X post does not expose photo media")
        text = post.get("text", "")
        return CollectedItem(
            platform="x",
            canonical_url=f"https://x.com/{username}/status/{post_id}",
            external_id=post_id,
            author=f"@{username}",
            title=text.splitlines()[0][:90],
            source_text=text,
            published_at=post.get("created_at"),
            media=media_items,
            thread_texts=self._thread_texts(post.get("conversation_id", post_id), username),
            metadata={"conversation_id": post.get("conversation_id", post_id), "user": user},
        )
