from __future__ import annotations

import hmac
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, Cookie, Depends, FastAPI, File, Form, HTTPException, Query, Response, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .auth import COOKIE_NAME, create_session, verify_session
from .categories import CATEGORIES
from .config import CONTROL_ROOT, settings
from .db import Database, utc_now
from .pipeline import CollectionPipeline
from .repository import GalleryRepository


settings.ensure_directories()
database = Database(settings.database_path)
pipeline = CollectionPipeline(settings, database)
repository = GalleryRepository(settings, database)

app = FastAPI(title="Prompt Gallery Control", docs_url=None, redoc_url=None)


class LoginRequest(BaseModel):
    password: str


class SourceRequest(BaseModel):
    id: str | None = None
    platform: str
    source_type: str = "creator"
    label: str
    locator: str
    enabled: bool = True
    collection_mode: str = "api"
    frequency_hours: int = Field(default=24, ge=1, le=168)
    config: dict[str, Any] = Field(default_factory=dict)


class CandidatePatch(BaseModel):
    title: str | None = None
    active_prompt: str | None = None
    prompt_kind: str | None = None
    prompt_status: str | None = None
    prompt_variants_json: list[dict[str, Any]] | None = None
    category_id: str | None = None
    category_label: str | None = None
    status: str | None = None
    rights_status: str | None = None
    hidden: bool | None = None
    quality_notes: str | None = None


class ManualImportRequest(BaseModel):
    platform: str
    canonical_url: str
    author: str = ""
    title: str
    source_text: str = ""
    media_urls: list[str]
    prompt: str = ""
    rights_confirmed: bool = False


class LinkImportRequest(BaseModel):
    url: str
    rights_confirmed: bool = False


class PublishedPatch(BaseModel):
    title: str | None = None
    title_en: str | None = None
    prompt: str | None = None
    prompt_label: str | None = None
    category_id: str | None = None
    hidden: bool | None = None


class PublishRequest(BaseModel):
    candidate_ids: list[str] = Field(default_factory=list)
    commit_message: str = "Publish reviewed gallery references"


def require_admin(session: str | None = Cookie(default=None, alias=COOKIE_NAME)) -> None:
    if not session or not verify_session(session, settings.session_secret):
        raise HTTPException(status_code=401, detail="Authentication required")


def run_collection() -> None:
    pipeline.collect_all()


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "database": str(settings.database_path),
        "repo": str(settings.repo_root),
        "openai_ready": bool(settings.openai_api_key),
        "x_ready": bool(settings.x_bearer_token),
        "unsafe_defaults": settings.admin_password == "change-me" or settings.session_secret == "development-only-secret",
    }


@app.post("/api/session")
def login(payload: LoginRequest, response: Response) -> dict[str, bool]:
    if not hmac.compare_digest(payload.password, settings.admin_password):
        raise HTTPException(status_code=401, detail="Password is incorrect")
    token = create_session(settings.session_secret)
    response.set_cookie(
        COOKIE_NAME,
        token,
        httponly=True,
        secure=settings.secure_cookie,
        samesite="strict",
        max_age=60 * 60 * 12,
        path="/",
    )
    return {"ok": True}


@app.delete("/api/session")
def logout(response: Response) -> dict[str, bool]:
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


@app.get("/api/me", dependencies=[Depends(require_admin)])
def me() -> dict[str, Any]:
    return {"authenticated": True, "role": "administrator"}


@app.get("/api/summary", dependencies=[Depends(require_admin)])
def summary() -> dict[str, Any]:
    queue = database.summary()
    public = repository.validate()
    return {"queue": queue, "public": public}


@app.get("/api/categories", dependencies=[Depends(require_admin)])
def categories() -> list[dict[str, str]]:
    return [{"id": item.id, "label": item.label, "english": item.english} for item in CATEGORIES]


@app.get("/api/sources", dependencies=[Depends(require_admin)])
def list_sources() -> list[dict[str, Any]]:
    return database.list_sources()


@app.post("/api/sources", dependencies=[Depends(require_admin)])
def save_source(payload: SourceRequest) -> dict[str, Any]:
    return database.upsert_source(payload.model_dump())


@app.delete("/api/sources/{source_id}", dependencies=[Depends(require_admin)])
def delete_source(source_id: str) -> dict[str, bool]:
    database.delete_source(source_id)
    return {"ok": True}


@app.post("/api/collect", dependencies=[Depends(require_admin)])
def collect(background_tasks: BackgroundTasks) -> dict[str, str]:
    background_tasks.add_task(run_collection)
    return {"status": "started"}


@app.get("/api/jobs", dependencies=[Depends(require_admin)])
def jobs(limit: int = Query(default=50, ge=1, le=200)) -> list[dict[str, Any]]:
    return database.list_jobs(limit)


@app.get("/api/candidates", dependencies=[Depends(require_admin)])
def candidates(
    status: str = "review",
    q: str = "",
    limit: int = Query(default=200, ge=1, le=500),
) -> list[dict[str, Any]]:
    return database.list_candidates(status=status, query=q, limit=limit)


@app.get("/api/candidates/{candidate_id}", dependencies=[Depends(require_admin)])
def candidate(candidate_id: str) -> dict[str, Any]:
    result = database.get_candidate(candidate_id)
    if not result:
        raise HTTPException(status_code=404, detail="Candidate not found")
    return result


