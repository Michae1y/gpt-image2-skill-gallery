from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


CONTROL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPO_ROOT = CONTROL_ROOT.parent


def _bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    repo_root: Path = Path(os.getenv("GALLERY_REPO_ROOT", DEFAULT_REPO_ROOT)).resolve()
    database_path: Path = Path(
        os.getenv("GALLERY_DB_PATH", CONTROL_ROOT / "data" / "gallery.db")
    ).resolve()
    spool_path: Path = Path(
        os.getenv("GALLERY_SPOOL_PATH", CONTROL_ROOT / "spool")
    ).resolve()
    admin_password: str = os.getenv("GALLERY_ADMIN_PASSWORD", "change-me")
    session_secret: str = os.getenv("GALLERY_SESSION_SECRET", "development-only-secret")
    secure_cookie: bool = _bool("GALLERY_SECURE_COOKIE", False)
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    vision_model: str = os.getenv("GALLERY_VISION_MODEL", "gpt-5.5")
    image_model: str = os.getenv("GALLERY_IMAGE_MODEL", "gpt-image-2")
    render_back_enabled: bool = _bool("GALLERY_RENDER_BACK_ENABLED", False)
    fidelity_threshold: int = int(os.getenv("GALLERY_FIDELITY_THRESHOLD", "88"))
    x_bearer_token: str = os.getenv("X_BEARER_TOKEN", "")
    unsplash_access_key: str = os.getenv("UNSPLASH_ACCESS_KEY", "")
    wallhaven_api_key: str = os.getenv("WALLHAVEN_API_KEY", "")
    git_push_enabled: bool = _bool("GALLERY_GIT_PUSH", False)
    git_remote: str = os.getenv("GALLERY_GIT_REMOTE", "origin")
    git_branch: str = os.getenv("GALLERY_GIT_BRANCH", "main")
    schedule_hour: int = int(os.getenv("GALLERY_SCHEDULE_HOUR", "9"))
    schedule_minute: int = int(os.getenv("GALLERY_SCHEDULE_MINUTE", "30"))

    def ensure_directories(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.spool_path.mkdir(parents=True, exist_ok=True)


settings = Settings()
