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

    square_access_token: Optional[str] = None
    square_application_id: Optional[str] = None

    # Enables dev-only routes like POST /dev/seed-order. Must stay false
    # in production; flip to true locally or in a preview env when the
    # dashboard needs seed data before the voice loop is wired up.
    niko_dev_endpoints: bool = False


settings = Settings()
