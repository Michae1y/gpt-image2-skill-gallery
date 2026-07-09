from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Category:
    id: str
    label: str
    english: str
    keywords: tuple[str, ...]


CATEGORIES = (
    Category("cat-anime-manga", "动漫与漫画", "Anime & Manga", ("anime", "manga", "动漫", "漫画", "二次元")),
    Category("cat-gaming", "游戏与 HUD", "Gaming & HUD", ("game", "hud", "rpg", "游戏", "界面")),
    Category("cat-retro-cyberpunk", "复古与赛博朋克", "Retro & Cyberpunk", ("cyberpunk", "retro", "赛博", "复古", "霓虹")),
    Category("cat-cinematic-animation", "电影感与动画", "Cinematic & Animation", ("animation", "pixar", "ghibli", "动画", "分镜")),
    Category("cat-character-design", "角色设计", "Character Design", ("character sheet", "角色设定", "三视图", "设定表")),
    Category("cat-typography-posters", "字体与海报", "Typography & Posters", ("poster", "typography", "海报", "字体", "封面", "请柬")),
    Category("cat-illustration", "插画", "Illustration", ("illustration", "插画", "绘本")),
    Category("cat-watercolor", "水彩", "Watercolor", ("watercolor", "水彩")),
    Category("cat-ink-chinese", "水墨与中文风格", "Ink & Chinese", ("ink", "水墨", "国风", "东方", "书法")),
    Category("cat-pixel-art", "像素艺术", "Pixel Art", ("pixel", "像素")),
    Category("cat-isometric", "等距视角", "Isometric", ("isometric", "等距")),
    Category("cat-product-food", "产品与食物", "Product & Food", ("product", "food", "packaging", "产品", "食品", "包装", "饮料")),
    Category("cat-brand-systems-identity", "品牌系统与视觉识别", "Brand Systems & Identity", ("brand", "identity", "logo", "品牌", "视觉识别", "标志")),
    Category("cat-photography", "摄影", "Photography", ("photo", "photography", "portrait", "摄影", "写真", "自拍", "人像")),
    Category("cat-infographics-field-guides", "信息图与图鉴", "Infographics & Field Guides", ("infographic", "field guide", "信息图", "图鉴", "百科")),
    Category("cat-research-paper-figures", "论文配图", "Research Paper Figures", ("research", "paper", "论文", "流程图", "科研")),
    Category("cat-official-openai-cookbook-examples", "OpenAI Cookbook 官方示例", "Official OpenAI Cookbook Examples", ("openai cookbook",)),
    Category("cat-edit-endpoint-showcase", "图片编辑接口示例", "Edit Endpoint Showcase", ("image edit", "编辑接口")),
    Category("cat-ui-ux-mockups", "UI/UX 界面样机", "UI/UX Mockups", ("ui", "ux", "mockup", "界面", "样机")),
    Category("cat-data-visualization", "数据可视化", "Data Visualization", ("data visualization", "chart", "数据可视化", "图表")),
    Category("cat-technical-illustration", "技术插图", "Technical Illustration", ("technical", "exploded", "cutaway", "技术插图", "爆炸图", "剖面")),
    Category("cat-architecture-interior", "建筑与室内", "Architecture & Interior", ("architecture", "interior", "建筑", "室内", "空间")),
    Category("cat-scientific-educational", "科学与教育", "Scientific & Educational", ("science", "education", "科学", "教育", "解剖")),
    Category("cat-fashion-editorial", "时尚大片", "Fashion Editorial", ("fashion", "editorial", "couture", "时尚", "大片", "lookbook")),
    Category("cat-fine-art-painting", "美术绘画", "Fine Art Painting", ("painting", "fine art", "油画", "绘画", "壁画")),
    Category("cat-more-illustration-styles", "更多插画风格", "More Illustration Styles", ("risograph", "flat design", "sticker", "低多边形", "贴纸")),
    Category("cat-cinematic-film-references", "电影风格参考", "Cinematic Film References", ("cinematic", "film still", "电影感", "镜头", "电影")),
    Category("cat-beauty-lifestyle", "美妆与生活方式", "Beauty & Lifestyle", ("beauty", "skincare", "makeup", "美妆", "护肤", "生活方式")),
    Category("cat-events-experience", "活动与体验设计", "Events & Experience", ("event", "wayfinding", "活动", "导视", "体验设计")),
    Category("cat-tattoo-design", "纹身设计", "Tattoo Design", ("tattoo", "纹身")),
    Category("cat-screen-photography", "屏幕摄影", "Screen Photography", ("screen photography", "屏幕摄影", "电脑屏幕")),
)

CATEGORY_BY_ID = {category.id: category for category in CATEGORIES}


def classify_by_keywords(*values: str) -> Category:
    haystack = " ".join(value for value in values if value).lower()
    scored: list[tuple[int, Category]] = []
    for category in CATEGORIES:
        score = sum(1 for keyword in category.keywords if keyword.lower() in haystack)
        if score:
            scored.append((score, category))
    if not scored:
        return CATEGORY_BY_ID["cat-photography"]
    scored.sort(key=lambda item: item[0], reverse=True)
    return scored[0][1]
