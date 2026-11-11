"""The dimension tools say each value's unit: mm, degrees, or a count."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastmcp import FastMCP

from solidworks_mcp.adapters.base import AdapterResult, AdapterResultStatus
from solidworks_mcp.adapters.mock_adapter import MockSolidWorksAdapter
from solidworks_mcp.tools.modeling import _with_units, register_modeling_tools


async def _tools(adapter: Any, config: Any) -> dict[str, Any]:
    mcp = FastMCP("dimensions")
    await register_modeling_tools(mcp, adapter, config)
    return {t.name: t.fn for t in await mcp.list_tools()}


def _ok(data: dict[str, Any]) -> AdapterResult[Any]:
    return AdapterResult(status=AdapterResultStatus.SUCCESS, data=data)


@pytest.mark.parametrize(
    ("value", "units", "text"),
    [(12.5, "mm", "12.5 mm"), (180.0, "deg", "180 deg"), (2.0, "count", "2 (count)")],
)
def test_values_are_shown_with_their_unit(value: float, units: str, text: str) -> None:
    assert _with_units(value, units) == text
    assert _with_units("n/a", "mm") == "n/a mm"


async def test_setting_a_pattern_count_says_it_is_a_count(mock_config: Any) -> None:
    adapter = MockSolidWorksAdapter({})
    adapter.set_dimension = AsyncMock(  # type: ignore[method-assign]
        return_value=_ok(
            {"old_value": 6.0, "new_value": 2.0, "units": "count", "kind": "count"}
        )
    )
    tools = await _tools(adapter, mock_config)

    result = await tools["set_dimension"]({"name": "D1@CirPattern1", "value": 2})

    assert result["status"] == "success", result
    assert result["message"] == "Set dimension D1@CirPattern1 = 2 (count)"
    assert result["dimension_update"] == {
        "name": "D1@CirPattern1",
        "old_value": 6.0,
        "new_value": 2.0,
        "units": "count",
        "kind": "count",
    }
    adapter.set_dimension.assert_awaited_once_with("D1@CirPattern1", 2.0)


async def test_reading_an_angle_gives_degrees(mock_config: Any) -> None:
    adapter = MockSolidWorksAdapter({})
    adapter.get_dimension = AsyncMock(  # type: ignore[method-assign]
        return_value=_ok({"value": 180.0, "units": "deg", "kind": "angle"})
    )
    tools = await _tools(adapter, mock_config)

    result = await tools["get_dimension"]({"name": "D2@CirPattern1"})

    assert result["message"] == "Dimension D2@CirPattern1 = 180 deg"
    assert result["dimension"]["kind"] == "angle"


async def test_the_mock_reports_lengths_and_the_old_value(mock_config: Any) -> None:
    adapter = MockSolidWorksAdapter({})
    tools = await _tools(adapter, mock_config)

    first = await tools["set_dimension"]({"name": "D9@Sketch1", "value": 12})
    second = await tools["set_dimension"]({"name": "D9@Sketch1", "value": 15})
    read = await tools["get_dimension"]({"name": "D9@Sketch1"})

    assert first["dimension_update"]["old_value"] is None
    assert second["dimension_update"]["old_value"] == 12
    assert second["message"] == "Set dimension D9@Sketch1 = 15 mm"
    assert read["dimension"] == {
        "name": "D9@Sketch1",
        "value": 15,
        "units": "mm",
        "kind": "length",
    }
