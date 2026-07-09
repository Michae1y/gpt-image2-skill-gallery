from gallery_control.prompting import (
    extract_marked_prompt,
    is_placeholder,
    is_prompt_like,
    join_prompt_variants,
    prompt_candidates_from_post,
)


PROMPT = (
    "写实人像摄影，成年女性位于画面中央偏右，主体占据画面约百分之八十，"
    "近景半身裁切，平视视角，背景为红色方形瓷砖墙，正前方偏左柔和漫射光，"
    "暖调肤色，浅景深，白色蕾丝布料纹理清晰，阴影很轻，高细节真实相机质感。"
)


def test_extracts_only_marked_prompt() -> None:
    body = f"New work today.\n\nPrompt: {PROMPT}"
    assert extract_marked_prompt(body) == PROMPT
    assert is_prompt_like(extract_marked_prompt(body))


def test_placeholder_is_never_treated_as_prompt() -> None:
    value = "Prompt in the reply below."
    assert is_placeholder(value)
    assert not is_prompt_like(value)


def test_alt_prompts_remain_split_by_image() -> None:
    media = [{"alt_text": PROMPT}, {"alt_text": PROMPT.replace("中央偏右", "中央偏左")}]
    candidates = prompt_candidates_from_post("", media)
    assert [candidate.image_ordinal for candidate in candidates] == [1, 2]
    combined = join_prompt_variants(
        [{"image_ordinal": item.image_ordinal, "text": item.text} for item in candidates]
    )
    assert "[图片 1 / Image 1]" in combined
    assert "[图片 2 / Image 2]" in combined
