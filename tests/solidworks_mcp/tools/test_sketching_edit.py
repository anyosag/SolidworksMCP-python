"""``edit_sketch`` and ``delete_sketch_entities`` on the mock."""

from __future__ import annotations

from typing import Any

import pytest
from fastmcp import FastMCP

from solidworks_mcp.adapters.base import ExtrusionParameters
from solidworks_mcp.adapters.mock_adapter import MockSolidWorksAdapter
from solidworks_mcp.tools.sketching import register_sketching_tools


@pytest.fixture
async def part(mock_config: Any) -> tuple[MockSolidWorksAdapter, dict[str, Any]]:
    adapter = MockSolidWorksAdapter({})
    await adapter.connect()
    await adapter.create_part()
    mcp = FastMCP("sketch-edit")
    await register_sketching_tools(mcp, adapter, mock_config)
    return adapter, {tool.name: tool.fn for tool in await mcp.list_tools()}


async def test_a_sketch_reopens_and_loses_a_line(part: Any) -> None:
    adapter, tools = part
    sketch = (await tools["create_sketch"]({"plane": "Top"}))["sketch"]["name"]
    line = (await tools["add_line"]({"x1": 0, "y1": 0, "x2": 5, "y2": 0}))["line"]["id"]
    await tools["exit_sketch"]()

    opened = await tools["edit_sketch"]({"name": sketch})
    deleted = await tools["delete_sketch_entities"]({"ids": [line]})

    assert opened["status"] == "success", opened
    assert opened["message"] == f"Opened {sketch} for editing (0 segments)"
    assert deleted["deleted"] == [line]
    assert line not in deleted["remaining"]


@pytest.mark.parametrize(
    ("name", "error_type", "fragment"),
    [
        ("Sketch9", "not_found", "'Sketch9' not found"),
        ("Top Plane", None, "not a sketch"),
    ],
)
async def test_only_sketches_open(
    part: Any, name: str, error_type: str | None, fragment: str
) -> None:
    _adapter, tools = part

    result = await tools["edit_sketch"]({"name": name})

    assert result["status"] == "error"
    assert fragment in result["message"]
    if error_type:
        assert result["error_type"] == error_type


async def test_deleting_needs_known_ids_and_an_open_sketch(part: Any) -> None:
    adapter, tools = part

    closed = await tools["delete_sketch_entities"]({"ids": ["Line_1"]})
    await tools["create_sketch"]({"plane": "Top"})
    unknown = await tools["delete_sketch_entities"]({"ids": ["Line_404"]})
    empty = await tools["delete_sketch_entities"]({"ids": []})
    blank = await tools["edit_sketch"]({"name": " "})

    assert closed["error_type"] == "no_active_sketch"
    assert "Line_404 not found in the open sketch" in unknown["message"]
    assert empty["error_type"] == "invalid_input"
    assert blank["error_type"] == "invalid_input"


async def test_a_feature_is_not_a_sketch(part: Any) -> None:
    adapter, tools = part
    await adapter.create_sketch("Top")
    await adapter.add_rectangle(0, 0, 5, 5)
    await adapter.exit_sketch()
    boss = await adapter.create_extrusion(ExtrusionParameters(depth=2))

    result = await adapter.edit_sketch(boss.data.name)

    assert result.error == f"{boss.data.name!r} is a Feature, not a sketch."
