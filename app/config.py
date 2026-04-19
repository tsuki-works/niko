"""Runtime settings loaded from environment variables.

All third-party credentials the POC will consume live here. Fields are
``Optional`` because services are wired in across multiple sprints — a
missing key shouldn't crash import of unrelated modules. Each service
module that needs a key should assert it at use time.
"""

from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    anthropic_api_key: Optional[str] = None

    deepgram_api_key: Optional[str] = None

    elevenlabs_api_key: Optional[str] = None

    twilio_account_sid: Optional[str] = None
    twilio_auth_token: Optional[str] = None
    twilio_phone_number: Optional[str] = None

    square_access_token: Optional[str] = None
    square_application_id: Optional[str] = None


settings = Settings()
