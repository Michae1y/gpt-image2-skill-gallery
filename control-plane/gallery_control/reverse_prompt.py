from __future__ import annotations

import base64
import json
import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import CONTROL_ROOT, Settings
from .prompting import normalize_prompt


AUDIT_PROMPT = """你是图片提示词复原质检员。比较参考图与候选提示词，检查候选提示词是否明确覆盖：主体、构图位置与占比、裁切、视角与透视、前后层级、主辅色、明度饱和度与对比度、光源方向与软硬、阴影和高光、材质、背景结构、景深、比例和清晰度。只返回 JSON：{\"score\":0到100的整数,\"missing\":\"缺失或错误点\",\"revised_prompt\":\"修正后的一整段完整生图提示词\"}。不要增加参考图中不存在的元素。"""

COMPARE_PROMPT = """你是严格的图像复原验收员。第一张图是参考图，第二张图是根据候选提示词生成的复原图。比较主体、构图、位置占比、裁切、视角透视、前后层级、色调、光影、材质、背景、景深和细节密度。只返回 JSON：{\"score\":0到100的整数,\"differences\":\"主要差异\",\"revised_prompt\":\"为修正差异而重写的一整段完整提示词\"}。不得加入参考图不存在的元素。"""


@dataclass(frozen=True)
class ReverseResult:
    prompt: str
    score: int | None
    notes: str
    render_path: str | None = None


def _image_data_url(path: Path) -> str:
    mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def _json_from_text(text: str) -> dict[str, Any]:
    value = text.strip()
    if value.startswith("```"):
        value = value.split("\n", 1)[-1].rsplit("```", 1)[0]
        if value.lstrip().startswith("json"):
            value = value.lstrip()[4:].lstrip()
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        start = value.find("{")
        end = value.rfind("}")
        if start != -1 and end > start:
            return json.loads(value[start : end + 1])
        raise


class ReversePromptEngine:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.system_prompt = (CONTROL_ROOT / "prompts" / "reverse_prompt.zh.txt").read_text(encoding="utf-8")

    def _client(self):
        if not self.settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is required for prompt reversal")
        from openai import OpenAI

        return OpenAI(api_key=self.settings.openai_api_key)

    @staticmethod
    def _image_content(image: str | Path) -> dict[str, Any]:
        if isinstance(image, Path) or not str(image).startswith(("http://", "https://", "data:")):
            image_url = _image_data_url(Path(image))
        else:
            image_url = str(image)
        return {"type": "input_image", "image_url": image_url, "detail": "original"}

    def reverse(self, image: str | Path) -> ReverseResult:
        client = self._client()
        response = client.responses.create(
            model=self.settings.vision_model,
            input=[
                {"role": "system", "content": [{"type": "input_text", "text": self.system_prompt}]},
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": "反推提示词"},
                        self._image_content(image),
                    ],
                },
            ],
        )
        prompt = normalize_prompt(response.output_text)
        if prompt == "无法准确识别该链接图片，请直接上传图片原图。":
            return ReverseResult(prompt="", score=None, notes=prompt)
        audited = self.audit(image, prompt)
        prompt = audited.prompt
        if self.settings.render_back_enabled and audited.score is not None:
            return self.render_and_compare(image, prompt, initial_score=audited.score, notes=audited.notes)
        return audited

    def audit(self, image: str | Path, prompt: str) -> ReverseResult:
        client = self._client()
        response = client.responses.create(
            model=self.settings.vision_model,
            input=[
                {"role": "system", "content": [{"type": "input_text", "text": AUDIT_PROMPT}]},
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": f"候选提示词：\n{prompt}"},
                        self._image_content(image),
                    ],
                },
            ],
        )
        payload = _json_from_text(response.output_text)
        revised = normalize_prompt(payload.get("revised_prompt") or prompt)
        return ReverseResult(
            prompt=revised,
            score=int(payload.get("score", 0)),
            notes=str(payload.get("missing", "")),
        )

    def render_and_compare(
        self,
        image: str | Path,
        prompt: str,
        *,
        initial_score: int | None = None,
        notes: str = "",
    ) -> ReverseResult:
        client = self._client()
        render_dir = self.settings.spool_path / "render-back"
        render_dir.mkdir(parents=True, exist_ok=True)
        latest_prompt = prompt
        latest_score = initial_score
        latest_notes = notes
        latest_path: Path | None = None

        for attempt in range(2):
            result = client.images.generate(
                model=self.settings.image_model,
                prompt=latest_prompt,
                quality="medium",
                size="auto",
            )
            image_bytes = base64.b64decode(result.data[0].b64_json)
            latest_path = render_dir / f"render-{abs(hash((latest_prompt, attempt)))}.png"
            latest_path.write_bytes(image_bytes)
            response = client.responses.create(
                model=self.settings.vision_model,
                input=[
                    {"role": "system", "content": [{"type": "input_text", "text": COMPARE_PROMPT}]},
                    {
                        "role": "user",
                        "content": [
                            {"type": "input_text", "text": f"候选提示词：\n{latest_prompt}"},
                            self._image_content(image),
                            self._image_content(latest_path),
                        ],
                    },
                ],
            )
            payload = _json_from_text(response.output_text)
            latest_score = int(payload.get("score", 0))
            latest_notes = str(payload.get("differences", ""))
            revised = normalize_prompt(payload.get("revised_prompt") or latest_prompt)
            if latest_score >= self.settings.fidelity_threshold or not revised:
                break
            latest_prompt = revised

        return ReverseResult(
            prompt=latest_prompt,
            score=latest_score,
            notes=latest_notes,
            render_path=str(latest_path) if latest_path else None,
        )
