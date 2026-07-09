from __future__ import annotations

import hashlib
import mimetypes
import re
import uuid
from pathlib import Path
from typing import Any

import httpx
from PIL import Image, ImageOps

from .categories import classify_by_keywords
from .collectors import collector_for
from .collectors.base import CollectedItem, CollectedMedia
from .collectors.link import LinkCollector
from .config import Settings
from .db import Database, utc_now
from .prompting import (
    PromptCandidate,
    extract_marked_prompt,
    is_prompt_like,
    join_prompt_variants,
    normalize_prompt,
    prompt_candidates_from_post,
)
from .reverse_prompt import ReversePromptEngine


def safe_slug(value: str, fallback: str = "reference") -> str:
    value = value.lower().strip()
    value = re.sub(r"https?://", "", value)
    value = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "-", value).strip("-")
    return value[:80] or fallback


class CollectionPipeline:
    def __init__(self, settings: Settings, database: Database):
        self.settings = settings
        self.database = database
        self.reverse_engine = ReversePromptEngine(settings)
        self.http = httpx.Client(
            follow_redirects=True,
            timeout=45,
            headers={"User-Agent": "prompt-gallery-collector/1.0"},
        )

    def collect_all(self) -> dict[str, Any]:
        job_id = self.database.create_job("daily_collect")
        report = {"sources": 0, "new": 0, "duplicates": 0, "failed": []}
        try:
            for source in self.database.list_sources():
                if not source.get("enabled") or source.get("collection_mode") in {"manual", "blocked"}:
                    continue
                report["sources"] += 1
                try:
                    result = self.collect_source(source)
                    report["new"] += result["new"]
                    report["duplicates"] += result["duplicates"]
                except Exception as error:
                    message = f"{source.get('label')}: {error}"
                    report["failed"].append(message)
                    self.database.update_source_state(source["id"], error=str(error))
            status = "completed" if not report["failed"] else "partial"
            summary = f"新增 {report['new']} 条，重复 {report['duplicates']} 条"
            self.database.finish_job(job_id, status=status, summary=summary, detail=report)
            return report
        except Exception as error:
            self.database.finish_job(job_id, status="failed", summary=str(error), detail=report)
            raise

    def collect_source(self, source: dict[str, Any]) -> dict[str, int]:
        collector = collector_for(source["platform"], self.settings)
        items, cursor = collector.collect(source)
        result = {"new": 0, "duplicates": 0}
        for item in reversed(items):
            _, created = self.ingest_item(source, item)
            result["new" if created else "duplicates"] += 1
        self.database.update_source_state(source["id"], cursor=cursor, error=None)
        return result

    def ingest_item(self, source: dict[str, Any] | None, item: CollectedItem) -> tuple[dict[str, Any], bool]:
        index_path = self.settings.repo_root / "index.html"
        if index_path.exists():
            public_source = index_path.read_text(encoding="utf-8")
            if item.canonical_url in public_source or (
                item.external_id and item.external_id in public_source
            ):
                return {"canonical_url": item.canonical_url, "status": "already_published"}, False
        category = classify_by_keywords(item.title, item.source_text, " ".join(item.thread_texts))
        base = {
            "id": str(uuid.uuid4()),
            "source_id": source.get("id") if source else None,
            "platform": item.platform,
            "canonical_url": item.canonical_url,
            "external_id": item.external_id,
            "author": item.author,
            "title": item.title,
            "source_text": item.source_text,
            "prompt_kind": "pending",
            "prompt_status": "pending",
            "category_id": category.id,
            "category_label": category.label,
            "status": "pending",
            "rights_status": self._rights_status(item.platform),
            "source_published_at": item.published_at,
            "collected_at": utc_now(),
            "metadata": item.metadata,
        }
        candidate, created = self.database.upsert_candidate(base)
        if not created:
            return candidate, False

        try:
            media_records = self._prepare_media(candidate["id"], item.media)
            self.database.replace_media(candidate["id"], media_records)
            prompt_variants, prompt_kind, prompt_status, score, notes = self._resolve_prompts(
                item, media_records
            )
            active_prompt = join_prompt_variants(prompt_variants)
            category = classify_by_keywords(item.title, item.source_text, active_prompt)
            status = "prompt_ready" if prompt_status == "verified_source" else "needs_review"
            if not active_prompt:
                status = "pending"
            candidate = self.database.update_candidate(
                candidate["id"],
                {
                    "prompt_variants_json": prompt_variants,
                    "active_prompt": active_prompt,
                    "prompt_kind": prompt_kind,
                    "prompt_status": prompt_status,
                    "category_id": category.id,
                    "category_label": category.label,
                    "status": status,
                    "quality_score": score,
                    "quality_notes": notes,
                },
                action="collect",
            )
            return candidate, True
        except Exception as error:
            self.database.update_candidate(
                candidate["id"],
                {"status": "failed", "quality_notes": str(error)},
                action="collect_failed",
            )
            raise

    @staticmethod
    def _rights_status(platform: str) -> str:
        if platform == "unsplash":
            return "attributed_hotlink"
        if platform == "artstation":
            return "manual_rights_and_noai_check"
        return "source_trace_required"

    def _prepare_media(self, candidate_id: str, media_items: list[CollectedMedia]) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        folder = self.settings.spool_path / candidate_id
        folder.mkdir(parents=True, exist_ok=True)
        for ordinal, media in enumerate(media_items, start=1):
            record: dict[str, Any] = {
                "ordinal": ordinal,
                "source_url": media.source_url,
                "alt_text": media.alt_text,
                "width": media.width,
                "height": media.height,
                "media_policy": media.media_policy,
                "attribution": media.attribution,
            }
            if media.media_policy == "hotlink":
                output.append(record)
                continue
            if media.source_url.startswith("file://"):
                local_source = Path(media.source_url.removeprefix("file://"))
                content = local_source.read_bytes()
                content_type = mimetypes.guess_type(local_source.name)[0] or "image/jpeg"
                source_suffix = local_source.suffix
            else:
                response = self.http.get(media.source_url)
                response.raise_for_status()
                content = response.content
                content_type = response.headers.get("content-type", "").split(";", 1)[0]
                source_suffix = Path(media.source_url).suffix
            extension = mimetypes.guess_extension(content_type) or source_suffix or ".jpg"
            if extension == ".jpe":
                extension = ".jpg"
            original_path = folder / f"source-{ordinal:02d}{extension}"
            original_path.write_bytes(content)
            digest = hashlib.sha256(content).hexdigest()
            with Image.open(original_path) as image:
                image = ImageOps.exif_transpose(image)
                width, height = image.size
                full_path = folder / f"full-{ordinal:02d}.jpg"
                preview_path = folder / f"preview-{ordinal:02d}.jpg"
                rgb = image.convert("RGB")
                rgb.save(full_path, "JPEG", quality=95, optimize=True)
                preview = rgb.copy()
                preview.thumbnail((1200, 1200), Image.Resampling.LANCZOS)
                preview.save(preview_path, "JPEG", quality=88, optimize=True)
            record.update(
                {
                    "local_path": str(full_path),
                    "preview_path": str(preview_path),
                    "width": width,
                    "height": height,
                    "sha256": digest,
                }
            )
            output.append(record)
        return output

    def _resolve_prompts(
        self, item: CollectedItem, media_records: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], str, str, int | None, str]:
        media_payload = [{"alt_text": media.alt_text} for media in item.media]
        candidates = prompt_candidates_from_post(item.source_text, media_payload)
        if not candidates:
            for thread_text in item.thread_texts:
                marked = extract_marked_prompt(thread_text)
                value = marked if is_prompt_like(marked) else normalize_prompt(thread_text)
                if is_prompt_like(value):
                    candidates.append(PromptCandidate(value, "author_thread", None, True))
                    break

        if candidates:
            variants = [
                {
                    "image_ordinal": candidate.image_ordinal,
                    "text": candidate.text,
                    "source": candidate.source,
                    "verified": candidate.verified,
                }
                for candidate in candidates
            ]
            return variants, "original", "verified_source", None, "已从 ALT、主帖或作者线程核验。"

        if not self.settings.openai_api_key:
            return [], "pending", "missing_api_key", None, "未发现原始提示词，需配置 OPENAI_API_KEY 后反推。"

        variants = []
        scores = []
        notes = []
        for index, media in enumerate(media_records, start=1):
            image = media.get("local_path") or media["source_url"]
            result = self.reverse_engine.reverse(image)
            if not result.prompt:
                continue
            variants.append(
                {
                    "image_ordinal": index,
                    "text": result.prompt,
                    "source": "reverse_prompt",
                    "verified": False,
                    "quality_score": result.score,
                    "render_path": result.render_path,
                }
            )
            if result.score is not None:
                scores.append(result.score)
            if result.notes:
                notes.append(f"图片 {index}: {result.notes}")
        score = min(scores) if scores else None
        return variants, "reverse", "ai_review_required", score, "\n".join(notes)

    def ingest_manual(
        self,
        *,
        platform: str,
        canonical_url: str,
        author: str,
        title: str,
        source_text: str,
        media_urls: list[str],
        prompt: str = "",
        rights_confirmed: bool = False,
    ) -> tuple[dict[str, Any], bool]:
        media = [CollectedMedia(source_url=url) for url in media_urls if url]
        if not media:
            raise ValueError("At least one image URL is required")
        item = CollectedItem(
            platform=platform,
            canonical_url=canonical_url,
            external_id=safe_slug(canonical_url, str(uuid.uuid4())),
            author=author,
            title=title,
            source_text=f"{source_text}\n\nPrompt:\n{prompt}" if prompt else source_text,
            published_at=None,
            media=media,
            metadata={"manual": True, "rights_confirmed": rights_confirmed},
        )
        if platform == "artstation" and not rights_confirmed:
            raise ValueError("ArtStation images require rights and NoAI confirmation before AI processing")
        return self.ingest_item(None, item)

    def ingest_url(self, url: str, *, rights_confirmed: bool = False) -> tuple[dict[str, Any], bool]:
        collector = LinkCollector(
            x_bearer_token=self.settings.x_bearer_token,
            wallhaven_api_key=self.settings.wallhaven_api_key,
            unsplash_access_key=self.settings.unsplash_access_key,
        )
        item = collector.collect(url)
        if item.platform == "artstation" and not rights_confirmed:
            raise ValueError("ArtStation images require rights and NoAI confirmation before AI processing")
        return self.ingest_item(None, item)
