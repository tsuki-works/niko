"""`search_repo_docs` — substring grep over the local docs/ directory.

This is the PR 3a substitute for the spec's "ripgrep over a fresh git
clone refreshed hourly" plan. The bot runs from the repo (until PR 5
deploys to GCE), so reading directly from `docs/` is sufficient and
avoids spinning up a clone-refresh cron.

PR 5 (deploy) will revisit: either bake docs/ into the container at
build time or maintain a checked-out copy on the GCE VM with a refresh
cron.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from jarvis.tools import ToolDescriptor

_MAX_RESULTS = 25
_SNIPPET_RADIUS = 80  # chars on each side of the match


def _snippet(line: str, query_lower: str) -> str:
    idx = line.lower().find(query_lower)
    if idx < 0:
        return line.strip()[: _SNIPPET_RADIUS * 2]
    start = max(0, idx - _SNIPPET_RADIUS)
    end = min(len(line), idx + len(query_lower) + _SNIPPET_RADIUS)
    snippet = line[start:end].strip()
    return ("…" if start > 0 else "") + snippet + ("…" if end < len(line) else "")


def build_search_repo_docs_tool(*, docs_root: Optional[Path]) -> ToolDescriptor:
    async def search_repo_docs(query: str) -> list[dict[str, Any]]:
        if not query:
            return []
        if docs_root is None or not docs_root.exists():
            return []
        q = query.lower()
        results: list[dict[str, Any]] = []
        for md_path in sorted(docs_root.rglob("*.md")):
            try:
                text = md_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for line in text.splitlines():
                if q in line.lower():
                    results.append(
                        {
                            "path": str(md_path.relative_to(docs_root)).replace("\\", "/"),
                            "snippet": _snippet(line, q),
                        }
                    )
                    break  # one snippet per file
            if len(results) >= _MAX_RESULTS:
                break
        return results

    return ToolDescriptor(
        name="search_repo_docs",
        description=(
            "Search the niko repo's docs/ directory for a substring "
            "(case-insensitive). Returns up to 25 matches as "
            "{path, snippet} pairs (one per file). Use this when the "
            "user asks 'where do we configure X?', 'what does the doc "
            "say about Y?', or to ground answers in repo documentation."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Substring to grep for, case-insensitive.",
                },
            },
            "required": ["query"],
        },
        fn=search_repo_docs,
    )
