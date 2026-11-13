"""The ``set_component_transform`` tool, and ``fixed`` on ``insert_component``."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastmcp import FastMCP

from solidworks_mcp.adapters.base import AdapterResult, AdapterResultStatus
from solidworks_mcp.adapters.mock_adapter import MockSolidWorksAdapter
from solidworks_mcp.tools.modeling import (
    SetComponentTransformInput,
    register_modeling_tools,
)

_QUARTER_Y = [[0.0, 0.0, -1.0], [0.0, 1.0, 0.0], [1.0, 0.0, 0.0]]


@pytest.fixture
async def tools(mock_config: Any) -> tuple[MockSolidWorksAdapter, dict[str, Any]]:
    adapter = MockSolidWorksAdapter({})
    await adapter.connect()
    await adapter.create_assembly()
    mcp = FastMCP("component-transform")
    await register_modeling_tools(mcp, adapter, mock_config)
    return adapter, {tool.name: tool.fn for tool in await mcp.list_tools()}


async def test_a_rack_stacked_137_mm_up(tools) -> None:
    _adapter, tool = tools
    await tool["insert_component"]({"file_path": "C:/rack.sldasm"})
    await tool["insert_component"]({"file_path": "C:/rack.sldasm"})

    reply = await tool["set_component_transform"](
        {"component": "component-2", "origin_mm": [0, 137, 0]}
    )

    assert reply["status"] == "success", reply
    assert reply["placed"] is True
    assert reply["transform"]["origin_mm"] == [0.0, 137.0, 0.0]
    assert reply["message"] == "Placed component-2 at [0.0, 137.0, 0.0] mm"
    # Only the support level's note: nothing about mates.
    assert "mate" not in reply.get("warning", "")


async def test_a_quarter_turn_about_y_and_fixed(tools) -> None:
    _adapter, tool = tools
    await tool["insert_component"]({"file_path": "C:/stand-in.sldprt", "fixed": False})

    reply = await tool["set_component_transform"](
        {
            "component": "component-1",
            "origin_mm": [10, 20, 30],
            "rotation_deg": [0, 90, 0],
            "fixed": True,
        }
    )

    assert reply["transform"]["rotation"][0] == pytest.approx([0.0, 0.0, -1.0])
    assert reply["fixed"] is True
    assert reply["message"].endswith("(fixed)")


async def test_a_floating_first_insert(tools) -> None:
    _adapter, tool = tools

    reply = await tool["insert_component"](
        {"file_path": "C:/base.sldprt", "fixed": False}
    )

    assert reply["component"]["placement"]["fixed"] is False


@pytest.mark.parametrize(
    ("mates", "fragment"),
    [
        (2, "it has 2 mate(s), which likely hold it there"),
        (0, "isn't fixed by its mates"),
    ],
)
async def test_a_component_solidworks_keeps_is_a_warning(
    tools, mates, fragment
) -> None:
    adapter, tool = tools
    adapter.set_component_transform = AsyncMock(  # type: ignore[method-assign]
        return_value=AdapterResult(
            status=AdapterResultStatus.SUCCESS,
            data={
                "placed": False,
                "fixed": False,
                "mates": mates,
                "origin_mm": [0.0, 0.0, 0.0],
                "rotation": _QUARTER_Y,
            },
        )
    )

    reply = await tool["set_component_transform"](
        {"component": "latch-1", "origin_mm": [0, 5, 0]}
    )

    assert reply["status"] == "success"
    assert reply["placed"] is False
    assert reply["message"] == "latch-1 did not move where asked"
    assert fragment in reply["warning"]


async def test_an_unknown_component_is_not_found(tools) -> None:
    _adapter, tool = tools
    await tool["insert_component"]({"file_path": "C:/a.sldprt"})

    reply = await tool["set_component_transform"](
        {"component": "ghost-1", "origin_mm": [0, 0, 0]}
    )

    assert reply["status"] == "error"
    assert reply["error_type"] == "not_found"


@pytest.mark.parametrize(
    ("arguments", "fragment"),
    [
        ({"rotation_deg": [0, 90, 0], "matrix": _QUARTER_Y}, "not both"),
        ({"matrix": [[2, 0, 0], [0, 1, 0], [0, 0, 1]]}, "orthonormal"),
        ({"matrix": [[1, 0, 0], [0, 1, 0], [0, 0, -1]]}, "mirror"),
        ({"component": " "}, "component is required"),
        ({"origin_mm": [1, 2]}, "at least 3"),
    ],
)
async def test_bad_placements_are_invalid_input(tools, arguments, fragment) -> None:
    _adapter, tool = tools

    reply = await tool["set_component_transform"]({"component": "a-1", **arguments})

    assert reply["error_type"] == "invalid_input"
    assert fragment in reply["message"]


def test_the_rotation_rows_come_from_degrees_a_matrix_or_nothing() -> None:
    by_degrees = SetComponentTransformInput(component="a-1", rotation_deg=[0, 90, 0])
    by_matrix = SetComponentTransformInput(component="a-1", matrix=_QUARTER_Y)
    kept = SetComponentTransformInput(component="a-1")

    assert by_degrees.rotation_rows()[0] == pytest.approx([0.0, 0.0, -1.0])
    assert by_matrix.rotation_rows() == _QUARTER_Y
    assert kept.rotation_rows() is None
