"""Multi-config Deepgram STT comparison harness for issue #279.

Replays each ``dev_recordings/*.ulaw`` file through three Deepgram
configurations concurrently (Flux, Nova-2, Nova-3) at realtime pace,
captures per-final wall-clock latency and confidence, and writes a
markdown report under ``docs/superpowers/specs/`` so the team can
decide whether to migrate from Flux.

This script is intentionally separate from ``scripts/replay_stt.py`` —
that tool is the stable single-call inspector and shouldn't change.

Usage::

    .venv\\Scripts\\python.exe scripts/replay_compare_stt.py

The set of audio files and the three configs are baked in (see
``AUDIO_FILES`` and ``CONFIGS`` at the top of the file). Per-call
progress streams to stdout; the markdown report is written at the end.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import statistics
import sys
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

# Ensure ``app`` is importable when running from the repo root.
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from deepgram import AsyncDeepgramClient

from app.restaurants.keyterms import compute_keyterms

# Mulaw 8 kHz: 1 byte = 1 sample, 20 ms = 160 samples = 160 bytes.
FRAME_SIZE_BYTES = 160
FRAME_DURATION_S = 0.020

# 18 production caller dumps from #279 — fixed list so the report is
# reproducible. Names include the SID so we can cross-reference with
# Twilio if anything looks wrong.
AUDIO_FILES = [
    "CA01864c6bb49b3703bcb26e0d071fc5e8_20260509T030245Z.ulaw",
    "CA04458cc5e3d24809e06dd582a230fe4a_20260509T130814Z.ulaw",
    "CA16b771f616e8b66dfa8e12d308926122_20260509T001152Z.ulaw",
    "CA1fdf536a7206273a6a5a66fe9701106a_20260509T032833Z.ulaw",
    "CA2408cfaf3f250c0bcf7cc2da2f9e19a1_20260509T015049Z.ulaw",
    "CA5599e671e788f60e3b41e62a361f7430_20260508T195131Z.ulaw",
    "CA671b0dc4ee626e9830f8114dd69ca9e7_20260509T035136Z.ulaw",
    "CA83420faa36fc4e14dc852a06a52f5507_20260509T153554Z.ulaw",
    "CA8960400e3e20b08a3a45f8eba13d0e1f_20260509T001525Z.ulaw",
    "CA94ad6280044d8e5d8ce824ffeb5a5a78_20260508T222005Z.ulaw",
    "CA9f8b0ed12dd61237e0fc2185ba529f67_20260509T011754Z.ulaw",
    "CAbdb33a2f80e5b355d9b44f9470f3e360_20260508T190006Z.ulaw",
    "CAc4f381eebc15fe9448404a77518734da_20260509T034939Z.ulaw",
    "CAd65d23c15880b6238d499969601d2c56_20260509T021913Z.ulaw",
    "CAd68df54a44a770570cb8e5cfc3a65dfe_20260509T001940Z.ulaw",
    "CAd95100aa9bc6fb5284bd01ab406c8e8c_20260510T190757Z.ulaw",
    "CAdf8a04e24cf9c41195fa678343cce8f2_20260509T131255Z.ulaw",
    "CAfe25e2f82829a17da61ea6db6d82cbe0_20260508T183926Z.ulaw",
]

# (config_name, model, endpoint_version) — endpoint determines which
# kwargs we pass and which message-shape parser we use.
CONFIGS = [
    ("flux", "flux-general-en", "v2"),
    ("nova-2", "nova-2", "v1"),
    ("nova-3", "nova-3-general", "v1"),
]

# Deepgram's v1 endpoint puts ``keyterm=`` repeated query params in the
# WebSocket URL. With our 94-keyterm production list (qlen ~2370 chars),
# the v1 server returns HTTP 400 "Unexpected error when initializing
# websocket connection". Empirical bisect on 2026-05-10 against
# nova-3-general showed:
#   * n=88 (qlen=2246) — accepted
#   * n=90 (qlen=2280) — rejected with 400
# Truncating to 80 leaves comfortable margin (qlen=2041) and keeps the
# universal modifiers + the most common menu items. Flux v2 sends the
# keyterm list inside its Configure JSON so it's unaffected.
#
# This is the headline finding of #279 — Nova's keyterm channel cannot
# carry the full menu; production keyterm computation would need a
# separate v1-aware budget if we migrated.
V1_KEYTERM_CAP = 80


def _sanitize_error(text: str) -> str:
    """Strip the API key (and other obvious secrets) from any string we
    intend to print or write to disk. The Deepgram SDK's ApiError
    inlines the Authorization header verbatim in its __str__, which
    means a naive ``str(exc)`` leaks the token to logs."""
    if not text:
        return text
    # 'Token <40 hex chars>'
    text = re.sub(r"Token\s+[A-Fa-f0-9]{32,}", "Token <redacted>", text)
    # Generic 'Authorization': '...' patterns from header dumps.
    text = re.sub(
        r"['\"]?[Aa]uthorization['\"]?\s*[:=]\s*['\"][^'\"]+['\"]",
        "'Authorization': '<redacted>'",
        text,
    )
    # Any value that looks like a long hex token.
    text = re.sub(r"\b[A-Fa-f0-9]{40,}\b", "<redacted-hex>", text)
    return text


@dataclass
class FinalRecord:
    """One [final] event from one config."""

    text: str
    conf: float
    wall_s_from_open: float  # time since connection opened
    audio_position_s: float  # how much audio had been pumped at this moment


@dataclass
class RunResult:
    """Outcome of one replay (one file × one config)."""

    config_name: str
    model: str
    audio_duration_s: float
    finals: list[FinalRecord] = field(default_factory=list)
    total_wall_s: float = 0.0
    error: str | None = None


def _api_key() -> str:
    key = os.getenv("DEEPGRAM_API_KEY", "").strip()
    if not key:
        sys.exit("DEEPGRAM_API_KEY not set. Add it to .env or export it before running.")
    return key


def _read_frames(path: Path) -> list[bytes]:
    """Read a mulaw file and split into 20 ms frames; pad final frame
    with mulaw silence (0xFF) so Flux's frame-aligned pipeline doesn't
    see a short frame."""
    with open(path, "rb") as f:
        data = f.read()
    if not data:
        raise ValueError(f"empty audio file: {path}")
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


class _PumpState:
    """Mutable holder for the current audio-pump position. The recv
    loop reads ``audio_position_s`` to stamp finals with how much audio
    had been pushed when the [final] arrived."""

    def __init__(self) -> None:
        self.audio_position_s: float = 0.0


async def _pump_frames_realtime(
    conn: Any, frames: Sequence[bytes], state: _PumpState
) -> None:
    """Send all frames at realtime pace (20 ms per frame), update
    ``state.audio_position_s`` after each send, then close-stream."""
    start = time.monotonic()
    for i, frame in enumerate(frames):
        target = start + (i + 1) * FRAME_DURATION_S
        await conn.send_media(frame)
        state.audio_position_s = (i + 1) * FRAME_DURATION_S
        now = time.monotonic()
        if now < target:
            await asyncio.sleep(target - now)
    await conn.send_close_stream()


async def _run_v2_timed(
    *,
    api_key: str,
    config_name: str,
    model: str,
    keyterms: list[str],
    frames: Sequence[bytes],
    audio_duration_s: float,
) -> RunResult:
    """Replay through Flux (v2) endpoint with per-final timing."""
    result = RunResult(
        config_name=config_name,
        model=model,
        audio_duration_s=audio_duration_s,
    )
    try:
        client = AsyncDeepgramClient(api_key=api_key)
        cm = client.listen.v2.connect(
            model=model,
            encoding="mulaw",
            sample_rate=8000,
            keyterm=keyterms or None,
            eot_threshold=0.8,
            eot_timeout_ms=4000,
        )
        async with cm as conn:
            start_wall = time.monotonic()
            state = _PumpState()
            pump = asyncio.create_task(_pump_frames_realtime(conn, frames, state))
            last_final_wall = 0.0
            try:
                while True:
                    msg = await conn.recv()
                    msg_type = (
                        msg.get("type") if isinstance(msg, dict) else getattr(msg, "type", None)
                    )
                    if msg_type == "TurnInfo":
                        event = (
                            msg.get("event")
                            if isinstance(msg, dict)
                            else getattr(msg, "event", "")
                        )
                        text = (
                            msg.get("transcript")
                            if isinstance(msg, dict)
                            else getattr(msg, "transcript", "")
                        ) or ""
                        text = text.strip()
                        if event == "EndOfTurn" and text:
                            words = (
                                msg.get("words", [])
                                if isinstance(msg, dict)
                                else getattr(msg, "words", [])
                            )
                            conf = _avg_word_conf(words)
                            wall = time.monotonic() - start_wall
                            result.finals.append(
                                FinalRecord(
                                    text=text,
                                    conf=conf,
                                    wall_s_from_open=wall,
                                    audio_position_s=state.audio_position_s,
                                )
                            )
                            last_final_wall = wall
                        continue
                    if msg_type in ("ConfigureFailure", "FatalError"):
                        result.error = _sanitize_error(f"{msg_type}: {msg}")
                        break
            except Exception as exc:
                # Connection closed after close-stream — normal exit
                # path. Only surface if we got nothing useful at all.
                if not pump.done() and not result.finals:
                    result.error = _sanitize_error(f"recv error: {exc!r}")
            finally:
                if not pump.done():
                    pump.cancel()
                    try:
                        await pump
                    except (asyncio.CancelledError, Exception):
                        pass
                result.total_wall_s = (
                    last_final_wall
                    if last_final_wall > 0
                    else time.monotonic() - start_wall
                )
    except Exception as exc:
        result.error = _sanitize_error(f"{type(exc).__name__}: {exc}")
    return result


async def _run_v1_timed(
    *,
    api_key: str,
    config_name: str,
    model: str,
    keyterms: list[str],
    frames: Sequence[bytes],
    audio_duration_s: float,
) -> RunResult:
    """Replay through Nova (v1) endpoint with per-final timing.

    The ``keyterm`` parameter is **only sent for Nova-3**. Empirical
    finding on 2026-05-10: Nova-2 returns HTTP 400 at WebSocket connect
    when ``keyterm=`` is in the URL — it does NOT silently ignore the
    param as the original spec assumed. Nova-2 must therefore run
    keyterm-free.
    """
    result = RunResult(
        config_name=config_name,
        model=model,
        audio_duration_s=audio_duration_s,
    )
    try:
        client = AsyncDeepgramClient(api_key=api_key)
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
        # Only Nova-3 (not Nova-2) accepts the keyterm parameter on v1.
        # Even for Nova-3 we must cap at V1_KEYTERM_CAP because the full
        # 94-term list overflows the v1 connect URL (HTTP 400 at
        # qlen >= ~2280, bisected on nova-3-general).
        nova3 = "nova-3" in model.lower()
        if keyterms and nova3:
            kwargs["keyterm"] = keyterms[:V1_KEYTERM_CAP]

        cm = client.listen.v1.connect(**kwargs)
        async with cm as conn:
            start_wall = time.monotonic()
            state = _PumpState()
            pump = asyncio.create_task(_pump_frames_realtime(conn, frames, state))
            last_final_wall = 0.0
            try:
                while True:
                    msg = await conn.recv()
                    msg_type = (
                        msg.get("type") if isinstance(msg, dict) else getattr(msg, "type", None)
                    )
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
                            conf_raw = (
                                alt.get("confidence")
                                if isinstance(alt, dict)
                                else getattr(alt, "confidence", None)
                            )
                            try:
                                conf = float(conf_raw) if conf_raw is not None else 1.0
                            except (TypeError, ValueError):
                                conf = 1.0
                            wall = time.monotonic() - start_wall
                            result.finals.append(
                                FinalRecord(
                                    text=text,
                                    conf=conf,
                                    wall_s_from_open=wall,
                                    audio_position_s=state.audio_position_s,
                                )
                            )
                            last_final_wall = wall
            except Exception as exc:
                if not pump.done() and not result.finals:
                    result.error = _sanitize_error(f"recv error: {exc!r}")
            finally:
                if not pump.done():
                    pump.cancel()
                    try:
                        await pump
                    except (asyncio.CancelledError, Exception):
                        pass
                result.total_wall_s = (
                    last_final_wall
                    if last_final_wall > 0
                    else time.monotonic() - start_wall
                )
    except Exception as exc:
        result.error = _sanitize_error(f"{type(exc).__name__}: {exc}")
    return result


async def _run_one_config_safe(
    *,
    api_key: str,
    config_name: str,
    model: str,
    endpoint: str,
    keyterms: list[str],
    frames: list[bytes],
    audio_duration_s: float,
) -> RunResult:
    """Wrapper that catches catastrophic errors so one bad config
    doesn't take down the whole gather()."""
    try:
        if endpoint == "v2":
            return await _run_v2_timed(
                api_key=api_key,
                config_name=config_name,
                model=model,
                keyterms=keyterms,
                frames=frames,
                audio_duration_s=audio_duration_s,
            )
        return await _run_v1_timed(
            api_key=api_key,
            config_name=config_name,
            model=model,
            keyterms=keyterms,
            frames=frames,
            audio_duration_s=audio_duration_s,
        )
    except Exception as exc:
        return RunResult(
            config_name=config_name,
            model=model,
            audio_duration_s=audio_duration_s,
            error=_sanitize_error(
                f"{type(exc).__name__}: {exc}\n{traceback.format_exc(limit=3)}"
            ),
        )


