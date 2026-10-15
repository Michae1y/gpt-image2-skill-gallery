# GPT-Image2-Skill 标准网页版

打开 `index.html` 即可查看。

这是标准静态网页结构：

- `index.html`：页面内容
- `assets/styles.css`：样式
- `assets/images/`：页面卡片缩略图资源
- `assets/full/`：点击图片后使用的高清预览图资源

页面整理自 wuyoscar/GPT-Image2-Skill，原仓库作者：Wuyoscar。

发布时，把整个 `gpt-image2-skill-gallery-standard-site` 文件夹上传即可，不要只上传 `index.html`，因为图片和 CSS 在 `assets/` 目录里。

## 图片精选画廊

`prom-gallery-style.html` 支持按单张图片收藏、只看收藏、待补完整提示词和分类组合筛选。收藏使用当前浏览器的 localStorage，无需登录、不上传个人选择；不同浏览器之间不自动同步。可导出 JSON 精选清单，包含原图、来源、完整提示词或单独标注的正文摘要。

提示词缺失规则：正文为空，或 `promptIsComplete` 不是 true。2026-10-15 核对结果为 34 张图片 / 14 个条目，明细见 `missing-prompts.csv`。不把帖子正文或摘要当作完整提示词。

交互与增量样式位于 `assets/prom-gallery.js`、`assets/prom-gallery.css`；生成器 `tools/build_prom_gallery_style.py` 已同步引用这些文件，重新生成页面时会保留功能。

本地预览：`python3 -m http.server 8769 --bind 127.0.0.1`，打开 `http://127.0.0.1:8769/prom-gallery-style.html`。
