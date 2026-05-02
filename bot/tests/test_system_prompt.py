"""Tests for jarvis.system_prompt — the static system prompt builder."""

from __future__ import annotations

from jarvis.system_prompt import build_system_prompt


def test_system_prompt_mentions_jarvis_and_team():
    p = build_system_prompt()
    assert "Jarvis" in p
    assert "Tsuki Works" in p
    assert "niko" in p


def test_system_prompt_includes_team_members():
    p = build_system_prompt()
    for name in ("Meet", "Kailash", "Sandeep", "Daniel"):
        assert name in p, f"{name} missing from system prompt"


def test_system_prompt_lists_available_tools():
    p = build_system_prompt()
    # PR 3a: three tools available
    assert "get_current_sprint" in p
    assert "get_recent_commits" in p
    assert "search_repo_docs" in p


def test_system_prompt_has_hard_rules():
    p = build_system_prompt()
    assert "@-everyone" in p or "@everyone" in p
    assert "secret" in p.lower()


def test_system_prompt_is_a_single_string():
    p = build_system_prompt()
    assert isinstance(p, str)
    assert len(p) > 200  # not a stub
    assert len(p) < 4000  # not bloated
