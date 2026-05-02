"""Runtime settings for the Jarvis bot.

Mirrors the pattern used by `app/config.py`: pydantic-settings reading
from environment variables (and optionally a .env file), with required
fields typed without defaults so a missing env var fails loudly at
construction. Optional fields used only by later PRs (anthropic_api_key,
jarvis_post_secret) default to None so importing this module never
crashes a PR-1-only install.
"""

from __future__ import annotations

from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    discord_bot_token: str
    discord_guild_id: int

    anthropic_api_key: Optional[str] = None
    jarvis_post_secret: Optional[str] = None
    jarvis_http_port: int = 8080
    jarvis_log_level: str = "INFO"

    # Firestore project ID. Optional — google-cloud-firestore auto-detects
    # from credentials (gcloud ADC locally, metadata server on GCE). Set
    # explicitly only when you need to override (e.g., dev pointing at a
    # staging project).
    gcp_project_id: Optional[str] = None

    # GitHub credentials (PR 3a). Token is a PAT with read:org / repo
    # scope (or fine-grained equivalent). PR 5 swaps to a GitHub App
    # whose private key lives in Secret Manager — this PAT path is the
    # bridging step.
    github_token: Optional[str] = None
    github_repo: str = "tsuki-works/niko"
    github_project_id: str = "PVT_kwDOEIgWQM4BVBdK"

    commit_sha: str = ""


def get_settings() -> Settings:
    """Single accessor — useful for tests that want to monkeypatch."""
    return Settings()
