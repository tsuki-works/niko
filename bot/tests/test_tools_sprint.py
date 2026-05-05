"""Tests for jarvis.tools.sprint.build_get_current_sprint_tool."""

from __future__ import annotations

from unittest.mock import AsyncMock

from jarvis.tools.sprint import build_get_current_sprint_tool


def _gh_with_response(data: dict):
    gh = AsyncMock()
    gh.graphql = AsyncMock(return_value=data)
    return gh


async def test_returns_in_progress_items():
    data = {
        "node": {
            "items": {
                "nodes": [
                    {
                        "content": {"title": "Sprint 2.4", "url": "u4", "number": 7},
                        "fieldValues": {
                            "nodes": [
                                {"name": "In progress", "field": {"name": "Status"}},
                                {"name": "Phase 2: MVP", "field": {"name": "Phase"}},
                            ]
                        },
                    },
                    {
                        "content": {"title": "Sprint 2.1", "url": "u1", "number": 4},
                        "fieldValues": {
                            "nodes": [
                                {"name": "Done", "field": {"name": "Status"}},
                                {"name": "Phase 2: MVP", "field": {"name": "Phase"}},
                            ]
                        },
                    },
                ]
            }
        }
    }
    gh = _gh_with_response(data)
    desc = build_get_current_sprint_tool(github_client=gh, project_id="PVT_x")
    out = await desc.fn()
    assert out["selected_by"] == "in_progress"
    assert len(out["items"]) == 1
    assert out["items"][0]["title"] == "Sprint 2.4"
    assert out["items"][0]["url"] == "u4"
    assert out["items"][0]["status"] == "In progress"
    assert out["items"][0]["phase"] == "Phase 2: MVP"


async def test_falls_back_to_lowest_open_phase_when_none_in_progress():
    data = {
        "node": {
            "items": {
                "nodes": [
                    {
                        "content": {"title": "Phase 0 wrap", "url": "u0", "number": 2},
                        "fieldValues": {
                            "nodes": [
                                {"name": "Done", "field": {"name": "Status"}},
                                {"name": "Phase 0: Foundation", "field": {"name": "Phase"}},
                            ]
                        },
                    },
                    {
                        "content": {"title": "Sprint 3.1", "url": "u31", "number": 8},
                        "fieldValues": {
                            "nodes": [
                                {"name": "Todo", "field": {"name": "Status"}},
                                {"name": "Phase 3: Beta", "field": {"name": "Phase"}},
                            ]
                        },
                    },
                    {
                        "content": {"title": "Sprint 2.4", "url": "u24", "number": 7},
                        "fieldValues": {
                            "nodes": [
                                {"name": "Todo", "field": {"name": "Status"}},
                                {"name": "Phase 2: MVP", "field": {"name": "Phase"}},
                            ]
                        },
                    },
                ]
            }
        }
    }
    gh = _gh_with_response(data)
    desc = build_get_current_sprint_tool(github_client=gh, project_id="PVT_x")
    out = await desc.fn()
    assert out["selected_by"] == "lowest_open_phase"
    titles = [item["title"] for item in out["items"]]
    assert "Sprint 2.4" in titles
    assert "Sprint 3.1" not in titles  # later phase, dropped


async def test_handles_empty_board():
    gh = _gh_with_response({"node": {"items": {"nodes": []}}})
    desc = build_get_current_sprint_tool(github_client=gh, project_id="PVT_x")
    out = await desc.fn()
    assert out["selected_by"] == "empty"
    assert out["items"] == []


async def test_descriptor_metadata():
    gh = _gh_with_response({"node": {"items": {"nodes": []}}})
    desc = build_get_current_sprint_tool(github_client=gh, project_id="PVT_x")
    assert desc.name == "get_current_sprint"
    assert "sprint" in desc.description.lower()
    # No required input — the tool takes no args.
    assert desc.input_schema["type"] == "object"
    assert desc.input_schema.get("required", []) == []
