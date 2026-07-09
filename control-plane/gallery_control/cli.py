from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .config import settings
from .db import Database
from .pipeline import CollectionPipeline
from .repository import GalleryRepository


SEED_SOURCES = (
    ("x", "X · xiaoxiaodong01", "@xiaoxiaodong01", True, {"max_results": 10, "fetch_thread": True}),
    ("x", "X · YangOnchain", "@YangOnchain", True, {"max_results": 10, "fetch_thread": True}),
    ("x", "X · MrLarus", "@MrLarus", True, {"max_results": 10, "fetch_thread": True}),
    ("x", "X · ToroJushiAi", "@ToroJushiAi", True, {"max_results": 10, "fetch_thread": True}),
    ("x", "X · sdjn_wgc", "@sdjn_wgc", True, {"max_results": 10, "fetch_thread": True}),
    ("x", "X · Kunda623270", "@Kunda623270", True, {"max_results": 10, "fetch_thread": True}),
    ("x", "X · BubbleBrain", "@BubbleBrain", True, {"max_results": 10, "fetch_thread": True}),
    ("x", "X · Sairah_0", "@Sairah_0", True, {"max_results": 10, "fetch_thread": True}),
    ("wallhaven", "Wallhaven · 4K CG", "+digital_art +4k", False, {"sorting": "toplist", "topRange": "1w", "max_results": 12}),
    ("wallhaven", "Wallhaven · Anime", "+anime +scenery", False, {"sorting": "toplist", "topRange": "1w", "max_results": 12}),
    ("unsplash", "Unsplash · Editorial photography", "editorial photography", False, {"max_results": 12}),
    ("unsplash", "Unsplash · 3D render", "3d render abstract", False, {"max_results": 12}),
    ("design-milk", "Design Milk", "https://design-milk.com/feed/", False, {"max_results": 10}),
    ("abduzeedo", "Abduzeedo", "https://abduzeedo.com/rss.xml", False, {"max_results": 10}),
)


def seed_sources(database: Database) -> None:
    for platform, label, locator, enabled, config in SEED_SOURCES:
        database.upsert_source(
            {
                "platform": platform,
                "source_type": "creator" if platform == "x" else "discovery",
                "label": label,
                "locator": locator,
                "enabled": enabled,
                "collection_mode": "api" if platform not in {"design-milk", "abduzeedo"} else "rss",
                "frequency_hours": 24,
                "config": config,
            }
        )


def run_schedule(pipeline: CollectionPipeline) -> None:
    timezone = ZoneInfo("Asia/Shanghai")
    while True:
        now = datetime.now(timezone)
        target = now.replace(
            hour=settings.schedule_hour,
            minute=settings.schedule_minute,
            second=0,
            microsecond=0,
        )
        if target <= now:
            target += timedelta(days=1)
        time.sleep(max(1, (target - now).total_seconds()))
        try:
            pipeline.collect_all()
        except Exception as error:
            print(f"scheduled collection failed: {error}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="GPT Image prompt gallery control plane")
    parser.add_argument("command", choices=("init", "seed-sources", "collect", "schedule", "build", "validate", "publish"))
    parser.add_argument("--candidate", action="append", default=[])
    parser.add_argument("--message", default="Publish reviewed gallery references")
    args = parser.parse_args()

    settings.ensure_directories()
    database = Database(settings.database_path)
    pipeline = CollectionPipeline(settings, database)
    repository = GalleryRepository(settings, database)

    if args.command in {"init", "seed-sources"}:
        if args.command == "seed-sources" or not database.list_sources():
            seed_sources(database)
        print(json.dumps({"ok": True, "sources": len(database.list_sources())}, ensure_ascii=False))
    elif args.command == "collect":
        print(json.dumps(pipeline.collect_all(), ensure_ascii=False, indent=2))
    elif args.command == "schedule":
        run_schedule(pipeline)
    elif args.command == "build":
        repository.build_blanc()
    elif args.command == "validate":
        print(json.dumps(repository.validate(), ensure_ascii=False, indent=2))
    elif args.command == "publish":
        if args.candidate:
            for candidate_id in args.candidate:
                database.update_candidate(candidate_id, {"status": "approved"}, action="cli_approve")
            repository.publish_candidates(args.candidate)
        repository.build_blanc()
        print(json.dumps(repository.validate(), ensure_ascii=False, indent=2))
        sha = repository.commit_and_push(args.message)
        print(json.dumps({"commit": sha}, ensure_ascii=False))


if __name__ == "__main__":
    main()
