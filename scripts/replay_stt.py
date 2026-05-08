"""Local STT replay tool — feed a captured caller-audio file through
Deepgram and print transcripts.

Usage::

    python scripts/replay_stt.py PATH.ulaw [options]

The audio file must be raw mulaw 8 kHz mono with no header — the same
bytes Twilio's media stream delivers and Deepgram's ``send_media``
consumes. Files written by ``app.dev.audio_dump.CallerAudioDump`` are
in this format directly; no conversion needed.

This script talks to Deepgram via the ``deepgram-sdk`` package and is
deliberately **standalone** — it does NOT import ``app.deepgram.stt``.
That keeps production STT untouched and lets the script swap between
v1 (Nova) and v2 (Flux) endpoints freely for offline A/B testing.

Single-config mode::

    python scripts/replay_stt.py call.ulaw --model flux-general-en \\
        --keyterms "Niko's Pizza,pickup,Can I" --pace realtime

Sweep mode (run N configs against the same file, print a comparison
table)::

    python scripts/replay_stt.py call.ulaw --sweep configs.json

The sweep file is a JSON list of objects, each with ``model`` and
``keyterms`` (a list of strings). See the docstring on ``run_sweep``
for the exact shape.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

# Ensure ``app`` is importable when running from the repo root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from deepgram import AsyncDeepgramClient

# Mulaw 8 kHz: 1 byte = 1 sample, 20 ms = 160 samples = 160 bytes.
FRAME_SIZE_BYTES = 160
FRAME_DURATION_S = 0.020

V2_MODELS = {"flux-general-en", "flux-general-multi"}


@dataclass
class ReplayResult:
    """Outcome of one replay run."""

    model: str
    keyterms: list[str]
    finals: list[tuple[str, float]] = field(default_factory=list)
    error: Optional[str] = None

    @property
    def first_final(self) -> tuple[str, float] | None:
        return self.finals[0] if self.finals else None


def _api_key() -> str:
    key = os.getenv("DEEPGRAM_API_KEY", "").strip()
    if not key:
        sys.exit("DEEPGRAM_API_KEY not set. Add it to .env or export it before running.")
    return key


def _read_frames(path: str) -> list[bytes]:
    """Read the entire file and split into 20 ms mulaw frames.

    For audio short enough to fit in memory (typical call: a few MB)
    this is simpler than streaming I/O. Trailing partial frames are
    padded with mulaw silence (0xFF) so Flux's frame-aligned pipeline
    doesn't see a short final frame.
    """
    with open(path, "rb") as f:
        data = f.read()
    if not data:
        sys.exit(f"replay: input file is empty: {path}")
    frames: list[bytes] = []
    for i in range(0, len(data), FRAME_SIZE_BYTES):
        chunk = data[i : i + FRAME_SIZE_BYTES]
        if len(chunk) < FRAME_SIZE_BYTES:
            chunk = chunk + b"\xff" * (FRAME_SIZE_BYTES - len(chunk))
        frames.append(chunk)
    return frames


def _avg_word_conf(words: Any) -> float:
    """Average word-level confidence; 1.0 fallback when missing."""
    if not words:
        return 1.0
    confs: list[float] = []
    for w in words:
        if isinstance(w, dict):
            c = w.get("confidence")
        else:
            c = getattr(w, "confidence", None)
        if c is None:
            continue
        try:
            confs.append(float(c))
        except (TypeError, ValueError):
            pass
    if confs:
        return sum(confs) / len(confs)
    return 1.0


async def _pump_frames(conn: Any, frames: Sequence[bytes], pace: str) -> None:
    """Send all frames to Deepgram, then close-stream."""
    if pace == "realtime":
        start = time.monotonic()
        for i, frame in enumerate(frames):
            target = start + (i + 1) * FRAME_DURATION_S
            await conn.send_media(frame)
            now = time.monotonic()
            if now < target:
                await asyncio.sleep(target - now)
    else:
        for frame in frames:
            await conn.send_media(frame)
    await conn.send_close_stream()


async def _run_v2(
    *,
    api_key: str,
    model: str,
    keyterms: list[str],
    frames: Sequence[bytes],
    pace: str,
    verbose: bool,
) -> ReplayResult:
    """Replay through Flux (v2) endpoint."""
    result = ReplayResult(model=model, keyterms=list(keyterms))
    client = AsyncDeepgramClient(api_key=api_key)
    cm = client.listen.v2.connect(
        model=model,
        encoding="mulaw",
        sample_rate=8000,
        keyterm=keyterms or None,
    )
    async with cm as conn:
        pump = asyncio.create_task(_pump_frames(conn, frames, pace))
        try:
            while True:
                msg = await conn.recv()
                msg_type = msg.get("type") if isinstance(msg, dict) else getattr(msg, "type", None)
                if msg_type == "Connected":
                    if verbose:
                        rid = (
                            msg.get("request_id")
                            if isinstance(msg, dict)
                            else getattr(msg, "request_id", "?")
                        )
                        print(f"[connected request_id={rid}]")
                    continue
                if msg_type == "TurnInfo":
                    event = msg.get("event") if isinstance(msg, dict) else getattr(msg, "event", "")
                    text = (
                        msg.get("transcript")
                        if isinstance(msg, dict)
                        else getattr(msg, "transcript", "")
                    ) or ""
                    text = text.strip()
                    if event == "Update" and verbose and text:
                        print(f"[interim] {text}")
                    elif event == "EndOfTurn" and text:
                        words = (
                            msg.get("words", [])
                            if isinstance(msg, dict)
                            else getattr(msg, "words", [])
                        )
                        conf = _avg_word_conf(words)
                        result.finals.append((text, conf))
                        print(f"[final  ] {text}   conf={conf:.2f}")
                    continue
                if msg_type in ("ConfigureFailure", "FatalError"):
                    err = f"{msg_type}: {msg}"
                    result.error = err
                    print(f"[error] {err}", file=sys.stderr)
                    break
        except Exception as exc:
            # Connection closed after close-stream — normal exit path.
            if not pump.done() or not result.finals:
                result.error = f"recv error: {exc!r}"
        finally:
            if not pump.done():
                pump.cancel()
                try:
                    await pump
                except (asyncio.CancelledError, Exception):
                    pass
    return result


async def _run_v1(
    *,
    api_key: str,
    model: str,
    keyterms: list[str],
    frames: Sequence[bytes],
    pace: str,
    verbose: bool,
) -> ReplayResult:
    """Replay through Nova (v1) endpoint."""
    result = ReplayResult(model=model, keyterms=list(keyterms))
    client = AsyncDeepgramClient(api_key=api_key)
    # v1 supports keyterm only on Nova-3; Nova-2 silently ignores it
    # (which is what we want for the "Nova-2 baseline" config).
    #
    # Boolean-shaped params on v1 must be the *strings* ``"true"`` /
    # ``"false"`` — the SDK doesn't coerce Python ``bool`` and the
    # server returns 400 if it gets an int/bool. Numeric params accept
    # ``int``. (Confirmed empirically against deepgram-sdk 7.0.1.)
    kwargs: dict[str, Any] = dict(
        model=model,
        encoding="mulaw",
        sample_rate=8000,
        interim_results="true",
        utterance_end_ms=1000,
        endpointing=800,
        vad_events="true",
        smart_format="false",
        punctuate="true",
    )
    if keyterms:
        kwargs["keyterm"] = keyterms

    cm = client.listen.v1.connect(**kwargs)
    async with cm as conn:
        pump = asyncio.create_task(_pump_frames(conn, frames, pace))
        try:
            while True:
                msg = await conn.recv()
                msg_type = msg.get("type") if isinstance(msg, dict) else getattr(msg, "type", None)
                if msg_type == "Results":
                    is_final = (
                        msg.get("is_final")
                        if isinstance(msg, dict)
                        else getattr(msg, "is_final", False)
                    )
                    channel = (
                        msg.get("channel", {})
                        if isinstance(msg, dict)
                        else getattr(msg, "channel", None)
                    )
                    alts = (
                        channel.get("alternatives", [])
                        if isinstance(channel, dict)
                        else getattr(channel, "alternatives", [])
                    ) or []
                    if not alts:
                        continue
                    alt = alts[0]
                    text = (
                        alt.get("transcript")
                        if isinstance(alt, dict)
                        else getattr(alt, "transcript", "")
                    ) or ""
                    text = text.strip()
                    if not text:
                        continue
                    if is_final:
                        conf = (
                            alt.get("confidence")
                            if isinstance(alt, dict)
                            else getattr(alt, "confidence", None)
                        )
                        try:
                            conf_f = float(conf) if conf is not None else 1.0
                        except (TypeError, ValueError):
                            conf_f = 1.0
                        result.finals.append((text, conf_f))
                        print(f"[final  ] {text}   conf={conf_f:.2f}")
                    elif verbose:
                        print(f"[interim] {text}")
                    continue
                if msg_type == "Metadata" and verbose:
                    rid = (
                        msg.get("request_id")
                        if isinstance(msg, dict)
                        else getattr(msg, "request_id", "?")
                    )
                    print(f"[connected request_id={rid}]")
                    continue
                if msg_type == "UtteranceEnd" and verbose:
                    print("[utterance_end]")
                    continue
        except Exception as exc:
            if not pump.done() or not result.finals:
                result.error = f"recv error: {exc!r}"
        finally:
            if not pump.done():
                pump.cancel()
                try:
                    await pump
                except (asyncio.CancelledError, Exception):
                    pass
    return result


async def run_one(
    *,
    path: str,
    model: str,
    keyterms: list[str],
    pace: str,
    verbose: bool,
) -> ReplayResult:
    api_key = _api_key()
    frames = _read_frames(path)
    if verbose:
        print(
            f"[opening {model}: {len(frames)} frames "
            f"({len(frames) * FRAME_DURATION_S:.1f}s), keyterms={len(keyterms)}]"
        )
    if model in V2_MODELS:
        return await _run_v2(
            api_key=api_key,
            model=model,
            keyterms=keyterms,
            frames=frames,
            pace=pace,
            verbose=verbose,
        )
    return await _run_v1(
        api_key=api_key,
        model=model,
        keyterms=keyterms,
        frames=frames,
        pace=pace,
        verbose=verbose,
    )


async def run_sweep(
    *,
    path: str,
    sweep_file: str,
    pace: str,
    verbose: bool,
) -> list[ReplayResult]:
    """Run multiple configs against the same audio file.

    Sweep file format::

        [
          {"model": "flux-general-en", "keyterms": []},
          {"model": "flux-general-en", "keyterms": ["Niko's Pizza", "pickup"]},
          {"model": "nova-2", "keyterms": []},
          {"model": "nova-3-general", "keyterms": ["pickup", "Can I"]}
        ]
    """
    with open(sweep_file, "r", encoding="utf-8") as f:
        configs = json.load(f)
    if not isinstance(configs, list):
        sys.exit("sweep: top-level JSON must be a list of {model, keyterms} objects")

    results: list[ReplayResult] = []
    for i, cfg in enumerate(configs, start=1):
        model = cfg.get("model")
        keyterms = cfg.get("keyterms", [])
        if not model:
            print(f"[skip config #{i}: missing 'model']", file=sys.stderr)
            continue
        if not isinstance(keyterms, list):
            print(f"[skip config #{i}: 'keyterms' must be a list]", file=sys.stderr)
            continue
        print(f"\n=== config {i}/{len(configs)}: model={model}, keyterms={len(keyterms)} ===")
        result = await run_one(
            path=path,
            model=model,
            keyterms=list(keyterms),
            pace=pace,
            verbose=verbose,
        )
        results.append(result)
    return results


def _print_sweep_table(results: list[ReplayResult]) -> None:
    if not results:
        return
    print("\n" + "=" * 80)
    print("SWEEP COMPARISON")
    print("=" * 80)
    header = f"{'#':>2}  {'model':<20}  {'kt':>3}  {'first_final_transcript':<40}  {'conf':>5}"
    print(header)
    print("-" * len(header))
    for i, r in enumerate(results, start=1):
        if r.error:
            row = (
                f"{i:>2}  {r.model:<20}  {len(r.keyterms):>3}  ERROR: {r.error[:40]:<40}  {'-':>5}"
            )
        elif r.first_final:
            text, conf = r.first_final
            display = text if len(text) <= 40 else text[:37] + "..."
            row = f"{i:>2}  {r.model:<20}  {len(r.keyterms):>3}  {display:<40}  {conf:>5.2f}"
        else:
            row = f"{i:>2}  {r.model:<20}  {len(r.keyterms):>3}  {'(no final transcript)':<40}  {'-':>5}"
        print(row)
    print("=" * 80)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Replay a captured caller-audio file through Deepgram.",
    )
    p.add_argument("path", help="Path to a raw mulaw 8 kHz file (.ulaw).")
    p.add_argument(
        "--model",
        default="flux-general-en",
        help="Deepgram model. Flux: flux-general-en. Nova: nova-2, nova-3-general. (default: %(default)s)",
    )
    p.add_argument(
        "--keyterms",
        default="",
        help="Comma-separated keyterms to bias recognition (single-config mode).",
    )
    p.add_argument(
        "--pace",
        choices=("realtime", "fast"),
        default="realtime",
        help="realtime = 20ms between frames (matches a live call); fast = no pacing. (default: %(default)s)",
    )
    p.add_argument(
        "--sweep",
        default=None,
        help="Path to a JSON file with N configs; runs each and prints a comparison table.",
    )
    p.add_argument(
        "--verbose",
        action="store_true",
        help="Print interim transcripts and connection metadata.",
    )
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    if not os.path.isfile(args.path):
        sys.exit(f"replay: input file not found: {args.path}")

    if args.sweep:
        results = asyncio.run(
            run_sweep(
                path=args.path,
                sweep_file=args.sweep,
                pace=args.pace,
                verbose=args.verbose,
            )
        )
        _print_sweep_table(results)
        return

    keyterms = [t.strip() for t in args.keyterms.split(",") if t.strip()]
    asyncio.run(
        run_one(
            path=args.path,
            model=args.model,
            keyterms=keyterms,
            pace=args.pace,
            verbose=args.verbose,
        )
    )


if __name__ == "__main__":
    main()