async def run_one_file(
    *,
    api_key: str,
    audio_path: Path,
    keyterms: list[str],
) -> tuple[Path, dict[str, RunResult]]:
    """Run all 3 configs concurrently against one audio file."""
    frames = _read_frames(audio_path)
    audio_duration_s = len(frames) * FRAME_DURATION_S
    print(
        f"\n=== {audio_path.name}  ({audio_duration_s:.1f}s, {len(frames)} frames) ==="
    )

    tasks = [
        _run_one_config_safe(
            api_key=api_key,
            config_name=name,
            model=model,
            endpoint=endpoint,
            keyterms=keyterms,
            frames=frames,
            audio_duration_s=audio_duration_s,
        )
        for name, model, endpoint in CONFIGS
    ]
    results = await asyncio.gather(*tasks, return_exceptions=False)
    out: dict[str, RunResult] = {r.config_name: r for r in results}

    # Per-call summary line.
    for name, _, _ in CONFIGS:
        r = out[name]
        if r.error:
            print(f"  [{name:>6}] ERROR: {r.error.splitlines()[0]}")
        else:
            mean_lat = (
                statistics.mean(
                    f.wall_s_from_open - f.audio_position_s for f in r.finals
                )
                if r.finals
                else 0.0
            )
            print(
                f"  [{name:>6}] {len(r.finals):>2} finals  "
                f"wall={r.total_wall_s:5.1f}s  mean_lat={mean_lat:5.2f}s"
            )

    return audio_path, out


