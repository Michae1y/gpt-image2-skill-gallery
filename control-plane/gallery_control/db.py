from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY,
    platform TEXT NOT NULL,
    source_type TEXT NOT NULL DEFAULT 'creator',
    label TEXT NOT NULL,
    locator TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    collection_mode TEXT NOT NULL DEFAULT 'api',
    frequency_hours INTEGER NOT NULL DEFAULT 24,
    config_json TEXT NOT NULL DEFAULT '{}',
    last_cursor TEXT,
    last_checked_at TEXT,
    last_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(platform, locator)
);

CREATE TABLE IF NOT EXISTS candidates (
    id TEXT PRIMARY KEY,
    source_id TEXT REFERENCES sources(id) ON DELETE SET NULL,
    platform TEXT NOT NULL,
    canonical_url TEXT NOT NULL UNIQUE,
    external_id TEXT,
    author TEXT,
    title TEXT NOT NULL DEFAULT '',
    source_text TEXT NOT NULL DEFAULT '',
    prompt_kind TEXT NOT NULL DEFAULT 'pending',
    prompt_status TEXT NOT NULL DEFAULT 'pending',
    prompt_variants_json TEXT NOT NULL DEFAULT '[]',
    active_prompt TEXT NOT NULL DEFAULT '',
    category_id TEXT,
    category_label TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    rights_status TEXT NOT NULL DEFAULT 'review',
    source_published_at TEXT,
    collected_at TEXT NOT NULL,
    reviewed_at TEXT,
    published_entry_id TEXT,
    hidden INTEGER NOT NULL DEFAULT 0,
    quality_score INTEGER,
    quality_notes TEXT NOT NULL DEFAULT '',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS media (
    id TEXT PRIMARY KEY,
    candidate_id TEXT NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL,
    source_url TEXT NOT NULL,
    local_path TEXT,
    preview_path TEXT,
    alt_text TEXT NOT NULL DEFAULT '',
    width INTEGER,
    height INTEGER,
    sha256 TEXT,
    media_policy TEXT NOT NULL DEFAULT 'cache',
    attribution_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE(candidate_id, ordinal)
);

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    job_type TEXT NOT NULL,
    status TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    detail_json TEXT NOT NULL DEFAULT '{}',
    started_at TEXT NOT NULL,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id TEXT NOT NULL,
    before_json TEXT,
    after_json TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS candidates_status_idx ON candidates(status, collected_at DESC);
CREATE INDEX IF NOT EXISTS candidates_platform_idx ON candidates(platform, collected_at DESC);
CREATE INDEX IF NOT EXISTS media_candidate_idx ON media(candidate_id, ordinal);
CREATE INDEX IF NOT EXISTS jobs_started_idx ON jobs(started_at DESC);
"""


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(SCHEMA)

    @staticmethod
    def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        result = dict(row)
        for key in ("config_json", "metadata_json", "prompt_variants_json", "attribution_json", "detail_json"):
            if key in result:
                try:
                    result[key.removesuffix("_json")] = json.loads(result[key] or "{}")
                except json.JSONDecodeError:
                    result[key.removesuffix("_json")] = {} if key != "prompt_variants_json" else []
        return result

    def summary(self) -> dict[str, int]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT status, COUNT(*) AS count FROM candidates GROUP BY status"
            ).fetchall()
            source_count = connection.execute(
                "SELECT COUNT(*) FROM sources WHERE enabled=1"
            ).fetchone()[0]
        counts = {row["status"]: row["count"] for row in rows}
        return {
            "pending": sum(counts.get(key, 0) for key in ("pending", "prompt_ready", "needs_review")),
            "approved": counts.get("approved", 0),
            "published": counts.get("published", 0),
            "rejected": counts.get("rejected", 0),
            "enabled_sources": source_count,
        }

    def list_sources(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM sources ORDER BY enabled DESC, platform, label"
            ).fetchall()
        return [self._row(row) for row in rows if row]

    def upsert_source(self, payload: dict[str, Any]) -> dict[str, Any]:
        now = utc_now()
        source_id = payload.get("id") or str(uuid.uuid4())
        config = json.dumps(payload.get("config", {}), ensure_ascii=False)
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO sources (
                    id, platform, source_type, label, locator, enabled,
                    collection_mode, frequency_hours, config_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(platform, locator) DO UPDATE SET
                    source_type=excluded.source_type,
                    label=excluded.label,
                    enabled=excluded.enabled,
                    collection_mode=excluded.collection_mode,
                    frequency_hours=excluded.frequency_hours,
                    config_json=excluded.config_json,
                    updated_at=excluded.updated_at
                """,
                (
                    source_id,
                    payload["platform"],
                    payload.get("source_type", "creator"),
                    payload.get("label") or payload["locator"],
                    payload["locator"],
                    int(payload.get("enabled", True)),
                    payload.get("collection_mode", "api"),
                    int(payload.get("frequency_hours", 24)),
                    config,
                    now,
                    now,
                ),
            )
            row = connection.execute(
                "SELECT * FROM sources WHERE platform=? AND locator=?",
                (payload["platform"], payload["locator"]),
            ).fetchone()
        return self._row(row) or {}

    def update_source_state(self, source_id: str, *, cursor: str | None = None, error: str | None = None) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE sources
                SET last_cursor=COALESCE(?, last_cursor), last_checked_at=?, last_error=?, updated_at=?
                WHERE id=?
                """,
                (cursor, utc_now(), error, utc_now(), source_id),
            )

    def delete_source(self, source_id: str) -> None:
        with self.connect() as connection:
            connection.execute("DELETE FROM sources WHERE id=?", (source_id,))

    def upsert_candidate(self, payload: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        now = utc_now()
        candidate_id = payload.get("id") or str(uuid.uuid4())
        with self.connect() as connection:
            existing = connection.execute(
                "SELECT id FROM candidates WHERE canonical_url=?", (payload["canonical_url"],)
            ).fetchone()
            created = existing is None
            if existing:
                candidate_id = existing["id"]
            connection.execute(
                """
                INSERT INTO candidates (
                    id, source_id, platform, canonical_url, external_id, author, title,
                    source_text, prompt_kind, prompt_status, prompt_variants_json,
                    active_prompt, category_id, category_label, status, rights_status,
                    source_published_at, collected_at, quality_score, quality_notes,
                    metadata_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(canonical_url) DO UPDATE SET
                    author=excluded.author,
                    title=CASE WHEN excluded.title!='' THEN excluded.title ELSE candidates.title END,
                    source_text=CASE WHEN excluded.source_text!='' THEN excluded.source_text ELSE candidates.source_text END,
                    prompt_kind=CASE WHEN candidates.status='published' THEN candidates.prompt_kind ELSE excluded.prompt_kind END,
                    prompt_status=CASE WHEN candidates.status='published' THEN candidates.prompt_status ELSE excluded.prompt_status END,
                    prompt_variants_json=CASE WHEN excluded.prompt_variants_json!='[]' THEN excluded.prompt_variants_json ELSE candidates.prompt_variants_json END,
                    active_prompt=CASE WHEN excluded.active_prompt!='' THEN excluded.active_prompt ELSE candidates.active_prompt END,
                    category_id=COALESCE(excluded.category_id, candidates.category_id),
                    category_label=COALESCE(excluded.category_label, candidates.category_label),
                    quality_score=COALESCE(excluded.quality_score, candidates.quality_score),
                    quality_notes=CASE WHEN excluded.quality_notes!='' THEN excluded.quality_notes ELSE candidates.quality_notes END,
                    metadata_json=excluded.metadata_json,
                    updated_at=excluded.updated_at
                """,
                (
                    candidate_id,
                    payload.get("source_id"),
                    payload["platform"],
                    payload["canonical_url"],
                    payload.get("external_id"),
                    payload.get("author", ""),
                    payload.get("title", ""),
                    payload.get("source_text", ""),
                    payload.get("prompt_kind", "pending"),
                    payload.get("prompt_status", "pending"),
                    json.dumps(payload.get("prompt_variants", []), ensure_ascii=False),
                    payload.get("active_prompt", ""),
                    payload.get("category_id"),
                    payload.get("category_label"),
                    payload.get("status", "pending"),
                    payload.get("rights_status", "review"),
                    payload.get("source_published_at"),
                    payload.get("collected_at", now),
                    payload.get("quality_score"),
                    payload.get("quality_notes", ""),
                    json.dumps(payload.get("metadata", {}), ensure_ascii=False),
                    now,
                ),
            )
            row = connection.execute("SELECT * FROM candidates WHERE id=?", (candidate_id,)).fetchone()
        return self._row(row) or {}, created

    def replace_media(self, candidate_id: str, media_items: list[dict[str, Any]]) -> None:
        with self.connect() as connection:
            connection.execute("DELETE FROM media WHERE candidate_id=?", (candidate_id,))
            for index, item in enumerate(media_items, start=1):
                connection.execute(
                    """
                    INSERT INTO media (
                        id, candidate_id, ordinal, source_url, local_path, preview_path,
                        alt_text, width, height, sha256, media_policy, attribution_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item.get("id") or str(uuid.uuid4()),
                        candidate_id,
                        int(item.get("ordinal", index)),
                        item["source_url"],
                        item.get("local_path"),
                        item.get("preview_path"),
                        item.get("alt_text", ""),
                        item.get("width"),
                        item.get("height"),
                        item.get("sha256"),
                        item.get("media_policy", "cache"),
                        json.dumps(item.get("attribution", {}), ensure_ascii=False),
                    ),
                )

    def list_candidates(self, *, status: str | None = None, query: str = "", limit: int = 200) -> list[dict[str, Any]]:
        where: list[str] = []
        values: list[Any] = []
        if status and status != "all":
            if status == "review":
                where.append("c.status IN ('pending','prompt_ready','needs_review','approved')")
            else:
                where.append("c.status=?")
                values.append(status)
        if query:
            where.append("(c.title LIKE ? OR c.author LIKE ? OR c.canonical_url LIKE ? OR c.active_prompt LIKE ?)")
            term = f"%{query}%"
            values.extend([term, term, term, term])
        clause = " WHERE " + " AND ".join(where) if where else ""
        values.append(max(1, min(limit, 500)))
        with self.connect() as connection:
            rows = connection.execute(
                f"SELECT c.* FROM candidates c{clause} ORDER BY c.collected_at DESC LIMIT ?",
                values,
            ).fetchall()
            result = []
            for row in rows:
                candidate = self._row(row) or {}
                media_rows = connection.execute(
                    "SELECT * FROM media WHERE candidate_id=? ORDER BY ordinal", (candidate["id"],)
                ).fetchall()
                candidate["media"] = [self._row(media) for media in media_rows]
                result.append(candidate)
        return result

    def get_candidate(self, candidate_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM candidates WHERE id=?", (candidate_id,)).fetchone()
            candidate = self._row(row)
            if candidate:
                media_rows = connection.execute(
                    "SELECT * FROM media WHERE candidate_id=? ORDER BY ordinal", (candidate_id,)
                ).fetchall()
                candidate["media"] = [self._row(media) for media in media_rows]
        return candidate

    def update_candidate(self, candidate_id: str, patch: dict[str, Any], action: str = "edit") -> dict[str, Any]:
        allowed = {
            "title", "active_prompt", "prompt_kind", "prompt_status", "category_id",
            "category_label", "status", "rights_status", "quality_score", "quality_notes",
            "hidden", "published_entry_id", "reviewed_at", "prompt_variants_json",
        }
        changes: dict[str, Any] = {}
        for key, value in patch.items():
            if key not in allowed:
                continue
            if key == "prompt_variants_json" and not isinstance(value, str):
                value = json.dumps(value, ensure_ascii=False)
            changes[key] = value
        if not changes:
            candidate = self.get_candidate(candidate_id)
            if candidate is None:
                raise KeyError(candidate_id)
            return candidate
        before = self.get_candidate(candidate_id)
        assignments = ", ".join(f"{key}=?" for key in changes)
        values = list(changes.values()) + [utc_now(), candidate_id]
        with self.connect() as connection:
            connection.execute(
                f"UPDATE candidates SET {assignments}, updated_at=? WHERE id=?", values
            )
            connection.execute(
                """
                INSERT INTO audit_log (action, target_type, target_id, before_json, after_json, created_at)
                VALUES (?, 'candidate', ?, ?, ?, ?)
                """,
                (
                    action,
                    candidate_id,
                    json.dumps(before, ensure_ascii=False, default=str),
                    json.dumps(changes, ensure_ascii=False, default=str),
                    utc_now(),
                ),
            )
        candidate = self.get_candidate(candidate_id)
        if candidate is None:
            raise KeyError(candidate_id)
        return candidate

    def create_job(self, job_type: str) -> str:
        job_id = str(uuid.uuid4())
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO jobs (id, job_type, status, started_at) VALUES (?, ?, 'running', ?)",
                (job_id, job_type, utc_now()),
            )
        return job_id

    def finish_job(self, job_id: str, *, status: str, summary: str, detail: dict[str, Any] | None = None) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE jobs SET status=?, summary=?, detail_json=?, finished_at=? WHERE id=?
                """,
                (status, summary, json.dumps(detail or {}, ensure_ascii=False), utc_now(), job_id),
            )

    def list_jobs(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM jobs ORDER BY started_at DESC LIMIT ?", (max(1, min(limit, 200)),)
            ).fetchall()
        return [self._row(row) for row in rows if row]
