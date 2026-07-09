# Prompt Gallery Control Plane

这个目录是主站与 BLANC 副站之外的管理控制层。公开页面仍由 GitHub Pages 托管；采集、反推、审核和发布在这里完成。

## 工作流

1. 每日调度器读取启用的采集源。
2. 新内容按 canonical URL 和 X status id 去重。
3. 优先核验媒体 ALT、主帖明确 prompt、作者同线程回复。
4. 没有原始 prompt 时，调用 `prompts/reverse_prompt.zh.txt` 进行图片反推，并做第二遍视觉覆盖审查。
5. 所有新内容先进入审核队列，不自动公开。
6. 管理员可改 prompt、改分类、隐藏、删除或批准。
7. 发布器只修改 `index.html`，随后运行 `tools/build_prom_gallery_style.py`，因此两个前台同步更新。

## 本地启动

```bash
cd control-plane
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
PYTHONPATH=. .venv/bin/python -m gallery_control.cli init
PYTHONPATH=. .venv/bin/uvicorn gallery_control.app:app --host 127.0.0.1 --port 8787
```

打开 `http://127.0.0.1:8787/admin/`。

## 平台边界

- X：推荐官方 X API，按用户时间线增量读取，并抓作者同线程回复；数据中心 IP 不运行浏览器 Cookie 抓取。
- Wallhaven：使用公开 API，默认仅 SFW。
- Unsplash：遵守 API 的热链、摄影师署名和下载追踪要求，不缓存到本地 assets。
- Design Milk / Abduzeedo：只从 RSS 收集候选链接，图片仍需审核。
- Behance / ArtStation：默认人工链接导入。ArtStation 必须先确认权利和 NoAI 状态，不能自动把 NoAI 内容送入生成式模型。
- Dynamic Wallpaper Club / Haikei / Cool Backgrounds / Simple Desktops：人工链接导入，保留原始页面、作者和平台追溯。

## 复原质量

日常模式会执行“反推 + 覆盖审查”两遍视觉推理。`GALLERY_RENDER_BACK_ENABLED=true` 后，会额外用 GPT Image 2 生成复原图并比较差异，最多修订两轮。该模式成本和耗时更高，建议只对管理员选中的重点素材使用。
