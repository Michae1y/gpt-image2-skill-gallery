from __future__ import annotations

import re
from dataclasses import dataclass


PROMPT_MARKERS = (
    r"(?:^|\n)\s*(?:prompt|image prompt|提示词|生图提示词|プロンプト)\s*[:：]\s*",
    r"(?:^|\n)\s*【\s*(?:GPT\s*Image\s*2\s*)?プロンプト\s*】\s*",
)

PLACEHOLDER_PATTERNS = (
    r"prompt\s+(?:is\s+)?in\s+(?:the\s+)?(?:reply|comment)s?",
    r"prompt\s+below",
    r"提示词.{0,8}(?:评论区|回复|下方|置顶)",
    r"check\s+(?:the\s+)?(?:alt|reply|comment)",
)

VISUAL_TERMS = (
    "composition", "lighting", "background", "foreground", "camera", "lens", "perspective",
    "color", "palette", "shadow", "highlight", "texture", "material", "subject", "portrait",
    "构图", "光线", "背景", "前景", "镜头", "透视", "色调", "阴影", "高光", "材质", "主体",
    "人物", "产品", "景深", "裁切", "占据画面", "画面中央", "左侧", "右侧",
)


@dataclass(frozen=True)
class PromptCandidate:
    text: str
    source: str
    image_ordinal: int | None = None
    verified: bool = False


def normalize_prompt(text: str) -> str:
    value = (text or "").strip()
    value = re.sub(r"\r\n?", "\n", value)
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip(" \n`\"“”")


def extract_marked_prompt(text: str) -> str:
    source = text or ""
    matches = []
    for pattern in PROMPT_MARKERS:
        match = re.search(pattern, source, re.I)
        if match:
            matches.append(match)
    if not matches:
        return ""
    match = min(matches, key=lambda item: item.start())
    return normalize_prompt(source[match.end():])


def is_placeholder(text: str) -> bool:
    value = normalize_prompt(text).lower()
    return any(re.search(pattern, value, re.I) for pattern in PLACEHOLDER_PATTERNS)


def is_prompt_like(text: str) -> bool:
    value = normalize_prompt(text)
    if len(value) < 90 or is_placeholder(value):
        return False
    lowered = value.lower()
    visual_hits = sum(1 for term in VISUAL_TERMS if term.lower() in lowered)
    sentence_signals = len(re.findall(r"[,，。.;；:]", value))
    return visual_hits >= 3 and sentence_signals >= 4


def prompt_candidates_from_post(body: str, media: list[dict]) -> list[PromptCandidate]:
    candidates: list[PromptCandidate] = []
    for index, item in enumerate(media, start=1):
        alt_text = normalize_prompt(item.get("alt_text", ""))
        if is_prompt_like(alt_text):
            candidates.append(PromptCandidate(alt_text, "media_alt", index, True))

    marked = extract_marked_prompt(body)
    if is_prompt_like(marked):
        candidates.append(PromptCandidate(marked, "post_body", None, True))

    return candidates


def join_prompt_variants(variants: list[dict]) -> str:
    if not variants:
        return ""
    if len(variants) == 1:
        return normalize_prompt(variants[0].get("text", ""))
    blocks = []
    for index, variant in enumerate(variants, start=1):
        ordinal = variant.get("image_ordinal") or index
        blocks.append(f"[图片 {ordinal} / Image {ordinal}]\n{normalize_prompt(variant.get('text', ''))}")
    return "\n\n".join(blocks)