def _interleave_finals(per_config: dict[str, RunResult]) -> list[tuple[str, FinalRecord]]:
    """Flatten finals from all configs and sort by wall time."""
    rows: list[tuple[str, FinalRecord]] = []
    for cfg_name, r in per_config.items():
        for f in r.finals:
            rows.append((cfg_name, f))
    rows.sort(key=lambda row: row[1].wall_s_from_open)
    return rows


def _md_escape(text: str) -> str:
    """Escape pipe characters so transcripts don't break markdown
    tables. Keep everything else as-is — readability wins over
    strict markdown."""
    return text.replace("|", "\\|")


def _pivot_per_call_table(per_config: dict[str, RunResult]) -> str:
    """Build a 5-column markdown table for one audio file: each row is
    one final from one config, sorted by wall time. Three columns hold
    the transcript text — only the column for the config that produced
    the final is filled in. Lets a reader scan for divergence."""
    rows = _interleave_finals(per_config)
    if not rows:
        return "_(no finals from any config)_\n"

    lines = [
        "| # | Wall (s) | Flux | Nova-2 | Nova-3 |",
        "|---|---|---|---|---|",
    ]
    for i, (cfg_name, fr) in enumerate(rows, start=1):
        cell = f'"{_md_escape(fr.text)}" ({fr.conf:.2f})'
        flux_cell = cell if cfg_name == "flux" else ""
        n2_cell = cell if cfg_name == "nova-2" else ""
        n3_cell = cell if cfg_name == "nova-3" else ""
        lines.append(
            f"| {i} | {fr.wall_s_from_open:.2f} | {flux_cell} | {n2_cell} | {n3_cell} |"
        )
    return "\n".join(lines) + "\n"


