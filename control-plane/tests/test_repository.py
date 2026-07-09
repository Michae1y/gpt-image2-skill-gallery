from pathlib import Path

from gallery_control.config import Settings
from gallery_control.repository import GalleryRepository


HTML = """<!doctype html><html><body>
<nav><a href="#cat-photography"><small>Photography · No. 1–1 · 1 条</small></a><a href="#cat-fashion-editorial"><small>Fashion · No. 2–2 · 1 条</small></a></nav>
<div class="stats"><div class="stat"><strong>2</strong>完整 prompt 条目</div><div class="stat"><strong>2</strong>图片引用</div><div class="stat"><strong>2</strong>卡片条目</div></div>
<section id="cat-photography" class="category"><h2>摄影 <span class="meta">/ Photography · No. 1–1 · 1 条</span></h2><div class="pin-grid">
<article id="entry-one" class="entry" data-entry-no="1"><div class="entry-head"><div class="title-stack"><span class="entry-no">No. 1</span><h3 class="entry-title">One</h3><p class="title-en">One EN</p></div><span class="badge">摄影 / Photography</span></div><div class="tag-list"><span class="tag">摄影</span></div><div class="images"><figure><img src="assets/one.jpg" data-full="assets/one.jpg" alt="one"></figure></div><details class="prompt-details"><summary>完整提示词 / Original Prompt</summary><pre class="prompt"><code>Old prompt</code></pre></details></article>
</div></section>
<section id="cat-fashion-editorial" class="category"><h2>时尚大片 <span class="meta">/ Fashion · No. 2–2 · 1 条</span></h2><div class="pin-grid">
<article id="entry-two" class="entry" data-entry-no="2"><div class="entry-head"><div class="title-stack"><span class="entry-no">No. 2</span><h3 class="entry-title">Two</h3><p class="title-en">Two EN</p></div><span class="badge">时尚大片 / Fashion Editorial</span></div><div class="tag-list"><span class="tag">时尚大片</span></div><div class="images"><figure><img src="assets/two.jpg" data-full="assets/two.jpg" alt="two"></figure></div><details class="prompt-details"><summary>完整提示词 / Original Prompt</summary><pre class="prompt"><code>Second prompt</code></pre></details></article>
</div></section>
</body></html>"""


def make_repo(tmp_path: Path) -> GalleryRepository:
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "one.jpg").write_bytes(b"one")
    (tmp_path / "assets" / "two.jpg").write_bytes(b"two")
    (tmp_path / "index.html").write_text(HTML, encoding="utf-8")
    settings = Settings(
        repo_root=tmp_path,
        database_path=tmp_path / "gallery.db",
        spool_path=tmp_path / "spool",
    )
    return GalleryRepository(settings)


def test_hide_restore_prompt_and_move(tmp_path) -> None:
    repository = make_repo(tmp_path)
    repository.set_hidden("entry-one", True)
    visible = repository.list_entries(include_hidden=False)
    assert [entry["id"] for entry in visible] == ["entry-two"]
    repository.set_hidden("entry-one", False)
    repository.update_prompt("entry-one", "New precise prompt")
    repository.move_entry("entry-one", "cat-fashion-editorial")
    entries = repository.list_entries()
    moved = next(entry for entry in entries if entry["id"] == "entry-one")
    assert moved["section_id"] == "cat-fashion-editorial"
    assert moved["prompt"] == "New precise prompt"
    assert "2 条" in repository.index_path.read_text(encoding="utf-8")


def test_validate_checks_local_assets(tmp_path) -> None:
    repository = make_repo(tmp_path)
    result = repository.validate()
    assert result == {"entries": 2, "images": 2, "prompts": 2}
