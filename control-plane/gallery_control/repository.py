from __future__ import annotations

import html
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .categories import CATEGORY_BY_ID
from .config import Settings
from .db import Database, utc_now
from .pipeline import safe_slug


ARTICLE_START_RE = re.compile(r"<article\b[^>]*>", re.I)
SECTION_START_RE = re.compile(r'<section\s+id="([^"]+)"\s+class="category"[^>]*>', re.I)


def _text(fragment: str) -> str:
    fragment = re.sub(r"<br\s*/?>", "\n", fragment, flags=re.I)
    return html.unescape(re.sub(r"<[^>]+>", "", fragment)).strip()


def _match(pattern: str, text: str, default: str = "") -> str:
    match = re.search(pattern, text, re.S | re.I)
    return _text(match.group(1)) if match else default


@dataclass(frozen=True)
class EntryBlock:
    id: str
    start: int
    end: int
    start_tag: str
    block: str
    section_id: str


class GalleryRepository:
    def __init__(self, settings: Settings, database: Database | None = None):
        self.settings = settings
        self.database = database
        self.index_path = settings.repo_root / "index.html"
        self.blanc_path = settings.repo_root / "prom-gallery-style.html"
        self.archive_path = settings.repo_root / "control-plane" / "data" / "deleted-entries"

    def _read(self) -> str:
        return self.index_path.read_text(encoding="utf-8")

    def _write(self, source: str) -> None:
        self.index_path.write_text(source, encoding="utf-8")

    @staticmethod
    def _section_id_at(source: str, position: int) -> str:
        matches = list(SECTION_START_RE.finditer(source, 0, position))
        return matches[-1].group(1) if matches else "uncategorized"

    @classmethod
    def scan_blocks(cls, source: str) -> list[EntryBlock]:
        blocks: list[EntryBlock] = []
        anonymous_index = 0
        for match in ARTICLE_START_RE.finditer(source):
            start_tag = match.group(0)
            class_match = re.search(r'class="([^"]*)"', start_tag, re.I)
            classes = class_match.group(1).split() if class_match else []
            if "entry" not in classes or "submission-preview" in classes or "lightbox-card" in classes:
                continue
            id_match = re.search(r'id="([^"]+)"', start_tag, re.I)
            if id_match:
                entry_id = id_match.group(1)
            else:
                anonymous_index += 1
                entry_id = f"anonymous-entry-{anonymous_index:03d}"
            close = source.find("</article>", match.end())
            if close == -1:
                continue
            end = close + len("</article>")
            blocks.append(
                EntryBlock(
                    id=entry_id,
                    start=match.start(),
                    end=end,
                    start_tag=start_tag,
                    block=source[match.start():end],
                    section_id=cls._section_id_at(source, match.start()),
                )
            )
        return blocks

    def list_entries(self, include_hidden: bool = True) -> list[dict[str, Any]]:
        source = self._read()
        entries = []
        for item in self.scan_blocks(source):
            hidden = bool(re.search(r"\shidden(?:\s|=|>)", item.start_tag, re.I))
            if hidden and not include_hidden:
                continue
            image_tags = re.findall(r"<img\b([^>]*)>", item.block, re.S | re.I)
            images = []
            for tag in image_tags:
                src = _match(r'src="([^"]+)"', tag)
                if not src:
                    continue
                images.append(
                    {
                        "src": src,
                        "full": _match(r'data-full="([^"]+)"', tag, src),
                        "alt": _match(r'alt="([^"]*)"', tag),
                    }
                )
            prompt_parts = [
                _text(value)
                for value in re.findall(
                    r'<pre[^>]*class="[^"]*prompt[^"]*"[^>]*>\s*<code>(.*?)</code>\s*</pre>',
                    item.block,
                    re.S | re.I,
                )
            ]
            source_url = _match(r'data-source-url="([^"]+)"', item.start_tag)
            if not source_url:
                source_url = _match(r'<a\s+href="(https?://[^"]+)"', item.block)
            entries.append(
                {
                    "id": item.id,
                    "entry_no": _match(r'data-entry-no="([^"]+)"', item.start_tag)
                    or _match(r'<span class="entry-no">(.*?)</span>', item.block),
                    "title": _match(r'<h3 class="entry-title">(.*?)</h3>', item.block, "未命名素材"),
                    "title_en": _match(r'<p class="title-en">(.*?)</p>', item.block),
                    "section_id": item.section_id,
                    "category": CATEGORY_BY_ID.get(item.section_id).label if item.section_id in CATEGORY_BY_ID else item.section_id,
                    "platform": _match(r'data-source-platform="([^"]+)"', item.start_tag),
                    "source_url": source_url,
                    "prompt": "\n\n".join(part for part in prompt_parts if part),
                    "prompt_label": _match(r'<summary>(.*?)</summary>', item.block),
                    "images": images,
                    "hidden": hidden,
                }
            )
        return entries

    def _find_block(self, source: str, entry_id: str) -> EntryBlock:
        for block in self.scan_blocks(source):
            if block.id == entry_id:
                return block
        raise KeyError(f"Gallery entry not found: {entry_id}")

    def set_hidden(self, entry_id: str, hidden: bool) -> None:
        source = self._read()
        block = self._find_block(source, entry_id)
        start_tag = block.start_tag
        if hidden:
            if not re.search(r"\shidden(?:\s|=|>)", start_tag, re.I):
                start_tag = start_tag[:-1] + " hidden>"
        else:
            start_tag = re.sub(r'\s+hidden(?:="[^"]*")?', "", start_tag, flags=re.I)
        source = source[: block.start] + start_tag + source[block.start + len(block.start_tag) :]
        self._write(self.refresh_counts(source))

    def update_prompt(self, entry_id: str, prompt: str, label: str | None = None) -> None:
        source = self._read()
        block = self._find_block(source, entry_id)
        escaped = html.escape(prompt.strip(), quote=False)
        updated, count = re.subn(
            r'(<pre[^>]*class="[^"]*prompt[^"]*"[^>]*>\s*<code>).*?(</code>\s*</pre>)',
            lambda match: match.group(1) + escaped + match.group(2),
            block.block,
            count=1,
            flags=re.S | re.I,
        )
        if not count:
            raise ValueError(f"Entry {entry_id} does not contain a prompt block")
        if label:
            updated = re.sub(
                r'(<details[^>]*class="[^"]*prompt-details[^"]*"[^>]*>\s*<summary>).*?(</summary>)',
                lambda match: match.group(1) + html.escape(label) + match.group(2),
                updated,
                count=1,
                flags=re.S | re.I,
            )
        source = source[: block.start] + updated + source[block.end :]
        self._write(self.refresh_counts(source))

    def update_title(self, entry_id: str, title: str, title_en: str | None = None) -> None:
        source = self._read()
        block = self._find_block(source, entry_id)
        updated = re.sub(
            r'(<h3 class="entry-title">).*?(</h3>)',
            lambda match: match.group(1) + html.escape(title.strip()) + match.group(2),
            block.block,
            count=1,
            flags=re.S | re.I,
        )
        if title_en is not None:
            updated = re.sub(
                r'(<p class="title-en">).*?(</p>)',
                lambda match: match.group(1) + html.escape(title_en.strip()) + match.group(2),
                updated,
                count=1,
                flags=re.S | re.I,
            )
        source = source[: block.start] + updated + source[block.end :]
        self._write(source)

    def move_entry(self, entry_id: str, target_section_id: str) -> None:
        if target_section_id not in CATEGORY_BY_ID:
            raise ValueError(f"Unknown category: {target_section_id}")
        source = self._read()
        block = self._find_block(source, entry_id)
        category = CATEGORY_BY_ID[target_section_id]
        updated = re.sub(
            r'(<span class="badge">).*?(</span>)',
            lambda match: match.group(1) + html.escape(f"{category.label} / {category.english}") + match.group(2),
            block.block,
            count=1,
            flags=re.S | re.I,
        )
        updated = re.sub(
            r'(<div class="tag-list">\s*<span class="tag">).*?(</span>)',
            lambda match: match.group(1) + html.escape(category.label) + match.group(2),
            updated,
            count=1,
            flags=re.S | re.I,
        )
        source = source[: block.start] + source[block.end :]
        section_match = re.search(
            rf'<section\s+id="{re.escape(target_section_id)}"\s+class="category"[^>]*>', source, re.I
        )
        if not section_match:
            raise ValueError(f"Target section missing: {target_section_id}")
        section_end = source.find("</section>", section_match.end())
        insert_at = source.rfind("</div>", section_match.end(), section_end)
        if insert_at == -1:
            insert_at = section_end
        source = source[:insert_at] + updated + "\n" + source[insert_at:]
        self._write(self.refresh_counts(source))

    def delete_entry(self, entry_id: str) -> None:
        source = self._read()
        block = self._find_block(source, entry_id)
        self.archive_path.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        (self.archive_path / f"{timestamp}-{safe_slug(entry_id)}.html").write_text(
            block.block, encoding="utf-8"
        )
        source = source[: block.start] + source[block.end :]
        self._write(self.refresh_counts(source))

    def publish_candidates(self, candidate_ids: list[str]) -> list[str]:
        if not self.database:
            raise RuntimeError("Database is required to publish candidates")
        source = self._read()
        published_ids: list[str] = []
        current_numbers = [
            int(match.group(1))
            for match in re.finditer(r'data-entry-no="S(\d+)"', source, re.I)
        ]
        next_number = max(current_numbers, default=0) + 1

        for candidate_id in candidate_ids:
            candidate = self.database.get_candidate(candidate_id)
            if not candidate:
                raise KeyError(candidate_id)
            if candidate.get("status") not in {"approved", "prompt_ready", "needs_review"}:
                raise ValueError(f"Candidate {candidate_id} is not ready to publish")
            if not candidate.get("active_prompt"):
                raise ValueError(f"Candidate {candidate_id} has no active prompt")
            category_id = candidate.get("category_id")
            if category_id not in CATEGORY_BY_ID:
                raise ValueError(f"Candidate {candidate_id} has no valid category")

            entry_no = f"S{next_number}"
            next_number += 1
            metadata = candidate.get("metadata") or {}
            slug = safe_slug(metadata.get("asset_slug", ""), "")
            if not slug:
                author_slug = safe_slug(candidate.get("author", "source"), "source")
                title_slug = safe_slug(candidate.get("title", "reference"), "reference")
                slug = f"{author_slug}-{title_slug}"[:110].strip("-")
            entry_id = f"supplement-{slug}"
            suffix = 2
            while f'id="{entry_id}"' in source:
                entry_id = f"supplement-{slug}-{suffix}"
                suffix += 1
            article = self._candidate_article(candidate, entry_id, entry_no, slug)
            source = self._insert_article(source, category_id, article)
            self.database.update_candidate(
                candidate_id,
                {
                    "status": "published",
                    "published_entry_id": entry_id,
                    "reviewed_at": candidate.get("reviewed_at") or utc_now(),
                },
                action="publish",
            )
            published_ids.append(entry_id)

        self._write(self.refresh_counts(source))
        return published_ids

    def _candidate_article(self, candidate: dict[str, Any], entry_id: str, entry_no: str, slug: str) -> str:
        category = CATEGORY_BY_ID[candidate["category_id"]]
        platform = candidate.get("platform", "source")
        source_url = candidate["canonical_url"]
        added_at = utc_now()
        figures = []
        destination_full = self.settings.repo_root / "assets" / "full" / "supplements" / slug
        destination_preview = self.settings.repo_root / "assets" / "images" / "supplements" / slug
        local_media = [media for media in candidate.get("media", []) if media]
        for index, media in enumerate(local_media, start=1):
            width = media.get("width") or ""
            height = media.get("height") or ""
            if media.get("media_policy") == "hotlink":
                src = full = media["source_url"]
            else:
                destination_full.mkdir(parents=True, exist_ok=True)
                destination_preview.mkdir(parents=True, exist_ok=True)
                full_name = f"{slug}-{index:02d}.jpg"
                preview_name = f"{slug}-{index:02d}.jpg"
                shutil.copy2(media["local_path"], destination_full / full_name)
                shutil.copy2(media["preview_path"], destination_preview / preview_name)
                full = f"assets/full/supplements/{slug}/{full_name}"
                src = f"assets/images/supplements/{slug}/{preview_name}"
            alt = f"参考图：{candidate.get('title') or '提示词素材'} {index:02d}"
            size_attrs = ""
            if width and height:
                size_attrs = f' width="{int(width)}" height="{int(height)}"'
            figures.append(
                "\n".join(
                    [
                        '<figure class="figure">',
                        f'<img src="{html.escape(src, quote=True)}" data-full="{html.escape(full, quote=True)}" alt="{html.escape(alt, quote=True)}" loading="lazy" decoding="async"{size_attrs}>',
                        f'<figcaption><span class="caption-zh">{html.escape(alt)}</span><br><span>{html.escape(candidate.get("author") or platform)}</span></figcaption>',
                        "</figure>",
                    ]
                )
            )
        prompt_label = (
            "完整提示词 / Original Prompt"
            if candidate.get("prompt_kind") == "original"
            else "反推提示词 / Reverse Prompt"
        )
        tags = [category.label, platform.upper(), "自动采集", "来源可追溯"]
        prompt_source = {
            "original": "原帖 ALT、正文或作者线程",
            "reverse": "图片反推，经人工审核",
        }.get(candidate.get("prompt_kind"), "人工审核")
        title = candidate.get("title") or "未命名提示词参考"
        metadata = candidate.get("metadata") or {}
        title_en = metadata.get("title_en") or f"{platform.upper()} visual prompt reference"
        source_date = candidate.get("source_published_at") or "日期未提供"
        return f'''<article id="{html.escape(entry_id, quote=True)}" class="entry supplement-entry" data-entry-no="{entry_no}" data-source-platform="{html.escape(platform, quote=True)}" data-source-url="{html.escape(source_url, quote=True)}" data-added-at="{added_at}" data-prompt-kind="{html.escape(candidate.get("prompt_kind", ""), quote=True)}">
<div class="entry-head">
<div class="title-stack"><span class="entry-no">Supplement {entry_no[1:]}</span><h3 class="entry-title">{html.escape(title)}</h3><p class="title-en">{html.escape(title_en)}</p></div>
<span class="badge">{html.escape(category.label)} / {html.escape(category.english)}</span>
</div>
<div class="tag-list">{''.join(f'<span class="tag">{html.escape(tag)}</span>' for tag in tags)}</div>
<div class="images">{''.join(figures)}</div>
<p class="kv"><strong>来源作者：</strong>{html.escape(candidate.get("author") or "未署名")}</p>
<p class="kv"><strong>来源日期：</strong>{html.escape(source_date)}</p>
<p class="kv"><strong>Prompt 来源：</strong>{html.escape(prompt_source)}</p>
<p class="kv source-trace"><strong>来源追溯：</strong><a href="{html.escape(source_url, quote=True)}" target="_blank" rel="noopener noreferrer">{html.escape(platform.upper())} 原始页面</a></p>
<details class="prompt-details"><summary>{html.escape(prompt_label)}</summary>
<pre class="prompt"><code>{html.escape(candidate["active_prompt"], quote=False)}</code></pre>
</details>
</article>'''

    @staticmethod
    def _insert_article(source: str, section_id: str, article: str) -> str:
        section_match = re.search(
            rf'<section\s+id="{re.escape(section_id)}"\s+class="category"[^>]*>', source, re.I
        )
        if not section_match:
            raise ValueError(f"Target section missing: {section_id}")
        section_end = source.find("</section>", section_match.end())
        insert_at = source.rfind("</div>", section_match.end(), section_end)
        if insert_at == -1:
            insert_at = section_end
        return source[:insert_at] + article + "\n" + source[insert_at:]

    def refresh_counts(self, source: str) -> str:
        visible_blocks = [
            block
            for block in self.scan_blocks(source)
            if not re.search(r"\shidden(?:\s|=|>)", block.start_tag, re.I)
        ]
        image_count = sum(len(re.findall(r"<img\b", block.block, re.I)) for block in visible_blocks)
        prompt_count = 0
        for block in visible_blocks:
            label = _match(r"<summary>(.*?)</summary>", block.block)
            prompt = _match(
                r'<pre[^>]*class="[^"]*prompt[^"]*"[^>]*>\s*<code>(.*?)</code>\s*</pre>',
                block.block,
            )
            if prompt and "Source Text" not in label and "摘要" not in label:
                prompt_count += 1
        card_count = len(visible_blocks)

        source = re.sub(
            r'(<div class="stat"><strong>)\d+(</strong>完整 prompt 条目</div>)',
            rf"\g<1>{prompt_count}\g<2>", source, count=1,
        )
        source = re.sub(
            r'(<div class="stat"><strong>)\d+(</strong>图片引用</div>)',
            rf"\g<1>{image_count}\g<2>", source, count=1,
        )
        source = re.sub(
            r'(<div class="stat"><strong>)\d+(</strong>卡片条目</div>)',
            rf"\g<1>{card_count}\g<2>", source, count=1,
        )

        grouped: dict[str, list[EntryBlock]] = {}
        for block in visible_blocks:
            grouped.setdefault(block.section_id, []).append(block)
        for section_id, blocks in grouped.items():
            if section_id not in CATEGORY_BY_ID:
                continue
            supplements = sum(
                1 for block in blocks if re.search(r'data-entry-no="S\d+"', block.start_tag, re.I)
            )
            base = len(blocks) - supplements
            count_text = f"{base} 条" + (f" + {supplements} 补充" if supplements else "")
            nav_pattern = re.compile(
                rf'(<a href="#{re.escape(section_id)}"[^>]*>.*?<small>)(.*?)(</small>)',
                re.S | re.I,
            )
            nav_match = nav_pattern.search(source)
            if nav_match:
                prefix = re.sub(r"\d+\s*条(?:\s*\+\s*\d+\s*补充)?\s*$", count_text, nav_match.group(2))
                source = source[: nav_match.start(2)] + prefix + source[nav_match.end(2) :]
            section_pattern = re.compile(
                rf'(<section\s+id="{re.escape(section_id)}"\s+class="category"[^>]*>\s*<h2>.*?<span class="meta">)(.*?)(</span>)',
                re.S | re.I,
            )
            section_match = section_pattern.search(source)
            if section_match:
                meta = re.sub(r"\d+\s*条(?:\s*\+\s*\d+\s*补充)?\s*$", count_text, section_match.group(2))
                source = source[: section_match.start(2)] + meta + source[section_match.end(2) :]
        return source

    def build_blanc(self) -> None:
        subprocess.run(
            ["python3", "tools/build_prom_gallery_style.py"],
            cwd=self.settings.repo_root,
            check=True,
        )

    def validate(self) -> dict[str, int]:
        entries = self.list_entries(include_hidden=False)
        ids = [entry["id"] for entry in entries]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate gallery entry IDs found")
        tracked_result = subprocess.run(
            ["git", "ls-files"],
            cwd=self.settings.repo_root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        tracked = set(tracked_result.stdout.splitlines()) if tracked_result.returncode == 0 else set()
        missing = []
        for entry in entries:
            for image in entry["images"]:
                for key in ("src", "full"):
                    path = image[key]
                    if path.startswith(("http://", "https://", "data:")):
                        continue
                    if not (self.settings.repo_root / path).exists() and path not in tracked:
                        missing.append(path)
        if missing:
            raise FileNotFoundError(f"Missing gallery assets: {missing[:8]}")
        return {
            "entries": len(entries),
            "images": sum(len(entry["images"]) for entry in entries),
            "prompts": sum(
                bool(entry["prompt"])
                and "Source Text" not in entry.get("prompt_label", "")
                and "摘要" not in entry.get("prompt_label", "")
                for entry in entries
            ),
        }

    def commit_and_push(self, message: str) -> str | None:
        subprocess.run(
            [
                "git", "add", "--sparse", "index.html", "prom-gallery-style.html",
                "assets/images/supplements", "assets/full/supplements",
            ],
            cwd=self.settings.repo_root,
            check=True,
        )
        diff = subprocess.run(
            ["git", "diff", "--cached", "--quiet"], cwd=self.settings.repo_root, check=False
        )
        if diff.returncode == 0:
            return None
        subprocess.run(["git", "commit", "-m", message], cwd=self.settings.repo_root, check=True)
        sha = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=self.settings.repo_root, text=True
        ).strip()
        if self.settings.git_push_enabled:
            subprocess.run(
                ["git", "push", self.settings.git_remote, self.settings.git_branch],
                cwd=self.settings.repo_root,
                check=True,
            )
        return sha