def _summary_table(all_results: list[dict[str, RunResult]]) -> str:
    """Per-config aggregate table across all calls."""
    lines = [
        "| Config | Files OK | Files Failed | Total Finals | Mean Conf | Mean Per-Final Latency (s) | Mean Total Wall (s) |",
        "|---|---|---|---|---|---|---|",
    ]
    for cfg_name, model, _ in CONFIGS:
        ok = 0
        failed = 0
        confs: list[float] = []
        lats: list[float] = []
        walls: list[float] = []
        total_finals = 0
        for per_call in all_results:
            r = per_call.get(cfg_name)
            if r is None:
                continue
            if r.error:
                failed += 1
                continue
            ok += 1
            walls.append(r.total_wall_s)
            for f in r.finals:
                total_finals += 1
                confs.append(f.conf)
                lats.append(f.wall_s_from_open - f.audio_position_s)
        mean_conf = statistics.mean(confs) if confs else 0.0
        mean_lat = statistics.mean(lats) if lats else 0.0
        mean_wall = statistics.mean(walls) if walls else 0.0
        lines.append(
            f"| {cfg_name} | {ok} | {failed} | {total_finals} | "
            f"{mean_conf:.3f} | {mean_lat:.3f} | {mean_wall:.2f} |"
        )
    return "\n".join(lines) + "\n"


