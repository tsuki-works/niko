"""Tests for jarvis.tools.docs.build_search_repo_docs_tool."""

from __future__ import annotations

from pathlib import Path

from jarvis.tools.docs import build_search_repo_docs_tool


def _seed_docs(root: Path, files: dict[str, str]) -> None:
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


async def test_search_finds_substring_matches(tmp_path):
    _seed_docs(
        tmp_path,
        {
            "docs/01-prd.md": "Twilio is the telephony provider.\n",
            "docs/02-roadmap.md": "Phase 2 work.\n",
            "docs/06-creds.md": "Twilio creds in 1Password.\n",
        },
    )
    desc = build_search_repo_docs_tool(docs_root=tmp_path / "docs")
    out = await desc.fn(query="twilio")
    paths = sorted(item["path"] for item in out)
    assert paths == ["01-prd.md", "06-creds.md"]
    snippets = [item["snippet"].lower() for item in out]
    assert all("twilio" in s for s in snippets)


async def test_search_returns_empty_for_no_matches(tmp_path):
    _seed_docs(tmp_path, {"docs/x.md": "nothing relevant"})
    desc = build_search_repo_docs_tool(docs_root=tmp_path / "docs")
    out = await desc.fn(query="zzznothere")
    assert out == []


async def test_search_skips_non_md_files(tmp_path):
    _seed_docs(
        tmp_path,
        {
            "docs/note.md": "telephony rules",
            "docs/note.png": "telephony rules",  # not markdown
            "docs/sub/deep.md": "telephony deep",
        },
    )
    desc = build_search_repo_docs_tool(docs_root=tmp_path / "docs")
    out = await desc.fn(query="telephony")
    paths = sorted(item["path"] for item in out)
    assert paths == ["note.md", "sub/deep.md"]


async def test_search_caps_results(tmp_path):
    files = {f"docs/n{i}.md": "match" for i in range(60)}
    _seed_docs(tmp_path, files)
    desc = build_search_repo_docs_tool(docs_root=tmp_path / "docs")
    out = await desc.fn(query="match")
    assert len(out) <= 25  # default cap


async def test_search_handles_missing_root(tmp_path):
    desc = build_search_repo_docs_tool(docs_root=tmp_path / "no-such-dir")
    out = await desc.fn(query="anything")
    assert out == []


async def test_descriptor_metadata(tmp_path):
    desc = build_search_repo_docs_tool(docs_root=tmp_path / "docs")
    assert desc.name == "search_repo_docs"
    assert "docs" in desc.description.lower()
    assert "query" in desc.input_schema["properties"]
    assert desc.input_schema.get("required") == ["query"]
