"""``edit_sketch`` and ``delete_sketch_entities`` on the mock."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastmcp import FastMCP

from solidworks_mcp.adapters.base import (
    AdapterResult,
    AdapterResultStatus,
    ExtrusionParameters,
)
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


async def test_an_unknown_id_names_the_ids_there_are(part: Any) -> None:
    _adapter, tools = part
    await tools["create_sketch"]({"plane": "Top"})
    line = (await tools["add_line"]({"x1": 0, "y1": 0, "x2": 5, "y2": 0}))["line"]["id"]

    unknown = await tools["delete_sketch_entities"]({"ids": ["Line_404"]})

    assert unknown["error_type"] == "not_found", unknown
    assert f"The open sketch has one id: {line}." in unknown["message"]
    assert "Ids change each time a sketch is opened" in unknown["message"]


async def test_all_deletes_every_entity(part: Any) -> None:
    _adapter, tools = part
    await tools["create_sketch"]({"plane": "Top"})
    drawn = [
        (await tools["add_line"]({"x1": 0, "y1": 0, "x2": 5, "y2": 0}))["line"]["id"],
        (await tools["add_circle"]({"center_x": 0, "center_y": 0, "radius": 2}))[
            "circle"
        ]["id"],
    ]

    cleared = await tools["delete_sketch_entities"]({"all": True})
    again = await tools["delete_sketch_entities"]({"all": True})

    assert cleared["status"] == "success", cleared
    assert cleared["deleted"] == sorted(drawn)
    assert (cleared["deleted_count"], cleared["skipped"], cleared["remaining"]) == (
        2,
        [],
        [],
    )
    assert cleared["message"] == "Deleted every entity of the open sketch (2)"
    assert again["message"] == "The open sketch had no entities to delete"


async def test_all_reports_what_it_could_not_select(part: Any) -> None:
    adapter, tools = part
    stuck = {"id": "Arc_2", "type": "arc"}
    adapter.delete_all_sketch_entities = AsyncMock(  # type: ignore[method-assign]
        return_value=AdapterResult(
            status=AdapterResultStatus.SUCCESS,
            data={
                "deleted": ["Line_1"],
                "deleted_count": 3,
                "skipped": [stuck],
                "remaining": ["Arc_2"],
            },
        )
    )

    reply = await tools["delete_sketch_entities"]({"all": True})

    assert reply["message"] == (
        "Deleted 3 of the open sketch's 4 entities; SolidWorks could not select "
        "the other 1 (see skipped)"
    )
    assert (reply["skipped"], reply["remaining"]) == ([stuck], ["Arc_2"])


@pytest.mark.parametrize(
    "arguments", [{"ids": ["Line_1"], "all": True}, {}, {"all": False}]
)
async def test_ids_or_all_but_not_both(part: Any, arguments: dict) -> None:
    _adapter, tools = part
    await tools["create_sketch"]({"plane": "Top"})

    reply = await tools["delete_sketch_entities"](arguments)

    assert reply["error_type"] == "invalid_input", reply
    assert "ids" in reply["message"] and "all: true" in reply["message"]


async def test_all_needs_an_open_sketch(part: Any) -> None:
    _adapter, tools = part

    reply = await tools["delete_sketch_entities"]({"all": True})

    assert reply["error_type"] == "no_active_sketch", reply


async def test_a_feature_is_not_a_sketch(part: Any) -> None:
    adapter, tools = part
    await adapter.create_sketch("Top")
    await adapter.add_rectangle(0, 0, 5, 5)
    await adapter.exit_sketch()
    boss = await adapter.create_extrusion(ExtrusionParameters(depth=2))

    result = await adapter.edit_sketch(boss.data.name)

    assert result.error == f"{boss.data.name!r} is a Feature, not a sketch."