def _latency_distribution_table(all_results: list[dict[str, RunResult]]) -> str:
    """Per-config latency percentiles (p50, p90, p95, p99, max)."""
    lines = [
        "| Config | Count | p50 | p90 | p95 | p99 | max |",
        "|---|---|---|---|---|---|---|",
    ]
    for cfg_name, _, _ in CONFIGS:
        lats: list[float] = []
        for per_call in all_results:
            r = per_call.get(cfg_name)
            if r is None or r.error:
                continue
            for f in r.finals:
                lats.append(f.wall_s_from_open - f.audio_position_s)
        if not lats:
            lines.append(f"| {cfg_name} | 0 | - | - | - | - | - |")
            continue
        lats.sort()
        n = len(lats)

        def pct(p: float) -> float:
            # Nearest-rank, guarded against off-by-one at the ends.
            idx = min(n - 1, max(0, int(round(p * n)) - 1))
            return lats[idx]

        lines.append(
            f"| {cfg_name} | {n} | {pct(0.50):.2f} | {pct(0.90):.2f} | "
            f"{pct(0.95):.2f} | {pct(0.99):.2f} | {lats[-1]:.2f} |"
        )
    return "\n".join(lines) + "\n"


def _notable_divergences(per_call: dict[str, RunResult]) -> list[str]:
    """Heuristic: for each final from any config, see if the other two
    have a final whose wall time is within a 2-second window. If only
    one config produced text near that moment — or the texts disagree
    on substantive content — flag it.

    This is intentionally cheap / approximate. The signal here is
    qualitative: a human will read the per-call tables to decide
    whether a divergence matters."""
    if not per_call:
        return []
    rows = _interleave_finals(per_call)
    if not rows:
        return []

    notes: list[str] = []
    window_s = 2.0

    # Track which finals we've already grouped to avoid duplicate
    # divergence notes for the same audio moment.
    used: set[tuple[str, int]] = set()
    by_cfg: dict[str, list[tuple[int, FinalRecord]]] = {n: [] for n, _, _ in CONFIGS}
    for cfg_name, r in per_call.items():
        for idx, f in enumerate(r.finals):
            by_cfg[cfg_name].append((idx, f))

    for cfg_name, finals in by_cfg.items():
        for idx, f in finals:
            key = (cfg_name, idx)
            if key in used:
                continue
            # Find nearby finals from other configs.
            group: dict[str, str] = {cfg_name: f.text}
            for other, other_finals in by_cfg.items():
                if other == cfg_name:
                    continue
                for oidx, of in other_finals:
                    if (other, oidx) in used:
                        continue
                    if abs(of.wall_s_from_open - f.wall_s_from_open) <= window_s:
                        group[other] = of.text
                        used.add((other, oidx))
                        break
            used.add(key)

            # Flag if not all three configs spoke up at this moment.
            if len(group) < 3:
                missing = [c for c, _, _ in CONFIGS if c not in group]
                snippet = (f.text[:60] + "...") if len(f.text) > 60 else f.text
                notes.append(
                    f"- @ {f.wall_s_from_open:.1f}s — only "
                    f"{', '.join(group.keys())} produced a final "
                    f'(missing: {", ".join(missing)}). '
                    f'Text: "{snippet}"'
                )
                continue

            # All three spoke. Flag if the texts disagree (case-insensitive).
            normalized = {c: t.strip().lower().rstrip(".?!,") for c, t in group.items()}
            if len(set(normalized.values())) > 1:
                lines = [
                    f"- @ {f.wall_s_from_open:.1f}s — divergence:",
                    *[f'  - **{c}**: "{group[c]}"' for c in ("flux", "nova-2", "nova-3") if c in group],
                ]
                notes.append("\n".join(lines))

    return notes