@app.get("/api/media/{candidate_id}/{filename}", dependencies=[Depends(require_admin)])
def candidate_media(candidate_id: str, filename: str) -> FileResponse:
    folder = (settings.spool_path / candidate_id).resolve()
    path = (folder / Path(filename).name).resolve()
    if folder not in path.parents or not path.exists():
        raise HTTPException(status_code=404, detail="Media not found")
    return FileResponse(path)


@app.patch("/api/candidates/{candidate_id}", dependencies=[Depends(require_admin)])
def update_candidate(candidate_id: str, payload: CandidatePatch) -> dict[str, Any]:
    patch = payload.model_dump(exclude_none=True)
    if patch.get("status") == "approved":
        patch["reviewed_at"] = utc_now()
    try:
        return database.update_candidate(candidate_id, patch, action="admin_edit")
    except KeyError:
        raise HTTPException(status_code=404, detail="Candidate not found") from None


@app.post("/api/import", dependencies=[Depends(require_admin)])
def manual_import(payload: ManualImportRequest) -> dict[str, Any]:
    try:
        candidate, created = pipeline.ingest_manual(**payload.model_dump())
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {"created": created, "candidate": candidate}


@app.post("/api/import-link", dependencies=[Depends(require_admin)])
def import_link(payload: LinkImportRequest) -> dict[str, Any]:
    try:
        candidate, created = pipeline.ingest_url(
            payload.url.strip(), rights_confirmed=payload.rights_confirmed
        )
    except (ValueError, RuntimeError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {"created": created, "candidate": candidate}


@app.post("/api/import-upload", dependencies=[Depends(require_admin)])
async def import_upload(
    platform: str = Form(...),
    canonical_url: str = Form(...),
    author: str = Form(""),
    title: str = Form(...),
    source_text: str = Form(""),
    prompt: str = Form(""),
    rights_confirmed: bool = Form(False),
    images: list[UploadFile] = File(...),
) -> dict[str, Any]:
    import uuid

    upload_dir = settings.spool_path / "_uploads" / str(uuid.uuid4())
    upload_dir.mkdir(parents=True, exist_ok=True)
    media_urls = []
    for index, image in enumerate(images, start=1):
        suffix = Path(image.filename or "image.jpg").suffix or ".jpg"
        path = upload_dir / f"upload-{index:02d}{suffix}"
        path.write_bytes(await image.read())
        media_urls.append(f"file://{path}")
    try:
        candidate, created = pipeline.ingest_manual(
            platform=platform,
            canonical_url=canonical_url,
            author=author,
            title=title,
            source_text=source_text,
            media_urls=media_urls,
            prompt=prompt,
            rights_confirmed=rights_confirmed,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {"created": created, "candidate": candidate}


@app.get("/api/published", dependencies=[Depends(require_admin)])
def published(q: str = "", include_hidden: bool = True) -> list[dict[str, Any]]:
    entries = repository.list_entries(include_hidden=include_hidden)
    if q:
        needle = q.lower()
        entries = [
            entry for entry in entries
            if needle in " ".join(
                [entry.get("title", ""), entry.get("title_en", ""), entry.get("source_url", ""), entry.get("prompt", "")]
            ).lower()
        ]
    return entries[:500]


@app.patch("/api/published/{entry_id}", dependencies=[Depends(require_admin)])
def update_published(entry_id: str, payload: PublishedPatch) -> dict[str, bool]:
    patch = payload.model_dump(exclude_none=True)
    try:
        if "title" in patch or "title_en" in patch:
            current = next((item for item in repository.list_entries() if item["id"] == entry_id), None)
            if not current:
                raise KeyError(entry_id)
            repository.update_title(
                entry_id,
                patch.get("title", current["title"]),
                patch.get("title_en", current["title_en"]),
            )
        if "prompt" in patch:
            repository.update_prompt(entry_id, patch["prompt"], patch.get("prompt_label"))
        if "category_id" in patch:
            repository.move_entry(entry_id, patch["category_id"])
        if "hidden" in patch:
            repository.set_hidden(entry_id, patch["hidden"])
    except (KeyError, ValueError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {"ok": True}


@app.delete("/api/published/{entry_id}", dependencies=[Depends(require_admin)])
def delete_published(entry_id: str) -> dict[str, bool]:
    try:
        repository.delete_entry(entry_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return {"ok": True}


@app.post("/api/publish", dependencies=[Depends(require_admin)])
def publish(payload: PublishRequest) -> dict[str, Any]:
    if payload.candidate_ids:
        for candidate_id in payload.candidate_ids:
            candidate = database.get_candidate(candidate_id)
            if not candidate:
                raise HTTPException(status_code=404, detail=f"Candidate not found: {candidate_id}")
            if candidate.get("status") != "approved":
                database.update_candidate(
                    candidate_id,
                    {"status": "approved", "reviewed_at": utc_now()},
                    action="approve_for_publish",
                )
        entry_ids = repository.publish_candidates(payload.candidate_ids)
    else:
        entry_ids = []
    repository.build_blanc()
    validation = repository.validate()
    sha = repository.commit_and_push(payload.commit_message)
    return {"ok": True, "entry_ids": entry_ids, "validation": validation, "commit": sha}


WEB_ROOT = CONTROL_ROOT / "web"
app.mount("/admin/assets", StaticFiles(directory=WEB_ROOT), name="admin-assets")


@app.get("/admin/")
def admin_page() -> FileResponse:
    return FileResponse(WEB_ROOT / "index.html")


@app.get("/")
def root() -> RedirectResponse:
    return RedirectResponse("/admin/")
