#!/usr/bin/env python3
from __future__ import annotations

import bisect
import colorsys
from collections import defaultdict
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


def make_visual_groups(tiles: list[dict], columns: int) -> tuple[list[list[dict]], dict]:
    """Build cohesive visual rows before weaving those rows through the gallery."""
    newest = max(
        tiles,
        key=lambda tile: (
            timestamp_for_sort(tile["imageAddedAt"]),
            entry_number_for_sort(tile["entryNo"]),
        ),
    )
    family_pools: dict[str, list[dict]] = defaultdict(list)
    for tile in tiles:
        family_pools[tile["_visual"]["family"]].append(tile)

    groups = []
    leftovers = []
    for family in sorted(family_pools):
        pool = family_pools[family][:]
        preferred_anchor = newest if newest in pool else None
        while len(pool) >= columns:
            anchor = (
                preferred_anchor
                if preferred_anchor in pool
                else min(pool, key=lambda tile: tile["_visual"]["jitter"])
            )
            preferred_anchor = None
            pool.remove(anchor)
            group = [anchor]
            while len(group) < columns:
                used_entries = {member["entryIndex"] for member in group}
                candidates = [
                    tile for tile in pool if tile["entryIndex"] not in used_entries
                ] or pool
                candidate = min(
                    candidates,
                    key=lambda tile: (
                        sum(
                            visual_distance(member["_visual"], tile["_visual"], 0.0)
                            for member in group
                        )
                        / len(group),
                        tile["_visual"]["jitter"],
                    ),
                )
                pool.remove(candidate)
                group.append(candidate)
            groups.append(group)
        leftovers.extend(pool)

    while leftovers:
        anchor = min(
            leftovers,
            key=lambda tile: (
                0 if tile is newest else 1,
                tile["_visual"]["jitter"],
            ),
        )
        leftovers.remove(anchor)
        group = [anchor]
        while leftovers and len(group) < columns:
            used_entries = {member["entryIndex"] for member in group}
            candidates = [
                tile for tile in leftovers if tile["entryIndex"] not in used_entries
            ] or leftovers
            candidate = min(
                candidates,
                key=lambda tile: (
                    visual_distance(anchor["_visual"], tile["_visual"], 2.6),
                    tile["_visual"]["jitter"],
                ),
            )
            leftovers.remove(candidate)
            group.append(candidate)
        groups.append(group)
    return groups, newest


def order_visual_groups(groups: list[list[dict]], newest: dict) -> list[list[dict]]:
    first = next(group for group in groups if newest in group)
    ordered = [first]
    remaining = [group for group in groups if group is not first]
    family_run = 1
    medium_run = 1

    while remaining:
        previous = group_centroid(ordered[-1])
        previous_medium = VISUAL_MEDIUM_BY_FAMILY.get(previous["family"], "other")
        previous_entries = {tile["entryIndex"] for tile in ordered[-1]}

        def transition_cost(group: list[dict]) -> float:
            current = group_centroid(group)
            cost = visual_distance(previous, current, 0.95)
            if current["family"] == previous["family"] and family_run >= 2:
                cost += 2.3
            current_medium = VISUAL_MEDIUM_BY_FAMILY.get(current["family"], "other")
            if current_medium == previous_medium and medium_run >= 4:
                cost += 2.8
            repeated_entries = previous_entries.intersection(
                tile["entryIndex"] for tile in group
            )
            cost += len(repeated_entries) * 1.4
            group_key = "|".join(tile["tileId"] for tile in group)
            return cost + stable_fraction(group_key) * 0.04

        selected = min(remaining, key=transition_cost)
        remaining.remove(selected)
        selected_family = group_centroid(selected)["family"]
        selected_medium = VISUAL_MEDIUM_BY_FAMILY.get(selected_family, "other")
        family_run = family_run + 1 if selected_family == previous["family"] else 1
        medium_run = medium_run + 1 if selected_medium == previous_medium else 1
        ordered.append(selected)
    return ordered


