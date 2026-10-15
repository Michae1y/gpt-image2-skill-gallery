#!/usr/bin/env python3
from __future__ import annotations

import bisect
import colorsys
from collections import Counter
from datetime import datetime, timezone
import hashlib
import html
import json
import math
import re
import subprocess
from pathlib import Path

try:
    from PIL import Image
except ImportError:  # The control-plane runtime includes Pillow; keep a deterministic fallback.
    Image = None


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "index.html"
OUTPUT = ROOT / "prom-gallery-style.html"
_IMAGE_ADDED_AT_CACHE: dict[str, str] = {}
_GIT_ADDED_AT_BY_PATH: dict[str, str] | None = None
_IMAGE_COLOR_CACHE: dict[str, dict[str, float]] = {}

DESKTOP_GALLERY_COLUMNS = 4
RECENT_GROUP_WINDOW = 16
RECENT_TILE_WEIGHT = 0.35
HARD_VISUAL_FAMILIES = {
    "字体与海报": "graphic",
    "品牌系统与视觉识别": "graphic",
    "UI/UX 界面样机": "graphic",
    "活动与体验设计": "graphic",
    "信息图与图鉴": "diagram",
    "论文配图": "diagram",
    "数据可视化": "diagram",
    "技术插图": "diagram",
    "科学与教育": "diagram",
    "OpenAI Cookbook 官方示例": "diagram",
    "图片编辑接口示例": "graphic",
    "产品与食物": "product",
    "建筑与室内": "space",
    "等距视角": "space",
    "游戏与 HUD": "game",
    "复古与赛博朋克": "game",
    "电影感与动画": "cinematic",
    "电影风格参考": "cinematic",
    "动漫与漫画": "anime",
    "角色设计": "anime",
    "插画": "illustration",
    "水彩": "illustration",
    "水墨与中文风格": "illustration",
    "像素艺术": "illustration",
    "美术绘画": "illustration",
    "更多插画风格": "illustration",
    "纹身设计": "illustration",
    "屏幕摄影": "screen",
}
RELATED_VISUAL_FAMILIES = {
    frozenset(pair)
    for pair in (
        ("portrait", "beauty"),
        ("portrait", "lifestyle"),
        ("portrait", "cinematic"),
        ("beauty", "product"),
        ("illustration", "anime"),
        ("illustration", "graphic"),
        ("graphic", "diagram"),
        ("graphic", "product"),
        ("diagram", "space"),
        ("space", "product"),
        ("space", "cinematic"),
        ("game", "cinematic"),
        ("game", "anime"),
        ("photo-scene", "cinematic"),
        ("photo-scene", "space"),
        ("screen", "graphic"),
        ("screen", "photo-scene"),
    )
}
VISUAL_MEDIUM_BY_FAMILY = {
    "portrait": "photo",
    "beauty": "photo",
    "lifestyle": "photo",
    "photo-scene": "photo",
    "graphic": "design",
    "diagram": "design",
    "product": "design",
    "anime": "art",
    "illustration": "art",
    "cinematic": "scene",
    "game": "scene",
    "space": "scene",
    "screen": "scene",
    "other": "other",
}


def attrs_from(tag: str) -> dict[str, str]:
    return {k: html.unescape(v) for k, v in re.findall(r'([:\w-]+)="([^"]*)"', tag)}


def text_from(fragment: str) -> str:
    fragment = re.sub(r"<br\s*/?>", "\n", fragment, flags=re.I)
    fragment = re.sub(r"<[^>]+>", "", fragment)
    return html.unescape(fragment).strip()


def one_line(fragment: str) -> str:
    return re.sub(r"\s+", " ", text_from(fragment)).strip()


def first_match(pattern: str, text: str, default: str = "") -> str:
    match = re.search(pattern, text, re.S)
    return one_line(match.group(1)) if match else default


def image_added_at(path: str) -> str:
    if path in _IMAGE_ADDED_AT_CACHE:
        return _IMAGE_ADDED_AT_CACHE[path]
    added_at = ""
    if path and not path.startswith(("http://", "https://", "data:")):
        added_at = git_added_at_by_path().get(path, "")
        if not added_at:
            local_path = ROOT / path
            if local_path.exists():
                mtime = datetime.fromtimestamp(local_path.stat().st_mtime, timezone.utc)
                added_at = mtime.isoformat()
    _IMAGE_ADDED_AT_CACHE[path] = added_at
    return added_at