def _build_report(
    *,
    keyterms: list[str],
    all_results: list[tuple[Path, dict[str, RunResult]]],
    sweep_wall_s: float,
) -> str:
    total_audio_s = sum(
        r.audio_duration_s
        for _, per_call in all_results
        for r in per_call.values()
        if r.config_name == "flux"  # any config; pick flux to avoid triple-counting
    )

    parts: list[str] = []
    parts.append("# Flux vs Nova-2 vs Nova-3 STT Evaluation")
    parts.append("")
    parts.append("Date: 2026-05-10  ")
    parts.append("Issue: [#279](https://github.com/tsuki-works/niko/issues/279)  ")
    parts.append(
        f"Audio dataset: {len(all_results)} calls, {total_audio_s / 60:.1f} minutes total, "
        "all Twilight Family Restaurant  "
    )
    parts.append(
        f"Keyterms: n={len(keyterms)} from `compute_keyterms()` "
        "(76 menu items + 18 universal modifiers from #271)  "
    )
    parts.append(f"Sweep wall-clock: {sweep_wall_s / 60:.1f} minutes")
    parts.append("")
    parts.append("**Important caveat — keyterms on the wire are NOT identical across configs:**")
    parts.append("")
    parts.append("- **Flux (v2)** sends the keyterm list inside its `Configure` JSON; the")
    parts.append(f"  full n={len(keyterms)} list is delivered.")
    parts.append("- **Nova-3 (v1)** URL-encodes each keyterm as a repeated query parameter")
    parts.append("  on the WebSocket connect URL. Empirical bisect on 2026-05-10 found")
    parts.append("  the v1 endpoint returns HTTP 400 once the query string passes")
    parts.append("  ~2280 chars (somewhere between n=88 and n=90 of our list). To keep")
    parts.append(f"  the sweep meaningful we cap Nova-3 at n={V1_KEYTERM_CAP} (qlen ~2040),")
    parts.append("  preserving the restaurant name + all 18 modifiers + the first ~60")
    parts.append("  menu items.")
    parts.append("- **Nova-2 (v1) receives NO keyterm.** The original plan assumed")
    parts.append("  Nova-2 would silently ignore the param, but empirically it returns")
    parts.append("  HTTP 400 when `keyterm=` is in the URL — Nova-2 simply doesn't")
    parts.append("  accept that query param at all. Nova-2 is therefore the unbiased")
    parts.append("  baseline in this comparison.")
    parts.append("")
    parts.append("**These v1 findings are themselves headline results for #279:**")
    parts.append("")
    parts.append("1. If we migrate Flux → Nova-3, the existing 500-token Flux budget in")
    parts.append("   `compute_keyterms()` does not apply. We'd need a separate v1-aware")
    parts.append("   URL-length cap (or pursue a POST-body keyterm route if Deepgram")
    parts.append("   exposes one).")
    parts.append("2. Any \"Nova-2 with keyterms\" production fallback path is broken —")
    parts.append("   the connect itself fails. Nova-2 must run unbiased.")
    parts.append("")
    parts.append("## Summary")
    parts.append("")
    parts.append(_summary_table([per for _, per in all_results]))
    parts.append("Latency = `wall_s_from_open - audio_position_s` at each [final],")
    parts.append("averaged across every final across every call. This is the")
    parts.append("end-of-utterance lag — how long after the caller stopped speaking")
    parts.append("the model emitted the transcript.")
    parts.append("")
    parts.append("## Latency distribution")
    parts.append("")
    parts.append(_latency_distribution_table([per for _, per in all_results]))
    parts.append("Flux's pitch is fast turn detection (eot_threshold=0.8); Nova's")
    parts.append("v1 endpointing window is 800ms with utterance_end_ms=1000.")
    parts.append("")
    parts.append("## Per-call breakdown")
    parts.append("")
    for path, per_call in all_results:
        parts.append(f"### {path.name}")
        any_r = next(iter(per_call.values()))
        parts.append(f"_Audio duration: {any_r.audio_duration_s:.1f}s_")
        parts.append("")
        # Per-config error notes (if any).
        for cfg_name, _, _ in CONFIGS:
            r = per_call.get(cfg_name)
            if r and r.error:
                parts.append(f"> **{cfg_name} ERROR:** {r.error.splitlines()[0]}")
                parts.append("")
        parts.append(_pivot_per_call_table(per_call))
        parts.append("")

    parts.append("## Notable divergences")
    parts.append("")
    parts.append(
        "Heuristic flag: for each [final] from any config, we look for nearby"
    )
    parts.append(
        "finals (within 2s) from the other two. If a config went silent — or"
    )
    parts.append(
        "the three configs disagree on the text — it's listed below. Read the"
    )
    parts.append(
        "per-call tables above for context; this section is the index, not the"
    )
    parts.append("primary signal.")
    parts.append("")
    any_divergences = False
    for path, per_call in all_results:
        notes = _notable_divergences(per_call)
        if notes:
            any_divergences = True
            parts.append(f"### {path.name}")
            parts.extend(notes)
            parts.append("")
    if not any_divergences:
        parts.append("_All three configs agreed across every call — no divergences flagged._")
        parts.append("")

    parts.append("## Recommendation")
    parts.append("")
    parts.append("_Filled in by the human reviewer — see the data above. Look for:_")
    parts.append("")
    parts.append("- **Latency**: Flux should beat Nova-1 by a clear margin on p50/p90.")
    parts.append("  If it doesn't, Flux's value prop is gone — switch to Nova-3.")
    parts.append("- **Menu-item hits**: scan the divergence section for items that")
    parts.append("  Nova-3 caught but Flux missed (or vice versa). The keyterm list")
    parts.append("  is identical across configs, so this isolates the model.")
    parts.append("- **Failure rate**: any config that errored on >1 file is a")
    parts.append("  reliability concern, not just a quality concern.")
    parts.append("")
    parts.append("**Verdict (TBD by reviewer):** stay on Flux / canary Nova-3 / migrate to Nova-3 / inconclusive.")
    parts.append("")

    return "\n".join(parts)


