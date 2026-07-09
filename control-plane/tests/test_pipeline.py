from gallery_control.config import Settings
from gallery_control.db import Database
from gallery_control.pipeline import CollectionPipeline


def test_daily_collection_skips_sources_without_required_credentials(tmp_path) -> None:
    database = Database(tmp_path / "gallery.db")
    database.upsert_source(
        {
            "platform": "x",
            "label": "X without credentials",
            "locator": "@example",
            "enabled": True,
            "config": {},
        }
    )
    settings = Settings(
        repo_root=tmp_path,
        database_path=tmp_path / "gallery.db",
        spool_path=tmp_path / "spool",
        x_bearer_token="",
    )

    report = CollectionPipeline(settings, database).collect_all()

    assert report["new"] == 0
    assert report["failed"] == []
    assert report["skipped"] == ["X without credentials: 未配置 X_BEARER_TOKEN"]
    job = database.list_jobs(1)[0]
    assert job["status"] == "completed"
    assert "跳过 1 个源" in job["summary"]
