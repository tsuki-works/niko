"""Runtime settings loaded from environment variables.

All third-party credentials the POC will consume live here. Credential
fields are ``Optional`` because services are wired in across multiple
sprints — a missing key shouldn't crash import of unrelated modules.
Each service module that needs a key should assert it at use time.
Non-credential config fields (model IDs, voice IDs) use ``str`` with
safe defaults so they never need a None-guard.
"""

from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    anthropic_api_key: Optional[str] = None

    deepgram_api_key: Optional[str] = None

    # Deepgram Aura TTS voice/model. The model name encodes both the model
    # generation (aura-2) and the voice (thalia — warm, conversational female).
    # Browse voices at https://developers.deepgram.com/docs/tts-models and
    # override via DEEPGRAM_TTS_MODEL.
    deepgram_tts_model: str = "aura-2-thalia-en"

    twilio_account_sid: Optional[str] = None
    twilio_auth_token: Optional[str] = None
    twilio_phone_number: Optional[str] = None

    # Public HTTPS base URL of this service (e.g. "https://niko-xyz.run.app"
    # or an ngrok URL locally). Required for Twilio recording callbacks:
    # the URL we hand Twilio when starting a recording must equal the URL
    # we reconstruct in /recording-status to validate Twilio's signature.
    # Building it from the request's Host header would defeat the
    # signature check, since the Host header is client-controlled.
    public_base_url: Optional[str] = None

    # Recordings bucket. Phase 2 default; can be overridden via env if we
    # ever split prod/dev/staging buckets.
    recordings_bucket: str = "niko-recordings"

    # Default retention applied at upload time when a Restaurant doc
    # doesn't carry its own ``recording_retention_days`` field. The bucket
    # lifecycle rule deletes blobs whose ``custom_time`` has passed.
    recording_default_retention_days: int = 90

    square_access_token: Optional[str] = None
    square_application_id: Optional[str] = None

    # Enables dev-only routes like POST /dev/seed-order. Must stay false
    # in production; flip to true locally or in a preview env when the
    # dashboard needs seed data before the voice loop is wired up.
    niko_dev_endpoints: bool = False

    # Set by the deploy pipeline to the git commit SHA. Used to surface
    # the build version in the dashboard and (when testing_mode=True) as
    # a spoken announcement at call start.
    commit_sha: str = ""
    testing_mode: bool = False


settings = Settings()