async def main() -> None:
    api_key = _api_key()

    # Compute keyterms once — same list for all three configs, all 18 calls.
    menu_path = REPO_ROOT / "restaurants" / "twilight-family-restaurant.json"
    with open(menu_path, encoding="utf-8") as f:
        menu = json.load(f)
    keyterms = compute_keyterms(menu, "Twilight Family Restaurant")
    print(f"[keyterms n={len(keyterms)}]")
    print(f"[configs: {', '.join(name for name, _, _ in CONFIGS)}]")
    print(f"[files: {len(AUDIO_FILES)}]")

    rec_dir = REPO_ROOT / "dev_recordings"
    missing = [name for name in AUDIO_FILES if not (rec_dir / name).is_file()]
    if missing:
        sys.exit(f"missing audio files: {missing}")

    sweep_start = time.monotonic()
    all_results: list[tuple[Path, dict[str, RunResult]]] = []
    for idx, name in enumerate(AUDIO_FILES, start=1):
        path = rec_dir / name
        print(f"\n[{idx}/{len(AUDIO_FILES)}] starting {name}")
        path_done, per_call = await run_one_file(
            api_key=api_key,
            audio_path=path,
            keyterms=keyterms,
        )
        all_results.append((path_done, per_call))
    sweep_wall_s = time.monotonic() - sweep_start

    print(f"\n[sweep complete in {sweep_wall_s / 60:.1f} min]")

    # Write report.
    report = _build_report(
        keyterms=keyterms,
        all_results=all_results,
        sweep_wall_s=sweep_wall_s,
    )
    report_path = (
        REPO_ROOT
        / "docs"
        / "superpowers"
        / "specs"
        / "2026-05-10-flux-vs-nova3-evaluation.md"
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"[report written: {report_path}]")


if __name__ == "__main__":
    asyncio.run(main())