def git_added_at_by_path() -> dict[str, str]:
    global _GIT_ADDED_AT_BY_PATH
    if _GIT_ADDED_AT_BY_PATH is not None:
        return _GIT_ADDED_AT_BY_PATH
    added: dict[str, str] = {}
    result = subprocess.run(
        ["git", "log", "--diff-filter=A", "--name-only", "--format=commit:%cI", "--", "assets"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    current_date = ""
    for raw_line in result.stdout.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("commit:"):
            current_date = line.removeprefix("commit:")
            continue
        if current_date and line not in added:
            added[line] = current_date
    _GIT_ADDED_AT_BY_PATH = added
    return added


def timestamp_for_sort(value: str) -> float:
    if not value:
        return 0.0
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def entry_number_for_sort(entry_no: str) -> int:
    match = re.search(r"\d+", entry_no or "")
    return int(match.group(0)) if match else 0


def stable_fraction(value: str) -> float:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
    return int(digest, 16) / float(0xFFFFFFFFFFFF)


def visual_family(tile: dict) -> str:
    category = tile["category"]
    if category in HARD_VISUAL_FAMILIES:
        return HARD_VISUAL_FAMILIES[category]

    text = " ".join(
        [category, tile["title"], tile["alt"], *tile.get("_tags", [])]
    ).lower()
    if category == "时尚大片":
        if re.search(r"字体|视觉系统|typography|海报", text, re.I):
            return "graphic"
        return "portrait"
    if category == "美妆与生活方式":
        product = re.search(r"产品|护肤品|香氛|包装|product|skincare|fragrance", text, re.I)
        person = re.search(r"人像|肖像|自拍|portrait|面孔|贴脸", text, re.I)
        return "product" if product and not person else "beauty"
    if category == "摄影":
        if re.search(r"幼儿|儿童|宝宝|家庭|生活方式|生活感|日常|抓拍|candid|lifestyle", text, re.I):
            return "lifestyle"
        if re.search(r"美妆|beauty|makeup", text, re.I):
            return "beauty"
        if re.search(
            r"人像|肖像|写真|自拍|模特|portrait|selfie|女孩|女性|少女|比基尼|泳装|婚礼|白裙|服装|影棚",
            text,
            re.I,
        ):
            return "portrait"
        if re.search(r"电影感|全景|场景|landscape|cinematic", text, re.I):
            return "cinematic"
        return "photo-scene"
    return "other"


def image_color_features(path: str) -> dict[str, float]:
    if path in _IMAGE_COLOR_CACHE:
        return _IMAGE_COLOR_CACHE[path]

    fallback = {
        "hue": stable_fraction(path),
        "lum": 0.5,
        "sat": 0.2,
        "contrast": 0.2,
    }
    local_path = ROOT / path
    if Image is None or not local_path.exists():
        _IMAGE_COLOR_CACHE[path] = fallback
        return fallback

    try:
        with Image.open(local_path) as source:
            sample = source.convert("RGB")
            sample.thumbnail((48, 48))
            pixels = list(sample.getdata())
    except OSError:
        _IMAGE_COLOR_CACHE[path] = fallback
        return fallback

    hue_x = 0.0
    hue_y = 0.0
    hue_weight = 0.0
    luminances = []
    saturations = []
    for red, green, blue in pixels:
        red_f, green_f, blue_f = red / 255, green / 255, blue / 255
        hue, saturation, _ = colorsys.rgb_to_hsv(red_f, green_f, blue_f)
        luminance = 0.2126 * red_f + 0.7152 * green_f + 0.0722 * blue_f
        luminances.append(luminance)
        saturations.append(saturation)
        if saturation > 0.06 and 0.03 < luminance < 0.97:
            weight = saturation * (0.45 + 0.55 * (1 - abs(luminance - 0.5) * 2))
            hue_x += math.cos(hue * math.tau) * weight
            hue_y += math.sin(hue * math.tau) * weight
            hue_weight += weight

    luminance = sum(luminances) / len(luminances)
    features = {
        "hue": (math.atan2(hue_y, hue_x) / math.tau) % 1 if hue_weight else 0.0,
        "lum": luminance,
        "sat": sum(saturations) / len(saturations),
        "contrast": math.sqrt(
            sum((value - luminance) ** 2 for value in luminances) / len(luminances)
        ),
    }
    _IMAGE_COLOR_CACHE[path] = features
    return features


def tile_visual_features(tile: dict) -> dict:
    try:
        width = max(float(tile["width"]), 1.0)
        height = max(float(tile["height"]), 1.0)
    except (TypeError, ValueError):
        width = height = 1.0
    return {
        **image_color_features(tile["src"]),
        "aspect": height / width,
        "family": visual_family(tile),
        "entry": tile["entryIndex"],
        "jitter": stable_fraction(tile["tileId"]),
    }


def visual_distance(first: dict, second: dict, family_weight: float = 1.0) -> float:
    hue_distance = abs(first["hue"] - second["hue"])
    hue_distance = min(hue_distance, 1 - hue_distance) * 2
    hue_distance *= 0.3 + math.sqrt(first["sat"] * second["sat"])

    if first["family"] == second["family"]:
        family_distance = 0.0
    elif frozenset((first["family"], second["family"])) in RELATED_VISUAL_FAMILIES:
        family_distance = 0.5
    else:
        family_distance = 1.1

    return (
        hue_distance * 1.1
        + abs(first["lum"] - second["lum"]) * 1.8
        + abs(first["sat"] - second["sat"]) * 0.7
        + abs(first["contrast"] - second["contrast"]) * 0.45
        + abs(math.log(max(first["aspect"], 0.1) / max(second["aspect"], 0.1))) * 0.4
        + family_distance * family_weight
    )


def group_centroid(group: list[dict]) -> dict:
    features = [tile["_visual"] for tile in group]
    hue_x = sum(
        math.cos(item["hue"] * math.tau) * max(item["sat"], 0.05)
        for item in features
    )
    hue_y = sum(
        math.sin(item["hue"] * math.tau) * max(item["sat"], 0.05)
        for item in features
    )
    families = {item["family"] for item in features}
    family = max(
        sorted(families),
        key=lambda candidate: (
            sum(item["family"] == candidate for item in features),
            candidate,
        ),
    )
    return {
        "hue": (math.atan2(hue_y, hue_x) / math.tau) % 1,
        "lum": sum(item["lum"] for item in features) / len(features),
        "sat": sum(item["sat"] for item in features) / len(features),
        "contrast": sum(item["contrast"] for item in features) / len(features),
        "aspect": sum(item["aspect"] for item in features) / len(features),
        "family": family,
    }


def visual_medium(tile: dict) -> str:
    return VISUAL_MEDIUM_BY_FAMILY.get(tile["_visual"]["family"], "other")


def make_visual_groups(tiles: list[dict], columns: int) -> tuple[list[list[dict]], dict]:
    """Build palette-matched rows with no more than two tiles from one medium."""
    newest = max(
        tiles,
        key=lambda tile: (
            timestamp_for_sort(tile["imageAddedAt"]),
            entry_number_for_sort(tile["entryNo"]),
        ),
    )
    added_timestamps = [timestamp_for_sort(tile["imageAddedAt"]) for tile in tiles]
    oldest_timestamp = min(added_timestamps)
    recency_span = max(max(added_timestamps) - oldest_timestamp, 1.0)

    def recency(tile: dict) -> float:
        return (
            timestamp_for_sort(tile["imageAddedAt"]) - oldest_timestamp
        ) / recency_span

    pool = tiles[:]
    groups = []
    preferred_anchor = newest

    while pool:
        pool_mediums = Counter(visual_medium(tile) for tile in pool)
        if preferred_anchor in pool:
            anchor = preferred_anchor
            preferred_anchor = None
        else:
            target_medium = max(
                sorted(pool_mediums),
                key=lambda medium: (pool_mediums[medium], medium),
            )
            anchor = max(
                (tile for tile in pool if visual_medium(tile) == target_medium),
                key=lambda tile: (
                    timestamp_for_sort(tile["imageAddedAt"]),
                    entry_number_for_sort(tile["entryNo"]),
                    -tile["_visual"]["jitter"],
                ),
            )

        pool.remove(anchor)
        group = [anchor]
        while pool and len(group) < columns:
            used_entries = {member["entryIndex"] for member in group}
            entry_candidates = [
                tile for tile in pool if tile["entryIndex"] not in used_entries
            ] or pool
            group_mediums = Counter(visual_medium(tile) for tile in group)
            group_families = Counter(tile["_visual"]["family"] for tile in group)
            group_categories = Counter(tile["category"] for tile in group)
            pool_mediums = Counter(visual_medium(tile) for tile in pool)
            candidates = [
                tile
                for tile in entry_candidates
                if group_mediums[visual_medium(tile)] < 2
            ] or entry_candidates

            def candidate_cost(tile: dict) -> float:
                palette = sum(
                    visual_distance(member["_visual"], tile["_visual"], 0.1)
                    for member in group
                ) / len(group)
                medium = visual_medium(tile)
                pressure = pool_mediums[medium] / max(len(pool), 1)
                return (
                    palette
                    + group_mediums[medium] * 0.52
                    + group_families[tile["_visual"]["family"]] * 0.2
                    + group_categories[tile["category"]] * 0.08
                    - pressure * 0.75
                    - recency(tile) * RECENT_TILE_WEIGHT
                    + tile["_visual"]["jitter"] * 0.02
                )

            selected = min(candidates, key=candidate_cost)
            pool.remove(selected)
            group.append(selected)
        groups.append(group)
    return groups, newest


def order_visual_groups(groups: list[list[dict]], newest: dict) -> list[list[dict]]:
    first = next(group for group in groups if newest in group)
    ordered = [first]
    remaining = [group for group in groups if group is not first]

    def group_added_at(group: list[dict]) -> float:
        return max(timestamp_for_sort(tile["imageAddedAt"]) for tile in group)

    while remaining:
        recent_candidates = sorted(
            remaining,
            key=lambda group: (
                -group_added_at(group),
                -max(entry_number_for_sort(tile["entryNo"]) for tile in group),
            ),
        )[:RECENT_GROUP_WINDOW]
        recency_rank = {
            id(group): rank for rank, group in enumerate(recent_candidates)
        }
        previous = group_centroid(ordered[-1])
        previous_entries = {tile["entryIndex"] for tile in ordered[-1]}
        previous_media = {visual_medium(tile) for tile in ordered[-1]}

        def transition_cost(group: list[dict]) -> float:
            current = group_centroid(group)
            current_entries = {tile["entryIndex"] for tile in group}
            current_media = {visual_medium(tile) for tile in group}
            media_union = previous_media | current_media
            media_similarity = len(previous_media & current_media) / max(
                len(media_union), 1
            )
            group_key = "|".join(tile["tileId"] for tile in group)
            return (
                visual_distance(previous, current, 0.06)
                + len(previous_entries & current_entries) * 1.4
                + media_similarity * 0.05
                + recency_rank[id(group)] * 0.025
                + stable_fraction(group_key) * 0.015
            )

        selected = min(recent_candidates, key=transition_cost)
        remaining.remove(selected)
        ordered.append(selected)
    return ordered


def visual_weave_tiles(tiles: list[dict], columns: int = DESKTOP_GALLERY_COLUMNS) -> list[dict]:
    """Return a stable palette-led order with a balanced mix of visual media."""
    if not tiles:
        return []
    for tile in tiles:
        tile["_visual"] = tile_visual_features(tile)
    groups, newest = make_visual_groups(tiles, columns)
    groups = order_visual_groups(groups, newest)
    ordered = [tile for group in groups for tile in group]
    return [
        {key: value for key, value in tile.items() if not key.startswith("_")}
        for tile in ordered
    ]


def parse_entries(source: str) -> tuple[list[dict], list[str]]:
    sections = []
    for match in re.finditer(r'<section\s+id="([^"]+)"\s+class="category"[^>]*>\s*<h2>(.*?)</h2>', source, re.S):
        title = one_line(match.group(2)).split(" / ")[0].strip()
        sections.append((match.start(), match.group(1), title))
    section_positions = [item[0] for item in sections]

    entries = []
    article_re = re.compile(r'<article\b([^>]*)class="([^"]*\bentry\b[^"]*)"([^>]*)>(.*?)</article>', re.S)
    for match in article_re.finditer(source):
        attrs_raw = match.group(1) + " " + match.group(3)
        classes = match.group(2)
        block = match.group(4)
        if "submission-preview" in classes or "lightbox-card" in classes:
            continue
        if re.search(r"(?:^|\s)hidden(?:\s|=|$)", attrs_raw, re.I):
            continue
        image_tags = list(re.finditer(r"<img\b([^>]*)>", block, re.S))
        if not image_tags:
            continue

        article_attrs = attrs_from("<article " + attrs_raw + ">")
        entry_id = article_attrs.get("id") or f"extra-{len(entries) + 1:03d}"
        entry_no = article_attrs.get("data-entry-no") or first_match(r'<span class="entry-no">(.*?)</span>', block, "")
        title = first_match(r'<h3 class="entry-title">(.*?)</h3>', block, "")
        title_en = first_match(r'<p class="title-en">(.*?)</p>', block, "")
        if not title:
            title = first_match(r'<span class="caption-zh">(.*?)</span>', block, "未命名素材")
        badge = first_match(r'<span class="badge">(.*?)</span>', block, "")

        idx = bisect.bisect_right(section_positions, match.start()) - 1
        section_id = sections[idx][1] if idx >= 0 else "uncategorized"
        category = sections[idx][2] if idx >= 0 else (badge.split(" / ")[0] if badge else "未分类")
        if badge and " / " in badge:
            category = badge.split(" / ")[0].strip() or category

        tags = [one_line(t) for t in re.findall(r'<span class="tag">(.*?)</span>', block, re.S)]
        kvs = [one_line(p) for p in re.findall(r'<p class="kv">(.*?)</p>', block, re.S)]
        summary_match = re.search(r'<details[^>]*class="[^"]*prompt-details[^"]*"[^>]*>\s*<summary>(.*?)</summary>', block, re.S)
        prompt_label = one_line(summary_match.group(1)) if summary_match else "完整提示词 / Original Prompt"
        prompt_is_complete = bool(prompt_label and "Source Text" not in prompt_label and "摘要" not in prompt_label)
        prompt_match = re.search(r'<pre[^>]*class="[^"]*prompt[^"]*"[^>]*>\s*<code>(.*?)</code>\s*</pre>', block, re.S)
        prompt = text_from(prompt_match.group(1)) if prompt_match else ""

        source_url = ""
        source_match = re.search(r'<a href="(https?://[^"]+)"[^>]*>', block)
        if source_match:
            source_url = html.unescape(source_match.group(1))
        source_url = article_attrs.get("data-source-url") or source_url
        source_platform = article_attrs.get("data-source-platform", "")
        added_at = article_attrs.get("data-added-at", "")

        images = []
        for image_match in image_tags:
            img_attrs = attrs_from("<img " + image_match.group(1) + ">")
            src = img_attrs.get("src", "")
            if not src:
                continue
            caption = ""
            fig_start = block.rfind("<figure", 0, image_match.start())
            fig_end = block.find("</figure>", image_match.end())
            if fig_start != -1 and fig_end != -1:
                figure = block[fig_start:fig_end]
                caption = one_line(figure)
            images.append(
                {
                    "src": src,
                    "full": img_attrs.get("data-full") or src,
                    "alt": img_attrs.get("alt") or title,
                    "width": img_attrs.get("width") or "",
                    "height": img_attrs.get("height") or "",
                    "caption": caption,
                }
            )
        if not images:
            continue

        entries.append(
            {
                "id": entry_id,
                "entryNo": entry_no,
                "title": title,
                "titleEn": title_en,
                "category": category,
                "sectionId": section_id,
                "badge": badge,
                "tags": tags[:8],
                "kvs": kvs,
                "prompt": prompt,
                "promptLabel": prompt_label,
                "promptIsComplete": prompt_is_complete,
                "sourceUrl": source_url,
                "sourcePlatform": source_platform,
                "addedAt": added_at,
                "images": images,
            }
        )

    categories = []
    seen = set()
    for entry in entries:
        category = entry["category"]
        if category and category not in seen:
            seen.add(category)
            categories.append(category)
    return entries, categories


def make_tiles(entries: list[dict]) -> list[dict]:
    tiles = []
    for entry_index, entry in enumerate(entries):
        for image_index, image in enumerate(entry["images"]):
            local_src = image["src"]
            tiles.append(
                {
                    "tileId": f"{entry['id']}-{image_index + 1}",
                    "entryIndex": entry_index,
                    "imageIndex": image_index,
                    "src": image["src"],
                    "full": image["full"],
                    "alt": image["alt"],
                    "width": image["width"],
                    "height": image["height"],
                    "category": entry["category"],
                    "title": entry["title"],
                    "entryNo": entry["entryNo"],
                    "_tags": entry["tags"],
                    "imageAddedAt": entry.get("addedAt") or image_added_at(image["src"]),
                    "localAvailable": (ROOT / local_src).exists() if not local_src.startswith(("http://", "https://", "data:")) else True,
                }
            )
    return visual_weave_tiles(tiles)


def build_html(entries: list[dict], categories: list[str]) -> str:
    tiles = make_tiles(entries)
    prompts = sum(1 for entry in entries if entry["prompt"] and entry.get("promptIsComplete"))
    data = {
        "entries": entries,
        "tiles": tiles,
        "categories": categories,
        "stats": {
            "entries": len(entries),
            "tiles": len(tiles),
            "categories": len(categories),
            "prompts": prompts,
        },
    }
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    chips = "\n".join(
        [
            '<button class="chip is-active" type="button" data-filter="all">全部</button>',
            *[
                f'<button class="chip" type="button" data-filter="{html.escape(category)}">{html.escape(category)}</button>'
                for category in categories
            ],
        ]
    )
    tiles_html = "\n".join(
        f'''<button class="tile" type="button" data-tile-index="{i}" data-category="{html.escape(tile["category"])}" aria-label="{html.escape(tile["title"])}">
  <span class="tile-media">
    <img src="{html.escape(tile["src"])}" data-full="{html.escape(tile["full"])}" alt="{html.escape(tile["alt"])}" loading="lazy" decoding="async"{' width="' + html.escape(tile["width"]) + '"' if tile["width"] else ''}{' height="' + html.escape(tile["height"]) + '"' if tile["height"] else ''}>
    <span class="tile-shade"><span>{html.escape(tile["entryNo"] or "REF")}</span></span>
  </span>
</button>'''
        for i, tile in enumerate(tiles)
    )

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Prompt Gallery · 图片精选</title>
<link rel="icon" href="data:,">
<style>
:root {{
  --sky: #b5e4ea;
  --cyan: #d9f1f3;
  --cream: #fcf0d6;
  --ink: #111827;
  --muted: #4b5563;
  --line: rgba(17, 24, 39, 0.12);
  --card: rgba(255, 255, 255, 0.88);
  --peach: #f3b6a7;
  color-scheme: light;
}}
* {{ box-sizing: border-box; }}
html {{ scroll-behavior: smooth; }}
body {{
  margin: 0;
  min-height: 100dvh;
  background: var(--cyan);
  color: var(--ink);
  font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}}
button, input {{ font: inherit; }}
button {{ cursor: pointer; }}
.brand-header {{
  background: var(--sky);
  border-bottom: 1px solid var(--cyan);
}}
.brand-inner {{
  width: min(1280px, calc(100% - 160px));
  min-height: clamp(88px, 10.6vw, 152px);
  margin: 0 auto;
  display: grid;
  grid-template-columns: 140px 1fr 140px;
  align-items: center;
}}
.mark {{
  width: clamp(52px, 7.8vw, 112px);
  height: clamp(52px, 7.8vw, 112px);
  display: grid;
  place-items: center;
  color: var(--ink);
  text-decoration: none;
}}
.mark-box {{
  width: 42%;
  aspect-ratio: 1;
  display: grid;
  place-items: center;
  border: 2px solid var(--ink);
  transform: rotate(45deg);
  letter-spacing: 0;
  font-weight: 800;
}}
.mark-box span {{ transform: rotate(-45deg); font-size: clamp(12px, 1.4vw, 18px); }}
.brand-title {{
  margin: 0;
  text-align: center;
  font-size: clamp(2.45rem, 4vw, 3.55rem);
  line-height: 1;
  letter-spacing: 0.22em;
  font-weight: 760;
}}
.intro {{
  background: var(--cream);
  padding: 36px 0 52px;
  text-align: center;
}}
.intro-inner {{
  width: min(1280px, calc(100% - 192px));
  margin: 0 auto;
}}
.tagline {{
  margin: 0 auto;
  max-width: none;
  color: #374151;
  font-family: Georgia, "Times New Roman", serif;
  font-size: clamp(16px, 1.35vw, 20px);
  line-height: 1.5;
  white-space: nowrap;
}}
.info-grid {{
  margin-top: 26px;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
}}
.info-card {{
  min-height: 94px;
  border: 1px solid var(--cyan);
  border-radius: 18px;
  background: var(--card);
  padding: 18px 20px;
  text-align: left;
  display: flex;
  align-items: center;
  gap: 14px;
  color: var(--muted);
}}
.info-icon {{
  width: 38px;
  height: 38px;
  border-radius: 10px;
  background: var(--cyan);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: var(--ink);
  font-size: 12px;
  font-weight: 800;
  line-height: 1;
  text-align: center;
  flex: 0 0 auto;
}}
.info-card strong {{
  display: block;
  color: var(--ink);
  font-size: 16px;
  line-height: 1.4;
}}
.info-copy {{
  display: block;
  margin-top: 4px;
  font-size: 14px;
  line-height: 1.45;
}}
.controls {{
  margin-top: 32px;
}}
.mode-row, .chip-row {{
  display: flex;
  justify-content: center;
  gap: 8px;
  flex-wrap: wrap;
}}
.mode-row {{
  margin-bottom: 16px;
}}
.mode-pill, .chip {{
  border: 0;
  border-radius: 999px;
  transition: transform 220ms cubic-bezier(.16,1,.3,1), background 220ms ease, color 220ms ease, box-shadow 220ms ease;
}}
.mode-pill {{
  background: transparent;
  color: #6b7280;
  padding: 8px 18px;
  font-size: 14px;
  font-weight: 700;
}}
.mode-pill.is-active {{
  background: #fff;
  color: var(--ink);
  box-shadow: 0 1px 2px rgba(0,0,0,.06);
}}
.chip {{
  background: var(--cyan);
  color: #374151;
  padding: 7px 13px;
  font-size: 14px;
  font-weight: 650;
}}
.chip.is-active, .chip:hover {{
  background: var(--sky);
  color: var(--ink);
}}
.mode-pill:active, .chip:active, .tile:active, .copy-button:active, .modal-close:active {{ transform: translateY(1px) scale(.99); }}
.gallery {{
  column-count: 4;
  column-gap: 0;
  background: var(--cyan);
}}
.tile {{
  width: 100%;
  display: block;
  break-inside: avoid;
  border: 0;
  padding: 0;
  margin: 0;
  background: transparent;
  text-align: left;
}}
.tile[hidden] {{ display: none; }}
.tile-media {{
  position: relative;
  display: block;
  overflow: hidden;
  background: var(--cyan);
}}
.tile img {{
  width: 100%;
  height: auto;
  display: block;
  transition: transform 360ms cubic-bezier(.16,1,.3,1), filter 360ms cubic-bezier(.16,1,.3,1);
}}
.tile:hover img {{ transform: scale(1.045); filter: saturate(1.04); }}
.tile-shade {{
  position: absolute;
  inset: 0;
  display: flex;
  align-items: flex-end;
  justify-content: flex-end;
  padding: 12px;
  color: white;
  background: rgba(0, 0, 0, 0);
  opacity: 0;
  transition: opacity 220ms ease, background 220ms ease;
}}
.tile-shade span {{
  min-width: 34px;
  min-height: 34px;
  border-radius: 999px;
  display: grid;
  place-items: center;
  background: rgba(17, 24, 39, .72);
  color: #fff;
  font-size: 12px;
  font-weight: 800;
  padding: 0 8px;
}}
.tile:hover .tile-shade {{ opacity: 1; background: rgba(0, 0, 0, .18); }}
.empty-state {{
  display: none;
  padding: 80px 20px 120px;
  text-align: center;
  background: var(--cyan);
  color: var(--muted);
}}
.empty-state.is-visible {{ display: block; }}
.modal {{
  position: fixed;
  inset: 0;
  z-index: 50;
  display: none;
  align-items: center;
  justify-content: center;
  padding: 32px;
  background: rgba(17, 24, 39, .64);
}}
.modal.is-open {{ display: flex; }}
.modal-card {{
  width: min(1080px, 100%);
  max-height: min(92dvh, 980px);
  overflow: auto;
  border-radius: 14px;
  background: var(--cream);
  box-shadow: 0 28px 80px rgba(0, 0, 0, .28);
  transform: translateY(10px) scale(.985);
  opacity: 0;
  transition: transform 260ms cubic-bezier(.16,1,.3,1), opacity 260ms ease;
}}
.modal.is-open .modal-card {{ transform: translateY(0) scale(1); opacity: 1; }}
.modal-top {{
  position: sticky;
  top: 0;
  z-index: 2;
  display: flex;
  justify-content: flex-end;
  padding: 14px 14px 0;
  background: linear-gradient(var(--cream), rgba(252,240,214,.9));
}}
.modal-close {{
  width: 38px;
  height: 38px;
  border: 0;
  border-radius: 999px;
  background: transparent;
  color: #64748b;
  font-size: 28px;
  line-height: 1;
}}
.modal-close:hover {{ background: rgba(255,255,255,.7); color: var(--ink); }}
.modal-body {{
  padding: 0 22px 26px;
  display: grid;
  grid-template-columns: minmax(320px, .9fr) minmax(0, 1fr);
  gap: 24px;
  align-items: start;
}}
.modal-image-wrap {{
  border-radius: 10px;
  overflow: hidden;
  background: #111827;
}}
.modal-image {{
  width: 100%;
  max-height: 78dvh;
  object-fit: contain;
  display: block;
}}
.modal-info {{
  min-width: 0;
  padding-bottom: 8px;
}}
.modal-kicker {{
  margin: 0 0 8px;
  color: #64748b;
  font-size: 13px;
  font-weight: 800;
  letter-spacing: .06em;
}}
.modal-title {{
  margin: 0;
  color: var(--ink);
  font-size: clamp(24px, 3vw, 38px);
  line-height: 1.08;
  letter-spacing: 0;
}}
.modal-en {{
  margin: 8px 0 0;
  color: #6b7280;
  font-size: 15px;
  line-height: 1.5;
}}
.modal-tags {{
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
  margin: 16px 0;
}}
.modal-tags span {{
  border-radius: 999px;
  background: var(--cyan);
  color: #374151;
  padding: 6px 10px;
  font-size: 12px;
  font-weight: 700;
}}
.source-link {{
  color: var(--ink);
  text-decoration: underline;
  text-underline-offset: 3px;
}}
.modal-meta {{
  margin: 14px 0;
  color: #4b5563;
  font-size: 14px;
  line-height: 1.55;
}}
.prompt-head {{
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-top: 18px;
}}
.prompt-head strong {{ font-size: 15px; }}
.copy-button {{
  border: 1px solid var(--line);
  border-radius: 999px;
  background: #fff;
  color: var(--ink);
  padding: 7px 12px;
  font-size: 13px;
  font-weight: 800;
}}
.prompt-text {{
  margin: 10px 0 0;
  border: 1px solid rgba(17,24,39,.1);
  border-radius: 12px;
  background: rgba(255,255,255,.72);
  color: #1f2937;
  padding: 16px;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 13px;
  line-height: 1.65;
}}
.page-footer {{
  min-height: 360px;
  background: linear-gradient(var(--cyan), var(--cream));
}}
@media (max-width: 900px) {{
  .brand-inner {{
    width: calc(100% - 28px);
    min-height: 64px;
    grid-template-columns: 58px 1fr 58px;
  }}
  .brand-title {{
    font-size: clamp(1.1rem, 7vw, 2.25rem);
    letter-spacing: .2em;
  }}
  .intro {{ padding: 18px 0 24px; }}
  .intro-inner {{ width: calc(100% - 28px); }}
  .tagline {{ font-size: 13px; line-height: 1.45; white-space: normal; }}
  .info-grid {{ grid-template-columns: 1fr; gap: 8px; margin-top: 14px; }}
  .info-card {{ min-height: 62px; border-radius: 12px; padding: 10px 12px; gap: 10px; }}
  .info-icon {{ width: 30px; height: 30px; border-radius: 8px; font-size: 10px; }}
  .info-card strong {{ font-size: 13px; }}
  .info-card span {{ font-size: 11px; margin-top: 1px; }}
  .controls {{ margin-top: 14px; }}
  .mode-row {{ margin-bottom: 10px; }}
  .chip-row {{
    justify-content: flex-start;
    flex-wrap: nowrap;
    overflow-x: auto;
    padding: 0 2px 4px;
    scrollbar-width: none;
  }}
  .chip-row::-webkit-scrollbar {{ display: none; }}
  .chip, .mode-pill {{ font-size: 11px; padding: 5px 10px; white-space: nowrap; }}
  .gallery {{ column-count: 1; }}
  .modal {{ padding: 10px; align-items: stretch; }}
  .modal-card {{ max-height: calc(100dvh - 20px); border-radius: 12px; }}
  .modal-body {{ grid-template-columns: 1fr; padding: 0 12px 18px; gap: 14px; }}
  .modal-image {{ max-height: 58dvh; }}
  .modal-title {{ font-size: 22px; }}
  .prompt-text {{ font-size: 12px; }}
}}
@media (min-width: 901px) and (max-width: 1180px) {{
  .gallery {{ column-count: 3; }}
  .brand-inner, .intro-inner {{ width: min(100% - 72px, 1080px); }}
}}
@media (prefers-reduced-motion: reduce) {{
  html {{ scroll-behavior: auto; }}
  *, *::before, *::after {{
    animation-duration: .001ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: .001ms !important;
  }}
}}
</style>
<link rel="stylesheet" href="assets/prom-gallery.css?v=20261015">
</head>
<body>
<header class="brand-header">
  <div class="brand-inner">
    <a class="mark" href="#top" aria-label="回到顶部"><span class="mark-box"><span>PG</span></span></a>
    <h1 class="brand-title">PROMPT GALLERY</h1>
    <span aria-hidden="true"></span>
  </div>
</header>
<main id="top">
  <section class="intro" aria-label="图库介绍">
    <div class="intro-inner">
      <p class="tagline">Turn visual references into reusable prompts. 浏览灵感，收藏精选，让下一次创作从这里开始。</p>
      <div class="info-grid">
        <div class="info-card"><span class="info-icon">REF</span><span><strong>{data["stats"]["tiles"]} 张图片参考</strong><span class="info-copy">来自主站素材库，保留原图、分类、来源与 prompt。</span></span></div>
        <div class="info-card"><span class="info-icon">CAT</span><span><strong>{data["stats"]["categories"]} 个分类</strong><span class="info-copy">{data["stats"]["entries"]} 个条目，其中 {data["stats"]["prompts"]} 个包含完整提示词。</span></span></div>
      </div>
      <div class="controls" aria-label="筛选">
        <div class="mode-row">
          <button class="mode-pill is-active" type="button" data-mode="all" aria-pressed="true">全部图片</button>
          <button class="mode-pill" type="button" data-mode="favorites" aria-pressed="false">★ 我的收藏 <span class="favorite-count">0</span></button>
          <button class="mode-pill missing-toggle" type="button" aria-pressed="false">待补提示词 <span class="missing-count">0</span></button>
          <button class="mode-pill export-favorites" type="button" disabled>导出精选清单 ↓</button>
        </div>
        <p class="audit-summary"></p>
        <p class="storage-note" role="status">无需登录，收藏保存在当前浏览器；清除浏览器数据会移除收藏，可导出清单备份。</p>
        <div class="chip-row">{chips}</div>
      </div>
    </div>
  </section>
  <div class="results-bar"><span class="result-count" role="status"></span><button class="reset-filters" type="button">重置筛选</button></div>
  <section class="gallery" aria-label="图片瀑布流">
{tiles_html}
  </section>
  <p class="empty-state">当前分类暂无图片。</p>
</main>
<div class="modal" role="dialog" aria-modal="true" aria-label="图片与提示词详情">
  <div class="modal-card">
    <div class="modal-top"><button class="modal-close" type="button" aria-label="关闭">×</button></div>
    <div class="modal-body">
      <div class="modal-image-wrap"><img class="modal-image" alt=""></div>
      <div class="modal-info">
        <p class="modal-kicker"></p>
        <h2 class="modal-title"></h2>
        <p class="modal-en"></p>
        <div class="modal-tags"></div>
        <p class="modal-meta"></p>
        <button class="modal-favorite" type="button" aria-pressed="false">☆ 收藏这张图片</button>
        <p class="prompt-notice" hidden></p>
        <div class="prompt-head"><strong>完整提示词 / Original Prompt</strong><button class="copy-button" type="button">复制</button></div>
        <pre class="prompt-text"></pre>
      </div>
    </div>
  </div>
</div>
<footer class="page-footer" aria-hidden="true"></footer>
<script id="gallery-data" type="application/json">{payload}</script>
<script src="assets/prom-gallery.js?v=20261015"></script>
</body>
</html>
"""


def main() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    entries, categories = parse_entries(source)
    OUTPUT.write_text(build_html(entries, categories), encoding="utf-8")
    print(f"wrote {OUTPUT}")
    print(f"entries={len(entries)} categories={len(categories)} tiles={len(make_tiles(entries))}")


if __name__ == "__main__":
    main()
