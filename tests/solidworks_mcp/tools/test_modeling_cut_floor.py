"""``create_cut_extrude`` warns when a blind cut's depth was mostly outside the part.

From the Cellvis dish rack: a cut sketched on an offset plane removed a
1.13 mm³ sliver where 9.05 mm³ was meant, and reported success.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastmcp import FastMCP

from solidworks_mcp.adapters.base import (
    AdapterResult,
    AdapterResultStatus,
    SolidWorksFeature,
)
from solidworks_mcp.adapters.mock_adapter import MockSolidWorksAdapter
from solidworks_mcp.tools.modeling import register_modeling_tools


def _summary(volume: float) -> AdapterResult[dict[str, Any]]:
    return AdapterResult(
        status=AdapterResultStatus.SUCCESS,
        data={"volume_mm3": volume, "solid_body_count": 1},
    )


async def _cut_tool(removed: float, floor: float | None, config: Any) -> Any:
    adapter = MockSolidWorksAdapter({})
    await adapter.connect()
    await adapter.create_part()
    adapter.get_model_geometry_summary = AsyncMock(  # type: ignore[method-assign]
        side_effect=[_summary(1000.0), _summary(1000.0 - removed)]
    )
    feature = SolidWorksFeature(
        name="Cut-Extrude1",
        type="Cut-Extrude",
        parameters={"floor_area_mm2": floor, "sketch_name": "Sketch3"},
    )
    adapter.create_cut_extrude = AsyncMock(  # type: ignore[method-assign]
        return_value=AdapterResult(status=AdapterResultStatus.SUCCESS, data=feature)
    )
    mcp = FastMCP("cut")
    await register_modeling_tools(mcp, adapter, config)
    return next(t.fn for t in await mcp.list_tools() if t.name == "create_cut_extrude")


async def test_a_sliver_cut_is_warned_about(mock_config: Any) -> None:
    cut = await _cut_tool(removed=1.13, floor=4.525, config=mock_config)

    reply = await cut({"depth": 2.0, "sketch_name": "Sketch3"})

    assert reply["status"] == "success", reply
    assert reply["cut_extrude"]["floor_area_mm2"] == 4.525
    assert "far less than its floor area times its depth" in reply["warning"]


@pytest.mark.parametrize(
    ("removed", "floor", "arguments"),
    [
        (9.05, 4.525, {}),  # removed what it should
        (1.13, None, {}),  # floor unknown
        (1.13, 4.525, {"end_condition": "ThroughAll"}),
    ],
)
async def test_otherwise_no_warning(
    mock_config: Any, removed: float, floor: float | None, arguments: dict[str, Any]
) -> None:
    cut = await _cut_tool(removed, floor, mock_config)

    reply = await cut({"depth": 2.0, "sketch_name": "Sketch3", **arguments})

    assert reply["status"] == "success", reply
    assert "far less" not in (reply.get("warning") or "")