def visual_weave_tiles(tiles: list[dict], columns: int = DESKTOP_GALLERY_COLUMNS) -> list[dict]:
    """Return a stable row-major order based on subject family, palette, and aspect ratio."""
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
<title>Prompt Gallery - BLANC Style Copy</title>
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
      <p class="tagline">Turn visual references into reusable prompts. 浏览图片，打开细节，复制完整提示词。</p>
      <div class="info-grid">
        <div class="info-card"><span class="info-icon">REF</span><span><strong>{data["stats"]["tiles"]} 张图片参考</strong><span class="info-copy">来自主站素材库，保留原图、分类、来源与 prompt。</span></span></div>
        <div class="info-card"><span class="info-icon">CAT</span><span><strong>{data["stats"]["categories"]} 个分类</strong><span class="info-copy">{data["stats"]["entries"]} 个条目，其中 {data["stats"]["prompts"]} 个包含完整提示词。</span></span></div>
      </div>
      <div class="controls" aria-label="筛选">
        <div class="mode-row">
          <button class="mode-pill is-active" type="button">Images</button>
        </div>
        <div class="chip-row">{chips}</div>
      </div>
    </div>
  </section>
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
        <div class="prompt-head"><strong>完整提示词 / Original Prompt</strong><button class="copy-button" type="button">复制</button></div>
        <pre class="prompt-text"></pre>
      </div>
    </div>
  </div>
