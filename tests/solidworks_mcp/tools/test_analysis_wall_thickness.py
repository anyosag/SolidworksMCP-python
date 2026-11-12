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

    result = await tool({"max_rays": 100, "exclude_boxes_mm": []})

    assert result["message"] == "No wall could be measured"
    adapter.check_wall_thickness.assert_awaited_once_with(0.8, 100, None)


#: The mock block spans 0..10 mm; this box holds its +x face's centre only.
_PLUS_X_FACE = [9, 0, 0, 11, 10, 10]


async def test_a_thin_region_can_be_excluded(setup: Any) -> None:
    _adapter, tool = setup

    result = await tool({"min_wall_mm": 12, "exclude_boxes_mm": [_PLUS_X_FACE]})

    data = result["data"]
    assert (data["below_minimum"], data["ok"]) == (5, False)
    assert (data["excluded"]["measured"], data["excluded"]["below_minimum"]) == (1, 1)
    assert data["excluded"]["thin_spots"][0]["at_mm"] == [10.0, 5.0, 5.0]
    assert result["message"] == (
        "Outside exclude_boxes_mm, the thinnest wall is 10 mm; 5 of 5 points are "
        "under 12 mm; 1 points under 12 mm inside the boxes are not counted"
    )


async def test_an_excluded_region_that_is_thick_enough(setup: Any) -> None:
    _adapter, tool = setup

    result = await tool({"exclude_boxes_mm": [_PLUS_X_FACE]})

    assert result["data"]["ok"] is True
    assert result["message"] == (
        "Outside exclude_boxes_mm, the thinnest wall is 10 mm; every point is at "
        "least 0.8 mm"
    )


async def test_every_point_excluded_gives_no_verdict(setup: Any) -> None:
    _adapter, tool = setup

    result = await tool({"min_wall_mm": 12, "exclude_boxes_mm": [[-1] * 3 + [11] * 3]})

    assert result["data"]["ok"] is None
    assert result["message"] == (
        "Every point measured is inside exclude_boxes_mm; 6 points under 12 mm "
        "inside the boxes are not counted"
    )


@pytest.mark.parametrize(
    "arguments",
    [
        {"min_wall_mm": 0},
        {"max_rays": 5},
        {"max_rays": 50000},
        {"exclude_boxes_mm": [[0, 0, 0, 1, 1]]},
        {"exclude_boxes_mm": [[0, 0, 0, 1, 1, 1, 1]]},
        {"exclude_boxes_mm": [[0, 0, 0, 1, 1, "top"]]},
        {"exclude_boxes_mm": [0, 0, 0, 1, 1, 1]},
    ],
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
