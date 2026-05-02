"""Tests for jarvis.tools — ToolRegistry + ToolContext."""

from __future__ import annotations

import json

from jarvis.tools import ToolContext, ToolDescriptor, ToolRegistry


def _ctx() -> ToolContext:
    # Minimal context — no real fields needed for these tests.
    return ToolContext(guild=None, github_client=None, github_repo="org/repo",
                       github_project_id="PVT_x", docs_root=None)


async def test_register_and_as_anthropic_tools_shape():
    async def echo(*, x: int) -> dict:
        return {"x": x}

    reg = ToolRegistry()
    reg.register(
        ToolDescriptor(
            name="echo",
            description="Echoes x.",
            input_schema={
                "type": "object",
                "properties": {"x": {"type": "integer"}},
                "required": ["x"],
            },
            fn=echo,
        )
    )
    tools = reg.as_anthropic_tools()
    assert len(tools) == 1
    assert tools[0]["name"] == "echo"
    assert tools[0]["description"] == "Echoes x."
    assert tools[0]["input_schema"]["properties"]["x"]["type"] == "integer"


async def test_dispatch_returns_json_string_on_success():
    async def echo(*, x: int) -> dict:
        return {"x": x, "doubled": x * 2}

    reg = ToolRegistry()
    reg.register(
        ToolDescriptor(
            name="echo", description="d", input_schema={}, fn=echo,
        )
    )
    out = await reg.dispatch(name="echo", tool_input={"x": 3}, context=_ctx())
    parsed = json.loads(out)
    assert parsed == {"x": 3, "doubled": 6}


async def test_dispatch_returns_error_json_for_unknown_tool():
    reg = ToolRegistry()
    out = await reg.dispatch(name="nope", tool_input={}, context=_ctx())
    parsed = json.loads(out)
    assert "error" in parsed
    assert "nope" in parsed["error"]


async def test_dispatch_catches_tool_exception():
    async def explode(**_kwargs) -> dict:
        raise ValueError("boom")

    reg = ToolRegistry()
    reg.register(
        ToolDescriptor(
            name="explode", description="d", input_schema={}, fn=explode,
        )
    )
    out = await reg.dispatch(name="explode", tool_input={}, context=_ctx())
    parsed = json.loads(out)
    assert "error" in parsed
    assert "boom" in parsed["error"]


async def test_dispatch_passes_context_when_fn_accepts_it():
    """Tools may opt-in to the context by accepting a `context` kwarg."""
    seen = {}

    async def needs_ctx(*, x: int, context: ToolContext) -> dict:
        seen["repo"] = context.github_repo
        return {"x": x}

    reg = ToolRegistry()
    reg.register(
        ToolDescriptor(
            name="needs_ctx", description="d", input_schema={}, fn=needs_ctx,
            wants_context=True,
        )
    )
    await reg.dispatch(
        name="needs_ctx", tool_input={"x": 1}, context=_ctx()
    )
    assert seen["repo"] == "org/repo"


async def test_register_rejects_duplicate_name():
    async def fn(**_kwargs):
        return {}

    reg = ToolRegistry()
    desc = ToolDescriptor(name="t", description="", input_schema={}, fn=fn)
    reg.register(desc)
    import pytest
    with pytest.raises(ValueError, match="already registered"):
        reg.register(desc)