</div>
<footer class="page-footer" aria-hidden="true"></footer>
<script id="gallery-data" type="application/json">{payload}</script>
<script>
(() => {{
  const data = JSON.parse(document.getElementById('gallery-data').textContent);
  const tiles = Array.from(document.querySelectorAll('.tile'));
  const chips = Array.from(document.querySelectorAll('.chip'));
  const gallery = document.querySelector('.gallery');
  const empty = document.querySelector('.empty-state');
  const modal = document.querySelector('.modal');
  const modalImage = document.querySelector('.modal-image');
  const modalKicker = document.querySelector('.modal-kicker');
  const modalTitle = document.querySelector('.modal-title');
  const modalEn = document.querySelector('.modal-en');
  const modalTags = document.querySelector('.modal-tags');
  const modalMeta = document.querySelector('.modal-meta');
  const promptLabel = document.querySelector('.prompt-head strong');
  const promptText = document.querySelector('.prompt-text');
  const copyButton = document.querySelector('.copy-button');
  const closeButton = document.querySelector('.modal-close');
  let activePrompt = '';
  let activeCategory = 'all';
  let lastFocus = null;
  let lastColumnCount = 0;
  let layoutFrame = 0;

  function currentColumnCount() {{
    return Math.max(1, Number.parseInt(getComputedStyle(gallery).columnCount, 10) || 1);
  }}

  function tileRatio(tile) {{
    const image = tile.querySelector('img');
    const width = Number(image?.getAttribute('width')) || image?.naturalWidth || 1;
    const height = Number(image?.getAttribute('height')) || image?.naturalHeight || 1;
    return height / Math.max(width, 1);
  }}

  function arrangeVisibleTiles(visibleTiles) {{
    const columns = currentColumnCount();
    lastColumnCount = columns;
    if (columns === 1) {{
      visibleTiles.forEach(tile => gallery.append(tile));
    }} else {{
      const lanes = Array.from({{ length: columns }}, () => []);
      const heights = Array(columns).fill(0);
      for (let offset = 0; offset < visibleTiles.length; offset += columns) {{
        const row = visibleTiles.slice(offset, offset + columns)
          .sort((first, second) => tileRatio(second) - tileRatio(first));
        const laneOrder = Array.from({{ length: columns }}, (_, index) => index)
          .sort((first, second) => heights[first] - heights[second] || first - second);
        row.forEach((tile, index) => {{
          const lane = laneOrder[index];
          lanes[lane].push(tile);
          heights[lane] += tileRatio(tile);
        }});
      }}
      lanes.flat().forEach(tile => gallery.append(tile));
    }}
    tiles.filter(tile => tile.hidden).forEach(tile => gallery.append(tile));
  }}

  function applyFilter(category) {{
    activeCategory = category;
    const visibleTiles = [];
    tiles.forEach(tile => {{
      const show = tile.dataset.broken !== 'true' && (category === 'all' || tile.dataset.category === category);
      tile.hidden = !show;
      if (show) visibleTiles.push(tile);
    }});
    arrangeVisibleTiles(visibleTiles);
    empty.classList.toggle('is-visible', visibleTiles.length === 0);
    chips.forEach(chip => chip.classList.toggle('is-active', chip.dataset.filter === category));
  }}

  function openTile(index) {{
    const tile = data.tiles[index];
    if (!tile) return;
    const entry = data.entries[tile.entryIndex];
    const image = entry.images[tile.imageIndex] || entry.images[0];
    lastFocus = document.activeElement;
    modalImage.dataset.fallback = image.src || '';
    modalImage.src = image.full || image.src;
    modalImage.alt = image.alt || entry.title;
    modalKicker.textContent = `${{entry.entryNo || 'Reference'}} | ${{entry.category}}`;
    modalTitle.textContent = entry.title || '未命名素材';
    modalEn.textContent = entry.titleEn || image.caption || '';
    modalTags.innerHTML = (entry.tags || []).slice(0, 8).map(tag => `<span>${{escapeHtml(tag)}}</span>`).join('');
    const platform = entry.sourcePlatform || platformFromUrl(entry.sourceUrl);
    const source = entry.sourceUrl ? `<a class="source-link" href="${{escapeAttr(entry.sourceUrl)}}" target="_blank" rel="noopener">${{escapeHtml(platform)}} 来源追溯</a>` : '';
    const meta = (entry.kvs || []).slice(0, 2).join(' ');
    modalMeta.innerHTML = [source, escapeHtml(meta)].filter(Boolean).join(' · ');
    activePrompt = entry.prompt || '这条素材暂未收录完整提示词。';
    promptLabel.textContent = entry.promptLabel || '完整提示词 / Original Prompt';
    promptText.textContent = activePrompt;
    copyButton.textContent = entry.prompt ? (entry.promptIsComplete ? '复制' : '复制正文') : '暂无 prompt';
    copyButton.disabled = !entry.prompt;
    modal.classList.add('is-open');
    document.body.style.overflow = 'hidden';
    closeButton.focus();
  }}

  function closeModal() {{
    modal.classList.remove('is-open');
    document.body.style.overflow = '';
    modalImage.removeAttribute('src');
    if (lastFocus && typeof lastFocus.focus === 'function') lastFocus.focus();
  }}

  function escapeHtml(value) {{
    return String(value).replace(/[&<>"']/g, char => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[char]));
  }}
  function escapeAttr(value) {{ return escapeHtml(value).replace(/`/g, '&#96;'); }}
  function platformFromUrl(value) {{
    if (!value) return '原始';
    try {{
      const host = new URL(value).hostname.replace(/^www\./, '');
      if (host === 'x.com' || host === 'twitter.com') return 'X';
      if (host.includes('unsplash.com')) return 'Unsplash';
      if (host.includes('wallhaven.cc')) return 'Wallhaven';
      if (host.includes('behance.net')) return 'Behance';
      if (host.includes('artstation.com')) return 'ArtStation';
      return host;
    }} catch {{
      return '原始';
    }}
  }}

  tiles.forEach(tile => {{
    const img = tile.querySelector('img');
    img?.addEventListener('error', () => {{
      tile.dataset.broken = 'true';
      tile.hidden = true;
      requestAnimationFrame(() => applyFilter(activeCategory));
    }}, {{ once: true }});
  }});
  modalImage.addEventListener('error', () => {{
    const fallback = modalImage.dataset.fallback;
    if (fallback && modalImage.src !== new URL(fallback, window.location.href).href) {{
      modalImage.src = fallback;
    }}
  }});
  chips.forEach(chip => chip.addEventListener('click', () => applyFilter(chip.dataset.filter)));
  tiles.forEach(tile => tile.addEventListener('click', () => openTile(Number(tile.dataset.tileIndex))));
  closeButton.addEventListener('click', closeModal);
  modal.addEventListener('click', event => {{ if (event.target === modal) closeModal(); }});
  document.addEventListener('keydown', event => {{ if (event.key === 'Escape' && modal.classList.contains('is-open')) closeModal(); }});
  window.addEventListener('resize', () => {{
    cancelAnimationFrame(layoutFrame);
    layoutFrame = requestAnimationFrame(() => {{
      if (currentColumnCount() !== lastColumnCount) applyFilter(activeCategory);
    }});
  }});
  copyButton.addEventListener('click', async () => {{
    if (!activePrompt) return;
    try {{
      await navigator.clipboard.writeText(activePrompt);
      copyButton.textContent = '已复制';
      setTimeout(() => copyButton.textContent = '复制', 1200);
    }} catch {{
      const range = document.createRange();
      range.selectNodeContents(promptText);
      const selection = window.getSelection();
      selection.removeAllRanges();
      selection.addRange(range);
      copyButton.textContent = '已选中';
    }}
  }});
  applyFilter('all');
}})();
</script>
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
