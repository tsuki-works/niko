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

    # LLM provider selector. Today only "anthropic" is implemented; the
    # selector seam exists so a second provider becomes a one-line add
    # to app/llm/__init__.py.
    llm_provider: str = "anthropic"

    # Anthropic model + reply cap. Was hardcoded as module constants in
    # app/llm/client.py; pulled into config so a model swap (Haiku →
    # Sonnet → Opus) is an env change, not a code edit.
    anthropic_model: str = "claude-haiku-4-5-20251001"
    anthropic_max_tokens: int = 512

    deepgram_api_key: Optional[str] = None

    # Deepgram Aura TTS voice/model. The model name encodes both the model
    # generation (aura-2) and the voice (thalia — warm, conversational female).
    # Browse voices at https://developers.deepgram.com/docs/tts-models and
    # override via DEEPGRAM_TTS_MODEL.
    deepgram_tts_model: str = "aura-2-thalia-en"

    # TTS provider selector. Today only "deepgram" is implemented; the
    # selector seam exists so a second provider becomes a one-line add
    # to app/tts/__init__.py.
    tts_provider: str = "deepgram"

    # STT provider selector. Today only "deepgram" is implemented.
    stt_provider: str = "deepgram"

    # Deepgram live STT options. Migrated to Flux English mono in #257.
    # Flux owns turn detection natively (prosody-aware, ~260ms confirmed
    # end-of-turn); the knobs below override Flux's own defaults.
    stt_model: str = "flux-general-en"
    # Confidence threshold to confirm end-of-turn. Flux default is 0.7;
    # 0.8 reduces false cut-offs on mid-sentence pauses.
    stt_eot_threshold: float = 0.8
    # Max silence (ms) before Flux forces end-of-turn. Flux default is 5000;
    # 4000 keeps latency tighter without clipping normal speech.
    stt_eot_timeout_ms: int = 4000
    # Optional early end-of-turn confidence gate. None = let Flux decide;
    # set e.g. 0.95 to cut off turn aggressively on high-confidence pauses.
    stt_eager_eot_threshold: Optional[float] = None
    # Comma-separated debug-override keyterms. When non-empty, REPLACES
    # the per-tenant heuristic output entirely (used to A/B test what
    # Flux does with a specific term list). Empty in production —
    # session.py computes keyterms from each restaurant's menu.
    stt_keyterms: str = ""

    # Instant barge-in. When True (default), a barge-in fires as soon as
    # the STT provider signals "user started speaking" (Flux fires
    # `TurnInfo.event="StartOfTurn"` on the first frame of detected
    # speech) instead of waiting for the confirmed final transcript.
    # Flip to False if the start-of-turn signal turns out to misfire
    # on coughs or background noise on real calls — the
    # final-transcript path in _handle_final_transcript absorbs the
    # fallback case with no other code changes.
    stt_instant_barge_in: bool = True

    twilio_account_sid: Optional[str] = None
    twilio_auth_token: Optional[str] = None
    twilio_phone_number: Optional[str] = None

    # Twilio Messaging Service SID for outbound SMS. Shared 10DLC pool
    # for pilot; per-tenant brand registration deferred until pilot ramp.
    # Required when wiring outbound SMS in Sprint 2.4 (#7) — None elsewhere
    # so importing this module doesn't crash environments that don't
    # send SMS yet.
    twilio_messaging_service_sid: Optional[str] = None

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

    # Local-dev only: when set to a directory path, the /media-stream WS
    # handler dumps each call's inbound (caller-side) mulaw audio to
    # ``<dir>/<call_sid>_<started_at>.ulaw``. Empty/unset in production —
    # ``app.dev.audio_dump.open_caller_dump`` returns None and the dump
    # path becomes a no-op. Designed to feed ``scripts/replay_stt.py``
    # for offline STT A/B testing without touching the GCS recording path.
    niko_local_audio_dump_dir: Optional[str] = None

    # Set by the deploy pipeline to the git commit SHA. Used to surface
    # the build version in the dashboard and (when testing_mode=True) as
    # a spoken announcement at call start.
    commit_sha: str = ""
    testing_mode: bool = False


settings = Settings()
