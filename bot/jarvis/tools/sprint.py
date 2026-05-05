"""`get_current_sprint` — pulls the niko sprint board via GraphQL.

Selection rules mirror the `current-sprint` Claude Code skill:
  1. Prefer items with Status = "In progress".
  2. Otherwise, items at the lowest open phase (parsed from the Phase
     field's "Phase N: ..." prefix) whose status != "Done".
  3. Otherwise, empty.
"""

from __future__ import annotations

import re
from typing import Any

from jarvis.tools import ToolDescriptor

_QUERY = """
query($id: ID!) {
  node(id: $id) {
    ... on ProjectV2 {
      items(first: 100) {
        nodes {
          content {
            ... on Issue { title url number }
            ... on PullRequest { title url number }
          }
          fieldValues(first: 20) {
            nodes {
              ... on ProjectV2ItemFieldSingleSelectValue {
                name
                field { ... on ProjectV2SingleSelectField { name } }
              }
            }
          }
        }
      }
    }
  }
}
"""


def _phase_number(phase_label: str | None) -> int | None:
    if not phase_label:
        return None
    m = re.match(r"Phase\s+(\d+)", phase_label)
    return int(m.group(1)) if m else None


def _flatten(item: dict[str, Any]) -> dict[str, Any]:
    content = item.get("content") or {}
    field_values = (item.get("fieldValues") or {}).get("nodes") or []
    by_field = {}
    for fv in field_values:
        field_meta = fv.get("field") or {}
        fname = field_meta.get("name")
        if fname:
            by_field[fname] = fv.get("name")
    return {
        "title": content.get("title"),
        "url": content.get("url"),
        "number": content.get("number"),
        "status": by_field.get("Status"),
        "phase": by_field.get("Phase"),
    }


def build_get_current_sprint_tool(*, github_client: Any, project_id: str) -> ToolDescriptor:
    async def get_current_sprint() -> dict[str, Any]:
        data = await github_client.graphql(_QUERY, variables={"id": project_id})
        nodes = (((data or {}).get("node") or {}).get("items") or {}).get("nodes") or []
        flat = [_flatten(n) for n in nodes]

        in_progress = [i for i in flat if i["status"] == "In progress"]
        if in_progress:
            return {"selected_by": "in_progress", "items": in_progress}

        open_items = [i for i in flat if i["status"] != "Done"]
        if not open_items:
            return {"selected_by": "empty", "items": []}

        phases = [_phase_number(i.get("phase")) for i in open_items]
        present = [p for p in phases if p is not None]
        if not present:
            return {"selected_by": "no_phase_field", "items": open_items}

        lowest = min(present)
        items_at_lowest = [i for i, p in zip(open_items, phases) if p == lowest]
        return {"selected_by": "lowest_open_phase", "items": items_at_lowest}

    return ToolDescriptor(
        name="get_current_sprint",
        description=(
            "Get the current sprint from the tsuki-works/niko GitHub Project. "
            "Returns items currently In progress, or the lowest open Phase if "
            "none are In progress. Use this when the user asks 'what are we "
            "working on?', 'what's the current sprint?', or 'sprint status'."
        ),
        input_schema={
            "type": "object",
            "properties": {},
            "required": [],
        },
        fn=get_current_sprint,
    )
