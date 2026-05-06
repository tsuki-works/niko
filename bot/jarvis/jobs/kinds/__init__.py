"""Kind registry. Kinds register themselves at import time."""

from __future__ import annotations

from jarvis.jobs import KindHandler

KIND_REGISTRY: dict[str, KindHandler] = {}


def register_kind(name: str, handler: KindHandler) -> None:
    if name in KIND_REGISTRY:
        raise ValueError(f"kind '{name}' already registered")
    KIND_REGISTRY[name] = handler
