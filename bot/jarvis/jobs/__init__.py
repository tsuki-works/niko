"""Core types for the scheduled-jobs framework.

Manifest entries are `Job` dataclasses. Kinds are async callables that
take a `KindContext` and return a `KindResult` — a list of `PlannedPost`s
the executor will send, plus state writes and a one-line self-report
summary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Awaitable, Callable, Optional


@dataclass(frozen=True)
class Job:
    name: str
    kind: str
    cron: str
    channel: str
    timezone: str = "America/Toronto"
    params: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True


@dataclass
class PlannedPost:
    content: str
    dedup_key: Optional[str] = None


@dataclass
class KindResult:
    posts: list[PlannedPost]
    state_writes: dict[str, Any] = field(default_factory=dict)
    summary: str = ""


@dataclass
class KindContext:
    job: Job
    discord_channel: Any
    github_client: Any
    anthropic_client: Any
    state: Any
    now: datetime
    settings: Any
    logger: Any


KindHandler = Callable[[KindContext], Awaitable[KindResult]]
