from gallery_control.db import Database


def test_candidate_lifecycle(tmp_path) -> None:
    database = Database(tmp_path / "gallery.db")
    source = database.upsert_source(
        {
            "platform": "x",
            "label": "Example",
            "locator": "@example",
            "enabled": True,
            "config": {"max_results": 10},
        }
    )
    candidate, created = database.upsert_candidate(
        {
            "source_id": source["id"],
            "platform": "x",
            "canonical_url": "https://x.com/example/status/1",
            "title": "Example prompt",
            "prompt_variants": [],
            "metadata": {},
        }
    )
    assert created
    database.replace_media(
        candidate["id"],
        [{"source_url": "https://example.com/image.jpg", "media_policy": "hotlink"}],
    )
    updated = database.update_candidate(
        candidate["id"],
        {"active_prompt": "A complete prompt", "status": "approved"},
        action="test",
    )
    assert updated["status"] == "approved"
    assert len(updated["media"]) == 1
    assert database.summary()["approved"] == 1
