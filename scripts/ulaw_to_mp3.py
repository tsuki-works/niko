"""Convert raw mulaw 8 kHz files (the format ``app.dev.audio_dump``
writes) to MP3 so the audio can be uploaded to tools that don't accept
raw mulaw — e.g. Deepgram's web console, generic audio players, support
attachments.

Reuses the production helpers from ``app.storage.recordings``:
``_ulaw2lin_16`` for the mulaw→PCM decode and ``_make_encoder`` for the
lameenc MP3 encoder. No new dependencies.

Usage::

    python scripts/ulaw_to_mp3.py PATH.ulaw            # one file
    python scripts/ulaw_to_mp3.py dev_recordings/      # every .ulaw in dir

Output is written next to each input as ``<basename>.mp3``. Existing
``.mp3`` files are overwritten.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.storage.recordings import _make_encoder, _ulaw2lin_16


def convert_one(ulaw_path: str) -> str:
    """Convert one ``.ulaw`` file to ``.mp3``. Returns the output path."""
    with open(ulaw_path, "rb") as f:
        mulaw_bytes = f.read()
    if not mulaw_bytes:
        raise ValueError(f"input file is empty: {ulaw_path}")

    pcm = _ulaw2lin_16(mulaw_bytes)
    encoder = _make_encoder()
    mp3 = bytes(encoder.encode(pcm) + encoder.flush())

    out_path = os.path.splitext(ulaw_path)[0] + ".mp3"
    with open(out_path, "wb") as f:
        f.write(mp3)

    duration_s = (len(pcm) // 2) / 8000.0
    print(
        f"{ulaw_path}  ->  {out_path}  "
        f"({len(mulaw_bytes):,}B mulaw, {len(mp3):,}B mp3, {duration_s:.1f}s)"
    )
    return out_path


def collect_targets(arg: str) -> list[str]:
    if os.path.isdir(arg):
        return sorted(
            os.path.join(arg, name) for name in os.listdir(arg) if name.lower().endswith(".ulaw")
        )
    if os.path.isfile(arg):
        return [arg]
    sys.exit(f"input not found: {arg}")


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit("usage: ulaw_to_mp3.py <file.ulaw | dir>")
    targets = collect_targets(sys.argv[1])
    if not targets:
        sys.exit("no .ulaw files found")
    for path in targets:
        try:
            convert_one(path)
        except Exception as exc:
            print(f"FAIL: {path}: {exc}", file=sys.stderr)


if __name__ == "__main__":
    main()
