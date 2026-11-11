"""The ``check_wall_thickness`` tool, on the mock's 10 mm block."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastmcp import FastMCP

from solidworks_mcp.adapters.base import AdapterResult, AdapterResultStatus
from solidworks_mcp.adapters.mock_adapter import MockSolidWorksAdapter
from solidworks_mcp.tools.analysis import register_analysis_tools


@pytest.fixture
async def setup(mock_config: Any) -> tuple[MockSolidWorksAdapter, Any]:
    adapter = MockSolidWorksAdapter({})
    await adapter.connect()
    await adapter.create_part()
    mcp = FastMCP("wall-thickness")
    await register_analysis_tools(mcp, adapter, mock_config)
    tool = next(
        t.fn for t in await mcp.list_tools() if t.name == "check_wall_thickness"
    )
    return adapter, tool


async def test_every_wall_is_thick_enough(setup: Any) -> None:
    _adapter, tool = setup

    result = await tool()

    assert result["status"] == "success", result
    assert result["data"]["min_thickness_mm"] == 10.0
    assert result["message"] == "Thinnest wall 10 mm; every point is at least 0.8 mm"


async def test_thin_spots_are_counted(setup: Any) -> None:
    _adapter, tool = setup

    result = await tool({"min_wall_mm": 12})

    assert result["data"]["below_minimum"] == 6
    assert result["message"] == "Thinnest wall 10 mm; 6 of 6 points are under 12 mm"


async def test_nothing_measured_says_so(setup: Any) -> None:
    adapter, tool = setup
    adapter.check_wall_thickness = AsyncMock(  # type: ignore[method-assign]
        return_value=AdapterResult(
            status=AdapterResultStatus.SUCCESS, data={"min_thickness_mm": None}
        )
    )

    result = await tool({"max_rays": 100})

    assert result["message"] == "No wall could be measured"
    adapter.check_wall_thickness.assert_awaited_once_with(0.8, 100)


@pytest.mark.parametrize(
    "arguments", [{"min_wall_mm": 0}, {"max_rays": 5}, {"max_rays": 50000}]
)
async def test_out_of_range_inputs_are_refused(setup: Any, arguments: dict) -> None:
    _adapter, tool = setup

    result = await tool(arguments)

    assert result["error_type"] == "invalid_input"


async def test_a_drawing_is_refused() -> None:
    adapter = MockSolidWorksAdapter({})
    await adapter.connect()
    assert (await adapter.check_wall_thickness()).error == "No active model"
    await adapter.create_assembly()
    assert (await adapter.check_wall_thickness()).error == (
        "check_wall_thickness needs an active part document (active document is "
        "assembly)."
    )
    part = MockSolidWorksAdapter({})
    await part.connect()
    await part.create_part()
    capped = await part.check_wall_thickness(1.0, max_rays=2)
    assert (capped.data or {})["samples"] == 2
