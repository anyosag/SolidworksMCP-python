"""The ``check_printability`` tool."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastmcp import FastMCP

from solidworks_mcp.adapters.base import AdapterResult, AdapterResultStatus
from solidworks_mcp.adapters.mock_adapter import MockSolidWorksAdapter
from solidworks_mcp.tools.analysis import register_analysis_tools


@pytest.fixture
async def tools(mock_config: Any) -> tuple[MockSolidWorksAdapter, dict[str, Any]]:
    adapter = MockSolidWorksAdapter({})
    await adapter.connect()
    await adapter.create_part()
    mcp = FastMCP("printability")
    await register_analysis_tools(mcp, adapter, mock_config)
    return adapter, {tool.name: tool.fn for tool in await mcp.list_tools()}


def _answer(adapter: MockSolidWorksAdapter, **data: Any) -> None:
    adapter.check_printability = AsyncMock(  # type: ignore[method-assign]
        return_value=AdapterResult(status=AdapterResultStatus.SUCCESS, data=data)
    )


async def test_the_mock_part_is_checked(tools) -> None:
    _adapter, tool = tools

    reply = await tool["check_printability"]({"build_direction": "z"})

    assert reply["status"] == "success", reply
    assert reply["data"]["triangles"] == 4


async def test_a_part_that_prints_as_it_is(tools) -> None:
    adapter, tool = tools
    _answer(adapter, ok=True, down_facing={"needs_support_mm2": 0.0})

    reply = await tool["check_printability"]({"build_direction": [0, 1, 0]})

    assert reply["message"] == "Prints in this orientation without supports"


async def test_what_needs_attention_is_summed_up(tools) -> None:
    adapter, tool = tools
    _answer(
        adapter,
        ok=False,
        down_facing={"needs_support_mm2": 200.0},
        islands={"count": 1, "items": []},
        bridges={"count": 0, "items": []},
        suction_cups={"count": 2, "items": []},
    )

    reply = await tool["check_printability"](
        {"build_direction": "-y", "support_angle_deg": 30, "min_bridge_mm": 3}
    )

    assert reply["message"] == (
        "In this orientation: 1 island(s), 2 suction cup(s), 200 mm² needing supports"
    )
    adapter.check_printability.assert_awaited_once_with("-y", 30.0, 3.0)


@pytest.mark.parametrize(
    ("arguments", "fragment"),
    [
        ({"build_direction": "up"}, "build_direction must be"),
        ({"build_direction": [0, 0, 0]}, "zero vector"),
        ({"build_direction": "z", "support_angle_deg": 90}, "less than 90"),
    ],
)
async def test_bad_inputs_are_invalid(tools, arguments, fragment) -> None:
    _adapter, tool = tools

    reply = await tool["check_printability"](arguments)

    assert reply["error_type"] == "invalid_input"
    assert fragment in reply["message"]


async def test_an_assembly_is_refused(tools) -> None:
    adapter, tool = tools
    await adapter.create_assembly()

    reply = await tool["check_printability"]({"build_direction": "z"})

    assert reply["status"] == "error"
    assert "requires an active part document" in reply["message"]
